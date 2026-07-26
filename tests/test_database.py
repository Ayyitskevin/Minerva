from __future__ import annotations

import os
import sqlite3
import stat
import threading
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

import pytest

import minerva.core.db as db_module
from conftest import SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder, list_audit_events
from minerva.core.db import Database, Migration, latest_schema_version
from minerva.core.errors import ConflictError, IntegrityError, MinervaError, NotFoundError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.research.service import ResearchService


class FailingAuditSink:
    def __init__(self, ids: SequenceIds) -> None:
        self.delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

    def ensure_run(
        self,
        connection: sqlite3.Connection,
        identity: IdentityContext,
    ) -> None:
        self.delegate.ensure_run(connection, identity)

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
        raise RuntimeError("synthetic audit failure")


def test_fresh_and_repeated_initialization_are_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "research.db")

    first = database.initialize()
    second = database.initialize()

    assert first == latest_schema_version()
    assert second == first
    assert database.schema_version() == first
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == first


def test_connection_policy_enables_wal_foreign_keys_and_busy_timeout(database: Database) -> None:
    with database.read() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5_000
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_new_database_has_owner_only_permissions(database: Database) -> None:
    assert stat.S_IMODE(os.stat(database.path).st_mode) == 0o600


def test_recorded_migration_checksum_mismatch_fails_closed(database: Database) -> None:
    with database.transaction() as connection:
        connection.execute("DROP TRIGGER schema_migrations_no_update")
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
            ("0" * 64,),
        )

    with pytest.raises(IntegrityError) as caught:
        database.initialize()

    assert caught.value.code == "migration_checksum_mismatch"


def test_database_with_unknown_future_migration_is_rejected(database: Database) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum)
            VALUES (99, '0099_future.sql', ?)
            """,
            ("f" * 64,),
        )

    with pytest.raises(IntegrityError) as caught:
        database.initialize()

    assert caught.value.code == "database_too_new"


def test_malformed_migration_version_is_a_safe_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed-migration.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations(
                version TEXT,
                name TEXT,
                checksum TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
            ("not-an-integer", "0001_research_core.sql", "0" * 64),
        )
        connection.commit()

    with pytest.raises(IntegrityError) as caught:
        Database(path).connect()

    assert caught.value.code == "migration_history_invalid"


def test_failed_migration_rolls_back_every_statement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_sql = """
    CREATE TABLE schema_migrations(
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        checksum TEXT NOT NULL
    );
    CREATE TABLE should_rollback(value TEXT);
    THIS IS NOT VALID SQL;
    """
    migration = Migration(
        version=1,
        name="0001_failure.sql",
        sql=migration_sql,
        checksum="a" * 64,
    )
    monkeypatch.setattr(db_module, "_migration_files", lambda: (migration,))
    path = tmp_path / "failed.db"

    with pytest.raises(IntegrityError) as caught:
        Database(path).initialize()

    assert caught.value.code == "migration_failed"
    assert not path.exists()
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()


def test_unmanaged_existing_database_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unmanaged.db"
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    with pytest.raises(IntegrityError) as caught:
        Database(path).initialize()

    assert caught.value.code == "database_unmanaged"


def test_database_parent_symlink_is_rejected_without_creating_target(
    tmp_path: Path,
) -> None:
    actual_parent = tmp_path / "actual"
    actual_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)

    with pytest.raises(IntegrityError) as caught:
        Database(linked_parent / "research.db").initialize()

    assert caught.value.code == "database_symlink"
    assert not (actual_parent / "research.db").exists()


def test_malformed_database_is_reported_as_a_safe_domain_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed.db"
    malformed = b"not a sqlite database\x00private bytes"
    path.write_bytes(malformed)

    with pytest.raises(IntegrityError):
        Database(path).initialize()

    assert path.read_bytes() == malformed


@pytest.mark.security
def test_publication_persists_the_new_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published database must survive a crash right after the success report.

    `os.link` creates a directory entry that lives in the page cache until the
    containing directory is synced. Initialization, backup, and restore all
    publish through that one primitive, so the barrier belongs there rather than
    at each of the three call sites.
    """

    synced: list[str] = []
    original_fsync = db_module.os.fsync

    def recording_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            synced.append("directory")
        original_fsync(descriptor)

    monkeypatch.setattr(db_module.os, "fsync", recording_fsync)

    source = tmp_path / "source.db"
    Database(source).initialize()
    assert synced == ["directory"], "fresh initialization did not persist its directory entry"

    synced.clear()
    Database(source).backup_to(tmp_path / "backup.db")
    assert synced == ["directory"], "backup did not persist its directory entry"

    synced.clear()
    Database.restore_from(tmp_path / "backup.db", tmp_path / "restored.db")
    assert synced == ["directory"], "restore did not persist its directory entry"
    assert (tmp_path / "restored.db").is_file()


