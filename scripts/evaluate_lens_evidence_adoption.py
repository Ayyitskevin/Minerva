"""Evaluate deterministic, explicit Lens-to-evidence adoption on fixed fixtures."""

from __future__ import annotations

import argparse
import base64
import json
import socket
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from minerva.core.audit import AuditRecorder
from minerva.core.db import Database, latest_schema_version
from minerva.core.doctor import run_doctor
from minerva.core.errors import MinervaError
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence import (
    EvidenceStance,
    LensCandidateConfirmation,
    LensEvidenceAdoptionService,
)
from minerva.lens import LensBounds, LensService
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

_CLOCK = "2026-08-08T12:00:00.000000Z"
_PROTECTED_TABLES = (
    "schema_migrations",
    "research_runs",
    "research_missions",
    "research_questions",
    "claims",
    "claim_status_events",
    "sources",
    "source_snapshots",
    "evidence_withdrawals",
    "findings",
    "finding_citations",
    "finding_retractions",
    "brief_exports",
    "agent_inferences",
    "agent_inference_citations",
    "agent_inference_retractions",
    "agent_inference_promotions",
)


class _SequenceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


class _FailOnAdoptionAudit:
    """Delegate normal audit work, then fail at the second feature audit."""

    def __init__(self, recorder: AuditRecorder) -> None:
        self._recorder = recorder

    def ensure_run(self, connection: sqlite3.Connection, identity: IdentityContext) -> None:
        self._recorder.ensure_run(connection, identity)

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
            raise RuntimeError("fixed evaluation failure at Lens adoption audit")
        return self._recorder.record(
            connection,
            identity=identity,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            mission_id=mission_id,
            details=details,
        )


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


def _jsonable_sql_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    if value is None or isinstance(value, str | int | float):
        return value
    raise TypeError(f"unsupported SQLite value in evaluation: {type(value).__name__}")


def _table_state(database: Database, tables: tuple[str, ...]) -> dict[str, object]:
    state: dict[str, object] = {}
    with database.read() as connection:
        for table in tables:
            columns = tuple(
                str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")
            )
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid"  # noqa: S608 - fixed table tuple.
            ).fetchall()
            state[table] = {
                "columns": columns,
                "rows": tuple(tuple(_jsonable_sql_value(value) for value in row) for row in rows),
            }
    return state


def _logical_state_digest(database: Database) -> str:
    with database.read() as connection:
        dump = tuple(connection.iterdump())
    return sha256(_canonical_bytes(dump)).hexdigest()


def _counts(database: Database) -> dict[str, int]:
    with database.read() as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in (*_PROTECTED_TABLES, "evidence_cards", "audit_events")
        }


def _error_code(action: Callable[[], object]) -> str | None:
    try:
        action()
    except MinervaError as error:
        return error.code
    return None


