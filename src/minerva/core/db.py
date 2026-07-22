"""SQLite connection policy, forward-only migrations, backup, and restore."""

from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from pathlib import Path

from minerva.core.errors import ConflictError, IntegrityError, MinervaError

BUSY_TIMEOUT_MS = 5_000


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def _migration_files() -> tuple[Migration, ...]:
    root = resources.files("minerva.core.migrations")
    migrations: list[Migration] = []
    for item in sorted(root.iterdir(), key=lambda entry: entry.name):
        if not item.name.endswith(".sql"):
            continue
        prefix, separator, _ = item.name.partition("_")
        if not separator or not prefix.isdigit():
            raise RuntimeError(f"invalid packaged migration name: {item.name}")
        sql = item.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=int(prefix),
                name=item.name,
                sql=sql,
                checksum=sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    versions = [migration.version for migration in migrations]
    if not migrations or versions != list(range(1, len(migrations) + 1)):
        raise RuntimeError("packaged migrations must be contiguous and start at version 1")
    return tuple(migrations)


def latest_schema_version() -> int:
    return len(_migration_files())


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_migration_state(
    connection: sqlite3.Connection,
    *,
    require_latest: bool,
) -> int:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if table is None:
        raise IntegrityError("database_unready", "The database is not initialized.")

    rows = list(
        connection.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version")
    )
    raw_versions = [row["version"] for row in rows]
    if any(type(version) is not int for version in raw_versions):
        raise IntegrityError(
            "migration_history_invalid",
            "The recorded migration history contains an invalid version.",
        )
    applied_versions = list(raw_versions)
    if applied_versions != list(range(1, len(applied_versions) + 1)):
        raise IntegrityError(
            "migration_history_invalid",
            "The recorded migration history is not contiguous.",
        )

    migrations = _migration_files()
    if len(rows) > len(migrations):
        raise IntegrityError(
            "database_too_new",
            "The database was created by a newer Minerva version.",
        )
    for row, migration in zip(rows, migrations, strict=False):
        recorded = (str(row["name"]), str(row["checksum"]))
        if recorded != (migration.name, migration.checksum):
            raise IntegrityError(
                "migration_checksum_mismatch",
                "A recorded migration does not match this Minerva installation.",
            )
    if require_latest and len(rows) != len(migrations):
        raise IntegrityError(
            "database_migration_required",
            "The database requires an explicit Minerva migration.",
        )
    return len(rows)


def _is_busy_error(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", 0)
    return isinstance(code, int) and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _reject_unsafe_database_path(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:-1]:
        current /= component
        if current.is_symlink():
            raise IntegrityError("database_symlink", "Database paths may not use symbolic links.")
        if not current.is_dir():
            raise IntegrityError(
                "database_parent_missing", "The database directory does not exist."
            )
    if absolute.is_symlink():
        raise IntegrityError("database_symlink", "Database paths may not be symbolic links.")
    if not absolute.parent.is_dir():
        raise IntegrityError("database_parent_missing", "The database directory does not exist.")


@dataclass(frozen=True, slots=True)
class _PrivateDatabaseFile:
    path: Path
    device: int
    inode: int

    def cleanup(self) -> None:
        try:
            current = os.stat(self.path, follow_symlinks=False)
        except OSError:
            return
        if (current.st_dev, current.st_ino) != (self.device, self.inode):
            return
        _remove_database_artifacts(self.path)


def _create_private_database_file(target: Path) -> _PrivateDatabaseFile:
    """Create an unpredictable same-directory staging file with owner-only access."""

    _reject_unsafe_database_path(target)
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{target.name}.minerva-",
            suffix=".tmp",
            dir=target.parent,
        )
    except OSError as error:
        raise IntegrityError(
            "database_path_invalid",
            "The database staging file could not be created safely.",
        ) from error
    try:
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise IntegrityError(
                "database_path_invalid",
                "The database staging file could not be created safely.",
            )
        return _PrivateDatabaseFile(Path(raw_path), metadata.st_dev, metadata.st_ino)
    except BaseException:
        with suppress(OSError):
            Path(raw_path).unlink()
        raise
    finally:
        with suppress(OSError):
            os.close(descriptor)


