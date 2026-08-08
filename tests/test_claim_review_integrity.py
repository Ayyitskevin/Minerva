from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from hashlib import sha256
from inspect import signature
from typing import Any, cast

import pytest

import minerva.review.service as review_service_module
from conftest import ClaimSeed, Lab, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import (
    AgentInference,
    FindingCandidate,
    ModelProvider,
    ProviderSelection,
)
from minerva.assist.service import AssistanceService
from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.research.models import ClaimStatus, Finding, FindingStatus, StatementKind
from minerva.review import ClaimReviewBounds, ClaimReviewService

_SUPPORT_QUOTE = "Evidence supports the claim."
_SAFE_INTEGRITY_MESSAGE = "Stored claim review state is invalid."


def test_public_claim_review_cannot_accept_a_caller_forged_snapshot_cache(lab: Lab) -> None:
    seed = lab.seed_claim()
    service = ClaimReviewService(lab.database)
    parameters = signature(service.review_claim).parameters

    assert "_connection" not in parameters
    assert "_snapshot_cache" not in parameters
    with pytest.raises(TypeError):
        cast(Any, service.review_claim)(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            _snapshot_cache={},
        )


def test_public_claim_review_snapshot_bound_remains_distinct_blob_bytes(lab: Lab) -> None:
    quote = "Q" * 100_000
    seed = lab.seed_claim(content=quote.encode("utf-8"))
    lab.cite(seed, quote, EvidenceStance.SUPPORTS)
    lab.cite(seed, quote, EvidenceStance.CONTEXT)

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        bounds=ClaimReviewBounds(
            max_evidence_cards=2,
            max_snapshot_bytes=100_000,
        ),
    )

    assert review.work.evidence_card_count == 2
    assert review.work.distinct_snapshot_count == 1
    assert review.work.distinct_snapshot_bytes == 100_000


def _raw_corrupt(
    database: Database,
    statements: tuple[tuple[str, tuple[object, ...]], ...],
    *,
    ignore_checks: bool = False,
) -> None:
    connection = sqlite3.connect(database.path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        if ignore_checks:
            connection.execute("PRAGMA ignore_check_constraints = ON")
        for statement, parameters in statements:
            connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


def _adopt_inference(
    lab: Lab,
    seed: ClaimSeed,
    evidence: EvidenceCard,
    *,
    statement: str,
) -> tuple[AdoptionService, AgentInference]:
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "integrity-test-model", "test"),
        max_candidates=1,
        max_output_tokens=256,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inference = adoption.adopt_inference(
        preview=preview,
        candidate_index=0,
        candidate=FindingCandidate(
            statement=statement,
            statement_kind=StatementKind.AGENT_INFERENCE,
            uncertainty="This model-authored statement remains evidence-bounded.",
            evidence_ids=(evidence.id,),
        ),
        response_sha256=sha256(statement.encode("utf-8")).hexdigest(),
        identity=lab.identity,
    )
    return adoption, inference


def _add_material_finding(
    lab: Lab,
    seed: ClaimSeed,
    evidence: EvidenceCard,
    *,
    statement: str,
) -> Finding:
    return lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement=statement,
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The exact observation remains bounded.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )


