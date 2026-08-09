from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

import minerva.core.db as db_module
from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.db import Database, latest_schema_version
from minerva.core.doctor import DoctorReport, run_doctor
from minerva.core.errors import IntegrityError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence import (
    EvidenceStance,
    LensCandidateConfirmation,
    LensEvidenceAdoptionService,
)
from minerva.evidence.service import EvidenceService
from minerva.lens import LensService
from minerva.lens.models import LensSearchResult
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService


def _confirmation(receipt: LensSearchResult) -> LensCandidateConfirmation:
    candidate = receipt.candidates[0]
    return LensCandidateConfirmation(
        rank=1,
        snapshot_sha256=candidate.snapshot_sha256,
        start_byte=candidate.start_byte,
        end_byte=candidate.end_byte,
        quote_sha256=candidate.quote_sha256,
    )


def _adopt(
    lab: Lab,
    receipt: LensSearchResult,
    *,
    supersedes: str | None = None,
):
    return LensEvidenceAdoptionService(
        lab.database,
        clock=fixed_clock,
        id_factory=lab.ids,
    ).adopt_candidate(
        receipt=receipt,
        mission_id=receipt.mission_id,
        claim_id=lab.research.list_claims(receipt.mission_id)[0].id,
        confirmation=_confirmation(receipt),
        expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
        stance=EvidenceStance.SUPPORTS,
        supersedes_evidence_id=supersedes,
        identity=lab.identity,
    )


def _check(report: DoctorReport, name: str) -> bool:
    return next(check.ok for check in report.checks if check.name == name)


def test_replay_evidence_insert_and_audits_use_one_writable_transaction_connection(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    replay_original = LensService._search_normalized_in_transaction
    evidence_original = EvidenceService._add_evidence_in_transaction
    connections: list[sqlite3.Connection] = []

    def replay_probe(
        service: LensService,
        *args: object,
        connection: sqlite3.Connection,
        **kwargs: object,
    ):
        assert connection.in_transaction
        assert int(connection.execute("PRAGMA query_only").fetchone()[0]) == 0
        competitor = lab.database.connect()
        try:
            competitor.execute("PRAGMA busy_timeout = 0")
            with pytest.raises(sqlite3.OperationalError) as locked:
                competitor.execute("BEGIN IMMEDIATE")
            assert int(locked.value.sqlite_errorcode or 0) & 0xFF == sqlite3.SQLITE_BUSY
        finally:
            competitor.close()
        connections.append(connection)
        return replay_original(service, *args, connection=connection, **kwargs)

    def evidence_probe(
        service: EvidenceService,
        connection: sqlite3.Connection,
        *args: object,
        **kwargs: object,
    ):
        assert connection.in_transaction
        assert int(connection.execute("PRAGMA query_only").fetchone()[0]) == 0
        connections.append(connection)
        return evidence_original(service, connection, *args, **kwargs)

    monkeypatch.setattr(LensService, "_search_normalized_in_transaction", replay_probe)
    monkeypatch.setattr(EvidenceService, "_add_evidence_in_transaction", evidence_probe)

    result = _adopt(lab, receipt)

    assert result.status == "adopted"
    assert len(connections) == 2
    assert connections[0] is connections[1]
    with lab.database.read() as connection:
        rows = list(
            connection.execute(
                """
                SELECT sequence, event_type FROM audit_events
                WHERE entity_id = ? ORDER BY sequence
                """,
                (result.evidence.id,),
            )
        )
    assert [str(row["event_type"]) for row in rows] == [
        "evidence.card.created",
        "lens.candidate.adopted",
    ]
    assert int(rows[1]["sequence"]) == int(rows[0]["sequence"]) + 1


def test_current_database_replay_mismatch_rolls_back_without_adoption_state(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"first matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=b"second matching observation\n",
        original_label="later.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    with lab.database.read() as connection:
        before_audit = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

    with pytest.raises(IntegrityError) as caught:
        _adopt(lab, receipt)

    assert caught.value.code == "lens_replay_mismatch"
    assert lab.evidence.ledger_for_claim(seed.claim.id) == ()
    with lab.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before_audit
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'lens.candidate.adopted'"
            ).fetchone()[0]
            == 0
        )


def test_adoption_refuses_to_extend_a_corrupt_supersession_cycle(lab: Lab) -> None:
    seed = lab.seed_claim(
        content=b"matching first\nmatching second\nmatching third\n",
    )
    first = lab.cite(seed, "matching first", EvidenceStance.CONTEXT)
    second = lab.cite(
        seed,
        "matching second",
        EvidenceStance.INCONCLUSIVE,
        supersedes_evidence_id=first.id,
    )
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER evidence_no_update")
        connection.execute(
            "UPDATE evidence_cards SET supersedes_evidence_id = ? WHERE id = ?",
            (second.id, first.id),
        )
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="third",
    )
    before = len(lab.evidence.ledger_for_claim(seed.claim.id))

    with pytest.raises(IntegrityError) as caught:
        _adopt(lab, receipt, supersedes=second.id)

    assert caught.value.code == "evidence_supersession_invalid"
    assert len(lab.evidence.ledger_for_claim(seed.claim.id)) == before
    with lab.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'lens.candidate.adopted'"
            ).fetchone()[0]
            == 0
        )


