from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path

import pytest

import minerva.core.db as db_module
import minerva.core.operations as operations_module
from conftest import SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder, list_audit_events
from minerva.core.db import Database, Migration, latest_schema_version
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
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


def test_failed_restore_audit_removes_base_and_all_sidecars(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup = tmp_path / "standalone.db"
    target = tmp_path / "failed-restore.db"
    database.backup_to(backup)
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:restore-cleanup-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="restore audit cleanup",
    )
    original_cleanup = operations_module._unlink_database_if_same

    def synthesize_sidecars_then_cleanup(path: Path, device: int, inode: int) -> bool:
        assert path == target
        for suffix in operations_module._SQLITE_SIDECAR_SUFFIXES:
            Path(f"{path}{suffix}").write_bytes(b"synthetic orphan")
        return original_cleanup(path, device, inode)

    monkeypatch.setattr(
        operations_module,
        "_unlink_database_if_same",
        synthesize_sidecars_then_cleanup,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        OperationsService.restore(
            backup=backup,
            target=target,
            identity=identity,
            audit=FailingAuditSink(ids),
            clock=fixed_clock,
            id_factory=ids,
        )

    assert backup.is_file()
    for suffix in ("", *operations_module._SQLITE_SIDECAR_SUFFIXES):
        assert not Path(f"{target}{suffix}").exists()


def test_database_cleanup_preserves_concurrent_replacements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "restore.db"
    target.write_bytes(b"minerva-owned base")
    base_metadata = os.stat(target, follow_symlinks=False)
    replacement_bytes = b"B" * 32
    sidecars = [Path(f"{target}{suffix}") for suffix in operations_module._SQLITE_SIDECAR_SUFFIXES]
    for sidecar in sidecars:
        sidecar.write_bytes(b"A" * 32)

    original_unlink = operations_module._unlink_if_same

    def unlink_then_replace(path: Path, device: int, inode: int) -> bool:
        removed = original_unlink(path, device, inode)
        if path == target and removed:
            target.write_bytes(replacement_bytes)
            for sidecar in sidecars:
                sidecar.unlink()
                sidecar.write_bytes(replacement_bytes)
        return removed

    monkeypatch.setattr(operations_module, "_unlink_if_same", unlink_then_replace)

    assert operations_module._unlink_database_if_same(
        target,
        base_metadata.st_dev,
        base_metadata.st_ino,
    )
    assert target.read_bytes() == replacement_bytes
    assert all(sidecar.read_bytes() == replacement_bytes for sidecar in sidecars)


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
