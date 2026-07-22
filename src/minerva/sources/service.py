"""Immutable local UTF-8 source registration commands."""

from __future__ import annotations

import re
import sqlite3
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qsl, urlsplit

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now
from minerva.sources.files import (
    SourceFileError,
    read_local_utf8,
    scan_secret_patterns,
)
from minerva.sources.integrity import verify_snapshot_integrity
from minerva.sources.models import SnapshotContent, SourceSnapshot

DEFAULT_MAX_SOURCE_BYTES = 1_048_576
HARD_MAX_SOURCE_BYTES = 10_485_760
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,49}/[a-z0-9][a-z0-9!#$&^_.+-]{0,48}\Z")
_SENSITIVE_QUERY_PARAMETER_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "client_secret",
        "credential",
        "credentials",
        "key",
        "password",
        "passwd",
        "refresh_token",
        "secret",
        "security_token",
        "sig",
        "signature",
        "token",
        "x_amz_credential",
        "x_amz_security_token",
        "x_amz_signature",
        "x_goog_signature",
    }
)


class SourceService:
    def __init__(
        self,
        database: Database,
        *,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> None:
        if (
            isinstance(max_source_bytes, bool)
            or not isinstance(max_source_bytes, int)
            or not 1 <= max_source_bytes <= HARD_MAX_SOURCE_BYTES
        ):
            raise ValueError("max_source_bytes is outside the supported range")
        self.database = database
        self.max_source_bytes = max_source_bytes
        self._clock = clock
        self._id_factory = id_factory
        self._audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)

    def import_file(
        self,
        *,
        mission_id: str,
        root: Path,
        relative_path: str,
        media_type: str,
        identity: IdentityContext,
        url_metadata: str | None = None,
    ) -> SourceSnapshot:
        try:
            local_file = read_local_utf8(root, relative_path, self.max_source_bytes)
        except SourceFileError as error:
            raise _present_file_error(error) from error
        return self.import_bytes(
            mission_id=mission_id,
            content=local_file.content,
            original_label=local_file.original_label,
            media_type=media_type,
            identity=identity,
            url_metadata=url_metadata,
        )

    def import_bytes(
        self,
        *,
        mission_id: str,
        content: bytes,
        original_label: str,
        media_type: str,
        identity: IdentityContext,
        url_metadata: str | None = None,
    ) -> SourceSnapshot:
        if not content:
            raise IntegrityError("source_empty", "Source snapshots may not be empty.")
        if len(content) > self.max_source_bytes:
            raise IntegrityError("source_too_large", "The source exceeds the import limit.")
        if b"\x00" in content:
            raise IntegrityError("source_nul_byte", "The source contains a NUL byte.")
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise IntegrityError("source_invalid_utf8", "The source is not valid UTF-8.") from error
        secret_category = scan_secret_patterns(content)
        if secret_category is not None:
            raise IntegrityError(
                "source_secret_detected",
                f"The source matches a blocked {secret_category.value.replace('_', ' ')} pattern.",
            )

        safe_label = _validate_original_label(original_label)
        safe_media_type = media_type.strip().lower()
        if not _MEDIA_TYPE.fullmatch(safe_media_type):
            raise IntegrityError("source_media_type_invalid", "The source media type is invalid.")
        safe_url = _validate_url_metadata(url_metadata)
        digest = sha256(content).hexdigest()
        source_id = self._id_factory("src")
        snapshot_id = self._id_factory("snp")
        imported_at = self._clock()

        with self.database.transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM research_missions WHERE id = ?", (mission_id,)
                ).fetchone()
                is None
            ):
                raise NotFoundError("mission_not_found")
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO sources(
                    id, mission_id, source_kind, original_label, url_metadata,
                    creator_id, run_id, created_at
                ) VALUES (?, ?, 'local_utf8', ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    mission_id,
                    safe_label,
                    safe_url,
                    identity.actor_id,
                    identity.run_id,
                    imported_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO source_snapshots(
                    id, source_id, mission_id, content, sha256, byte_length, encoding,
                    media_type, original_label, imported_at, creator_id, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'utf-8', ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    source_id,
                    mission_id,
                    content,
                    digest,
                    len(content),
                    safe_media_type,
                    safe_label,
                    imported_at,
                    identity.actor_id,
                    identity.run_id,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="source.snapshot.imported",
                entity_type="source_snapshot",
                entity_id=snapshot_id,
                mission_id=mission_id,
                details={
                    "source_id": source_id,
                    "sha256": digest,
                    "byte_length": len(content),
                    "encoding": "utf-8",
                    "media_type": safe_media_type,
                },
            )
            verify_snapshot_integrity(connection, _snapshot_row(connection, snapshot_id))

        return SourceSnapshot(
            source_id=source_id,
            snapshot_id=snapshot_id,
            mission_id=mission_id,
            sha256=digest,
            byte_length=len(content),
            encoding="utf-8",
            media_type=safe_media_type,
            original_label=safe_label,
            url_metadata=safe_url,
            imported_at=imported_at,
            creator_id=identity.actor_id,
            run_id=identity.run_id,
        )

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> SourceSnapshot:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.get_snapshot(snapshot_id, connection=owned_connection)
        row = _snapshot_row(connection, snapshot_id)
        verify_snapshot_integrity(connection, row)
        return _snapshot_from_row(row)

    def read_snapshot(
        self,
        snapshot_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> SnapshotContent:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.read_snapshot(snapshot_id, connection=owned_connection)
        row = _snapshot_row(connection, snapshot_id)
        content = verify_snapshot_integrity(connection, row)
        return SnapshotContent(metadata=_snapshot_from_row(row), content=content)

    def list_snapshots(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[SourceSnapshot, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_snapshots(mission_id, connection=owned_connection)
        _require_mission(connection, mission_id)
        rows = connection.execute(
            """
            SELECT ss.*, s.url_metadata
            FROM source_snapshots AS ss
            JOIN sources AS s ON s.id = ss.source_id
            WHERE ss.mission_id = ?
            ORDER BY ss.imported_at ASC, ss.id ASC
            """,
            (mission_id,),
        )
        snapshots: list[SourceSnapshot] = []
        for row in rows:
            verify_snapshot_integrity(connection, row)
            snapshots.append(_snapshot_from_row(row))
        return tuple(snapshots)

    def page_snapshots(
        self,
        mission_id: str,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[tuple[SourceSnapshot, ...], tuple[str, str] | None]:
        _validate_page_request(limit, after)
        if connection is None:
            with self.database.read() as owned_connection:
                return self.page_snapshots(
                    mission_id,
                    limit=limit,
                    after=after,
                    connection=owned_connection,
                )
        _require_mission(connection, mission_id)
        if after is None:
            rows = list(
                connection.execute(
                    """
                    SELECT ss.*, s.url_metadata
                    FROM source_snapshots AS ss
                    JOIN sources AS s ON s.id = ss.source_id
                    WHERE ss.mission_id = ?
                    ORDER BY ss.imported_at ASC, ss.id ASC LIMIT ?
                    """,
                    (mission_id, limit + 1),
                )
            )
        else:
            imported_at, snapshot_id = after
            rows = list(
                connection.execute(
                    """
                    SELECT ss.*, s.url_metadata
                    FROM source_snapshots AS ss
                    JOIN sources AS s ON s.id = ss.source_id
                    WHERE ss.mission_id = ?
                      AND (ss.imported_at > ? OR (ss.imported_at = ? AND ss.id > ?))
                    ORDER BY ss.imported_at ASC, ss.id ASC LIMIT ?
                    """,
                    (mission_id, imported_at, imported_at, snapshot_id, limit + 1),
                )
            )
        page_rows = rows[:limit]
        snapshots: list[SourceSnapshot] = []
        for row in page_rows:
            verify_snapshot_integrity(connection, row)
            snapshots.append(_snapshot_from_row(row))
        next_position = None
        if len(rows) > limit:
            last = page_rows[-1]
            next_position = (str(last["imported_at"]), str(last["id"]))
        return tuple(snapshots), next_position


def _require_mission(connection: sqlite3.Connection, mission_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM research_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        is None
    ):
        raise NotFoundError("mission_not_found")


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
    imported_at, snapshot_id = after
    if (
        not isinstance(imported_at, str)
        or not isinstance(snapshot_id, str)
        or not imported_at
        or not snapshot_id
        or len(imported_at) > 64
        or len(snapshot_id) > 100
        or "\x00" in imported_at
        or "\x00" in snapshot_id
    ):
        raise IntegrityError("pagination_invalid", "The pagination cursor is invalid.")


def _snapshot_row(connection: sqlite3.Connection, snapshot_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT ss.*, s.url_metadata
        FROM source_snapshots AS ss
        JOIN sources AS s ON s.id = ss.source_id
        WHERE ss.id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("snapshot_not_found")
    if not isinstance(row, sqlite3.Row):
        raise IntegrityError("database_row_invalid", "Stored source state is invalid.")
    return row


def _snapshot_from_row(row: sqlite3.Row) -> SourceSnapshot:
    return SourceSnapshot(
        source_id=str(row["source_id"]),
        snapshot_id=str(row["id"]),
        mission_id=str(row["mission_id"]),
        sha256=str(row["sha256"]),
        byte_length=int(row["byte_length"]),
        encoding=str(row["encoding"]),
        media_type=str(row["media_type"]),
        original_label=str(row["original_label"]),
        url_metadata=str(row["url_metadata"]) if row["url_metadata"] is not None else None,
        imported_at=str(row["imported_at"]),
        creator_id=str(row["creator_id"]),
        run_id=str(row["run_id"]),
    )


def _validate_original_label(label: str) -> str:
    candidate = label.strip()
    if (
        not candidate
        or len(candidate) > 500
        or "\x00" in candidate
        or "\\" in candidate
        or candidate.startswith("/")
    ):
        raise IntegrityError("source_label_invalid", "The source label is invalid.")
    path = PurePosixPath(candidate)
    windows_path = PureWindowsPath(candidate)
    if windows_path.is_absolute() or windows_path.drive:
        raise IntegrityError("source_label_invalid", "The source label is invalid.")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise IntegrityError("source_label_invalid", "The source label is invalid.")
    if scan_secret_patterns(candidate) is not None:
        raise IntegrityError(
            "source_secret_detected", "Source metadata matches a blocked secret pattern."
        )
    return candidate


def _validate_url_metadata(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 2_000 or "\x00" in candidate:
        raise IntegrityError("source_url_invalid", "URL metadata is invalid.")
    if scan_secret_patterns(candidate) is not None:
        raise IntegrityError(
            "source_secret_detected", "Source metadata matches a blocked secret pattern."
        )
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
        query_parameters = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=50)
    except ValueError as error:
        raise IntegrityError("source_url_invalid", "URL metadata is invalid.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise IntegrityError("source_url_invalid", "URL metadata is invalid.")
    for name, query_value in query_parameters:
        normalized_name = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if (
            normalized_name in _SENSITIVE_QUERY_PARAMETER_NAMES
            or scan_secret_patterns(name) is not None
            or scan_secret_patterns(query_value) is not None
        ):
            raise IntegrityError(
                "source_secret_detected",
                "Source metadata matches a blocked secret pattern.",
            )
    return candidate


def _present_file_error(error: SourceFileError) -> IntegrityError:
    category = error.category
    if category is not None:
        return IntegrityError(
            "source_secret_detected",
            f"The source matches a blocked {category.value.replace('_', ' ')} pattern.",
        )
    mapping = {
        "invalid_utf8": ("source_invalid_utf8", "The source is not valid UTF-8."),
        "nul_byte": ("source_nul_byte", "The source contains a NUL byte."),
        "source_too_large": ("source_too_large", "The source exceeds the import limit."),
        "not_found": ("source_not_found", "The source file was not found."),
        "symlink_not_allowed": (
            "source_symlink_rejected",
            "Symbolic links are not accepted for source import.",
        ),
        "invalid_root": ("source_root_invalid", "The import root is invalid."),
        "invalid_path": ("source_path_invalid", "The source path is invalid."),
        "not_regular_file": ("source_not_regular", "Only regular files may be imported."),
        "source_changed": ("source_changed", "The source changed during import."),
    }
    code, message = mapping.get(
        error.code,
        ("source_read_failed", "The source could not be imported safely."),
    )
    return IntegrityError(code, message)
