from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_claim_lineage.py"
evaluate_claim_lineage = cast(
    Callable[[], dict[str, object]],
    runpy.run_path(str(_SCRIPT))["evaluate_claim_lineage"],
)


def test_claim_lineage_evaluation_measures_quality_and_safety_deterministically() -> None:
    first = evaluate_claim_lineage()
    second = evaluate_claim_lineage()

    assert first == second
    assert first == {
        "schema_version": "minerva.claim-lineage-evaluation.v1",
        "algorithm": "structural-ledger-lineage",
        "algorithm_version": "1",
        "node_precision_ppm": 1_000_000,
        "node_recall_ppm": 1_000_000,
        "payload_link_precision_ppm": 1_000_000,
        "payload_link_recall_ppm": 1_000_000,
        "edge_precision_ppm": 1_000_000,
        "edge_recall_ppm": 1_000_000,
        "citation_byte_accuracy_ppm": 1_000_000,
        "determinism": True,
        "mission_and_claim_isolation": True,
        "unauthorized_mutation_count": 0,
        "fixture_mission_count": 2,
        "fixture_claim_count": 3,
        "expected_node_count": 14,
        "result_node_count": 14,
        "expected_edge_count": 20,
        "result_edge_count": 20,
        "expected_citation_count": 2,
        "result_evidence_node_count": 2,
        "accurate_citation_count": 2,
    }


def test_claim_lineage_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_claim_lineage.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_claim_lineage()
    assert result.stdout.endswith("\n")
