"""SQLite connection policy, forward-only migrations, backup, and restore."""

from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from minerva.core.durability import fsync_directory
from minerva.core.errors import ConflictError, IntegrityError, MinervaError, OperationalError

if TYPE_CHECKING:
    # `doctor` imports this module, so the runtime import stays inside the
    # functions that need it and only the annotation is resolved here.
    from minerva.core.doctor import DoctorReport

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


def _read_migration_history(connection: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    return {
        int(row[0]): (str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        )
    }


def _classify_migrations(
    applied: Mapping[int, tuple[str, str]],
    migrations: tuple[Migration, ...],
) -> list[Migration]:
    """Return the packaged migrations this history has not recorded.

    Raises rather than returning a gap when the history cannot be reconciled
    with this installation at all: a version this build does not ship is
    `database_too_new`, and a recorded version whose name or checksum differs
    is `migration_checksum_mismatch`.
    """

    if set(applied) - {migration.version for migration in migrations}:
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
    return pending


def _reclassify_under_write_lock(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...],
) -> bool:
    """Re-derive the pending set with the write lock held, after a failed replay.

    Discards this connection's partial work, takes the lock, and classifies the
    committed history again. Returns True when nothing is pending any more,
    which means another writer applied these exact migrations first and there is
    no work left; the lock is still held, so the caller continues as if it had
    won the race. Returns False when work genuinely remains, and re-raises the
    accurate code when the history cannot be reconciled at all -- a mixed-version
    race whose winner is newer reports `database_too_new` rather than blaming the
    migration.

    A *partial* concurrent upgrade -- another writer applying some of several
    pending migrations -- still returns False and so still reports
    `migration_failed`. Applying the remainder here is not possible without
    releasing the lock, because `executescript` implicitly commits; retrying is a
    loop whose bound depends on other processes. The operator's next attempt sees
    the smaller pending set and succeeds.
    """

    if connection.in_transaction:
        connection.rollback()
    try:
        connection.execute("BEGIN IMMEDIATE")
        applied = _read_migration_history(connection)
    except sqlite3.Error as error:
        if _is_busy_error(error):
            raise MinervaError(
                "database_busy",
                "The database is busy; retry the operation.",
                http_status=503,
            ) from error
        return False
    return not _classify_migrations(applied, migrations)


