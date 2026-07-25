---
repository: Ayyitskevin/Minerva
phase: FABLE_PLANNING
status: PLANNING_IN_PROGRESS
base_commit: 4977f5aa40cc83a300d009cf3d8e4649cf68ae1d
---

# Fable Minerva game plan

This document is the complete Fable 5 planning deliverable for the two-stage
Fable → Opus assignment. It records a full repository review at
`base_commit` (`4977f5a`, the merge of PR #7, tip of `main`), a findings
ledger, a refined product vision, and an implementation-ready roadmap.
Opus 5 executes from this file; all handoff state is durable here.

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

The review found **no blocker-severity defect**. The dominant risks are
not bugs but structural pressures on the next stage of the vision:

1. **Availability debt in fulfillment.** The M1.3 work-budget guard is
   honest but the schema lacks the indexes its claim-scoped queries need
   (`findings(claim_id)`, `finding_citations(evidence_id)`,
   `audit_events(entity_id)`), so valid sparse requests on scan-heavy
   databases can false-refuse with `brief_work_limit`. The docs already
   defer this to "a separately human-reviewed indexing migration." That
   migration is the single highest-value, lowest-risk next change.
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
fix the small verified defects from the findings ledger (section 27) and
ship the fulfillment indexing migration (0003) with invariant-level
regression tests. It touches no trust boundary, requires no new human
decision, and directly reduces the one documented availability defect in
the fleet-facing contract.

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
file/symbol evidence. No blocker-severity findings were confirmed.

1. **Fulfillment false-refusal debt (planned, highest value).** The
   claim-scoped fulfillment path executes queries whose access paths are
   unindexed under migrations 0001–0002 (findings by claim,
   finding-citations by evidence, audit events by entity). On databases
   with large unrelated history, the cumulative VM-instruction budget
   trips and a *valid* request is refused with `brief_work_limit`. This
   is documented, deliberate, and deferred — and it is the main
   availability defect in the one artifact contract the future fleet
   depends on. (Ledger F-FUL-1.)
2. **Restore/backup/fulfillment crash windows are honest but
   operator-hostile.** Partial staging files, partial output
   directories, and unmatched assist `requested` audit events are all
   documented as operator-cleanup cases; nothing in `doctor` or the CLI
   helps an operator find or classify them. (Ledger F-OPS-1.)
3. **Assist candidates are ephemeral to a fault.** The operator cannot
   keep an accepted candidate without manually retyping it as a finding,
   which loses the machine-readable link between the model run recorded
   in audit and the human-authored finding derived from it. Evolving
   this touches ADR 0003's "never persisted" promise and is therefore a
   Kevin decision, not a background improvement. (Ledger F-AI-1.)
4. **Single-claim assist scope.** The bounded context covers one claim
   and its active ledger only; there is no cross-claim or
   mission-level assistance. This is by design for M2B; the plan keeps
   it that way until agent-inference persistence is decided.
5. **Coverage soft spots.** `safe_artifact_file.py` (73%),
   `core/operations.py` (66%), and `sources/integrity.py` (77%) have
   the lowest branch coverage in the tree; the uncovered branches are
   mostly error paths in exactly the code where error paths are the
   security contract. (Ledger F-TEST-1.)
6. **Web/API surface lags the domain model.** The HTML surface shows
   missions/claims/briefs but not findings, withdrawals, supersession
   chains, or audit; the API cannot withdraw evidence or record claim
   status reasons the CLI can. None of this violates a contract (CLI is
   the reference surface), but parity drift is accumulating. (Ledger
   F-PAR-1.)
7. **Fleet-vision gap, not defect:** no authentication design, no run
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
   Candidate set (final set must be justified by `EXPLAIN QUERY PLAN`
   diffs in the PR, not copied blindly):
   - `idx_findings_claim` ON findings(claim_id, created_at, id) WHERE claim_id IS NOT NULL
   - `idx_finding_citations_evidence` ON finding_citations(evidence_id, finding_id)
   - `idx_audit_entity` ON audit_events(entity_id, sequence)
   - possibly `idx_withdrawals_mission` ON evidence_withdrawals(mission_id, evidence_id)
   Implementation notes from code reading: claim-scoped finding queries
   currently filter `mission_id = ? AND claim_id = ?` through forced
   `INDEXED BY idx_findings_mission` hints (synthesis/service.py:622,
   645–646), so unrelated same-mission findings are scanned; migration
   0003 must update those `INDEXED BY` pins to the new index in the same
   PR (SQLite errors on a missing named index, which usefully pins the
   plan). The scoped audit CTE (synthesis/service.py:50–115) scans
   mission audit history via `idx_audit_mission` with per-row EXISTS PK
   probes, and its `research.run.started` branch joins on
   `audit_events.entity_id`, which has no index at all — candidates:
   `audit_events(mission_id, event_type, sequence)` and
   `audit_events(entity_type, entity_id, sequence)`.
   Proof obligations: (a) canonical brief/packet bytes identical
   before/after on the golden corpus; (b) a fulfillment scenario that
   false-refuses under 0002 succeeds under 0003 within the same budget
   (regression test constructs scan-heavy unrelated history); (c) the
   work guard still trips on genuinely oversized requests.
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
4. Ledger fix_now items (see section 27 final dispositions) with one
   invariant regression each.
5. Docs: README/SECURITY/ARCHITECTURE note redeeming the "separately
   human-reviewed indexing migration" deferral; ADR 0005.
6. Coverage lift for `safe_artifact_file.py`, `core/operations.py`,
   `sources/integrity.py` error branches (target: every security-
   relevant branch exercised; do not chase the number, chase the
   branches).
7. `doctor` remnant enumeration (ADR 0006): staging files, partial
   output directories, unmatched assist `requested` events — read-only,
   bounded, path-safe output.
8. Demo/docs polish pass from ledger `low` items worth keeping.
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
ledger fix_now items + their regression tests + ADR 0005 + doc
updates.**

- **User outcome:** valid research requests on realistic databases stop
  false-refusing with `brief_work_limit`; every small verified defect
  from this review is fixed with a pinned regression; docs stop
  promising an indexing migration "later."
- **Scope:** exactly issues 1–6 in section 19; nothing else.
- **Files expected to change:** section 20 Phase 0 list.
- **Data-model impact:** additive indexes only (migration 0003).
- **Security impact:** none to trust boundaries; migration merge
  requires Kevin's PR review per AGENTS.md; work guard retained and
  regression-proven to still trip on oversized requests.
- **Migration impact:** schema version 2 → 3; standard documented
  backup-first upgrade; old binaries refuse the newer schema (existing
  fail-closed behavior, documented).
- **Acceptance tests:** the three proof obligations of section 17 item
  1, plus one regression per fixed ledger item, plus the full 11-gate
  list green.
- **Rollback strategy:** pre-upgrade backup + prior binary (documented,
  unchanged); the slice's PR is revertible as a unit before merge.
- **Explicitly deferred:** doctor remnants (issue 7 — next slice),
  everything gated on D-1..D-8, any index not justified by an
  EXPLAIN-plan diff, any packet/schema change whatsoever.

Second slice (no new decision needed): issues 7–8 (doctor remnant
enumeration under ADR 0006 + polish). Third and later slices: strictly
per gates in section 24 — if no decision has been recorded, Opus stops
after slice 2 and reports.

## 27. Fable findings ledger

<!-- LEDGER_PENDING: filled from the completed review workflow before commit -->

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
  listed in section 4 item 5 and targeted by issue 6.

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
re-verified against the code before entering section 27.
