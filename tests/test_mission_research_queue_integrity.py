from __future__ import annotations

import json
import socket
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

import minerva.cli.credentials as cli_credentials
import minerva.core.db as db_module
import minerva.integrations.ai as ai_integrations
import minerva.research_queue.service as queue_service_module
import minerva.review.service as review_service_module
from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceStance
from minerva.lineage import ClaimLineageService
from minerva.research.models import FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.research_queue import MissionResearchQueueBounds, MissionResearchQueueService
from minerva.review import ClaimReviewService
from minerva.review.models import ClaimReviewCue, ClaimReviewResult

_SUPPORT_QUOTE = "Evidence supports the claim."
_OPPOSITION_QUOTE = "Evidence opposes the claim."


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _replace_review_digest(review: ClaimReviewResult) -> ClaimReviewResult:
    provisional = replace(review, review_receipt_sha256="")
    payload = asdict(provisional)
    payload.pop("review_receipt_sha256")
    return replace(
        provisional,
        review_receipt_sha256=sha256(_canonical_bytes(payload)).hexdigest(),
    )


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


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


def _two_claim_mission(lab: Lab) -> tuple[str, str, str, str, bytes]:
    mission = lab.research.create_mission(
        title="Two-claim queue mission",
        objective="Verify complete mission aggregation and one-snapshot reads.",
        identity=lab.identity,
    )
    question = lab.research.add_question(
        mission_id=mission.id,
        text="Do both claims remain in one deterministic snapshot?",
        identity=lab.identity,
    )
    first = lab.research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="The first claim establishes the queue read snapshot.",
        falsification_criteria="Omission from the reviewed summaries would falsify it.",
        identity=lab.identity,
    )
    second = lab.research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="The second claim must not observe a mid-build write.",
        falsification_criteria="A mixed-snapshot receipt would falsify it.",
        identity=lab.identity,
    )
    content = b"Evidence supports the claim.\nEvidence opposes the claim.\n"
    lab.sources.import_bytes(
        mission_id=mission.id,
        content=content,
        original_label="queue-integrity.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    return mission.id, question.id, first.id, second.id, content


@pytest.mark.parametrize(
    "invalid_mission_id",
    [
        None,
        7,
        b"mis_00000000000000000000000000000000",
        "",
        " mis_00000000000000000000000000000000",
        "MIS_00000000000000000000000000000000",
        "mis_0000000000000000000000000000000g",
    ],
)
def test_hostile_mission_identifiers_fail_stably_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    invalid_mission_id: object,
) -> None:
    def read_must_not_run() -> object:
        raise AssertionError("mission ID shape must be validated before database work")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(NotFoundError) as caught:
        MissionResearchQueueService(lab.database).build_queue(
            mission_id=cast(str, invalid_mission_id)
        )

    assert caught.value.code == "mission_not_found"
    assert caught.value.public_message == "The requested resource was not found."
    assert caught.value.http_status == 404
    if reflected := str(invalid_mission_id):
        assert reflected not in caught.value.public_message


def test_unknown_well_formed_mission_is_non_reflective(lab: Lab) -> None:
    missing_id = "mis_" + "f" * 32

    with pytest.raises(NotFoundError) as caught:
        MissionResearchQueueService(lab.database).build_queue(mission_id=missing_id)

    assert caught.value.code == "mission_not_found"
    assert caught.value.public_message == "The requested resource was not found."
    assert missing_id not in caught.value.public_message


