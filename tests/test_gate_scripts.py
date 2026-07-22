from __future__ import annotations

import ast
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


def _scan(source: str) -> set[str]:
    visitor = static_security_check.PolicyVisitor(Path("synthetic_policy_probe.py"))
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


def test_loaded_gate_scripts_are_modules() -> None:
    assert all(
        isinstance(module, ModuleType)
        for module in (installed_smoke, static_security_check, verify_dist)
    )
