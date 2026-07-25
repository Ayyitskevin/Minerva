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

Phase 0 (foundation stabilization) of the plan's roadmap is **complete**.
Slices 1-5 are done and verified; slices 1-3 are merged to `main` via PR #10
and slices 4-5 are open as PR #11. No gated phase (D-1..D-11) has been
entered, and none may be until Kevin records the decision. **All ungated work
in the plan is now finished.**

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

### Slice 2 — failure cleanup must not destroy foreign state (COMPLETE, all gates green)

**User outcome.** A failed database open can no longer delete files Minerva did
not create, and concurrent `minerva init` can no longer destroy the database one
of the callers just published.

**The plan's high finding, confirmed and worse than described.** Three
destructive outcomes were reproduced against the shipped code:

| Scenario | Before | After |
| --- | --- | --- |
| Six initializers racing one fresh path | 6 of 6 trials: one caller reports success, directory left **empty** | 6 of 6: all return version 3, one database survives, no staging leftovers |
| Operator `-wal`/`-shm`/`-journal` beside a missing database | all three deleted | preserved byte for byte; open reports `database_missing` |
| Dangling operator symlink at the database path | unlinked | preserved; still rejected as `database_symlink` |

The concurrent-init loss is deterministic, not a narrow race: losers replay
migration 0001 against the winner's committed database, every migration uses bare
`CREATE TABLE`, so the replay fails with `migration_failed` and the failure
cleanup unlinks the winner's file.

**Fix.** `connect()` opens a `mode=rw` URI and neither creates nor removes
anything; `SQLITE_CANTOPEN` maps to the existing `database_missing`. Fresh
`initialize()` stages into an unpredictable owner-only file, migrates and runs
`on_ready` inside that staged transaction, refuses retained staging sidecars, and
publishes with an exclusive hard link — ADR 0004's restore pattern, now applied
to initialization. Losing the publication race repeats initialization against the
published database, preserving the documented idempotent-init contract.
`_remove_database_artifacts` is now reachable only from the device/inode-checked
staging cleanup, and says so in its docstring.

**Critically, the plan's literal fix would not have worked.** Fable proposed
`O_CREAT|O_EXCL` plus a dev/inode-checked cleanup. Verification proved that still
loses data: the loser creates the file, the winner initializes that same inode,
and the loser's identity check then passes against the winner's database. Only
staged publication fixes it.

