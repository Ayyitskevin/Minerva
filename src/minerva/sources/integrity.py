"""Shared snapshot and import-audit integrity verification."""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from typing import Never

from minerva.core.errors import IntegrityError

_IMPORT_EVENT_TYPE = "source.snapshot.imported"
_IMPORT_ENTITY_TYPE = "source_snapshot"
_IMPORT_DETAIL_KEYS = frozenset({"source_id", "sha256", "byte_length", "encoding", "media_type"})


def verify_snapshot_integrity(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> bytes:
    """Verify exact snapshot bytes and their independently stored import event."""

    content = row["content"]
    if not isinstance(content, bytes):
        _raise_snapshot_tampered()

    digest = sha256(content).hexdigest()
    try:
        byte_length = int(row["byte_length"])
    except (TypeError, ValueError):
        _raise_snapshot_tampered()
    if len(content) != byte_length or digest != str(row["sha256"]):
        _raise_snapshot_tampered()

    try:
        decoded = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _raise_snapshot_tampered()
    if "\x00" in decoded or str(row["encoding"]) != "utf-8":
        _raise_snapshot_tampered()

    audit_rows = list(
        connection.execute(
            """
            SELECT entity_type, mission_id, actor_id, run_id, details_json
            FROM audit_events
            WHERE event_type = ? AND entity_id = ?
            ORDER BY sequence
            """,
            (_IMPORT_EVENT_TYPE, str(row["id"])),
        )
    )
    if len(audit_rows) != 1:
        _raise_snapshot_tampered()
    audit_row = audit_rows[0]
    if (
        str(audit_row["entity_type"]) != _IMPORT_ENTITY_TYPE
        or audit_row["mission_id"] is None
        or str(audit_row["mission_id"]) != str(row["mission_id"])
        or str(audit_row["actor_id"]) != str(row["creator_id"])
        or str(audit_row["run_id"]) != str(row["run_id"])
    ):
        _raise_snapshot_tampered()

    details = _strict_json_object(str(audit_row["details_json"]))
    if set(details) != _IMPORT_DETAIL_KEYS:
        _raise_snapshot_tampered()
    if (
        not isinstance(details["source_id"], str)
        or details["source_id"] != str(row["source_id"])
        or not isinstance(details["sha256"], str)
        or details["sha256"] != digest
        or type(details["byte_length"]) is not int
        or details["byte_length"] != byte_length
        or not isinstance(details["encoding"], str)
        or details["encoding"] != str(row["encoding"])
        or not isinstance(details["media_type"], str)
        or details["media_type"] != str(row["media_type"])
    ):
        _raise_snapshot_tampered()
    return content


def _strict_json_object(raw: str) -> dict[str, object]:
    try:
        raw.encode("utf-8", errors="strict")
        parsed: object = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeEncodeError, ValueError, json.JSONDecodeError):
        _raise_snapshot_tampered()
    if not isinstance(parsed, dict):
        _raise_snapshot_tampered()
    if raw != json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")):
        _raise_snapshot_tampered()
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> Never:
    raise ValueError("non-standard JSON constant")


def _raise_snapshot_tampered() -> Never:
    raise IntegrityError("snapshot_tampered", "Stored source snapshot integrity failed.")