@pytest.mark.parametrize(
    "bounds",
    [
        MissionResearchQueueBounds(max_claims=0),
        MissionResearchQueueBounds(max_claims=True),
        MissionResearchQueueBounds(max_claims=201),
        MissionResearchQueueBounds(max_items=0),
        MissionResearchQueueBounds(max_items=2_801),
        MissionResearchQueueBounds(max_evidence_cards=0),
        MissionResearchQueueBounds(max_evidence_cards=40_001),
        MissionResearchQueueBounds(max_distinct_evidence_quote_bytes=0),
        MissionResearchQueueBounds(max_distinct_evidence_quote_bytes=67_108_865),
        MissionResearchQueueBounds(max_affected_records=0),
        MissionResearchQueueBounds(max_affected_records=100_001),
        MissionResearchQueueBounds(max_relationships=0),
        MissionResearchQueueBounds(max_relationships=1_000_001),
        MissionResearchQueueBounds(max_distinct_snapshot_bytes=0),
        MissionResearchQueueBounds(max_distinct_snapshot_bytes=67_108_865),
        MissionResearchQueueBounds(max_output_bytes=0),
        MissionResearchQueueBounds(max_output_bytes=134_217_729),
        MissionResearchQueueBounds(max_sqlite_vm_steps=999),
        MissionResearchQueueBounds(max_sqlite_vm_steps=16_000_001),
    ],
)
def test_invalid_bounds_fail_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    bounds: MissionResearchQueueBounds,
) -> None:
    mission = lab.research.create_mission(
        title="Bounds validation mission",
        objective="Bounds validation must precede all read work.",
        identity=lab.identity,
    )

    def read_must_not_run() -> object:
        raise AssertionError("queue bounds must be validated before database work")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(
            mission_id=mission.id,
            bounds=bounds,
        )

    assert caught.value.code == "mission_research_queue_bounds_invalid"
    assert caught.value.public_message == "Mission research queue bounds are invalid."


def test_wrong_bounds_object_fails_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission = lab.research.create_mission(
        title="Wrong bounds type mission",
        objective="Only the versioned queue bounds DTO is accepted.",
        identity=lab.identity,
    )

    def read_must_not_run() -> object:
        raise AssertionError("queue bounds must be validated before database work")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(
            mission_id=mission.id,
            bounds=cast(MissionResearchQueueBounds, object()),
        )

    assert caught.value.code == "mission_research_queue_bounds_invalid"


