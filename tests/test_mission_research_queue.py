from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256

from conftest import ClaimSeed, Lab, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import (
    AgentInference,
    FindingCandidate,
    ModelProvider,
    ProviderSelection,
)
from minerva.assist.service import AssistanceService
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.research.models import (
    Claim,
    ClaimStatus,
    Finding,
    FindingStatus,
    Mission,
    StatementKind,
)
from minerva.research_queue import MissionResearchQueueService
from minerva.review import CLAIM_REVIEW_CUE_CATALOG, ClaimReviewService

_ALL_REASON_CODES = tuple(code for code, _category, _explanation in CLAIM_REVIEW_CUE_CATALOG)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _cite(
    lab: Lab,
    *,
    mission_id: str,
    claim_id: str,
    snapshot_id: str,
    content: bytes,
    quote: str,
    stance: EvidenceStance,
) -> EvidenceCard:
    quote_bytes = quote.encode("utf-8")
    start_byte = content.index(quote_bytes)
    return lab.evidence.add_evidence(
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot_id,
        start_byte=start_byte,
        end_byte=start_byte + len(quote_bytes),
        quote=quote,
        stance=stance,
        identity=lab.identity,
    )


def _adopt(
    lab: Lab,
    *,
    claim_id: str,
    evidence: EvidenceCard,
    statements: tuple[str, ...],
) -> tuple[AdoptionService, tuple[AgentInference, ...]]:
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=claim_id,
        selection=ProviderSelection(ModelProvider.OPENAI, "queue-test-model", "test"),
        max_candidates=len(statements),
        max_output_tokens=512,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inferences = tuple(
        adoption.adopt_inference(
            preview=preview,
            candidate_index=index,
            candidate=FindingCandidate(
                statement=statement,
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty="This remains labeled model output with exact citations.",
                evidence_ids=(evidence.id,),
            ),
            response_sha256=sha256(f"queue response {claim_id} {index}".encode()).hexdigest(),
            identity=lab.identity,
        )
        for index, statement in enumerate(statements)
    )
    return adoption, inferences


@dataclass(frozen=True, slots=True)
class _QueueScenario:
    mission: Mission
    claims: tuple[Claim, ...]
    optional_finding: Finding
    unrelated_claimless_finding: Finding
    foreign: ClaimSeed


