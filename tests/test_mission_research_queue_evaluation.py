from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_mission_research_queue.py"
evaluate_mission_research_queue = cast(
    Callable[[], dict[str, object]],
    runpy.run_path(str(_SCRIPT))["evaluate_mission_research_queue"],
)


def test_mission_research_queue_evaluation_is_exact_deterministic_and_read_only() -> None:
    first = evaluate_mission_research_queue()
    second = evaluate_mission_research_queue()

    assert first == second
    assert first == {
        "schema_version": "minerva.mission-research-queue-evaluation.v1",
        "algorithm": "claim-review-cue-aggregation",
        "algorithm_version": "1",
        "claim_precision_ppm": 1_000_000,
        "claim_recall_ppm": 1_000_000,
        "entry_precision_ppm": 1_000_000,
        "entry_recall_ppm": 1_000_000,
        "reason_code_classification_accuracy_ppm": 1_000_000,
        "reason_code_catalog_coverage_ppm": 1_000_000,
        "determinism": True,
        "canonical_ordering": True,
        "claim_set_digest_valid": True,
        "claim_review_set_digest_valid": True,
        "item_set_digest_valid": True,
        "queue_receipt_digest_valid": True,
        "mission_isolation": True,
        "unauthorized_mutation_count": 0,
        "fixture_mission_count": 2,
        "fixture_claim_count": 4,
        "expected_claim_count": 3,
        "result_claim_count": 3,
        "expected_entry_count": 15,
        "result_entry_count": 15,
        "reason_code_label_count": 42,
        "correct_reason_code_label_count": 42,
        "expected_reason_code_count": 14,
        "covered_reason_code_count": 14,
    }


def test_mission_research_queue_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_mission_research_queue.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_mission_research_queue()
    assert result.stdout.endswith("\n")
