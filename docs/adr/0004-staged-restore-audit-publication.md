# ADR 0004: Audit restored databases before exclusive publication

- Status: Accepted
- Date: 2026-07-22
- Amended: 2026-07-25 (extended to fresh initialization) and 2026-07-30 (staged
  migration during restore, gate D-11); see the amendments at the end of this
  record
- Review: Kevin/Opus review required because this changes audit atomicity and
  restore-publication ordering

## Context

The original restore flow published the restored database and then appended its
`database.restored` audit event. If that audit transaction failed, cleanup tried to
remove the already-public database by pathname. A concurrent process could replace the
base or a SQLite sidecar between the identity check and deletion, so failure cleanup
could remove state that Minerva did not create.

Restore needs fail-closed audit semantics without treating a filesystem pathname as a
transactional extension of SQLite.

## Decision

Restore copies the verified standalone backup into an unpredictable owner-only staging
file in the destination directory. Minerva initializes that private database and runs
the supplied restore-audit callback inside the initialization transaction, before the
database has a public pathname. The callback records the run and
`database.restored` event in the restored database itself. Callback failure rolls
back the SQLite transaction; cleanup is limited to the identity-checked private
staging path and never removes a public destination.

After the audit transaction commits, Minerva performs a deep doctor check, rechecks
that the input backup remains sidecar-free, rejects any retained staging
WAL/SHM/journal, and rejects existing destination WAL/SHM/journal files without
deleting them. It then publishes the base database with a same-directory hard link
that fails if the destination exists. This exclusive publication never overwrites an
existing database.

## Consequences

- A successfully published restore already contains its run and restore audit events.
- An audit or validation failure cannot expose the staged database at the destination
  pathname and cannot trigger cleanup of a concurrently created public replacement.
- Retained staging sidecars and destination-sidecar injection fail closed. Existing
  destination sidecars remain untouched for operator inspection.
- Deep validation runs after the audit callback, so callback-induced integrity damage
  is rejected before publication.
- This does not create one atomic transaction across SQLite and the filesystem. A
  process or power failure after the staging commit but before publication can leave an
  orphan private staging file with no public restore; a failure after hard-link
  publication but before staging cleanup can leave two names for the same inode.
- POSIX offers no portable atomic operation covering the base and every SQLite
  sidecar. A same-OS-user adversary can still race the final sidecar checks or discover
  staging paths; that actor is inside the documented local trust boundary.

## Rejected alternatives

- Publish first and delete on audit failure: pathname cleanup can delete a concurrent
  replacement and makes failure recovery destructive.
- Write the audit only after publication: exposes a restored database that may never
  receive its required audit event.
- Rename over the destination: would overwrite existing state and violate Minerva's
  no-overwrite invariant.
- Delete destination sidecars before publication: sidecars may belong to another
  process or database generation and must not be treated as Minerva-owned cleanup.
- Claim cross-resource atomicity: SQLite commit and filesystem publication have no
  shared transaction coordinator in this local design.

## Amendment (2026-07-25): the same doctrine governs fresh initialization

### Context

This record fixed pathname-based failure cleanup for `restore`, but `connect()`
and `initialize()` kept it. Both snapshotted `path.exists()` and, on failure,
called `_remove_database_artifacts()`, which unlinked the base path plus
`-wal`, `-shm`, and `-journal` with no device or inode check. Three destructive
outcomes were reproduced against the shipped code:

- **Concurrent initialization destroyed a published database.** Six
  initializers racing on one fresh path ended, in six of six trials, with one
  caller reporting success and an empty directory: the losers replayed
  migration 0001 against the winner's committed database, failed with
  `migration_failed`, and unlinked the winner's file. Every migration uses bare
  `CREATE TABLE`, so the replay could not be idempotent.
- **Operator-owned sidecars were deleted.** A failed open beside a nonexistent
  database removed pre-existing `-wal`, `-shm`, and `-journal` files that
  Minerva never created — precisely what this record's rejected alternatives
  already forbade for restore.
- **A dangling operator symlink was unlinked** by the very check that rejected
  it, because `Path.exists()` follows symlinks and reported the path absent.

An identity-checked cleanup on the public path does **not** fix the first case:
the loser creates the file, the winner initializes that same inode, and the
loser's device/inode check then passes against the winner's data.

### Decision

`connect()` no longer creates a database and no longer cleans up. It opens a
`mode=rw` URI built with `Path.as_uri()` so a path containing `?` or `#` cannot
terminate the URI and address a different file, and it maps `SQLITE_CANTOPEN` to
the same `database_missing` that `read()` already raises.

`initialize()` follows this record's restore pattern. On a fresh path it stages
into an unpredictable owner-only file, runs migrations and the `on_ready` audit
callback inside that staged database's transaction, refuses retained staging
sidecars, and publishes with an exclusive same-directory hard link. Losing the
publication race is not an error when the caller did not ask to refuse an
existing database: initialization repeats against the published database, which
keeps a race as idempotent as a sequential second `initialize()` already was.

`_remove_database_artifacts` now has exactly one caller,
`_PrivateDatabaseFile.cleanup`, which verifies device and inode first.

### Consequences

- A failed open cannot remove any file. Operator sidecars, symlinks, and
  concurrently published databases all survive.