@pytest.mark.parametrize(
    "corruption",
    ["unknown", "duplicate", "reordered", "explanation", "category"],
)
def test_incompatible_claim_review_cue_catalog_refuses_even_with_valid_child_digest(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    seed = lab.seed_claim()
    real_review = ClaimReviewService._review_claim_in_snapshot

    def corrupting_review(
        self: ClaimReviewService,
        **kwargs: object,
    ) -> ClaimReviewResult:
        review = real_review(self, **kwargs)  # type: ignore[arg-type]
        cues = list(review.review_cues)
        gap_codes = list(review.gap_codes)
        impact_codes = list(review.impact_codes)
        if corruption == "unknown":
            cues[0] = ClaimReviewCue(
                code="unknown_queue_reason_must_not_be_adopted",
                explanation="UNKNOWN-QUEUE-EXPLANATION-MUST-NOT-LEAK",
                record_ids=(),
            )
            gap_codes[0] = cues[0].code
        elif corruption == "duplicate":
            cues.insert(1, cues[0])
            gap_codes.insert(1, gap_codes[0])
        elif corruption == "reordered":
            cues[0], cues[1] = cues[1], cues[0]
            gap_codes[0], gap_codes[1] = gap_codes[1], gap_codes[0]
        else:
            if corruption == "explanation":
                cues[0] = replace(
                    cues[0],
                    explanation="UNKNOWN-QUEUE-EXPLANATION-MUST-NOT-LEAK",
                )
            else:
                impact_codes = gap_codes + impact_codes
                gap_codes = []
        return _replace_review_digest(
            replace(
                review,
                gap_codes=tuple(gap_codes),
                impact_codes=tuple(impact_codes),
                review_cues=tuple(cues),
            )
        )

    monkeypatch.setattr(
        ClaimReviewService,
        "_review_claim_in_snapshot",
        corrupting_review,
    )

    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(mission_id=seed.mission.id)

    assert caught.value.code == "mission_research_queue_inconsistent"
    assert caught.value.public_message == "Stored mission research queue state is invalid."
    assert "UNKNOWN-QUEUE-EXPLANATION-MUST-NOT-LEAK" not in caught.value.public_message


@pytest.mark.parametrize(
    "corruption",
    ["question", "statement", "status", "work", "record_ids"],
)
def test_forged_child_review_payload_refuses_even_with_valid_child_digest(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    seed = lab.seed_claim()
    real_review = ClaimReviewService._review_claim_in_snapshot
    sentinel = "FOREIGN-FORGED-CHILD-PAYLOAD-MUST-NOT-LEAK"

    def corrupting_review(
        self: ClaimReviewService,
        **kwargs: object,
    ) -> ClaimReviewResult:
        review = real_review(self, **kwargs)  # type: ignore[arg-type]
        if corruption == "question":
            review = replace(review, question_id="que_" + "f" * 32)
        elif corruption == "statement":
            review = replace(review, claim_statement=sentinel)
        elif corruption == "status":
            review = replace(
                review,
                recorded_status=replace(
                    review.recorded_status,
                    version=review.recorded_status.version + 1,
                ),
            )
        elif corruption == "work":
            review = replace(
                review,
                work=replace(review.work, evidence_card_count=-999),
            )
        else:
            cues = list(review.review_cues)
            cues[0] = replace(cues[0], record_ids=("evd_" + "f" * 32,))
            review = replace(review, review_cues=tuple(cues))
        return _replace_review_digest(review)

    monkeypatch.setattr(
        ClaimReviewService,
        "_review_claim_in_snapshot",
        corrupting_review,
    )
    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(mission_id=seed.mission.id)

    assert caught.value.code == "mission_research_queue_inconsistent"
    assert caught.value.public_message == "Stored mission research queue state is invalid."
    assert sentinel not in caught.value.public_message


def test_forged_child_cannot_underreport_relationship_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The affected finding contributes one relationship.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The relationship work must remain exact.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="Admit the affected finding into Claim Review.",
        identity=lab.identity,
    )
    real_review = ClaimReviewService._review_claim_in_snapshot

    def underreported_review(
        self: ClaimReviewService,
        **kwargs: object,
    ) -> ClaimReviewResult:
        review = real_review(self, **kwargs)  # type: ignore[arg-type]
        assert review.work.citation_relationship_count == 1
        return _replace_review_digest(
            replace(
                review,
                work=replace(review.work, citation_relationship_count=0),
            )
        )

    monkeypatch.setattr(
        ClaimReviewService,
        "_review_claim_in_snapshot",
        underreported_review,
    )
    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(mission_id=seed.mission.id)

    assert caught.value.code == "mission_research_queue_inconsistent"


def test_self_consistent_zero_cue_review_still_has_a_reviewed_claim_summary(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    real_review = ClaimReviewService._review_claim_in_snapshot

    def zero_cue_review(
        self: ClaimReviewService,
        **kwargs: object,
    ) -> ClaimReviewResult:
        review = real_review(self, **kwargs)  # type: ignore[arg-type]
        return _replace_review_digest(
            replace(
                review,
                gap_codes=(),
                impact_codes=(),
                review_cues=(),
            )
        )

    monkeypatch.setattr(
        ClaimReviewService,
        "_review_claim_in_snapshot",
        zero_cue_review,
    )

    queue = MissionResearchQueueService(lab.database).build_queue(mission_id=seed.mission.id)

    assert len(queue.reviewed_claims) == 1
    summary = queue.reviewed_claims[0]
    assert summary.claim_id == seed.claim.id
    assert summary.reason_codes == ()
    assert summary.item_count == 0
    assert queue.items == ()
    assert queue.work.reviewed_claim_count == 1
    assert queue.work.item_count == 0
    assert all(count.count == 0 for count in queue.reason_counts)


def test_claim_and_item_bounds_are_exact_and_complete_or_refuse(lab: Lab) -> None:
    mission_id, _question_id, _first_id, _second_id, _content = _two_claim_mission(lab)
    service = MissionResearchQueueService(lab.database)

    exact = service.build_queue(
        mission_id=mission_id,
        bounds=MissionResearchQueueBounds(max_claims=2, max_items=6),
    )
    assert exact.work.reviewed_claim_count == 2
    assert exact.work.item_count == 6

    for bounds in (
        MissionResearchQueueBounds(max_claims=1),
        MissionResearchQueueBounds(max_items=5),
    ):
        with pytest.raises(IntegrityError) as caught:
            service.build_queue(mission_id=mission_id, bounds=bounds)
        assert caught.value.code == "mission_research_queue_work_limit"
        assert caught.value.public_message == (
            "The complete mission research queue exceeds its configured work limits."
        )


def test_cumulative_review_bounds_succeed_exactly_and_refuse_one_below(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    lab.cite(seed, _OPPOSITION_QUOTE, EvidenceStance.OPPOSES)
    findings = tuple(
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement=f"Corrected material finding {index}.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="The shared supporting card is later withdrawn.",
            evidence_ids=(support.id,),
            identity=lab.identity,
        )
        for index in range(2)
    )
    lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="Exercise cumulative affected-record and relationship bounds.",
        identity=lab.identity,
    )
    service = MissionResearchQueueService(lab.database)
    baseline = service.build_queue(mission_id=seed.mission.id)
    assert baseline.work.evidence_card_count == 2
    assert baseline.work.affected_finding_count == len(findings) == 2
    assert baseline.work.affected_record_count == 2
    assert baseline.work.citation_relationship_count == 2
    assert baseline.work.distinct_snapshot_bytes == len(seed.content)

    exact = replace(
        MissionResearchQueueBounds(),
        max_evidence_cards=baseline.work.evidence_card_count,
        max_affected_records=baseline.work.affected_record_count,
        max_relationships=baseline.work.citation_relationship_count,
        max_distinct_snapshot_bytes=baseline.work.distinct_snapshot_bytes,
    )
    assert service.build_queue(mission_id=seed.mission.id, bounds=exact).complete is True

    for field, value in (
        ("max_evidence_cards", baseline.work.evidence_card_count),
        ("max_affected_records", baseline.work.affected_record_count),
        ("max_relationships", baseline.work.citation_relationship_count),
        ("max_distinct_snapshot_bytes", baseline.work.distinct_snapshot_bytes),
    ):
        with pytest.raises(IntegrityError) as caught:
            service.build_queue(
                mission_id=seed.mission.id,
                bounds=replace(exact, **{field: value - 1}),
            )
        assert caught.value.code == "mission_research_queue_work_limit"


def test_remaining_evidence_budget_refuses_before_child_citation_verification(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    lab.cite(seed, _OPPOSITION_QUOTE, EvidenceStance.OPPOSES)
    captured_limits: list[tuple[int, int]] = []
    real_review = ClaimReviewService._review_claim_in_snapshot

    def bounded_review(self: ClaimReviewService, **kwargs: object) -> ClaimReviewResult:
        execution_limits = kwargs["execution_limits"]
        captured_limits.append(
            (
                cast(Any, execution_limits).max_evidence_cards,
                cast(Any, execution_limits).max_new_evidence_cards,
            )
        )
        return real_review(self, **kwargs)  # type: ignore[arg-type]

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "aggregate evidence admission must refuse before citation verification"
        )

    monkeypatch.setattr(ClaimReviewService, "_review_claim_in_snapshot", bounded_review)
    monkeypatch.setattr(
        review_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )

    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_evidence_cards=1),
        )

    assert caught.value.code == "mission_research_queue_work_limit"
    assert captured_limits == [(200, 1)]


