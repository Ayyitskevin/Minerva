from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

import minerva.core.db as db_module
import minerva.integrations.ai as ai_integrations
import minerva.review.service as review_service_module
from conftest import ClaimSeed, Lab, SequenceIds, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import (
    AgentInference,
    FindingCandidate,
    ModelProvider,
    ProviderSelection,
)
from minerva.assist.service import AssistanceService
from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.research.models import ClaimStatus, Finding, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.review import ClaimReviewBounds, ClaimReviewService
from minerva.sources.service import SourceService


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


def _counts(value: object) -> tuple[int, int, int, int, int]:
    return tuple(
        asdict(value)[key]
        for key in (  # type: ignore[return-value]
            "supports",
            "opposes",
            "context",
            "inconclusive",
            "total",
        )
    )


_QUOTES = {
    EvidenceStance.SUPPORTS: "Evidence supports the claim.",
    EvidenceStance.OPPOSES: "Evidence opposes the claim.",
    EvidenceStance.CONTEXT: "Café context remains uncertain.",
    EvidenceStance.INCONCLUSIVE: "Café context remains uncertain.",
}


@pytest.mark.parametrize(
    (
        "status",
        "initial_stances",
        "withdraw_indexes",
        "expected_active",
        "expected_withdrawn",
        "required",
        "missing_required",
        "valid",
        "contradiction",
        "gap_codes",
    ),
    [
        (
            ClaimStatus.OPEN,
            (),
            (),
            (0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0),
            (),
            (),
            True,
            False,
            ("no_active_evidence", "no_active_support", "no_active_opposition"),
        ),
        (
            ClaimStatus.INCONCLUSIVE,
            (EvidenceStance.CONTEXT, EvidenceStance.INCONCLUSIVE),
            (),
            (0, 0, 1, 1, 2),
            (0, 0, 0, 0, 0),
            (),
            (),
            True,
            False,
            ("no_active_support", "no_active_opposition"),
        ),
        (
            ClaimStatus.PROVISIONALLY_SUPPORTED,
            (EvidenceStance.SUPPORTS,),
            (),
            (1, 0, 0, 0, 1),
            (0, 0, 0, 0, 0),
            (EvidenceStance.SUPPORTS,),
            (),
            True,
            False,
            ("no_active_opposition",),
        ),
        (
            ClaimStatus.PROVISIONALLY_SUPPORTED,
            (EvidenceStance.SUPPORTS, EvidenceStance.OPPOSES),
            (),
            (1, 1, 0, 0, 2),
            (0, 0, 0, 0, 0),
            (EvidenceStance.SUPPORTS,),
            (),
            True,
            True,
            (),
        ),
        (
            ClaimStatus.UNSUPPORTED,
            (EvidenceStance.OPPOSES,),
            (),
            (0, 1, 0, 0, 1),
            (0, 0, 0, 0, 0),
            (EvidenceStance.OPPOSES,),
            (),
            True,
            False,
            ("no_active_support",),
        ),
        (
            ClaimStatus.CONTESTED,
            (EvidenceStance.SUPPORTS, EvidenceStance.OPPOSES),
            (),
            (1, 1, 0, 0, 2),
            (0, 0, 0, 0, 0),
            (EvidenceStance.SUPPORTS, EvidenceStance.OPPOSES),
            (),
            True,
            True,
            (),
        ),
        (
            ClaimStatus.CONTESTED,
            (
                EvidenceStance.SUPPORTS,
                EvidenceStance.OPPOSES,
                EvidenceStance.CONTEXT,
                EvidenceStance.INCONCLUSIVE,
            ),
            (1,),
            (1, 0, 1, 1, 3),
            (0, 1, 0, 0, 1),
            (EvidenceStance.SUPPORTS, EvidenceStance.OPPOSES),
            (EvidenceStance.OPPOSES,),
            False,
            False,
            ("no_active_opposition", "status_required_active_stance_missing"),
        ),
        (
            ClaimStatus.PROVISIONALLY_SUPPORTED,
            (EvidenceStance.SUPPORTS,),
            (0,),
            (0, 0, 0, 0, 0),
            (1, 0, 0, 0, 1),
            (EvidenceStance.SUPPORTS,),
            (EvidenceStance.SUPPORTS,),
            False,
            False,
            (
                "no_active_evidence",
                "no_active_support",
                "no_active_opposition",
                "status_required_active_stance_missing",
            ),
        ),
        (
            ClaimStatus.UNSUPPORTED,
            (EvidenceStance.OPPOSES,),
            (0,),
            (0, 0, 0, 0, 0),
            (0, 1, 0, 0, 1),
            (EvidenceStance.OPPOSES,),
            (EvidenceStance.OPPOSES,),
            False,
            False,
            (
                "no_active_evidence",
                "no_active_support",
                "no_active_opposition",
                "status_required_active_stance_missing",
            ),
        ),
    ],
)
def test_status_and_stance_matrix_is_structural_and_presence_based(
    lab: Lab,
    status: ClaimStatus,
    initial_stances: tuple[EvidenceStance, ...],
    withdraw_indexes: tuple[int, ...],
    expected_active: tuple[int, int, int, int, int],
    expected_withdrawn: tuple[int, int, int, int, int],
    required: tuple[EvidenceStance, ...],
    missing_required: tuple[EvidenceStance, ...],
    valid: bool,
    contradiction: bool,
    gap_codes: tuple[str, ...],
) -> None:
    seed = lab.seed_claim()
    cards = [lab.cite(seed, _QUOTES[stance], stance) for stance in initial_stances]
    if status is not ClaimStatus.OPEN:
        lab.research.set_claim_status(
            claim_id=seed.claim.id,
            status=status,
            reason="Record the workflow state before structural review.",
            expected_version=1,
            identity=lab.identity,
        )
    for index in withdraw_indexes:
        lab.evidence.withdraw_evidence(
            evidence_id=cards[index].id,
            reason="Café 東京 correction withdrew this exact card.",
            identity=lab.identity,
        )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    assert _counts(review.active_stance_counts) == expected_active
    assert _counts(review.withdrawn_stance_counts) == expected_withdrawn
    assert review.recorded_status.status is status
    assert review.recorded_status.required_active_stances == required
    assert review.recorded_status.missing_required_active_stances == missing_required
    assert review.recorded_status.evidence_valid is valid
    assert review.active_support_and_opposition_present is contradiction
    assert ("active_stance_contradiction" in review.impact_codes) is contradiction
    assert review.gap_codes == gap_codes
    assert review.complete is True
    assert review.truncated is False
    assert review.semantic_boundary.determines_truth is False
    assert review.semantic_boundary.calculates_confidence is False
    assert review.semantic_boundary.recommends_claim_status is False