- Concurrent initialization is safe: every caller returns the same schema
  version against one surviving database.
- Mutations against a missing database now raise `database_missing` (HTTP 503)
  instead of creating a file and reporting `database_unready` (HTTP 422). This
  is an API-visible change; it matches what read paths already returned, and no
  longer leaves a stray file behind after a failed write.
- Fresh initialization briefly holds two names for one inode, and a crash
  between the staged commit and publication can leave an orphan staging file —
  the same window this record already documents for restore, with the same
  operator-visible cleanup.

### Rejected alternatives (amendment)

- **Identity-checked cleanup on the public path**: proven insufficient above.
- **`O_CREAT|O_EXCL` in place**: same flaw; the winner writes into the loser's
  inode, so the identity check passes.
- **`IF NOT EXISTS` in migrations**: hides genuine schema conflicts and does not
  stop the destructive unlink.
- **Interpolating the path into the URI**: a database named `a?b.db` silently
  opens a file named `a`.

## Amendment (2026-07-30): migrate the staged copy during restore (gate D-11)

### Context

This record's pipeline stages the backup copy, initializes it, audits,
deep-validates, and publishes exclusively — but until now the source validation
refused any backup whose recorded schema version was behind the binary's
packaged migrations. That left an asymmetric recovery gap. The documented
upgrade procedure is: verified standalone pre-upgrade backup, then `minerva
init`, then `doctor --deep`. An operator who upgraded, hit trouble, and reached
for that backup found that the *upgraded* binary refused to restore it
(`database_migration_required`), so recovery from a pre-upgrade backup required
keeping or reinstalling the prior binary — the exact binary whose retirement
was the point of the upgrade. Rolling back a version legitimately needs the
prior binary (there is no in-place downgrade), but moving *forward* from an
older backup does not: the forward-only migration chain is already the reviewed
mechanism for advancing recorded history, and this record's staging pipeline
already gives it a private, audited, deep-validated place to run.

Kevin's directive of 2026-07-30 opened gate D-11 and accepted Plan 2's
recommendation to close the gap inside this pipeline rather than beside it.

### Decision

`restore_from` validates the backup's migration state without requiring the
latest schema version. An intact backup at any older recorded version is
accepted; an unmanaged, newer, or checksum-mismatched backup is still refused
before staging with the same stable codes as before, and only genuine
corruption reports `backup_invalid`.

The staged copy — never the live database — is then migrated forward by the
same forward-only, checksum-recording migration runner that initialization
uses, inside the staging pipeline this record established. When the staged
copy's recorded history advances, a `database.migrated` audit event carrying
`from_schema_version` and `to_schema_version` is recorded in the same
transaction as the migration itself and the restore-audit callback, before
deep validation. The existing deep doctor check then runs on the *migrated*
staging state, and only a clean report proceeds to the unchanged exclusive
publication.

The audit trail this produces is provenance-correct about what happened: the
staged copy is the database that gets published, so the restored database
carries the backup's original history followed by the restore run's
`database.migrated` (from → to) and `database.restored` events, all committed
atomically with the schema change they describe. A same-version restore records
no `database.migrated` event. `minerva init` upgrades of a live database are
unchanged and record none either; the event exists only where a migration ran
inside restore.

### Consequences

- Restoring a pre-upgrade backup with the upgraded binary now succeeds and
  yields a published database at the latest schema version, with recorded
  migration history and checksums identical to any other current database.
- The live database is never migrated by restore. A failed staged migration
  reports `migration_failed`, and every failure in the pipeline — migration,
  audit callback, or deep validation — abandons the private staged copy with
  the destination and live state untouched, preserving this record's
  fail-closed semantics.
- Deep validation continues to run after all staged writes, so it now also
  covers the migrated schema: the required-trigger set and audit reconciliation
  are derived from the packaged migrations the staged copy was just advanced
  to.
- Backup policy is deliberately unchanged: `backup_to` still refuses an
  outdated live schema with `database_migration_required`, because running deep
  doctor against an older schema is not meaningful. The operator takes the
  pre-upgrade backup *before* upgrading, with the binary that is current at
  that moment; restore is the side that now tolerates the age difference.
- Rollback doctrine is unchanged. Migrations remain forward-only and recorded
  history is never rewritten; rolling back to an older version still means
  restoring the verified pre-upgrade backup with the prior binary into a new
  path. What closed is the forward direction of the same gap.

### Rejected alternatives (amendment)

- **Restore-with-prior-binary forever**: operationally fragile (the prior
  binary may be unavailable exactly when recovery is needed) and unnecessary,
  since the forward chain and the staging pipeline already exist and compose
  safely.
- **Migrate the backup file in place before staging**: mutates the operator's
  only recovery artifact and breaks the byte-stable-artifact posture; the whole
  point of staging is that nothing irreversible happens to anything public or
  operator-owned.
- **Migrate after publication**: exposes a published database at an
  unvalidated intermediate schema and repeats the publish-then-fix ordering
  this record was written to forbid.
- **A silent migration**: advancing recorded history without an audit event
  would leave the restored database's own trail unable to say when or by how
  much its schema moved — dishonesty by omission on a high-integrity surface.
