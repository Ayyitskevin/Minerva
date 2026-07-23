"""Install Minerva's wheel into a temporary venv and smoke-test it off-checkout."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

PROVIDER_EXTRA_CASES = (
    ("ai-openai", ("openai",)),
    ("ai-anthropic", ("anthropic",)),
    ("ai", ("anthropic", "openai")),
)


class SmokeError(RuntimeError):
    """Raised when the installed artifact fails its smoke contract."""


def _run_checked(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(  # noqa: S603 - executable paths are resolved inside the temp venv.
        list(command),
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if len(detail) > 2_000:
            detail = f"{detail[:2_000]}..."
        raise SmokeError(f"command failed with exit {result.returncode}: {detail}")
    return result.stdout.strip()


def _json_object(document: str, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(document)
    except json.JSONDecodeError as error:
        raise SmokeError(f"{label} returned malformed JSON") from error
    if not isinstance(value, dict):
        raise SmokeError(f"{label} did not return a JSON object")
    return value


def _single_wheel(dist_directory: Path) -> Path:
    resolved_directory = dist_directory.resolve()
    if not resolved_directory.is_dir():
        raise SmokeError(f"distribution directory does not exist: {resolved_directory}")
    wheels = sorted(resolved_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise SmokeError(f"expected exactly one wheel, found {len(wheels)}")
    return wheels[0].resolve(strict=True)


def _uv_tooling(checkout: Path) -> tuple[Path, Path]:
    uv_command = shutil.which("uv")
    if uv_command is None:
        raise SmokeError("uv is required to provision the locked installed-smoke environment")
    lockfile = checkout / "uv.lock"
    if not lockfile.is_file():
        raise SmokeError(f"installed smoke requires the project lockfile: {lockfile}")
    return Path(uv_command).resolve(strict=True), lockfile


def _venv_executable(venv_root: Path, name: str) -> Path:
    bin_directory = venv_root / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    executable = bin_directory / f"{name}{suffix}"
    if not executable.is_file():
        raise SmokeError(f"installed environment is missing expected executable {name!r}")
    return executable.resolve()


def _provision_locked_environment(
    *,
    uv_command: Path,
    checkout: Path,
    wheel: Path,
    venv_root: Path,
    cwd: Path,
    environment: dict[str, str],
    extra: str | None,
) -> Path:
    venv.EnvBuilder(with_pip=False, system_site_packages=False, clear=True).create(venv_root)
    python = _venv_executable(venv_root, "python")
    requirements = venv_root.with_name(f"{venv_root.name}-requirements.txt")
    extra_arguments = [] if extra is None else ["--extra", extra]

    _run_checked(
        [
            str(uv_command),
            "export",
            "--project",
            str(checkout),
            "--frozen",
            *extra_arguments,
            "--no-emit-project",
            "--no-hashes",
            "--output-file",
            str(requirements),
            "--offline",
        ],
        cwd=cwd,
        environment=environment,
    )
    if not requirements.is_file() or not requirements.read_text(encoding="utf-8").strip():
        raise SmokeError("uv exported an empty locked dependency set")

    try:
        _run_checked(
            [
                str(uv_command),
                "pip",
                "install",
                "--python",
                str(python),
                "--requirement",
                str(requirements),
                "--offline",
            ],
            cwd=cwd,
            environment=environment,
        )
    except SmokeError as pip_error:
        sync_environment = environment.copy()
        sync_environment["UV_PROJECT_ENVIRONMENT"] = str(venv_root)
        try:
            _run_checked(
                [
                    str(uv_command),
                    "sync",
                    "--project",
                    str(checkout),
                    "--frozen",
                    *extra_arguments,
                    "--no-install-project",
                    "--offline",
                ],
                cwd=cwd,
                environment=sync_environment,
            )
        except SmokeError as sync_error:
            extra_label = "base dependencies" if extra is None else f"extra {extra!r}"
            raise SmokeError(
                f"unable to provision locked {extra_label} offline; "
                f"export install failed: {pip_error}; lock sync failed: {sync_error}"
            ) from sync_error

    _run_checked(
        [
            str(uv_command),
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--offline",
            str(wheel),
        ],
        cwd=cwd,
        environment=environment,
    )
    _run_checked(
        [str(uv_command), "pip", "check", "--python", str(python)],
        cwd=cwd,
        environment=environment,
    )
    return python


def smoke_wheel(dist_directory: Path) -> Path:
    """Install and exercise the sole wheel in *dist_directory* outside the checkout."""
    wheel = _single_wheel(dist_directory)
    checkout = Path(__file__).resolve().parents[1]
    uv_command, _lockfile = _uv_tooling(checkout)

    with tempfile.TemporaryDirectory(prefix="minerva-installed-smoke-") as temporary:
        temporary_root = Path(temporary).resolve()
        smoke_directory = temporary_root / "outside-checkout"
        smoke_directory.mkdir()
        if smoke_directory.is_relative_to(checkout):
            raise SmokeError("temporary smoke directory unexpectedly resides inside the checkout")

        environment = os.environ.copy()
        for variable in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "MINERVA_AI_MODEL",
            "MINERVA_AI_PROVIDER",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "PYTHONPATH",
        ):
            environment.pop(variable, None)
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "UV_NO_PROGRESS": "1",
            }
        )

        venv_root = temporary_root / "venv-base"
        python = _provision_locked_environment(
            uv_command=uv_command,
            checkout=checkout,
            wheel=wheel,
            venv_root=venv_root,
            cwd=smoke_directory,
            environment=environment,
            extra=None,
        )

        probe = (
            "from importlib.metadata import version; "
            "from pathlib import Path; "
            "import minerva; "
            "print(version('minerva-research')); "
            "print(Path(minerva.__file__).resolve())"
        )
        probe_output = _run_checked(
            [str(python), "-c", probe], cwd=smoke_directory, environment=environment
        )
        output_lines = probe_output.splitlines()
        if len(output_lines) != 2 or not output_lines[0]:
            raise SmokeError("installed package probe returned an unexpected result")
        imported_path = Path(output_lines[1]).resolve()
        if not imported_path.is_relative_to(venv_root):
            raise SmokeError("package import did not resolve to the temporary wheel installation")
        sdk_probe = """