def test_one_remaining_card_preserves_presence_without_becoming_confidence(lab: Lab) -> None:
    seed = lab.seed_claim()
    first = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    second = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="At least one active support card is present.",
        expected_version=1,
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=first.id,
        reason="One duplicate observation was withdrawn.",
        identity=lab.identity,
    )

    one_left = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id, claim_id=seed.claim.id
    )
    assert one_left.active_stance_counts.supports == 1
    assert one_left.withdrawn_stance_counts.supports == 1
    assert one_left.recorded_status.evidence_valid is True
    assert "recorded_status_requirement_unmet" not in one_left.impact_codes

    lab.evidence.withdraw_evidence(
        evidence_id=second.id,
        reason="The final supporting observation was withdrawn.",
        identity=lab.identity,
    )
    none_left = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id, claim_id=seed.claim.id
    )
    assert none_left.active_stance_counts.supports == 0
    assert none_left.recorded_status.evidence_valid is False
    assert "recorded_status_requirement_unmet" in none_left.impact_codes


def test_supersession_is_history_and_only_withdrawal_deactivates_a_card(lab: Lab) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        _QUOTES[EvidenceStance.SUPPORTS],
        EvidenceStance.SUPPORTS,
        supersedes_evidence_id=original.id,
    )
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="A supporting observation remains active.",
        expected_version=1,
        identity=lab.identity,
    )
    service = ClaimReviewService(lab.database)

    before = service.review_claim(mission_id=seed.mission.id, claim_id=seed.claim.id)
    assert before.active_stance_counts.supports == 2
    assert before.withdrawn_stance_counts.supports == 0
    assert [item.evidence_id for item in before.evidence] == [original.id, replacement.id]
    assert before.evidence[1].supersedes_evidence_id == original.id

    lab.evidence.withdraw_evidence(
        evidence_id=original.id,
        reason="The corrected card superseded this measurement.",
        identity=lab.identity,
    )
    after = service.review_claim(mission_id=seed.mission.id, claim_id=seed.claim.id)
    assert after.active_stance_counts.supports == 1
    assert after.withdrawn_stance_counts.supports == 1
    assert after.recorded_status.evidence_valid is True
    assert after.withdrawal_impacts[0].evidence_id == original.id
    assert after.withdrawal_impacts[0].direct_superseding_evidence_ids == (replacement.id,)
    assert "current_claim_status_requirement_unmet" not in after.withdrawal_impacts[0].effect_codes


