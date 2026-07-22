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

        venv_root = temporary_root / "venv"
        venv.EnvBuilder(with_pip=False, system_site_packages=False, clear=True).create(venv_root)
        python = _venv_executable(venv_root, "python")
        requirements = temporary_root / "locked-requirements.txt"

        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "UV_NO_PROGRESS": "1",
            }
        )

        _run_checked(
            [
                str(uv_command),
                "export",
                "--project",
                str(checkout),
                "--frozen",
                "--extra",
                "dev",
                "--no-emit-project",
                "--no-hashes",
                "--output-file",
                str(requirements),
                "--offline",
            ],
            cwd=smoke_directory,
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
                cwd=smoke_directory,
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
                        "--extra",
                        "dev",
                        "--no-install-project",
                        "--offline",
                    ],
                    cwd=smoke_directory,
                    environment=sync_environment,
                )
            except SmokeError as sync_error:
                raise SmokeError(
                    "unable to provision locked dependencies offline after `uv sync --frozen "
                    f"--extra dev`; export install failed: {pip_error}; "
                    f"lock sync failed: {sync_error}"
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
            cwd=smoke_directory,
            environment=environment,
        )
        _run_checked(
            [str(uv_command), "pip", "check", "--python", str(python)],
            cwd=smoke_directory,
            environment=environment,
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
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from minerva.web.app import create_app

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
with TestClient(create_app(database, testing=True)) as client:
    for route in routes:
        response = client.get(route)
        if response.status_code != 200:
            raise RuntimeError(f"installed web route {route} returned {response.status_code}")
        if route == "/static/style.css" and not response.content:
            raise RuntimeError("installed static CSS is empty")
""".strip()
        _run_checked(
            [str(python), "-c", web_probe, str(demo_database), mission_id, claim_id],
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