def test_deep_doctor_reconciles_a_healthy_lens_adoption(lab: Lab) -> None:
    seed = lab.seed_claim(content="Café matching observation\n".encode())
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    result = _adopt(lab, receipt)

    report = run_doctor(lab.database, deep=True)

    assert report.ok
    assert _check(report, "material_audit_integrity")
    with lab.database.read() as connection:
        details = json.loads(
            str(
                connection.execute(
                    "SELECT details_json FROM audit_events WHERE id = ?",
                    (result.adoption_audit_event_id,),
                ).fetchone()[0]
            )
        )
    assert details["quote_sha256"] == result.quote_sha256
    assert "quote" not in details


class _SilentAdoptionAudit:
    def __init__(self, ids: SequenceIds) -> None:
        self._ids = ids
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
            return self._ids("aud")
        return self._delegate.record(
            connection,
            identity=identity,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            mission_id=mission_id,
            details=details,
        )


def test_silent_adoption_audit_sink_rolls_back_card_events_and_new_run(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    new_identity = IdentityContext(
        actor_id="os-user:silent-audit-probe",
        actor_kind=ActorKind.OS_USER,
        run_id=lab.ids("run"),
        purpose="prove Lens adoption audit postconditions",
    )
    with lab.database.read() as connection:
        before_dump = tuple(connection.iterdump())

    with pytest.raises(IntegrityError) as caught:
        LensEvidenceAdoptionService(
            lab.database,
            audit=_SilentAdoptionAudit(lab.ids),
            clock=fixed_clock,
            id_factory=lab.ids,
        ).adopt_candidate(
            receipt=receipt,
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            confirmation=_confirmation(receipt),
            expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
            stance=EvidenceStance.SUPPORTS,
            identity=new_identity,
        )

    assert caught.value.code == "lens_adoption_audit_invalid"
    with lab.database.read() as connection:
        assert tuple(connection.iterdump()) == before_dump


@pytest.mark.parametrize("corruption", ["tamper", "orphan", "duplicate"])
def test_deep_doctor_detects_tampered_or_unpaired_adoption_audit(
    lab: Lab,
    corruption: str,
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    result = _adopt(lab, receipt)
    with lab.database.transaction() as connection:
        existing = connection.execute(
            "SELECT * FROM audit_events WHERE id = ?",
            (result.adoption_audit_event_id,),
        ).fetchone()
        assert existing is not None
        if corruption == "tamper":
            details = json.loads(str(existing["details_json"]))
            details["quote_sha256"] = "f" * 64
            connection.execute("DROP TRIGGER audit_no_update")
            connection.execute(
                "UPDATE audit_events SET details_json = ? WHERE id = ?",
                (
                    json.dumps(details, sort_keys=True, separators=(",", ":")),
                    result.adoption_audit_event_id,
                ),
            )
        else:
            entity_id = result.evidence.id if corruption == "duplicate" else "evd_" + "f" * 32
            connection.execute(
                """
                INSERT INTO audit_events(
                    id, event_type, entity_type, entity_id, mission_id,
                    actor_id, run_id, occurred_at, details_json
                ) VALUES (?, 'lens.candidate.adopted', 'evidence_card', ?, ?, ?, ?, ?, ?)
                """,
                (
                    lab.ids("aud"),
                    entity_id,
                    seed.mission.id,
                    lab.identity.actor_id,
                    lab.identity.run_id,
                    fixed_clock(),
                    str(existing["details_json"]),
                ),
            )

    report = run_doctor(lab.database, deep=True)

    assert not report.ok
    assert not _check(report, "material_audit_integrity")


def test_schema_v4_database_requires_explicit_migration_before_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy = Database(tmp_path / "legacy-lens-adoption-v4.db")
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:4])
    assert legacy.initialize() == 4

    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-lens-adoption",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify explicit migration before Lens evidence adoption",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy Lens adoption mission",
        objective="Adopt only after the owner-approved schema is current.",
        identity=identity,
    )
    question = research.add_question(
        mission_id=mission.id,
        text="Can a verified local lead become reviewed evidence?",
        identity=identity,
    )
    claim = research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="The local observation supports this claim.",
        falsification_criteria="An exact opposing observation would falsify it.",
        identity=identity,
    )
    SourceService(legacy, clock=fixed_clock, id_factory=ids).import_bytes(
        mission_id=mission.id,
        content=b"legacy matching observation\n",
        original_label="legacy.txt",
        media_type="text/plain",
        identity=identity,
    )
    receipt = LensService(legacy).search(mission_id=mission.id, query="matching")
    candidate = receipt.candidates[0]

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    service = LensEvidenceAdoptionService(
        legacy,
        clock=fixed_clock,
        id_factory=ids,
    )
    with pytest.raises(IntegrityError) as required:
        service.adopt_candidate(
            receipt=receipt,
            mission_id=mission.id,
            claim_id=claim.id,
            confirmation=LensCandidateConfirmation(
                rank=1,
                snapshot_sha256=candidate.snapshot_sha256,
                start_byte=candidate.start_byte,
                end_byte=candidate.end_byte,
                quote_sha256=candidate.quote_sha256,
            ),
            expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )
    assert required.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    result = service.adopt_candidate(
        receipt=receipt,
        mission_id=mission.id,
        claim_id=claim.id,
        confirmation=LensCandidateConfirmation(
            rank=1,
            snapshot_sha256=candidate.snapshot_sha256,
            start_byte=candidate.start_byte,
            end_byte=candidate.end_byte,
            quote_sha256=candidate.quote_sha256,
        ),
        expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
        stance=EvidenceStance.SUPPORTS,
        identity=identity,
    )
    assert result.status == "adopted"
    assert legacy.schema_version() == 5