def test_withdrawing_context_does_not_claim_it_invalidated_a_supported_status(lab: Lab) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    context = lab.cite(seed, _QUOTES[EvidenceStance.CONTEXT], EvidenceStance.CONTEXT)
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="Active support satisfies the recorded workflow status.",
        expected_version=1,
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=context.id,
        reason="The contextual note was corrected.",
        identity=lab.identity,
    )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    assert review.recorded_status.evidence_valid is True
    assert "recorded_status_requirement_unmet" not in review.impact_codes
    assert "current_claim_status_requirement_unmet" not in review.withdrawal_impacts[0].effect_codes


@dataclass(frozen=True, slots=True)
class _ImpactScenario:
    seed: ClaimSeed
    evidence: EvidenceCard
    active_finding: Finding
    retracted_finding: Finding
    optional_finding: Finding
    active_inference: AgentInference
    retracted_inference: AgentInference
    promoted_inference: AgentInference
    promoted_finding: Finding


def _impact_scenario(lab: Lab) -> _ImpactScenario:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="The exact support is provisionally sufficient for the workflow label.",
        expected_version=1,
        identity=lab.identity,
    )
    active_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="An active material finding uses the exact card.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The observation is bounded.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    retracted_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A material finding later retracted.",
        statement_kind=StatementKind.SOURCE_ASSERTION,
        status=FindingStatus.SUPPORTED,
        uncertainty="The assertion may need correction.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=retracted_finding.id,
        reason="The finding is no longer asserted.",
        identity=lab.identity,
    )
    optional_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=None,
        statement="A claim-less assumption keeps an optional citation.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="It is explicitly non-evidentiary.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )

    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "test-model-1", "test"),
        max_candidates=3,
        max_output_tokens=512,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inferences = tuple(
        adoption.adopt_inference(
            preview=preview,
            candidate_index=index,
            candidate=FindingCandidate(
                statement=f"Reviewed candidate inference {index}.",
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty="This remains model-authored and bounded.",
                evidence_ids=(evidence.id,),
            ),
            response_sha256=sha256(f"fake response {index}".encode()).hexdigest(),
            identity=lab.identity,
        )
        for index in range(3)
    )
    promoted_finding = adoption.promote_inference_to_finding(
        inference_id=inferences[2].id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    adoption.retract_inference(
        inference_id=inferences[1].id,
        reason="The second inference is no longer asserted.",
        identity=lab.identity,
    )
    adoption.retract_inference(
        inference_id=inferences[2].id,
        reason="The promoted draft is no longer independently asserted.",
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="Café 東京 correction withdrew the supporting measurement.",
        identity=lab.identity,
    )
    return _ImpactScenario(
        seed=seed,
        evidence=evidence,
        active_finding=active_finding,
        retracted_finding=retracted_finding,
        optional_finding=optional_finding,
        active_inference=inferences[0],
        retracted_inference=inferences[1],
        promoted_inference=inferences[2],
        promoted_finding=promoted_finding,
    )


def test_withdrawal_impact_keeps_asserted_historical_and_promoted_records_distinct(
    lab: Lab,
) -> None:
    scenario = _impact_scenario(lab)

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=scenario.seed.mission.id,
        claim_id=scenario.seed.claim.id,
    )

    assert review.recorded_status.status is ClaimStatus.PROVISIONALLY_SUPPORTED
    assert review.recorded_status.version == 2
    assert review.recorded_status.evidence_valid is False
    assert review.recorded_status.missing_required_active_stances == (EvidenceStance.SUPPORTS,)
    assert _counts(review.active_stance_counts) == (0, 0, 0, 0, 0)
    assert _counts(review.withdrawn_stance_counts) == (1, 0, 0, 0, 1)
    assert review.work.evidence_card_count == 1
    assert review.work.affected_finding_count == 4
    assert review.work.affected_inference_count == 3
    assert review.work.citation_relationship_count == 7
    assert review.work.distinct_snapshot_count == 1
    assert review.work.distinct_snapshot_bytes == len(scenario.seed.content)

    evidence = review.evidence[0]
    assert evidence.evidence_id == scenario.evidence.id
    assert evidence.snapshot_id == scenario.seed.snapshot.snapshot_id
    assert evidence.snapshot_sha256 == scenario.seed.snapshot.sha256
    assert evidence.start_byte == scenario.evidence.start_byte
    assert evidence.end_byte == scenario.evidence.end_byte
    quote_bytes = scenario.seed.content[evidence.start_byte : evidence.end_byte]
    assert evidence.quote_byte_length == len(quote_bytes)
    assert evidence.quote_sha256 == sha256(quote_bytes).hexdigest()
    assert evidence.withdrawal is not None
    assert evidence.withdrawal.reason == "Café 東京 correction withdrew the supporting measurement."

    findings = {item.finding_id: item for item in review.affected_findings}
    assert set(findings) == {
        scenario.active_finding.id,
        scenario.retracted_finding.id,
        scenario.optional_finding.id,
        scenario.promoted_finding.id,
    }
    for finding_id in (scenario.active_finding.id, scenario.promoted_finding.id):
        assert findings[finding_id].material is True
        assert findings[finding_id].retraction is None
        assert findings[finding_id].withdrawn_target_evidence_ids == (scenario.evidence.id,)
        assert findings[finding_id].effect_codes == (
            "mission_synthesis_blocked_by_live_material_finding",
            "claim_synthesis_blocked_by_live_material_finding",
        )
    assert findings[scenario.retracted_finding.id].effect_codes == (
        "finding_excluded_from_synthesis",
        "history_retained",
    )
    assert findings[scenario.retracted_finding.id].retraction is not None
    assert findings[scenario.optional_finding.id].claim_id is None
    assert findings[scenario.optional_finding.id].material is False
    assert findings[scenario.optional_finding.id].effect_codes == (
        "optional_statement_retains_withdrawn_citation",
    )

    inferences = {item.inference_id: item for item in review.affected_inferences}
    assert set(inferences) == {
        scenario.active_inference.id,
        scenario.retracted_inference.id,
        scenario.promoted_inference.id,
    }
    assert inferences[scenario.active_inference.id].active_citation_policy_satisfied is False
    assert inferences[scenario.active_inference.id].effect_codes == (
        "live_inference_citation_no_longer_active",
        "inference_promotion_blocked",
    )
    assert inferences[scenario.retracted_inference.id].effect_codes == (
        "inference_excluded_from_markdown",
        "history_retained",
    )
    promoted = inferences[scenario.promoted_inference.id]
    assert promoted.retraction is not None
    assert promoted.promotion is not None
    assert promoted.promotion.id.startswith("inp_")
    assert promoted.promotion.finding_id == scenario.promoted_finding.id
    assert promoted.promotion.creator_id == lab.identity.actor_id
    assert promoted.promotion.run_id == lab.identity.run_id
    assert promoted.promotion.created_at == fixed_clock()
    assert promoted.promotion.finding_retracted is False
    assert promoted.effect_codes == (
        "inference_excluded_from_markdown",
        "history_retained",
        "promoted_finding_remains_independently_asserted",
    )

    impact = review.withdrawal_impacts[0]
    assert impact.evidence_id == scenario.evidence.id
    assert impact.active_material_finding_ids == (
        scenario.active_finding.id,
        scenario.promoted_finding.id,
    )
    assert impact.active_optional_finding_ids == (scenario.optional_finding.id,)
    assert impact.retracted_finding_ids == (scenario.retracted_finding.id,)
    assert impact.active_inference_ids == (scenario.active_inference.id,)
    assert impact.retracted_inference_ids == (
        scenario.retracted_inference.id,
        scenario.promoted_inference.id,
    )
    assert impact.direct_superseding_evidence_ids == ()
    assert review.impact_codes == (
        "withdrawn_evidence_history_present",
        "recorded_status_requirement_unmet",
        "live_material_finding_uses_withdrawn_evidence",
        "optional_statement_uses_withdrawn_evidence",
        "retracted_finding_history_present",
        "live_inference_uses_withdrawn_evidence",
        "retracted_inference_history_present",
        "promoted_finding_remains_independently_asserted",
    )
    cues = {item.code: item.record_ids for item in review.review_cues}
    assert cues["live_material_finding_uses_withdrawn_evidence"] == (
        scenario.active_finding.id,
        scenario.promoted_finding.id,
    )
    assert cues["promoted_finding_remains_independently_asserted"] == (
        scenario.promoted_inference.id,
    )