from importlib.util import find_spec

unexpected = [name for name in ("anthropic", "openai") if find_spec(name) is not None]
if unexpected:
    raise RuntimeError(f"provider SDKs leaked into base installation: {unexpected}")
""".strip()
        _run_checked([str(python), "-c", sdk_probe], cwd=smoke_directory, environment=environment)

        minerva_command = _venv_executable(venv_root, "minerva")
        demo_command = _venv_executable(venv_root, "minerva-demo")
        for command in (minerva_command, demo_command):
            _run_checked([str(command), "--help"], cwd=smoke_directory, environment=environment)

        demo_database = smoke_directory / "demo.db"
        export_directory = smoke_directory / "demo-export"
        demo = _json_object(
            _run_checked(
                [
                    str(demo_command),
                    "--db",
                    str(demo_database),
                    "--export-dir",
                    str(export_directory),
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed demo",
        )
        if demo.get("status") != "demo_created":
            raise SmokeError("installed demo did not report successful creation")
        mission_id = demo.get("mission_id")
        if not isinstance(mission_id, str):
            raise SmokeError("installed demo did not return a mission identifier")
        claim_ids = demo.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids or not isinstance(claim_ids[0], str):
            raise SmokeError("installed demo did not return a claim identifier")
        claim_id = claim_ids[0]
        assistant_preview = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "assist",
                    "finding-candidates",
                    "--db",
                    str(demo_database),
                    "--claim",
                    claim_id,
                    "--provider",
                    "openai",
                    "--model",
                    "test-model-1",
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed assistant preview",
        )
        if assistant_preview.get("mode") != "preview":
            raise SmokeError("installed assistant did not return preview mode")
        if assistant_preview.get("network_called") is not False:
            raise SmokeError("installed assistant preview reported a network call")
        preview_document = assistant_preview.get("preview")
        if not isinstance(preview_document, dict):
            raise SmokeError("installed assistant preview omitted its request document")
        request_sha256 = preview_document.get("request_sha256")
        if not isinstance(request_sha256, str) or len(request_sha256) != 64:
            raise SmokeError("installed assistant preview omitted its request digest")

        preview = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "brief",
                    "preview",
                    "--db",
                    str(demo_database),
                    "--mission",
                    mission_id,
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed brief preview",
        )
        markdown_path = export_directory / "research-brief.md"
        json_path = export_directory / "research-brief.json"
        markdown = markdown_path.read_bytes()
        json_bytes = json_path.read_bytes()
        brief = _json_object(json_bytes.decode("utf-8", errors="strict"), label="brief export")
        if brief.get("export_digest") != demo.get("export_digest"):
            raise SmokeError("installed demo and JSON export digests disagree")
        if preview.get("markdown_sha256") != sha256(markdown).hexdigest():
            raise SmokeError("installed Markdown export digest is invalid")
        if preview.get("json_sha256") != sha256(json_bytes).hexdigest():
            raise SmokeError("installed JSON export digest is invalid")
        if preview.get("export_digest") != demo.get("export_digest"):
            raise SmokeError("installed preview and demo export digests disagree")

        doctor = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "doctor",
                    "--db",
                    str(demo_database),
                    "--deep",
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed doctor",
        )
        doctor_report = doctor.get("doctor")
        if not isinstance(doctor_report, dict) or doctor_report.get("ok") is not True:
            raise SmokeError("installed deep doctor did not report a healthy database")

        web_probe = """
