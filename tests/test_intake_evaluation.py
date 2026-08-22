from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_intake.py"
evaluate_intake = cast(
    Callable[[], dict[str, object]],
    runpy.run_path(str(_SCRIPT))["evaluate_intake"],
)


def test_intake_evaluation_is_exact_deterministic_and_realistic() -> None:
    first = evaluate_intake()
    second = evaluate_intake()

    assert first == second
    assert first["schema_version"] == "minerva.evidence-intake-evaluation.v1"
    assert first["realistic_case_count"] == 20
    assert first["successful_source_to_evidence_count"] == 20
    for metric in (
        "exact_utf8_span_accuracy_ppm",
        "candidate_count_accuracy_ppm",
        "source_digest_binding_ppm",
        "preview_read_only_ppm",
        "creation_audit_binding_ppm",
        "stale_replay_refusal_ppm",
        "duplicate_refusal_ppm",
    ):
        assert first[metric] == 1_000_000
    assert first["operator_steps_source_to_evidence"] == 4
    assert first["schema_version_unchanged"] is True
    assert first["deep_integrity"] is True
    assert first["provider_invocation_count"] == 0
    assert first["network_invocation_count"] == 0


def test_intake_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_intake.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_intake()
    assert result.stdout.endswith("\n")