def test_retracting_a_promoted_finding_removes_the_independent_assertion_cue(lab: Lab) -> None:
    scenario = _impact_scenario(lab)
    lab.research.retract_finding(
        finding_id=scenario.promoted_finding.id,
        reason="The promoted human finding is also no longer asserted.",
        identity=lab.identity,
    )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=scenario.seed.mission.id,
        claim_id=scenario.seed.claim.id,
    )

    promoted_inference = next(
        item
        for item in review.affected_inferences
        if item.inference_id == scenario.promoted_inference.id
    )
    assert promoted_inference.promotion is not None
    assert promoted_inference.promotion.finding_retracted is True
    assert "promoted_finding_remains_independently_asserted" not in promoted_inference.effect_codes
    assert "promoted_finding_remains_independently_asserted" not in review.impact_codes
    promoted_finding = next(
        item for item in review.affected_findings if item.finding_id == scenario.promoted_finding.id
    )
    assert promoted_finding.retraction is not None
    assert promoted_finding.effect_codes == ("finding_excluded_from_synthesis", "history_retained")


def test_receipt_is_byte_deterministic_and_binds_every_structural_field(lab: Lab) -> None:
    scenario = _impact_scenario(lab)
    service = ClaimReviewService(lab.database)

    first = service.review_claim(
        mission_id=scenario.seed.mission.id, claim_id=scenario.seed.claim.id
    )
    second = service.review_claim(
        mission_id=scenario.seed.mission.id, claim_id=scenario.seed.claim.id
    )

    assert first == second
    assert _canonical_bytes(asdict(first)) == _canonical_bytes(asdict(second))
    payload = asdict(first)
    digest = payload.pop("review_receipt_sha256")
    assert digest == sha256(_canonical_bytes(payload)).hexdigest()
    assert first.schema_version == "minerva.claim-review.v1"
    assert first.algorithm == "structural-ledger-review"
    assert first.algorithm_version == "1"
    assert first.completion_policy == "complete_or_refuse"
    assert first.complete is True
    assert first.truncated is False


