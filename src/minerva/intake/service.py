"""Preview and file one exact quote without weakening evidence invariants."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, replace
from hashlib import sha256

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now
from minerva.evidence.models import EvidenceStance
from minerva.evidence.service import (
    EvidenceService,
    _validate_evidence_input,
    _validate_supersession_chain,
)
from minerva.intake.models import (
    EvidenceIntakeCandidate,
    EvidenceIntakePreview,
    EvidenceIntakeResult,
    EvidenceIntakeSemanticBoundary,
)
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

INTAKE_PREVIEW_SCHEMA_VERSION = "minerva.evidence-intake-preview.v1"
INTAKE_RESULT_SCHEMA_VERSION = "minerva.evidence-intake.v1"
INTAKE_ALGORITHM = "exact-utf8-byte-match"
INTAKE_ALGORITHM_VERSION = 1
INTAKE_MAX_CANDIDATES = 100
INTAKE_CONTEXT_BYTES = 80
INTAKE_NOTICE = (
    "Exact occurrences in one verified immutable snapshot are review candidates only. "
    "The operator selects one occurrence and supplies stance; intake does not determine "
    "truth, confidence, relevance, or source quality."
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"clm_[0-9a-f]{32}\Z")
_SNAPSHOT_ID = re.compile(r"snp_[0-9a-f]{32}\Z")
_EVIDENCE_ID = re.compile(r"evd_[0-9a-f]{32}\Z")
_AUDIT_ID = re.compile(r"aud_[0-9a-f]{32}\Z")


class EvidenceIntakeService:
    """Locate exact quotes and file one explicitly confirmed occurrence."""

    def __init__(
        self,
        database: Database,
        *,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> None:
        self.database = database
        resolved_audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)
        self._research = ResearchService(database, clock=clock, id_factory=id_factory)
        self._sources = SourceService(database, clock=clock, id_factory=id_factory)
        self._evidence = EvidenceService(
            database,
            audit=resolved_audit,
            clock=clock,
            id_factory=id_factory,
        )

    def preview(
        self,
        *,
        mission_id: str,
        claim_id: str,
        snapshot_id: str,
        quote: str,
    ) -> EvidenceIntakePreview:
        """Return every bounded exact occurrence without creating state."""

        quote_bytes = _validated_quote_bytes(quote)
        with self.database.read() as connection:
            return self._preview_in_connection(
                connection,
                mission_id=mission_id,
                claim_id=claim_id,
                snapshot_id=snapshot_id,
                quote=quote,
                quote_bytes=quote_bytes,
            )

    def file_evidence(
        self,
        *,
        mission_id: str,
        claim_id: str,
        snapshot_id: str,
        quote: str,
        candidate_rank: int,
        expected_intake_preview_sha256: str,
        expected_snapshot_sha256: str,
        expected_mission_audit_sequence: int,
        stance: EvidenceStance,
        identity: IdentityContext,
        supersedes_evidence_id: str | None = None,
    ) -> EvidenceIntakeResult:
        """Reproduce a preview and file one candidate in one write transaction."""

        quote_bytes = _validate_confirmation(
            mission_id=mission_id,
            claim_id=claim_id,
            snapshot_id=snapshot_id,
            quote=quote,
            candidate_rank=candidate_rank,
            expected_intake_preview_sha256=expected_intake_preview_sha256,
            expected_snapshot_sha256=expected_snapshot_sha256,
            expected_mission_audit_sequence=expected_mission_audit_sequence,
            stance=stance,
            supersedes_evidence_id=supersedes_evidence_id,
        )

        with self.database.transaction() as connection:
            current_sequence = self._research.get_mission_audit_sequence(
                mission_id,
                connection=connection,
            )
            if current_sequence != expected_mission_audit_sequence:
                raise ConflictError(
                    "mission_version_conflict",
                    "The mission changed; preview intake again before filing evidence.",
                )
            preview = self._preview_in_connection(
                connection,
                mission_id=mission_id,
                claim_id=claim_id,
                snapshot_id=snapshot_id,
                quote=quote,
                quote_bytes=quote_bytes,
            )
            if preview.intake_preview_sha256 != expected_intake_preview_sha256:
                raise IntegrityError(
                    "intake_preview_mismatch",
                    "The current intake preview does not match the reviewed digest.",
                )
            if preview.snapshot_sha256 != expected_snapshot_sha256:
                raise IntegrityError(
                    "intake_confirmation_mismatch",
                    "The intake confirmation does not match the immutable snapshot.",
                )
            if candidate_rank > len(preview.candidates):
                raise IntegrityError(
                    "intake_confirmation_invalid",
                    "The intake candidate confirmation is invalid.",
                )
            candidate = preview.candidates[candidate_rank - 1]

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
                    snapshot_id,
                    preview.snapshot_sha256,
                    candidate.start_byte,
                    candidate.end_byte,
                    quote,
                    stance.value,
                    supersedes_evidence_id,
                ),
            ).fetchone()
            if duplicate is not None:
                raise ConflictError(
                    "intake_evidence_already_exists",
                    "This exact quote occurrence and evidence evaluation already exist.",
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
                snapshot_id=snapshot_id,
                start_byte=candidate.start_byte,
                end_byte=candidate.end_byte,
                quote=quote,
                stance=stance,
                identity=identity,
                supersedes_evidence_id=supersedes_evidence_id,
            )
            creation_audit_event_id = _verify_creation_audit(
                connection,
                evidence_id=evidence.id,
                mission_id=mission_id,
                claim_id=claim_id,
                snapshot_id=snapshot_id,
                snapshot_sha256=preview.snapshot_sha256,
                candidate=candidate,
                stance=stance,
                supersedes_evidence_id=supersedes_evidence_id,
                identity=identity,
            )

        return EvidenceIntakeResult(
            schema_version=INTAKE_RESULT_SCHEMA_VERSION,
            kind="single_exact_quote_evidence_intake",
            status="filed",
            mission_id=mission_id,
            claim_id=claim_id,
            snapshot_id=snapshot_id,
            snapshot_sha256=preview.snapshot_sha256,
            intake_preview_sha256=preview.intake_preview_sha256,
            candidate_rank=candidate_rank,
            stance=stance,
            supersedes_evidence_id=supersedes_evidence_id,
            evidence=evidence,
            creation_audit_event_id=creation_audit_event_id,
            semantic_notice=INTAKE_NOTICE,
            semantic_boundary=EvidenceIntakeSemanticBoundary(),
        )

    def _preview_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        claim_id: str,
        snapshot_id: str,
        quote: str,
        quote_bytes: bytes,
    ) -> EvidenceIntakePreview:
        claim = connection.execute(
            "SELECT 1 FROM claims WHERE id = ? AND mission_id = ?",
            (claim_id, mission_id),
        ).fetchone()
        if claim is None:
            raise NotFoundError("claim_not_found")
        snapshot_scope = connection.execute(
            "SELECT 1 FROM source_snapshots WHERE id = ? AND mission_id = ?",
            (snapshot_id, mission_id),
        ).fetchone()
        if snapshot_scope is None:
            raise NotFoundError("snapshot_not_found")

        snapshot = self._sources.read_snapshot(snapshot_id, connection=connection)
        mission_sequence = self._research.get_mission_audit_sequence(
            mission_id,
            connection=connection,
        )
        candidates = _locate_candidates(snapshot.content, quote_bytes)
        if not candidates:
            raise NotFoundError(
                "intake_quote_not_found",
                "The exact quote was not found in the immutable snapshot.",
            )
        boundary = EvidenceIntakeSemanticBoundary()
        preview = EvidenceIntakePreview(
            schema_version=INTAKE_PREVIEW_SCHEMA_VERSION,
            kind="exact_quote_candidates",
            algorithm=INTAKE_ALGORITHM,
            algorithm_version=INTAKE_ALGORITHM_VERSION,
            mission_id=mission_id,
            claim_id=claim_id,
            source_id=snapshot.metadata.source_id,
            snapshot_id=snapshot_id,
            snapshot_sha256=snapshot.metadata.sha256,
            snapshot_byte_length=snapshot.metadata.byte_length,
            quote=quote,
            quote_sha256=sha256(quote_bytes).hexdigest(),
            mission_audit_sequence=mission_sequence,
            candidate_count=len(candidates),
            candidates=candidates,
            intake_preview_sha256="",
            semantic_notice=INTAKE_NOTICE,
            semantic_boundary=boundary,
        )
        return replace(preview, intake_preview_sha256=_preview_digest(preview))


def _validated_quote_bytes(quote: object) -> bytes:
    if not isinstance(quote, str):
        raise IntegrityError(
            "evidence_quote_invalid",
            "Evidence quote is not valid UTF-8.",
        )
    try:
        quote_bytes = quote.encode("utf-8", errors="strict")
    except (AttributeError, UnicodeEncodeError) as error:
        raise IntegrityError(
            "evidence_quote_invalid",
            "Evidence quote is not valid UTF-8.",
        ) from error
    if not quote_bytes:
        raise IntegrityError(
            "evidence_quote_invalid",
            "Evidence quote is empty or too large.",
        )
    _validate_evidence_input(
        start_byte=0,
        end_byte=len(quote_bytes),
        quote=quote,
        stance=EvidenceStance.CONTEXT,
    )
    return quote_bytes


def _validate_confirmation(
    *,
    mission_id: object,
    claim_id: object,
    snapshot_id: object,
    quote: object,
    candidate_rank: object,
    expected_intake_preview_sha256: object,
    expected_snapshot_sha256: object,
    expected_mission_audit_sequence: object,
    stance: object,
    supersedes_evidence_id: object,
) -> bytes:
    if (
        not isinstance(mission_id, str)
        or _MISSION_ID.fullmatch(mission_id) is None
        or not isinstance(claim_id, str)
        or _CLAIM_ID.fullmatch(claim_id) is None
        or not isinstance(snapshot_id, str)
        or _SNAPSHOT_ID.fullmatch(snapshot_id) is None
        or (
            supersedes_evidence_id is not None
            and (
                not isinstance(supersedes_evidence_id, str)
                or _EVIDENCE_ID.fullmatch(supersedes_evidence_id) is None
            )
        )
    ):
        raise IntegrityError(
            "intake_scope_invalid",
            "The evidence intake scope is invalid.",
        )
    if (
        isinstance(candidate_rank, bool)
        or not isinstance(candidate_rank, int)
        or candidate_rank < 1
        or isinstance(expected_mission_audit_sequence, bool)
        or not isinstance(expected_mission_audit_sequence, int)
        or expected_mission_audit_sequence < 1
    ):
        code = (
            "mission_version_invalid"
            if not isinstance(expected_mission_audit_sequence, int)
            or isinstance(expected_mission_audit_sequence, bool)
            or expected_mission_audit_sequence < 1
            else "intake_confirmation_invalid"
        )
        message = (
            "Mission audit sequence must be a positive integer."
            if code == "mission_version_invalid"
            else "The intake candidate confirmation is invalid."
        )
        raise IntegrityError(code, message)
    if (
        not isinstance(expected_intake_preview_sha256, str)
        or _SHA256.fullmatch(expected_intake_preview_sha256) is None
        or not isinstance(expected_snapshot_sha256, str)
        or _SHA256.fullmatch(expected_snapshot_sha256) is None
    ):
        raise IntegrityError(
            "intake_confirmation_invalid",
            "The intake candidate confirmation is invalid.",
        )
    if not isinstance(stance, EvidenceStance):
        raise IntegrityError("evidence_stance_invalid", "Evidence stance is invalid.")
    return _validated_quote_bytes(quote)


def _locate_candidates(content: bytes, quote: bytes) -> tuple[EvidenceIntakeCandidate, ...]:
    candidates: list[EvidenceIntakeCandidate] = []
    position = 0
    quote_digest = sha256(quote).hexdigest()
    while position <= len(content) - len(quote):
        start = content.find(quote, position)
        if start < 0:
            break
        if len(candidates) >= INTAKE_MAX_CANDIDATES:
            raise ConflictError(
                "intake_candidate_limit",
                "The exact quote has too many occurrences; use a more specific quote.",
            )
        end = start + len(quote)
        context_start, context_end, context = _context(content, start=start, end=end)
        candidates.append(
            EvidenceIntakeCandidate(
                rank=len(candidates) + 1,
                start_byte=start,
                end_byte=end,
                quote_sha256=quote_digest,
                context_start_byte=context_start,
                context_end_byte=context_end,
                context=context,
            )
        )
        position = start + 1
    return tuple(candidates)


def _context(content: bytes, *, start: int, end: int) -> tuple[int, int, str]:
    context_start = max(0, start - INTAKE_CONTEXT_BYTES)
    while context_start < start and content[context_start] & 0xC0 == 0x80:
        context_start += 1
    context_end = min(len(content), end + INTAKE_CONTEXT_BYTES)
    while context_end > end:
        try:
            context = content[context_start:context_end].decode("utf-8", errors="strict")
            return context_start, context_end, context
        except UnicodeDecodeError:
            context_end -= 1
    return (
        context_start,
        end,
        content[context_start:end].decode("utf-8", errors="strict"),
    )


def _preview_digest(preview: EvidenceIntakePreview) -> str:
    payload = asdict(preview)
    payload.pop("intake_preview_sha256")
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")
    return sha256(canonical).hexdigest()


def _verify_creation_audit(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    mission_id: str,
    claim_id: str,
    snapshot_id: str,
    snapshot_sha256: str,
    candidate: EvidenceIntakeCandidate,
    stance: EvidenceStance,
    supersedes_evidence_id: str | None,
    identity: IdentityContext,
) -> str:
    rows = list(
        connection.execute(
            """
            SELECT id, entity_type, entity_id, mission_id, actor_id, run_id, details_json
            FROM audit_events
            WHERE event_type = 'evidence.card.created' AND entity_id = ?
            ORDER BY sequence
            LIMIT 2
            """,
            (evidence_id,),
        )
    )
    expected_details = json.dumps(
        {
            "claim_id": claim_id,
            "end_byte": candidate.end_byte,
            "snapshot_id": snapshot_id,
            "snapshot_sha256": snapshot_sha256,
            "stance": stance.value,
            "start_byte": candidate.start_byte,
            "supersedes": supersedes_evidence_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(rows) != 1:
        _audit_invalid()
    row = rows[0]
    audit_id = str(row["id"])
    if (
        _AUDIT_ID.fullmatch(audit_id) is None
        or str(row["entity_type"]) != "evidence_card"
        or str(row["entity_id"]) != evidence_id
        or str(row["mission_id"]) != mission_id
        or str(row["actor_id"]) != identity.actor_id
        or str(row["run_id"]) != identity.run_id
        or str(row["details_json"]) != expected_details
    ):
        _audit_invalid()
    return audit_id


def _audit_invalid() -> None:
    raise IntegrityError(
        "intake_audit_invalid",
        "Evidence intake audit provenance is incomplete or inconsistent.",
    )
