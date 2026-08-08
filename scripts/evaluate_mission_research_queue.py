"""Run the deterministic, model-free Mission Research Queue evaluation."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from minerva.assist.adoption import AdoptionService
from minerva.assist.models import (
    AgentInference,
    FindingCandidate,
    ModelProvider,
    ProviderSelection,
)
from minerva.assist.service import AssistanceService
from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.research_queue import MissionResearchQueueService
from minerva.research_queue.models import MissionResearchQueueResult
from minerva.sources.service import SourceService

_CLOCK = "2026-08-08T12:00:00.000000Z"
_REASON_CODES = (
    "no_active_evidence",
    "no_active_support",
    "no_active_opposition",
    "status_required_active_stance_missing",
    "active_stance_contradiction",
    "withdrawn_evidence_history_present",
    "recorded_status_requirement_unmet",
    "live_material_finding_uses_withdrawn_evidence",
    "optional_statement_uses_withdrawn_evidence",
    "retracted_finding_history_present",
    "live_inference_uses_withdrawn_evidence",
    "retracted_inference_history_present",
    "promoted_finding_remains_independently_asserted",
    "live_inference_remains_after_promoted_finding_retraction",
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
    return numerator * 1_000_000 // denominator if denominator else 0


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


def _adopt(
    *,
    assistance: AssistanceService,
    adoption: AdoptionService,
    claim_id: str,
    evidence_ids: tuple[str, ...],
    statements: tuple[str, ...],
    model: str,
    identity: IdentityContext,
) -> tuple[AgentInference, ...]:
    preview = assistance.preview_finding_candidates(
        claim_id=claim_id,
        selection=ProviderSelection(ModelProvider.OPENAI, model, "evaluation"),
        max_candidates=len(statements),
        max_output_tokens=512,
    )
    return tuple(
        adoption.adopt_inference(
            preview=preview,
            candidate_index=index,
            candidate=FindingCandidate(
                statement=statement,
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty="This remains labeled model output with exact citations.",
                evidence_ids=evidence_ids,
            ),
            response_sha256=sha256(f"queue response {model} {index}".encode()).hexdigest(),
            identity=identity,
        )
        for index, statement in enumerate(statements)
    )


def _framed_digest(
    *,
    schema_version: str,
    mission_id: str,
    key: str,
    value: object,
) -> str:
    return sha256(
        _canonical_bytes(
            {
                "schema_version": schema_version,
                "algorithm": "claim-review-cue-aggregation",
                "algorithm_version": "1",
                "scope": "mission_claim_review_cues_v1",
                "mission_id": mission_id,
                key: value,
            }
        )
    ).hexdigest()


def _claim_set_digest(result: MissionResearchQueueResult) -> str:
    return _framed_digest(
        schema_version="minerva.mission-research-queue-claims.v1",
        mission_id=result.mission_id,
        key="claims",
        value=[
            {
                "sequence": item.sequence,
                "claim_id": item.claim_id,
                "question_id": item.question_id,
                "claim_statement": item.claim_statement,
                "recorded_status": item.recorded_status,
                "recorded_status_version": item.recorded_status_version,
                "claim_created_at": item.claim_created_at,
            }
            for item in result.reviewed_claims
        ],
    )


def _claim_review_set_digest(result: MissionResearchQueueResult) -> str:
    return _framed_digest(
        schema_version="minerva.mission-research-queue-claim-reviews.v1",
        mission_id=result.mission_id,
        key="claim_reviews",
        value=[
            {
                "sequence": item.sequence,
                "claim_id": item.claim_id,
                "reason_codes": item.reason_codes,
                "item_count": item.item_count,
                "review_receipt_sha256": item.review_receipt_sha256,
            }
            for item in result.reviewed_claims
        ],
    )


def _item_set_digest(result: MissionResearchQueueResult) -> str:
    return _framed_digest(
        schema_version="minerva.mission-research-queue-items.v1",
        mission_id=result.mission_id,
        key="items",
        value=[asdict(item) for item in result.items],
    )


def _queue_receipt_digest(result: MissionResearchQueueResult) -> str:
    payload = asdict(result)
    payload.pop("queue_receipt_sha256")
    return sha256(_canonical_bytes(payload)).hexdigest()


def evaluate_mission_research_queue() -> dict[str, object]:
    """Return exact classification, receipt, isolation, and read-only metrics."""
    with tempfile.TemporaryDirectory(prefix="minerva-mission-queue-evaluation-") as temporary:
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:mission-queue-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="evaluate deterministic mission structural review aggregation",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)
        evidence = EvidenceService(database, clock=_fixed_clock, id_factory=ids)
        assistance = AssistanceService(database, clock=_fixed_clock, id_factory=ids)
        adoption = AdoptionService(database, clock=_fixed_clock, id_factory=ids)

        mission = research.create_mission(
            title="Mission queue evaluation target",
            objective="Measure exact structural review cue aggregation.",
            identity=identity,
        )
        question = research.add_question(
            mission_id=mission.id,
            text="Which claim ledger structures appear in the mission index?",
            identity=identity,
        )
        empty_claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="An empty claim has no evidence cards.",
            falsification_criteria="Any evidence card would change the empty fixture.",
            identity=identity,
        )
        contested_claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="A contested claim has active support and opposition.",
            falsification_criteria="Removing either active stance ends the conflict.",
            identity=identity,
        )
        corrected_claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="A correction trail retains every structural impact class.",
            falsification_criteria="A missing correction relationship changes the fixture.",
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
            original_label="mission-queue-evaluation.txt",
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
            reason="Both structurally required active stances are present.",
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
        active_opposition = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Opposing evidence remains active.",
            stance=EvidenceStance.OPPOSES,
            identity=identity,
        )
        _cite(
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
            reason="Support was active when this workflow state was recorded.",
            expected_version=corrected_claim.version,
            identity=identity,
        )

        live_material = research.add_finding(
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            statement="A live material finding retains the corrected observation.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="The cited observation was later withdrawn.",
            evidence_ids=(withdrawn_support.id,),
            identity=identity,
        )
        live_optional = research.add_finding(
            mission_id=mission.id,
            claim_id=None,
            statement="A claimless assumption retains the corrected citation.",
            statement_kind=StatementKind.ASSUMPTION,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="It remains explicitly optional and non-evidentiary.",
            evidence_ids=(withdrawn_support.id,),
            identity=identity,
        )
        retracted_finding = research.add_finding(
            mission_id=mission.id,
            claim_id=corrected_claim.id,
            statement="A retracted material finding remains in history.",
            statement_kind=StatementKind.SOURCE_ASSERTION,
            status=FindingStatus.SUPPORTED,
            uncertainty="The assertion remains only in append-only history.",
            evidence_ids=(withdrawn_support.id,),
            identity=identity,
        )
        research.retract_finding(
            finding_id=retracted_finding.id,
            reason="The material assertion is no longer asserted.",
            identity=identity,
        )

        live_inference, retracted_inference = _adopt(
            assistance=assistance,
            adoption=adoption,
            claim_id=corrected_claim.id,
            evidence_ids=(withdrawn_support.id,),
            statements=(
                "A live inference uses the later-withdrawn support.",
                "A retracted inference remains append-only history.",
            ),
            model="queue-evaluation-withdrawal",
            identity=identity,
        )
        adoption.retract_inference(
            inference_id=retracted_inference.id,
            reason="This inference remains only as retracted history.",
            identity=identity,
        )

        promoted_then_retracted, live_after_finding_retraction = _adopt(
            assistance=assistance,
            adoption=adoption,
            claim_id=corrected_claim.id,
            evidence_ids=(active_opposition.id,),
            statements=(
                "A retracted promoted inference leaves its finding independent.",
                "A live inference remains after its promoted finding is retracted.",
            ),
            model="queue-evaluation-promotion",
            identity=identity,
        )
        adoption.promote_inference_to_finding(
            inference_id=promoted_then_retracted.id,
            status=FindingStatus.SUPPORTED,
            identity=identity,
        )
        adoption.retract_inference(
            inference_id=promoted_then_retracted.id,
            reason="Retraction does not transitively retract the promoted finding.",
            identity=identity,
        )
        promoted_retracted_finding = adoption.promote_inference_to_finding(
            inference_id=live_after_finding_retraction.id,
            status=FindingStatus.SUPPORTED,
            identity=identity,
        )
        research.retract_finding(
            finding_id=promoted_retracted_finding.id,
            reason="The promoted human assertion is no longer asserted.",
            identity=identity,
        )
        evidence.withdraw_evidence(
            evidence_id=withdrawn_support.id,
            reason="The original supporting observation failed later verification.",
            identity=identity,
        )

        foreign_mission = research.create_mission(
            title="FOREIGN-MISSION-TITLE-MUST-NOT-LEAK",
            objective="FOREIGN-MISSION-OBJECTIVE-MUST-NOT-LEAK",
            identity=identity,
        )
        foreign_question = research.add_question(
            mission_id=foreign_mission.id,
            text="FOREIGN-QUESTION-TEXT-MUST-NOT-LEAK",
            identity=identity,
        )
        foreign_claim = research.add_claim(
            mission_id=foreign_mission.id,
            question_id=foreign_question.id,
            statement="FOREIGN-CLAIM-TEXT-MUST-NOT-LEAK",
            falsification_criteria="FOREIGN-CRITERIA-TEXT-MUST-NOT-LEAK",
            identity=identity,
        )
        foreign_content = b"FOREIGN-SOURCE-TEXT-MUST-NOT-LEAK\n"
        foreign_snapshot = sources.import_bytes(
            mission_id=foreign_mission.id,
            content=foreign_content,
            original_label="FOREIGN-SOURCE-LABEL-MUST-NOT-LEAK",
            media_type="text/plain",
            identity=identity,
        )
        foreign_evidence = _cite(
            evidence,
            mission_id=foreign_mission.id,
            claim_id=foreign_claim.id,
            snapshot_id=foreign_snapshot.snapshot_id,
            content=foreign_content,
            quote="FOREIGN-SOURCE-TEXT-MUST-NOT-LEAK",
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )

        expected_claim_ids = (empty_claim.id, contested_claim.id, corrected_claim.id)
        expected_entries = frozenset(
            {
                (empty_claim.id, "no_active_evidence", ()),
                (empty_claim.id, "no_active_support", ()),
                (empty_claim.id, "no_active_opposition", ()),
                (contested_claim.id, "active_stance_contradiction", ()),
                (corrected_claim.id, "no_active_support", ()),
                (corrected_claim.id, "status_required_active_stance_missing", ()),
                (
                    corrected_claim.id,
                    "withdrawn_evidence_history_present",
                    (withdrawn_support.id,),
                ),
                (corrected_claim.id, "recorded_status_requirement_unmet", ()),
                (
                    corrected_claim.id,
                    "live_material_finding_uses_withdrawn_evidence",
                    (live_material.id,),
                ),
                (
                    corrected_claim.id,
                    "optional_statement_uses_withdrawn_evidence",
                    (live_optional.id,),
                ),
                (
                    corrected_claim.id,
                    "retracted_finding_history_present",
                    (retracted_finding.id, promoted_retracted_finding.id),
                ),
                (
                    corrected_claim.id,
                    "live_inference_uses_withdrawn_evidence",
                    (live_inference.id,),
                ),
                (
                    corrected_claim.id,
                    "retracted_inference_history_present",
                    (retracted_inference.id, promoted_then_retracted.id),
                ),
                (
                    corrected_claim.id,
                    "promoted_finding_remains_independently_asserted",
                    (promoted_then_retracted.id,),
                ),
                (
                    corrected_claim.id,
                    "live_inference_remains_after_promoted_finding_retraction",
                    (live_after_finding_retraction.id,),
                ),
            }
        )

        service = MissionResearchQueueService(database)
        before = _state(database)
        first = service.build_queue(mission_id=mission.id)
        second = service.build_queue(mission_id=mission.id)
        after = _state(database)

        first_bytes = _canonical_bytes(asdict(first))
        second_bytes = _canonical_bytes(asdict(second))
        actual_claim_ids = tuple(item.claim_id for item in first.reviewed_claims)
        actual_entries = frozenset(
            (item.claim_id, item.reason_code, item.record_ids) for item in first.items
        )
        correct_claim_ids = set(actual_claim_ids) & set(expected_claim_ids)
        correct_entries = actual_entries & expected_entries
        expected_by_claim_code = {
            (claim_id, reason_code): record_ids
            for claim_id, reason_code, record_ids in expected_entries
        }
        actual_by_claim_code = {
            (item.claim_id, item.reason_code): item.record_ids for item in first.items
        }
        reason_code_label_count = len(expected_claim_ids) * len(_REASON_CODES)
        correct_reason_code_label_count = sum(
            ((claim_id, code) in actual_by_claim_code)
            == ((claim_id, code) in expected_by_claim_code)
            for claim_id in expected_claim_ids
            for code in _REASON_CODES
        )

        expected_item_order = tuple(
            (claim_id, code, expected_by_claim_code[(claim_id, code)])
            for claim_id in expected_claim_ids
            for code in _REASON_CODES
            if (claim_id, code) in expected_by_claim_code
        )
        actual_item_order = tuple(
            (item.claim_id, item.reason_code, item.record_ids) for item in first.items
        )
        reason_count_map = Counter(item.reason_code for item in first.items)
        canonical_ordering = (
            actual_claim_ids == expected_claim_ids
            and tuple(item.sequence for item in first.reviewed_claims)
            == tuple(range(1, len(first.reviewed_claims) + 1))
            and actual_item_order == expected_item_order
            and tuple(item.sequence for item in first.items)
            == tuple(range(1, len(first.items) + 1))
            and tuple(reason.code for reason in first.reason_catalog) == _REASON_CODES
            and tuple(reason.catalog_position for reason in first.reason_catalog)
            == tuple(range(1, len(_REASON_CODES) + 1))
            and tuple(count.code for count in first.reason_counts) == _REASON_CODES
            and all(count.count == reason_count_map[count.code] for count in first.reason_counts)
            and all(item.kind == "structural_review_cue" for item in first.items)
            and all(
                summary.reason_codes
                == tuple(
                    item.reason_code for item in first.items if item.claim_id == summary.claim_id
                )
                and summary.item_count
                == sum(item.claim_id == summary.claim_id for item in first.items)
                and all(
                    item.source_review_receipt_sha256 == summary.review_receipt_sha256
                    for item in first.items
                    if item.claim_id == summary.claim_id
                )
                for summary in first.reviewed_claims
            )
        )

        foreign_values = (
            foreign_mission.id,
            foreign_mission.title,
            foreign_mission.objective,
            foreign_question.id,
            foreign_question.text,
            foreign_claim.id,
            foreign_claim.statement,
            foreign_claim.falsification_criteria,
            foreign_snapshot.source_id,
            foreign_snapshot.snapshot_id,
            "FOREIGN-SOURCE-LABEL-MUST-NOT-LEAK",
            foreign_evidence.id,
            "FOREIGN-SOURCE-TEXT-MUST-NOT-LEAK",
        )
        mission_isolation = first.mission_id == mission.id and not any(
            value.encode("utf-8") in first_bytes for value in foreign_values
        )
        covered_codes = {item.reason_code for item in first.items}
        unauthorized_mutation_count = int(before[0] != after[0]) + int(before[1] != after[1])

        return {
            "schema_version": "minerva.mission-research-queue-evaluation.v1",
            "algorithm": first.algorithm,
            "algorithm_version": first.algorithm_version,
            "claim_precision_ppm": _ppm(len(correct_claim_ids), len(actual_claim_ids)),
            "claim_recall_ppm": _ppm(len(correct_claim_ids), len(expected_claim_ids)),
            "entry_precision_ppm": _ppm(len(correct_entries), len(actual_entries)),
            "entry_recall_ppm": _ppm(len(correct_entries), len(expected_entries)),
            "reason_code_classification_accuracy_ppm": _ppm(
                correct_reason_code_label_count,
                reason_code_label_count,
            ),
            "reason_code_catalog_coverage_ppm": _ppm(
                len(covered_codes & set(_REASON_CODES)),
                len(_REASON_CODES),
            ),
            "determinism": first_bytes == second_bytes,
            "canonical_ordering": canonical_ordering,
            "claim_set_digest_valid": first.claim_set_sha256 == _claim_set_digest(first),
            "claim_review_set_digest_valid": (
                first.claim_review_set_sha256 == _claim_review_set_digest(first)
            ),
            "item_set_digest_valid": first.item_set_sha256 == _item_set_digest(first),
            "queue_receipt_digest_valid": (
                first.queue_receipt_sha256 == _queue_receipt_digest(first)
            ),
            "mission_isolation": mission_isolation,
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_claim_count": 4,
            "expected_claim_count": len(expected_claim_ids),
            "result_claim_count": len(actual_claim_ids),
            "expected_entry_count": len(expected_entries),
            "result_entry_count": len(actual_entries),
            "reason_code_label_count": reason_code_label_count,
            "correct_reason_code_label_count": correct_reason_code_label_count,
            "expected_reason_code_count": len(_REASON_CODES),
            "covered_reason_code_count": len(covered_codes & set(_REASON_CODES)),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(_canonical_bytes(evaluate_mission_research_queue()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
