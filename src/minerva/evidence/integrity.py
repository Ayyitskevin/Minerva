"""Tamper-evident citation resolution shared by findings and synthesis."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from minerva.core.errors import IntegrityError, NotFoundError
from minerva.evidence.models import EvidenceStance
from minerva.sources.integrity import verify_snapshot_integrity


@dataclass(frozen=True, slots=True)
class VerifiedCitation:
    evidence_id: str
    mission_id: str
    claim_id: str
    snapshot_id: str
    snapshot_sha256: str
    source_label: str
    start_byte: int
    end_byte: int
    quote: str
    stance: EvidenceStance
    withdrawn: bool
    withdrawal_reason: str | None
    withdrawn_at: str | None


def verify_evidence_reference(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    mission_id: str,
    allow_withdrawn: bool,
) -> VerifiedCitation:
    return _verify_evidence_reference(
        connection,
        evidence_id=evidence_id,
        mission_id=mission_id,
        allow_withdrawn=allow_withdrawn,
        snapshot_cache={},
    )


def verify_evidence_references(
    connection: sqlite3.Connection,
    *,
    evidence_ids: Sequence[str],
    mission_id: str,
    allow_withdrawn: bool,
) -> list[VerifiedCitation]:
    snapshot_cache: dict[str, tuple[sqlite3.Row, bytes]] = {}
    return [
        _verify_evidence_reference(
            connection,
            evidence_id=evidence_id,
            mission_id=mission_id,
            allow_withdrawn=allow_withdrawn,
            snapshot_cache=snapshot_cache,
        )
        for evidence_id in evidence_ids
    ]


def _verify_evidence_reference(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    mission_id: str,
    allow_withdrawn: bool,
    snapshot_cache: dict[str, tuple[sqlite3.Row, bytes]],
) -> VerifiedCitation:
    row = connection.execute(
        """
        SELECT e.id, e.mission_id, e.claim_id, e.snapshot_id, e.start_byte, e.end_byte,
               e.snapshot_sha256, e.quote, e.stance, w.reason AS withdrawal_reason,
               w.created_at AS withdrawn_at
        FROM evidence_cards AS e
        LEFT JOIN evidence_withdrawals AS w ON w.evidence_id = e.id
        WHERE e.id = ? AND e.mission_id = ?
        """,
        (evidence_id, mission_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("evidence_not_found")

    snapshot_id = str(row["snapshot_id"])
    cached_snapshot = snapshot_cache.get(snapshot_id)
    if cached_snapshot is None:
        snapshot = connection.execute(
            """
            SELECT id, source_id, mission_id, content, sha256, byte_length,
                   encoding, media_type, original_label, creator_id, run_id
            FROM source_snapshots
            WHERE id = ? AND mission_id = ?
            """,
            (snapshot_id, mission_id),
        ).fetchone()
        if snapshot is None:
            raise IntegrityError("snapshot_tampered", "Stored source snapshot integrity failed.")
        raw_content = verify_snapshot_integrity(connection, snapshot)
        snapshot_cache[snapshot_id] = (snapshot, raw_content)
    else:
        snapshot, raw_content = cached_snapshot
    citation_digest = str(row["snapshot_sha256"])
    if citation_digest != str(snapshot["sha256"]):
        raise IntegrityError("citation_tampered", "Stored citation integrity failed.")

    start = int(row["start_byte"])
    end = int(row["end_byte"])
    if start < 0 or end <= start or end > len(raw_content):
        raise IntegrityError("citation_tampered", "Stored citation integrity failed.")
    try:
        resolved_quote = raw_content[start:end].decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise IntegrityError("citation_tampered", "Stored citation integrity failed.") from error
    quote = str(row["quote"])
    if not quote or resolved_quote != quote or quote.encode("utf-8") != raw_content[start:end]:
        raise IntegrityError("citation_tampered", "Stored citation integrity failed.")

    withdrawal_reason = (
        str(row["withdrawal_reason"]) if row["withdrawal_reason"] is not None else None
    )
    withdrawn_at = str(row["withdrawn_at"]) if row["withdrawn_at"] is not None else None
    withdrawn = withdrawn_at is not None
    if withdrawn and not allow_withdrawn:
        raise IntegrityError("citation_withdrawn", "Withdrawn evidence cannot support a finding.")

    try:
        stance = EvidenceStance(str(row["stance"]))
    except ValueError as error:
        raise IntegrityError("citation_tampered", "Stored citation integrity failed.") from error

    return VerifiedCitation(
        evidence_id=str(row["id"]),
        mission_id=str(row["mission_id"]),
        claim_id=str(row["claim_id"]),
        snapshot_id=snapshot_id,
        snapshot_sha256=citation_digest,
        source_label=str(snapshot["original_label"]),
        start_byte=start,
        end_byte=end,
        quote=quote,
        stance=stance,
        withdrawn=withdrawn,
        withdrawal_reason=withdrawal_reason,
        withdrawn_at=withdrawn_at,
    )
