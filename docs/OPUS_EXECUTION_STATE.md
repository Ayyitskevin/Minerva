---
repository: Ayyitskevin/Minerva
phase: OPUS_EXECUTION
plan: docs/FABLE_MINERVA_GAME_PLAN_2.md
plan_status_read: READY_FOR_OPUS
base_commit: 8bb2abc (merge of PR #14)
branch: opus/minerva-vision-implementation
---

# Opus execution state

Durable checkpoint for the Opus implementation phase. Fable's plans
(`docs/FABLE_MINERVA_GAME_PLAN.md`, superseded by
`docs/FABLE_MINERVA_GAME_PLAN_2.md`) are preserved unchanged; this file
records what has actually been built, verified, and deviated from.

## Current phase

**Plan 1 Phase 0 is complete and merged** (PRs #10, #11, #12). Slice 6
answered decision gate **D-9**, the first gate Kevin recorded.

**Plan 2 Phase 0C is in progress.** Plan 2 (base commit `b26268c`,
merged as PRs #13/#14) re-verified every load-bearing claim below against
the code and re-ran all eleven gates before trusting any of it: all
claims held, all gates passed. It also found eleven defects that survived
adversarial verification, two of them high, and both highs were
consequences of D-9 landing in the database but not on the reading
surfaces. Slice 7 closes exactly those two.

No decision gate beyond D-9 has been entered; none may be until Kevin
records it.

## Corrections to earlier entries in this file

Plan 2's verification sweep found this file substantively accurate — all
twelve load-bearing claims below verified against the code — with the
following drift, corrected here rather than silently edited in place:

- **Line references moved.** The `INDEXED BY` hints recorded as
  `synthesis/service.py:622, 645, 1206` are at 630, 653, 1216 on `main`,
  shifted by slice 6's retraction clauses. The mission-wide provenance
  lookup cited as `:735-746` is near 733-753; the source-preflight
  `ORDER BY` cited as `:570` is at 578.
- **Counts are historical snapshots.** "581 passing, 142 security-marked"
  and the gate table's "551 passed" were true when written. `main` after
  slice 7 collects **635 tests, 177 security-marked, 90.18% branch
  coverage**.
- **Two statements were loose, not wrong.** The index test's "no residual
  scan or temp-b-tree sort" applies the no-scan assertion only to the
  audit plan and the no-temp-b-tree assertion only to the findings plan;
  and because the findings query forces its index with `INDEXED BY`, free
  planner selection is genuinely asserted only for
  `idx_audit_event_entity`. `PRAGMA recursive_triggers = ON` is set on
  every connection that executes application SQL, but not on the
  ancillary backup/restore page-copy connections, which issue no DML.

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

### Slice 6 — finding retraction (decision gate D-9 answered, COMPLETE)

**Kevin decided D-9 by taking the recommendation: option (a), a labeled
append-only retraction record.**

**Reproduced first.** Following the documented correction workflow — record a
finding, later withdraw the evidence it cites — refused `build_brief` with
`citation_withdrawn` and left `doctor --deep` reporting a standing
`finding_integrity` failure, with no recovery: findings, finding citations, and
withdrawals are all append-only and nothing could express "no longer asserted".

**Fix.** Migration 0004 adds `finding_retractions`, mirroring
`evidence_withdrawals` exactly. `ResearchService.retract_finding` writes it plus
a `research.finding.retracted` audit event in one transaction;
`minerva finding retract` exposes it, CLI-only like `evidence withdraw`. A
retracted finding leaves the mission-wide and claim-scoped assembly queries, its
uncertainty entry, the packet's audit references, and the deep-doctor finding
check — and is never deleted.

**Second defect fixed with it (F-WDR-2).** The withdrawn-citation refusal ran
before the statement-kind branch, so an assumption or unresolved question with an
*optional* citation also blocked export. PRD invariant 8 governs material
findings only, so the check is now gated on `kind.requires_citation` in the
service, the packet verifier, and doctor. The citation stays in the packet marked
`withdrawn: true`, so the state is visible rather than the document refused.

**Verified end to end:** export refused after withdrawal; after retraction the
brief exports again with the retracted finding and its uncertainty absent, the
assumption retained, doctor healthy, and the database still holding both findings
plus the retraction record.

**`minerva.research-brief.v2` is unchanged.** A retracted finding is absent from
the packet rather than flagged inside it, so no schema version, canonical byte
layout, or golden fixture moves. Carrying retraction history in the packet is
recorded in ADR 0007 as the closest rejected alternative and a future v3
question — it would change the contract ADR 0002 froze, and no consumer needs it
yet.

**Files changed.** `src/minerva/core/migrations/0004_finding_retractions.sql`
(new), `src/minerva/research/service.py`, `src/minerva/synthesis/service.py`,
`src/minerva/core/doctor.py`, `src/minerva/integrations/research_packet.py`,
`src/minerva/cli/main.py`, `scripts/verify_dist.py`,
`docs/adr/0007-finding-retraction.md` (new), `tests/test_research.py`, and the
PRD, ROADMAP, DECISIONS, and README.

**Migration status.** Schema 3 → 4. Forward-only and additive: one table, one
index, two triggers; no existing table, column, trigger, or row changes.

**Rollback.** Restore a verified pre-upgrade backup with the prior binary, the
standard documented procedure. Retraction is additive, so a version-3 database
differs only by the new table and one `schema_migrations` row.

### Slice 7 — retraction visibility and verification (plan 2, issues 1-2, COMPLETE)

**User outcome.** A retracted finding is now visibly retracted everywhere a
human or agent reads it, and `doctor` can no longer be fooled about the
retraction records themselves.

**Both defects were reproduced first, then re-run against the fix.**

| Finding | Before | After |
| --- | --- | --- |
| F2-RES-1 (high) | `list_findings` returns a retracted finding as `status=supported, citation=active` with no retraction field; REST and web render it identically to an asserted one | `retracted=True` with reason, timestamp, and actor on service, pagination, REST, and a RETRACTED badge on the web page |
| F2-CORE-1 (high) | drop both 0004 triggers, `UPDATE` then `DELETE` the retraction row → `doctor --deep` returns `ok=True` on 11/11 checks while the finding silently returns to synthesis | same sequence fails **two** independent checks: `append_only_triggers` and `material_audit_integrity` |

The F2-CORE-1 control matters: dropping a *registered* trigger
(`findings_no_update`) was always caught, so the gap was specific to the
unregistered migration-0004 triggers rather than a broken checker.

**Fix.** `Finding` and `FindingRead` gained `retracted`,
`retraction_reason`, `retracted_at`, `retracted_by`, mirroring the
withdrawal fields on `LedgerEntry`. Findings are read through one left
join on the mission-composite key — `finding_retractions.finding_id` is
UNIQUE, so it cannot multiply rows or disturb cursor pagination. Doctor
now derives its required-trigger set from the packaged migrations, so a
future migration's triggers become required the moment it ships, and
reconciles every retraction row against its `research.finding.retracted`
audit event exactly as it already did for withdrawals.

**Files changed.** `src/minerva/research/models.py`,
`src/minerva/research/service.py`, `src/minerva/api/models.py`,
`src/minerva/core/doctor.py`,
`src/minerva/web/templates/mission_detail.html`,
`tests/test_research.py`, `tests/test_doctor.py`, `tests/test_api.py`,
`tests/test_web.py`, `README.md`, `docs/PRD.md`, `docs/DECISIONS.md`.

**Migration status.** None. No schema change; `finding_retractions` was
already correct — only its verification and its visibility were missing.

**Security impact.** Closes an integrity-verification bypass (doctor
reporting a tampered database healthy) and a false-certainty surface (a
retracted statement reading as asserted). No contract weakened; the frozen
`minerva.research-brief.v2` packet is untouched, and synthesis behaviour is
unchanged.

**Tests.** Six of the seven new tests were verified to fail on the pre-fix
source by stashing only `src/minerva` and re-running. The seventh
(`test_finding_pagination_still_advances_across_the_retraction_join`)
passes both before and after by design: it guards against the new join
*breaking* pagination, so it is a guard rather than a defect witness, and
this is stated rather than counted as a failing-first regression.

**Known residual, disclosed.** Editing only a retraction's `reason` text
is not detectable by audit reconciliation, because the audit event carries
the retraction id rather than the reason — the same shape as
`evidence.card.withdrawn`. The defence is the append-only trigger, which
doctor now requires and fingerprints, so the edit cannot happen without
first dropping a trigger doctor reports.

**Rollback.** Pure code, tests, and docs; no migration. The read-model
fields default to the non-retracted values, so reverting is safe.

### Slice 8 — index-pinning claims corrected (plan 2, issue 3, COMPLETE)

**User outcome.** Four documents described a security control Minerva does not
have. They now describe the one it does.

**Measured before writing, on a fresh connection per statement** so no cached
plan could mislead (the first probe did use one connection and reported a
dropped index still in use — a statement-cache artifact, discarded):

| Query | Index present | Index dropped |
| --- | --- | --- |
| audit lookup (no hint in product code) | `SEARCH audit_events USING INDEX idx_audit_event_entity` | `SCAN audit_events`, **no error** |
| claim-scoped findings (`INDEXED BY idx_findings_claim`) | `SEARCH findings USING COVERING INDEX` | raises `OperationalError: no such index` |
| findings with the hint but no equality predicate | `SCAN findings USING COVERING INDEX ... USE TEMP B-TREE FOR ORDER BY`, **no error** | — |

So `INDEXED BY` gives a loud failure only for the index it names, and never
forces a seek. ADR 0005's decision section already said this correctly;
THREAT_MODEL.md:27, ARCHITECTURE.md:251-256, ROADMAP.md:91-92, and ADR 0005's
own consequences bullet contradicted it. All four are corrected, and each now
names `test_targeted_fulfillment_indexes_are_present_and_selected` as the real
control.

**Deviation from the plan, with evidence.** Plan 2 issue 3 listed migration
0003's header comment among the places to fix. **It must not be touched.**
`schema_migrations.checksum` is `sha256` over the entire migration file,
comments included: editing the comment changes the digest from `4622fe79...`
to `09d38ed6...`, and every database already at schema 3 or higher would then
refuse to open with `migration_checksum_mismatch`. Measured directly against a
real initialized database. The stale comment stays; ADR 0005 carries the
correction of record and states why the comment cannot be fixed. `git status`
on `src/minerva/core/migrations/` was verified empty before commit.

**New regression.** `test_index_protection_is_only_what_the_documents_now_claim`
pins both halves: dropping the audit index must degrade to a scan, and dropping
the hinted findings index must raise `no such index`. If a future change adds a
hint for the audit index, the test fails and the documents must move with it.

**Files changed.** `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
`docs/THREAT_MODEL.md`, `docs/adr/0005-targeted-fulfillment-indexing.md`,
`docs/DECISIONS.md`, `tests/test_request_cli.py`. No product code, no
migration.

**Migration status.** None, deliberately — see the deviation above.

**Security impact.** Retires a false security claim. The control itself is
unchanged; only its description is now accurate, and the residual (a silently
droppable audit index guarded solely by a test) is stated rather than hidden.

**Rollback.** Docs and one test; revert the commit.

### Slice 9 — reads no longer alter what they read (plan 2, issue 4, COMPLETE)

**User outcome.** `minerva doctor` no longer changes the bytes of the database
it inspects, so a recorded artifact digest still matches after a health check.

**Reproduced, then re-run against the fix.** A standalone delete-journal
artifact: SHA-256 before `doctor` and after differed (`f26dacd5...` →
`6e8b338b...`), journal mode converted `delete` → `wal`. After: byte-identical,
mode unchanged, no sidecars left behind.

**Deviation from the plan, with measurements.** Plan 2 issue 4 prescribed
opening doctor and `read()` with `mode=ro`. **That fix breaks backup and
restore.** A read-only connection attaches the WAL index and then cannot
checkpoint or unlink `-wal`/`-shm` on close, so it leaves sidecars beside the
database; the restore and backup publication guards refuse to publish over live
sidecars. Measured: with `mode=ro`, seven tests failed, all in the
backup/restore family. The mutation came from `PRAGMA journal_mode = WAL`, not
from the open mode, so the write-path pragmas now run only on write paths and
the connection stays `mode=rw`. `read()` and `_connect` both carry a comment
saying why, so the rejected approach is not re-introduced as an improvement.

**Second half of the finding also fixed.** Doctor's `wal` and `foreign_keys`
checks were tautological — both reported state `_connect` had just set.
`wal` now reports the journal mode stored in the file.
`Database.integrity_check` returns page integrity and foreign-key satisfaction
separately, so `foreign_keys` means "the recorded references resolve" rather
than "this connection has enforcement on". Both pragmas were already run; only
one was reported.

**One test double updated, not weakened.**
`test_claim_scoped_audit_query_does_not_materialize_unrelated_mission_rows`
stubs `Database.connect`; its signature gained `read_only` and now forwards it.
What the test measures — the count of audit rows returned to Python — is
unchanged.

**Files changed.** `src/minerva/core/db.py`, `src/minerva/core/doctor.py`,
`tests/test_doctor.py`, `tests/test_request_cli.py`, `docs/DECISIONS.md`.

**Migration status.** None.

**Security impact.** Restores byte-stable artifact provenance across
inspection, and converts two theatrical checks into real ones. No guard
weakened — the `mode=ro` variant that would have weakened one was rejected on
measurement.

**Tests.** The new regression
(`test_doctor_leaves_the_bytes_of_what_it_inspects_unchanged`, security-marked)
was verified to fail on the pre-fix source with "doctor rewrote the database it
was asked to inspect". 637 tests, 90.21% branch coverage.

**Rollback.** Pure code and tests; revert the commit.

### Slice 10 — publication durability (plan 2, issue 5, COMPLETE)

**User outcome.** A file Minerva reports as published survives a crash that
immediately follows the report.

**The gap.** Publishing makes a file's *contents* durable but not the directory
entry naming it. There was exactly one `fsync` in the whole source tree (the
export file descriptor in `synthesis/service.py`) and none in `core/`, so a
crash right after a successful `minerva backup` could leave a committed
`database.backup.created` audit row describing a file that no longer existed.

**Fix.** `minerva/core/durability.py` (new) provides `fsync_directory`, called
from `_publish_private_database` — one place, covering initialization, backup,
and restore, so the guarantee is structural rather than something each new
caller must remember. The two export paths sync their already-open directory
descriptor directly.

**Ordering is the substance of the fix.** The directory is synced *before* the
operation records that it happened: before the `brief_exports` transaction on
export, before returning success on fulfillment, before any caller of
`_publish_private_database` audits the publication. The regressions assert that
ordering, not merely that an fsync occurred.

**Tests.** Three new security-marked regressions, all verified to fail on the
pre-fix source:

| Test | Pre-fix failure |
| --- | --- |
| `test_export_persists_directory_entries_before_recording_the_export` | `the output directory was never fsynced` / `assert 'fsync_directory' in ['record_export']` |
| `test_fulfillment_persists_directory_entries_before_reporting_success` | `assert 0 == 1` |
| `test_publication_persists_the_new_directory_entry` | `fresh initialization did not persist its directory entry` |

640 tests, 90.23% branch coverage, 181 security-marked. The static gate now
scans 50 files.

**Honest limit, stated in SECURITY.md and DECISIONS.md.** This was verified
structurally, not by simulating power loss — the same caveat plan 2 section 28
recorded for the original finding. The tests prove the sync happens and happens
before success is recorded; they do not prove behaviour across a real crash.
SECURITY.md states what is still not covered: no multi-file export atomicity,
nothing about SQLite's own write path (`synchronous = FULL` is SQLite's
contract), and no defence against hardware that acknowledges `fsync` without
persisting.

**`fsync` failures propagate** rather than being suppressed: a filesystem that
cannot sync a directory cannot support the durability the operation is about to
claim.

**Files changed.** `src/minerva/core/durability.py` (new),
`src/minerva/core/db.py`, `src/minerva/synthesis/service.py`,
`tests/test_database.py`, `tests/test_synthesis.py`, `SECURITY.md`,
`docs/DECISIONS.md`.

**Migration status.** None.

**Rollback.** Pure code, tests, and docs; revert the commit.

### Slice 11 — backup refuses only what it should (plan 2, issue 6, COMPLETE)

**User outcome.** An intact database can be backed up, and a refusal says what
is actually wrong.

**Reproduced first, and wider than the finding described.** `backup_to` gated
on the whole `DoctorReport`, so one message covered three situations:

| Source database | Before | After |
| --- | --- | --- |
| intact, schema 3 (the pre-upgrade state) | `database_invalid` "failed validation" | `database_migration_required` |
| intact, group-readable (0644) | `database_invalid` | backs up; `doctor` still reports the permissions |
| intact, delete-journal | `database_invalid` | backs up; source left byte-identical |
| dropped `audit_no_update` trigger | `database_invalid` | `database_invalid` (unchanged) |

`restore_from` already distinguished the outdated-schema case, so this was the
Phase 0 wave-A masking fix (F-OPS-2) surviving in the sibling path.

**Slice 9 regression found and repaired.** Making doctor report the real
journal mode meant a delete-journal database started failing the `wal` check,
which `backup_to` turned into `database_invalid`. Before slice 9 that database
was silently converted to WAL and backed up. Neither behaviour was right;
recorded in DECISIONS rather than quietly folded in.

**Second defect found while fixing it.** `backup_to` read its source through a
write connection, so copying a delete-journal database rewrote that database's
header. It now reads through the same non-mutating connection every other read
path uses, and a regression asserts the source is byte-identical afterwards.

**Design.** `doctor.BACKUP_ADVISORY_CHECKS = {"permissions", "wal"}` names the
checks that describe configuration rather than trustworthy data; everything
else blocks, so a future check fails closed until someone decides otherwise.
`_require_backupable` applies it to both the pre-copy and post-copy reports.

**Scope held.** Permitting an outdated database to be backed up outright would
be more useful, but deep doctor is not meaningful against an older schema (the
required-trigger set is derived from the packaged migrations, so a schema-3
database legitimately lacks migration 0004's triggers), and a weaker "raw copy"
validation tier belongs with decision gate **D-11**. The honest refusal ships
now; the capability stays gated.

**Tests.** Five new regressions; four verified to fail on the pre-fix source.
The fifth (`test_backup_still_refuses_a_database_whose_data_cannot_be_trusted`)
passes before and after by design — it guards the relaxation from going too
far, so it is a guard rather than a defect witness.

**Files changed.** `src/minerva/core/db.py`, `src/minerva/core/doctor.py`,
`tests/test_database.py`, `docs/DECISIONS.md`.

**Migration status.** None.

**Security impact.** No integrity check weakened — the advisory allowlist has
exactly two members, both configuration, and the blocking default is
fail-closed. Removes a false corruption report and stops a backup from
mutating its source.

**Rollback.** Pure code and tests; revert the commit.

### Slice 12 — oversized is a work limit, never tampering (plan 2, issue 7, COMPLETE)

**User outcome.** A mission that is merely too large to export says so, instead
of reporting that its data failed integrity validation.

**Reproduced first.** 215 evidence cards quoting the same 99,001-byte range —
21,285,215 bytes of quote text against 99,002 bytes of snapshot:

| | Before | After |
| --- | --- | --- |
| mission-wide `build_brief` | `packet_integrity_invalid` "Research packet integrity validation failed." | `brief_work_limit` "The research brief exceeds synthesis limits." |

The mission-wide preflight bounded record counts, reference counts, and
snapshot bytes but never emitted text, unlike the claim-scoped branch. Record
and snapshot counts do not bound emitted text: one quote may be 100,000 bytes
and many cards may quote the same small snapshot. The oversize therefore
surfaced only at serialization, where a blanket `except ValueError` classified
it as tampering — and wedged mission-wide export permanently.

**Fix.** Mission-scoped materialized-text accounting in the mission-wide
branch, refusing with `brief_work_limit` before any snapshot BLOB is
materialized. `ResearchPacketTooLargeError` (a `ValueError` subclass, so every
consumer-side handler is unaffected) lets the producer distinguish "too large"
from "malformed"; the serializer guard stays as a backstop and now also maps to
`brief_work_limit`.

**The accounting is a deliberate lower bound.** It sums the unbounded free-text
columns and ignores identifiers, timestamps, and JSON structure, so it can only
refuse a mission whose output genuinely exceeds the cap — never one that would
have fit. The existing
`test_claim_materialization_lower_bound_never_exceeds_canonical_json` guards
that property for the claim-scoped side and still passes.

**Incidental deduplication.** The UTF-8/UTF-16 storage factor was spelled out
in the claim-scoped branch only; it is now one shared helper
(`_storage_bytes_per_output_byte`) so the two branches cannot drift on it.

**Tests.** Two new security-marked regressions, both verified to fail on the
pre-fix source (`snapshot BLOB materialized after the preflight should have
refused`, and `module ... has no attribute 'ResearchPacketTooLargeError'`).
647 tests, 90.28% branch coverage, 184 security-marked.

**One test-authoring correction worth recording.** The first draft patched
`synthesis_module.MAX_EXPORT_BYTES`, which does nothing: `max_export_bytes` is a
constructor default captured when the service is built, so the fixture's
instance had already bound the old value. The test now constructs its own
`SynthesisService` with the small cap, which is what actually exercises the
path.

**Files changed.** `src/minerva/synthesis/service.py`,
`src/minerva/integrations/research_packet.py`, `tests/test_synthesis.py`,
`docs/DECISIONS.md`.

**Migration status.** None.

**Security impact.** Removes a false tamper report and closes a permanent
availability failure. No limit relaxed — `MAX_EXPORT_BYTES`,
`MAX_RESEARCH_PACKET_BYTES`, and every count bound are unchanged; the refusal
simply happens earlier and under an honest code.

**Rollback.** Pure code and tests; revert the commit.

### Slice 13 — the claim-scoped boundary is documented, not changed (plan 2, issue 8, COMPLETE)

**Outcome.** The behaviour that reads like a bug is now stated where a reader
looks, pinned by a test, and its alternative recorded with the reason it was
rejected. No product behaviour changed.

**Reproduced.** A mission-level finding (`claim_id` NULL) citing the target
claim's own evidence, plus a mission-level unresolved question:

| | mission-wide | claim-scoped |
| --- | --- | --- |
| findings | 2 | 1 |
| unresolved questions | 1 | 0 |
| uncertainties | 2 | 1 |
| the cited card | present | **present** |

So the packet carries an evidence card while carrying nothing that rests on it,
and the empty arrays are indistinguishable from "this mission recorded none".

**Why this is documentation rather than a fix.** ADR 0002 already says a
claim-scoped packet retains the closure the canonical verifier requires and that
"unrelated mission entities are omitted"; PRD invariant 16 already says the
packet carries no selection marker, with the request/result binding supplying
that meaning. The rule existed; it just was not stated precisely enough for the
behaviour to look intentional.

**Inclusion was rejected on a technical blocker, not on taste.**
`_validate_findings` requires every finding's citations to be present in the
packet. A mission-level finding may cite cards from several claims, so including
it would force those other claims' cards into a claim-scoped packet —
contradicting "unrelated mission entities are omitted" and dragging the packet
toward mission-wide. Restricting inclusion to findings whose citations lie
entirely inside the target ledger would still silently drop the rest, moving the
ambiguity rather than removing it. Recorded as a v3 question on the same terms
as ADR 0007's retraction-in-packet deferral: it needs a consumer and a selection
rule that survives citation closure.

**No decision gate was needed.** Documenting the boundary does not touch the
frozen `research-brief.v2` contract; only the inclusion option would have, and
that option is deferred rather than taken.

**Files changed.** `docs/PRD.md` (invariant 16), `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, `tests/test_synthesis.py`. No product code.

**Tests.** `test_claim_scoped_packet_omits_mission_level_statements_by_design`
pins the boundary in both directions. This is a pin, not a defect witness —
there is no pre-fix source to fail against, because nothing was broken.
648 tests, 90.28% branch coverage.

**Migration status.** None. **Rollback.** Docs and one test.

### Slice 14 — the review surface says what it is showing (plan 2, issue 9, COMPLETE)

**User outcome.** A reviewer can tell whether the mission list is the whole set.

**Reproduced, then re-run against the fix** (105 missions seeded):

| | Before | After |
| --- | --- | --- |
| cards rendered | 100 | 100 |
| "Mission 104" visible | no | no |
| says "Showing the first" | **no** | yes |
| says "More exist than this page displays" | **no** | yes |
| names a paging surface | **no** | yes |

**Fix.** `/missions` uses `page_missions`, which fetches one extra row and
reports whether it existed, so "more exist" is exact. A `len(missions) == limit`
heuristic would have claimed more missions existed whenever a count landed
exactly on the page size — a surface built to stop overstating completeness must
not start overstating truncation instead, and the second regression pins that.

**Single-page on purpose.** Cursor navigation would mean coupling the review
surface to the REST layer's cursor encoding or growing a second one, and this is
a deliberately restrained GET-only surface. What it owed the reviewer was
honesty about the cap, not navigation; the banner names `minerva mission list`
and `/api/v1/missions` as the surfaces that page, so nothing is unreachable.

**A weak test caught and strengthened.** Both new tests failed on the pre-fix
source only with `AttributeError: module has no attribute
'WEB_MISSION_PAGE_SIZE'` — a missing-symbol failure that proves nothing about
behaviour. The behavioural before/after above was measured separately against
pre-fix source with the constant inlined, which is what actually establishes the
defect. A first attempt at that probe also mis-reported (its indicator check
included the substring "page", which matches page chrome and returned true in
both directions); tightened to the exact banner strings.

**Files changed.** `src/minerva/web/app.py`,
`src/minerva/web/templates/missions.html`, `src/minerva/web/static/style.css`,
`tests/test_web.py`, `docs/DECISIONS.md`.

**Migration status.** None. **Security impact.** No boundary moved; the route
still reads through the shared service, and the page remains GET-only.
650 tests, 90.28% branch coverage.

**Rollback.** Pure code, template, and tests; revert the commit.

### Slice 15 — the suite delivers what it claims (plan 2, issue 10, COMPLETE)

**User outcome.** Three guards that were weaker than their own descriptions now
match them, and the security gate's detection branches are held to the coverage
floor.

**Reproduced against the real fixture and script, then re-run after:**

| | Before | After |
| --- | --- | --- |
| `socket.connect` to 127.0.0.2 | blocked | blocked |
| `socket.connect_ex` | **reached the OS silently** | blocked |
| UDP `sendto` | **delivered its bytes silently** | blocked |
| `socket.create_connection` | blocked | blocked |
| `runner = os.system` | MIN002 | MIN002 |
| `(runner,) = (os.system,)` | **evaded** | MIN002 |
| `[runner] = [os.system]` | **evaded** | MIN002 |
| `first, runner = 1, os.system` | **evaded** | MIN002 |
| `*rest, runner = [1, os.system]` | **evaded** | MIN002 |

**Scope decision on the starred form.** The first implementation deliberately
refused to pair past a star and left that case evading. That was a real hole I
was about to document instead of close, so it was reworked:
`_unpacked_bindings` pairs names before the star from the front and names after
it from the back, which is exact for a literal sequence. Where pairing is not
knowable it binds `None`, clearing the name rather than guessing — a wrong alias
would be worse than none, because it could flag innocent code.

**MIN003 witnesses are new coverage, not a fix.** The dynamic-code-execution
rule already worked; it had simply never been tested, so it was enforced only by
the tool running clean over a repository that happens not to call `eval`. Those
four cases pass on the pre-fix source, and this is stated rather than counted as
a regression.

**Coverage scoping, and why it is not the whole tree.**
`scripts/static_security_check.py` joins the floor because it enforces
threat-model prohibitions. `verify_dist.py` and `installed_smoke.py` are omitted
deliberately: both are exercised end to end by their own gate commands against a
built distribution, so pytest coverage of them measures how little pytest calls
them, not how well they are tested. Including all of `scripts/` unfiltered put
the total at exactly 85.0% — flush against the floor, which would have made the
gate flap on any small change.

**Tests.** Six of the new cases were verified to fail on the pre-fix source
(four alias forms, `connect_ex`, `sendto`). 663 tests, 89.93% branch coverage
over the widened source set, 197 security-marked.

**Files changed.** `tests/conftest.py`, `scripts/static_security_check.py`,
`tests/test_gate_scripts.py`, `pyproject.toml`, `docs/DECISIONS.md`.

**Migration status.** None. **Security impact.** Strictly strengthening: two
real egress paths closed in the test harness, four alias-evasion forms closed in
the static gate, and the gate's own branches now measured. No prohibition
relaxed.

**Rollback.** Pure test, script, and config changes; revert the commit.

### Slice 16 — the low sweep (plan 2, issue 11, PARTIAL: 7 of 10 items)

**User outcome.** Five refusals now describe the right problem, or fire at all;
two documents no longer understate their scope; and the capability manifest
lists two verbs that already shipped.

**Reproduced against real code, then re-run after:**

| | Before | After |
| --- | --- | --- |
| `add_finding(ASSUMPTION, withdrawn citation)` | **refused `citation_withdrawn`** | accepted |
| `add_finding(MATERIAL, withdrawn citation)` | refused `citation_withdrawn` | refused `citation_withdrawn` |
| `add_evidence(start_byte=1.0)` | **raw `TypeError` in the transaction** | `citation_offsets_invalid` |
| `initialize(refuse_existing=True)` on a symlink | **`database_exists`** | `database_symlink` |
| `initialize(refuse_existing=False)` on a symlink | `database_symlink` | `database_symlink` |
| non-root validation error carrying the digest sentence | **`request_digest_mismatch`** | `request_invalid` |
| genuine root digest mismatch | `request_digest_mismatch` | `request_digest_mismatch` |
| `X-Forwarded-Email`, `X-Goog-Authenticated-User-Email`, +5 more | **accepted** | `external_identity_rejected` |

**F2-RES-2 was resolved toward the ADR, not away from it.** The choice plan 2
offered was to gate on `kind.requires_citation` or amend ADR 0007. Amending
would have been weakening a contract to match an implementation: the ADR and
PRD invariant 8 both scope the withdrawn-citation refusal to material findings,
and the blanket refusal was not even a stronger guarantee, because the same end
state reached by withdrawing *after* creation already exported fine. The flag
now derives from `statement_kind.requires_citation`, so creation and export
read one predicate.

**F2-SURFACES-3 is defence in depth and is labelled as such.** `local_identity`
derives the actor from `getpass.getuser()`; no code path reads an actor from a
header, so the headers this now rejects would have granted nothing if accepted.
The value is that a misconfigured identity proxy in front of Minerva fails
loudly instead of appearing to work. Matching is case-normalised and covers the
mainstream families — Google IAP, oauth2-proxy, Azure EasyAuth, Kong, and
Cloudflare Access via prefix — rather than the arbitrary subset it listed.

**F2-INTEGRATIONS-1 closes a class, not a live hole.** Every request field is
pattern-constrained today, so no input can currently carry the mismatch
sentence into a non-root error. The classifier is anchored anyway — exact
message, `value_error`, empty `loc` — because the packet reader already learned
this lesson as F-SEC-1 and the two readers should not differ.

**F3-MILESTONE-TITLES needed more than a title.** Retitling
`docs/THREAT_MODEL.md` to cover Milestone 1.5 would have claimed coverage its
body did not have, since it had no retraction row at all. It gained one, plus a
security invariant that states what the code does rather than the tidier thing:
finding reads return a retracted finding marked with its reason, timestamp, and
actor, while synthesis *excludes* it from the brief. Both are true; they are not
the same rule, and an invariant that said "every surface returns it" would have
been false for export.

**F5-CAP-PACKET-CLI changes a published contract, additively.**
`research.packet.v2.verify.cli` and `research.packet.v2.inspect.cli` back real
`minerva packet verify` / `minerva packet inspect` commands, verified present
before being declared. This adds two names to `minerva.capabilities.v2` and
removes or alters none, so a consumer pinning the previous set sees new entries,
never a missing one. `test_capability_manifest_is_versioned_and_truthful` pins
the full document, so the manifest cannot drift from this record silently.

**Three items are NOT done.** `F2-CORE-5` (recompute pending migrations inside
the write transaction), `F2-TESTS-4` (golden-fixture regeneration procedure),
and `F4-CLI-UNDOC` (README CLI verb reference) remain open. Issue 11 is
therefore partially complete and is recorded that way; the next slice picks
them up.

**Tests.** Five regressions verified to fail on pre-fix source, one per code
fix. 676 tests, 208 security-marked, 89.97% branch coverage. All eleven gates
green.

**Files changed.** `src/minerva/research/service.py`,
`src/minerva/evidence/service.py`, `src/minerva/core/db.py`,
`src/minerva/integrations/research_request.py`,
`src/minerva/integrations/research_request_file.py`,
`src/minerva/api/routes.py`, `docs/PRD.md`, `docs/THREAT_MODEL.md`,
`docs/DECISIONS.md`, and five test modules.

**Migration status.** None. **Security impact.** One refusal deliberately
relaxed — assumptions may now cite withdrawn evidence — which restores the
documented contract rather than weakening it; the material-finding refusal is
unchanged and pinned. Everything else strengthens: an unmapped exception became
a domain refusal, a flag-dependent error code became deterministic, a
classifier was anchored, and seven proxy identity headers plus two vendor
prefixes are now rejected.

**Rollback.** Revert the commit. The manifest addition is the only externally
visible contract change and reverting it removes two names a consumer may have
started reading.

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

**Ungated work remains available.** Unlike after slice 6, Opus is not
blocked: plan 2 section 19 lists twelve ordered Phase 0C issues, every one
traceable to a reproduced finding. Slice 7 completed issues 1-2; slice 8
completed issue 3.

Slices 7-15 completed issues 1-10. Slice 16 completed **seven of the ten**
items in issue 11 — the low sweep from plan 2 section 27: `F2-CORE-6`,
`F2-RES-2`, `F2-EVD-1`, `F2-INTEGRATIONS-1`, `F2-SURFACES-3`,
`F3-MILESTONE-TITLES`, and `F5-CAP-PACKET-CLI`.

**Issue 11 is not finished.** Three items remain and are the next slice:

- `F2-CORE-5` — recompute pending migrations inside the write transaction so a
  concurrent upgrade resolves as a no-op instead of a spurious
  `migration_failed`. The only one of the three that touches migration history,
  so it needs a reproduction that actually races two upgraders, not a mocked
  one.
- `F2-TESTS-4` — a deterministic golden-fixture regeneration procedure. Today
  a contract change means hand-editing fixtures, which is how a fixture and the
  code it pins drift apart without either looking wrong.
- `F4-CLI-UNDOC` — the README does not list every CLI verb. `packet verify` and
  `packet inspect` were undocumented there even while slice 16 was adding them
  to the capability manifest.

Then issue 12 (interrupt audit, helper consolidation, release tag, coverage
ratchet).


Still awaiting Kevin, and not to be started without a recorded decision:

- **D-1 — persist human-adopted agent inferences.** The remaining
  high-leverage gate. Plan 2 specifies it with a day-one retraction table so
  the D-9 lesson is applied rather than relearned, and notes that slice 7's
  read-model work was a prerequisite in spirit: persisting a second record
  type on an invisible-retraction read model would have repeated exactly the
  defect slice 7 just fixed.
- **D-10** REST evidence withdrawal and the capability manifest `.cli`
  taxonomy. **D-11** restoring a pre-upgrade backup with an upgraded binary.
- **D-2..D-8** the fleet gates: Athena authentication and transport, Icarus
  artifacts, remote access, MCP timing, retrieval/OCR, signing, licensing.

A natural follow-on to D-9 that Kevin may want to consider: whether a future
`minerva.research-brief.v3` should carry retracted findings under a flag, the
way the ledger keeps withdrawn evidence visible. ADR 0007 records this as the
closest rejected alternative; it needs a consumer before it is worth the
contract change.

## Rollback instructions (whole phase)

Every slice is one reviewed commit on `opus/minerva-vision-implementation`
and is revertible in isolation. `main` is never pushed directly. Because
Minerva's research tables are append-only and migration 0003 is additive,
no slice rewrites research history: reverting the code and restoring a
pre-upgrade backup with the prior binary always reproduces the pre-slice
state exactly.
