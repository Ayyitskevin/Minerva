---
repository: Ayyitskevin/Minerva
phase: FABLE_PLANNING
status: READY_FOR_OPUS
base_commit: 4977f5aa40cc83a300d009cf3d8e4649cf68ae1d
---

# Fable Minerva game plan

This document is the complete Fable 5 planning deliverable for the two-stage
Fable → Opus assignment. It records a full repository review at
`base_commit` (`4977f5a`, the merge of PR #7 — the reviewed source
tree; the only later merge, PR #8, added this document itself), a
findings ledger, a refined product vision, and an implementation-ready
roadmap. Opus 5 executes from this file; all handoff state is durable
here.

Reading order for Opus: sections 1–4 (what exists and what is wrong),
section 26 (what to build first), sections 16–21 (how to build it),
section 27 (the findings ledger backing every "fix now" item), section 24
(what NOT to decide alone).

---

## 1. Executive summary

Minerva at `4977f5a` is a genuinely healthy, unusually disciplined alpha.
All eleven repository gates pass in the locked environment (ruff lint and
format, strict mypy over 51 files, 547 tests at 89.04% branch coverage
against an 85% floor, build, dist verification, installed-wheel smoke,
static security check over 49 files, `uv pip check`, `git diff --check`).
The implemented surface matches the documented milestones: an offline
research vertical slice (missions → questions → falsifiable claims →
immutable UTF-8 snapshots → exact byte-span evidence → findings →
deterministic briefs) with append-only audit (M1/M1.1), standalone offline
packet verification (M1.2), an inert offline research-request contract with
bounded read-only fulfillment (M1.3), and digest-bound CLI-only BYOK model
assistance (M2B). The doctrine — *records evidence and uncertainty; does
not manufacture certainty* — is enforced in schema (no `true` claim state,
no confidence-from-counts anywhere), in triggers (append-only on every
research table), and in tests.

The review found **no blocker-severity defect**. Eleven parallel deep
reviews with adversarial re-verification confirmed **one high finding**
(a data-loss race in `Database.connect()/initialize()` failure cleanup,
ledger F-DB-1 — the exact pattern class ADR 0004 eliminated for
restore, still present on the fresh-database path), **seven medium
findings** (permanent brief-export block after withdrawing cited
evidence; over-strict withdrawn-citation refusal for non-material
statements; restore masking migration-state errors as corruption; two
quantified full-table audit scans in the fulfillment budget; a missing
`ANTHROPIC_AUTH_TOKEN` fail-closed guard; static-gate ban-list gaps),
and a body of low findings — every one with exact file/symbol evidence
in section 27. The dominant risks beyond those defects are structural
pressures on the next stage of the vision:

1. **Availability debt in fulfillment — now quantified.** The M1.3
   work-budget guard is honest, but two query families full-scan the
   *global* `audit_events` table (the per-snapshot import-event lookup
   in `sources/integrity.py:42–53`, executed twice per cited snapshot,
   and the `research.run.started` branch of the scoped audit CTE,
   executed twice per fulfillment), and the claim-scoped finding
   queries scan every mission finding. Measured on a schema replica:
   ~3 VM steps per scanned row, so a valid request citing ~20 snapshots
   false-refuses with `brief_work_limit` once total audit history
   reaches roughly 60–70k rows — an ordinary long-lived multi-mission
   database. The docs already defer this to "a separately human-reviewed
   indexing migration." That migration is the single highest-value,
   lowest-risk next change.
2. **The fleet seams exist but have no identity.** `research-request.v1`,
   `research-brief.v2`, `research-result.v1`, and the capabilities
   manifest are exactly the right artifact seams for Athena and Icarus,
   and they are deliberately inert. Every future step (Athena adapter,
   Icarus exchange, MCP) is blocked — correctly — on an authentication
   and authorization design that does not exist yet. That design is a
   human decision gate, not an engineering backlog item.
3. **Model assistance is safe but a dead end as designed.** Candidates
   are ephemeral by contract; the operator retypes anything useful. The
   PRD's own statement classes (`agent_inference` with required, labeled
   citations) already describe the safe evolution: an explicit,
   human-accepted, persisted agent-inference finding — never evidence,
   never auto-adopted. That requires an ADR and Kevin's sign-off because
   ADR 0003 currently promises candidates are never persisted.

The recommended first Opus slice (section 26) is deliberately narrow:
ship the fulfillment indexing migration (0003) and fix the verified
correctness/security defects from the findings ledger (wave A in
section 27), each with an invariant-level regression test. It adds no
new trust surface and requires no new human decision; the two items
that touch guarded code (`db.py` cleanup identity, the static-gate ban
list) are exactly the changes AGENTS.md routes through Kevin's PR
review, which this workflow already provides.

## 2. Current-state architecture

Verified against source at `4977f5a`; this restates the ARCHITECTURE.md
picture only where the code confirms it, and notes where reality is more
specific.

**Shape.** One installable package (`minerva-research` 0.2.0a1, Python
3.12–3.15 excl., Linux/POSIX) with a single command/service layer and
thin adapters. Imports point inward; only
`integrations/ai/{openai,anthropic}.py` may import provider SDKs/httpx
(statically enforced by `scripts/static_security_check.py`).

