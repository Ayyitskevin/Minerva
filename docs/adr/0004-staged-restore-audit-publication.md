# ADR 0004: Audit restored databases before exclusive publication

- Status: Accepted
- Date: 2026-07-22
- Amended: 2026-07-25 (extended to fresh initialization; see the amendment at the
  end of this record)
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