def _publish_private_database(
    staged: _PrivateDatabaseFile,
    target: Path,
    *,
    conflict_code: str,
) -> None:
    """Atomically publish *staged* without opening or replacing the target pathname."""

    try:
        current = os.stat(staged.path, follow_symlinks=False)
    except OSError as error:
        raise IntegrityError(
            "database_path_invalid",
            "The database staging file could not be published safely.",
        ) from error
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (
        staged.device,
        staged.inode,
    ):
        raise IntegrityError(
            "database_path_invalid",
            "The database staging file could not be published safely.",
        )
    try:
        os.link(staged.path, target, follow_symlinks=False)
    except FileExistsError as error:
        raise ConflictError(conflict_code, "Refusing to overwrite an existing file.") from error
    except (NotImplementedError, OSError, TypeError) as error:
        raise IntegrityError(
            "database_path_invalid",
            "The database staging file could not be published safely.",
        ) from error


def _require_standalone_backup(backup: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{backup}{suffix}")
        if sidecar.exists() or sidecar.is_symlink():
            raise IntegrityError(
                "backup_not_standalone",
                "The backup has live SQLite sidecars and is not a standalone artifact.",
            )


def _remove_database_artifacts(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        with suppress(OSError):
            Path(f"{path}{suffix}").unlink(missing_ok=True)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file() and not self.path.is_symlink()

    def connect(self, *, validate_schema: bool = True) -> sqlite3.Connection:
        was_present = self.path.exists()
        try:
            return self._connect(validate_schema=validate_schema)
        except MinervaError:
            if not was_present:
                _remove_database_artifacts(self.path)
            raise
        except sqlite3.Error as error:
            if not was_present:
                _remove_database_artifacts(self.path)
            if _is_busy_error(error):
                raise MinervaError(
                    "database_busy",
                    "The database is busy; retry the operation.",
                    http_status=503,
                ) from error
            raise IntegrityError(
                "database_invalid",
                "The database could not be opened safely.",
            ) from error

    def _connect(self, *, validate_schema: bool) -> sqlite3.Connection:
        _reject_unsafe_database_path(self.path)
        was_present = self.path.exists()
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA trusted_schema = OFF")
            journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if journal_mode.lower() != "wal":
                raise IntegrityError("database_wal_unavailable", "SQLite WAL mode is unavailable.")
            connection.execute("PRAGMA synchronous = FULL")
            if not was_present:
                os.chmod(self.path, 0o600)
            if validate_schema:
                _validate_migration_state(connection, require_latest=True)
            return connection
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as error:
            if connection.in_transaction:
                connection.rollback()
            if _is_busy_error(error):
                raise MinervaError(
                    "database_busy",
                    "The database is busy; retry the operation.",
                    http_status=503,
                ) from error
            raise
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        if not self.exists():
            raise MinervaError(
                "database_missing", "The Minerva database does not exist.", http_status=503
            )
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
        except sqlite3.OperationalError as error:
            if _is_busy_error(error):
                raise MinervaError(
                    "database_busy",
                    "The database is busy; retry the operation.",
                    http_status=503,
                ) from error
            raise
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def initialize(
        self,
        *,
        refuse_existing: bool = False,
        on_ready: Callable[[sqlite3.Connection, int], None] | None = None,
    ) -> int:
        existed_before = self.path.exists()
        if refuse_existing and existed_before:
            raise ConflictError("database_exists", "Refusing to overwrite an existing database.")
        _reject_unsafe_database_path(self.path)
        connection = self.connect(validate_schema=False)
        try:
            existing = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            if existing and "schema_migrations" not in existing:
                raise IntegrityError(
                    "database_unmanaged", "The database is not managed by Minerva migrations."
                )

            applied: dict[int, tuple[str, str]] = {}
            if "schema_migrations" in existing:
                for row in connection.execute(
                    "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
                ):
                    applied[int(row[0])] = (str(row[1]), str(row[2]))

            migrations = _migration_files()
            known_versions = {migration.version for migration in migrations}
            if set(applied) - known_versions:
                raise IntegrityError(
                    "database_too_new", "The database was created by a newer Minerva version."
                )

            pending: list[Migration] = []
            for migration in migrations:
                recorded = applied.get(migration.version)
                if recorded is None:
                    pending.append(migration)
                elif recorded != (migration.name, migration.checksum):
                    raise IntegrityError(
                        "migration_checksum_mismatch",
                        "A recorded migration does not match this Minerva installation.",
                    )

            try:
                if pending:
                    statements = ["BEGIN IMMEDIATE;"]
                    for migration in pending:
                        statements.extend(
                            (
                                migration.sql,
                                "INSERT INTO schema_migrations(version, name, checksum) VALUES ("  # noqa: S608
                                f"{migration.version}, {_sql_literal(migration.name)}, "
                                f"{_sql_literal(migration.checksum)});",
                            )
                        )
                    connection.executescript("\n".join(statements))
                else:
                    connection.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as error:
                if _is_busy_error(error):
                    raise MinervaError(
                        "database_busy",
                        "The database is busy; retry the operation.",
                        http_status=503,
                    ) from error
                raise IntegrityError(
                    "migration_failed", "A database migration could not be applied."
                ) from error

            _validate_migration_state(connection, require_latest=True)
            version = len(migrations)
            if on_ready is not None:
                on_ready(connection, version)
            connection.commit()
            return version
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            if not existed_before:
                connection.close()
                _remove_database_artifacts(self.path)
            raise
        finally:
            connection.close()

    def schema_version(self) -> int:
        with self.read() as connection:
            try:
                row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            except sqlite3.Error as error:
                raise IntegrityError(
                    "database_unready", "The database is not initialized."
                ) from error
            return int(row[0] or 0)

    def integrity_check(self) -> tuple[bool, str]:
        with self.read() as connection:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if result != "ok" or foreign_keys:
            return False, "SQLite integrity validation failed."
        return True, "ok"

    def backup_to(self, target: Path) -> None:
        _reject_unsafe_database_path(target)
        if not self.exists():
            raise MinervaError("database_missing", "The Minerva database does not exist.")

        from minerva.core.doctor import run_doctor

        source_report = run_doctor(self, deep=True)
        if not source_report.ok:
            raise IntegrityError(
                "database_invalid",
                "The database failed validation and cannot be backed up.",
            )

        source = self.connect()
        destination: sqlite3.Connection | None = None
        staged = _create_private_database_file(target)
        try:
            destination = sqlite3.connect(staged.path)
            source.backup(destination)
            destination.commit()
            destination.close()
            destination = None
            backup_report = run_doctor(Database(staged.path), deep=True)
            if not backup_report.ok:
                raise IntegrityError(
                    "backup_invalid",
                    "The backup failed post-copy validation.",
                )
            _publish_private_database(staged, target, conflict_code="backup_exists")
        finally:
            source.close()
            if destination is not None:
                destination.close()

            staged.cleanup()

    @classmethod
    def restore_from(cls, backup: Path, target: Path) -> Database:
        _reject_unsafe_database_path(backup)
        _reject_unsafe_database_path(target)
        if not backup.is_file() or backup.is_symlink():
            raise IntegrityError("backup_invalid", "The backup is not a regular database file.")
        _require_standalone_backup(backup)

        backup_uri = backup.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
        source = sqlite3.connect(backup_uri, uri=True)
        source.row_factory = sqlite3.Row
        destination: sqlite3.Connection | None = None
        staged: _PrivateDatabaseFile | None = None
        try:
            _require_standalone_backup(backup)
            try:
                result = str(source.execute("PRAGMA integrity_check").fetchone()[0])
                foreign_keys = list(source.execute("PRAGMA foreign_key_check"))
                _validate_migration_state(source, require_latest=True)
            except (sqlite3.Error, IntegrityError) as error:
                raise IntegrityError(
                    "backup_invalid",
                    "The backup failed integrity validation.",
                ) from error
            if result != "ok" or foreign_keys:
                raise IntegrityError(
                    "backup_invalid",
                    "The backup failed integrity validation.",
                )

            staged = _create_private_database_file(target)
            try:
                destination = sqlite3.connect(staged.path)
                source.backup(destination)
                destination.commit()
            except sqlite3.Error as error:
                raise IntegrityError(
                    "restore_failed",
                    "The database could not be restored safely.",
                ) from error
            finally:
                if destination is not None:
                    destination.close()
                    destination = None

            _require_standalone_backup(backup)
            restored = cls(staged.path)
            restored.initialize()
            from minerva.core.doctor import run_doctor

            report = run_doctor(restored, deep=True)
            if not report.ok:
                raise IntegrityError(
                    "backup_invalid",
                    "The restored database failed integrity validation.",
                )
            _require_standalone_backup(backup)
            _publish_private_database(staged, target, conflict_code="database_exists")
            return cls(target)
        finally:
            source.close()
            if destination is not None:
                destination.close()
            if staged is not None:
                staged.cleanup()
