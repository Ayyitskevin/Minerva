from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_review_dossier.py"
evaluate_review_dossier = cast(
    Callable[[], dict[str, object]],
    runpy.run_path(str(_SCRIPT))["evaluate_review_dossier"],
)


def test_review_dossier_evaluation_is_exact_deterministic_and_read_only() -> None:
    first = evaluate_review_dossier()
    second = evaluate_review_dossier()

    assert first == second
    assert first == {
        "schema_version": "minerva.review-dossier-evaluation.v1",
        "algorithm": "current-snapshot-review-composition",
        "algorithm_version": "1",
        "component_order_valid": True,
        "component_receipt_links_valid": True,
        "nested_component_digests_valid": True,
        "component_set_digest_valid": True,
        "dossier_receipt_digest_valid": True,
        "crosschecks_valid": True,
        "citation_byte_accuracy_ppm": 1_000_000,
        "lens_candidate_byte_accuracy_ppm": 1_000_000,
        "determinism": True,
        "mission_isolation": True,
        "lens_truncation_disclosed": True,
        "structural_completion_disclosed": True,
        "lens_candidate_boundary_preserved": True,
        "unauthorized_mutation_count": 0,
        "fixture_mission_count": 2,
        "fixture_claim_count": 3,
        "component_count": 5,
        "crosscheck_count": 11,
        "passing_crosscheck_count": 11,
        "expected_citation_count": 2,
        "accurate_citation_count": 2,
        "lens_matching_candidate_count": 3,
        "lens_result_count": 1,
        "lens_omitted_candidate_count": 2,
    }


def test_review_dossier_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_review_dossier.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_review_dossier()
    assert result.stdout.endswith("\n")