def test_backup_restore_preserves_state_and_owner_only_permissions(
    database: Database,
    tmp_path: Path,
) -> None:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:backup-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="backup round trip",
    )
    research = ResearchService(database, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Backup mission",
        objective="Prove backup and restore preserve committed state.",
        identity=identity,
    )
    backup = tmp_path / "backup.db"
    restored_path = tmp_path / "restored.db"

    database.backup_to(backup)
    restored = Database.restore_from(backup, restored_path)

    assert restored.schema_version() == latest_schema_version()
    assert ResearchService(restored).get_mission(mission.id).title == mission.title
    assert stat.S_IMODE(os.stat(backup).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(restored_path).st_mode) == 0o600


def test_successful_restore_persists_transactional_audit(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "restored.db"
    database.backup_to(backup)
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:restore-audit-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="restore audit persistence",
    )

    restored = OperationsService.restore(
        backup=backup,
        target=target,
        identity=identity,
        clock=fixed_clock,
        id_factory=ids,
    )

    assert restored.path == target
    with restored.read() as connection:
        events = [
            event for event in list_audit_events(connection) if event["run_id"] == identity.run_id
        ]
    assert [event["event_type"] for event in events] == [
        "research.run.started",
        "database.restored",
    ]
    assert events[-1]["details"] == {"schema_version": latest_schema_version()}
    assert all(event["actor_id"] == identity.actor_id for event in events)
    assert list(tmp_path.glob(f".{target.name}.minerva-*.tmp*")) == []


def test_database_cleanup_preserves_concurrent_replacements(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "restore.db"
    database.backup_to(backup)
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:restore-replacement-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="preserve concurrent restore replacements",
    )
    replacements: dict[Path, bytes] = {}

    class ReplacingFailingAuditSink:
        def __init__(self) -> None:
            self.delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

        def ensure_run(
            self,
            connection: sqlite3.Connection,
            current_identity: IdentityContext,
        ) -> None:
            self.delegate.ensure_run(connection, current_identity)

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
            assert event_type == "database.restored"
            assert not target.exists()
            staged_paths = list(tmp_path.glob(f".{target.name}.minerva-*.tmp"))
            assert len(staged_paths) == 1
            staged_path = staged_paths[0]
            database_path = Path(str(connection.execute("PRAGMA database_list").fetchone()["file"]))
            assert database_path == staged_path
            replacement_size = staged_path.stat().st_size
            assert replacement_size > 0

            public_paths = [
                target,
                *(Path(f"{target}{suffix}") for suffix in ("-wal", "-shm", "-journal")),
            ]
            for index, public_path in enumerate(public_paths):
                replacement = bytes([65 + index]) * replacement_size
                public_path.write_bytes(replacement)
                replacements[public_path] = replacement
            assert {path.stat().st_size for path in public_paths} == {replacement_size}
            raise RuntimeError("synthetic audit failure")

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        OperationsService.restore(
            backup=backup,
            target=target,
            identity=identity,
            audit=ReplacingFailingAuditSink(),
            clock=fixed_clock,
            id_factory=ids,
        )

    assert backup.is_file()
    assert replacements
    for path, expected in replacements.items():
        assert path.read_bytes() == expected
    assert list(tmp_path.glob(f".{target.name}.minerva-*.tmp*")) == []


def test_restore_revalidates_staged_database_after_audit_callback(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "unpublished.db"
    database.backup_to(backup)
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:restore-revalidation-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="restore post-audit revalidation",
    )

    class TriggerRemovingAuditSink:
        def __init__(self) -> None:
            self.delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

        def ensure_run(
            self,
            connection: sqlite3.Connection,
            current_identity: IdentityContext,
        ) -> None:
            self.delegate.ensure_run(connection, current_identity)

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
            audit_id = self.delegate.record(
                connection,
                identity=identity,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                mission_id=mission_id,
                details=details,
            )
            connection.execute("DROP TRIGGER audit_no_update")
            return audit_id

    with pytest.raises(IntegrityError) as caught:
        OperationsService.restore(
            backup=backup,
            target=target,
            identity=identity,
            audit=TriggerRemovingAuditSink(),
            clock=fixed_clock,
            id_factory=ids,
        )

    assert caught.value.code == "backup_invalid"
    assert not target.exists()
    assert list(tmp_path.glob(f".{target.name}.minerva-*.tmp*")) == []