def test_mission_scope_is_non_reflective_and_sql_shaped_ids_are_inert(lab: Lab) -> None:
    first = lab.seed_claim()
    foreign = lab.seed_claim(content=b"Foreign mission evidence must never leak.\n")
    first_review = ClaimReviewService(lab.database).review_claim(
        mission_id=first.mission.id, claim_id=first.claim.id
    )

    encoded = _canonical_bytes(asdict(first_review)).decode()
    assert foreign.mission.id not in encoded
    assert foreign.claim.id not in encoded
    failures: list[IntegrityError] = []
    for claim_id in (foreign.claim.id, "clm_" + "f" * 32, "' OR 1=1 --"):
        with pytest.raises(IntegrityError) as caught:
            ClaimReviewService(lab.database).review_claim(
                mission_id=first.mission.id,
                claim_id=claim_id,
            )
        failures.append(caught.value)
    assert {error.code for error in failures} == {"claim_review_scope_invalid"}
    assert len({error.public_message for error in failures}) == 1

    with pytest.raises(NotFoundError) as missing:
        ClaimReviewService(lab.database).review_claim(
            mission_id="mis_" + "f" * 32,
            claim_id=first.claim.id,
        )
    assert missing.value.code == "mission_not_found"


@pytest.mark.parametrize(
    "bounds",
    [
        ClaimReviewBounds(max_evidence_cards=0),
        ClaimReviewBounds(max_evidence_cards=True),
        ClaimReviewBounds(max_evidence_cards=201),
        ClaimReviewBounds(max_affected_records=0),
        ClaimReviewBounds(max_affected_records=501),
        ClaimReviewBounds(max_relationships=0),
        ClaimReviewBounds(max_relationships=5_001),
        ClaimReviewBounds(max_snapshot_bytes=0),
        ClaimReviewBounds(max_snapshot_bytes=67_108_865),
        ClaimReviewBounds(max_sqlite_vm_steps=999),
        ClaimReviewBounds(max_sqlite_vm_steps=16_000_001),
    ],
)
def test_invalid_bounds_are_rejected(lab: Lab, bounds: ClaimReviewBounds) -> None:
    seed = lab.seed_claim()
    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=bounds,
        )
    assert caught.value.code == "claim_review_bounds_invalid"