- `core/` — `Database` (WAL, foreign keys, busy timeout, `BEGIN
  IMMEDIATE` mutations via `transaction()`, read snapshots via `read()`),
  packaged SQL migrations with recorded SHA-256 checksums and
  fail-closed version/checksum validation, `AuditRecorder` (run insert +
  audit row in the mutation's transaction), `IdentityContext`
  (`local_identity`/`system_identity`; remote actor headers rejected at
  the API layer), restore staging/publication per ADR 0004, doctor.
- `research/`, `sources/`, `evidence/`, `synthesis/` — domain services
  owning missions/questions/claims/findings, snapshot import (descriptor
  walk, UTF-8 validation, secret-pattern scan, double-read stability),
  byte-span citations (creation and export re-verify digest, bounds,
  code-point boundaries, exact quote bytes), deterministic canonical
  briefs (sorted keys, compact separators, no wall-clock in payload,
  SHA-256 over semantic payload), and M1.3 claim-scoped request
  fulfillment (query-only snapshot, progress-handler work budget,
  NUL-safe storage-byte preflight).
- `integrations/` — SQLite-independent protocol layer: strict
  `minerva.research-brief.v2` DTO/parser/verifier,
  `minerva.research-request.v1`, `minerva.research-result.v1`,
  `safe_artifact_file.py` (reject `..`, `O_NOFOLLOW` component walk,
  `O_PATH` pin, regular-file check, metadata size cap, bounded
  double-read identity check), plus the two reviewed provider adapters.
- `assist/` — preview/authorize service: bounded context assembly from
  one claim's active ledger, request SHA-256 binding provider, model,
  destination, prompt hash, context hash, provenance, and limits;
  post-call context revalidation; structured-response validation
  (evidence-ID membership, bounds, secret patterns); metadata-only
  requested/terminal audit events bracketing the non-transactional call.
- `api/` — `/api/v1` strict Pydantic contracts: capabilities manifest
  (`minerva.capabilities.v2`), mission/question/claim/source/evidence/
  finding creation and listing, claim status with `If-Match` versioning,
  signed opaque pagination cursors, stable error codes. Source import is
  inline-content only (1 MiB cap) — no endpoint accepts a filesystem
  path or an actor header.
- `web/` — loopback-only read-only server-rendered pages (missions,
  claim detail, brief preview/markdown/json), middleware enforcing
  loopback Host/Origin, body cap, CSP; CSRF primitive exists but is
  deliberately unwired (no unsafe forms exist).
- `cli/` — `init`, `mission`, `question`, `claim` (add/show/ledger/
  status), `source` (import/show), `evidence` (add/withdraw), `finding
  add`, `brief` (preview/export), `packet` (verify/inspect), `request`
  (verify/fulfill), `audit list`, `doctor [--deep]`, `backup`, `restore`,
  `assist finding-candidates`, `serve`; plus `minerva-demo`. Exit
  contract 0/2/3/4/1 is uniform.

**Schema (migrations 0001–0002).** Eleven STRICT tables, all with
append-only UPDATE/DELETE triggers: `schema_migrations`, `research_runs`,
`research_missions`, `research_questions`, `claims`,
`claim_status_events` (versioned, UNIQUE(claim_id, version)), `sources`,
`source_snapshots` (content BLOB + sha256 + byte_length CHECK),
`evidence_cards` (byte-span + quote + stance + supersedes FK,
mission-composite FKs throughout), `evidence_withdrawals`
(UNIQUE(evidence_id)), `audit_events` (AUTOINCREMENT sequence, bounded
details_json), `findings` (statement_kind enum matching the PRD statement
classes), `finding_citations`, `brief_exports`. Existing indexes cover
mission-scoped listing and claim→evidence; they do **not** cover
findings-by-claim, citations-by-evidence, or audit-by-entity (see
section 17).

**Gates.** CI mirrors AGENTS.md. All gates verified green in this review
(section 28).

## 3. Verified strengths

These were checked in code and tests, not assumed from docs:

1. **Append-only is real.** Every research table has UPDATE and DELETE
   ABORT triggers in migration SQL; withdrawal and supersession are new
   rows; doctor and tests exercise the triggers.
2. **Citations are re-verified, not trusted.** Byte bounds, UTF-8
   code-point boundaries, digest, and exact quote-byte equality are
   checked at creation and again at export/read; tampering fails closed
   rather than producing a plausible brief.
3. **Mutation/audit atomicity holds.** One command, one `BEGIN
   IMMEDIATE` transaction, run + audit row inside it; rejected mutations
   leave nothing. The single declared exception (assist bracketing) is
   documented in ADR 0003 and implemented exactly as documented.
4. **Determinism is enforced end to end.** Canonical serialization
   (sorted keys, compact separators, trailing newline, no export
   wall-clock) with SHA-256 over the semantic payload; golden fixtures
   pin byte-identical output.
5. **The protocol layer is genuinely SQLite-independent** and strict:
   unknown/duplicate fields, non-standard numbers, depth/width bounds,
   fail-fast sequence validation, bounded error fanout, pre-decode size
   caps from file metadata.
6. **File-boundary discipline is uniform.** One shared
   `safe_artifact_file` reader (no `..`, no symlinks in any component,
   `O_PATH` pin, type check, bounded double-read) serves packet and
   request intake; export/publication uses `O_EXCL` owner-only no-follow
   writes with inode-aware caught-error cleanup.
7. **The digest story is honest everywhere.** Every surface that prints
   a digest also states that it proves self-consistency, not
   authenticity, origin, approval, or truth — in README, SECURITY,
   command output, and packet ownership blocks.
8. **The assist boundary matches its ADR.** Preview reads no credential
   and performs no network I/O; egress requires flag + exact fresh
   digest; adapters pin official origins, ignore proxies, fail closed on
   header/account-routing env vars, disable retries/redirects/tools;
   timeout is recorded as an unknown outcome and never retried.
9. **Capability manifest is truthful.** `minerva.capabilities.v2`
   advertises only implemented local surfaces and explicitly lists
   sibling exchange, orchestration, execution, and approval authority as
   unavailable.
10. **Test discipline.** 547 tests including security-marked adversarial
    tests, provider fakes only, demo under denied outbound connections,
    installed-wheel smoke outside the checkout, and invariant-level
    negative tests (e.g., triggers, digest mismatch, citation forgery).

## 4. Verified weaknesses and risks

Summarized here; each maps to ledger entries in section 27 with exact
file/symbol evidence and an adversarial-verification verdict. No
blocker-severity findings were confirmed; one high and seven medium
findings were.

1. **Fresh-database failure cleanup can destroy state Minerva did not
   create (confirmed high, F-DB-1).** `Database.connect()` and
   `initialize()` delete the base path plus `-wal/-shm/-journal` by
   pathname on failure with no dev/inode identity check
   (`_remove_database_artifacts`, `core/db.py:244–267, 429–435`). Two
   Minerva processes racing on a fresh path can end with the loser
   unlinking the winner's just-committed database; a mutation command
   racing the first `minerva init` does the same; a dangling operator
   symlink or stale sidecars beside a nonexistent database also get
   unlinked. The codebase already owns the correct pattern
   (identity-checked `_PrivateDatabaseFile.cleanup`, ADR 0004) — it is
   simply not applied to this path.
2. **Fulfillment false-refusal debt — quantified (F-FUL-1..3).** Two
   query families full-scan the *global* `audit_events` table inside
   the VM budget (per-snapshot import-event lookup, twice per cited
   snapshot; the `run.started` CTE branch, twice per fulfillment), and
   claim-scoped finding queries scan all mission findings. Measured:
   ~3 VM steps/row ⇒ a valid ~20-snapshot request false-refuses at
   roughly 60–70k total audit rows. Documented, deliberate, deferred —
   and the main availability defect in the artifact contract the
   future fleet depends on.
3. **Withdrawal can permanently brick mission export (confirmed
   medium, F-WDR-1/2).** Following the documented correction workflow
   (record a finding, later withdraw evidence it cites) makes `brief
   preview/export` and claim-scoped fulfillment refuse forever —
   findings are append-only, withdrawal is irreversible, and no
   retraction record exists; deep doctor then reports a permanent
   `finding_integrity` failure for honest use. The refusal also
   applies to *optional* citations on explicitly non-evidentiary
   assumptions/unresolved questions, stricter than PRD invariant 8.
   Needs a product decision (D-9), not a patch.
4. **Smaller confirmed mediums:** restore masks migration-state errors
   as "failed integrity validation" (F-OPS-2); the Anthropic adapter's
   fail-closed env list omits `ANTHROPIC_AUTH_TOKEN` (F-AI-2); the
   static security gate misses several process/egress primitives —
   `os.posix_spawn`, `multiprocessing`, `ProcessPoolExecutor`,
   `webbrowser`, `ctypes` loaders, `loop.getaddrinfo`/`sock_connect` —
   all confirmed by probe (F-GATE-1).
5. **Restore/backup/fulfillment crash windows are honest but
   operator-hostile.** Partial staging files, partial output
   directories, and unmatched assist `requested` audit events are all
   documented as operator-cleanup cases; nothing in `doctor` or the CLI
   helps an operator find or classify them, and orphan staging files
   are full copies of sensitive research data hidden as dotfiles.
   (Ledger F-OPS-1.)
6. **Assist candidates are ephemeral to a fault.** The operator cannot
   keep an accepted candidate without manually retyping it as a finding,
   which loses the machine-readable link between the model run recorded
   in audit and the human-authored finding derived from it. Evolving
   this touches ADR 0003's "never persisted" promise and is therefore a
   Kevin decision, not a background improvement. (Ledger F-AI-1.)
7. **Single-claim assist scope.** The bounded context covers one claim
   and its active ledger only; there is no cross-claim or
   mission-level assistance. This is by design for M2B; the plan keeps
   it that way until agent-inference persistence is decided.
8. **Coverage soft spots.** `safe_artifact_file.py` (73%),
   `core/operations.py` (66%), and `sources/integrity.py` (77%) have
   the lowest branch coverage in the tree; the uncovered branches are
   mostly error paths in exactly the code where error paths are the
   security contract. (Ledger F-TEST-1.)
9. **Web/API surface lags the domain model.** The HTML surface shows
   missions/claims/briefs but not findings, withdrawals, supersession
   chains, or audit; the API cannot withdraw evidence (escalated as
   D-10); the web mission list silently truncates at 100. None of this
   violates a contract (CLI is the reference surface), but parity
   drift is accumulating. (Ledger F-PAR-1..3.)
10. **Fleet-vision gap, not defect:** no authentication design, no run
    lineage for external agents, no import-before-evidence workflow for
    external artifacts. These are the roadmap, entered through decision
    gates in section 24.

## 5. Refined Minerva vision

The working vision ("provenance-first research intelligence plane for
Kevin's AI fleet") survives contact with the codebase, with three
refinements the code itself argues for:

1. **Minerva is the *memory of why*, not a workflow engine.** Athena
   coordinates *who does what when*; Minerva owns *what is claimed, on
   what evidence, with what uncertainty*. The codebase already refuses
   workflow gravity (no approvals, no orchestration, machine-readable
   ownership boundary in every packet). Keep refusing it. Anything that
   looks like task state belongs in Athena; anything that looks like an
   epistemic state belongs in Minerva.
2. **The unit of exchange is a verified artifact, never a connection.**
   The implemented request/brief/result triple proves the pattern:
   inert files, canonical bytes, digests that bind but do not
   authenticate, verification before use. Athena and Icarus integration
   should *extend this pattern with authentication around it*, not
   replace it with RPC into Minerva's services.
3. **Model output enters through exactly one door.** The PRD statement
   classes already define it: `agent_inference`, labeled, cited,
   uncertainty-bearing, never evidence. The evolution path for
   assistance is to make that door real (persisted, human-accepted
   inference objects with full provenance) rather than adding more
   ephemeral surfaces or more providers.

Restated one-line vision: **Minerva is the fleet's defensible research
memory: every claim any agent relies on can be traced to exact bytes,
explicit stances, named uncertainty, and an append-only account of who
asserted what — and nothing else pretends to be that.**

## 6. Athena / Minerva / Icarus responsibility map

| Concern | Athena (coordination plane) | Minerva (research intelligence plane) | Icarus (experiment plane) |
| --- | --- | --- | --- |
| Missions as work | Creates/assigns/monitors work missions, identities, approvals | Owns *research* missions as epistemic containers; Athena references them by ID, never writes them | Receives bounded experiment requests referencing Minerva claims |
| Identity | Issues and authenticates fleet identities | Maps *authenticated* callers to local `IdentityContext` at an adapter boundary; never trusts headers | Runs as its own identity; results carry it as metadata, not authority |
| Questions/claims/evidence/uncertainty | Read-only consumer via verified packets | Sole owner and system of record | Consumer of claim context in requests; producer of raw results only |
| Requests for research | May *produce* `minerva.research-request.v1` files once authenticated adapter exists | Verifies and fulfills; never fetches, never pushes | n/a |
| Experiment execution | Approves/schedules | Never executes; imports result artifacts as sources only after explicit verification + snapshot import + citation | Executes bounded, versioned experiments; returns result manifests (schema + SHA-256) |
| Truth/confidence | Never asserts | Never asserts; records stances and statuses | Never asserts; results are bytes with provenance |
| Storage | Own store | Own SQLite; no shared tables, no sibling imports (permanent) | Own store |
| Transport | Future authenticated channel (decision gate D-2) | Artifact seams only until D-2; loopback HTTP stays single-user | Same artifact discipline |

Permanent rules regardless of phase: no shared database, no sibling
package imports, artifact references are schema-version + SHA-256 (never
paths/URLs to dereference), digests are never authentication, external
results become evidence only through explicit Minerva import and
citation.

## 7. Current-versus-target capability matrix

Status legend: **implemented** / **partial** / **planned** (this plan
proposes it) / **unsupported** (not planned) / **speculative** (needs
validation) / **decision** (blocked on Kevin, section 24).

| Capability | Current | Target | Status |
| --- | --- | --- | --- |
| Offline research vertical slice (missions→briefs) | Complete, gated | Keep; polish parity | implemented |
| Immutable snapshots, exact citations, append-only audit | Complete | Keep permanently | implemented |
| Deterministic canonical packet + offline verify/inspect | Complete | Keep; stable contract | implemented |
| Offline research request verify/fulfill | Complete but false-refusal debt | Indexed, availability-tested | partial → planned (slice 1) |
| Operator crash-remnant guidance (staging/partial outputs) | Documented only | `doctor` surfaces remnants read-only | planned |
| BYOK CLI assistance (preview/confirm/candidates) | Complete | Keep; no expansion of providers/surfaces | implemented |
| Persisted, human-accepted agent-inference objects | Absent (candidates ephemeral) | One reviewed door for model output | decision (D-1) → planned |
| Research-run lineage for external agent work | Runs exist, local kinds only | Bounded run/agent lineage records | planned (after D-2 shape known) |
| Authenticated Athena coordination adapter | Absent (correctly) | Token-authenticated local adapter producing/consuming existing artifacts | decision (D-2) → planned |
| Icarus experiment request/result artifacts | Absent | Versioned artifact pair + import-before-evidence workflow | decision (D-3) → planned |
| Evidence-preserving local source collections (dirs of files, manifests) | Single-file import only | Batched import with per-file provenance | planned |
| Reviewed retrieval / OCR / PDF / crawling | Absent (banned) | Only via separate approved design; not in this plan's horizon | decision (D-6) / speculative |
| Semantic / vector search | Absent | Local, optional, index-only (never evidence) | speculative |
| MCP server | Absent (correctly) | Defer until D-2 authentication exists; then read-only verified-packet tools first | decision (D-5) |
| Bounded research workers / autonomous loops | Absent (banned) | Remains banned absent separate design | unsupported |
| Human review & escalation objects | Absent | Speculative; Athena may own this instead | speculative |
| Remote access / multi-user | Absent (banned) | Requires new auth + threat model | decision (D-4) |
| Signed exports / origin assurance | Absent (digests only) | Optional signing seam | decision (D-7) / speculative |
| Encryption at rest | Absent (documented) | OS-level guidance now; app-level speculative | speculative |

## 8. Product principles and permanent non-goals

Principles (all currently true in code; keep them true):

1. Evidence and uncertainty are recorded, never manufactured; claim
   status is workflow, never truth; counts are never confidence.
2. Adverse evidence is structurally impossible to hide: complete-ledger
   fulfillment, stance preservation in every export, withdrawal as
   history rather than deletion.
3. Every material statement resolves to exact bytes a human can re-read.
4. Determinism before convenience: same state + same schema = same
   bytes, always.
5. Disclosure is explicit, previewed, and digest-bound; nothing leaves
   the machine that an operator did not see leave.
6. One command/service layer; adapters never own rules.
7. Artifacts over connections; verification before trust; digests bind,
   they do not authenticate.
8. Boundaries are stated in machine-readable form (ownership blocks,
   capability manifest) and kept truthful.

Permanent non-goals (outside Minerva regardless of phase — section 25
records the reasoning):

- Determining truth, scoring confidence, or auto-adopting model output.
- Orchestration, approvals, task assignment, scheduling (Athena's).
- Experiment execution, arbitrary shell/notebook/plugin/code execution
  (Icarus's, behind its own boundary).
- Publication, messaging, email/Slack, cloud hosting.
- Shared databases or package imports with siblings.
- Trusting caller-supplied identity without an authentication boundary.
- Medical diagnosis, legal conclusions, live financial actions.

## 9. Target architecture

The target keeps the current shape and adds exactly three kinds of new
structure, in dependency order:

```text
                       (unchanged core)
CLI / REST / HTML --> commands/services --> SQLite (migrated, append-only)
                             |                    |
                             +--> protocol layer: research-brief.v2,
                             |    research-request.v1, research-result.v1,
                             |    capabilities.v2   (unchanged contracts)
                             |
        NEW (1) agent-inference door (post D-1):
        assist CLI --> preview/confirm (unchanged) --> candidates
             --> EXPLICIT `assist adopt` --> persisted agent_inference
                 finding (labeled, cited, uncertainty-bearing, audited)

        NEW (2) authenticated coordination adapter (post D-2):
        Athena --> authenticated local transport --> adapter
             --> maps identity --> produces/consumes the SAME inert
                 request/brief/result artifacts (no new query surface)

        NEW (3) experiment exchange (post D-3):
        Minerva --> minerva.experiment-request.v1 (artifact out)
        Icarus  --> minerva.experiment-result.v1 + payload bytes
             --> operator/adapter verifies digest --> `source import`
                 (existing snapshot door) --> citation --> evidence
```

Non-negotiable structural rules carried forward: adapters stay thin; the
protocol layer stays SQLite-independent; new artifact contracts get their
own versioned schemas and golden fixtures; every new mutation goes
through a service that owns its transaction and audit row; every new
boundary gets adversarial tests before it ships.

## 10. Domain-model evolution

Current model (verified): eleven STRICT append-only tables (section 2).
Evolution is additive-only — no existing table, column, trigger, or
contract changes meaning. Proposed additions, in order:

1. **Migration 0003 (slice 1, no new tables):** targeted indexes only —
   `findings(claim_id)` partial where claim_id IS NOT NULL,
   `finding_citations(evidence_id)`, `audit_events(entity_id, sequence)`,
   and `evidence_withdrawals(mission_id)` if the fulfillment path's
   withdrawal-history query needs it (verify query plans first with
   `EXPLAIN QUERY PLAN` in tests). Indexes do not alter canonical
   output; determinism tests must prove exports are byte-identical
   before/after.
2. **`agent_inferences` table (post D-1, migration 0004):** persisted,
   append-only, human-accepted inference records: id (`inf_` prefix),
   mission_id, claim_id, statement, uncertainty (required non-empty),
   provider, model, request_sha256 (links to the assist audit events),
   accepted_by/creator_id, run_id, created_at; plus
   `agent_inference_citations` mirroring `finding_citations` with
   NOT-NULL evidence references (an inference with zero citations is
   invalid by definition). Never a stance, never a claim-status input,
   excluded from evidence ledgers, included in briefs only under an
   explicit labeled section.
3. **Run lineage columns (post D-2 shape):** `research_runs` gains no
   new trust; a new append-only `run_origins` table records, for runs
   created through the authenticated adapter: authenticated principal
   name, transport, request digest. Local runs are unaffected.
4. **Experiment exchange (post D-3):** no new research tables; an
   `external_artifacts` append-only registry (schema_version, sha256,
   byte_length, verified_at, imported_snapshot_id nullable) records
   verify→import lineage so an imported Icarus result is traceable to
   its manifest without trusting either.

Explicitly rejected model changes: mutable anything; a `true`/`score`
column anywhere; storing provider prompts/responses; cross-mission
dedup of snapshots; request/scope fields inside `research-brief.v2`.

## 11. Evidence and citation safety model

Unchanged foundation (verified in code, keep permanently): immutable
digested snapshots; zero-based half-open UTF-8 byte offsets; quote-byte
equality re-checked at creation, read, and export; mission-composite
foreign keys preventing cross-mission reference; withdrawal/supersession
as history; complete-ledger fulfillment preventing stance suppression;
material findings requiring same-mission citations.

Additions this plan layers on top:

- **Import-before-evidence for external artifacts (D-3):** an Icarus
  result participates in research only as a normal imported snapshot
  (UTF-8, size-bounded, digested) plus citations. The
  `external_artifacts` registry links manifest digest → snapshot for
  provenance, but the *evidence rules do not change at all* — that is
  the point.
- **Inference citations are mandatory** for persisted agent inferences
  (stricter than findings, where assumptions/unresolved questions may be
  uncited): a model may only say things about cited evidence.
- **No new text-trust surfaces:** semantic search, if ever built, indexes
  snapshots/quotes but returns citations, never synthesized text.

## 12. AI / provider policy model

Current policy (ADR 0003, verified implemented): CLI-only, BYOK,
preview-then-confirm with exact digest, two pinned adapters, no retry/
fallback/tools/proxies, ephemeral candidates, metadata-only audit,
unknown-outcome honesty. This plan changes none of it in place.

Policy evolution, gated:

- **D-1 (agent-inference persistence):** adds one verb, `assist adopt`
  (name final at implementation): after a normal preview→confirm→
  candidates round, the operator explicitly adopts at most one candidate
  by index *in the same CLI session output*, which re-validates the
  candidate against the current active ledger, requires non-empty
  uncertainty, and persists it as an `agent_inference` record citing
  only authorized evidence IDs. ADR 0003 must be amended (supersession
  note, not silent edit): "never persisted" becomes "never persisted
  *without a distinct explicit adoption action*." Everything else
  (ephemeral by default, no auto-adoption, no API/web surface) stands.
- **Additional providers / local models:** rejected for this planning
  horizon (section 25) — every provider multiplies the reviewed-adapter
  audit surface; local models add an execution surface. Revisit only
  with a concrete fleet need.
- **Prompt-injection posture:** unchanged — untrusted research text,
  fixed instruction prompt, structured output, local validation, human
  review. Adversarial tests must accompany any prompt change; the test
  suite already fakes hostile responses (oversized, out-of-scope IDs,
  secret-bearing) and must gain injection-shaped fixtures when D-1 lands
  (a candidate that tries to smuggle instructions into `statement`).
- **What stays banned regardless:** model calls from API/web, URL
  retrieval, tools, autonomous loops, model-derived claim status,
  confidence scores.

## 13. Research-run and agent lifecycle

Current (verified): every mutation carries an `IdentityContext` (run id,
actor id, actor kind ∈ {os_user, system}); first mutation in a run
inserts the run row in the same transaction; audit rows reference the
run. This is sufficient lineage for a single trusted operator.

Target lifecycle for fleet work, phased:

1. **Now → D-2:** no change. External agents have no write path, so no
   agent lifecycle exists; anything claiming otherwise would be false.
2. **Post D-2 (authenticated adapter):** an authenticated principal
   (e.g., `athena:planner-1`) maps at the adapter to a *new* actor kind
   (`external_agent`) recorded in `run_origins` with transport and
   credential fingerprint. Runs remain append-only and application-
   created; the adapter can never supply a run id or actor string
   directly (mapping table, not passthrough — the no-actor-header rule
   generalizes).
3. **Bounded work, always:** an external run is created per verified
   request artifact, does exactly that request's work, and terminates.
   No standing sessions, no queues inside Minerva, no autonomous
   continuation. Idempotency: one request digest → at most one
   fulfillment output directory; replays are detected by digest and
   refused with a stable error (Athena retries by asking again with a
   fresh request if state changed).
4. **Agent inferences (post D-1)** record which model/run produced them,
   permanently distinguishing machine inference from human synthesis in
   every export.

## 14. Protocol and artifact contracts

Implemented and stable (do not change): `minerva.research-brief.v2`
(canonical packet; request/scope fields permanently excluded),
`minerva.research-request.v1` (inert selection + complete-ledger
precondition), `minerva.research-result.v1` (digest binding),
`minerva.capabilities.v2` (truthful manifest). All are strict, canonical,
size-capped, and golden-fixtured.

Planned contracts (each ships with: JSON schema doc section, strict DTO
+ canonical serializer + verifier in `integrations/`, golden fixtures,
adversarial parse tests, and a capabilities entry only when usable):

- **`minerva.experiment-request.v1` (post D-3):** mission_id, claim_id,
  bounded hypothesis text drawn from the claim statement/falsification
  criterion, expected result schema, optional cited evidence context ids;
  NO execution parameters beyond a declared bounded profile name — Icarus
  owns execution semantics. Digest = self-consistency only.
- **`minerva.experiment-result.v1` (post D-3):** request digest,
  result payload schema + SHA-256 + byte length, Icarus run metadata as
  *inert strings*. Consumed only by verify → explicit `source import`.
- **Envelope (post D-2, if adopted):** the ADR 0002 shared run envelope
  (run_id, task_id, actor, capability, scope, artifact_refs,
  idempotency_key, status, timestamps, model, node,
  recovery_checkpoint) as a *transport* wrapper outside every artifact
  digest; correlation metadata, never authority. Version it separately
  (`fleet.run-envelope.v1`) and keep it out of `integrations`' semantic
  verifiers except for reference-shape checks.

Contract rules: forward-only versioning (new schema string, parallel
support window, no in-place mutation of meaning); every field bounded;
unknown fields rejected; no paths/URLs/credentials/free-form authority
anywhere; digests never authenticate.

## 15. Authentication and authorization design

Nothing in this section is implemented until D-2 is decided; it is the
design Opus should hold future work against, and the reason MCP and any
Athena transport stay deferred.

- **Principals:** named fleet identities issued by Athena (or by Kevin
  manually at first: a keyfile per agent). Minerva stores only public
  verification material and a local capability grant per principal.
- **Transport candidate (local-first):** UNIX domain socket with
  per-request signed envelopes (Ed25519 over canonical request bytes +
  monotonic nonce + expiry), or an authenticated loopback HTTP header
  scheme carrying the same signed envelope. Decision belongs to D-2;
  both keep the no-remote-exposure rule intact.
- **Authorization model:** capability grants per principal, smallest
  useful set: `request:fulfill` (produce claim-scoped briefs),
  `packet:read` (receive brief bytes), later `inference:propose`.
  No principal ever gets raw SQL, mutation verbs, source import, or
  assist confirmation. Grants live in a new append-only table with
  explicit revocation rows (grant/revoke as events, current state =
  latest event), administered only via local CLI by the OS user.
- **Authentication is never:** an actor header, a digest, possession of
  a request file, loopback origin, or an MCP session default.
- **Disclosure policy:** authorization to *receive* a brief is a grant
  decision by the OS user per principal; the packet remains a
  disclosure-bearing artifact and the docs must say which principals
  hold which grants. Secret-pattern scanning stays defense-in-depth.
- **Replay/idempotency:** signed envelopes carry nonce + expiry;
  Minerva keeps a bounded seen-nonce set per principal; a replayed
  fulfillment request returns the stable already-fulfilled error with
  the original result digest (safe: it reveals only what the principal
  already received).
- **Audit:** every authenticated request records principal, capability,
  request digest, and outcome as bounded metadata audit events — the
  existing audit vocabulary extended, not bypassed.
- **Threat-model delta to write with the ADR:** key theft from Athena
  host, local malware replaying grants, socket permission tightening,
  DoS via request floods (rate bound per principal), and the standing
  rule that same-OS-user malware is inside the boundary until D-4.

## 16. Proposed ADR sequence

ADRs are the review instrument for every durable contract change. Order
matters; none may be skipped by implementation that needs it.

| ADR | Title | Gate | Contents |
| --- | --- | --- | --- |
| 0005 | Targeted fulfillment and audit indexing | none (documented deferral being redeemed; Kevin reviews the PR) | Index set, EXPLAIN-QUERY-PLAN evidence, determinism proof obligations, work-guard retention, rollback = restore pre-upgrade backup with prior binary |
| 0006 | Operator remnant diagnostics in doctor | none | Read-only enumeration of staging/partial-output/unmatched-assist remnants; no auto-cleanup, ever |
| 0007 | Persistent human-adopted agent inferences | **D-1** | Amends ADR 0003's "never persisted" to "never persisted without a distinct explicit adoption action"; schema, citation mandate, export labeling, threat-model delta (injection via adopted text), non-goals (no auto-adopt, no API/web, no status influence) |
| 0008 | Fleet principal authentication and capability grants | **D-2** | Principals, transport, signed envelopes, grant/revoke events, replay defense, audit vocabulary, threat model; explicitly supersedes nothing — it *creates* the first trust boundary beyond the OS user |
| 0009 | Athena coordination adapter over inert artifacts | **D-2** (after 0008) | Adapter consumes/produces existing request/brief/result artifacts under 0008 authentication; run lineage (`run_origins`); idempotency by request digest; no new query surface |
| 0010 | Icarus experiment request/result artifact contracts | **D-3** | `minerva.experiment-request.v1`/`-result.v1`, import-before-evidence via existing snapshot door, `external_artifacts` registry, failure/replay semantics |
| 0011 | MCP read-only research surface | **D-5** (after 0008) | Authenticated MCP exposing verify/inspect/fulfill-equivalent read tools only; no mutation verbs; per-principal grants |

Any ADR that changes a security contract requires: threat-model diff,
negative tests named in the ADR, and Kevin's merge review (AGENTS.md red
boundary already requires this).

## 17. Proposed migration sequence

Forward-only, checksum-recorded, one concern per migration, every one
preceded by a verified standalone backup in operator docs.

1. **0003_fulfillment_indexes.sql** (slice 1): `CREATE INDEX` only.
   Verified candidate set (the review reproduced each scan with
   `EXPLAIN QUERY PLAN` on a schema replica and measured ~3 VM
   steps/row; the PR must still include its own EXPLAIN diffs):
   - `idx_audit_event_entity` ON audit_events(event_type, entity_id,
     sequence) — converts BOTH confirmed global scans to point
     lookups: the per-snapshot import-event check
     (`sources/integrity.py:42–53`, `WHERE event_type = ? AND
     entity_id = ?`, runs twice per cited snapshot, ledger F-FUL-1)
     and the `research.run.started` branch of the scoped audit CTE
     (`synthesis/service.py:104–112`, filters
     `event_type='research.run.started'` joining on `entity_id`, runs
     twice per fulfillment, ledger F-FUL-2).
   - `idx_findings_claim` ON findings(claim_id, created_at, id) —
     serves the three claim-scoped finding/reference queries that
     currently scan every mission finding through forced `INDEXED BY
     idx_findings_mission` hints (`synthesis/service.py:622, 645–646,
     1202–1211`, ledger F-FUL-3); those `INDEXED BY` pins must be
     updated to the new index in the same PR (SQLite errors on a
     missing named index, which usefully pins the plan).
   Not needed (checked and rejected): `finding_citations(evidence_id)`
   — reverse lookups go through the PK; `evidence_withdrawals` — the
   UNIQUE(evidence_id) index already serves the EXISTS probes.
   Companion code-only changes in the same slice (no migration
   needed): share one snapshot-verification cache across the sources
   loop and citation batch inside `_assemble_brief`
   (`synthesis/service.py:967` vs `:1021`, ledger F-FUL-4 — halves
   hashing and audit probes per fulfillment), and reuse the
   materialized scoped-event set between preflight and assembly so
   the audit CTE runs once.
   Proof obligations: (a) canonical brief/packet bytes identical
   before/after on the golden corpus; (b) a fulfillment scenario that
   false-refuses under 0002 succeeds under 0003 within the same budget
   (regression test constructs scan-heavy unrelated audit history,
   which the review showed dominates); (c) the work guard still trips
   on genuinely oversized requests.
2. **0004_agent_inferences.sql** (post D-1/ADR 0007): two append-only
   STRICT tables + triggers, prefix `inf_`; no changes to existing
   tables.
3. **0005_run_origins.sql** (post D-2/ADR 0008–0009): append-only
   `run_origins` + `principal_grants` event tables + triggers.
4. **0006_external_artifacts.sql** (post D-3/ADR 0010): append-only
   registry + triggers.

Never in any migration: dropping/altering existing columns, weakening a
trigger or CHECK, data rewrites of research content, or an index whose
absence a test does not demonstrate.

## 18. Phased roadmap

Each phase states the full checklist demanded by this assignment. Later
phases are intentionally thinner: they must not pretend certainty their
gate decisions have not yet supplied. **Do not begin a gated phase
before its decision (section 24) is recorded by Kevin.**

### Phase 0 — Foundation stabilization (no gate)
- **User value:** the documented false-refusal defect goes away for
  realistic databases; small verified defects from the ledger are fixed;
  crash remnants become diagnosable.
- **Capability:** migration 0003; ledger `fix_now` items; `doctor`
  remnant enumeration (ADR 0006).
- **Data model / migration:** 0003 indexes only.
- **REST/CLI/MCP:** no contract changes; doctor output gains a bounded,
  read-only `remnants` section.
- **AuthN/AuthZ:** unchanged (single OS user).
- **Disclosure:** unchanged; doctor remnant output must name paths the
  operator already owns and nothing else.
- **Threat model:** no boundary change; ADR 0005/0006 record deltas.
- **Failure/recovery:** unchanged semantics; migration rollback =
  pre-upgrade backup + prior binary (existing documented procedure).
- **Idempotency/replay:** n/a.
- **Tests:** EXPLAIN-plan regression, determinism byte-equality,
  false-refusal reproduction, remnant-enumeration fixtures, plus one
  regression per fixed ledger item.
- **Operations:** README/SECURITY note that 0003 requires `minerva init`
  upgrade with standard backup procedure.
- **Rollback:** restore pre-upgrade backup with prior binary (already
  documented); indexes are additive so the old binary refuses newer
  schema version — documented, acceptable.
- **Non-goals:** no schema beyond indexes, no new surfaces, no auth.

### Phase 1 — Agent-inference door (gate D-1, ADR 0007)
- **User value:** model-drafted findings stop dying in the terminal;
  Kevin gets a permanent, honest record of what the model contributed,
  cited and labeled, without weakening the evidence model.
- **Capability:** `assist adopt` CLI verb; `agent_inferences` +
  mandatory citations; brief/packet export section labeled agent
  inference (schema bump to `minerva.research-brief.v3` **only if**
  packet must carry them — default recommendation: keep v2 unchanged
  and export inferences only in Markdown/an additive sidecar until a
  consumer exists; Opus must not fork v2 semantics casually).
- **Data model:** migration 0004 (above).
- **REST/CLI/MCP:** CLI only, mirroring the M2B decision; API read
  listing may follow later.
- **AuthN/AuthZ:** unchanged; adoption is an OS-user action.
- **Disclosure:** none new (content already local).
- **Threat model:** adopted text is untrusted model output persisting
  locally: injection-shaped adversarial tests, secret rescan at
  adoption, size bounds.
- **Failure/recovery:** adoption is a normal atomic mutation+audit
  transaction; a failed adoption leaves nothing.
- **Idempotency:** re-adopting the same candidate digest for the same
  claim is refused (unique constraint on request_sha256 + candidate
  index + claim).
- **Tests:** adversarial adoption fixtures, ledger-revalidation races
  (evidence withdrawn between candidates and adopt), export labeling,
  never-status-influence regression.
- **Operations:** none beyond migration procedure.
- **Rollback:** pre-upgrade backup; feature is additive.
- **Non-goals:** auto-adoption, API/web adoption, model-initiated
  anything, status/stance influence, additional providers.

### Phase 2 — Authenticated coordination (gate D-2, ADRs 0008 + 0009)
- **User value:** Athena can request and receive claim-scoped briefs
  without Kevin hand-carrying files, with real authentication instead
  of trust-by-filesystem.
- **Capability:** principal registry + grants (CLI-administered),
  authenticated local transport, adapter that verifies a request
  artifact from an authenticated principal, fulfills via the existing
  read-only path, and returns result+brief bytes; `run_origins`
  lineage.
- **Data model:** migration 0005.
- **Contracts:** existing artifact triple unchanged; optional
  `fleet.run-envelope.v1` transport wrapper.
- **AuthN/AuthZ:** section 15 in full; this phase IS that design.
- **Disclosure:** per-principal grant to receive brief bytes; grants
  are Kevin's explicit local action.
- **Threat model:** new ADR-0008 model (key theft, replay, floods,
  socket permissions).
- **Failure/recovery:** fulfillment unchanged (read-only, no-overwrite);
  transport failures leave no state; idempotent by request digest.
- **Idempotency/replay:** nonce set + digest-keyed prior-result reply.
- **Tests:** signature verification vectors, replay/nonce exhaustion,
  unauthorized-capability refusal, grant-revocation immediacy,
  adversarial envelope parsing, end-to-end request→brief round trip.
- **Operations:** key provisioning/rotation runbook; grant audit
  listing.
- **Rollback:** disable transport (config off = no listener), revoke
  grants; migration 0005 is additive.
- **Non-goals:** remote network exposure (stays banned pending D-4),
  Athena writing research state, envelope-as-authority, MCP.

### Phase 3 — Icarus exchange (gate D-3, ADR 0010)
Thin by design until D-3; the committed shape is: versioned
experiment-request/result artifacts, digest verification, and
import-before-evidence through the existing snapshot door with an
`external_artifacts` lineage registry (migration 0006). Everything else
(transport, who runs Icarus, result payload schemas) is speculative
until Icarus itself has a contract to offer. Non-goals now: Minerva
scheduling or supervising experiments; auto-import; treating result
digests as truth.

### Phase 4 — MCP read-only surface (gate D-5, after Phase 2)
Authenticated MCP server exposing read/verify tools (capabilities,
packet verify/inspect equivalents, request fulfillment under grants).
Recommendation stands: **do not add MCP now** — without Phase 2 there
is no authentication to build on, and an unauthenticated local MCP
would hand every local process the research corpus. Non-goals:
mutation tools, assist invocation, unauthenticated operation.

### Deliberately unscheduled (speculative; revisit only with a driving need)
Local source collections at scale, reviewed retrieval/OCR/PDF/crawling
(D-6), semantic/vector search, human review/escalation objects, bounded
research workers, fleet-level research operations dashboards. Each
requires its own ADR + threat model; none is entered lightly, and
several may belong to Athena or a new sibling instead of Minerva.

## 19. First 20 implementation issues

Ordered; 1–8 constitute Phase 0 (slice 1 = issues 1–6, see section 26).

1. Migration 0003 indexes + `EXPLAIN QUERY PLAN` regression harness
   proving the fulfillment path's hot queries use them.
2. False-refusal reproduction test: scan-heavy unrelated history
   database where a valid sparse request refuses under 0002 and
   succeeds under 0003 with the unchanged budget.
3. Determinism proof: golden corpus byte-equality across the 0003
   upgrade (brief export, packet verify, request fulfill outputs).
4. Ledger **wave A** fixes (section 27: F-DB-1 connect/init cleanup
   identity, F-OPS-2 restore error masking, F-OPS-3 backup sidecar
   refusal, F-AI-2 ANTHROPIC_AUTH_TOKEN, F-AI-3 OpenAI refusal
   ordering, F-GATE-1 static ban-list gaps, F-GATE-2 suite-wide
   network denial, F-SEC-1 packet error-code spoof, F-SEC-2 websocket
   scope bypass, F-VAL-1 UTF-8 encodability, F-VAL-2 finding citation
   bound, F-DB-2 recursive_triggers) with one invariant regression
   each. F-DB-1 and F-GATE-1 touch review-gated surfaces: flag them
   explicitly in the PR description for Kevin.
5. Docs: README/SECURITY/ARCHITECTURE note redeeming the "separately
   human-reviewed indexing migration" deferral; ADR 0005; brief ADR
   0004 amendment note extending identity-checked cleanup doctrine to
   connect/initialize (with F-DB-1's fix).
6. Coverage lift for `safe_artifact_file.py`, `core/operations.py`,
   `sources/integrity.py` error branches (target: every security-
   relevant branch exercised; do not chase the number, chase the
   branches).
7. `doctor` remnant enumeration (ADR 0006): orphan `.{db}.minerva-*.tmp`
   staging files, partial output directories, unmatched assist
   `requested` events — read-only, bounded, path-safe output.
8. Ledger **wave B** quality fixes (section 27: batch snapshot
   verification F-PERF-1, duplicated-helper consolidation F-DUP-1,
   supersession regression tests F-TEST-2, uncertainty error text
   F-VAL-3, package-data glob F-PKG-1, dead DTOs F-PAR-4, doc
   milestone-numbering F-DOC-1, identity-header denylist F-PAR-5) plus
   demo/docs polish.
9. (D-1) ADR 0007 draft for Kevin: persisted agent inferences.
10. (D-1) Migration 0004 + `assist adopt` service + CLI with
    adversarial adoption tests.
11. (D-1) Export labeling for adopted inferences (Markdown first; v2
    packet untouched).
12. (D-2) ADR 0008 draft: principals, transport choice, grants,
    replay.
13. (D-2) Principal/grant tables + CLI administration + audit
    vocabulary.
14. (D-2) Signed-envelope verification library + adversarial vectors.
15. (D-2) ADR 0009 + Athena adapter: authenticated request intake →
    existing fulfillment → result return; `run_origins`.
16. (D-2) Idempotency/replay store + already-fulfilled stable reply.
17. (D-3) ADR 0010 draft: experiment artifact pair + import-before-
    evidence.
18. (D-3) `minerva.experiment-request.v1`/`-result.v1` DTOs, golden
    fixtures, verify CLI.
19. (D-3) `external_artifacts` registry + import lineage wiring through
    existing `source import`.
20. (D-5) ADR 0011 + MCP read-only server behind Phase 2 auth.

## 20. Exact source files likely to change

Phase 0 (slice 1 bounded set):
- `src/minerva/core/migrations/0003_fulfillment_indexes.sql` (new; the
  loader glob-discovers packaged `NNNN_*.sql` files, requires contiguous
  versions from 1, and computes checksums itself — verified in
  `core/db.py:_migration_files` — so no registration edit is needed and
  `core/db.py` stays untouched)
- `src/minerva/synthesis/service.py` (update the forced `INDEXED BY`
  hints at lines 622 and 645–646 to the new claim-scoped index; no
  semantic query changes)
- `tests/test_database.py`, `tests/test_request_cli.py`,
  `tests/test_synthesis.py` (new regression tests), new
  `tests/test_fulfillment_indexes.py` if cleaner
- `tests/test_gate_scripts.py` (only if it pins migration counts)
- `docs/adr/0005-fulfillment-indexing.md`, `docs/DECISIONS.md`,
  `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `README.md`, `SECURITY.md`
  (the false-refusal caveat paragraphs get a "reduced by migration
  0003" update — do not delete the caveat: the guard still exists)
- Ledger fix_now items touch the exact files named in section 27.
- Doctor work: `src/minerva/core/doctor.py`, `src/minerva/cli/main.py`
  (doctor output), `tests/test_doctor.py`, `docs/adr/0006-*.md`.

Phase 1: `src/minerva/assist/{models,service}.py`,
`src/minerva/cli/main.py`, new migration 0004, `src/minerva/core/`
(audit event types), `src/minerva/synthesis/service.py` (Markdown
labeling), tests `test_assist.py`, `test_cli.py`, new
`test_agent_inferences.py`, docs ADR 0007 + PRD/ARCHITECTURE/SECURITY.

Phase 2: new `src/minerva/fleet/` (or `integrations/athena/` —
decide in ADR 0009; keep provider-adapter precedent of one reviewed
module), migration 0005, `scripts/static_security_check.py` (allowlist
change = security boundary, ADR-gated), CLI admin verbs, extensive new
tests, THREAT_MODEL rewrite.

## 21. Test and evaluation matrix

| Area | Existing anchor | Required additions (phase) |
| --- | --- | --- |
| Append-only triggers | test_database.py | none — keep |
| Citation integrity | test_evidence.py, test_synthesis.py | byte-equality across 0003 (P0) |
| Fulfillment bounds | test_request_cli.py | false-refusal repro + EXPLAIN-plan pin + still-trips-when-oversized (P0) |
| Safe file boundary | test_packet_cli.py, test_request_cli.py | error-branch coverage in safe_artifact_file (P0) |
| Restore/backup (ADR 0004) | test_cli.py, test_doctor.py | operations.py error branches; remnant enumeration fixtures (P0) |
| Assist consent chain | test_assist.py, test_ai_providers.py | adoption adversarial fixtures incl. injection-shaped statements (P1) |
| Determinism/golden | test_research_packet.py fixtures | corpus regeneration procedure documented; never regenerate to make a failure pass without diffing semantics (standing rule) |
| API/web boundary | test_web_security.py | none for P0; grants/authn suite (P2) |
| Auth/replay | — | signature vectors, nonce replay, revocation (P2) |
| Packaging | test_gate_scripts.py, scripts/ | keep; extend for any new package-data |
| Full gate | AGENTS.md list | run complete list per slice; report skips as open verification, never as pass |

Evaluation discipline: every invariant named in PRD "Domain invariants"
1–17 must keep at least one test that fails if the invariant is removed;
new invariants introduced by ADRs 0005–0011 join that list in the ADR
text itself.

## 22. Operational and backup requirements

Current, verified: SQLite online-backup API via `minerva backup`;
restore per ADR 0004 (staged, audited, deep-checked, exclusively
published); forward-only migrations with the documented
backup-verify-upgrade procedure; `doctor [--deep]` integrity checks;
no-overwrite everywhere; WAL sidecars respected and never deleted.

Standing requirements every phase must preserve:

1. **Backup before migrate, always.** Operator docs must repeat the
   procedure at every migration announcement: `minerva backup` →
   `minerva doctor --db <backup> --deep` → `minerva init`.
2. **Rollback is restore-with-prior-binary.** No in-place downgrade is
   ever implemented; each ADR restates this for its migration.
3. **Crash remnants are enumerable.** After Phase 0, `doctor` names
   (read-only) orphan staging files, partial export/output directories
   it can recognize, and unmatched assist `requested` events, so the
   documented operator-cleanup contracts become actionable.
4. **Keys and grants (Phase 2+) are operator-owned files** with owner-
   only modes, listed by an audit command, rotated by documented
   runbook; Minerva never generates or transmits them silently.
5. **No telemetry, ever, in any phase.** Operational visibility is
   local: audit ledger, doctor, health endpoints, exit codes.
6. **Disk growth is bounded by policy, not hope:** snapshot size bounds
   exist today; Phase 1+ tables carry the same bounded-text discipline
   (CHECK length bounds in schema, enforced again in services).

## 23. Rollout and rollback plan

Per slice (Opus repeats this loop):

1. Implement on `opus/minerva-vision-implementation`; keep Fable's
   planning commit intact.
2. Run the full 11-gate list; record exact results in
   `docs/OPUS_EXECUTION_STATE.md` (skips reported as open verification,
   never passes).
3. Inspect the diff for scope creep against the slice definition;
   update docs/ADRs in the same commit as the behavior they describe.
4. Commit the completed slice with its tests; push; PR review by Kevin
   is the human gate (AGENTS.md requires it for migrations and security
   contracts — that includes migration 0003).
5. Rollback story per slice: additive migrations → pre-upgrade backup +
   prior binary; new CLI verbs → absent verb, no data risk; Phase 2
   transport → config-off kill switch plus grant revocation; every
   slice must state its story in OPUS_EXECUTION_STATE.md before merge.

Repository-level rollback safety net: `main` is never pushed directly;
every change is a reviewed PR; the append-only database contract means
no upgrade rewrites research history, so a binary downgrade plus
restored backup always reproduces the pre-slice world exactly.

## 24. Open human decisions

Kevin must decide these explicitly; Opus must not infer an answer from
silence. Each lists the recommendation Fable would make, so a decision
can be a one-word reply.

- **D-1 — Persist human-adopted agent inferences?** Amends ADR 0003's
  "never persisted" promise into "never without explicit adoption."
  *Recommendation: yes, Phase 1 as specified; the current design loses
  the model-contribution provenance the doctrine wants kept.*
- **D-2 — Build the authenticated Athena seam now, and which transport?**
  (UNIX socket + signed envelopes vs. authenticated loopback HTTP.)
  This is the gate for Phases 2 and 4 and ADRs 0008/0009.
  *Recommendation: yes when Athena exists concretely; prefer UNIX
  socket + Ed25519 envelopes for the smaller ambient surface. If Athena
  is not imminent, defer the build but adopt ADR 0008 on paper so MCP
  and Icarus plans stop floating.*
- **D-3 — Icarus artifact contract now or when Icarus is real?**
  *Recommendation: draft ADR 0010 only when an Icarus repo/contract
  exists; premature contracts to imaginary consumers rot.*
- **D-4 — Remote access / multi-user: keep banned?**
  *Recommendation: keep banned; revisit only with a concrete need and
  a full new threat model (this plan contains no remote design).*
- **D-5 — MCP timing.** *Recommendation: defer until Phase 2 ships;
  read-only tools first; never unauthenticated.*
- **D-6 — Retrieval/OCR/PDF/crawling ingestion.** *Recommendation:
  keep out of Minerva entirely for this horizon; if the fleet needs
  web research, a separate collector produces files Kevin imports
  through the existing reviewed snapshot door.*
- **D-7 — Signed exports / origin assurance seam.** *Recommendation:
  defer; Phase 2 principals give a natural future signer identity, and
  doing it earlier duplicates that design.*
- **D-8 — License.** Explicitly deferred in DECISIONS.md as a human
  legal decision; remains open; nothing in this plan requires it.
- **D-9 — Finding retraction vs. permanent export block (ledger
  F-WDR-1/2).** Today, withdrawing evidence cited by any finding
  permanently blocks mission brief export and claim-scoped
  fulfillment, and deep doctor reports a standing integrity failure —
  after an *honest, documented* correction workflow. Options: (a) add
  a labeled, append-only finding-retraction/supersession record
  (analogous to evidence withdrawal) so exports can represent the
  finding as historically retracted — needs an ADR + migration and a
  v2-packet-validator decision; (b) declare permanent refusal
  intended doctrine and document it loudly. *Recommendation: (a); the
  current behavior punishes the exact correction discipline the
  doctrine demands. Also decide the narrower sub-question: should the
  refusal apply to optional citations on non-material statements at
  all (F-WDR-2)?*
- **D-10 — REST evidence-withdrawal endpoint and manifest taxonomy
  (ledger F-PAR-1/2).** The API can create evidence but not withdraw
  it, and the capability manifest's `.cli` suffix convention is
  inconsistent (`brief.export.markdown_json`). Either add the
  withdrawal endpoint + fix the taxonomy in a deliberate manifest
  revision, or record CLI-only withdrawal as an intentional boundary
  in DECISIONS.md. *Recommendation: defer the endpoint until D-2
  (first real protocol consumer), but record the boundary and fix the
  manifest label taxonomy now.*
- **D-11 — Restoring pre-upgrade backups with an upgraded binary
  (ledger F-OPS-4).** `restore_from` requires latest schema, so after
  an upgrade plus data loss, the only recovery is an unaudited manual
  copy + `minerva init`, which records the wrong provenance event.
  Options: allow restore to migrate the staged copy inside the audited
  staging pipeline (ADR 0004 review clause applies), or document the
  copy-then-init procedure and its provenance tradeoff.
  *Recommendation: allow staged migration during restore — the
  staging + deep-doctor pipeline already supports it safely.*

## 25. Explicitly rejected ideas

Considered during this review and rejected with reasons (rejections are
durable unless Kevin reopens them):

1. **Confidence scores, evidence-count heuristics, "truth" states** —
   violates the doctrine at its core; the schema deliberately cannot
   express them, and that inexpressibility is a feature to protect.
2. **Shared database or sibling package imports with Athena/Icarus** —
   destroys ownership, migration, and trust boundaries; ADR 0002
   already rejected it; nothing since weakens that reasoning.
3. **RPC/queue-style integration into Minerva services** — the artifact
   seam is safer, testable offline, replay-friendly, and already built.
4. **Unauthenticated MCP now** — hands the corpus to any local process
   and freezes an immature contract; rejected until ADR 0008 exists.
5. **Auto-adoption of model output, background/batch assist, provider
   fallback or retry** — reopens exactly the disclosure/cost/provenance
   holes ADR 0003 closed.
6. **Additional model providers or local-model adapters this horizon** —
   each multiplies the reviewed network surface; no driving need.
7. **Crawler/URL-fetch/OCR inside Minerva** — a collector belongs
   outside the trust boundary and its output enters through the
   existing reviewed snapshot door (see D-6).
8. **A second packet format or request/scope fields inside v2** —
   ADR 0002's reasoning holds; scope meaning stays in request/result
   binding.
9. **In-place or downgrade migrations, mutable audit, retention
   pruning of research history** — append-only is the product.
10. **Replacing the VM work budget with a wall-clock timeout** —
    nondeterministic refusals under load; the budget is the right
    instrument, indexes fix its false positives (Phase 0).
11. **Auto-cleanup of crash remnants** — ADR 0004's reasoning (never
    delete what you cannot prove you created) generalizes; doctor
    enumerates, the operator deletes.
12. **Coverage-number chasing** — raise branch coverage only through
    security-relevant branch tests (section 21); the 85% floor is a
    tripwire, not a goal.

## 26. Recommended first Opus implementation slice

**Slice 1 = Phase 0 issues 1–6: fulfillment indexing migration 0003 +
ledger wave A fixes + their regression tests + ADR 0005 (and the ADR
0004 amendment note for F-DB-1) + doc updates.**

- **User outcome:** valid research requests on realistic databases stop
  false-refusing with `brief_work_limit` (the confirmed ~60–70k-audit-
  row cliff moves out of ordinary reach); the confirmed high data-loss
  race and every wave A defect is fixed with a pinned regression; docs
  stop promising an indexing migration "later."
- **Scope:** exactly issues 1–6 in section 19; nothing else. Wave A =
  F-DB-1, F-DB-2, F-OPS-2, F-OPS-3, F-AI-2, F-AI-3, F-GATE-1,
  F-GATE-2, F-SEC-1, F-SEC-2, F-VAL-1, F-VAL-2, plus the slice-1 plan
  items F-FUL-3/F-FUL-4 folded into the migration work and F-TEST-1
  as issue 6.
- **Files expected to change:** section 20 Phase 0 list, plus the
  wave A files named in section 27.
- **Data-model impact:** additive indexes only (migration 0003).
- **Security impact:** two review-gated surfaces change — `db.py`
  connect/init cleanup identity (F-DB-1) and the static-gate ban list
  (F-GATE-1); both must be called out in the PR description for
  Kevin's review per AGENTS.md. Work guard retained and
  regression-proven to still trip on oversized requests.
- **Migration impact:** schema version 2 → 3; standard documented
  backup-first upgrade; old binaries refuse the newer schema (existing
  fail-closed behavior, documented).
- **Acceptance tests:** the three proof obligations of section 17 item
  1, plus one regression per fixed ledger item, plus the full 11-gate
  list green.
- **Rollback strategy:** pre-upgrade backup + prior binary (documented,
  unchanged); the slice's PR is revertible as a unit before merge.
- **Explicitly deferred:** doctor remnants and wave B (issues 7–8 —
  next slice), everything gated on D-1..D-11, any index not justified
  by an EXPLAIN-plan diff, any packet/schema change whatsoever
  (including the F-WDR-2 validator question, which waits for D-9).

Second slice (no new decision needed): issues 7–8 (doctor remnant
enumeration under ADR 0006 + polish). Third and later slices: strictly
per gates in section 24 — if no decision has been recorded, Opus stops
after slice 2 and reports.

## 27. Fable findings ledger

Method: eleven parallel deep-review agents covered the mandated areas;
every blocker/high/medium candidate was independently re-verified by an
adversarial agent instructed to refute it against the code. Verdicts:
**CONFIRMED** (verifier reproduced the behavior at the cited location)
or **—** (low/info findings, reviewed by Fable but not separately
re-verified). 53 raw findings consolidated to the entries below;
duplicates across dimensions are merged with all locations kept.
Dispositions: **wave A** = slice 1 fix set, **wave B** = slice 2 fix
set, **plan** = scheduled later work, **escalate** = Kevin decision
(section 24), **reject** = considered, not worth doing (reasons kept).

### Severity index

| ID | Sev | Verdict | Title | Disposition |
| --- | --- | --- | --- | --- |
| F-DB-1 | high | CONFIRMED | connect/init failure cleanup deletes by pathname; data-loss race | fix_now (wave A, Kevin review) |
| F-WDR-1 | medium | CONFIRMED | Withdrawing cited evidence permanently blocks mission export | escalate (D-9) |
| F-WDR-2 | medium | CONFIRMED | Withdrawn-citation refusal hits optional citations on non-material statements | plan (D-9) |
| F-OPS-2 | medium | CONFIRMED | Restore masks migration-state errors as "failed integrity validation" | fix_now (wave A) |
| F-FUL-1 | medium | CONFIRMED | Import-audit lookup full-scans global audit_events, ×2 per snapshot | plan (slice 1, migration 0003) |
| F-FUL-2 | medium | CONFIRMED | run.started CTE branch full-scans audit_events, ×2 per fulfillment | plan (slice 1, migration 0003) |
| F-AI-2 | medium | CONFIRMED | Anthropic fail-closed env list omits ANTHROPIC_AUTH_TOKEN | fix_now (wave A) |
| F-GATE-1 | medium | CONFIRMED | Static security gate misses process/egress primitives | fix_now (wave A, Kevin review) |
| F-DB-2 | low | — | recursive_triggers off: OR REPLACE bypasses append-only DELETE triggers | fix_now (wave A) |
| F-OPS-3 | low | — | backup_to lacks restore's destination-sidecar refusal | fix_now (wave A) |
| F-AI-3 | low | — | OpenAI adapter labels non-terminal responses as REFUSED | fix_now (wave A) |
| F-SEC-1 | low | — | Packet error-code classification spoofable via identifier substring | fix_now (wave A) |
| F-SEC-2 | low | — | Security middleware passes websocket scopes unchecked | fix_now (wave A) |
| F-VAL-1 | low | — | Undecodable argv/quote bytes surface as internal_error | fix_now (wave A) |
| F-VAL-2 | low | — | Finding citation-count bound exists only in the API adapter | fix_now (wave A) |
| F-GATE-2 | low | — | No suite-wide outbound-network denial in tests | fix_now (wave A) |
| F-PERF-1 | low | — | Per-card snapshot re-hash on ledger/finding/doctor paths | fix_now (wave B) |
| F-TEST-2 | low | — | Supersession workflows (withdrawn target, chains, N-to-1) untested | fix_now (wave B) |
| F-VAL-3 | low | — | Uncertainty NUL reported as size-limit failure | fix_now (wave B) |
| F-PKG-1 | low | — | web/static package-data glob non-recursive | fix_now (wave B) |
| F-PAR-4 | low | — | Dead DTOs HealthRead/ReadinessRead; endpoints hand-build JSON | fix_now (wave B) |
| F-DOC-1 | low | — | Milestone-numbering drift across doc titles | fix_now (wave B) |
| F-PAR-5 | info | — | Identity-header denylist omits common proxy headers | fix_now (wave B) |
| F-DUP-1 | low | — | Status-evidence + pagination helpers duplicated across services | fix_now (wave B) |
| F-FUL-3 | low | — | Claim-scoped finding queries scan all mission findings ×3 | plan (slice 1, migration 0003) |
| F-FUL-4 | low | — | Snapshot verification duplicated within one fulfillment | plan (slice 1, code-only) |
| F-TEST-1 | low | — | Error-branch coverage gaps in security-critical modules | plan (slice 1, issue 6) |
| F-OPS-1 | info | — | Orphan staging files invisible to doctor and docs | plan (slice 2, ADR 0006) |
| F-OPS-5 | low | — | Doctor mutates journal-mode header; wal/foreign_keys checks tautological | plan |
| F-OPS-6 | low | — | No directory fsync after export/backup/restore publication | plan |
| F-AI-4 | low | — | KeyboardInterrupt during provider call leaves no terminal audit event | plan |
| F-PAR-3 | low | — | Web mission list truncates at 100; CLI capped at 200; REST-only enumeration | plan |
| F-PAR-2 | low | — | Capability manifest `.cli` suffix taxonomy inconsistent | plan (D-10) |
| F-SYN-1 | info | — | Claim-scoped briefs exclude mission-level findings citing target-claim evidence | plan (document + pin test) |
| F-DUP-2 | info | — | Canonical-JSON/strict-parse helpers duplicated packet↔request | plan (dedicated reviewed change) |
| F-REL-1 | info | CONFIRMED (downgraded from medium) | Version 0.2.0a1 spans five functional states; no tags | plan |
| F-REL-2 | info | — | Agent provenance only in branch names; commit convention drifted | plan |
| F-TEST-3 | info | — | Coverage floor 85 sits ~4 points under actual | plan (ratchet to 88 after F-TEST-1) |
| F-AI-1 | info | — | Assist candidates ephemeral by contract; accepted work loses model-run provenance | escalate (D-1) |
| F-PAR-1 | info | — | Evidence withdrawal has no REST endpoint or manifest entry | escalate (D-10) |
| F-OPS-4 | info | — | No audited path to restore a pre-upgrade backup with an upgraded binary | escalate (D-11) |
| R-1..R-7 | info | — | Rejected items (below) | reject |

### High

**F-DB-1 — connect/init failure cleanup deletes by pathname and can
destroy a concurrently initialized live database.** CONFIRMED (high,
found independently by two dimensions).
*Location:* `src/minerva/core/db.py` — `Database.connect` (257–277),
`Database.initialize` (354, 429–435), `_remove_database_artifacts`
(244–247).
*Evidence:* `connect()` snapshots `path.exists()` before
`sqlite3.connect()` creates the file and, on failure, unlinks base +
`-wal/-shm/-journal` purely by pathname; `initialize()` mirrors this.
Two processes racing a fresh path both see `exists()==False`; the loser
(`migration_failed` or `database_busy`) unlinks the winner's committed
database and live WAL after the winner reported success. Also
reachable: a mutation command racing the first `minerva init`
(`database_unready` → cleanup unlinks mid-transaction); `minerva
mission create --db dangling-symlink` deletes the operator's symlink;
stale operator sidecars beside a nonexistent path are deleted on any
failed open. The identity-checked pattern already exists in the same
file (`_PrivateDatabaseFile.cleanup`, 137–144) and in
`operations._unlink_if_same`.
*Invariant:* PRD invariant 6 (failure must not leave misleading state —
here it destroys another process's committed domain+audit state); ADR
0004's doctrine that cleanup never removes state Minerva did not create.
*Impact:* silent loss of a just-initialized database, including audit
history, with a success report standing.
*Action:* (a) non-initialize connects open with `file:{path}?mode=rw`
URI so they never create and never clean up — a missing database
becomes an immediate error with zero filesystem side effects; (b)
`initialize()` on a fresh path creates the file with `O_CREAT|O_EXCL`
(or stages + hard-links like restore) and restricts cleanup to a
dev/inode-identity-checked file this process created; (c) never unlink
sidecars the process did not create; (d) short ADR 0004 amendment note
+ regression test mirroring
`test_database_cleanup_preserves_concurrent_replacements`.
*Disposition:* fix_now (wave A) — flag prominently for Kevin's PR
review; this touches the migration/connection trust surface.

### Medium

**F-WDR-1 — Withdrawing cited evidence permanently blocks mission brief
export with no remediation path.** CONFIRMED.
`synthesis/service.py:1231–1238` raises `citation_withdrawn` on every
brief path (CLI preview/export, web, API preview, request fulfillment);
findings/citations are append-only, withdrawal irreversible
(UNIQUE(evidence_id)), no retraction record exists; deep doctor also
reports `finding_integrity=False` for this honest state
(`core/doctor.py:229–235`). The documented correction workflow
(withdraw bad evidence) therefore permanently disables the milestone's
core deliverable for the whole mission. Invariant 8 is honored *by
refusal*; the gap is the 3+8+append-only interaction. → escalate D-9.

**F-WDR-2 — The withdrawn-citation refusal also applies to optional
citations on explicitly non-evidentiary statements.** CONFIRMED.
The check loop (`synthesis/service.py:1231–1243`) runs before the
statement-kind branch, and `research_packet.py:584–595` hard-codes the
same for AssumptionRecord/UnresolvedQuestionRecord — stricter than PRD
invariant 8, which mandates refusal for *material* findings only; the
tests bless optional citations on non-material statements but never
test their withdrawal. Same permanent-block consequence; misleading
"cannot support a finding" message for statements that assert no
support. → plan under D-9 (touches the v2 packet validator, needs the
ADR, align service + validator together).

**F-OPS-2 — Restore reports healthy pre-upgrade or too-new backups as
"failed integrity validation".** CONFIRMED.
`db.py:515–528` wraps `_validate_migration_state(source,
require_latest=True)` in a blanket except that re-raises everything as
`backup_invalid` ("The backup failed integrity validation."), masking
`database_migration_required` / `database_too_new` /
`migration_checksum_mismatch`. At recovery time an operator may
conclude a good backup is corrupt and discard it — the doctrine's
worst failure mode (manufactured certainty about corruption).
→ wave A: preserve the underlying code (or add
`backup_migration_required`), regression test with a
truncated-migration backup.

**F-FUL-1 — Per-snapshot import-audit lookup full-scans the global
audit_events table twice per cited snapshot.** CONFIRMED empirically.
`sources/integrity.py:42–53`: `WHERE event_type = ? AND entity_id = ?`
has no usable index; EXPLAIN shows `SCAN audit_events`; measured
600,028 VM steps over 200,001 rows (~3/row); runs twice per distinct
snapshot (sources loop + citation batch, separate caches). With ~20
snapshots the 8M budget dies at ~60–70k total audit rows across ALL
missions. → migration 0003 `idx_audit_event_entity` (slice 1).

**F-FUL-2 — run.started branch of the scoped audit CTE full-scans
audit_events and executes twice per fulfillment.** CONFIRMED
empirically. `synthesis/service.py:104–112` plans as `SCAN started`
probing an automatic index on the tiny CTE; ~600k VM steps against
200k unrelated audit rows, doubled (preflight + assembly); the
mission-export path `_packet_audit_references` (735–747) shares the
missing index. → same index; optionally reuse the materialized
scoped-event set so the CTE runs once (code-only).

**F-AI-2 — Anthropic fail-closed environment list omits
ANTHROPIC_AUTH_TOKEN.** CONFIRMED against installed SDK internals.
`anthropic.py:35` blocks only `ANTHROPIC_CUSTOM_HEADERS`; anthropic
0.118.0 skips ambient `ANTHROPIC_AUTH_TOKEN` only because of a
non-upstreamed hand-written guard, and the pin `>=0.117,<1` admits
versions without it; the bearer-header builder attaches `Authorization:
Bearer` alongside `x-api-key` when auth_token is set. Drift from ADR
0003's fail-closed principle (the OpenAI list is complete by
comparison). → wave A: add to `_UNSUPPORTED_SDK_ENVIRONMENT` + test
parameter + ADR 0003 list note.

**F-GATE-1 — Static security gate ban list misses process/egress
primitives.** CONFIRMED by probe: `os.posix_spawn(p)`,
`multiprocessing.Process().start()`, `ProcessPoolExecutor()`,
`webbrowser.open()`, `ctypes.cdll.LoadLibrary()`/`ctypes.WinDLL()`,
`loop.getaddrinfo()` (DNS exfiltration channel), `loop.sock_connect()`
all pass with zero violations while control probes are flagged.
No runtime violation exists today; the risk is silent future drift
past a gate the docs describe as static enforcement. → wave A: extend
the frozen sets + one parametrized negative probe per new ban in
`test_gate_scripts.py`; Kevin review (security gate change).

### Low — wave A (slice 1 fixes)

**F-DB-2 — recursive_triggers off; OR REPLACE bypasses append-only
DELETE triggers.** Verified empirically on SQLite 3.45.1: `INSERT OR
REPLACE` silently deletes+rewrites a trigger-protected row unless
`PRAGMA recursive_triggers=ON`. No shipped SQL uses OR REPLACE; this
hardens the trigger contract against future drift. One pragma in
`Database._connect` + one test asserting OR REPLACE aborts.

**F-OPS-3 — backup_to lacks destination-sidecar refusal.** Restore
checks `_reject_restore_destination_sidecars`; backup publishes beside
stale `X-wal/-shm/-journal`, deferring the failure to restore time
(`backup_not_standalone`) — the worst moment. Mirror the refusal +
parametrized test.

**F-AI-3 — OpenAI adapter classifies non-terminal/failed responses with
a refusal item as REFUSED.** `openai.py:119–140` checks `_has_refusal`
before `status != "completed"`; a failed/cancelled/in-progress response
with refusal content commits an `assistance.invocation.refused` audit
event for an outcome Minerva never observed (invariant 12 honesty).
Reorder the status check + fake-response test.

**F-SEC-1 — Packet error-code classification spoofable via substring
match.** `research_packet_file.py:169–176` matches the digest-failure
phrase as a substring of `detail["msg"]`; identifiers are unconstrained
and embedded in semantic ValueErrors, so a crafted packet steers
`packet_invalid` → `packet_digest_mismatch` (verified against venv
pydantic). Rejection still happens (exit 3). Tighten to `loc == ()` +
exact-match; mirror in the request adapter; regression test.

**F-SEC-2 — Security middleware forwards non-HTTP ASGI scopes
unchecked.** `web/security.py:315–318` passes websocket scopes to the
inner app with no Host/Origin/body enforcement. Unexploitable today
(no websocket routes; plain uvicorn); silently voids the documented
boundary if one is ever added. Allow only `http` (checked) +
`lifespan`; reject others; test.

**F-VAL-1 — Undecodable argv/content bytes surface as
`internal_error`.** Surrogate-escaped argv passes `validate_text`
(`core/types.py:64–84`) and dies at sqlite3 binding as bare-Exception
exit 1; `evidence add --quote` dies at `quote.encode()` similarly
(`evidence/service.py:49,84`); the API content encode at
`api/routes.py:485` would 500. All fail closed (rollback confirmed)
but misreport operator input as a Minerva bug. Add strict-encodability
to `validate_text`, wrap the two encode sites into domain errors +
CLI regression tests.

**F-VAL-2 — Finding citation-count bound lives only in the API
adapter.** `FindingCreate` caps at 100; the service and CLI accept
unbounded lists (AGENTS.md forbids adapter-only validation), and a CLI
operator can push `finding_citations` past `MAX_SYNTHESIS_REFERENCES`,
self-inflicting a permanent `brief_work_limit` export refusal. Move
the bound into `ResearchService.add_finding` + stable error + test.

**F-GATE-2 — No suite-wide outbound-network denial.** Fakes-only is
enforced by convention plus three local patches (demo/packet/request
tests). Add an autouse conftest fixture denying non-loopback
`socket.connect`/`create_connection` with the existing canary pattern,
keeping the stricter local total-denial patches.

### Low — wave B (slice 2 fixes)

**F-PERF-1 — Per-card snapshot re-hash on hot paths** (three dimensions
flagged): `_ledger_entries_from_rows` (`evidence/service.py:331`),
`add_finding` loop (`research/service.py:330–336`), read paths
(`research/service.py:756–772, 891–914`), doctor loops
(`core/doctor.py:187–194, 229–235`) each construct a fresh
`snapshot_cache`, re-reading and re-SHA-256-ing the same BLOB per card
(≈200 MiB redundant work per 200-entry ledger page; gigabytes for a
100-citation finding on 20 MiB snapshots). The batch verifier with a
shared cache exists and synthesis already uses it. Switch call sites;
semantics unchanged; pin with the existing batching-count test pattern.

**F-TEST-2 — Supersession workflows untested.** Superseding a withdrawn
card (the documented correction flow), three-card chains, and N-to-1
supersession are all currently legal and consistent across service/
export/packet layers but have zero regression tests; document the DAG
semantics while adding them.

**F-VAL-3 — Uncertainty NUL misreported as size failure**
(`research/service.py:310–312`): split the conditions under the
existing `uncertainty_invalid` code.

**F-PKG-1 — `web/static/*` glob non-recursive** (pyproject:68) unlike
templates; a future nested static asset ships a silently broken wheel
that verify_dist can only half-catch. Add `web/static/**/*` + a gate
test tying the tree to `EXPECTED_RESOURCES`.

**F-PAR-4 — Dead DTOs** `HealthRead`/`ReadinessRead`
(`api/models.py:197,207`): endpoints hand-build JSON; construct through
the DTOs (preferred) or delete them.

**F-DOC-1 — Milestone-numbering drift:** PRD title omits 1.1,
THREAT_MODEL omits 1.2, README labels the base slice 1.1. One
docs-only normalization pass.

**F-PAR-5 — Identity-header denylist misses `X-Remote-User`,
`X-Forwarded-User`, `X-Auth-Request-User/Email`** and applies only to
`/api/v1`. Trust boundary intact (nothing consumes headers); extending
the frozenset widens the loud misdeployment signal. One-line + test.

**F-DUP-1 — Duplicated validation helpers:**
`_claim_status_evidence_valid` byte-identical in research + synthesis
services (the packet validator's independent copies are intentional);
`_validate_page_request` duplicated verbatim. Consolidate the
service-layer copies into one shared pure helper with a
cross-reference comment; a one-sided future edit would brick export
fail-closed until re-synced.

### Plan (scheduled, non-wave)

- **F-FUL-3** (slice 1, migration 0003): `idx_findings_claim` +
  `INDEXED BY` hint updates — claim-scoped queries currently scan all
  mission findings ×3 (`synthesis/service.py:603–654, 1202–1211`).
- **F-FUL-4** (slice 1, code-only): share one snapshot-verification
  cache across `_assemble_brief`'s sources loop and citation batch
  (`:967` vs `:1021`) — halves hashing and audit probes per
  fulfillment.
- **F-TEST-1** (slice 1, issue 6): error-injection tests for
  `safe_artifact_file.py` (73%), `core/operations.py` (66%),
  `sources/integrity.py` (77%) — the fail-closed branches are the
  security contract; several are asserted only by documentation.
- **F-OPS-1** (slice 2, ADR 0006): doctor enumeration of orphan
  `.{db}.minerva-*.tmp` staging files (full sensitive DB copies as
  dotfiles), partial outputs, unmatched assist `requested` events;
  README staging-convention note. Report-only, never delete.
- **F-OPS-5:** doctor's `read()` connection executes `PRAGMA
  journal_mode=WAL` — a persistent header write on the inspected file
  — and its wal/foreign_keys checks re-read what `_connect` itself
  forced (constant-true). Open read-only (`mode=ro`), report the
  persisted journal mode, extend `test_doctor_is_read_only` to assert
  byte-identity.
- **F-OPS-6:** no directory fsync after `_write_exclusive`,
  `_publish_private_database`, or staged cleanup — a reported+audited
  export/backup/restore publication can vanish on power loss while
  its audit row survives. fsync the directory fd (export already
  holds it) or extend ADR 0004's consequences honestly.
- **F-AI-4:** `generate_finding_candidates` records no terminal audit
  event when KeyboardInterrupt escapes the provider call although
  control returns to Minerva; add a BaseException arm recording
  `outcome_unknown` best-effort before re-raising (design care: a
  second Ctrl-C must not mask the first).
- **F-PAR-3:** web mission list silently truncates at 100 (no
  indicator), CLI caps at 200 (no cursor); short-term truncation
  indicator, longer-term paging (UX decision).
- **F-PAR-2:** manifest taxonomy (`brief.export.markdown_json` without
  `.cli`) — fold into D-10's deliberate manifest revision; the string
  is pinned in routes.py, test_api.py, and installed_smoke.py.
- **F-SYN-1:** claim-scoped packets exclude mission-level findings
  even when they cite target-claim evidence (`synthesis/
  service.py:1202–1211`); invariant 16 doesn't specify finding
  scoping. Document the rule (claim-linked only) or extend selection;
  either way pin with a test.
- **F-DUP-2:** `_canonical_json_bytes`/`_strict_json_loads`/
  `_require_bounded_json_shape` are character-identical between
  packet and request modules — digest-critical duplication. Dedicated
  reviewed change (shared helper or byte-equivalence test); do not
  bundle.
- **F-REL-1** (downgraded medium→info by verification: real, but no
  written contract violated): version 0.2.0a1 spans five functional
  states (~5.8k lines) with zero git tags; SECURITY.md asks reporters
  to name affected versions they cannot name. Bump per milestone
  merge; retro-tag 876f790/7cf6439/5868a12/4977f5a if useful.
- **F-REL-2:** agent provenance lives only in branch names (codex/*,
  sol/*, fable/*); commit-prefix convention silently dropped in PRs
  #5–#7. Add a commit/attribution convention to CONTRIBUTING.
- **F-TEST-3:** coverage floor 85 vs actual 89.04 — ratchet to 88
  after F-TEST-1 lands; never chase the number.

### Escalated to Kevin

- **F-AI-1 → D-1** (ephemeral-by-contract candidates mean an operator
  who accepts a model draft retypes it as an ordinary finding, losing
  the machine-readable link to the assist run recorded in audit; the
  persistence design is section 12 / ADR 0007 and is Kevin's call
  because ADR 0003 promises "never persisted").
- **F-WDR-1 → D-9** (finding retraction vs permanent export block).
- **F-PAR-1 → D-10** (REST evidence-withdrawal endpoint or documented
  CLI-only boundary; API tests currently reach withdrawal only by
  calling the service directly).
- **F-OPS-4 → D-11** (`restore_from` requires latest schema; after
  upgrade + data loss the only path is unaudited copy+init recording
  the wrong provenance event).

### Rejected (considered; reasons preserved)

- **R-1** DB CHECK against self-referential `supersedes_evidence_id`:
  unreachable through every service path; direct-SQL writers are
  outside the trust boundary and already fail closed at export.
- **R-2** Depth/width preflight runs post-decode; extreme nesting maps
  to `*_malformed` not `*_too_complex`: cosmetic code choice; memory
  is bounded by pre-decode caps; optionally clarify ARCHITECTURE
  wording only.
- **R-3** Backup compensation stat→unlink TOCTOU: reversing order
  would leave a worse residue (audit event with no file); actor is
  inside the documented trust boundary.
- **R-4** Backup cleanup captures identity post-publication:
  sub-millisecond window, same-OS-user actor, correctly inode-guarded
  otherwise.
- **R-5** Unused `EXIT_USAGE` constant: keep as documentation of the
  argparse-owned exit code.
- **R-6** AST gate evadable via `getattr` string-building: inherent
  static-analysis limit; MIN003/MIN005 block generic laundering;
  optionally note in the script docstring.
- **R-7** Fulfillment artifacts lack directory fsync: docs already
  declare publication non-crash-atomic and the result manifest's
  SHA-256 makes partial publication detectable (the export/backup
  variant stays open as F-OPS-6 because there an *audited success*
  can vanish).

## 28. Verification evidence and unavailable checks

All eleven AGENTS.md gates were run at `4977f5a` in the locked
environment (`uv 0.11.x`, CPython 3.12.3, Linux 6.18.5) during this
review. Exact results:

| Gate | Result | Evidence |
| --- | --- | --- |
| `uv sync --frozen --extra dev` | PASS | 41 packages installed from lockfile, no drift |
| `uv run ruff check .` | PASS | "All checks passed!" |
| `uv run ruff format --check .` | PASS | 72 files already formatted |
| `uv run mypy` | PASS | strict; no issues in 51 source files |
| `uv run pytest` | PASS | 547 passed, 1 warning; branch coverage 89.04% ≥ 85% floor |
| `uv run python -m build` | PASS | sdist + wheel built |
| `uv run python scripts/verify_dist.py dist` | PASS | wheel and sdist verified |
| `uv run python scripts/installed_smoke.py dist` | PASS | installed-wheel smoke outside checkout |
| `uv run python scripts/static_security_check.py` | PASS | 49 files, 0 violations |
| `uv pip check` | PASS | 41 packages compatible |
| `git diff --check` | PASS | clean |

Unavailable / not-run checks (reported as open verification, not passes):

- **Live provider behavior** — never exercised, by contract (AGENTS.md
  bans live/billable providers in tests and review). All provider
  evidence is from fakes and code reading.
- **Python 3.13 / 3.14 matrices** — this environment ran 3.12.3 only;
  CI covers the matrix on push and was not re-executed here.
- **Non-Linux platforms** — out of the supported boundary; untested.
- **Coverage-floor caveat** — the pytest gate result includes coverage
  instrumentation; the lowest-covered security-relevant modules are
  listed in section 4 item 8 and targeted by issue 6.
- **Timing note** — the eleven gates were run against `4977f5a`
  (pre-merge tip of `main`); the only change merged since (PR #8) is
  this document, which no gate inspects, so the results transfer to
  the current `main`. Opus re-runs the full list per slice regardless.

Review methodology: all governing documents read in full (AGENTS,
README, CONTRIBUTING, SECURITY, PRD, ARCHITECTURE, ROADMAP,
THREAT_MODEL, DECISIONS, ADRs 0001–0004, pyproject); both migrations
read line-by-line; core/db.py migration loader, synthesis claim-scoped
SQL, static_security_check.py, and CI workflow read directly by Fable;
eleven parallel deep-review agents covered the mandated areas
(snapshot/citation integrity; evidence/claim semantics with
withdrawal/supersession; findings/uncertainty; audit atomicity and
triggers; backup/restore/export/crash; packet/request canonicalization
and digest semantics; fulfillment bounds and false-refusal risk;
provider consent/credentials/prompt-injection/timeouts; API/web/CLI
parity; tests/gates/packaging; Git/PR archaeology), and every
high/medium candidate finding was independently adversarially
re-verified against the code before entering section 27. Final
workflow accounting: 21 agents (11 reviewers + 10 verifiers), 642
tool uses, zero agent errors; 53 raw findings consolidated into the
ledger; verification confirmed 9 of 10 serious candidates at severity
and downgraded 1 (F-REL-1, medium → info). Several verifiers
reproduced their claims empirically (EXPLAIN QUERY PLAN and VM-step
measurements on schema replicas for F-FUL-1/2/3; live probe files
against the static gate for F-GATE-1; installed-SDK source inspection
for F-AI-2; SQLite OR REPLACE trigger-bypass demonstration for
F-DB-2).
