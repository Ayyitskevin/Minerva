from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_claim_review.py"
evaluate_claim_review = cast(
    Callable[[], dict[str, object]],
    runpy.run_path(str(_SCRIPT))["evaluate_claim_review"],
)


def test_claim_review_evaluation_measures_quality_and_safety_deterministically() -> None:
    first = evaluate_claim_review()
    second = evaluate_claim_review()

    assert first == second
    assert first == {
        "schema_version": "minerva.claim-review-evaluation.v1",
        "algorithm": "structural-ledger-review",
        "algorithm_version": "1",
        "gap_classification_accuracy_ppm": 1_000_000,
        "status_validity_accuracy_ppm": 1_000_000,
        "impact_edge_precision_ppm": 1_000_000,
        "impact_edge_recall_ppm": 1_000_000,
        "determinism": True,
        "mission_isolation": True,
        "unauthorized_mutation_count": 0,
        "fixture_mission_count": 2,
        "fixture_claim_count": 4,
        "review_count": 3,
        "gap_label_count": 12,
        "correct_gap_label_count": 12,
        "status_case_count": 3,
        "correct_status_case_count": 3,
        "predicted_impact_edge_count": 6,
        "relevant_impact_edge_count": 6,
        "correct_impact_edge_count": 6,
    }


def test_claim_review_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_claim_review.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_claim_review()
    assert result.stdout.endswith("\n")