def test_wrong_bounds_object_is_rejected(lab: Lab) -> None:
    seed = lab.seed_claim()
    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=None,  # type: ignore[arg-type]
        )
    assert caught.value.code == "claim_review_bounds_invalid"


def test_evidence_and_snapshot_work_limits_refuse_instead_of_truncating(lab: Lab) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    lab.cite(seed, _QUOTES[EvidenceStance.OPPOSES], EvidenceStance.OPPOSES)
    service = ClaimReviewService(lab.database)

    with pytest.raises(IntegrityError) as evidence_limit:
        service.review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_evidence_cards=1),
        )
    assert evidence_limit.value.code == "claim_review_work_limit"

    with pytest.raises(IntegrityError) as snapshot_limit:
        service.review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_snapshot_bytes=len(seed.content) - 1),
        )
    assert snapshot_limit.value.code == "claim_review_work_limit"


def test_affected_record_and_relationship_limits_refuse_complete_review(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, _QUOTES[EvidenceStance.OPPOSES], EvidenceStance.OPPOSES)
    findings = tuple(
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement=f"Retracted material finding {index}.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.CONTESTED,
            uncertainty="",
            evidence_ids=(support.id, opposition.id),
            identity=lab.identity,
        )
        for index in range(2)
    )
    for finding in findings:
        lab.research.retract_finding(
            finding_id=finding.id,
            reason="Retraction keeps the record inspectable.",
            identity=lab.identity,
        )
    service = ClaimReviewService(lab.database)

    with pytest.raises(IntegrityError) as record_limit:
        service.review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_affected_records=1),
        )
    assert record_limit.value.code == "claim_review_work_limit"

    with pytest.raises(IntegrityError) as relationship_limit:
        service.review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_relationships=3),
        )
    assert relationship_limit.value.code == "claim_review_work_limit"


