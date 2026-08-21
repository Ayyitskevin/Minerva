"""Explicitly adopt one verified Lens lead through the evidence boundary."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from hashlib import sha256

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now
from minerva.evidence.models import (
    EvidenceStance,
    LensCandidateConfirmation,
    LensEvidenceAdoptionResult,
    LensEvidenceAdoptionSemanticBoundary,
)
from minerva.evidence.service import EvidenceService, _validate_supersession_chain
from minerva.lens.models import LensCandidateContext, LensSearchResult
from minerva.lens.receipt import (
    _replay_lens_receipt_in_transaction,
    verify_lens_receipt,
)
from minerva.lens.service import LensService

LENS_EVIDENCE_ADOPTION_SCHEMA_VERSION = "minerva.lens-evidence-adoption.v1"
LENS_EVIDENCE_ADOPTION_KIND = "single_candidate_evidence_adoption"
LENS_EVIDENCE_ADOPTION_NOTICE = (
    "One operator-selected Lens lead was reproduced against the current local database "
    "and added through normal evidence validation. Rank is not epistemic weight; the "
    "operator supplied stance, and this action does not determine truth, confidence, "
    "claim status, findings, or source quality."
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"clm_[0-9a-f]{32}\Z")
_EVIDENCE_ID = re.compile(r"evd_[0-9a-f]{32}\Z")
_AUDIT_ID = re.compile(r"aud_[0-9a-f]{32}\Z")


class LensEvidenceAdoptionService:
    """Create one EvidenceCard from one exactly reproduced Lens candidate."""

    def __init__(
        self,
        database: Database,
        *,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> None:
        self.database = database
        self._audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)
        self._lens = LensService(database)
        self._evidence = EvidenceService(
            database,
            audit=self._audit,
            clock=clock,
            id_factory=id_factory,
        )

    def adopt_candidate(
        self,
        *,
        receipt: LensSearchResult,
        mission_id: str,
        claim_id: str,
        confirmation: LensCandidateConfirmation,
        expected_retrieval_receipt_sha256: str,
        stance: EvidenceStance,
        identity: IdentityContext,
        supersedes_evidence_id: str | None = None,
    ) -> LensEvidenceAdoptionResult:
        """Verify, reproduce, and adopt exactly one explicitly confirmed lead.

        Receipt verification and confirmation happen before opening SQLite. The
        exact current replay, duplicate refusal, evidence insert, and both audit
        records then share one ``BEGIN IMMEDIATE`` transaction.
        """

        verified = verify_lens_receipt(receipt)
        candidate = _validate_adoption_request(
            receipt=verified,
            mission_id=mission_id,
            claim_id=claim_id,
            confirmation=confirmation,
            expected_retrieval_receipt_sha256=expected_retrieval_receipt_sha256,
            stance=stance,
            supersedes_evidence_id=supersedes_evidence_id,
        )

        with self.database.transaction() as connection:
            _replay_lens_receipt_in_transaction(
                self._lens,
                verified,
                connection=connection,
            )
            duplicate = connection.execute(
                """
                SELECT 1 FROM evidence_cards
                WHERE mission_id = ? AND claim_id = ? AND snapshot_id = ?
                  AND snapshot_sha256 = ? AND start_byte = ? AND end_byte = ?
                  AND quote = ? AND stance = ?
                  AND supersedes_evidence_id IS ?
                LIMIT 1
                """,
                (
                    mission_id,
                    claim_id,
                    candidate.snapshot_id,
                    candidate.snapshot_sha256,
                    candidate.start_byte,
                    candidate.end_byte,
                    candidate.quote,
                    stance.value,
                    supersedes_evidence_id,
                ),
            ).fetchone()
            if duplicate is not None:
                raise ConflictError(
                    "lens_candidate_already_adopted",
                    "This Lens candidate and evidence evaluation already exist.",
                )
            if supersedes_evidence_id is not None:
                _validate_supersession_chain(
                    connection,
                    mission_id=mission_id,
                    claim_id=claim_id,
                    evidence_id=supersedes_evidence_id,
                )

            evidence = self._evidence._add_evidence_in_transaction(
                connection,
                mission_id=mission_id,
                claim_id=claim_id,
                snapshot_id=candidate.snapshot_id,
                start_byte=candidate.start_byte,
                end_byte=candidate.end_byte,
                quote=candidate.quote,
                stance=stance,
                identity=identity,
                supersedes_evidence_id=supersedes_evidence_id,
            )
            adoption_details = {
                "candidate_rank": candidate.rank,
                "claim_id": claim_id,
                "end_byte": candidate.end_byte,
                "query_sha256": verified.query_sha256,
                "quote_sha256": candidate.quote_sha256,
                "retrieval_receipt_sha256": verified.retrieval_receipt_sha256,
                "retrieval_truncated": verified.truncated,
                "snapshot_id": candidate.snapshot_id,
                "snapshot_set_sha256": verified.snapshot_set_sha256,
                "snapshot_sha256": candidate.snapshot_sha256,
                "stance": stance.value,
                "start_byte": candidate.start_byte,
                "supersedes": supersedes_evidence_id,
            }
            adoption_audit_event_id = self._audit.record(
                connection,
                identity=identity,
                event_type="lens.candidate.adopted",
                entity_type="evidence_card",
                entity_id=evidence.id,
                mission_id=mission_id,
                details=adoption_details,
            )
            _verify_adoption_audit_postcondition(
                connection,
                evidence_id=evidence.id,
                mission_id=mission_id,
                identity=identity,
                adoption_audit_event_id=adoption_audit_event_id,
                creation_details={
                    "claim_id": claim_id,
                    "end_byte": candidate.end_byte,
                    "snapshot_id": candidate.snapshot_id,
                    "snapshot_sha256": candidate.snapshot_sha256,
                    "stance": stance.value,
                    "start_byte": candidate.start_byte,
                    "supersedes": supersedes_evidence_id,
                },
                adoption_details=adoption_details,
            )

        return LensEvidenceAdoptionResult(
            schema_version=LENS_EVIDENCE_ADOPTION_SCHEMA_VERSION,
            kind=LENS_EVIDENCE_ADOPTION_KIND,
            status="adopted",
            mission_id=mission_id,
            claim_id=claim_id,
            retrieval_receipt_sha256=verified.retrieval_receipt_sha256,
            query_sha256=verified.query_sha256,
            snapshot_set_sha256=verified.snapshot_set_sha256,
            candidate_rank=candidate.rank,
            source_id=candidate.source_id,
            snapshot_id=candidate.snapshot_id,
            snapshot_sha256=candidate.snapshot_sha256,
            start_byte=candidate.start_byte,
            end_byte=candidate.end_byte,
            quote_sha256=candidate.quote_sha256,
            retrieval_truncated=verified.truncated,
            stance=stance,
            supersedes_evidence_id=supersedes_evidence_id,
            evidence=evidence,
            adoption_audit_event_id=adoption_audit_event_id,
            semantic_notice=LENS_EVIDENCE_ADOPTION_NOTICE,
            semantic_boundary=LensEvidenceAdoptionSemanticBoundary(),
        )


def _validate_adoption_request(
    *,
    receipt: LensSearchResult,
    mission_id: object,
    claim_id: object,
    confirmation: object,
    expected_retrieval_receipt_sha256: object,
    stance: object,
    supersedes_evidence_id: object,
) -> LensCandidateContext:
    if (
        not isinstance(mission_id, str)
        or _MISSION_ID.fullmatch(mission_id) is None
        or not isinstance(claim_id, str)
        or _CLAIM_ID.fullmatch(claim_id) is None
        or mission_id != receipt.mission_id
        or (
            supersedes_evidence_id is not None
            and (
                not isinstance(supersedes_evidence_id, str)
                or _EVIDENCE_ID.fullmatch(supersedes_evidence_id) is None
            )
        )
    ):
        raise IntegrityError(
            "lens_adoption_scope_invalid",
            "The Lens adoption scope is invalid.",
        )
    if not isinstance(stance, EvidenceStance):
        raise IntegrityError(
            "evidence_stance_invalid",
            "Evidence stance is invalid.",
        )
    if (
        not isinstance(expected_retrieval_receipt_sha256, str)
        or _SHA256.fullmatch(expected_retrieval_receipt_sha256) is None
        or not isinstance(confirmation, LensCandidateConfirmation)
    ):
        raise IntegrityError(
            "lens_adoption_confirmation_invalid",
            "The Lens candidate confirmation is invalid.",
        )
    if (
        isinstance(confirmation.rank, bool)
        or not isinstance(confirmation.rank, int)
        or not 1 <= confirmation.rank <= len(receipt.candidates)
    ):
        raise IntegrityError(
            "lens_adoption_candidate_rank_invalid",
            "The Lens candidate rank is invalid.",
        )
    if (
        not isinstance(confirmation.start_byte, int)
        or isinstance(confirmation.start_byte, bool)
        or not isinstance(confirmation.end_byte, int)
        or isinstance(confirmation.end_byte, bool)
        or not isinstance(confirmation.snapshot_sha256, str)
        or not isinstance(confirmation.quote_sha256, str)
        or _SHA256.fullmatch(confirmation.snapshot_sha256) is None
        or _SHA256.fullmatch(confirmation.quote_sha256) is None
    ):
        raise IntegrityError(
            "lens_adoption_confirmation_invalid",
            "The Lens candidate confirmation is invalid.",
        )
    candidate = receipt.candidates[confirmation.rank - 1]
    if (
        expected_retrieval_receipt_sha256 != receipt.retrieval_receipt_sha256
        or confirmation.snapshot_sha256 != candidate.snapshot_sha256
        or confirmation.start_byte != candidate.start_byte
        or confirmation.end_byte != candidate.end_byte
        or confirmation.quote_sha256 != candidate.quote_sha256
        or sha256(candidate.quote.encode("utf-8")).hexdigest() != candidate.quote_sha256
    ):
        raise IntegrityError(
            "lens_adoption_confirmation_mismatch",
            "The explicit Lens candidate confirmation does not match the receipt.",
        )
    return candidate


def _verify_adoption_audit_postcondition(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    mission_id: str,
    identity: IdentityContext,
    adoption_audit_event_id: object,
    creation_details: Mapping[str, object],
    adoption_details: Mapping[str, object],
) -> None:
    """Require both exact feature audits before the writer may commit.

    Audit sinks are injectable for repository tests and integrations. A sink
    that returns without writing must never weaken the bridge's durable receipt
    provenance guarantee, so this service verifies the stored postcondition in
    the same transaction rather than trusting the sink's return value.
    """

    if (
        not isinstance(adoption_audit_event_id, str)
        or _AUDIT_ID.fullmatch(adoption_audit_event_id) is None
    ):
        _audit_invalid()
    rows = list(
        connection.execute(
            """
            SELECT sequence, id, event_type, entity_type, entity_id, mission_id,
                   actor_id, run_id, details_json
            FROM audit_events
            WHERE entity_id = ?
              AND event_type IN ('evidence.card.created', 'lens.candidate.adopted')
            ORDER BY sequence
            """,
            (evidence_id,),
        )
    )
    if (
        len(rows) != 2
        or str(rows[0]["event_type"]) != "evidence.card.created"
        or str(rows[1]["event_type"]) != "lens.candidate.adopted"
        or int(rows[1]["sequence"]) != int(rows[0]["sequence"]) + 1
        or str(rows[1]["id"]) != adoption_audit_event_id
    ):
        _audit_invalid()
    expected_details = (creation_details, adoption_details)
    for row, details in zip(rows, expected_details, strict=True):
        canonical_details = json.dumps(
            dict(details),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if (
            _AUDIT_ID.fullmatch(str(row["id"])) is None
            or str(row["entity_type"]) != "evidence_card"
            or str(row["entity_id"]) != evidence_id
            or str(row["mission_id"]) != mission_id
            or str(row["actor_id"]) != identity.actor_id
            or str(row["run_id"]) != identity.run_id
            or str(row["details_json"]) != canonical_details
        ):
            _audit_invalid()


def _audit_invalid() -> None:
    raise IntegrityError(
        "lens_adoption_audit_invalid",
        "Lens evidence adoption audit provenance is incomplete or inconsistent.",
    )
