# ADR 0004: Audit restored databases before exclusive publication

- Status: Accepted
- Date: 2026-07-22
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