def test_restore_rejects_staged_wal_retained_by_audit_reader(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "unpublished.db"
    database.backup_to(backup)
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:restore-reader-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="retain the staged WAL during restore audit",
    )
    held_readers: list[sqlite3.Connection] = []

    class ReaderRetainingAuditSink:
        def __init__(self) -> None:
            self.delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

        def ensure_run(
            self,
            connection: sqlite3.Connection,
            current_identity: IdentityContext,
        ) -> None:
            self.delegate.ensure_run(connection, current_identity)

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
            audit_id = self.delegate.record(
                connection,
                identity=identity,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                mission_id=mission_id,
                details=details,
            )
            staged_path = Path(str(connection.execute("PRAGMA database_list").fetchone()["file"]))
            reader = sqlite3.connect(staged_path)
            try:
                reader.execute("PRAGMA query_only = ON")
                reader.execute("BEGIN")
                reader.execute("SELECT COUNT(*) FROM audit_events").fetchone()
            except BaseException:
                reader.close()
                raise
            held_readers.append(reader)
            assert Path(f"{staged_path}-wal").is_file()
            return audit_id

    try:
        with pytest.raises(IntegrityError) as caught:
            OperationsService.restore(
                backup=backup,
                target=target,
                identity=identity,
                audit=ReaderRetainingAuditSink(),
                clock=fixed_clock,
                id_factory=ids,
            )
        assert caught.value.code == "restore_not_standalone"
        assert not target.exists()
    finally:
        for reader in held_readers:
            reader.close()

    assert held_readers
    assert list(tmp_path.glob(f".{target.name}.minerva-*.tmp*")) == []


def test_restore_rejects_valid_destination_wal_without_deleting_it(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "restored.db"
    database.backup_to(backup)
    backup_bytes = backup.read_bytes()
    target.write_bytes(backup_bytes)
    keeper = sqlite3.connect(target, isolation_level=None)
    verifier: sqlite3.Connection | None = None
    injected_value = "synthetic WAL injection"
    try:
        assert keeper.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        keeper.execute("PRAGMA wal_autocheckpoint = 0")
        keeper.execute("BEGIN IMMEDIATE")
        keeper.execute("CREATE TABLE injected(value TEXT NOT NULL)")
        keeper.execute("INSERT INTO injected(value) VALUES (?)", (injected_value,))
        keeper.commit()

        target.unlink()
        target.write_bytes(backup_bytes)
        verifier = sqlite3.connect(target)
        assert verifier.execute("SELECT value FROM injected").fetchone()[0] == injected_value
        target.unlink()

        sidecars = [
            Path(f"{target}{suffix}")
            for suffix in ("-wal", "-shm")
            if Path(f"{target}{suffix}").exists()
        ]
        assert {path.suffix for path in sidecars} == {".db-wal", ".db-shm"}
        sidecar_bytes = {path: path.read_bytes() for path in sidecars}

        with pytest.raises(ConflictError) as caught:
            Database.restore_from(backup, target)

        assert caught.value.code == "restore_destination_sidecar_exists"
        assert not target.exists()
        for path, expected in sidecar_bytes.items():
            assert path.read_bytes() == expected
    finally:
        if verifier is not None:
            verifier.close()
        keeper.close()

    assert not target.exists()
    assert backup.read_bytes() == backup_bytes
    assert list(tmp_path.glob(f".{target.name}.minerva-*.tmp*")) == []


def test_backup_and_restore_refuse_existing_targets(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup.db"
    sentinel = b"operator-owned existing backup bytes"
    backup.write_bytes(sentinel)

    with pytest.raises(ConflictError) as backup_error:
        database.backup_to(backup)

    assert backup_error.value.code == "backup_exists"
    assert backup.read_bytes() == sentinel

    valid_backup = tmp_path / "valid-backup.db"
    database.backup_to(valid_backup)
    with pytest.raises(ConflictError) as restore_error:
        Database.restore_from(valid_backup, database.path)

    assert restore_error.value.code == "database_exists"


def test_invalid_backup_fails_without_leaving_restore_target(tmp_path: Path) -> None:
    backup = tmp_path / "invalid.db"
    backup.write_bytes(b"synthetic invalid sqlite content")
    target = tmp_path / "target.db"

    with pytest.raises(IntegrityError):
        Database.restore_from(backup, target)

    assert not target.exists()


def test_backup_rejects_database_missing_an_integrity_trigger(
    database: Database,
    tmp_path: Path,
) -> None:
    with database.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_update")
    target = tmp_path / "untrustworthy-backup.db"

    with pytest.raises(IntegrityError) as caught:
        database.backup_to(target)

    assert caught.value.code == "database_invalid"
    assert not target.exists()
    assert not Path(f"{target}-wal").exists()
    assert not Path(f"{target}-shm").exists()


def test_failed_initialization_audit_removes_a_fresh_database(tmp_path: Path) -> None:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:init-atomic-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="initialization audit rollback",
    )
    path = tmp_path / "fresh-failure.db"
    service = OperationsService(
        Database(path),
        audit=FailingAuditSink(ids),
        clock=fixed_clock,
        id_factory=ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        service.initialize(identity=identity, refuse_existing=True)

    assert not path.exists()
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()


def test_failed_initialization_audit_rolls_back_an_existing_database_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = db_module._migration_files()
    assert len(migrations) >= 2
    path = tmp_path / "upgrade-failure.db"
    database = Database(path)
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:1])
    assert database.initialize() == 1
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)

    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:upgrade-atomic-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="upgrade audit rollback",
    )
    service = OperationsService(
        database,
        audit=FailingAuditSink(ids),
        clock=fixed_clock,
        id_factory=ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        service.initialize(identity=identity, refuse_existing=False)

    with closing(sqlite3.connect(path)) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        findings_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'findings'"
        ).fetchone()
        run_count = connection.execute(
            "SELECT COUNT(*) FROM research_runs WHERE id = ?",
            (identity.run_id,),
        ).fetchone()[0]
        audit_count = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert version == 1
    assert findings_table is None
    assert run_count == 0
    assert audit_count == 0