def test_sqlite_vm_work_limit_maps_interrupt_to_domain_refusal(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    monkeypatch.setattr(review_service_module, "_QUERY_PROGRESS_GRANULARITY", 1)
    monkeypatch.setattr(review_service_module, "_MIN_SQLITE_VM_STEPS", 1)

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_sqlite_vm_steps=1),
        )
    assert caught.value.code == "claim_review_work_limit"


def test_review_is_query_only_and_mutates_nothing_or_invokes_provider_or_network(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    before_dump = _database_dump(lab.database)
    before_bytes = lab.database.path.read_bytes()
    trace: list[str] = []
    real_read = lab.database.read

    @contextmanager
    def traced_read() -> Any:
        with real_read() as connection:
            connection.set_trace_callback(trace.append)
            yield connection

    def transaction_forbidden() -> object:
        raise AssertionError("Claim Review must not open a write transaction")

    def provider_forbidden(_: ModelProvider) -> object:
        raise AssertionError("Claim Review must not construct a model provider")

    def network_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Claim Review must not construct a network socket")

    monkeypatch.setattr(lab.database, "read", traced_read)
    monkeypatch.setattr(lab.database, "transaction", transaction_forbidden)
    monkeypatch.setattr(ai_integrations, "candidate_provider", provider_forbidden)
    monkeypatch.setattr(socket, "socket", network_forbidden)

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    assert any(statement.strip().upper() == "PRAGMA QUERY_ONLY = ON" for statement in trace)
    assert review.semantic_boundary.read_only is True
    assert review.semantic_boundary.writes_audit_event is False
    assert review.semantic_boundary.invokes_model_provider is False
    assert review.semantic_boundary.invokes_network is False
    assert review.semantic_boundary.alters_claim_status is False
    assert review.semantic_boundary.creates_or_withdraws_evidence is False
    assert review.semantic_boundary.creates_or_retracts_findings is False
    assert review.semantic_boundary.creates_retracts_or_promotes_inferences is False
    assert _database_dump(lab.database) == before_dump
    assert lab.database.path.read_bytes() == before_bytes


def test_tampered_snapshot_and_citation_fail_closed(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER evidence_no_update")
        connection.execute(
            "UPDATE evidence_cards SET quote = ? WHERE id = ?",
            ("A forged quote.", evidence.id),
        )
    with pytest.raises(IntegrityError) as citation:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id, claim_id=seed.claim.id
        )
    assert citation.value.code == "citation_tampered"

    second = lab.seed_claim()
    lab.cite(second, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (b"Z" * len(second.content), second.snapshot.snapshot_id),
        )
    with pytest.raises(IntegrityError) as snapshot:
        ClaimReviewService(lab.database).review_claim(
            mission_id=second.mission.id, claim_id=second.claim.id
        )
    assert snapshot.value.code == "snapshot_tampered"


def test_tampered_finding_and_inference_claim_scope_fail_closed(lab: Lab) -> None:
    seed = lab.seed_claim()
    target = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    other_claim = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=seed.question.id,
        statement="A separate proposition in the same mission.",
        falsification_criteria="An opposing exact observation would falsify it.",
        identity=lab.identity,
    )
    foreign = lab.evidence.add_evidence(
        mission_id=seed.mission.id,
        claim_id=other_claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        start_byte=target.start_byte,
        end_byte=target.end_byte,
        quote=target.quote,
        stance=EvidenceStance.SUPPORTS,
        identity=lab.identity,
    )
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A finding whose citation link will be tampered.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(target.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=finding.id,
        reason="Keep the finding selected by historical retraction.",
        identity=lab.identity,
    )
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "test-model", "test"),
        max_candidates=1,
        max_output_tokens=256,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inference = adoption.adopt_inference(
        preview=preview,
        candidate_index=0,
        candidate=FindingCandidate(
            statement="An inference whose citation link will be tampered.",
            statement_kind=StatementKind.AGENT_INFERENCE,
            uncertainty="The test changes only its relationship row.",
            evidence_ids=(target.id,),
        ),
        response_sha256=sha256(b"scope test response").hexdigest(),
        identity=lab.identity,
    )
    adoption.retract_inference(
        inference_id=inference.id,
        reason="Keep the inference selected by historical retraction.",
        identity=lab.identity,
    )

    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER finding_citations_no_update")
        connection.execute(
            "UPDATE finding_citations SET evidence_id = ? WHERE finding_id = ?",
            (foreign.id, finding.id),
        )
    with pytest.raises(IntegrityError) as finding_scope:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id, claim_id=seed.claim.id
        )
    assert finding_scope.value.code == "finding_citation_scope_invalid"

    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER agent_inference_citations_no_update")
        connection.execute(
            "UPDATE agent_inference_citations SET evidence_id = ? WHERE inference_id = ?",
            (foreign.id, inference.id),
        )
    with pytest.raises(IntegrityError) as inference_scope:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id, claim_id=seed.claim.id
        )
    # The finding remains tampered too, so restore its link only inside this
    # deliberately trigger-disabled corruption fixture before isolating inference.
    assert inference_scope.value.code == "finding_citation_scope_invalid"
    with lab.database.transaction() as connection:
        connection.execute(
            "UPDATE finding_citations SET evidence_id = ? WHERE finding_id = ?",
            (target.id, finding.id),
        )
    with pytest.raises(IntegrityError) as isolated_inference_scope:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id, claim_id=seed.claim.id
        )
    assert isolated_inference_scope.value.code == "inference_citation_scope_invalid"


