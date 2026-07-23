"""Audited database lifecycle operations."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now


class OperationsService:
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

    def initialize(
        self,
        *,
        identity: IdentityContext,
        refuse_existing: bool,
    ) -> int:
        def record_initialization(connection: sqlite3.Connection, version: int) -> None:
            self._audit.ensure_run(connection, identity)
            self._audit.record(
                connection,
                identity=identity,
                event_type="database.initialized",
                entity_type="database",
                entity_id="local",
                mission_id=None,
                details={"schema_version": version},
            )

        return self.database.initialize(
            refuse_existing=refuse_existing,
            on_ready=record_initialization,
        )

    def backup(self, *, target: Path, identity: IdentityContext) -> None:
        self.database.backup_to(target)
        metadata = os.stat(target, follow_symlinks=False)
        try:
            with self.database.transaction() as connection:
                self._audit.ensure_run(connection, identity)
                self._audit.record(
                    connection,
                    identity=identity,
                    event_type="database.backup.created",
                    entity_type="database_backup",
                    entity_id="local-backup",
                    mission_id=None,
                    details={},
                )
        except BaseException:
            _unlink_if_same(target, metadata.st_dev, metadata.st_ino)
            raise

    @classmethod
    def restore(
        cls,
        *,
        backup: Path,
        target: Path,
        identity: IdentityContext,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> Database:
        service = cls(Database(target), audit=audit, clock=clock, id_factory=id_factory)

        def record_restore(connection: sqlite3.Connection, version: int) -> None:
            service._audit.ensure_run(connection, identity)
            service._audit.record(
                connection,
                identity=identity,
                event_type="database.restored",
                entity_type="database",
                entity_id="local",
                mission_id=None,
                details={"schema_version": version},
            )

        return Database.restore_from(backup, target, on_ready=record_restore)


def _unlink_if_same(path: Path, device: int, inode: int) -> bool:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    if (current.st_dev, current.st_ino) != (device, inode):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
