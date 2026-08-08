"""Run the deterministic, model-free Claim Review synthetic evaluation."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from minerva.assist.adoption import AdoptionService
from minerva.assist.models import FindingCandidate, ModelProvider, ProviderSelection
from minerva.assist.service import AssistanceService
from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.review import ClaimReviewService
from minerva.review.models import ClaimReviewResult
from minerva.sources.service import SourceService

_CLOCK = "2026-08-08T12:00:00.000000Z"
_RESPONSE_SHA256 = sha256(b"fixed synthetic claim-review response").hexdigest()
_GAP_CODES = (
    "no_active_evidence",
    "no_active_support",
    "no_active_opposition",
    "status_required_active_stance_missing",
)
_IMPACT_EDGE_FIELDS = (
    ("active_material_finding", "active_material_finding_ids"),
    ("active_optional_finding", "active_optional_finding_ids"),
    ("retracted_finding", "retracted_finding_ids"),
    ("active_inference", "active_inference_ids"),
    ("retracted_inference", "retracted_inference_ids"),
    ("direct_superseding_evidence", "direct_superseding_evidence_ids"),
)


class _SequenceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


def _fixed_clock() -> str:
    return _CLOCK


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _state(database: Database) -> tuple[tuple[str, ...], str]:
    with database.read() as connection:
        dump = tuple(connection.iterdump())
    return dump, sha256(database.path.read_bytes()).hexdigest()


def _ppm(numerator: int, denominator: int) -> int:
    return numerator * 1_000_000 // denominator if denominator else 1_000_000


def _cite(
    evidence: EvidenceService,
    *,
    mission_id: str,
    claim_id: str,
    snapshot_id: str,
    content: bytes,
    quote: str,
    stance: EvidenceStance,
    identity: IdentityContext,
    supersedes_evidence_id: str | None = None,
) -> EvidenceCard:
    quote_bytes = quote.encode("utf-8")
    start_byte = content.index(quote_bytes)
    return evidence.add_evidence(
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot_id,
        start_byte=start_byte,
        end_byte=start_byte + len(quote_bytes),
        quote=quote,
        stance=stance,
        supersedes_evidence_id=supersedes_evidence_id,
        identity=identity,
    )


def _impact_edges(result: ClaimReviewResult) -> frozenset[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for impact in result.withdrawal_impacts:
        for relation, field_name in _IMPACT_EDGE_FIELDS:
            for record_id in getattr(impact, field_name):
                edges.add((impact.evidence_id, relation, record_id))
    return frozenset(edges)


def evaluate_claim_review() -> dict[str, object]:
    """Return integer quality metrics over fixed, mission-isolated ledger fixtures."""
    with tempfile.TemporaryDirectory(prefix="minerva-claim-review-evaluation-") as temporary:
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:claim-review-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="evaluate deterministic structural claim review",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)
        evidence = EvidenceService(database, clock=_fixed_clock, id_factory=ids)
        assistance = AssistanceService(database, clock=_fixed_clock, id_factory=ids)
        adoption = AdoptionService(database, clock=_fixed_clock, id_factory=ids)

        mission = research.create_mission(
            title="Claim Review evaluation mission",
            objective="Measure structural gaps and append-only correction impacts.",
            identity=identity,
        )
        question = research.add_question(
            mission_id=mission.id,
            text="Which ledger states require human review?",
            identity=identity,
        )
        empty_claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="An open claim may have no evidence yet.",
            falsification_criteria="Any added card changes the empty-ledger fixture.",
            identity=identity,
        )
        contested_claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="The active ledger contains both supporting and opposing observations.",
            falsification_criteria="Removing either active stance ends the structural conflict.",
            identity=identity,
        )
        corrected_claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="A withdrawn supporting card leaves reviewable downstream impacts.",
            falsification_criteria="No withdrawn support or dependent records would refute it.",
            identity=identity,
        )

        content = (
            b"Contested support was observed.\n"
            b"Contested opposition was observed.\n"
            b"Original support was observed.\n"
            b"Opposing evidence remains active.\n"
            b"Replacement context preserves the correction trail.\n"
        )
        snapshot = sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label="claim-review-fixture.txt",
            media_type="text/plain",
            identity=identity,
        )
        _cite(
            evidence,
            mission_id=mission.id,
            claim_id=contested_claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Contested support was observed.",
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )
        _cite(
            evidence,
            mission_id=mission.id,
            claim_id=contested_claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Contested opposition was observed.",
            stance=EvidenceStance.OPPOSES,
            identity=identity,
        )
        research.set_claim_status(
            claim_id=contested_claim.id,
            status=ClaimStatus.CONTESTED,
            reason="Both required active stances are present.",
            expected_version=contested_claim.version,
            identity=identity,
        )

        withdrawn_support = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Original support was observed.",
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )
        _cite(
            evidence,
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Opposing evidence remains active.",
            stance=EvidenceStance.OPPOSES,
            identity=identity,
        )
        superseding_context = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Replacement context preserves the correction trail.",
            stance=EvidenceStance.CONTEXT,
            supersedes_evidence_id=withdrawn_support.id,
            identity=identity,
        )
        research.set_claim_status(
            claim_id=corrected_claim.id,
            status=ClaimStatus.PROVISIONALLY_SUPPORTED,
            reason="Support was active when this workflow status was recorded.",
            expected_version=corrected_claim.version,
            identity=identity,
        )

        live_material = research.add_finding(
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            statement="A live material finding depends on the original support.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="The cited observation may later be corrected.",
            evidence_ids=(withdrawn_support.id,),
            identity=identity,
        )
        live_optional = research.add_finding(
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            statement="An optional assumption retains the historical citation.",
            statement_kind=StatementKind.ASSUMPTION,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="This assumption is not a material evidence assertion.",
            evidence_ids=(withdrawn_support.id,),
            identity=identity,
        )
        retracted_finding = research.add_finding(
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            statement="A retracted finding remains in append-only history.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="The assertion is retained only as correction history.",
            evidence_ids=(withdrawn_support.id,),
            identity=identity,
        )
        research.retract_finding(
            finding_id=retracted_finding.id,
            reason="The human reviewer withdrew this assertion.",
            identity=identity,
        )

        preview = assistance.preview_finding_candidates(
            claim_id=corrected_claim.id,
            selection=ProviderSelection(ModelProvider.OPENAI, "test-model-1", "evaluation"),
            max_candidates=2,
            max_output_tokens=512,
        )
        live_inference = adoption.adopt_inference(
            preview=preview,
            candidate_index=0,
            candidate=FindingCandidate(
                statement="A live adopted inference depends on the original support.",
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty="The cited support may be withdrawn.",
                evidence_ids=(withdrawn_support.id,),
            ),
            response_sha256=_RESPONSE_SHA256,
            identity=identity,
        )
        retracted_inference = adoption.adopt_inference(
            preview=preview,
            candidate_index=1,
            candidate=FindingCandidate(
                statement="A retracted adopted inference remains inspectable.",
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty="This inference is retained only as correction history.",
                evidence_ids=(withdrawn_support.id,),
            ),
            response_sha256=_RESPONSE_SHA256,
            identity=identity,
        )
        adoption.retract_inference(
            inference_id=retracted_inference.id,
            reason="The human reviewer withdrew this adopted inference.",
            identity=identity,
        )
        evidence.withdraw_evidence(
            evidence_id=withdrawn_support.id,
            reason="The original observation failed source verification.",
            identity=identity,
        )

        foreign_mission = research.create_mission(
            title="Claim Review isolation control",
            objective="Ensure review cannot cross mission boundaries.",
            identity=identity,
        )
        foreign_question = research.add_question(
            mission_id=foreign_mission.id,
            text="Can foreign research leak into the target review?",
            identity=identity,
        )
        foreign_claim = research.add_claim(
            mission_id=foreign_mission.id,
            question_id=foreign_question.id,
            statement="Foreign evidence must remain outside the target review.",
            falsification_criteria="Any foreign identifier in target output is a failure.",
            identity=identity,
        )
        foreign_content = b"Foreign support must remain isolated.\n"
        foreign_snapshot = sources.import_bytes(
            mission_id=foreign_mission.id,
            content=foreign_content,
            original_label="foreign-review-fixture.txt",
            media_type="text/plain",
            identity=identity,
        )
        foreign_evidence = _cite(
            evidence,
            mission_id=foreign_mission.id,
            claim_id=foreign_claim.id,
            snapshot_id=foreign_snapshot.snapshot_id,
            content=foreign_content,
            quote="Foreign support must remain isolated.",
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )

        claim_ids = (empty_claim.id, contested_claim.id, corrected_claim.id)
        service = ClaimReviewService(database)
        before = _state(database)
        first = tuple(
            service.review_claim(mission_id=mission.id, claim_id=claim_id) for claim_id in claim_ids
        )
        second = tuple(
            service.review_claim(mission_id=mission.id, claim_id=claim_id) for claim_id in claim_ids
        )
        after = _state(database)

        expected_gaps = {
            empty_claim.id: frozenset(
                {"no_active_evidence", "no_active_support", "no_active_opposition"}
            ),
            contested_claim.id: frozenset(),
            corrected_claim.id: frozenset(
                {"no_active_support", "status_required_active_stance_missing"}
            ),
        }
        gap_label_count = len(first) * len(_GAP_CODES)
        correct_gap_label_count = sum(
            (code in result.gap_codes) == (code in expected_gaps[result.claim_id])
            for result in first
            for code in _GAP_CODES
        )
        expected_status_validity = {
            empty_claim.id: True,
            contested_claim.id: True,
            corrected_claim.id: False,
        }
        correct_status_case_count = sum(
            result.recorded_status.evidence_valid is expected_status_validity[result.claim_id]
            for result in first
        )

        corrected_result = first[2]
        expected_impact_edges = frozenset(
            {
                (withdrawn_support.id, "active_material_finding", live_material.id),
                (withdrawn_support.id, "active_optional_finding", live_optional.id),
                (withdrawn_support.id, "retracted_finding", retracted_finding.id),
                (withdrawn_support.id, "active_inference", live_inference.id),
                (withdrawn_support.id, "retracted_inference", retracted_inference.id),
                (
                    withdrawn_support.id,
                    "direct_superseding_evidence",
                    superseding_context.id,
                ),
            }
        )
        predicted_impact_edges = _impact_edges(corrected_result)
        correct_impact_edges = predicted_impact_edges & expected_impact_edges

        first_bytes = _canonical_bytes([asdict(result) for result in first])
        second_bytes = _canonical_bytes([asdict(result) for result in second])
        foreign_identifiers = (
            foreign_mission.id,
            foreign_question.id,
            foreign_claim.id,
            foreign_snapshot.source_id,
            foreign_snapshot.snapshot_id,
            foreign_evidence.id,
        )
        mission_isolation = all(result.mission_id == mission.id for result in first) and not any(
            identifier.encode() in first_bytes for identifier in foreign_identifiers
        )
        unauthorized_mutation_count = int(before[0] != after[0]) + int(before[1] != after[1])

        return {
            "schema_version": "minerva.claim-review-evaluation.v1",
            "algorithm": first[0].algorithm,
            "algorithm_version": first[0].algorithm_version,
            "gap_classification_accuracy_ppm": _ppm(correct_gap_label_count, gap_label_count),
            "status_validity_accuracy_ppm": _ppm(correct_status_case_count, len(first)),
            "impact_edge_precision_ppm": _ppm(
                len(correct_impact_edges), len(predicted_impact_edges)
            ),
            "impact_edge_recall_ppm": _ppm(len(correct_impact_edges), len(expected_impact_edges)),
            "determinism": first_bytes == second_bytes,
            "mission_isolation": mission_isolation,
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_claim_count": 4,
            "review_count": len(first),
            "gap_label_count": gap_label_count,
            "correct_gap_label_count": correct_gap_label_count,
            "status_case_count": len(first),
            "correct_status_case_count": correct_status_case_count,
            "predicted_impact_edge_count": len(predicted_impact_edges),
            "relevant_impact_edge_count": len(expected_impact_edges),
            "correct_impact_edge_count": len(correct_impact_edges),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(_canonical_bytes(evaluate_claim_review()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