def test_remaining_evidence_budget_covers_correction_citation_closure(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    first = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    evidence_ids = [first.id]
    quote_bytes = _SUPPORT_QUOTE.encode("utf-8")
    start_byte = seed.content.index(quote_bytes)
    for index in range(2):
        claim = lab.research.add_claim(
            mission_id=seed.mission.id,
            question_id=seed.question.id,
            statement=f"Closure evidence claim {index}.",
            falsification_criteria="A missing citation would falsify it.",
            identity=lab.identity,
        )
        evidence = lab.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=start_byte,
            end_byte=start_byte + len(quote_bytes),
            quote=_SUPPORT_QUOTE,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )
        evidence_ids.append(evidence.id)
    lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=None,
        statement="A claimless correction dependent cites all three mission claims.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The correction closure must remain bounded before verification.",
        evidence_ids=tuple(evidence_ids),
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=first.id,
        reason="Expose the complete three-card correction closure.",
        identity=lab.identity,
    )

    exact = MissionResearchQueueService(lab.database).build_queue(
        mission_id=seed.mission.id,
        bounds=MissionResearchQueueBounds(max_evidence_cards=3),
    )
    assert exact.work.reviewed_claim_count == 3
    assert exact.work.evidence_card_count == 3

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("citation closure must be admitted before any card is verified")

    monkeypatch.setattr(
        review_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )
    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_evidence_cards=1),
        )

    assert caught.value.code == "mission_research_queue_work_limit"


