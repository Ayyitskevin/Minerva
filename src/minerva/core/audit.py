"""Append-only audit recording inside caller-owned transactions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Protocol

from minerva.core.errors import IntegrityError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now


class AuditSink(Protocol):
    def ensure_run(self, connection: sqlite3.Connection, identity: IdentityContext) -> None: ...

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
    ) -> str: ...


class AuditRecorder:
    def __init__(self, *, clock: Clock = utc_now, id_factory: IdFactory = new_id) -> None:
        self._clock = clock
        self._id_factory = id_factory

    def ensure_run(self, connection: sqlite3.Connection, identity: IdentityContext) -> None:
        existing = connection.execute(
            "SELECT actor_id, actor_kind, purpose FROM research_runs WHERE id = ?",
            (identity.run_id,),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["actor_id"]),
                str(existing["actor_kind"]),
                str(existing["purpose"]),
            ) != (identity.actor_id, identity.actor_kind.value, identity.purpose):
                raise IntegrityError(
                    "run_identity_mismatch", "The research run identity is inconsistent."
                )
            return

        created_at = self._clock()
        connection.execute(
            """
            INSERT INTO research_runs(id, actor_id, actor_kind, purpose, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                identity.run_id,
                identity.actor_id,
                identity.actor_kind.value,
                identity.purpose,
                created_at,
            ),
        )
        self.record(
            connection,
            identity=identity,
            event_type="research.run.started",
            entity_type="research_run",
            entity_id=identity.run_id,
            mission_id=None,
            details={"purpose": identity.purpose},
        )

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
        detail_json = json.dumps(
            dict(details or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(detail_json.encode("utf-8")) > 4_096:
            raise IntegrityError("audit_details_too_large", "Audit details exceed the size limit.")
        audit_id = self._id_factory("aud")
        connection.execute(
            """
            INSERT INTO audit_events(
                id, event_type, entity_type, entity_id, mission_id,
                actor_id, run_id, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                event_type,
                entity_type,
                entity_id,
                mission_id,
                identity.actor_id,
                identity.run_id,
                self._clock(),
                detail_json,
            ),
        )
        return audit_id


def list_audit_events(
    connection: sqlite3.Connection,
    *,
    mission_id: str | None = None,
    limit: int = 100,
    after_sequence: int = 0,
) -> list[dict[str, object]]:
    if not 1 <= limit <= 500:
        raise IntegrityError("pagination_invalid", "Audit page size must be between 1 and 500.")
    if after_sequence < 0:
        raise IntegrityError("pagination_invalid", "Audit cursor may not be negative.")
    if mission_id is None:
        rows = connection.execute(
            """
            SELECT sequence, id, event_type, entity_type, entity_id, mission_id,
                   actor_id, run_id, occurred_at, details_json
            FROM audit_events
            WHERE sequence > ?
            ORDER BY sequence ASC
            LIMIT ?
            """,
            (after_sequence, limit),
        )
    else:
        rows = connection.execute(
            """
            SELECT sequence, id, event_type, entity_type, entity_id, mission_id,
                   actor_id, run_id, occurred_at, details_json
            FROM audit_events
            WHERE sequence > ? AND (mission_id = ? OR entity_id = ?)
            ORDER BY sequence ASC
            LIMIT ?
            """,
            (after_sequence, mission_id, mission_id, limit),
        )
    return [
        {
            "sequence": int(row["sequence"]),
            "id": str(row["id"]),
            "event_type": str(row["event_type"]),
            "entity_type": str(row["entity_type"]),
            "entity_id": str(row["entity_id"]),
            "mission_id": str(row["mission_id"]) if row["mission_id"] is not None else None,
            "actor_id": str(row["actor_id"]),
            "run_id": str(row["run_id"]),
            "occurred_at": str(row["occurred_at"]),
            "details": json.loads(str(row["details_json"])),
        }
        for row in rows
    ]