def test_tampered_supersession_target_outside_claim_fails_closed(lab: Lab) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, _QUOTES[EvidenceStance.SUPPORTS], EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        _QUOTES[EvidenceStance.SUPPORTS],
        EvidenceStance.SUPPORTS,
        supersedes_evidence_id=original.id,
    )
    other_claim = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=seed.question.id,
        statement="Another same-mission proposition.",
        falsification_criteria="An opposing observation would falsify it.",
        identity=lab.identity,
    )
    foreign = lab.evidence.add_evidence(
        mission_id=seed.mission.id,
        claim_id=other_claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        start_byte=original.start_byte,
        end_byte=original.end_byte,
        quote=original.quote,
        stance=EvidenceStance.SUPPORTS,
        identity=lab.identity,
    )
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER evidence_no_update")
        connection.execute(
            "UPDATE evidence_cards SET supersedes_evidence_id = ? WHERE id = ?",
            (foreign.id, replacement.id),
        )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id, claim_id=seed.claim.id
        )
    assert caught.value.code == "evidence_supersession_invalid"


def test_pre_v5_database_requires_explicit_migration_before_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy = Database(tmp_path / "legacy-v4.db")
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])
    assert legacy.initialize() == 4
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-review",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify explicit migration before claim review",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy review mission",
        objective="Verify schema-free review still requires the current database contract.",
        identity=identity,
    )
    question = research.add_question(
        mission_id=mission.id,
        text="Can a v4 database be reviewed before explicit migration?",
        identity=identity,
    )
    claim = research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="Claim Review refuses stale migration state.",
        falsification_criteria="A successful pre-migration review would falsify it.",
        identity=identity,
    )
    SourceService(legacy, clock=fixed_clock, id_factory=ids).import_bytes(
        mission_id=mission.id,
        content=b"legacy review corpus\n",
        original_label="legacy.txt",
        media_type="text/plain",
        identity=identity,
    )

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    with pytest.raises(IntegrityError) as required:
        ClaimReviewService(legacy).review_claim(mission_id=mission.id, claim_id=claim.id)
    assert required.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    review = ClaimReviewService(legacy).review_claim(mission_id=mission.id, claim_id=claim.id)
    assert review.complete is True
    assert review.work.evidence_card_count == 0
    assert latest_schema_version() == 5
