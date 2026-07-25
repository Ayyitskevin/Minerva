# ADR 0005: Add targeted indexes for claim-scoped request fulfillment

- Status: Accepted
- Date: 2026-07-25
- Review: Kevin review required because this adds migration history and changes
  the pinned query plans that bound `request fulfill` work

## Context

Milestone 1.3 bounds `minerva request fulfill` with one cumulative SQLite
virtual-machine instruction budget across its query-only snapshot. That guard is
correct, but Milestone 1.3 deliberately shipped no schema migration, so several
queries in the fulfilled path reach data that has nothing to do with the
requested claim:

- `verify_snapshot_integrity` looks up a snapshot's import event with
  `WHERE event_type = ? AND entity_id = ?`. `audit_events` carried only
  `idx_audit_mission(mission_id, sequence)`, so this scanned the whole audit
  table — every mission's history — once per distinct cited snapshot, and it runs
  twice per snapshot because the sources loop and the citation batch keep
  separate caches.
- The `research.run.started` branch of the scoped packet audit CTE joins on
  `audit_events.entity_id`, which had no index at all, and the CTE is executed
  twice per fulfillment (preflight and assembly).
- The claim-scoped finding and finding-citation queries filter
  `mission_id = ? AND claim_id = ?` but were pinned to
  `INDEXED BY idx_findings_mission`, whose key is `(mission_id, created_at, id)`.
  Every finding in the mission was visited with `claim_id` applied as a residual
  filter.

Measured on this repository's own fulfillment path, cost grew linearly with
unrelated audit history at roughly 12 virtual-machine steps per audit row for a
single-snapshot claim, and proportionally more for each additional cited
snapshot. A valid, small request therefore failed closed with `brief_work_limit`
once ordinary multi-mission history accumulated — an availability defect in the
one artifact contract a future sibling system depends on. `docs/ROADMAP.md`,
`docs/THREAT_MODEL.md`, `docs/DECISIONS.md`, and `SECURITY.md` all recorded this
as an accepted residual awaiting "a separately human-reviewed indexing
migration". This ADR is that review.

## Decision

Add forward-only migration `0003_fulfillment_indexes.sql` containing two
`CREATE INDEX` statements and nothing else:

```sql
CREATE INDEX idx_audit_event_entity ON audit_events(event_type, entity_id, sequence);
CREATE INDEX idx_findings_claim ON findings(mission_id, claim_id, created_at, id);
```

`idx_audit_event_entity` serves both audit access paths: the snapshot
import-event lookup and the run-started branch of the scoped audit CTE both
filter on an exact `event_type` plus `entity_id`, and the trailing `sequence`
column preserves their `ORDER BY sequence` without a temporary b-tree.

`idx_findings_claim` serves the three claim-scoped finding and reference
queries. Because SQLite ignores a better index while an `INDEXED BY` hint names
another one, the two preflight queries and the claim-scoped assembly query are
repointed to the new index in the same change. Those hints are retained
deliberately: they pin the plan so a budgeted read cannot silently regress to a
scan, and SQLite raises `no such index` if the migration is ever removed, which
turns a silent performance regression into a loud failure.

The cumulative work budget, its `brief_work_limit` refusal, the storage-byte
preflight, and every other Milestone 1.3 control are unchanged. This migration
adds no table, column, trigger, constraint, or default, and rewrites no data.

## Consequences

- Fulfillment cost becomes independent of unrelated audit history. Measured on
  the real path with a single cited snapshot: 2,837 virtual-machine steps with
  no unrelated rows and 2,839 with 20,000 unrelated rows, against 242,806 for the
  same request when the audit index is absent.
- The work guard remains meaningful. It still refuses genuinely oversized work,
  including same-mission history that the claim-scoped audit CTE must examine
  row by row; the existing budget-exhaustion security test continues to pass
  unchanged.
- Canonical output is unaffected. Every order-sensitive query on the export and
  fulfillment paths orders by a unique key or key suffix (`sequence`, `id`, or a
  primary key), so no plan change can reorder rows. The golden packet and
  request fixtures still match byte for byte, and a new test fulfils the same
  request before and after unrelated history is added and asserts identical
  bytes.
- Schema version moves from 2 to 3. Existing databases require `minerva init` to
  upgrade, and an older binary refuses a version-3 database — the existing
  fail-closed behaviour, not a new one.
- Both index names are now load-bearing. They are named by `INDEXED BY` hints in
  `src/minerva/synthesis/service.py`, so they cannot be renamed or dropped
  without changing those queries in the same commit.
- Index maintenance adds a small write cost to `audit_events` and `findings`
  inserts and some database growth. Both are acceptable against a read path that
  previously scanned the entire audit table several times per request.

## Rollback

Migrations are forward-only and this one is additive. To roll back an upgrade,
stop the newer process and use the older binary to restore a verified
pre-upgrade backup into a new database path, exactly as documented in `README.md`
and ADR 0004. There is no in-place downgrade, and none is required: a version-3
database differs from version 2 only by two indexes and one `schema_migrations`
row.

## Rejected alternatives

- **Leaving the deferral open.** The guard was documented as fail-closed and
  correct, but it refused valid work on ordinary databases; the documentation
  already committed to this migration.
- **Raising `MAX_REQUEST_QUERY_VM_STEPS`.** Buys proportionally more scan budget
  without removing the scans, so the cliff moves rather than disappearing, and it
  weakens the bound against genuinely oversized requests.
- **Replacing the budget with a wall-clock timeout.** Non-deterministic refusals
  under load; the instruction budget is the right instrument and indexes remove
  its false positives.
- **Indexing `finding_citations(evidence_id)`.** The reference query joins on
  `finding_id` and is already served as a covering scan of the existing
  `idx_finding_citations_finding` primary-key index; measurement showed no
  additional benefit, so the index would be write cost with no read gain.
- **A partial `findings` index `WHERE claim_id IS NOT NULL`.** Smaller, but it
  makes index selection depend on SQLite proving the partial predicate from a
  bound parameter. The full index keeps the pinned plan obvious and testable.
- **Dropping the `INDEXED BY` hints and trusting the planner.** Measurement
  showed the planner does choose the new indexes unaided, but the hints are the
  mechanism that keeps a budgeted read from regressing silently as data
  distributions change.
