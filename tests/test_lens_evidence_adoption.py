from __future__ import annotations

import json
import socket
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, NoReturn, cast

import pytest

import minerva.integrations.ai as ai_integrations
from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.errors import ConflictError, IntegrityError, MinervaError
from minerva.core.types import IdentityContext
from minerva.evidence import (
    EvidenceStance,
    LensCandidateConfirmation,
    LensEvidenceAdoptionService,
)
from minerva.lens import LensBounds, LensService
from minerva.lens.models import LensSearchResult


def _confirmation(
    receipt: LensSearchResult,
    *,
    rank: int = 1,
) -> LensCandidateConfirmation:
    candidate = receipt.candidates[rank - 1]
    return LensCandidateConfirmation(
        rank=rank,
        snapshot_sha256=candidate.snapshot_sha256,
        start_byte=candidate.start_byte,
        end_byte=candidate.end_byte,
        quote_sha256=candidate.quote_sha256,
    )


def _service(lab: Lab, *, audit: object | None = None) -> LensEvidenceAdoptionService:
    return LensEvidenceAdoptionService(
        lab.database,
        audit=cast(Any, audit),
        clock=fixed_clock,
        id_factory=lab.ids,
    )


def _adopt(
    lab: Lab,
    receipt: LensSearchResult,
    *,
    stance: EvidenceStance = EvidenceStance.SUPPORTS,
    confirmation: LensCandidateConfirmation | None = None,
    expected_receipt_sha256: str | None = None,
    supersedes: str | None = None,
    service: LensEvidenceAdoptionService | None = None,
):
    return (service or _service(lab)).adopt_candidate(
        receipt=receipt,
        mission_id=receipt.mission_id,
        claim_id=lab.research.list_claims(receipt.mission_id)[0].id,
        confirmation=confirmation or _confirmation(receipt),
        expected_retrieval_receipt_sha256=(
            expected_receipt_sha256 or receipt.retrieval_receipt_sha256
        ),
        stance=stance,
        supersedes_evidence_id=supersedes,
        identity=lab.identity,
    )


def _audit_events(lab: Lab, event_type: str) -> list[sqlite3.Row]:
    with lab.database.read() as connection:
        return list(
            connection.execute(
                "SELECT * FROM audit_events WHERE event_type = ? ORDER BY sequence",
                (event_type,),
            )
        )