@pytest.mark.parametrize(
    "invalid_mission_id",
    [
        None,
        7,
        b"mis_00000000000000000000000000000000",
        "",
        " mis_00000000000000000000000000000000",
        "mis_0000000000000000000000000000000",
        "mis_000000000000000000000000000000000",
        "MIS_00000000000000000000000000000000",
        "mis_0000000000000000000000000000000g",
    ],
)
def test_invalid_mission_input_maps_to_stable_non_reflective_error(
    lab: Lab,
    invalid_mission_id: object,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(NotFoundError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=cast(str, invalid_mission_id),
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "mission_not_found"
    assert caught.value.public_message == "The requested resource was not found."
    assert caught.value.http_status == 404
    if reflected := str(invalid_mission_id):
        assert reflected not in caught.value.public_message


@pytest.mark.parametrize(
    "invalid_claim_id",
    [
        None,
        7,
        b"clm_00000000000000000000000000000000",
        "",
        " clm_00000000000000000000000000000000",
        "clm_0000000000000000000000000000000",
        "clm_000000000000000000000000000000000",
        "CLM_00000000000000000000000000000000",
        "clm_0000000000000000000000000000000g",
    ],
)
def test_invalid_claim_input_maps_to_stable_non_reflective_error(
    lab: Lab,
    invalid_claim_id: object,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=cast(str, invalid_claim_id),
        )

    assert caught.value.code == "claim_review_scope_invalid"
    assert caught.value.public_message == "The claim review scope is invalid for this mission."
    assert caught.value.http_status == 422
    if reflected := str(invalid_claim_id):
        assert reflected not in caught.value.public_message


@pytest.mark.parametrize("corruption", ["self", "cycle"])
def test_self_or_cyclic_evidence_supersession_corruption_refuses(
    lab: Lab,
    corruption: str,
) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        _SUPPORT_QUOTE,
        EvidenceStance.SUPPORTS,
        supersedes_evidence_id=original.id,
    )
    if corruption == "self":
        evidence_id = original.id
        supersedes_id = original.id
    else:
        evidence_id = original.id
        supersedes_id = replacement.id
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER evidence_no_update", ()),
            (
                "UPDATE evidence_cards SET supersedes_evidence_id = ? WHERE id = ?",
                (supersedes_id, evidence_id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "evidence_supersession_invalid"
    assert caught.value.public_message == "Stored evidence history is invalid."


def test_snapshot_actual_blob_length_is_checked_before_bound_and_materialization(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    tampered_content = b"X" * 4_096
    configured_bound = len(seed.content)
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER snapshots_no_update", ()),
            (
                "UPDATE source_snapshots SET content = ?, byte_length = ? WHERE id = ?",
                (tampered_content, 1, seed.snapshot.snapshot_id),
            ),
        ),
        ignore_checks=True,
    )
    with closing(sqlite3.connect(lab.database.path)) as connection:
        stored = connection.execute(
            """
            SELECT TYPEOF(content), LENGTH(content), byte_length
            FROM source_snapshots WHERE id = ?
            """,
            (seed.snapshot.snapshot_id,),
        ).fetchone()
    assert stored == ("blob", len(tampered_content), 1)
    assert len(tampered_content) > configured_bound

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("snapshot preflight must refuse before citation materialization")

    monkeypatch.setattr(
        review_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_snapshot_bytes=configured_bound),
        )

    assert caught.value.code == "snapshot_tampered"
    assert caught.value.public_message == "Stored source snapshot integrity failed."


@pytest.mark.parametrize("corruption", ["dangling", "foreign_mission", "wrong_claim"])
def test_selected_promotion_target_corruption_refuses(
    lab: Lab,
    corruption: str,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        evidence,
        statement="A promoted inference whose target link will be corrupted.",
    )
    adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )

    if corruption == "dangling":
        corrupted_target_id = "fnd_" + "f" * 32
    elif corruption == "foreign_mission":
        foreign = lab.seed_claim(content=b"Evidence supports the claim.\n")
        foreign_evidence = lab.cite(foreign, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
        corrupted_target_id = _add_material_finding(
            lab,
            foreign,
            foreign_evidence,
            statement="FOREIGN-MISSION-PROMOTION-TARGET",
        ).id
    else:
        other_claim = lab.research.add_claim(
            mission_id=seed.mission.id,
            question_id=seed.question.id,
            statement="A different proposition in the same mission.",
            falsification_criteria="An opposing exact observation would falsify it.",
            identity=lab.identity,
        )
        corrupted_target_id = lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=other_claim.id,
            statement="WRONG-CLAIM-PROMOTION-TARGET",
            statement_kind=StatementKind.ASSUMPTION,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="This assumption is intentionally uncited.",
            evidence_ids=(),
            identity=lab.identity,
        ).id

    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="The cited observation was withdrawn after promotion.",
        identity=lab.identity,
    )
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER agent_inference_promotions_no_update", ()),
            (
                "UPDATE agent_inference_promotions SET finding_id = ? WHERE inference_id = ?",
                (corrupted_target_id, inference.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert "PROMOTION-TARGET" not in caught.value.public_message


def test_same_claim_unrelated_promotion_target_refuses_copy_mismatch(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        support,
        statement="The inference text must be copied exactly by its promoted finding.",
    )
    adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    unrelated = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="UNRELATED-SAME-CLAIM-PROMOTION-TARGET",
        statement_kind=StatementKind.SOURCE_ASSERTION,
        status=FindingStatus.CONTESTED,
        uncertainty="This uncertainty was not copied from the inference.",
        evidence_ids=(opposition.id,),
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="Keep the inference selected while its promotion target is corrupted.",
        identity=lab.identity,
    )
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER agent_inference_promotions_no_update", ()),
            (
                "UPDATE agent_inference_promotions SET finding_id = ? WHERE inference_id = ?",
                (unrelated.id, inference.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert unrelated.statement not in caught.value.public_message


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("statement", "A tampered promoted statement."),
        ("statement_kind", StatementKind.SOURCE_ASSERTION.value),
        ("uncertainty", "A tampered promoted uncertainty."),
    ],
)
def test_each_promoted_finding_copy_field_is_verified(
    lab: Lab,
    column: str,
    replacement: str,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        evidence,
        statement="Each copied promotion field must remain exact.",
    )
    promoted = adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    adoption.retract_inference(
        inference_id=inference.id,
        reason="Keep the inference selected while its promoted finding is corrupted.",
        identity=lab.identity,
    )
    assert column in {"statement", "statement_kind", "uncertainty"}
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER findings_no_update", ()),
            (
                f"UPDATE findings SET {column} = ? WHERE id = ?",  # noqa: S608
                (replacement, promoted.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert replacement not in caught.value.public_message


def test_genuine_promotion_with_tampered_citation_lineage_refuses(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        support,
        statement="The promoted finding must retain the inference's exact citation set.",
    )
    promoted = adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="Select the inference after its promoted finding citation is corrupted.",
        identity=lab.identity,
    )
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER finding_citations_no_update", ()),
            (
                "UPDATE finding_citations SET evidence_id = ? WHERE finding_id = ?",
                (opposition.id, promoted.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE


def test_live_inference_is_included_through_retracted_promotion_target(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        evidence,
        statement="The active inference remains linked to its retracted promoted finding.",
    )
    promoted_finding = adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=promoted_finding.id,
        reason="Human review retracted the promoted assertion.",
        identity=lab.identity,
    )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    affected = {item.inference_id: item for item in review.affected_inferences}
    assert set(affected) == {inference.id}
    assert affected[inference.id].retraction is None
    assert affected[inference.id].active_citation_policy_satisfied is True
    effect_code = "live_inference_remains_after_promoted_finding_retraction"
    assert affected[inference.id].effect_codes == (effect_code,)
    promotion = affected[inference.id].promotion
    assert promotion is not None
    assert promotion.finding_id == promoted_finding.id
    assert promotion.finding_retracted is True
    assert effect_code in review.impact_codes
    cue = next(item for item in review.review_cues if item.code == effect_code)
    assert cue.record_ids == (inference.id,)


def test_promoted_live_inference_with_later_withdrawal_is_not_marked_promotion_blocked(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        evidence,
        statement="The live inference was promoted before its evidence was withdrawn.",
    )
    adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="The observation was withdrawn after the human promotion.",
        identity=lab.identity,
    )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    affected = next(
        item for item in review.affected_inferences if item.inference_id == inference.id
    )
    assert affected.retraction is None
    assert affected.promotion is not None
    assert affected.active_citation_policy_satisfied is False
    assert affected.effect_codes == ("live_inference_citation_no_longer_active",)
    assert "inference_promotion_blocked" not in review.withdrawal_impacts[0].effect_codes


def test_affected_discovery_plans_start_from_mission_owned_records(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    plans = (
        (
            """
            EXPLAIN QUERY PLAN
            SELECT DISTINCT finding.id AS finding_id
            FROM findings AS finding INDEXED BY idx_findings_mission
            JOIN finding_citations AS citation INDEXED BY idx_finding_citations_finding
              ON citation.finding_id = finding.id
            WHERE finding.mission_id = ? AND citation.evidence_id IN (?)
            ORDER BY finding.id ASC
            LIMIT ?
            """,
            "idx_findings_mission",
            "idx_finding_citations_finding",
        ),
        (
            """
            EXPLAIN QUERY PLAN
            SELECT DISTINCT inference.id AS inference_id
            FROM agent_inferences AS inference INDEXED BY idx_agent_inferences_claim
            JOIN agent_inference_citations AS citation
              INDEXED BY idx_agent_inference_citations_inference
              ON citation.inference_id = inference.id
            WHERE inference.mission_id = ? AND inference.claim_id = ?
              AND citation.evidence_id IN (?)
            ORDER BY inference.id ASC
            LIMIT ?
            """,
            "idx_agent_inferences_claim",
            "idx_agent_inference_citations_inference",
        ),
    )

    with lab.database.read() as connection:
        finding_details = tuple(
            str(row["detail"])
            for row in connection.execute(
                plans[0][0],
                (seed.mission.id, evidence.id, 201),
            )
        )
        inference_details = tuple(
            str(row["detail"])
            for row in connection.execute(
                plans[1][0],
                (seed.mission.id, seed.claim.id, evidence.id, 201),
            )
        )

    for details, (_, owner_index, relationship_index) in zip(
        (finding_details, inference_details), plans, strict=True
    ):
        owner_position = next(
            index for index, detail in enumerate(details) if owner_index in detail
        )
        relationship_position = next(
            index for index, detail in enumerate(details) if relationship_index in detail
        )
        assert details[owner_position].startswith("SEARCH ")
        assert "mission_id=?" in details[owner_position]
        assert owner_position < relationship_position


@pytest.mark.parametrize("owner_kind", ["finding", "inference"])
def test_cross_mission_citation_relationship_does_not_select_or_leak_foreign_owner(
    lab: Lab,
    owner_kind: str,
) -> None:
    target = lab.seed_claim()
    target_evidence = lab.cite(target, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    lab.evidence.withdraw_evidence(
        evidence_id=target_evidence.id,
        reason="Select relationships connected to this target evidence.",
        identity=lab.identity,
    )
    foreign = lab.seed_claim(content=b"Evidence supports the claim.\n")
    foreign_evidence = lab.cite(foreign, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    foreign_statement = f"FOREIGN-{owner_kind.upper()}-STATEMENT-MUST-NOT-LEAK"
    if owner_kind == "finding":
        owner_id = _add_material_finding(
            lab,
            foreign,
            foreign_evidence,
            statement=foreign_statement,
        ).id
        table = "finding_citations"
        owner_column = "finding_id"
        trigger = "finding_citations_no_update"
    else:
        _, foreign_inference = _adopt_inference(
            lab,
            foreign,
            foreign_evidence,
            statement=foreign_statement,
        )
        owner_id = foreign_inference.id
        table = "agent_inference_citations"
        owner_column = "inference_id"
        trigger = "agent_inference_citations_no_update"
    _raw_corrupt(
        lab.database,
        (
            (f"DROP TRIGGER {trigger}", ()),
            (
                f"UPDATE {table} SET evidence_id = ? WHERE {owner_column} = ?",  # noqa: S608
                (target_evidence.id, owner_id),
            ),
        ),
    )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=target.mission.id,
        claim_id=target.claim.id,
    )

    serialized = repr(asdict(review))
    assert foreign_statement not in serialized
    assert foreign.mission.id not in serialized
    assert foreign.claim.id not in serialized
    assert review.affected_findings == ()
    assert review.affected_inferences == ()


@pytest.mark.parametrize("owner_kind", ["finding", "inference"])
def test_selected_target_owner_citation_with_tampered_mission_refuses(
    lab: Lab,
    owner_kind: str,
) -> None:
    target = lab.seed_claim()
    target_evidence = lab.cite(target, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    owner_statement = f"TARGET-{owner_kind.upper()}-OWNER"
    if owner_kind == "finding":
        owner_id = _add_material_finding(
            lab,
            target,
            target_evidence,
            statement=owner_statement,
        ).id
        table = "finding_citations"
        owner_column = "finding_id"
        trigger = "finding_citations_no_update"
    else:
        _, target_inference = _adopt_inference(
            lab,
            target,
            target_evidence,
            statement=owner_statement,
        )
        owner_id = target_inference.id
        table = "agent_inference_citations"
        owner_column = "inference_id"
        trigger = "agent_inference_citations_no_update"
    foreign = lab.seed_claim(content=b"Evidence supports the claim.\n")
    lab.evidence.withdraw_evidence(
        evidence_id=target_evidence.id,
        reason="Keep the target owner within the review's affected set.",
        identity=lab.identity,
    )
    _raw_corrupt(
        lab.database,
        (
            (f"DROP TRIGGER {trigger}", ()),
            (
                f"UPDATE {table} SET mission_id = ? WHERE {owner_column} = ?",  # noqa: S608
                (foreign.mission.id, owner_id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=target.mission.id,
            claim_id=target.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert owner_statement not in caught.value.public_message
    assert foreign.claim.statement not in caught.value.public_message


@pytest.mark.parametrize("owner_kind", ["finding", "inference"])
def test_selected_affected_owner_with_dangling_evidence_citation_refuses_before_receipt(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    owner_kind: str,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    if owner_kind == "finding":
        finding = _add_material_finding(
            lab,
            seed,
            evidence,
            statement="A retracted finding whose citation will become dangling.",
        )
        lab.research.retract_finding(
            finding_id=finding.id,
            reason="Keep the finding selected independently of its citation.",
            identity=lab.identity,
        )
        owner_id = finding.id
        table = "finding_citations"
        owner_column = "finding_id"
        trigger = "finding_citations_no_update"
    else:
        adoption, inference = _adopt_inference(
            lab,
            seed,
            evidence,
            statement="A retracted inference whose citation will become dangling.",
        )
        adoption.retract_inference(
            inference_id=inference.id,
            reason="Keep the inference selected independently of its citation.",
            identity=lab.identity,
        )
        owner_id = inference.id
        table = "agent_inference_citations"
        owner_column = "inference_id"
        trigger = "agent_inference_citations_no_update"
    dangling_evidence_id = "evd_" + "f" * 32
    _raw_corrupt(
        lab.database,
        (
            (f"DROP TRIGGER {trigger}", ()),
            (
                f"UPDATE {table} SET evidence_id = ? WHERE {owner_column} = ?",  # noqa: S608
                (dangling_evidence_id, owner_id),
            ),
        ),
    )

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("dangling citation preflight must refuse before materialization")

    monkeypatch.setattr(
        review_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert dangling_evidence_id not in caught.value.public_message


def test_target_evidence_with_dangling_snapshot_refuses_before_materialization(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    dangling_snapshot_id = "snp_" + "f" * 32
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER evidence_no_update", ()),
            (
                "UPDATE evidence_cards SET snapshot_id = ? WHERE id = ?",
                (dangling_snapshot_id, evidence.id),
            ),
        ),
    )

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("dangling snapshot preflight must refuse before materialization")

    monkeypatch.setattr(
        review_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "snapshot_tampered"
    assert caught.value.public_message == "Stored source snapshot integrity failed."
    assert dangling_snapshot_id not in caught.value.public_message


def test_claim_only_evidence_discovery_refuses_foreign_mission_tampering(lab: Lab) -> None:
    target = lab.seed_claim()
    evidence = lab.cite(target, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    foreign = lab.seed_claim(content=b"Evidence supports the claim.\n")
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER evidence_no_update", ()),
            (
                "UPDATE evidence_cards SET mission_id = ? WHERE id = ?",
                (foreign.mission.id, evidence.id),
            ),
        ),
    )
    with closing(sqlite3.connect(lab.database.path)) as connection:
        stored_scope = connection.execute(
            "SELECT mission_id, claim_id FROM evidence_cards WHERE id = ?",
            (evidence.id,),
        ).fetchone()
    assert stored_scope == (foreign.mission.id, target.claim.id)

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=target.mission.id,
            claim_id=target.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert foreign.mission.id not in caught.value.public_message


def test_foreign_mission_latest_status_event_refuses_without_reflecting_fields(
    lab: Lab,
) -> None:
    target = lab.seed_claim()
    foreign = lab.seed_claim(content=b"Evidence supports the claim.\n")
    lab.research.set_claim_status(
        claim_id=target.claim.id,
        status=ClaimStatus.INCONCLUSIVE,
        reason="Record a second status event before deliberate corruption.",
        expected_version=1,
        identity=lab.identity,
    )
    foreign_reason = "FOREIGN-STATUS-REASON-MUST-NOT-LEAK"
    foreign_actor = "foreign-status-actor-must-not-leak"
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER claim_status_no_update", ()),
            (
                """
                UPDATE claim_status_events
                SET mission_id = ?, reason = ?, creator_id = ?
                WHERE claim_id = ? AND version = 2
                """,
                (foreign.mission.id, foreign_reason, foreign_actor, target.claim.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=target.mission.id,
            claim_id=target.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert foreign_reason not in caught.value.public_message
    assert foreign_actor not in caught.value.public_message
    assert foreign.mission.id not in caught.value.public_message


@pytest.mark.parametrize("corruption", ["foreign_mission", "dangling"])
def test_claim_with_foreign_or_dangling_question_refuses(
    lab: Lab,
    corruption: str,
) -> None:
    target = lab.seed_claim()
    foreign = lab.seed_claim(content=b"Evidence supports the claim.\n")
    corrupted_question_id = (
        foreign.question.id if corruption == "foreign_mission" else "que_" + "f" * 32
    )
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER claims_no_update", ()),
            (
                "UPDATE claims SET question_id = ? WHERE id = ?",
                (corrupted_question_id, target.claim.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=target.mission.id,
            claim_id=target.claim.id,
        )

    assert caught.value.code == "claim_review_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert corrupted_question_id not in caught.value.public_message
    assert foreign.question.text not in caught.value.public_message


def test_unaffected_promotion_lineage_counts_toward_relationship_bound(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    adoption, inference = _adopt_inference(
        lab,
        seed,
        evidence,
        statement="A retracted inference keeps inspectable promotion lineage.",
    )
    promoted = adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    adoption.retract_inference(
        inference_id=inference.id,
        reason="Select the inference while leaving its promoted finding live.",
        identity=lab.identity,
    )
    trace: list[str] = []
    real_read = lab.database.read

    @contextmanager
    def traced_read() -> Any:
        with real_read() as connection:
            connection.set_trace_callback(trace.append)
            yield connection

    monkeypatch.setattr(lab.database, "read", traced_read)

    with pytest.raises(IntegrityError) as caught:
        ClaimReviewService(lab.database).review_claim(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimReviewBounds(max_relationships=1),
        )
    assert caught.value.code == "claim_review_work_limit"
    normalized_trace = tuple(" ".join(statement.upper().split()) for statement in trace)
    assert not any(
        "SELECT MISSION_ID, EVIDENCE_ID FROM FINDING_CITATIONS WHERE FINDING_ID =" in statement
        for statement in normalized_trace
    )

    review = ClaimReviewService(lab.database).review_claim(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        bounds=ClaimReviewBounds(max_relationships=2),
    )

    assert review.affected_findings == ()
    assert tuple(item.inference_id for item in review.affected_inferences) == (inference.id,)
    promotion = review.affected_inferences[0].promotion
    assert promotion is not None
    assert promotion.finding_id == promoted.id
    assert review.work.citation_relationship_count == 2