def test_distinct_evidence_quote_bytes_refuse_before_quote_materialization(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = "Q" * 100_000
    seed = lab.seed_claim(content=quote.encode("utf-8"))
    lab.cite(seed, quote, EvidenceStance.SUPPORTS)
    lab.cite(seed, quote, EvidenceStance.CONTEXT)
    service = MissionResearchQueueService(lab.database)

    exact = service.build_queue(
        mission_id=seed.mission.id,
        bounds=MissionResearchQueueBounds(
            max_evidence_cards=2,
            max_distinct_evidence_quote_bytes=200_000,
        ),
    )
    assert exact.work.evidence_card_count == 2
    assert exact.work.distinct_evidence_quote_bytes == 200_000
    assert exact.work.distinct_snapshot_bytes == 100_000

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("quote-byte admission must precede quote materialization")

    monkeypatch.setattr(
        review_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )
    with pytest.raises(IntegrityError) as caught:
        service.build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(
                max_evidence_cards=2,
                max_distinct_evidence_quote_bytes=199_999,
            ),
        )

    assert caught.value.code == "mission_research_queue_work_limit"


def test_remaining_snapshot_budget_reuses_only_already_verified_snapshot_bytes(
    lab: Lab,
) -> None:
    mission_id, _question_id, first_id, second_id, content = _two_claim_mission(lab)
    with lab.database.read() as connection:
        snapshot_id = str(
            connection.execute(
                "SELECT id FROM source_snapshots WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()["id"]
        )
    for claim_id in (first_id, second_id):
        quote_bytes = _SUPPORT_QUOTE.encode("utf-8")
        start_byte = content.index(quote_bytes)
        lab.evidence.add_evidence(
            mission_id=mission_id,
            claim_id=claim_id,
            snapshot_id=snapshot_id,
            start_byte=start_byte,
            end_byte=start_byte + len(quote_bytes),
            quote=_SUPPORT_QUOTE,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    queue = MissionResearchQueueService(lab.database).build_queue(
        mission_id=mission_id,
        bounds=MissionResearchQueueBounds(max_distinct_snapshot_bytes=len(content)),
    )

    assert queue.work.evidence_card_count == 2
    assert queue.work.distinct_snapshot_count == 1
    assert queue.work.distinct_snapshot_bytes == len(content)


def test_output_and_sqlite_vm_limits_refuse_without_a_partial_queue(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    service = MissionResearchQueueService(lab.database)

    output_limit = service.build_queue(mission_id=seed.mission.id).work.canonical_output_bytes
    for _ in range(3):
        exact_output = service.build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_output_bytes=output_limit),
        )
        measured = exact_output.work.canonical_output_bytes
        if measured == output_limit:
            break
        output_limit = measured
    assert exact_output.work.canonical_output_bytes == output_limit

    with pytest.raises(IntegrityError) as one_below_output:
        service.build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_output_bytes=output_limit - 1),
        )
    assert one_below_output.value.code == "mission_research_queue_work_limit"

    with pytest.raises(IntegrityError) as tiny_output:
        service.build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_output_bytes=1),
        )
    assert tiny_output.value.code == "mission_research_queue_work_limit"

    monkeypatch.setattr(queue_service_module, "_QUERY_PROGRESS_GRANULARITY", 1)
    monkeypatch.setattr(queue_service_module, "_MIN_SQLITE_VM_STEPS", 1)
    with pytest.raises(IntegrityError) as vm_limit:
        service.build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_sqlite_vm_steps=1),
        )
    assert vm_limit.value.code == "mission_research_queue_work_limit"