def test_adopts_one_exact_multibyte_candidate_with_bounded_provenance(lab: Lab) -> None:
    content = "Préface.\nCafé 東京 evidence is byte exact.\n".encode()
    seed = lab.seed_claim(content=content)
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="CAFÉ 東京",
    )
    candidate = receipt.candidates[0]

    result = _adopt(lab, receipt, stance=EvidenceStance.CONTEXT)

    assert result.schema_version == "minerva.lens-evidence-adoption.v1"
    assert result.kind == "single_candidate_evidence_adoption"
    assert result.status == "adopted"
    assert result.retrieval_receipt_sha256 == receipt.retrieval_receipt_sha256
    assert result.query_sha256 == receipt.query_sha256
    assert result.snapshot_set_sha256 == receipt.snapshot_set_sha256
    assert result.candidate_rank == 1
    assert result.source_id == candidate.source_id
    assert result.snapshot_id == seed.snapshot.snapshot_id
    assert result.snapshot_sha256 == seed.snapshot.sha256
    assert result.start_byte == content.index(candidate.quote.encode("utf-8"))
    assert result.end_byte == result.start_byte + len(candidate.quote.encode("utf-8"))
    assert content[result.start_byte : result.end_byte].decode("utf-8") == candidate.quote
    assert result.quote_sha256 == candidate.quote_sha256
    assert result.evidence.quote == candidate.quote
    assert result.evidence.stance is EvidenceStance.CONTEXT
    assert result.evidence.supersedes_evidence_id is None

    boundary = result.semantic_boundary
    assert boundary.single_candidate_only
    assert boundary.receipt_strictly_verified
    assert boundary.current_database_exactly_reproduced
    assert boundary.candidate_explicitly_confirmed
    assert boundary.normal_evidence_validation_applied
    assert boundary.creates_one_evidence_card
    assert boundary.writes_append_only_audit_history
    assert boundary.operator_supplied_stance
    assert boundary.lens_search_remains_read_only
    assert not boundary.rank_used_as_epistemic_weight
    assert not boundary.performs_bulk_or_automatic_adoption
    assert not boundary.determines_truth_or_source_quality
    assert not boundary.calculates_confidence
    assert not boundary.alters_claim_status
    assert not boundary.creates_or_retracts_findings
    assert not boundary.persists_agent_inference
    assert not boundary.modifies_source_or_snapshot_bytes
    assert not boundary.invokes_model_provider_or_network
    assert not boundary.exposes_external_agent_protocol

    adoption_events = _audit_events(lab, "lens.candidate.adopted")
    assert len(adoption_events) == 1
    event = adoption_events[0]
    assert str(event["id"]) == result.adoption_audit_event_id
    assert str(event["entity_id"]) == result.evidence.id
    details = json.loads(str(event["details_json"]))
    assert details == {
        "candidate_rank": 1,
        "claim_id": seed.claim.id,
        "end_byte": candidate.end_byte,
        "query_sha256": receipt.query_sha256,
        "quote_sha256": candidate.quote_sha256,
        "retrieval_receipt_sha256": receipt.retrieval_receipt_sha256,
        "retrieval_truncated": False,
        "snapshot_id": candidate.snapshot_id,
        "snapshot_set_sha256": receipt.snapshot_set_sha256,
        "snapshot_sha256": candidate.snapshot_sha256,
        "stance": "context",
        "start_byte": candidate.start_byte,
        "supersedes": None,
    }
    assert candidate.quote not in str(event["details_json"])
    assert candidate.source_label not in str(event["details_json"])


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda receipt, confirmation: {"mission_id": "mis_" + "f" * 32},
            "lens_adoption_scope_invalid",
        ),
        (lambda receipt, confirmation: {"claim_id": "not-a-claim"}, "lens_adoption_scope_invalid"),
        (
            lambda receipt, confirmation: {"supersedes_evidence_id": "not-evidence"},
            "lens_adoption_scope_invalid",
        ),
        (
            lambda receipt, confirmation: {"expected_retrieval_receipt_sha256": "not-a-digest"},
            "lens_adoption_confirmation_invalid",
        ),
        (
            lambda receipt, confirmation: {"expected_retrieval_receipt_sha256": "f" * 64},
            "lens_adoption_confirmation_mismatch",
        ),
        (
            lambda receipt, confirmation: {"confirmation": replace(confirmation, rank=0)},
            "lens_adoption_candidate_rank_invalid",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, rank=len(receipt.candidates) + 1)
            },
            "lens_adoption_candidate_rank_invalid",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, rank=cast(int, True))
            },
            "lens_adoption_candidate_rank_invalid",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, snapshot_sha256="bad")
            },
            "lens_adoption_confirmation_invalid",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, snapshot_sha256="f" * 64)
            },
            "lens_adoption_confirmation_mismatch",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, start_byte=confirmation.start_byte + 1)
            },
            "lens_adoption_confirmation_mismatch",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, end_byte=confirmation.end_byte + 1)
            },
            "lens_adoption_confirmation_mismatch",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, end_byte=cast(int, False))
            },
            "lens_adoption_confirmation_invalid",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, quote_sha256="f" * 64)
            },
            "lens_adoption_confirmation_mismatch",
        ),
        (
            lambda receipt, confirmation: {
                "confirmation": replace(confirmation, quote_sha256="bad")
            },
            "lens_adoption_confirmation_invalid",
        ),
        (
            lambda receipt, confirmation: {"confirmation": cast(Any, object())},
            "lens_adoption_confirmation_invalid",
        ),
        (
            lambda receipt, confirmation: {"stance": cast(Any, "supports")},
            "evidence_stance_invalid",
        ),
    ],
)
def test_invalid_scope_and_every_explicit_confirmation_refuse_before_database_open(
    lab: Lab,
    tmp_path,
    mutate,
    expected_code: str,
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    confirmation = _confirmation(receipt)
    missing = type(lab.database)(tmp_path / "must-not-be-created.db")
    arguments: dict[str, object] = {
        "receipt": receipt,
        "mission_id": seed.mission.id,
        "claim_id": seed.claim.id,
        "confirmation": confirmation,
        "expected_retrieval_receipt_sha256": receipt.retrieval_receipt_sha256,
        "stance": EvidenceStance.SUPPORTS,
        "supersedes_evidence_id": None,
        "identity": lab.identity,
    }
    arguments.update(mutate(receipt, confirmation))

    with pytest.raises(MinervaError) as caught:
        LensEvidenceAdoptionService(missing).adopt_candidate(**cast(Any, arguments))

    assert caught.value.code == expected_code
    assert not missing.path.exists()


def test_well_formed_foreign_claim_refuses_atomically_after_mission_replay(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching observation\n", source_label="first.txt")
    foreign = lab.seed_claim(content=b"foreign observation\n", source_label="foreign.txt")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    with lab.database.read() as connection:
        before_audit = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

    with pytest.raises(MinervaError) as caught:
        _service(lab).adopt_candidate(
            receipt=receipt,
            mission_id=seed.mission.id,
            claim_id=foreign.claim.id,
            confirmation=_confirmation(receipt),
            expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    assert caught.value.code == "claim_not_found"
    assert lab.evidence.ledger_for_claim(seed.claim.id) == ()
    assert lab.evidence.ledger_for_claim(foreign.claim.id) == ()
    with lab.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before_audit


def test_tampered_receipt_refuses_before_database_open(lab: Lab, tmp_path) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    tampered = replace(receipt, semantic_notice="edited")
    missing = type(lab.database)(tmp_path / "must-not-be-created.db")

    with pytest.raises(IntegrityError) as caught:
        LensEvidenceAdoptionService(missing).adopt_candidate(
            receipt=tampered,
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            confirmation=_confirmation(receipt),
            expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    assert caught.value.code == "lens_receipt_digest_mismatch"
    assert not missing.path.exists()


def test_all_human_stances_are_distinct_and_have_no_semantic_side_effects(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content="Café matching observation.\n".encode())
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    with lab.database.read() as connection:
        original_audit = tuple(
            (str(row["id"]), str(row["details_json"]))
            for row in connection.execute(
                "SELECT id, details_json FROM audit_events ORDER BY sequence"
            )
        )
        original_snapshot = bytes(
            connection.execute(
                "SELECT content FROM source_snapshots WHERE id = ?",
                (seed.snapshot.snapshot_id,),
            ).fetchone()[0]
        )

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("Lens evidence adoption crossed a provider or network boundary")

    monkeypatch.setattr(ai_integrations, "candidate_provider", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    results = [
        _adopt(lab, receipt, stance=stance)
        for stance in (
            EvidenceStance.SUPPORTS,
            EvidenceStance.OPPOSES,
            EvidenceStance.CONTEXT,
            EvidenceStance.INCONCLUSIVE,
        )
    ]

    assert [result.evidence.stance for result in results] == list(EvidenceStance)
    with lab.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM evidence_cards").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM finding_retractions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM agent_inferences").fetchone()[0] == 0
        inference_state = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM agent_inference_citations),
                (SELECT COUNT(*) FROM agent_inference_retractions),
                (SELECT COUNT(*) FROM agent_inference_promotions)
            """
        ).fetchone()
        assert tuple(inference_state) == (0, 0, 0)
        statuses = list(
            connection.execute(
                "SELECT version, status FROM claim_status_events WHERE claim_id = ?",
                (seed.claim.id,),
            )
        )
        assert [(int(row["version"]), str(row["status"])) for row in statuses] == [(1, "open")]
        assert (
            bytes(
                connection.execute(
                    "SELECT content FROM source_snapshots WHERE id = ?",
                    (seed.snapshot.snapshot_id,),
                ).fetchone()[0]
            )
            == original_snapshot
        )
        all_audit = list(connection.execute("SELECT * FROM audit_events ORDER BY sequence"))
        assert (
            tuple(
                (str(row["id"]), str(row["details_json"]))
                for row in all_audit[: len(original_audit)]
            )
            == original_audit
        )
        assert [str(row["event_type"]) for row in all_audit[len(original_audit) :]] == [
            event for _ in range(4) for event in ("evidence.card.created", "lens.candidate.adopted")
        ]


def test_exact_duplicate_is_refused_while_active_and_after_withdrawal(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    first = _adopt(lab, receipt)

    with pytest.raises(ConflictError) as active:
        _adopt(lab, receipt)
    assert active.value.code == "lens_candidate_already_adopted"

    lab.evidence.withdraw_evidence(
        evidence_id=first.evidence.id,
        reason="A correction will preserve, not erase, this history.",
        identity=lab.identity,
    )
    with pytest.raises(ConflictError) as withdrawn:
        _adopt(lab, receipt)
    assert withdrawn.value.code == "lens_candidate_already_adopted"
    assert len(lab.evidence.ledger_for_claim(seed.claim.id)) == 1


def test_withdrawn_target_can_be_corrected_and_valid_supersession_can_branch(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    original = lab.cite(seed, "matching observation", EvidenceStance.INCONCLUSIVE)
    lab.evidence.withdraw_evidence(
        evidence_id=original.id,
        reason="The first evaluation is withdrawn but remains addressable.",
        identity=lab.identity,
    )
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )

    correction = _adopt(
        lab,
        receipt,
        stance=EvidenceStance.SUPPORTS,
        supersedes=original.id,
    )
    branch = _adopt(
        lab,
        receipt,
        stance=EvidenceStance.OPPOSES,
        supersedes=original.id,
    )

    assert correction.evidence.supersedes_evidence_id == original.id
    assert branch.evidence.supersedes_evidence_id == original.id
    ledger = lab.evidence.ledger_for_claim(seed.claim.id)
    by_id = {entry.evidence.id: entry for entry in ledger}
    assert by_id[original.id].withdrawn
    assert not by_id[correction.evidence.id].withdrawn
    assert not by_id[branch.evidence.id].withdrawn


class _FailOnAdoptionAudit:
    def __init__(self, ids: SequenceIds) -> None:
        self._delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

    def ensure_run(
        self,
        connection: sqlite3.Connection,
        identity: IdentityContext,
    ) -> None:
        self._delegate.ensure_run(connection, identity)

    def record(
        self,
        connection: sqlite3.Connection,
        *,
        identity: IdentityContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        mission_id: str | None,
        details: Mapping[str, object] | None = None,
    ) -> str:
        if event_type == "lens.candidate.adopted":
            raise RuntimeError("synthetic adoption audit failure")
        return self._delegate.record(
            connection,
            identity=identity,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            mission_id=mission_id,
            details=details,
        )


def test_adoption_audit_failure_rolls_back_card_and_creation_audit(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    before_created = len(_audit_events(lab, "evidence.card.created"))

    with pytest.raises(RuntimeError, match="synthetic adoption audit failure"):
        _adopt(
            lab,
            receipt,
            service=_service(lab, audit=_FailOnAdoptionAudit(lab.ids)),
        )

    assert lab.evidence.ledger_for_claim(seed.claim.id) == ()
    assert len(_audit_events(lab, "evidence.card.created")) == before_created
    assert _audit_events(lab, "lens.candidate.adopted") == []


def test_concurrent_exact_adoptions_commit_once_and_refuse_once(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    confirmation = _confirmation(receipt)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=30)
        try:
            LensEvidenceAdoptionService(lab.database).adopt_candidate(
                receipt=receipt,
                mission_id=seed.mission.id,
                claim_id=seed.claim.id,
                confirmation=confirmation,
                expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
                stance=EvidenceStance.SUPPORTS,
                identity=lab.identity,
            )
        except MinervaError as error:
            outcome = error.code
        else:
            outcome = "adopted"
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["adopted", "lens_candidate_already_adopted"]
    assert len(lab.evidence.ledger_for_claim(seed.claim.id)) == 1
    assert len(_audit_events(lab, "lens.candidate.adopted")) == 1


def test_returned_candidate_from_truncated_receipt_can_be_adopted(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching first\nmatching second\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
        bounds=LensBounds(max_results=1),
    )
    assert receipt.truncated
    assert receipt.result_count == 1
    assert receipt.matching_candidate_count == 2

    result = _adopt(lab, receipt)

    assert result.retrieval_truncated
    assert result.candidate_rank == 1
    assert result.evidence.quote == receipt.candidates[0].quote