def _is_busy_error(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", 0)
    return isinstance(code, int) and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _is_missing_database_error(error: sqlite3.Error) -> bool:
    code = getattr(error, "sqlite_errorcode", 0)
    return isinstance(code, int) and (code & 0xFF) == sqlite3.SQLITE_CANTOPEN


def _read_write_uri(path: Path) -> str:
    """Build a `mode=rw` URI that opens an existing database and never creates one.

    `Path.as_uri()` percent-encodes `?` and `#`; interpolating the path into the
    URI directly would let those characters terminate it and silently open or
    create a different file.
    """

    return Path(os.path.abspath(path)).as_uri() + "?mode=rw"


# A read path opens `mode=rw` like every other connection but sets none of the
# write-path pragmas. `mode=ro` was measured and rejected: a read-only connection
# attaches the WAL index and then cannot checkpoint or unlink `-wal`/`-shm` on
# close, leaving sidecars beside the database. The restore and backup guards
# refuse to publish over live sidecars, so read-only reads would have broken
# backup and restore to buy a guarantee the pragma change already provides.


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
    # The link created a new directory entry. Persist it before any caller
    # records the publication, so an audit row can never survive a crash that
    # the database it describes did not.
    try:
        fsync_directory(target)
    except OSError as error:
        # The public hard link is already visible. Do not unlink it here: another
        # process may have adopted that exact path, and a failed directory sync
        # cannot tell us whether the name will survive a crash. Preserve the
        # target and require the operator to inspect it before any retry.
        raise OperationalError(
            "database_publication_durability_unknown",
            "The database target may have been created, but its directory entry "
            "could not be confirmed durable. Inspect the target before retrying.",
        ) from error


def _require_backupable(
    report: DoctorReport,
    *,
    invalid_code: str = "database_invalid",
    invalid_message: str = "The database failed validation and cannot be backed up.",
) -> None:
    """Refuse a backup only for problems that make the data untrustworthy.

    Gating on the whole report conflated three different situations under one
    "failed validation" message: a genuinely corrupt database, an intact one
    whose schema is merely out of date, and an intact one with loose permissions
    or a non-WAL journal mode. Only the first is a reason to refuse a copy, and
    the second deserves a code that says what to do about it.
    """

    from minerva.core.doctor import BACKUP_ADVISORY_CHECKS

    failures = [
        check
        for check in report.checks
        if not check.ok and check.name not in BACKUP_ADVISORY_CHECKS
    ]
    if any(check.name == "schema" for check in failures):
        raise IntegrityError(
            "database_migration_required",
            "The database requires an explicit Minerva migration.",
        )
    if failures:
        raise IntegrityError(invalid_code, invalid_message)


def _require_standalone_backup(backup: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{backup}{suffix}")
        if sidecar.exists() or sidecar.is_symlink():
            raise IntegrityError(
                "backup_not_standalone",
                "The backup has live SQLite sidecars and is not a standalone artifact.",
            )


def _require_standalone_staged_restore(staged: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{staged}{suffix}")
        if sidecar.exists() or sidecar.is_symlink():
            raise IntegrityError(
                "restore_not_standalone",
                "The restored database has live SQLite sidecars and cannot be published safely.",
            )


def _require_standalone_staged_initialize(staged: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{staged}{suffix}")
        if sidecar.exists() or sidecar.is_symlink():
            raise IntegrityError(
                "database_not_standalone",
                "The new database has live SQLite sidecars and cannot be published safely.",
            )


def _reject_destination_sidecars(target: Path, *, code: str) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{target}{suffix}")
        if sidecar.exists() or sidecar.is_symlink():
            raise ConflictError(
                code,
                "Refusing to publish beside an existing SQLite sidecar.",
            )


def _remove_database_artifacts(path: Path) -> None:
    """Remove a database and its sidecars by pathname.

    Call this only from `_PrivateDatabaseFile.cleanup`, which first confirms the
    device and inode it created. Pathname removal on a public database path can
    delete a file another process published, so no caller may skip that check.
    """

    for suffix in ("", "-wal", "-shm", "-journal"):
        with suppress(OSError):
            Path(f"{path}{suffix}").unlink(missing_ok=True)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file() and not self.path.is_symlink()

    def connect(
        self,
        *,
        validate_schema: bool = True,
        read_only: bool = False,
    ) -> sqlite3.Connection:
        try:
            return self._connect(validate_schema=validate_schema, read_only=read_only)
        except sqlite3.Error as error:
            if _is_missing_database_error(error):
                raise MinervaError(
                    "database_missing",
                    "The Minerva database does not exist.",
                    http_status=503,
                ) from error
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

    def _connect(self, *, validate_schema: bool, read_only: bool = False) -> sqlite3.Connection:
        _reject_unsafe_database_path(self.path)
        connection = sqlite3.connect(
            _read_write_uri(self.path), uri=True, isolation_level=None, timeout=5.0
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA trusted_schema = OFF")
            # Without this, INSERT OR REPLACE resolves a primary-key conflict by
            # deleting the existing row without firing the BEFORE DELETE triggers
            # that make audit, snapshot, evidence, and migration rows append-only.
            connection.execute("PRAGMA recursive_triggers = ON")
            if not read_only:
                # `PRAGMA journal_mode = WAL` rewrites the database header, so it
                # belongs only on write paths. Running it on reads changed the
                # bytes — and therefore the recorded digest — of any non-WAL
                # database an operator inspected with `doctor`.
                journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
                if journal_mode.lower() != "wal":
                    raise IntegrityError(
                        "database_wal_unavailable", "SQLite WAL mode is unavailable."
                    )
                connection.execute("PRAGMA synchronous = FULL")
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
        """Open a snapshot that leaves the database's bytes untouched.

        Reads set none of the write-path pragmas, so inspecting an artifact no
        longer rewrites its journal-mode header and invalidates its recorded
        digest. See `_connect` for why the connection is not `mode=ro`.
        """

        if not self.exists():
            raise MinervaError(
                "database_missing", "The Minerva database does not exist.", http_status=503
            )
        connection = self.connect(read_only=True)
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
        on_migrate: Callable[[sqlite3.Connection, int, int], None] | None = None,
    ) -> int:
        # The unsafe-path rule dominates. `Path.exists()` follows symlinks, so
        # checking `refuse_existing` first made the same filesystem state report
        # `database_exists` or `database_symlink` depending only on a flag, and
        # the flag-dependent one misdescribed the problem: a symlinked path is
        # categorically unusable, not merely occupied.
        _reject_unsafe_database_path(self.path)
        existed_before = self.path.exists()
        if refuse_existing and existed_before:
            raise ConflictError("database_exists", "Refusing to overwrite an existing database.")
        if existed_before:
            return self._initialize_in_place(on_ready=on_ready, on_migrate=on_migrate)

        staged = _create_private_database_file(self.path)
        try:
            version = Database(staged.path)._initialize_in_place(
                on_ready=on_ready, on_migrate=on_migrate
            )
            _require_standalone_staged_initialize(staged.path)
            try:
                _publish_private_database(staged, self.path, conflict_code="database_exists")
            except ConflictError:
                if refuse_existing:
                    raise
                # Another process published first. Repeat initialization against
                # the public database so a race stays idempotent, exactly as a
                # sequential second `initialize()` already is.
                return self._initialize_in_place(on_ready=on_ready, on_migrate=on_migrate)
            return version
        finally:
            staged.cleanup()

    def _initialize_in_place(
        self,
        *,
        on_ready: Callable[[sqlite3.Connection, int], None] | None = None,
        on_migrate: Callable[[sqlite3.Connection, int, int], None] | None = None,
    ) -> int:
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
                applied = _read_migration_history(connection)

            migrations = _migration_files()
            # This classification is provisional: no write lock is held yet, and
            # none can be, because `executescript` implicitly commits and so the
            # migrations' `BEGIN IMMEDIATE` has to live inside the script. If a
            # concurrent upgrader wins the lock the replay below fails, and
            # `_reclassify_under_write_lock` derives the answer again with the
            # lock actually held.
            pending = _classify_migrations(applied, migrations)

            # Set only when this call migrates a database that already recorded
            # history. A fresh database applies every migration, but that is
            # initialization, not a migration of existing state, and `on_ready`
            # already covers it.
            migrated_from: int | None = None
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
                    if applied:
                        migrated_from = len(applied)
                else:
                    connection.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as error:
                if _is_busy_error(error):
                    raise MinervaError(
                        "database_busy",
                        "The database is busy; retry the operation.",
                        http_status=503,
                    ) from error
                # A concurrent upgrader that won the lock commits the same
                # packaged migrations while this one is still deciding, so the
                # replay fails on, for example, an already-existing table. That
                # is a benign race whose end state is the intended one, and it
                # resolves as a no-op once the pending set is derived again with
                # the lock held. Anything still outstanding is a real failure.
                if not _reclassify_under_write_lock(connection, migrations):
                    raise IntegrityError(
                        "migration_failed", "A database migration could not be applied."
                    ) from error

            _validate_migration_state(connection, require_latest=True)
            version = len(migrations)
            # The migration, its provenance callback, and the `on_ready` audit
            # callback commit in this one transaction, so a database is never
            # published with its schema advanced but the event unrecorded.
            if on_migrate is not None and migrated_from is not None:
                on_migrate(connection, migrated_from, version)
            if on_ready is not None:
                on_ready(connection, version)
            connection.commit()
            return version
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
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

    def integrity_check(self) -> tuple[bool, bool]:
        """Report page integrity and foreign-key satisfaction separately.

        Both are properties of the stored database. Doctor reports them as two
        checks so `foreign_keys` means "the recorded references resolve" rather
        than "this connection happens to have enforcement switched on", which
        was only ever a statement about the connection doctor had just opened.
        """

        with self.read() as connection:
            pages_ok = str(connection.execute("PRAGMA integrity_check").fetchone()[0]) == "ok"
            references_ok = not list(connection.execute("PRAGMA foreign_key_check"))
        return pages_ok, references_ok

    def backup_to(self, target: Path) -> None:
        _reject_unsafe_database_path(target)
        if not self.exists():
            raise MinervaError("database_missing", "The Minerva database does not exist.")

        from minerva.core.doctor import run_doctor

        _require_backupable(run_doctor(self, deep=True))

        # Reading through a write connection would force `journal_mode = WAL` and
        # rewrite the header of the database being backed up, so a backup would
        # alter its own source.
        source = self.connect(read_only=True)
        destination: sqlite3.Connection | None = None
        staged = _create_private_database_file(target)
        try:
            destination = sqlite3.connect(staged.path)
            source.backup(destination)
            destination.commit()
            destination.close()
            destination = None
            _require_backupable(
                run_doctor(Database(staged.path), deep=True),
                invalid_code="backup_invalid",
                invalid_message="The backup failed post-copy validation.",
            )
            _reject_destination_sidecars(target, code="backup_destination_sidecar_exists")
            _publish_private_database(staged, target, conflict_code="backup_exists")
        finally:
            source.close()
            if destination is not None:
                destination.close()

            staged.cleanup()

    @classmethod
    def restore_from(
        cls,
        backup: Path,
        target: Path,
        *,
        on_ready: Callable[[sqlite3.Connection, int], None] | None = None,
        on_migrate: Callable[[sqlite3.Connection, int, int], None] | None = None,
    ) -> Database:
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
            except sqlite3.Error as error:
                raise IntegrityError(
                    "backup_invalid",
                    "The backup failed integrity validation.",
                ) from error
            if result != "ok" or foreign_keys:
                raise IntegrityError(
                    "backup_invalid",
                    "The backup failed integrity validation.",
                )
            # Deliberately unwrapped: a backup taken before a schema upgrade is
            # intact, not corrupt. Since the D-11 amendment to ADR 0004 such a
            # backup is migrated on the staged copy below, so only a backup this
            # installation cannot reconcile at all -- unmanaged, newer, or
            # checksum-mismatched -- is refused here.
            _validate_migration_state(source, require_latest=False)

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
            # A pre-upgrade backup is migrated forward on the private staged
            # copy -- never the live database -- and deep validation then runs
            # on the migrated staging state, before publication (ADR 0004, D-11
            # amendment). Failure anywhere in this pipeline abandons the staged
            # copy and leaves the destination untouched.
            restored.initialize(on_ready=on_ready, on_migrate=on_migrate)
            from minerva.core.doctor import run_doctor

            report = run_doctor(restored, deep=True)
            if not report.ok:
                raise IntegrityError(
                    "backup_invalid",
                    "The restored database failed integrity validation.",
                )
            _require_standalone_backup(backup)
            _reject_destination_sidecars(target, code="restore_destination_sidecar_exists")
            _require_standalone_staged_restore(staged.path)
            _publish_private_database(staged, target, conflict_code="database_exists")
            return cls(target)
        finally:
            source.close()
            if destination is not None:
                destination.close()
            if staged is not None:
                staged.cleanup()