def evaluate_lens_evidence_adoption() -> dict[str, object]:
    """Return fixed-fixture safety and provenance measurements for adoption v1."""
    with tempfile.TemporaryDirectory(prefix="minerva-lens-adoption-evaluation-") as temporary:
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:lens-adoption-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="evaluate explicit Lens evidence adoption",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)

        mission = research.create_mission(
            title="Lens adoption evaluation mission",
            objective="Measure exact, explicit adoption without silent epistemic effects.",
            identity=identity,
        )
        question = research.add_question(
            mission_id=mission.id,
            text="Can one captured Lens lead be cited exactly?",
            identity=identity,
        )
        claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="The captured local passage can be cited by exact UTF-8 bytes.",
            falsification_criteria="The stored byte interval does not reproduce the passage.",
            identity=identity,
        )
        foreign_mission = research.create_mission(
            title="Lens adoption isolation control",
            objective="Refuse adoption outside the receipt mission.",
            identity=identity,
        )
        foreign_question = research.add_question(
            mission_id=foreign_mission.id,
            text="Must foreign evidence remain isolated?",
            identity=identity,
        )
        foreign_claim = research.add_claim(
            mission_id=foreign_mission.id,
            question_id=foreign_question.id,
            statement="Evidence from another mission remains unavailable here.",
            falsification_criteria="A foreign candidate can be adopted into this mission.",
            identity=identity,
        )

        content = (
            "A preliminary line is deliberately irrelevant.\n"
            "Exact Café 東京 provenance survives byte adoption.\n"
        ).encode()
        sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label="utf8-provenance.txt",
            media_type="text/plain",
            identity=identity,
        )
        sources.import_bytes(
            mission_id=foreign_mission.id,
            content=b"Exact provenance in a foreign mission must remain isolated.\n",
            original_label="foreign-control.txt",
            media_type="text/plain",
            identity=identity,
        )

        receipt = LensService(database).search(
            mission_id=mission.id,
            query="Café 東京 provenance",
            bounds=LensBounds(max_results=3, max_snapshots=10, max_corpus_bytes=1_000_000),
        )
        candidate = receipt.candidates[0]
        confirmation = LensCandidateConfirmation(
            rank=candidate.rank,
            snapshot_sha256=candidate.snapshot_sha256,
            start_byte=candidate.start_byte,
            end_byte=candidate.end_byte,
            quote_sha256=candidate.quote_sha256,
        )

        provider_calls = 0
        network_calls = 0

        def _forbid_provider(*_args: object, **_kwargs: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("Lens adoption attempted provider construction")

        def _forbid_network(*_args: object, **_kwargs: object) -> object:
            nonlocal network_calls
            network_calls += 1
            raise AssertionError("Lens adoption attempted network access")

        protected_before = _table_state(database, _PROTECTED_TABLES)
        counts_before = _counts(database)
        adoption = LensEvidenceAdoptionService(
            database,
            clock=_fixed_clock,
            id_factory=ids,
        )
        with (
            patch("minerva.integrations.ai.candidate_provider", _forbid_provider),
            patch.object(socket, "create_connection", _forbid_network),
            patch.object(socket.socket, "connect", _forbid_network),
            patch.object(socket.socket, "connect_ex", _forbid_network),
            patch.object(socket.socket, "sendto", _forbid_network),
            patch.object(socket.socket, "sendmsg", _forbid_network),
        ):
            result = adoption.adopt_candidate(
                receipt=receipt,
                mission_id=mission.id,
                claim_id=claim.id,
                confirmation=confirmation,
                expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
                stance=EvidenceStance.INCONCLUSIVE,
                identity=identity,
            )
            counts_after_success = _counts(database)
            protected_after_success = _table_state(database, _PROTECTED_TABLES)
            after_success_digest = _logical_state_digest(database)
            duplicate_before = after_success_digest
            duplicate_error = _error_code(
                lambda: adoption.adopt_candidate(
                    receipt=receipt,
                    mission_id=mission.id,
                    claim_id=claim.id,
                    confirmation=confirmation,
                    expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
                    stance=EvidenceStance.INCONCLUSIVE,
                    identity=identity,
                )
            )
            duplicate_after = _logical_state_digest(database)

            atomic_before = duplicate_after
            failing_audit = _FailOnAdoptionAudit(AuditRecorder(clock=_fixed_clock, id_factory=ids))
            failing_service = LensEvidenceAdoptionService(
                database,
                audit=failing_audit,
                clock=_fixed_clock,
                id_factory=ids,
            )
            atomic_failure_observed = False
            try:
                failing_service.adopt_candidate(
                    receipt=receipt,
                    mission_id=mission.id,
                    claim_id=claim.id,
                    confirmation=confirmation,
                    expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
                    stance=EvidenceStance.SUPPORTS,
                    identity=identity,
                )
            except RuntimeError as error:
                atomic_failure_observed = str(error).startswith("fixed evaluation failure")
            atomic_after = _logical_state_digest(database)

            isolation_before = atomic_after
            isolation_error = _error_code(
                lambda: adoption.adopt_candidate(
                    receipt=receipt,
                    mission_id=foreign_mission.id,
                    claim_id=foreign_claim.id,
                    confirmation=confirmation,
                    expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
                    stance=EvidenceStance.CONTEXT,
                    identity=identity,
                )
            )
            isolation_after = _logical_state_digest(database)

            sources.import_bytes(
                mission_id=mission.id,
                content=b"Later in-scope snapshot changes the captured corpus set.\n",
                original_label="in-scope-drift.txt",
                media_type="text/plain",
                identity=identity,
            )
            drift_before = _logical_state_digest(database)
            drift_error = _error_code(
                lambda: adoption.adopt_candidate(
                    receipt=receipt,
                    mission_id=mission.id,
                    claim_id=claim.id,
                    confirmation=confirmation,
                    expected_retrieval_receipt_sha256=receipt.retrieval_receipt_sha256,
                    stance=EvidenceStance.CONTEXT,
                    identity=identity,
                )
            )
            drift_after = _logical_state_digest(database)

        unauthorized_mutation_count = sum(
            protected_before[table] != protected_after_success[table] for table in _PROTECTED_TABLES
        )

        quoted_bytes = candidate.quote.encode("utf-8")
        exact_span = content[candidate.start_byte : candidate.end_byte]
        with database.read() as connection:
            evidence_row = connection.execute(
                "SELECT * FROM evidence_cards WHERE id = ?", (result.evidence.id,)
            ).fetchone()
            feature_audits = connection.execute(
                """
                SELECT event_type, entity_type, entity_id, mission_id, actor_id, run_id,
                       details_json
                FROM audit_events
                WHERE entity_id = ? AND event_type IN (
                    'evidence.card.created', 'lens.candidate.adopted'
                )
                ORDER BY sequence
                """,
                (result.evidence.id,),
            ).fetchall()
            snapshot_count = int(
                connection.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0]
            )

        creation_details = json.loads(str(feature_audits[0]["details_json"]))
        adoption_details = json.loads(str(feature_audits[1]["details_json"]))
        exact_candidate_binding = bool(
            evidence_row is not None
            and result.mission_id == candidate.mission_id == mission.id
            and result.claim_id == claim.id
            and result.candidate_rank == candidate.rank
            and result.retrieval_receipt_sha256 == receipt.retrieval_receipt_sha256
            and result.query_sha256 == receipt.query_sha256
            and result.snapshot_set_sha256 == receipt.snapshot_set_sha256
            and result.source_id == candidate.source_id
            and result.snapshot_id == candidate.snapshot_id == str(evidence_row["snapshot_id"])
            and result.snapshot_sha256
            == candidate.snapshot_sha256
            == str(evidence_row["snapshot_sha256"])
            and result.start_byte == candidate.start_byte == int(evidence_row["start_byte"])
            and result.end_byte == candidate.end_byte == int(evidence_row["end_byte"])
            and result.quote_sha256 == candidate.quote_sha256
            and candidate.quote == str(evidence_row["quote"])
            and exact_span == quoted_bytes
            and base64.b64decode(candidate.quote_utf8_base64, validate=True) == quoted_bytes
            and sha256(quoted_bytes).hexdigest() == candidate.quote_sha256
        )
        explicit_stance_preserved = bool(
            candidate.stance == "unassessed"
            and result.stance is EvidenceStance.INCONCLUSIVE
            and result.evidence.stance is EvidenceStance.INCONCLUSIVE
            and evidence_row is not None
            and str(evidence_row["stance"]) == EvidenceStance.INCONCLUSIVE.value
        )
        feature_audits_bound = bool(
            len(feature_audits) == 2
            and [str(row["event_type"]) for row in feature_audits]
            == ["evidence.card.created", "lens.candidate.adopted"]
            and all(str(row["entity_type"]) == "evidence_card" for row in feature_audits)
            and all(str(row["entity_id"]) == result.evidence.id for row in feature_audits)
            and all(str(row["mission_id"]) == mission.id for row in feature_audits)
            and all(str(row["actor_id"]) == identity.actor_id for row in feature_audits)
            and all(str(row["run_id"]) == identity.run_id for row in feature_audits)
            and creation_details["claim_id"] == claim.id
            and creation_details["snapshot_id"] == candidate.snapshot_id
            and adoption_details["candidate_rank"] == candidate.rank
            and adoption_details["retrieval_receipt_sha256"] == receipt.retrieval_receipt_sha256
            and adoption_details["quote_sha256"] == candidate.quote_sha256
            and adoption_details["stance"] == EvidenceStance.INCONCLUSIVE.value
        )
        success_delta = {
            table: counts_after_success[table] - counts_before[table] for table in counts_before
        }
        exact_authorized_delta = bool(
            success_delta["evidence_cards"] == 1
            and success_delta["audit_events"] == 2
            and all(
                delta == 0
                for table, delta in success_delta.items()
                if table not in {"evidence_cards", "audit_events"}
            )
            and unauthorized_mutation_count == 0
        )
        boundary = result.semantic_boundary

        return {
            "schema_version": "minerva.lens-evidence-adoption-evaluation.v1",
            "algorithm": "verified-current-replay-single-candidate",
            "algorithm_version": "1",
            "successful_adoption_count": 1,
            "exact_candidate_binding": exact_candidate_binding,
            "utf8_byte_span_accuracy_ppm": 1_000_000 if exact_candidate_binding else 0,
            "explicit_stance_preserved": explicit_stance_preserved,
            "evidence_creation_and_adoption_audits_bound": feature_audits_bound,
            "atomic_authorized_state_delta": exact_authorized_delta,
            "atomic_rollback_on_second_audit_failure": (
                atomic_failure_observed and atomic_before == atomic_after
            ),
            "duplicate_refusal": (
                duplicate_error == "lens_candidate_already_adopted"
                and duplicate_before == duplicate_after
            ),
            "corpus_drift_refusal": (
                drift_error == "lens_replay_mismatch" and drift_before == drift_after
            ),
            "mission_isolation_refusal": (
                isolation_error == "lens_adoption_scope_invalid"
                and isolation_before == isolation_after
            ),
            "semantic_non_effects_declared": (
                boundary.operator_supplied_stance
                and not boundary.rank_used_as_epistemic_weight
                and not boundary.determines_truth_or_source_quality
                and not boundary.calculates_confidence
                and not boundary.alters_claim_status
                and not boundary.creates_or_retracts_findings
                and not boundary.persists_agent_inference
                and not boundary.invokes_model_provider_or_network
            ),
            "deep_integrity": run_doctor(database, deep=True).ok,
            "schema_version_unchanged": latest_schema_version() == 5,
            "provider_invocation_count": provider_calls,
            "network_invocation_count": network_calls,
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_claim_count": 2,
            "fixture_snapshot_count": snapshot_count,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(_canonical_bytes(evaluate_lens_evidence_adoption()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