import asyncio
import json
import sys
from pathlib import Path

from minerva.web.app import create_app

async def get(app, path):
    messages = []
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if request_delivered:
            return {"type": "http.disconnect"}
        request_delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )
    status = next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, body

database = Path(sys.argv[1])
mission_id = sys.argv[2]
claim_id = sys.argv[3]
routes = (
    "/readyz",
    "/missions",
    f"/missions/{mission_id}",
    f"/claims/{claim_id}",
    f"/missions/{mission_id}/brief",
    "/static/style.css",
)
app = create_app(database, testing=True)

async def main():
    for route in routes:
        status, body = await get(app, route)
        if status != 200:
            raise RuntimeError(f"installed web route {route} returned {status}")
        if route == "/static/style.css" and not body:
            raise RuntimeError("installed static CSS is empty")

    capability_status, capability_body = await get(app, "/api/v1/capabilities")
    if capability_status != 200:
        raise RuntimeError(
            f"installed capability manifest returned {capability_status}"
        )
    try:
        capabilities = json.loads(capability_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("installed capability manifest returned malformed JSON") from error
    if not isinstance(capabilities, dict):
        raise RuntimeError("installed capability manifest did not return an object")

    advertised = capabilities.get("capabilities")
    unavailable = capabilities.get("unavailable")
    limits = capabilities.get("limits")
    if (
        capabilities.get("schema_version") != "minerva.capabilities.v2"
        or capabilities.get("api_version") != "v1"
        or capabilities.get("local_only") is not False
        or capabilities.get("loopback_only") is not True
        or capabilities.get("external_egress") != "disabled_by_default_cli_only"
        or capabilities.get("supported_external_providers") != ["openai", "anthropic"]
        or capabilities.get("identity_boundary") != "local_os_user"
        or capabilities.get("citation_scheme") != "utf8-byte-offset-v1"
        or capabilities.get("brief_schema_version") != "minerva.research-brief.v2"
        or not isinstance(advertised, list)
        or "brief.export.markdown_json" not in advertised
        or "research.packet.v2.canonical" not in advertised
        or "assist.finding_candidates.preview.cli" not in advertised
        or "assist.finding_candidates.invoke.cli.byok.optional" not in advertised
        or not isinstance(unavailable, list)
        or "network.fetch" not in unavailable
        or "model.invoke.api" not in unavailable
        or "model.invoke.web" not in unavailable
        or "model.output.auto_adopt" not in unavailable
        or "provider.credential.persist" not in unavailable
        or "sibling_artifact_exchange" not in unavailable
        or "shared_run_envelope" not in unavailable
        or "orchestration" not in unavailable
        or "experiment_execution" not in unavailable
        or "approval_authority" not in unavailable
        or not isinstance(limits, dict)
        or limits.get("assistant_context_bytes") != 65_536
        or limits.get("assistant_evidence_cards") != 50
        or limits.get("assistant_candidates") != 3
    ):
        raise RuntimeError("installed capability manifest is incomplete or untruthful")

asyncio.run(main())
""".strip()
        _run_checked(
            [str(python), "-c", web_probe, str(demo_database), mission_id, claim_id],
            cwd=smoke_directory,
            environment=environment,
        )

        provider_probe = """
import socket
import sys
from importlib.util import find_spec

def deny_network(*_args, **_kwargs):
    raise RuntimeError("provider adapter construction attempted network access")

socket.create_connection = deny_network
socket.getaddrinfo = deny_network

from minerva.assist.models import ModelProvider
from minerva.integrations.ai import candidate_provider

expected = frozenset(sys.argv[1:])
for module in ("anthropic", "openai"):
    present = find_spec(module) is not None
    if present != (module in expected):
        raise RuntimeError(
            f"provider SDK presence mismatch for {module}: present={present}, expected={expected}"
        )

for name in sorted(expected):
    provider = ModelProvider(name)
    adapter = candidate_provider(provider)
    if adapter.provider is not provider:
        raise RuntimeError(f"constructed adapter reports the wrong provider for {name}")
""".strip()
        for extra, expected_providers in PROVIDER_EXTRA_CASES:
            extra_python = _provision_locked_environment(
                uv_command=uv_command,
                checkout=checkout,
                wheel=wheel,
                venv_root=temporary_root / f"venv-{extra}",
                cwd=smoke_directory,
                environment=environment,
                extra=extra,
            )
            _run_checked(
                [str(extra_python), "-c", provider_probe, *expected_providers],
                cwd=smoke_directory,
                environment=environment,
            )

    return wheel


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", type=Path, help="directory containing one wheel")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        wheel = smoke_wheel(args.dist_directory)
    except (OSError, SmokeError) as exc:
        print(f"installed-wheel smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"installed-wheel smoke passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