def test_cumulative_progress_handler_is_restored_on_success_and_refusal(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    real_read = lab.database.read
    progress_calls: list[tuple[bool, int]] = []

    class RecordingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def set_progress_handler(self, callback: object, instructions: int) -> None:
            progress_calls.append((callback is None, instructions))
            self.connection.set_progress_handler(callback, instructions)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

    @contextmanager
    def recording_read() -> Any:
        with real_read() as connection:
            yield RecordingConnection(connection)

    monkeypatch.setattr(lab.database, "read", recording_read)
    MissionResearchQueueService(lab.database).build_queue(mission_id=seed.mission.id)
    assert progress_calls[0] == (False, 1_000)
    assert progress_calls[-1] == (True, 0)

    progress_calls.clear()
    monkeypatch.setattr(queue_service_module, "_QUERY_PROGRESS_GRANULARITY", 1)
    monkeypatch.setattr(queue_service_module, "_MIN_SQLITE_VM_STEPS", 1)
    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(
            mission_id=seed.mission.id,
            bounds=MissionResearchQueueBounds(max_sqlite_vm_steps=1),
        )
    assert caught.value.code == "mission_research_queue_work_limit"
    assert progress_calls[0] == (False, 1)
    assert progress_calls[-1] == (True, 0)


def test_queue_is_one_query_only_read_with_zero_unauthorized_side_effects(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    before_dump = _database_dump(lab.database)
    before_bytes = lab.database.path.read_bytes()
    trace: list[str] = []
    read_count = 0
    real_read = lab.database.read

    @contextmanager
    def traced_read() -> Any:
        nonlocal read_count
        read_count += 1
        with real_read() as connection:
            connection.set_trace_callback(trace.append)
            yield connection

    def transaction_forbidden() -> object:
        raise AssertionError("Mission Research Queue must not open a write transaction")

    def provider_forbidden(_: object) -> object:
        raise AssertionError("Mission Research Queue must not construct a model provider")

    def credential_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Mission Research Queue must not read provider credentials")

    def lineage_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Mission Research Queue v1 must not invoke Claim Lineage")

    def network_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Mission Research Queue must not construct a network socket")

    monkeypatch.setattr(lab.database, "read", traced_read)
    monkeypatch.setattr(lab.database, "transaction", transaction_forbidden)
    monkeypatch.setattr(ai_integrations, "candidate_provider", provider_forbidden)
    monkeypatch.setattr(cli_credentials, "load_provider_credential", credential_forbidden)
    monkeypatch.setattr(ClaimLineageService, "build_graph", lineage_forbidden)
    monkeypatch.setattr(socket, "socket", network_forbidden)

    queue = MissionResearchQueueService(lab.database).build_queue(mission_id=seed.mission.id)

    assert read_count == 1
    assert any(statement.strip().upper() == "PRAGMA QUERY_ONLY = ON" for statement in trace)
    assert queue.semantic_boundary.read_only is True
    assert queue.semantic_boundary.writes_audit_event_or_export is False
    assert queue.semantic_boundary.modifies_source_or_snapshot_bytes is False
    assert queue.semantic_boundary.invokes_claim_lineage is False
    assert queue.semantic_boundary.invokes_model_provider is False
    assert queue.semantic_boundary.invokes_network is False
    with real_read() as connection:
        after_dump = tuple(connection.iterdump())
    assert after_dump == before_dump
    assert lab.database.path.read_bytes() == before_bytes


def test_concurrent_writer_cannot_create_a_mixed_mission_snapshot(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission_id, _question_id, first_id, second_id, content = _two_claim_mission(lab)
    with lab.database.read() as connection:
        snapshot_id = str(
            connection.execute(
                "SELECT id FROM source_snapshots WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()["id"]
        )
    service = MissionResearchQueueService(lab.database)
    baseline = service.build_queue(mission_id=mission_id)
    entered = threading.Event()
    release = threading.Event()
    paused = False
    read_count = 0
    connection_ids: list[int] = []
    results: list[object] = []
    failures: list[BaseException] = []
    real_read = lab.database.read
    real_review = ClaimReviewService._review_claim_in_snapshot

    @contextmanager
    def counted_read() -> Any:
        nonlocal read_count
        read_count += 1
        with real_read() as connection:
            yield connection

    def pausing_review(
        self: ClaimReviewService,
        *,
        mission_id: str,
        claim_id: str,
        bounds: object,
        connection: sqlite3.Connection,
        snapshot_cache: object,
        verified_citation_cache: object,
        verified_citation_quote_bytes: object,
        execution_limits: object,
    ) -> object:
        nonlocal paused
        result = real_review(
            self,
            mission_id=mission_id,
            claim_id=claim_id,
            bounds=bounds,  # type: ignore[arg-type]
            connection=connection,
            snapshot_cache=snapshot_cache,  # type: ignore[arg-type]
            verified_citation_cache=verified_citation_cache,  # type: ignore[arg-type]
            verified_citation_quote_bytes=(  # type: ignore[arg-type]
                verified_citation_quote_bytes
            ),
            execution_limits=execution_limits,  # type: ignore[arg-type]
        )
        connection_ids.append(id(connection))
        if claim_id == first_id and not paused:
            paused = True
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError("timed out waiting to resume the queue snapshot")
        return result

    monkeypatch.setattr(lab.database, "read", counted_read)
    monkeypatch.setattr(ClaimReviewService, "_review_claim_in_snapshot", pausing_review)

    def build_in_thread() -> None:
        try:
            results.append(service.build_queue(mission_id=mission_id))
        except BaseException as error:  # pragma: no cover - asserted below
            failures.append(error)

    thread = threading.Thread(target=build_in_thread, name="mission-queue-reader")
    thread.start()
    try:
        assert entered.wait(timeout=10), "queue did not pause after its first claim review"
        quote_bytes = _SUPPORT_QUOTE.encode("utf-8")
        start_byte = content.index(quote_bytes)
        lab.evidence.add_evidence(
            mission_id=mission_id,
            claim_id=second_id,
            snapshot_id=snapshot_id,
            start_byte=start_byte,
            end_byte=start_byte + len(quote_bytes),
            quote=_SUPPORT_QUOTE,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )
    finally:
        release.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert failures == []
    assert len(results) == 1
    assert results[0] == baseline
    assert read_count == 1
    assert len(connection_ids) == 2
    assert len(set(connection_ids)) == 1

    after = service.build_queue(mission_id=mission_id)
    assert after != baseline
    before_second = next(item for item in baseline.reviewed_claims if item.claim_id == second_id)
    after_second = next(item for item in after.reviewed_claims if item.claim_id == second_id)
    assert before_second.reason_codes == (
        "no_active_evidence",
        "no_active_support",
        "no_active_opposition",
    )
    assert after_second.reason_codes == ("no_active_opposition",)


@pytest.mark.parametrize(
    ("corruption", "expected_code", "expected_message"),
    [
        ("citation", "citation_tampered", "Stored citation integrity failed."),
        (
            "snapshot",
            "snapshot_tampered",
            "Stored source snapshot integrity failed.",
        ),
        (
            "question",
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        ),
        (
            "status",
            "mission_research_queue_inconsistent",
            "Stored mission research queue state is invalid.",
        ),
    ],
)
def test_later_claim_tampering_aborts_the_whole_queue_without_reflection(
    lab: Lab,
    corruption: str,
    expected_code: str,
    expected_message: str,
) -> None:
    mission_id, _question_id, _first_id, second_id, content = _two_claim_mission(lab)
    with lab.database.read() as connection:
        snapshot = connection.execute(
            "SELECT id FROM source_snapshots WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
    snapshot_id = str(snapshot["id"])
    quote_bytes = _SUPPORT_QUOTE.encode("utf-8")
    start_byte = content.index(quote_bytes)
    evidence = lab.evidence.add_evidence(
        mission_id=mission_id,
        claim_id=second_id,
        snapshot_id=snapshot_id,
        start_byte=start_byte,
        end_byte=start_byte + len(quote_bytes),
        quote=_SUPPORT_QUOTE,
        stance=EvidenceStance.SUPPORTS,
        identity=lab.identity,
    )
    foreign = lab.seed_claim(content=b"FOREIGN-TAMPER-TEXT-MUST-NOT-LEAK\n")
    if corruption == "citation":
        statements = (
            ("DROP TRIGGER evidence_no_update", ()),
            (
                "UPDATE evidence_cards SET quote = ? WHERE id = ?",
                ("X" * len(_SUPPORT_QUOTE), evidence.id),
            ),
        )
    elif corruption == "snapshot":
        statements = (
            ("DROP TRIGGER snapshots_no_update", ()),
            (
                "UPDATE source_snapshots SET content = ? WHERE id = ?",
                (b"X" * len(content), snapshot_id),
            ),
        )
    elif corruption == "question":
        statements = (
            ("DROP TRIGGER claims_no_update", ()),
            (
                "UPDATE claims SET question_id = ? WHERE id = ?",
                (foreign.question.id, second_id),
            ),
        )
    else:
        statements = (
            ("DROP TRIGGER claim_status_no_update", ()),
            (
                """
                UPDATE claim_status_events
                SET mission_id = ?, reason = ?, creator_id = ?
                WHERE claim_id = ?
                """,
                (
                    foreign.mission.id,
                    "FOREIGN-STATUS-REASON-MUST-NOT-LEAK",
                    "foreign-actor-must-not-leak",
                    second_id,
                ),
            ),
        )
    _raw_corrupt(lab.database, statements)

    with pytest.raises(IntegrityError) as caught:
        MissionResearchQueueService(lab.database).build_queue(mission_id=mission_id)

    assert caught.value.code == expected_code
    assert caught.value.public_message == expected_message
    assert foreign.mission.id not in caught.value.public_message
    assert foreign.question.text not in caught.value.public_message
    assert "FOREIGN-STATUS-REASON-MUST-NOT-LEAK" not in caught.value.public_message


def test_pre_v5_database_requires_explicit_migration_before_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy = Database(tmp_path / "legacy-mission-queue-v4.db")
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])
    assert legacy.initialize() == 4
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-mission-queue",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify explicit migration before mission queue",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy mission queue",
        objective="A stale database cannot provide complete inference review cues.",
        identity=identity,
    )
    question = research.add_question(
        mission_id=mission.id,
        text="Can v4 expose a complete mission queue?",
        identity=identity,
    )
    research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="Mission Research Queue refuses stale migration state.",
        falsification_criteria="A successful pre-migration queue would falsify it.",
        identity=identity,
    )

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    with pytest.raises(IntegrityError) as required:
        MissionResearchQueueService(legacy).build_queue(mission_id=mission.id)
    assert required.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    queue = MissionResearchQueueService(legacy).build_queue(mission_id=mission.id)
    assert queue.complete is True
    assert queue.work.reviewed_claim_count == 1
    assert queue.work.item_count == 3