def test_audit_failure_rolls_back_domain_row_run_and_audit(database: Database) -> None:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:atomic-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="audit rollback",
    )
    research = ResearchService(
        database,
        audit=FailingAuditSink(ids),
        clock=fixed_clock,
        id_factory=ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        research.create_mission(
            title="Must roll back",
            objective="The domain row cannot outlive its failed audit event.",
            identity=identity,
        )

    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_missions").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM research_runs WHERE id = ?",
                (identity.run_id,),
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_rejected_mutation_creates_no_run_or_success_event(database: Database) -> None:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:rejected-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="rejected command",
    )
    research = ResearchService(database, clock=fixed_clock, id_factory=ids)

    with pytest.raises(NotFoundError):
        research.add_question(
            mission_id="mis_" + "0" * 32,
            text="This mission does not exist.",
            identity=identity,
        )

    with database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM research_runs WHERE id = ?",
                (identity.run_id,),
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_audit_events_are_sequence_ordered_and_append_only(database: Database) -> None:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:audit-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="audit ordering",
    )
    research = ResearchService(database, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Audit mission",
        objective="Check stable sequence ordering.",
        identity=identity,
    )
    research.add_question(
        mission_id=mission.id,
        text="Are audit events strictly ordered?",
        identity=identity,
    )

    with database.read() as connection:
        events = list_audit_events(connection)
    sequences = [int(event["sequence"]) for event in events]
    assert sequences == sorted(sequences)
    assert [event["event_type"] for event in events] == [
        "research.run.started",
        "research.mission.created",
        "research.question.created",
    ]

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        database.transaction() as connection,
    ):
        connection.execute("UPDATE audit_events SET details_json = '{}' WHERE sequence = 1")
    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        database.transaction() as connection,
    ):
        connection.execute("DELETE FROM audit_events WHERE sequence = 1")


