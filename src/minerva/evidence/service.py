"""Shared evidence commands and deterministic claim ledgers."""

from __future__ import annotations

import sqlite3

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now, validate_text
from minerva.evidence.integrity import verify_evidence_reference
from minerva.evidence.models import EvidenceCard, EvidenceStance, LedgerEntry
from minerva.sources.integrity import verify_snapshot_integrity


class EvidenceService:
    def __init__(
        self,
        database: Database,
        *,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> None:
        self.database = database
        self._clock = clock
        self._id_factory = id_factory
        self._audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)

    def add_evidence(
        self,
        *,
        mission_id: str,
        claim_id: str,
        snapshot_id: str,
        start_byte: int,
        end_byte: int,
        quote: str,
        stance: EvidenceStance,
        identity: IdentityContext,
        supersedes_evidence_id: str | None = None,
    ) -> EvidenceCard:
        if isinstance(start_byte, bool) or isinstance(end_byte, bool):
            raise IntegrityError("citation_offsets_invalid", "Citation offsets must be integers.")
        if start_byte < 0 or end_byte <= start_byte:
            raise IntegrityError("citation_offsets_invalid", "Citation offsets are invalid.")
        if not isinstance(stance, EvidenceStance):
            raise IntegrityError("evidence_stance_invalid", "Evidence stance is invalid.")
        if not quote or "\x00" in quote or len(quote.encode("utf-8")) > 100_000:
            raise IntegrityError("evidence_quote_invalid", "Evidence quote is empty or too large.")

        evidence_id = self._id_factory("evd")
        created_at = self._clock()
        with self.database.transaction() as connection:
            claim = connection.execute(
                "SELECT 1 FROM claims WHERE id = ? AND mission_id = ?",
                (claim_id, mission_id),
            ).fetchone()
            if claim is None:
                raise NotFoundError("claim_not_found")

            snapshot = connection.execute(
                """
                SELECT id, source_id, mission_id, content, sha256, byte_length,
                       encoding, media_type, creator_id, run_id
                FROM source_snapshots WHERE id = ? AND mission_id = ?
                """,
                (snapshot_id, mission_id),
            ).fetchone()
            if snapshot is None:
                raise NotFoundError("snapshot_not_found")
            content = verify_snapshot_integrity(connection, snapshot)
            snapshot_digest = str(snapshot["sha256"])
            if end_byte > len(content):
                raise IntegrityError(
                    "citation_offsets_invalid", "Citation offsets are out of range."
                )
            try:
                resolved_quote = content[start_byte:end_byte].decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise IntegrityError(
                    "citation_offsets_invalid", "Citation offsets split a UTF-8 character."
                ) from error
            if quote != resolved_quote or quote.encode("utf-8") != content[start_byte:end_byte]:
                raise IntegrityError(
                    "citation_quote_mismatch", "The quote does not match the source snapshot."
                )

            if supersedes_evidence_id is not None:
                superseded = connection.execute(
                    """
                    SELECT claim_id FROM evidence_cards
                    WHERE id = ? AND mission_id = ?
                    """,
                    (supersedes_evidence_id, mission_id),
                ).fetchone()
                if superseded is None or str(superseded["claim_id"]) != claim_id:
                    raise IntegrityError(
                        "evidence_supersession_invalid",
                        "Superseded evidence must evaluate the same claim.",
                    )

            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO evidence_cards(
                    id, mission_id, claim_id, snapshot_id, snapshot_sha256, start_byte, end_byte,
                    quote, stance, supersedes_evidence_id, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    mission_id,
                    claim_id,
                    snapshot_id,
                    snapshot_digest,
                    start_byte,
                    end_byte,
                    quote,
                    stance.value,
                    supersedes_evidence_id,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="evidence.card.created",
                entity_type="evidence_card",
                entity_id=evidence_id,
                mission_id=mission_id,
                details={
                    "claim_id": claim_id,
                    "snapshot_id": snapshot_id,
                    "snapshot_sha256": snapshot_digest,
                    "start_byte": start_byte,
                    "end_byte": end_byte,
                    "stance": stance.value,
                    "supersedes": supersedes_evidence_id,
                },
            )
        return EvidenceCard(
            evidence_id,
            mission_id,
            claim_id,
            snapshot_id,
            snapshot_digest,
            start_byte,
            end_byte,
            quote,
            stance,
            supersedes_evidence_id,
            identity.actor_id,
            identity.run_id,
            created_at,
        )

    def withdraw_evidence(
        self,
        *,
        evidence_id: str,
        reason: str,
        identity: IdentityContext,
    ) -> str:
        reason = validate_text(reason, field="reason", maximum=1_000)
        withdrawal_id = self._id_factory("wdr")
        created_at = self._clock()
        with self.database.transaction() as connection:
            evidence = connection.execute(
                "SELECT mission_id FROM evidence_cards WHERE id = ?",
                (evidence_id,),
            ).fetchone()
            if evidence is None:
                raise NotFoundError("evidence_not_found")
            if connection.execute(
                "SELECT 1 FROM evidence_withdrawals WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone():
                raise ConflictError("evidence_already_withdrawn", "Evidence is already withdrawn.")
            mission_id = str(evidence["mission_id"])
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO evidence_withdrawals(
                    id, mission_id, evidence_id, reason, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    withdrawal_id,
                    mission_id,
                    evidence_id,
                    reason,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="evidence.card.withdrawn",
                entity_type="evidence_card",
                entity_id=evidence_id,
                mission_id=mission_id,
                details={"withdrawal_id": withdrawal_id},
            )
        return withdrawal_id

    def ledger_for_claim(
        self,
        claim_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[LedgerEntry, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.ledger_for_claim(claim_id, connection=owned_connection)
        mission_id = _claim_mission(connection, claim_id)
        rows = list(
            connection.execute(
                _LEDGER_SELECT + " ORDER BY e.created_at ASC, e.id ASC",
                (claim_id,),
            )
        )
        return _ledger_entries_from_rows(connection, mission_id=mission_id, rows=rows)

    def page_ledger_for_claim(
        self,
        claim_id: str,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[tuple[LedgerEntry, ...], tuple[str, str] | None]:
        _validate_page_request(limit, after)
        if connection is None:
            with self.database.read() as owned_connection:
                return self.page_ledger_for_claim(
                    claim_id,
                    limit=limit,
                    after=after,
                    connection=owned_connection,
                )
        mission_id = _claim_mission(connection, claim_id)
        if after is None:
            rows = list(
                connection.execute(
                    _LEDGER_SELECT + " ORDER BY e.created_at ASC, e.id ASC LIMIT ?",
                    (claim_id, limit + 1),
                )
            )
        else:
            created_at, evidence_id = after
            rows = list(
                connection.execute(
                    _LEDGER_SELECT
                    + " AND (e.created_at > ? OR (e.created_at = ? AND e.id > ?))"
                    + " ORDER BY e.created_at ASC, e.id ASC LIMIT ?",
                    (claim_id, created_at, created_at, evidence_id, limit + 1),
                )
            )
        page_rows = rows[:limit]
        entries = _ledger_entries_from_rows(
            connection,
            mission_id=mission_id,
            rows=page_rows,
        )
        next_position = None
        if len(rows) > limit:
            last = page_rows[-1]
            next_position = (str(last["created_at"]), str(last["id"]))
        return entries, next_position


_LEDGER_SELECT = """
SELECT e.id, e.mission_id, e.claim_id, e.snapshot_id,
       e.snapshot_sha256, e.start_byte, e.end_byte, e.quote, e.stance,
       e.supersedes_evidence_id, e.creator_id, e.run_id, e.created_at,
       w.reason AS withdrawal_reason, w.created_at AS withdrawn_at,
       w.creator_id AS withdrawn_by
FROM evidence_cards AS e
LEFT JOIN evidence_withdrawals AS w ON w.evidence_id = e.id
WHERE e.claim_id = ?
""".strip()


def _claim_mission(connection: sqlite3.Connection, claim_id: str) -> str:
    claim = connection.execute(
        "SELECT mission_id FROM claims WHERE id = ?",
        (claim_id,),
    ).fetchone()
    if claim is None:
        raise NotFoundError("claim_not_found")
    return str(claim["mission_id"])


def _validate_page_request(limit: int, after: tuple[str, str] | None) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise IntegrityError(
            "pagination_invalid",
            "Collection page size must be between 1 and 200.",
        )
    if after is None:
        return
    if not isinstance(after, tuple) or len(after) != 2:
        raise IntegrityError("pagination_invalid", "The pagination cursor is invalid.")
    created_at, evidence_id = after
    if (
        not isinstance(created_at, str)
        or not isinstance(evidence_id, str)
        or not created_at
        or not evidence_id
        or len(created_at) > 64
        or len(evidence_id) > 100
        or "\x00" in created_at
        or "\x00" in evidence_id
    ):
        raise IntegrityError("pagination_invalid", "The pagination cursor is invalid.")


def _ledger_entries_from_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    rows: list[sqlite3.Row],
) -> tuple[LedgerEntry, ...]:
    ledger: list[LedgerEntry] = []
    for row in rows:
        verified = verify_evidence_reference(
            connection,
            evidence_id=str(row["id"]),
            mission_id=mission_id,
            allow_withdrawn=True,
        )
        card = EvidenceCard(
            id=str(row["id"]),
            mission_id=str(row["mission_id"]),
            claim_id=str(row["claim_id"]),
            snapshot_id=str(row["snapshot_id"]),
            snapshot_sha256=str(row["snapshot_sha256"]),
            start_byte=int(row["start_byte"]),
            end_byte=int(row["end_byte"]),
            quote=str(row["quote"]),
            stance=EvidenceStance(str(row["stance"])),
            supersedes_evidence_id=(
                str(row["supersedes_evidence_id"])
                if row["supersedes_evidence_id"] is not None
                else None
            ),
            creator_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
            created_at=str(row["created_at"]),
        )
        ledger.append(
            LedgerEntry(
                evidence=card,
                citation_id=card.id,
                snapshot_sha256=verified.snapshot_sha256,
                source_label=verified.source_label,
                withdrawn=verified.withdrawn,
                withdrawal_reason=verified.withdrawal_reason,
                withdrawn_at=verified.withdrawn_at,
                withdrawn_by=(
                    str(row["withdrawn_by"]) if row["withdrawn_by"] is not None else None
                ),
            )
        )
    return tuple(ledger)
