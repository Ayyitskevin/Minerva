from __future__ import annotations

import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from conftest import Lab
from minerva.evidence import EvidenceStance
from minerva.research.models import FindingStatus, StatementKind

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_research_quality.py"
_MODULE = runpy.run_path(str(_SCRIPT))
evaluate_research_quality = cast(
    Callable[..., dict[str, object]],
    _MODULE["evaluate_research_quality"],
)
EvaluationError = cast(type[RuntimeError], _MODULE["EvaluationError"])


def _count_audits(lab: Lab) -> int:
    with lab.database.read() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])


def test_research_quality_evaluation_measures_real_persisted_records_read_only(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"The measured result remained stable.")
    evidence = lab.cite(seed, "measured result", EvidenceStance.SUPPORTS)
    lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The recorded measurement supports the claim.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="This is one bounded local measurement.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    before = _count_audits(lab)

    result = evaluate_research_quality(lab.database, minimum_missions=1)

    assert result["schema_version"] == "minerva.research-quality-evaluation.v1"
    assert result["mission_count"] == 1
    assert result["claim_count"] == 1
    assert result["evidence_card_count"] == 1
    assert result["finding_count"] == 1
    quality = cast(dict[str, object], result["research_quality"])
    assert quality["claim_active_evidence_coverage_ppm"] == 1_000_000
    assert quality["supported_or_contested_finding_active_citation_coverage_ppm"] == 1_000_000
    uncertainty = cast(dict[str, object], result["uncertainty"])
    assert uncertainty["finding_explicit_uncertainty_ppm"] == 1_000_000
    effort = cast(dict[str, object], result["operator_effort"])
    assert effort["missions_reaching_first_evidence_count"] == 1
    assert cast(dict[str, object], effort["audited_events_to_first_evidence"])["minimum"] > 0
    assert result["read_only"] is True
    assert result["logical_state_receipt_before"] == result["logical_state_receipt_after"]
    assert str(lab.database.path) not in json.dumps(result)
    assert _count_audits(lab) == before


def test_research_quality_evaluation_refuses_an_underpowered_corpus(lab: Lab) -> None:
    lab.seed_claim()

    with pytest.raises(EvaluationError, match="at least 2 missions"):
        evaluate_research_quality(lab.database, minimum_missions=2)


def test_research_quality_evaluation_cli_emits_aggregate_json(lab: Lab) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    result = subprocess.run(  # noqa: S603 - fixed local interpreter and repository script
        [
            sys.executable,
            "scripts/evaluate_research_quality.py",
            "--db",
            str(lab.database.path),
            "--minimum-missions",
            "1",
        ],
        cwd=_SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["mission_count"] == 1
    assert str(lab.database.path) not in result.stdout
