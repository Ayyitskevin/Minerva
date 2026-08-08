from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_lens.py"
evaluate_lens = cast(Callable[[], dict[str, object]], runpy.run_path(str(_SCRIPT))["evaluate_lens"])


def test_lens_evaluation_measures_quality_and_safety_deterministically() -> None:
    first = evaluate_lens()
    second = evaluate_lens()

    assert first == second
    assert first == {
        "schema_version": "minerva.lens-evaluation.v1",
        "algorithm": "bounded-unicode-line-lexical",
        "algorithm_version": "1",
        "k": 3,
        "precision_at_k_ppm": 750_000,
        "recall_at_k_ppm": 1_000_000,
        "byte_span_accuracy_ppm": 1_000_000,
        "determinism": True,
        "mission_isolation": True,
        "unauthorized_mutation_count": 0,
        "fixture_mission_count": 2,
        "fixture_source_count": 5,
        "query_count": 3,
        "result_count": 4,
        "relevant_result_count": 3,
        "correct_result_count": 3,
    }


def test_lens_evaluation_cli_emits_one_stable_json_document() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_lens.py"],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == evaluate_lens()
    assert result.stdout.endswith("\n")