**Files changed.** `src/minerva/core/db.py`, `tests/test_database.py` (five
regressions), `docs/adr/0004-staged-restore-audit-publication.md` (amendment),
`docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `docs/DECISIONS.md`.

**Migration status.** None. No schema change.

**Security impact.** Removes a data-loss defect. One API-visible change:
mutations against a missing database now raise `database_missing` (503) instead
of creating a file and reporting `database_unready` (422). That matches what read
paths already returned and leaves no stray file behind. `/readyz` is unaffected
(it already returned 503 for any `MinervaError`).

**Tests.** Four of the five new tests fail on the pre-fix code. The fifth,
`test_database_paths_with_uri_metacharacters_open_the_intended_file`, guards a
trap introduced *by* this fix and was verified to fail when the URI is built with
an f-string instead of `Path.as_uri()` — a database named `with?query.db` would
otherwise open a file named `with`.

**Rollback.** Pure code change, no migration; revert the commit. Databases
created by the staged path are ordinary Minerva databases indistinguishable from
ones created in place.

### Slice 3 — wave-A hardening (COMPLETE, all gates green)

Ten verified findings, each a small independent patch. No migration, no
decision gate.

| ID | Fix | Evidence it mattered |
| --- | --- | --- |
| F-DB-2 | `PRAGMA recursive_triggers = ON` per connection | `INSERT OR REPLACE` was demonstrated to rewrite a recorded migration checksum in place, skipping the BEFORE DELETE trigger |
| F-OPS-2 | Restore stops collapsing migration-state failures into `backup_invalid` | Five distinct codes were masked; an intact pre-upgrade backup was reported as failing integrity validation |
| F-OPS-3 | Backup gains restore's destination-sidecar refusal | An unusable backup was only discovered at recovery time |
| F-AI-2 | `ANTHROPIC_AUTH_TOKEN` fails closed | Version-independence across `>=0.117,<1`; **not** a live bypass — the pinned SDK ignores it when an explicit key is passed |
| F-AI-3 | OpenAI checks terminal status before refusal content | A failed response carrying a refusal item was audited as an observed refusal |
| F-SEC-1 | Packet digest-mismatch classification anchored to the root validator and matched exactly | A crafted `question_id` containing the sentence made a semantic failure report as `packet_digest_mismatch` |
| F-SEC-2 | Middleware allows only `http` and `lifespan`; websockets are closed | Non-HTTP scopes bypassed Host, Origin, and body checks |
| F-VAL-1 | `validate_text` and the evidence quote reject non-encodable UTF-8 | Surrogate argv bytes surfaced as `internal_error` exit 1 instead of a domain refusal |
| F-VAL-2 | Finding citation bound moved into the service | The bound existed only in the REST adapter, so the CLI could self-inflict a permanent export refusal |
| F-GATE-1/2 | Static gate bans `posix_spawn`, `multiprocessing`, `ProcessPoolExecutor`, `webbrowser`, `ctypes`, asyncio DNS/socket helpers; tests deny non-loopback sockets suite-wide | All six primitives passed the gate unflagged; fakes-only was upheld by convention |

**Files changed.** `src/minerva/core/db.py`, `src/minerva/core/types.py`,
`src/minerva/evidence/service.py`, `src/minerva/research/service.py`,
`src/minerva/integrations/research_packet.py`,
`src/minerva/integrations/research_packet_file.py`,
`src/minerva/integrations/ai/anthropic.py`,
`src/minerva/integrations/ai/openai.py`, `src/minerva/web/security.py`,
`scripts/static_security_check.py`, six test modules, `tests/conftest.py`,
`docs/DECISIONS.md`, `docs/THREAT_MODEL.md`.

**Migration status.** None.

**Security impact.** Closes an append-only bypass, a websocket boundary gap,
an error-classification spoof, and three enforcement gaps. The static-gate
change is review-gated. `_UNSUPPORTED_SDK_ENVIRONMENT` additions are
defence-in-depth, and the commit says so rather than overstating them.

**Tests.** 581 passing, 142 security-marked. The gate additions were verified
by running the real gate script against probe files for every newly banned
primitive, and the packet spoof test was verified to fail under the previous
substring classification.

**Rollback.** Pure code changes, no migration; each fix reverts independently.

### Slice 4 — wave-B quality (COMPLETE, all gates green)

Behaviour-preserving cleanup. No migration, no contract change, no decision
gate.

- **F-PERF-1 / F-FUL-4 — one snapshot verification per assembly.** Snapshot
  verification re-reads the blob, recomputes SHA-256, and re-checks the import
  audit event. Five call sites did that once per *citation*: the claim ledger,
  `add_finding`, finding reads, and both doctor loops each built a fresh cache,
  and synthesis verified every snapshot twice (sources loop, then citation
  batch, with separate caches). `verify_evidence_reference(s)` now accept a
  shared `snapshot_cache`, and `_assemble_brief` seeds it from the sources loop.
- **F-DUP-1 — four duplicate validators collapsed to two.**
  `_claim_status_evidence_valid` was byte-identical in the research and
  synthesis services; `_validate_page_request` existed three times (research,
  evidence, **and sources** — the third copy was not in the ledger). They now
  live once each in `research/models.py` and `core/types.py`. The packet
  verifier's independent copy of the stance rule stays independent by design,
  and the shared docstring says so.
- **F-TEST-2 — supersession workflows pinned.** Superseding a *withdrawn* card
  (the documented correction workflow) and both chain and branch shapes now
  have tests; previously nothing would have failed if a change forbade them.
- **F-PKG-1** `web/static/**/*` mirrors the templates pattern so a nested asset
  cannot be silently dropped from the wheel.
- **F-PAR-4** `/healthz` and `/readyz` build their responses through
  `HealthRead` and `ReadinessRead` instead of hand-assembling JSON beside two
  unused DTOs.
- **F-PAR-5** the identity-header denylist gained `x-remote-user`,
  `x-forwarded-user`, and `x-auth-request-user`/`-email`, so a misconfigured
  identity-injecting proxy fails loudly rather than silently.
- **F-DOC-1** milestone numbering normalized across the PRD, threat-model, and
  README titles.

**One test was updated, and it got stronger.**
`test_synthesis_batches_citation_verification_and_caches_shared_snapshots`
patched only `evidence.integrity`'s `verify_snapshot_integrity`, so the
sources-loop verification was invisible to it: the real count was two while
the test asserted one. It now patches both call sites and asserts exactly one
verification per assembly, which the previous code would fail.

**Files changed.** `src/minerva/evidence/integrity.py`,
`src/minerva/evidence/service.py`, `src/minerva/research/service.py`,
`src/minerva/research/models.py`, `src/minerva/sources/service.py`,
`src/minerva/synthesis/service.py`, `src/minerva/core/types.py`,
`src/minerva/core/doctor.py`, `src/minerva/api/routes.py`,
`src/minerva/web/app.py`, `pyproject.toml`, four test modules, three docs.

**Rollback.** Pure code and docs; no migration. Each item reverts
independently.

### Slice 5 — operator remnant notices and error-path coverage (COMPLETE, all gates green)

**User outcome.** The cleanup contracts ADR 0003 and ADR 0004 documented are now
discoverable. `doctor` names crash residue an operator had no way to find, and
never removes it.

**Notices are a separate channel from checks (ADR 0006).** They never affect
`DoctorReport.ok`, so a database with remnants still reports healthy and
`/readyz` still returns 200 — residue is housekeeping, not unreadiness.

- `staging_remnants` counts `.{name}.minerva-*.tmp` files beside the database.
  Each is a full copy of a database, hidden as a dotfile. Runs on every
  invocation, including when the database itself is missing, because residue
  outlives what it was staged for.
- `unfinished_assistance` counts invocations with a `requested` audit event and
  no other event for that invocation — the case where a provider may have
  processed and charged for a request Minerva never recorded an outcome for.
  Runs under `--deep`, grouped over rows that pass already scans, so it needs
  no index and no migration.

Notice text carries a count and never a filename: the remnant name embeds the
database filename, which the threat model keeps out of reported output.

**What doctor honestly cannot do.** Partial export and fulfillment output
directories are undiscoverable. `brief_exports` stores digests, not paths, and
`request fulfill` records nothing, so Minerva cannot know where an interrupted
write was going. ADR 0006 says so explicitly rather than shipping a check that
silently finds nothing.

**Coverage lift (F-TEST-1).** Error-injection tests for the three
lowest-covered security-relevant modules, where the uncovered branches *were*
the security contract:

| Module | Before | After |
| --- | --- | --- |
| `core/operations.py` | 66% | 96% |
| `sources/integrity.py` | 77% | 94% |
| `integrations/safe_artifact_file.py` | 73% | 83% |

New suites cover the no-follow reader's failure kinds (symlinked target and
directory component, non-regular targets, metadata and bounded-read size
refusal, changed content between the two reads, file replaced between reads,
errno mapping, and non-reflective messages), every tampered snapshot field and
malformed import-event detail, and the identity-checked backup compensation
unlink.

**Files changed.** `src/minerva/core/doctor.py`,
`docs/adr/0006-operator-remnant-notices.md` (new), `tests/test_doctor.py`,
`tests/test_safe_artifact_file.py` (new),
`tests/test_integrity_error_paths.py` (new), `README.md`, `SECURITY.md`,
`docs/DECISIONS.md`.

**Migration status.** None.

**Rollback.** Pure code, tests, and docs. `DoctorReport.notices` defaults to an
empty tuple, so reverting is safe.

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

**None that Opus may take unilaterally.** Every remaining item in Fable's plan
is behind a decision gate, so the execution phase pauses here and reports.

Awaiting Kevin (highest leverage first):

- **D-1 — persist human-adopted agent inferences.** Needs ADR 0007, because
  ADR 0003 currently promises candidates are never persisted. Today an operator
  who accepts a model draft retypes it and the link to the audited assist run
  is lost.
- **D-9 — finding retraction versus the permanent export block.** Withdrawing
  evidence cited by any finding permanently disables brief export and
  claim-scoped fulfillment for that mission, because findings are append-only
  and withdrawal is irreversible. Following the documented correction workflow
  currently bricks the milestone's core deliverable.
- **D-10** REST evidence withdrawal and the capability manifest's `.cli`
  taxonomy. **D-11** restoring a pre-upgrade backup with an upgraded binary.
- **D-2..D-8** the fleet gates: Athena authentication and transport, Icarus
  artifacts, remote access, MCP timing, retrieval/OCR, signing, and licensing.

Ungated but unscheduled ledger items, available if Kevin wants more hardening
before any gate is decided: F-OPS-5 (doctor mutates the journal-mode header of
the file it inspects), F-OPS-6 (no directory fsync after publication), F-AI-4
(KeyboardInterrupt leaves no terminal assist audit event), F-PAR-3 (web mission
list truncates at 100 with no indicator), F-SYN-1 (claim-scoped briefs omit
mission-level findings that cite the target claim), F-DUP-2 (canonical-JSON
helpers duplicated across the packet and request contracts), and F-REL-1/2
(versioning and commit-attribution conventions).

## Rollback instructions (whole phase)

Every slice is one reviewed commit on `opus/minerva-vision-implementation`
and is revertible in isolation. `main` is never pushed directly. Because
Minerva's research tables are append-only and migration 0003 is additive,
no slice rewrites research history: reverting the code and restoring a
pre-upgrade backup with the prior binary always reproduces the pre-slice
state exactly.
