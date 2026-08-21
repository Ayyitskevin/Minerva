from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_lens_evidence_adoption.py"
evaluate_lens_evidence_adoption = cast(
    Callable[[], dict[str, object]],
    runpy.run_path(str(_SCRIPT))["evaluate_lens_evidence_adoption"],
)


def test_lens_evidence_adoption_evaluation_is_exact_and_deterministic() -> None:
    first = evaluate_lens_evidence_adoption()
    second = evaluate_lens_evidence_adoption()

    assert first == second
    assert first == {
        "schema_version": "minerva.lens-evidence-adoption-evaluation.v1",
        "algorithm": "verified-current-replay-single-candidate",
        "algorithm_version": "1",
        "successful_adoption_count": 1,
        "exact_candidate_binding": True,
        "utf8_byte_span_accuracy_ppm": 1_000_000,
        "explicit_stance_preserved": True,
        "evidence_creation_and_adoption_audits_bound": True,
        "atomic_authorized_state_delta": True,
        "atomic_rollback_on_second_audit_failure": True,
        "duplicate_refusal": True,
        "corpus_drift_refusal": True,
        "mission_isolation_refusal": True,
        "semantic_non_effects_declared": True,
        "deep_integrity": True,
        "schema_version_unchanged": True,
        "provider_invocation_count": 0,
        "network_invocation_count": 0,
        "unauthorized_mutation_count": 0,
        "fixture_mission_count": 2,
        "fixture_claim_count": 2,
        "fixture_snapshot_count": 3,
    }
    assert not any("truth" in key or "quality" in key for key in first)


def test_lens_evidence_adoption_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_lens_evidence_adoption.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_lens_evidence_adoption()
    assert result.stdout.endswith("\n")
