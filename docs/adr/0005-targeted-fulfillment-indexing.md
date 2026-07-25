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
- The same defect exists outside fulfillment. Mission-wide brief export resolves
  run provenance with one
  `WHERE event_type = 'research.run.started' AND entity_type = ? AND entity_id = ?`
  query per distinct run (`synthesis/service.py:735-746`), each a full table scan.
  That path has no cumulative budget, so it degraded silently rather than
  refusing.

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
CREATE INDEX idx_audit_event_entity ON audit_events(event_type, entity_id);
CREATE INDEX idx_findings_claim ON findings(mission_id, claim_id, created_at, id);
```

`idx_audit_event_entity` serves both audit access paths: the snapshot
import-event lookup and the run-started branch of the scoped audit CTE both
filter on an exact `event_type` plus `entity_id`. `sequence` is deliberately not
named. It is an `INTEGER PRIMARY KEY`, so it is the rowid alias and SQLite
already stores it as every index's implicit trailing key; naming it produced
byte-identical query plans and virtual-machine step counts while making the
index about 5% larger on a 150,000-row audit table. Their `ORDER BY sequence` is
still satisfied without a temporary b-tree.

`idx_findings_claim` serves the three claim-scoped finding and reference
queries. Because SQLite ignores a better index while an `INDEXED BY` hint names
another one, the two preflight queries and the claim-scoped assembly query are
repointed to the new index in the same change.

The hints are retained, but their guarantee is narrower than it looks and should
not be overstated. `INDEXED BY` fails to prepare only when the named index does
not exist, which is what makes the index names load-bearing and makes a removed
migration fail loudly rather than silently. It does **not** guarantee a seek: if
a future edit dropped the equality predicate, SQLite would quietly fall back to
scanning that index instead of raising. The actual plan pin is therefore a test
that asserts on `EXPLAIN QUERY PLAN` output
(`test_targeted_fulfillment_indexes_are_present_and_selected`), not the hint.

The cumulative work budget, its `brief_work_limit` refusal, the storage-byte
preflight, and every other Milestone 1.3 control are unchanged. This migration
adds no table, column, trigger, constraint, or default, and rewrites no data.

## Consequences

- Fulfillment cost becomes independent of unrelated audit history. Measured on
  the real path with a single cited snapshot: 2,837 virtual-machine steps with
  no unrelated rows and 2,839 with 20,000 unrelated rows, against 242,806 for the
  same request when the audit index is absent.
- The pre-migration refusal threshold was proportional to cited snapshots.
  Independent replay of the full claim-scoped query sequence at 150,000 audit
  rows measured `6.5 * S + 6` virtual-machine steps per global audit row, where
  `S` is the number of distinct cited snapshots, giving refusal at roughly
  639,000 rows for one snapshot, 112,000 for ten, and 59,000 for twenty. After
  the migration the same replay measured an identical total at every audit-table
  size from 20,000 to 150,000 rows.
- Mission-wide brief export benefits from the same index without a code change:
  its per-run provenance lookup drops from a full scan (450,029 steps at 150,000
  audit rows) to a point lookup (34). That path is unbudgeted, so this was a
  silent slowdown rather than a refusal, and it also affects brief preview, the
  REST brief-preview endpoint, and the web brief pages.
- The work guard remains meaningful. It still refuses genuinely oversized work,
  including same-mission history that the claim-scoped audit CTE must examine
  row by row; the existing budget-exhaustion security test continues to pass
  unchanged. Measured, the post-migration budget is now reached at roughly
  118,000 *mission-scoped* audit events, because the CTE's `relevant_events`
  branch legitimately filters by `mission_id` and its `LIMIT` caps matched rows
  rather than scanned rows. That is in-scope history for the requested claim, so
  bounding it is the guard doing its job rather than a residual defect.
- Canonical output is unaffected. Every order-sensitive query on the export and
  fulfillment paths orders by a unique key or key suffix (`sequence`, `id`, or a
  primary key), so no plan change can reorder rows. The golden packet and
  request fixtures still match byte for byte, and a new test fulfils the same
  request before and after unrelated history is added and asserts identical
  bytes.
- Schema version moves from 2 to 3. Existing databases require `minerva init` to
  upgrade, and an older binary refuses a version-3 database — the existing
  fail-closed behaviour, not a new one.
- `idx_findings_claim` is load-bearing in the strong sense: it is named by
  `INDEXED BY` hints in `src/minerva/synthesis/service.py`, so dropping or
  renaming it makes those statements fail to prepare
  (`OperationalError: no such index`) rather than degrade. `idx_audit_event_entity`
  is **not** — no `INDEXED BY` clause anywhere names it, so it is planner-selected
  and dropping it silently turns the audit lookups into `SCAN audit_events` with
  no error. Both behaviours were measured directly. Only
  `test_targeted_fulfillment_indexes_are_present_and_selected` protects the audit
  index, which is why that test is the real control for both.
  A database stopped at schema 2 is refused with the typed
  `database_migration_required` before those queries run, which is pinned by
  `test_pre_index_schema_fails_closed_before_pinned_queries_run`.
- The header comment inside `0003_fulfillment_indexes.sql` overstates this, saying
  that renaming or dropping *either* index makes the queries fail to prepare. That
  is true only of `idx_findings_claim`. The comment cannot be corrected: the
  migration file's bytes are hashed into `schema_migrations.checksum`, so editing
  it — comments included — makes every database already at schema 3 or higher
  refuse to open with `migration_checksum_mismatch`. This ADR is the correction of
  record; the stale comment is left in place because the cost of fixing it is
  breaking every existing installation.
- The migration file's bytes are hashed into `schema_migrations.checksum`, so it
  must not be edited — including its comments — once it has shipped.
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
  showed the planner does choose the new indexes unaided, but the hints keep the
  chosen index explicit at the call site and make a missing migration fail at
  prepare time. They are kept for that, not as a substitute for the
  `EXPLAIN QUERY PLAN` assertion.
- **Naming `sequence` in the audit index.** Measured byte-identical plans and
  step counts with a larger index, because the column is the rowid alias.