def _queue_scenario(lab: Lab) -> _QueueScenario:
    mission = lab.research.create_mission(
        title="Mission queue evaluation",
        objective="Expose every deterministic structural review cue without prioritizing it.",
        identity=lab.identity,
    )
    question = lab.research.add_question(
        mission_id=mission.id,
        text="Which claims have structural review cues?",
        identity=lab.identity,
    )

    def add_claim(statement: str) -> Claim:
        return lab.research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement=statement,
            falsification_criteria=f"A fixture mismatch would falsify: {statement}",
            identity=lab.identity,
        )

    empty_claim = add_claim("An empty claim exposes structural evidence gaps.")
    contested_claim = add_claim("A contested claim retains support and opposition.")
    impact_claim = add_claim("A corrected claim retains every correction impact class.")
    inverse_claim = add_claim("Inference and promoted-finding retractions are non-transitive.")

    content = (
        b"Contested support was observed.\n"
        b"Contested opposition was observed.\n"
        b"Withdrawn support was observed.\n"
        b"Inverse promotion support was observed.\n"
    )
    snapshot = lab.sources.import_bytes(
        mission_id=mission.id,
        content=content,
        original_label="mission-queue-fixture.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    _cite(
        lab,
        mission_id=mission.id,
        claim_id=contested_claim.id,
        snapshot_id=snapshot.snapshot_id,
        content=content,
        quote="Contested support was observed.",
        stance=EvidenceStance.SUPPORTS,
    )
    _cite(
        lab,
        mission_id=mission.id,
        claim_id=contested_claim.id,
        snapshot_id=snapshot.snapshot_id,
        content=content,
        quote="Contested opposition was observed.",
        stance=EvidenceStance.OPPOSES,
    )
    lab.research.set_claim_status(
        claim_id=contested_claim.id,
        status=ClaimStatus.CONTESTED,
        reason="Both structurally required active stances are present.",
        expected_version=1,
        identity=lab.identity,
    )

    withdrawn = _cite(
        lab,
        mission_id=mission.id,
        claim_id=impact_claim.id,
        snapshot_id=snapshot.snapshot_id,
        content=content,
        quote="Withdrawn support was observed.",
        stance=EvidenceStance.SUPPORTS,
    )
    lab.research.set_claim_status(
        claim_id=impact_claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="Support was active when this workflow status was recorded.",
        expected_version=1,
        identity=lab.identity,
    )
    lab.research.add_finding(
        mission_id=mission.id,
        claim_id=impact_claim.id,
        statement="A live material finding retains the corrected observation.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The cited observation was later withdrawn.",
        evidence_ids=(withdrawn.id,),
        identity=lab.identity,
    )
    retracted_finding = lab.research.add_finding(
        mission_id=mission.id,
        claim_id=impact_claim.id,
        statement="A retracted material finding remains in history.",
        statement_kind=StatementKind.SOURCE_ASSERTION,
        status=FindingStatus.SUPPORTED,
        uncertainty="The assertion is retained only as correction history.",
        evidence_ids=(withdrawn.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=retracted_finding.id,
        reason="The material assertion is no longer asserted.",
        identity=lab.identity,
    )
    optional_finding = lab.research.add_finding(
        mission_id=mission.id,
        claim_id=None,
        statement="A claimless assumption keeps an optional corrected citation.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="It remains explicitly optional and non-evidentiary.",
        evidence_ids=(withdrawn.id,),
        identity=lab.identity,
    )
    impact_adoption, impact_inferences = _adopt(
        lab,
        claim_id=impact_claim.id,
        evidence=withdrawn,
        statements=(
            "A live inference uses the later-withdrawn support.",
            "A retracted inference remains append-only history.",
            "A retracted promoted inference leaves its finding independent.",
        ),
    )
    impact_adoption.retract_inference(
        inference_id=impact_inferences[1].id,
        reason="This inference is retained only as retracted history.",
        identity=lab.identity,
    )
    impact_adoption.promote_inference_to_finding(
        inference_id=impact_inferences[2].id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    impact_adoption.retract_inference(
        inference_id=impact_inferences[2].id,
        reason="Retraction does not transitively retract the promoted finding.",
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=withdrawn.id,
        reason="The original supporting observation failed later verification.",
        identity=lab.identity,
    )

    inverse_evidence = _cite(
        lab,
        mission_id=mission.id,
        claim_id=inverse_claim.id,
        snapshot_id=snapshot.snapshot_id,
        content=content,
        quote="Inverse promotion support was observed.",
        stance=EvidenceStance.SUPPORTS,
    )
    inverse_adoption, (inverse_inference,) = _adopt(
        lab,
        claim_id=inverse_claim.id,
        evidence=inverse_evidence,
        statements=("A live inference remains after its promoted finding is retracted.",),
    )
    inverse_finding = inverse_adoption.promote_inference_to_finding(
        inference_id=inverse_inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=inverse_finding.id,
        reason="The promoted human assertion is no longer asserted.",
        identity=lab.identity,
    )

    unrelated_claimless_finding = lab.research.add_finding(
        mission_id=mission.id,
        claim_id=None,
        statement="UNRELATED-CLAIMLESS-FINDING-MUST-NOT-ENTER-THE-QUEUE",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="It has no relationship to any reviewed claim.",
        evidence_ids=(),
        identity=lab.identity,
    )
    foreign = lab.seed_claim(content=b"FOREIGN-MISSION-QUEUE-TEXT-MUST-NOT-LEAK\n")
    return _QueueScenario(
        mission=mission,
        claims=(empty_claim, contested_claim, impact_claim, inverse_claim),
        optional_finding=optional_finding,
        unrelated_claimless_finding=unrelated_claimless_finding,
        foreign=foreign,
    )


def test_queue_is_complete_deterministic_and_covers_all_review_cues(lab: Lab) -> None:
    scenario = _queue_scenario(lab)
    service = MissionResearchQueueService(lab.database)

    first = service.build_queue(mission_id=scenario.mission.id)
    second = service.build_queue(mission_id=scenario.mission.id)

    assert first == second
    assert _canonical_bytes(asdict(first)) == _canonical_bytes(asdict(second))
    assert first.schema_version == "minerva.mission-research-queue.v1"
    assert first.kind == "mission_research_queue"
    assert first.algorithm == "claim-review-cue-aggregation"
    assert first.algorithm_version == "1"
    assert first.scope == "mission_claim_review_cues_v1"
    assert first.completion_policy == "complete_or_refuse"
    assert first.complete is True
    assert first.truncated is False
    assert first.mission_id == scenario.mission.id
    assert first.sequence_semantics == "deterministic_display_order_not_priority"

    expected_catalog = tuple(
        (position, code, category, explanation)
        for position, (code, category, explanation) in enumerate(
            CLAIM_REVIEW_CUE_CATALOG,
            start=1,
        )
    )
    assert (
        tuple(
            (reason.catalog_position, reason.code, reason.category, reason.explanation)
            for reason in first.reason_catalog
        )
        == expected_catalog
    )
    assert tuple(summary.claim_id for summary in first.reviewed_claims) == tuple(
        claim.id for claim in scenario.claims
    )
    assert tuple(summary.sequence for summary in first.reviewed_claims) == (1, 2, 3, 4)
    assert tuple(item.sequence for item in first.items) == tuple(range(1, len(first.items) + 1))
    assert all(item.kind == "structural_review_cue" for item in first.items)
    assert len({(item.claim_id, item.reason_code) for item in first.items}) == len(first.items)
    assert {item.reason_code for item in first.items} == set(_ALL_REASON_CODES)

    direct_reviews = {
        claim.id: ClaimReviewService(lab.database).review_claim(
            mission_id=scenario.mission.id,
            claim_id=claim.id,
            bounds=first.claim_review_bounds,
        )
        for claim in scenario.claims
    }
    for summary in first.reviewed_claims:
        review = direct_reviews[summary.claim_id]
        claim_items = tuple(item for item in first.items if item.claim_id == summary.claim_id)
        assert summary.question_id == review.question_id
        assert summary.claim_statement == review.claim_statement
        assert summary.recorded_status is review.recorded_status.status
        assert summary.recorded_status_version == review.recorded_status.version
        assert summary.claim_created_at == review.claim_created_at
        assert summary.reason_codes == tuple(cue.code for cue in review.review_cues)
        assert summary.item_count == len(review.review_cues) == len(claim_items)
        assert summary.review_receipt_sha256 == review.review_receipt_sha256
        assert tuple(item.reason_code for item in claim_items) == summary.reason_codes
        for item, cue in zip(claim_items, review.review_cues, strict=True):
            assert item.question_id == review.question_id
            assert item.explanation == cue.explanation
            assert item.record_ids == cue.record_ids
            assert item.source_review_receipt_sha256 == summary.review_receipt_sha256

    assert first.work.reviewed_claim_count == len(first.reviewed_claims) == 4
    assert first.work.item_count == len(first.items)
    assert first.work.affected_record_count == (
        first.work.affected_finding_count + first.work.affected_inference_count
    )
    assert first.work.distinct_snapshot_count == 1
    assert first.work.distinct_snapshot_bytes > 0
    assert first.work.canonical_output_bytes == len(_canonical_bytes(asdict(first)))
    expected_reason_counts = Counter(item.reason_code for item in first.items)
    assert {count.code: count.count for count in first.reason_counts} == {
        code: expected_reason_counts[code] for code in _ALL_REASON_CODES
    }
    assert scenario.optional_finding.id in {
        record_id for item in first.items for record_id in item.record_ids
    }

    assert first.semantic_boundary.read_only is True
    assert first.semantic_boundary.structural_review_index_only is True
    assert first.semantic_boundary.current_claim_review_taxonomy_guarantees_a_cue is True
    assert first.semantic_boundary.item_presence_means_action_required is False
    assert first.semantic_boundary.item_presence_means_open_or_unresolved is False
    assert first.semantic_boundary.item_order_is_priority_or_severity is False
    assert first.semantic_boundary.assigns_work is False
    assert first.semantic_boundary.records_completion_or_deferral is False
    assert first.semantic_boundary.determines_truth is False
    assert first.semantic_boundary.calculates_confidence is False
    assert first.semantic_boundary.creates_or_changes_research_state is False
    assert first.semantic_boundary.invokes_claim_lineage is False
    assert first.semantic_boundary.invokes_model_provider is False
    assert first.semantic_boundary.invokes_network is False

    encoded = _canonical_bytes(asdict(first)).decode("utf-8")
    for excluded in (
        scenario.unrelated_claimless_finding.id,
        scenario.unrelated_claimless_finding.statement,
        scenario.foreign.mission.id,
        scenario.foreign.question.id,
        scenario.foreign.claim.id,
        scenario.foreign.snapshot.snapshot_id,
        "FOREIGN-MISSION-QUEUE-TEXT-MUST-NOT-LEAK",
    ):
        assert excluded not in encoded


def test_queue_subreceipts_and_whole_receipt_have_exact_framing(lab: Lab) -> None:
    scenario = _queue_scenario(lab)
    queue = MissionResearchQueueService(lab.database).build_queue(mission_id=scenario.mission.id)
    common = {
        "algorithm": "claim-review-cue-aggregation",
        "algorithm_version": "1",
        "scope": "mission_claim_review_cues_v1",
        "mission_id": scenario.mission.id,
    }
    claim_frame = {
        "schema_version": "minerva.mission-research-queue-claims.v1",
        **common,
        "claims": [
            {
                "sequence": item.sequence,
                "claim_id": item.claim_id,
                "question_id": item.question_id,
                "claim_statement": item.claim_statement,
                "recorded_status": item.recorded_status,
                "recorded_status_version": item.recorded_status_version,
                "claim_created_at": item.claim_created_at,
            }
            for item in queue.reviewed_claims
        ],
    }
    assert queue.claim_set_sha256 == sha256(_canonical_bytes(claim_frame)).hexdigest()

    review_frame = {
        "schema_version": "minerva.mission-research-queue-claim-reviews.v1",
        **common,
        "claim_reviews": [
            {
                "sequence": item.sequence,
                "claim_id": item.claim_id,
                "reason_codes": item.reason_codes,
                "item_count": item.item_count,
                "review_receipt_sha256": item.review_receipt_sha256,
            }
            for item in queue.reviewed_claims
        ],
    }
    assert queue.claim_review_set_sha256 == sha256(_canonical_bytes(review_frame)).hexdigest()

    item_frame = {
        "schema_version": "minerva.mission-research-queue-items.v1",
        **common,
        "items": [asdict(item) for item in queue.items],
    }
    assert queue.item_set_sha256 == sha256(_canonical_bytes(item_frame)).hexdigest()

    receipt = asdict(queue)
    receipt_sha256 = receipt.pop("queue_receipt_sha256")
    assert receipt_sha256 == sha256(_canonical_bytes(receipt)).hexdigest()


def test_existing_empty_mission_returns_an_empty_complete_queue(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Empty mission",
        objective="Verify an empty mission is complete rather than missing.",
        identity=lab.identity,
    )

    queue = MissionResearchQueueService(lab.database).build_queue(mission_id=mission.id)

    assert queue.complete is True
    assert queue.truncated is False
    assert queue.reviewed_claims == ()
    assert queue.items == ()
    assert queue.work.reviewed_claim_count == 0
    assert queue.work.item_count == 0
    assert all(count.count == 0 for count in queue.reason_counts)
    assert queue.semantic_boundary.current_claim_review_taxonomy_guarantees_a_cue is True
