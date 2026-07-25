---
repository: Ayyitskevin/Minerva
phase: OPUS_EXECUTION
plan: docs/FABLE_MINERVA_GAME_PLAN.md
plan_status_read: READY_FOR_OPUS
base_commit: b70fbdd (merge of PR #9)
branch: opus/minerva-vision-implementation
---

# Opus execution state

Durable checkpoint for the Opus implementation phase. Fable's plan
(`docs/FABLE_MINERVA_GAME_PLAN.md`) is preserved unchanged; this file
records what has actually been built, verified, and deviated from.

## Current phase

Phase 0 (foundation stabilization) of the plan's roadmap. Slice 1 is
complete and verified. No gated phase (D-1..D-11) has been entered; none
may be entered until Kevin records the decision.

## Completed slices

### Slice 1 — targeted fulfillment indexing (COMPLETE, all gates green)

**User outcome.** A valid `minerva request fulfill` no longer fails with
`brief_work_limit` because *other* missions accumulated audit history.
Fulfillment work is now independent of unrelated audit volume, and the
work budget is retained unchanged so genuinely oversized requests are
still refused.

**Scope.** Migration 0003 (two indexes), the three claim-scoped queries
that pin them, the packaging manifest, four regression tests, ADR 0005,
and the docs that recorded the deferral. Nothing else.

**Files changed.**

- `src/minerva/core/migrations/0003_fulfillment_indexes.sql` (new)
- `src/minerva/synthesis/service.py` (3 lines: `INDEXED BY` hints repointed
  at lines 622, 645, 1206)
- `scripts/verify_dist.py` (1 line: packaged-resource manifest)
- `tests/test_request_cli.py` (3 tests + 1 helper)
- `tests/test_database.py` (1 test)
- `docs/adr/0005-targeted-fulfillment-indexing.md` (new)
- `README.md`, `SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
  `docs/THREAT_MODEL.md`, `docs/DECISIONS.md`

**Migration status.** Schema version 2 → 3. Forward-only, additive,
`CREATE INDEX` only — no table, column, trigger, constraint, default, or
data change. Existing databases require `minerva init`; an older binary
refuses a version-3 database (existing fail-closed behaviour).

**Security impact.** No trust boundary changes. The cumulative
virtual-machine budget, `brief_work_limit` refusal, storage-byte
preflight, query-only snapshot, and no-mutation guarantee are all
unchanged. Two review-gated surfaces are touched and were flagged for
Kevin in the PR: migration history (AGENTS.md requires human review) and
the pinned query plans that bound fulfillment work.

**Measured evidence** (real fulfillment path, single cited snapshot,
`scratchpad/probe_cost.py`):

| unrelated audit rows | with index | audit index dropped |
| --- | --- | --- |
| 0 | 2,837 | 2,792 |
| 1,000 | 2,839 | 14,806 |
| 5,000 | 2,839 | 62,806 |
| 20,000 | 2,839 | 242,806 |

Cost was ~12 virtual-machine steps per unrelated audit row per cited
snapshot pair; it is now constant. Query plans went from
`SCAN audit_events` to `SEARCH audit_events USING INDEX
idx_audit_event_entity`, and the claim-scoped finding queries from
`SEARCH findings USING INDEX idx_findings_mission (mission_id=?)` (visiting
every mission finding) to a two-column equality seek on the new index.

An independent verification agent replayed the whole claim-scoped query
sequence at 150,000 audit rows and measured the pre-migration slope as
`6.5 * S + 6` steps per global audit row (`S` = distinct cited
snapshots): refusal at ~639,000 rows for one snapshot, ~112,000 for ten,
~59,000 for twenty. Post-migration the total was identical at every table
size from 20,000 to 150,000 rows. It also found a scan site neither the
plan nor I had listed: mission-wide brief export's per-run provenance
lookup (`synthesis/service.py:735-746`). I verified it directly —
450,029 steps to 34 — and it is fixed by the same index with no code
change, so `brief export`, `brief preview`, the REST preview endpoint,
and the web brief pages all benefit. That path is unbudgeted, so the
defect was a silent slowdown rather than a refusal.

**Acceptance tests (all passing, and all verified to fail without the
change).**

- `test_unrelated_audit_history_does_not_drive_fulfillment_work` — 5,000
  unrelated-mission audit rows, budget set between the indexed cost and
  the scan cost; fails closed if the index is dropped or deselected.
- `test_targeted_fulfillment_indexes_are_present_and_selected` — the two
  indexes exist and the audit/finding plans name them with no residual
  scan or temp-b-tree sort.
- `test_fulfilled_brief_bytes_are_unchanged_by_unrelated_history` —
  canonical output is byte-identical before and after unrelated history
  changes the plans.
- `test_pre_index_schema_fails_closed_before_pinned_queries_run` — a
  database stopped at schema 2 raises the typed
  `database_migration_required` rather than a raw `no such index` error.

Removal check performed: deleting `idx_audit_event_entity` from the
migration makes the first two tests fail; the determinism test correctly
still passes.

**Rollback.** Additive and forward-only. Stop the newer process, use the
prior binary to restore a verified pre-upgrade backup into a *new*
database path (`README.md` operations section, ADR 0004). No in-place
downgrade exists or is needed: a version-3 database differs from
version 2 only by two indexes and one `schema_migrations` row. Before
merge, the whole slice is revertible as a single commit.

**Explicitly deferred from this slice.** Every ledger wave-A fix, the
coverage lift (F-TEST-1), the doctor remnant work, and everything behind
decision gates D-1..D-11.

## Deviations from Fable's plan

Each was verified against the code before deviating; none discards the
plan's intent.

1. **Slice 1 narrowed to one vertical slice.** The plan bundled
   migration 0003 with twelve unrelated wave-A bug fixes and a coverage
   lift. Those are a different concern (correctness/security hardening
   spread across `db.py`, the provider adapters, the web middleware, the
   static gate) and do not share this slice's user outcome. They move to
   slices 2+ so each ships with its own reviewable diff and regressions.
2. **Index shape improved.** The plan proposed
   `findings(claim_id, created_at, id)`; shipped
   `findings(mission_id, claim_id, created_at, id)`. Measurement showed
   the shipped form yields a two-column equality seek for the actual
   `WHERE mission_id = ? AND claim_id = ?` predicate instead of a
   single-column seek plus residual filter, with identical row order. An
   independent verification agent reached the same conclusion.
3. **Partial index rejected.** The plan floated
   `WHERE claim_id IS NOT NULL`. Rejected so index selection never
   depends on SQLite proving a partial predicate from a bound parameter.
4. **`finding_citations(evidence_id)` not added.** The plan already
   suspected it was unnecessary; measurement confirmed the existing
   primary-key index already covers the join.
5. **F-FUL-4 (shared snapshot-verification cache) deferred to the
   wave-B quality slice.** With the audit index in place its remaining
   benefit is CPU and latency rather than false-refusal avoidance, and it
   is the same fix pattern as F-PERF-1, so the two belong in one focused
   change.
6. **One test added that the plan did not list**
   (`test_pre_index_schema_fails_closed_before_pinned_queries_run`),
   protecting the new coupling between the migration and the `INDEXED BY`
   hints.
7. **Plan quantification refined, not contradicted.** The plan's
   "~60–70k audit rows" figure holds for a claim citing ~20 snapshots.
   Measured cost is ~12 steps per unrelated audit row *per cited-snapshot
   pair*, so a single-snapshot claim tolerated ~667k rows and a
   20-snapshot claim ~63k. Both readings agree; the figure is
   snapshot-count-dependent.
8. **`sequence` dropped from the audit index.** The plan and the first
   draft of this slice used
   `audit_events(event_type, entity_id, sequence)`. `sequence` is an
   `INTEGER PRIMARY KEY`, hence the rowid alias that SQLite already
   stores as every index's implicit trailing key. Measured: identical
   query plans and identical virtual-machine step counts (33 and 30) with
   an index about 5% smaller on 150,000 rows. Shipped as
   `audit_events(event_type, entity_id)`.
9. **An overstated guarantee was corrected before merge.** The first
   draft of ADR 0005 and the migration comment claimed the `INDEXED BY`
   hints mean a budgeted read "cannot silently regress to a scan". That
   is wrong: `INDEXED BY` fails only when the named index does not
   exist; if a future edit dropped the equality predicate SQLite would
   quietly scan the named index instead. The prose now states the narrow
   guarantee and points at
   `test_targeted_fulfillment_indexes_are_present_and_selected` as the
   actual plan pin.

## Verification evidence

All eleven AGENTS.md gates were run at the slice-1 tree and passed:

| Gate | Result |
| --- | --- |
| `uv sync --frozen --extra dev` | PASS (41 packages audited, no drift) |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS (72 files) |
| `uv run mypy` | PASS (strict, 51 source files) |
| `uv run pytest` | PASS (551 passed; branch coverage 89.04% ≥ 85 floor) |
| `uv run python -m build` | PASS (sdist + wheel) |
| `uv run python scripts/verify_dist.py dist` | PASS |
| `uv run python scripts/installed_smoke.py dist` | PASS |
| `uv run python scripts/static_security_check.py` | PASS (49 files) |
| `uv pip check` | PASS |
| `git diff --check` | PASS |

Golden fixtures (`minerva.research-brief.v2.golden.json`,
`minerva.research-request.v1.golden.json`) still match byte for byte,
which is the strongest available determinism evidence: they were
generated before migration 0003 and are asserted after it.

## Tests unavailable (open verification, not passes)

- **Python 3.13 / 3.14** — this environment runs 3.12.3 only. CI covers
  the matrix on push.
- **Live provider behaviour** — never exercised, by contract. Provider
  evidence is from fakes and code reading only.
- **Non-Linux platforms** — outside the supported boundary.
- **Real-corpus scale** — measurements use synthetic databases with tied
  timestamps (the worst case for ordering stability, deliberately). The
  8,000,000-step budget's headroom on a real corpus is not measured.

## Known residual (documented, not fixed)

Same-mission audit history still consumes budget: the scoped packet audit
CTE's `relevant_events` branch legitimately filters by `mission_id` and
examines those rows individually, so `idx_audit_event_entity` does not
apply to it. Measured, the budget is now reached at roughly 118,000
mission-scoped audit events, and the branch's `LIMIT` caps matched rows
rather than scanned rows, so a large mission with few claim-relevant
events still pays for the pass. This is correct behaviour — that history
is in scope for the requested claim — and the existing budget-exhaustion
security test still exercises it. `SECURITY.md` and
`docs/THREAT_MODEL.md` state this explicitly.

Observation for a later slice, not a defect: the claim-scoped source
preflight query (`synthesis/service.py:570`) orders by
`snapshot.imported_at, snapshot.id`, which is total for real rows but
would tie if the LEFT JOIN produced NULLs. Those rows raise
`snapshot_tampered` before any accumulation and the query's results feed
only order-independent sums, so canonical output cannot be affected.

## Blockers

None. Slice 1 required no human decision.

## Next task

**Slice 2 — F-DB-1, the plan's single confirmed high finding.**
`Database.connect()` and `Database.initialize()` clean up failures with
`_remove_database_artifacts()`, which unlinks the base path plus
`-wal/-shm/-journal` by pathname with no device/inode identity check
(`src/minerva/core/db.py:244-267, 429-435`). This can delete a database a
concurrent process just committed, an operator's dangling symlink, or
stale sidecars Minerva never created — the pattern class ADR 0004
eliminated for restore but never applied to the fresh-database path.

Planned approach (to be verified before coding): open non-initializing
connections with a `file:{path}?mode=rw` URI so they never create a file
and never need cleanup; for `initialize()` on a fresh path, establish
creation ownership (`O_CREAT|O_EXCL` or an immediate dev/inode capture)
and restrict cleanup to that identity-verified inode; never unlink
sidecars this process did not create. Ships with an ADR 0004 amendment
note and a regression test mirroring
`test_database_cleanup_preserves_concurrent_replacements`. This touches a
review-gated surface and must be flagged for Kevin.

Then slice 3 (remaining wave-A hardening), slice 4 (wave B quality plus
F-FUL-4/F-PERF-1), slice 5 (doctor remnants, ADR 0006). Stop after the
wave-B slice unless a decision gate has been recorded.

## Rollback instructions (whole phase)

Every slice is one reviewed commit on `opus/minerva-vision-implementation`
and is revertible in isolation. `main` is never pushed directly. Because
Minerva's research tables are append-only and migration 0003 is additive,
no slice rewrites research history: reverting the code and restoring a
pre-upgrade backup with the prior binary always reproduces the pre-slice
state exactly.