def test_restore_rejects_committed_database_with_live_wal(
    database: Database,
    tmp_path: Path,
) -> None:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:live-wal-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="prove live WAL archives fail closed",
    )
    keeper = database.connect()
    target = tmp_path / "restored.db"
    try:
        ResearchService(database, clock=fixed_clock, id_factory=ids).create_mission(
            title="Committed WAL state",
            objective="Keep committed state in a live SQLite WAL sidecar.",
            identity=identity,
        )
        wal = Path(f"{database.path}-wal")
        assert wal.is_file()
        assert wal.stat().st_size > 0

        with pytest.raises(IntegrityError) as caught:
            Database.restore_from(database.path, target)

        assert caught.value.code == "backup_not_standalone"
        assert not target.exists()
    finally:
        keeper.close()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_restore_rejects_every_sqlite_sidecar_without_creating_target(
    database: Database,
    tmp_path: Path,
    suffix: str,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "restored.db"
    database.backup_to(backup)
    sidecar = Path(f"{backup}{suffix}")
    sidecar.write_bytes(b"operator-owned live sidecar")

    with pytest.raises(IntegrityError) as caught:
        Database.restore_from(backup, target)

    assert caught.value.code == "backup_not_standalone"
    assert sidecar.read_bytes() == b"operator-owned live sidecar"
    assert not target.exists()


def test_restore_reads_clean_backup_without_creating_source_sidecars(
    database: Database,
    tmp_path: Path,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "restored.db"
    database.backup_to(backup)
    sidecars = [Path(f"{backup}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
    assert not any(path.exists() or path.is_symlink() for path in sidecars)

    Database.restore_from(backup, target)

    assert target.is_file()
    assert not any(path.exists() or path.is_symlink() for path in sidecars)


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [("backup", "backup_exists"), ("restore", "database_exists")],
)
def test_database_publication_race_preserves_substituted_symlink_victim(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_code: str,
) -> None:
    archive = tmp_path / "archive.db"
    if operation == "restore":
        database.backup_to(archive)
    target = tmp_path / "published.db"
    victim = tmp_path / "victim.db"
    victim_bytes = b"must remain unchanged"
    victim.write_bytes(victim_bytes)
    original_link = db_module.os.link

    def substitute_then_link(
        source: os.PathLike[str] | str,
        destination: os.PathLike[str] | str,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        Path(destination).symlink_to(victim)
        original_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(db_module.os, "link", substitute_then_link)

    with pytest.raises(ConflictError) as caught:
        if operation == "backup":
            database.backup_to(target)
        else:
            Database.restore_from(archive, target)

    assert caught.value.code == expected_code
    assert target.is_symlink()
    assert target.resolve() == victim
    assert victim.read_bytes() == victim_bytes
    assert list(tmp_path.glob(f".{target.name}.minerva-*.tmp*")) == []


def test_pre_index_schema_fails_closed_before_pinned_queries_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database missing migration 0003 is refused with a typed error.

    Claim-scoped synthesis pins `idx_findings_claim` with INDEXED BY, so a
    database stopped at schema 2 would raise a raw sqlite3 "no such index"
    error if it ever reached those queries. The migration-state check must
    reject it first.
    """

    migrations = db_module._migration_files()
    assert len(migrations) >= 3
    path = tmp_path / "pre-index.db"
    database = Database(path)
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:2])
    assert database.initialize() == 2
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)

    with pytest.raises(IntegrityError) as caught, database.read():
        pass

    assert caught.value.code == "database_migration_required"


def test_concurrent_initialization_preserves_the_published_database(tmp_path: Path) -> None:
    """Racing initializers must not destroy the database one of them published.

    Before staged publication, every loser's failure cleanup unlinked the
    winner's committed database by pathname, so the directory ended empty while
    one caller had already reported success.
    """

    path = tmp_path / "research.db"
    workers = 6
    barrier = threading.Barrier(workers)
    versions: list[int] = []
    failures: list[str] = []
    lock = threading.Lock()

    def initialize() -> None:
        barrier.wait(timeout=30)
        try:
            version = Database(path).initialize()
        except MinervaError as error:  # pragma: no cover - recorded, then asserted away
            with lock:
                failures.append(error.code)
            return
        with lock:
            versions.append(version)

    threads = [threading.Thread(target=initialize) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == []
    assert versions == [latest_schema_version()] * workers
    assert path.is_file()
    assert sorted(item.name for item in tmp_path.iterdir()) == ["research.db"]
    with Database(path).read() as connection:
        recorded = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert recorded == latest_schema_version()


def test_failed_open_preserves_operator_owned_sidecars(tmp_path: Path) -> None:
    """A failed open must not remove SQLite sidecars Minerva did not create."""

    path = tmp_path / "research.db"
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{path}{suffix}").write_bytes(b"operator owned")

    with pytest.raises(MinervaError) as caught:
        Database(path).connect()

    assert caught.value.code == "database_missing"
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "research.db-journal",
        "research.db-shm",
        "research.db-wal",
    ]
    for suffix in ("-wal", "-shm", "-journal"):
        assert Path(f"{path}{suffix}").read_bytes() == b"operator owned"


def test_failed_open_preserves_a_dangling_operator_symlink(tmp_path: Path) -> None:
    """A rejected symlink path must be left for the operator to inspect."""

    path = tmp_path / "research.db"
    path.symlink_to(tmp_path / "absent.db")

    with pytest.raises(IntegrityError) as caught:
        Database(path).connect()

    assert caught.value.code == "database_symlink"
    assert path.is_symlink()


def test_connect_never_creates_a_database(tmp_path: Path) -> None:
    """Opening a missing database reports it plainly and writes nothing."""

    path = tmp_path / "research.db"

    with pytest.raises(MinervaError) as caught:
        Database(path).connect()

    assert caught.value.code == "database_missing"
    assert caught.value.http_status == 503
    assert list(tmp_path.iterdir()) == []


def test_database_paths_with_uri_metacharacters_open_the_intended_file(tmp_path: Path) -> None:
    """Percent-encoding keeps `?` and `#` from truncating the connection URI."""

    for name in ("plain.db", "with space.db", "with?query.db", "with#fragment.db"):
        path = tmp_path / name
        assert Database(path).initialize() == latest_schema_version()
        assert path.is_file()
        with Database(path).read() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                == latest_schema_version()
            )
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "plain.db",
        "with space.db",
        "with#fragment.db",
        "with?query.db",
    ]


def test_insert_or_replace_cannot_bypass_append_only_triggers(database: Database) -> None:
    """Conflict resolution must not delete an append-only row without firing triggers.

    `INSERT OR REPLACE` resolves a primary-key conflict with a delete. Without
    `PRAGMA recursive_triggers`, that delete skips the BEFORE DELETE triggers, so
    a recorded migration checksum could be rewritten in place.
    """

    with database.read() as connection:
        assert connection.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
        original = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 1"
        ).fetchone()[0]

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        database.transaction() as (connection),
    ):
        connection.execute(
            """
            INSERT OR REPLACE INTO schema_migrations(version, name, checksum)
            VALUES (1, '0001_research_core.sql', ?)
            """,
            ("0" * 64,),
        )

    with database.read() as connection:
        assert (
            connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = 1"
            ).fetchone()[0]
            == original
        )


def test_backup_refuses_to_publish_beside_an_existing_sidecar(
    database: Database,
    tmp_path: Path,
) -> None:
    """Backup applies the destination-sidecar refusal that restore already had."""

    target = tmp_path / "backup.db"
    sidecar = Path(f"{target}-wal")
    sidecar.write_bytes(b"operator owned")

    with pytest.raises(ConflictError) as caught:
        database.backup_to(target)

    assert caught.value.code == "backup_destination_sidecar_exists"
    assert not target.exists()
    assert sidecar.read_bytes() == b"operator owned"


@pytest.mark.parametrize(
    ("installed_migrations", "expected_code"),
    [
        ("newer", "database_migration_required"),
        ("older", "database_too_new"),
    ],
)
def test_restore_preserves_migration_state_codes_for_intact_backups(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed_migrations: str,
    expected_code: str,
) -> None:
    """An intact backup at another schema version must not be called corrupt.

    Reporting `backup_invalid` here would tell an operator their backup failed
    integrity validation at the moment they most need to trust it.
    """

    migrations = db_module._migration_files()
    assert len(migrations) >= 2
    backup = tmp_path / "backup.db"
    database.backup_to(backup)

    if installed_migrations == "newer":
        future = Migration(
            version=len(migrations) + 1,
            name="0099_future.sql",
            sql="CREATE TABLE future_state(value TEXT);",
            checksum="b" * 64,
        )
        monkeypatch.setattr(db_module, "_migration_files", lambda: (*migrations, future))
    else:
        monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])

    with pytest.raises(IntegrityError) as caught:
        Database.restore_from(backup, tmp_path / "restored.db")

    assert caught.value.code == expected_code
    assert not (tmp_path / "restored.db").exists()
