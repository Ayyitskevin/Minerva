---
repository: Ayyitskevin/Minerva
phase: FABLE_PLANNING
status: DRAFT
base_commit: b26268c33525f4852f9c31b90523fe128aa1a663
supersedes: docs/FABLE_MINERVA_GAME_PLAN.md
---

# Fable Minerva game plan 2

The first game plan (`docs/FABLE_MINERVA_GAME_PLAN.md`, base commit
`4977f5aa`) carried Minerva through Phase 0: the false-refusal indexing
defect, the data-loss initialization race, two waves of verified
hardening, operator remnant diagnostics, and — after Kevin recorded
decision gate D-9 — finding retraction. That plan is preserved unchanged
as the historical record; this plan supersedes it as the working
document. Everything below was re-verified against `main` at
`b26268c`, including the previous executor's own claims about what it
built.

## 1. Executive summary

Phase 0 is finished and verified. Between plan 1's base commit
(`4977f5aa`) and this plan's (`b26268c`), Opus delivered six slices
across three merged PRs: targeted fulfillment indexing (migration
0003), the staged-initialization fix for the data-loss race the first
review rated high, two waves of ledger hardening, operator remnant
notices, and — after Kevin recorded D-9, the first decision gate —
finding retraction (migration 0004). This plan re-ran every gate and
re-verified every load-bearing claim in `docs/OPUS_EXECUTION_STATE.md`
against the code before trusting any of it: all eleven AGENTS.md gates
pass at `b26268c` (628 tests, 90.12% branch coverage, 177
security-marked), and every checked slice claim held, with the
staleness and nuance corrections recorded in section 27.

The state of the repository is qualitatively different from plan 1's.
Then, the ledger held one high-severity data-loss defect and seven
mediums; now, the verification sweep found no defect of that class
outstanding, the correction vocabulary is complete (withdrawal for
evidence, retraction for findings), and the false-refusal availability
debt is paid and measured. What remains falls into exactly three
categories:

1. **One ungated phase (0C):** the surviving low-severity ledger items
   — doctor's inspection side effects, publication durability,
   interrupt audit honesty, web pagination, helper consolidation,
   release discipline — plus whatever this plan's fresh review sweep
   confirmed (section 27). Small, safe, and entirely within Opus's
   standing authority.
2. **Gated capability, waiting on one-word decisions (section 24):**
   the agent-inference door (D-1, the highest-leverage open decision),
   the authenticated Athena seam (D-2), Icarus artifacts (D-3), MCP
   (D-5), and the two small operational gates D-10/D-11.
3. **Deliberately unbuilt:** everything in section 25, kept out on
   purpose and re-affirmed.

The strategic picture for Kevin's workspace: Minerva's foundation
phase is over. Every further increment of value now runs through the
decision gates — which is by design, because each gate is a trust
boundary (what may persist, who may connect, what may be believed),
and those are Kevin's to open, not Fable's or Opus's. The
recommendation hierarchy is unchanged from plan 1 and sharpened by it:
record D-1 first; hold D-2 until Athena can hold a keypair; let
everything else follow need.

## 2. Current-state architecture

Verified directly against the tree at `b26268c`, not quoted from any
prior document.

**Runtime shape (unchanged in kind since plan 1, larger in surface):**

```text
CLI (argparse) ─┐
REST (/api/v1) ─┼─→ shared services ─→ SQLite (WAL, STRICT, append-only)
Web (Jinja2)   ─┘        │
                         ├─→ protocol layer (SQLite-independent):
                         │   minerva.research-brief.v2
                         │   minerva.research-request.v1
                         │   minerva.research-result.v1
                         │   minerva.capabilities.v2
                         └─→ assist (CLI-only, BYOK, preview→confirm,
                             ephemeral candidates; ADR 0003)
```

**Schema version 4** — four forward-only checksummed migrations,
fifteen tables, fourteen indexes, thirty triggers:

- Domain: `research_missions`, `research_questions`, `claims`,
  `claim_status_events`, `sources`, `source_snapshots`,
  `evidence_cards`, `evidence_withdrawals`, `findings`,
  `finding_citations`, `finding_retractions` (new in 0004),
  `research_runs`, `brief_exports`, `audit_events`; plus
  `schema_migrations`.
- Every research table is STRICT and append-only via
  `BEFORE UPDATE`/`BEFORE DELETE` `RAISE(ABORT)` triggers;
  `PRAGMA recursive_triggers = ON` on every connection closes the
  `INSERT OR REPLACE` bypass found in the first review.
- Migration 0003 added the two fulfillment indexes
  (`idx_audit_event_entity`, `idx_findings_claim`); 0004 added
  retraction. Both are additive-only.

**Module map** (`src/minerva/`): `core/` (db with staged
initialization, audit, operations backup/restore, doctor with the
notices channel, types, errors, packaged migrations), `sources/`,
`evidence/`, `research/` (now including `retract_finding`),
`synthesis/` (brief assembly + request fulfillment under the
8,000,000-step VM budget), `integrations/` (packet/request/result
contracts, safe artifact file I/O, two BYOK provider adapters),
`assist/`, `api/`, `web/`, `cli/`.

**Correction vocabulary is now complete and symmetric:** evidence has
withdrawal, findings have retraction; both are separate append-only
records that remove nothing, and both are CLI-only verbs. This was the
central gap plan 1 escalated (D-9); it closed without touching the v2
packet contract.

**Operational surfaces:** `minerva init|mission|question|claim|source|
evidence|finding|brief|packet|request|audit|doctor|backup|restore|
assist|serve` plus `minerva-demo`; `/api/v1` strict REST; loopback-only
server-rendered review UI; `/healthz`, `/readyz`, capabilities
manifest.

## 5. Refined Minerva vision

Kevin's stated ambition places Minerva as one pillar of a personal
AI-workspace: Athena coordinates, Icarus experiments, Minerva
remembers. The vision from plan 1 survives its second contact with the
codebase, and Phase 0 strengthened the argument for all three
refinements:

1. **Minerva is the *memory of why*, not a workflow engine.** Athena
   owns *who does what when*; Minerva owns *what is claimed, on what
   evidence, with what uncertainty*. The codebase kept refusing
   workflow gravity through Phase 0 — no approvals, no orchestration,
   ownership boundaries machine-readable in every packet. Keep
   refusing it.
2. **The unit of exchange is a verified artifact, never a connection.**
   The request/brief/result triple is now exercised end-to-end and
   indexed for realistic databases. Athena and Icarus integration must
   extend this pattern with authentication *around* it, never replace
   it with RPC into Minerva's services.
3. **Model output enters through exactly one door, and that door is
   still half-built.** Candidates exist, previews and digest-bound
   consent exist, but adoption does not: an operator who accepts a
   model draft retypes it and the model-contribution provenance the
   doctrine wants kept is lost. D-1 is the single highest-leverage
   decision in this plan, exactly as it was in plan 1.

What Phase 0 added to the vision: **corrections are first-class
epistemics.** A research memory that cannot honestly say "we no longer
assert this" is a liability, not a record. Withdrawal and retraction
now form a complete, symmetric correction vocabulary. Future surfaces
(adopted inferences, external artifacts) must ship with their
correction story stated up front, not discovered later the way D-9 was.

Restated one-line vision, unchanged: **Minerva is the fleet's
defensible research memory: every claim any agent relies on can be
traced to exact bytes, explicit stances, named uncertainty, and an
append-only account of who asserted what — and nothing else pretends to
be that.**

## 6. Athena / Minerva / Icarus responsibility map

| Concern | Athena (coordination plane) | Minerva (research intelligence plane) | Icarus (experiment plane) |
| --- | --- | --- | --- |
| Missions as work | Creates/assigns/monitors work missions, identities, approvals | Owns *research* missions as epistemic containers; Athena references them by ID, never writes them | Receives bounded experiment requests referencing Minerva claims |
| Identity | Issues and authenticates fleet identities | Maps *authenticated* callers to local `IdentityContext` at an adapter boundary; never trusts headers | Runs as its own identity; results carry it as metadata, not authority |
| Questions/claims/evidence/uncertainty | Read-only consumer via verified packets | Sole owner and system of record | Consumer of claim context in requests; producer of raw results only |
| Corrections | Never issues them | Sole owner: withdrawal and retraction are Minerva verbs recorded by the operator | Never issues them; a bad result is corrected by withdrawing the evidence that cited it |
| Requests for research | May *produce* `minerva.research-request.v1` files once the authenticated adapter exists | Verifies and fulfills; never fetches, never pushes | n/a |
| Experiment execution | Approves/schedules | Never executes; imports result artifacts as sources only after explicit verification + snapshot import + citation | Executes bounded, versioned experiments; returns result manifests (schema + SHA-256) |
| Truth/confidence | Never asserts | Never asserts; records stances and statuses | Never asserts; results are bytes with provenance |
| Storage | Own store | Own SQLite; no shared tables, no sibling imports (permanent) | Own store |
| Transport | Future authenticated channel (decision gate D-2) | Artifact seams only until D-2; loopback HTTP stays single-user | Same artifact discipline |

Permanent rules regardless of phase: no shared database, no sibling
package imports, artifact references are schema-version + SHA-256
(never paths/URLs to dereference), digests are never authentication,
external results become evidence only through explicit Minerva import
and citation.

## 7. Current-versus-target capability matrix

Status legend: **implemented** / **partial** / **planned** /
**unsupported** (not planned) / **speculative** (needs validation) /
**decision** (blocked on Kevin, section 24). Changes from plan 1 are
marked ∆.

| Capability | Current | Target | Status |
| --- | --- | --- | --- |
| Offline research vertical slice (missions→briefs) | Complete, gated | Keep; polish parity | implemented |
| Immutable snapshots, exact citations, append-only audit | Complete | Keep permanently | implemented |
| Deterministic canonical packet + offline verify/inspect | Complete | Keep; stable contract | implemented |
| Offline research request verify/fulfill | ∆ Complete, indexed, availability-tested | Keep | ∆ implemented (was partial) |
| Symmetric correction vocabulary (withdraw + retract) | ∆ Complete (migration 0004, D-9) | Keep permanently | ∆ implemented (was absent) |
| Operator crash-remnant guidance | ∆ `doctor` notices channel (ADR 0006) | Keep read-only, never auto-clean | ∆ implemented (was planned) |
| BYOK CLI assistance (preview/confirm/candidates) | Complete | Keep; no expansion of providers/surfaces | implemented |
| Persisted, human-accepted agent-inference objects | Absent (candidates ephemeral) | One reviewed door for model output | decision (D-1) → planned |
| Research-run lineage for external agent work | Runs exist, local kinds only | Bounded run/agent lineage records | planned (after D-2 shape known) |
| Authenticated Athena coordination adapter | Absent (correctly) | Token-authenticated local adapter producing/consuming existing artifacts | decision (D-2) → planned |
| Icarus experiment request/result artifacts | Absent | Versioned artifact pair + import-before-evidence workflow | decision (D-3) → planned |
| Evidence-preserving local source collections | Single-file import only | Batched import with per-file provenance | planned |
| Reviewed retrieval / OCR / PDF / crawling | Absent (banned) | Only via separate approved design | decision (D-6) / speculative |
| Semantic / vector search | Absent | Local, optional, index-only (never evidence) | speculative |
| MCP server | Absent (correctly) | Defer until D-2 authentication exists; read-only tools first | decision (D-5) |
| Bounded research workers / autonomous loops | Absent (banned) | Remains banned absent separate design | unsupported |
| Remote access / multi-user | Absent (banned) | Requires new auth + threat model | decision (D-4) |
| Signed exports / origin assurance | Absent (digests only) | Optional signing seam | decision (D-7) / speculative |
| Encryption at rest | Absent (documented) | OS-level guidance now; app-level speculative | speculative |
| Release discipline (tags, versions, provenance) | ∆ Still absent; version 0.2.0a1 spans seven functional states | Tagged releases with recorded gate evidence | planned (this plan, ungated) |

## 8. Product principles and permanent non-goals

Principles (all verified still true in code; keep them true):

1. Evidence and uncertainty are recorded, never manufactured; claim
   status is workflow, never truth; counts are never confidence.
2. Adverse evidence is structurally impossible to hide: complete-ledger
   fulfillment, stance preservation in every export, withdrawal as
   history rather than deletion.
3. Every material statement resolves to exact bytes a human can
   re-read.
4. Determinism before convenience: same state + same schema = same
   bytes, always.
5. Disclosure is explicit, previewed, and digest-bound; nothing leaves
   the machine that an operator did not see leave.
6. One command/service layer; adapters never own rules.
7. Artifacts over connections; verification before trust; digests bind,
   they do not authenticate.
8. Boundaries are stated in machine-readable form and kept truthful.
9. ∆ (new, earned by D-9) Corrections extend the record, never rewrite
   it — and every new persistence surface ships with its correction
   story designed in, not discovered in production.

Permanent non-goals (outside Minerva regardless of phase; section 25
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

Unchanged in structure from plan 1 — Phase 0 did not consume any of the
three planned additions, and nothing learned in Phase 0 invalidates
them. Renumbered to the migrations/ADRs that are actually free.

```text
                       (unchanged core)
CLI / REST / HTML --> commands/services --> SQLite (migrated, append-only)
                             |                    |
                             +--> protocol layer: research-brief.v2,
                             |    research-request.v1, research-result.v1,
                             |    capabilities.v2   (unchanged contracts)
                             |
        NEW (1) agent-inference door (post D-1, ADR 0008, migration 0005):
        assist CLI --> preview/confirm (unchanged) --> candidates
             --> EXPLICIT `assist adopt` --> persisted agent_inference
                 (labeled, cited, uncertainty-bearing, audited,
                  retractable from day one)

        NEW (2) authenticated coordination adapter (post D-2, ADRs 0009/0010,
        migration 0006):
        Athena --> authenticated local transport --> adapter
             --> maps identity --> produces/consumes the SAME inert
                 request/brief/result artifacts (no new query surface)

        NEW (3) experiment exchange (post D-3, ADR 0011, migration 0007):
        Minerva --> minerva.experiment-request.v1 (artifact out)
        Icarus  --> minerva.experiment-result.v1 + payload bytes
             --> operator/adapter verifies digest --> `source import`
                 (existing snapshot door) --> citation --> evidence
```

Non-negotiable structural rules carried forward: adapters stay thin;
the protocol layer stays SQLite-independent; new artifact contracts get
their own versioned schemas and golden fixtures; every new mutation
goes through a service that owns its transaction and audit row; every
new boundary gets adversarial tests before it ships; and (new) every
new persisted record type states its correction/retraction mechanism in
the same ADR that introduces it.

## 10. Domain-model evolution

Current model (verified): fifteen STRICT tables, append-only, schema
version 4. Evolution remains additive-only — no existing table, column,
trigger, or contract changes meaning. Proposed additions, in order:

1. **Migration 0005 — `agent_inferences` (post D-1, ADR 0008):**
   persisted, append-only, human-adopted inference records: id
   (`inf_` prefix, same CHECK shape as existing IDs), mission_id,
   claim_id, statement, uncertainty (required non-empty), provider,
   model, request_sha256 (links to the assist audit events),
   candidate_index, creator_id, run_id, created_at; plus
   `agent_inference_citations` mirroring `finding_citations` with
   NOT-NULL evidence references (an inference with zero citations is
   invalid by definition); plus — learned from D-9 —
   `agent_inference_retractions` in the *same* migration, mirroring
   `finding_retractions` exactly, so the correction story ships with
   the record type instead of being a later emergency. Never a stance,
   never a claim-status input, excluded from evidence ledgers, included
   in briefs only under an explicit labeled section.
2. **Migration 0006 — run lineage and principals (post D-2, ADRs
   0009/0010):** append-only `run_origins` (authenticated principal
   name, transport, request digest, credential fingerprint) and
   `principal_grants` (grant/revoke as events; current state = latest
   event). Local runs are unaffected; the adapter can never supply a
   run id or actor string directly.
3. **Migration 0007 — `external_artifacts` (post D-3, ADR 0011):**
   append-only registry (schema_version, sha256, byte_length,
   verified_at, imported_snapshot_id nullable) recording verify→import
   lineage so an imported Icarus result is traceable to its manifest
   without trusting either.

Explicitly rejected model changes (unchanged from plan 1, all still
right): mutable anything; a `true`/`score` column anywhere; storing
provider prompts/responses; cross-mission dedup of snapshots;
request/scope fields inside `research-brief.v2`.

## 11. Evidence and citation safety model

Unchanged foundation (re-verified in code, keep permanently): immutable
digested snapshots; zero-based half-open UTF-8 byte offsets; quote-byte
equality re-checked at creation, read, and export; mission-composite
foreign keys preventing cross-mission reference; withdrawal and
retraction as history; complete-ledger fulfillment preventing stance
suppression; material findings requiring same-mission citations, with
the withdrawn-citation refusal now correctly scoped to material
findings only (PRD invariant 8, tightened by D-9's implementation).

Additions this plan layers on top:

- **Import-before-evidence for external artifacts (D-3):** an Icarus
  result participates in research only as a normal imported snapshot
  plus citations. The `external_artifacts` registry links manifest
  digest → snapshot for provenance, but the *evidence rules do not
  change at all* — that is the point.
- **Inference citations are mandatory** for persisted agent inferences
  — stricter than findings, where assumptions and unresolved questions
  may be uncited: a model may only say things about cited evidence.
- **Every persisted statement type is correctable:** findings retract,
  inferences will retract from day one, and any future statement type
  must specify its correction record in its introducing ADR.
- **No new text-trust surfaces:** semantic search, if ever built,
  indexes snapshots/quotes but returns citations, never synthesized
  text.

## 12. AI / provider policy model

Current policy (ADR 0003, re-verified implemented): CLI-only, BYOK,
preview-then-confirm with exact digest, two pinned adapters, no
retry/fallback/tools/proxies, ephemeral candidates, metadata-only
audit, unknown-outcome honesty. This plan changes none of it in place.

Policy evolution, gated:

- **D-1 (agent-inference persistence):** adds one verb, `assist adopt`:
  after a normal preview→confirm→candidates round, the operator
  explicitly adopts at most one candidate by index in the same CLI
  session output. Adoption re-validates the candidate against the
  current active ledger (evidence may have been withdrawn between
  candidates and adoption), requires non-empty uncertainty, re-runs the
  secret-pattern scan over the adopted text, and persists it as an
  `agent_inference` record citing only authorized evidence IDs. ADR
  0003 must be amended by ADR 0008 (supersession note, not silent
  edit): "never persisted" becomes "never persisted *without a distinct
  explicit adoption action*." Everything else — ephemeral by default,
  no auto-adoption, no API/web surface — stands.
- **Additional providers / local models:** rejected for this planning
  horizon (section 25). Revisit only with a concrete fleet need.
- **Prompt-injection posture:** unchanged — untrusted research text,
  fixed instruction prompt, structured output, local validation, human
  review. When D-1 lands, the suite must gain injection-shaped
  fixtures: a candidate whose `statement` tries to smuggle
  instructions, markup, or secret-shaped content into a persisted,
  exported record.
- **What stays banned regardless:** model calls from API/web, URL
  retrieval, tools, autonomous loops, model-derived claim status,
  confidence scores.

## 13. Research-run and agent lifecycle

Current (re-verified): every mutation carries an `IdentityContext` (run
id, actor id, actor kind ∈ {os_user, system}); the first mutation in a
run inserts the run row in the same transaction; audit rows reference
the run. Sufficient lineage for a single trusted operator.

Target lifecycle for fleet work, phased (unchanged from plan 1):

1. **Now → D-2:** no change. External agents have no write path, so no
   agent lifecycle exists; anything claiming otherwise would be false.
2. **Post D-2:** an authenticated principal (e.g., `athena:planner-1`)
   maps at the adapter to a new actor kind (`external_agent`) recorded
   in `run_origins` with transport and credential fingerprint. Runs
   remain append-only and application-created; the adapter can never
   supply a run id or actor string directly — the no-actor-header rule
   generalizes.
3. **Bounded work, always:** an external run is created per verified
   request artifact, does exactly that request's work, and terminates.
   No standing sessions, no queues inside Minerva, no autonomous
   continuation. Idempotency: one request digest → at most one
   fulfillment output; replays are detected by digest and refused with
   a stable error.
4. **Agent inferences (post D-1)** record which provider/model/request
   produced them, permanently distinguishing machine inference from
   human synthesis in every export.

## 14. Protocol and artifact contracts

Implemented and stable (do not change): `minerva.research-brief.v2`,
`minerva.research-request.v1`, `minerva.research-result.v1`,
`minerva.capabilities.v2`. All strict, canonical, size-capped,
golden-fixtured. D-9 deliberately left v2 unchanged: a retracted
finding is absent from the packet, exactly as it was before the finding
was recorded.

One recorded future question (ADR 0007's closest rejected alternative):
whether a `minerva.research-brief.v3` should carry retracted findings
under an explicit flag, the way the ledger keeps withdrawn evidence
visible. The trigger for revisiting is a concrete consumer that needs
retraction history inside the packet rather than in the database and
audit ledger. Do not fork v2 semantics before that consumer exists.

Planned contracts (each ships with: schema doc section, strict DTO +
canonical serializer + verifier in `integrations/`, golden fixtures,
adversarial parse tests, and a capabilities entry only when usable):

- **`minerva.experiment-request.v1` (post D-3):** mission_id, claim_id,
  bounded hypothesis text drawn from the claim statement/falsification
  criterion, expected result schema, optional cited evidence context
  ids; NO execution parameters beyond a declared bounded profile name —
  Icarus owns execution semantics. Digest = self-consistency only.
- **`minerva.experiment-result.v1` (post D-3):** request digest, result
  payload schema + SHA-256 + byte length, Icarus run metadata as inert
  strings. Consumed only by verify → explicit `source import`.
- **Envelope (post D-2, if adopted):** the shared run envelope as a
  *transport* wrapper outside every artifact digest; correlation
  metadata, never authority. Version it separately
  (`fleet.run-envelope.v1`).

Contract rules: forward-only versioning; every field bounded; unknown
fields rejected; no paths/URLs/credentials/free-form authority
anywhere; digests never authenticate.

## 15. Authentication and authorization design

Nothing in this section is implemented until D-2 is decided; it is the
design Opus must hold future work against, and the reason MCP and any
Athena transport stay deferred. Unchanged from plan 1 in substance.

- **Principals:** named fleet identities issued by Athena (or by Kevin
  manually at first: a keyfile per agent). Minerva stores only public
  verification material and a local capability grant per principal.
- **Transport candidate (local-first):** UNIX domain socket with
  per-request signed envelopes (Ed25519 over canonical request bytes +
  monotonic nonce + expiry), or an authenticated loopback HTTP scheme
  carrying the same signed envelope. Decision belongs to D-2; both keep
  the no-remote-exposure rule intact.
- **Authorization model:** capability grants per principal, smallest
  useful set: `request:fulfill`, `packet:read`, later
  `inference:propose`. No principal ever gets raw SQL, mutation verbs,
  source import, or assist confirmation. Grants live in an append-only
  table with explicit revocation rows, administered only via local CLI
  by the OS user.
- **Authentication is never:** an actor header, a digest, possession of
  a request file, loopback origin, or an MCP session default.
- **Replay/idempotency:** signed envelopes carry nonce + expiry;
  Minerva keeps a bounded seen-nonce set per principal; a replayed
  fulfillment request returns the stable already-fulfilled error with
  the original result digest.
- **Audit:** every authenticated request records principal, capability,
  request digest, and outcome as bounded metadata audit events.
- **Threat-model delta to write with the ADR:** key theft from the
  Athena host, local malware replaying grants, socket permission
  tightening, request-flood rate bounds per principal, and the standing
  rule that same-OS-user malware is inside the boundary until D-4.

## 16. Proposed ADR sequence

Plan 1's proposed numbering is stale: 0005, 0006, and 0007 were
consumed by Phase 0's actual work (indexing, remnant notices,
retraction). The forward sequence renumbers accordingly. Order matters;
none may be skipped by implementation that needs it.

| ADR | Title | Gate | Contents |
| --- | --- | --- | --- |
| 0008 | Persistent human-adopted agent inferences | **D-1** | Amends ADR 0003's "never persisted" to "never persisted without a distinct explicit adoption action"; schema (including day-one retraction), citation mandate, ledger re-validation at adoption, export labeling, threat-model delta (injection via adopted text), non-goals (no auto-adopt, no API/web, no status influence) |
| 0009 | Fleet principal authentication and capability grants | **D-2** | Principals, transport, signed envelopes, grant/revoke events, replay defense, audit vocabulary, threat model; creates the first trust boundary beyond the OS user |
| 0010 | Athena coordination adapter over inert artifacts | **D-2** (after 0009) | Adapter consumes/produces existing request/brief/result artifacts under 0009 authentication; `run_origins` lineage; idempotency by request digest; no new query surface |
| 0011 | Icarus experiment request/result artifact contracts | **D-3** | `minerva.experiment-request.v1`/`-result.v1`, import-before-evidence via the existing snapshot door, `external_artifacts` registry, failure/replay semantics |
| 0012 | MCP read-only research surface | **D-5** (after 0009) | Authenticated MCP exposing verify/inspect/fulfill-equivalent read tools only; no mutation verbs; per-principal grants |
| 0004 amendment | Staged migration during restore | **D-11** | Allow `restore_from` to migrate the staged copy inside the audited staging pipeline before publication; deep-doctor on the migrated staging state; provenance events for restore-with-migration |

Any ADR that changes a security contract requires: threat-model diff,
negative tests named in the ADR, and Kevin's merge review (the AGENTS.md
red boundary already requires this).

## 17. Proposed migration sequence

Forward-only, checksum-recorded, one concern per migration, every one
preceded by a verified standalone backup in operator docs. Next free
number is 0005.

1. **0005_agent_inferences.sql** (post D-1, ADR 0008): three
   append-only STRICT tables + triggers — `agent_inferences`,
   `agent_inference_citations`, `agent_inference_retractions` — prefix
   `inf_`/`ret_`-style CHECKed IDs; no changes to existing tables.
2. **0006_run_origins.sql** (post D-2, ADRs 0009–0010): append-only
   `run_origins` + `principal_grants` event tables + triggers.
3. **0007_external_artifacts.sql** (post D-3, ADR 0011): append-only
   registry + triggers.

Never in any migration: dropping/altering existing columns, weakening a
trigger or CHECK, data rewrites of research content, or an index whose
absence a test does not demonstrate. (Phase 0 honored all four rules;
keep the streak.)

## 18. Phased roadmap

Each phase states the full checklist this planning protocol demands.
Later phases are intentionally thinner: they must not pretend certainty
their gate decisions have not yet supplied. **Do not begin a gated
phase before its decision (section 24) is recorded by Kevin.** Unlike
plan 1, there is exactly one ungated phase left; after it, every line
of forward motion runs through Kevin's decisions.

### Phase 0C — Ungated remainder (no gate; recommended first slice, section 26)

- **User value:** the last known honesty and durability gaps close:
  doctor stops modifying the database it inspects, published artifacts
  survive a crash directly after success, an interrupted provider call
  leaves an honest audit trail, the web surface stops silently
  truncating, and releases become identifiable.
- **Capability / scope:** the surviving ungated ledger items —
  F-OPS-5 (doctor opens the database read-write and rewrites the
  journal-mode header; inspect via immutable/read-only connection and
  make the wal/foreign_keys checks meaningful), F-OPS-6 (fsync the
  parent directory after export/backup/restore/fulfillment
  publication), F-AI-4 (KeyboardInterrupt during a provider call must
  write the terminal unknown-outcome audit event before propagating),
  F-PAR-3 (web mission list pagination instead of a silent 100-row
  truncation), F-SYN-1 (document the claim-scoped packet's scope
  boundary and pin it with a test), F-DUP-2 (consolidate the
  canonical-JSON/strict-parse helpers duplicated across the packet and
  request contracts into one reviewed module), F-REL-1/2 (tag a
  release, record the gate evidence, adopt the commit-attribution
  convention), F-TEST-3 (ratchet the coverage floor toward the actual
  figure) — plus the confirmed new findings of section 27 assigned to
  wave C.
- **Data model / migration:** none. If any wave-C fix turns out to
  need one, it leaves this phase and becomes a gated proposal.
- **REST/CLI/MCP:** no new surfaces; web pagination is a
  presentation-layer change inside the existing bounded contract.
- **AuthN/AuthZ:** unchanged (single OS user).
- **Disclosure:** unchanged; doctor output continues to carry counts,
  never paths or filenames.
- **Threat model:** no boundary change; SECURITY.md gains the
  durability statement (what fsync now guarantees and what it still
  does not — power loss inside SQLite's own WAL window is SQLite's
  contract, not Minerva's).
- **Failure/recovery:** strictly improved (durability + honest
  interrupt audit).
- **Idempotency/replay:** n/a.
- **Tests:** one regression per item, each verified to fail on the
  pre-fix code; doctor read-only proof (byte-compare the database file
  before/after `doctor --deep`); crash-window simulation for fsync
  (fault injection at the rename/link boundary); KeyboardInterrupt
  injection inside the provider-call window.
- **Operations:** release runbook (tag, gate evidence, changelog);
  README note on the doctor read-only guarantee.
- **Rollback:** every item is an independent pure-code commit.
- **Non-goals:** anything gated; any new table; any new surface.

### Phase 1 — Agent-inference door (gate D-1, ADR 0008, migration 0005)

- **User value:** model-drafted findings stop dying in the terminal;
  Kevin gets a permanent, honest record of what the model contributed,
  cited and labeled, without weakening the evidence model.
- **Capability:** `assist adopt` CLI verb; `agent_inferences` +
  mandatory citations + day-one retractions; Markdown brief section
  labeled as agent inference. The v2 packet is untouched: inferences
  export in Markdown (and optionally a separate additive sidecar
  artifact) until a consumer justifies a packet change.
- **Data model:** migration 0005 (section 17).
- **REST/CLI/MCP:** CLI only, mirroring the M2B decision; API read
  listing may follow later as a separate reviewed addition.
- **AuthN/AuthZ:** unchanged; adoption is an OS-user action.
- **Disclosure:** none new (content already local).
- **Threat model:** adopted text is untrusted model output persisting
  locally: injection-shaped adversarial tests, secret rescan at
  adoption, size bounds, and export labeling that cannot be confused
  with a human finding.
- **Failure/recovery:** adoption is a normal atomic mutation+audit
  transaction; a failed adoption leaves nothing; retraction handles
  regret.
- **Idempotency:** re-adopting the same candidate digest for the same
  claim is refused (unique constraint over request_sha256 +
  candidate_index + claim_id).
- **Tests:** adversarial adoption fixtures, ledger-revalidation races
  (evidence withdrawn between candidates and adopt), export labeling,
  never-status-influence regression, retraction round-trip.
- **Operations:** standard migration procedure (backup → init →
  doctor).
- **Rollback:** pre-upgrade backup; the feature is additive.
- **Non-goals:** auto-adoption, API/web adoption, model-initiated
  anything, status/stance influence, additional providers.

### Phase 2 — Authenticated coordination (gate D-2, ADRs 0009 + 0010, migration 0006)

- **User value:** Athena can request and receive claim-scoped briefs
  without Kevin hand-carrying files, with real authentication instead
  of trust-by-filesystem.
- **Capability:** principal registry + grants (CLI-administered),
  authenticated local transport, adapter that verifies a request
  artifact from an authenticated principal, fulfills via the existing
  read-only path, and returns result+brief bytes; `run_origins`
  lineage.
- **Data model:** migration 0006.
- **Contracts:** existing artifact triple unchanged; optional
  `fleet.run-envelope.v1` transport wrapper.
- **AuthN/AuthZ:** section 15 in full; this phase IS that design.
- **Disclosure:** per-principal grant to receive brief bytes; grants
  are Kevin's explicit local action.
- **Threat model:** new ADR-0009 model (key theft, replay, floods,
  socket permissions).
- **Failure/recovery:** fulfillment unchanged (read-only,
  no-overwrite); transport failures leave no state; idempotent by
  request digest.
- **Idempotency/replay:** nonce set + digest-keyed prior-result reply.
- **Tests:** signature verification vectors, replay/nonce exhaustion,
  unauthorized-capability refusal, grant-revocation immediacy,
  adversarial envelope parsing, end-to-end request→brief round trip.
- **Operations:** key provisioning/rotation runbook; grant audit
  listing.
- **Rollback:** disable transport (config off = no listener), revoke
  grants; migration 0006 is additive.
- **Non-goals:** remote network exposure (banned pending D-4), Athena
  writing research state, envelope-as-authority, MCP.

### Phase 3 — Icarus exchange (gate D-3, ADR 0011, migration 0007)

Thin by design until D-3; the committed shape: versioned
experiment-request/result artifacts, digest verification, and
import-before-evidence through the existing snapshot door with an
`external_artifacts` lineage registry. Everything else (transport, who
runs Icarus, result payload schemas) is speculative until Icarus itself
has a contract to offer. Non-goals now: Minerva scheduling or
supervising experiments; auto-import; treating result digests as
truth.

### Phase 4 — MCP read-only surface (gate D-5, after Phase 2)

Authenticated MCP server exposing read/verify tools (capabilities,
packet verify/inspect equivalents, request fulfillment under grants).
The recommendation stands: **do not add MCP before Phase 2** — without
it there is no authentication to build on, and an unauthenticated
local MCP would hand every local process the research corpus.
Non-goals: mutation tools, assist invocation, unauthenticated
operation.

### Small gated slices, schedulable independently

- **D-10 slice:** record CLI-only evidence withdrawal as a deliberate
  boundary in DECISIONS.md and fix the capability-manifest `.cli`
  taxonomy in one reviewed manifest revision; the REST withdrawal
  endpoint itself waits for the first real protocol consumer (D-2).
- **D-11 slice:** allow `restore_from` to migrate the staged copy
  inside the audited staging pipeline (ADR 0004 amendment), closing
  the pre-upgrade-backup recovery gap with provenance-correct audit
  events.

### Deliberately unscheduled (speculative; revisit only with a driving need)

Local source collections at scale, reviewed retrieval/OCR/PDF/crawling
(D-6), semantic/vector search, human review/escalation objects,
bounded research workers, fleet-level research dashboards. Each
requires its own ADR + threat model; several may belong to Athena or a
new sibling instead of Minerva.

## 19. First 20 implementation issues

Ordered. Issues 1–9 constitute Phase 0C (the recommended first slice
covers 1–6; section 26). Issues appended from section 27's new
findings are marked ∆ where they did not exist in plan 1.

1. F-OPS-5: doctor inspects via a read-only/immutable connection;
   prove read-only-ness by byte-comparing the database before/after
   `doctor --deep`; make the wal/foreign_keys checks assert the real
   database state rather than the inspection connection's.
2. F-OPS-6: directory fsync after every exclusive publication (brief
   export, backup, restore, fulfillment outputs, staged-init publish);
   fault-injection test at the publication boundary; SECURITY.md
   durability statement.
3. F-AI-4: KeyboardInterrupt (and every BaseException) inside the
   provider-call window writes the terminal unknown-outcome audit
   event before propagating; injection test for both adapters.
4. F-PAR-3: web mission-list pagination (bounded page size, explicit
   next/prev, no silent truncation); parity note for the CLI cap.
5. F-SYN-1: document the claim-scoped packet scope boundary
   (mission-level findings citing target-claim evidence are excluded
   by design) in the PRD and pin it with a regression test.
6. F-DUP-2: consolidate `_canonical_json_bytes`/`_strict_json_loads`
   and shared strict-parse helpers into one reviewed
   `integrations/canonical.py` used by both packet and request
   contracts; byte-identical golden fixtures prove no behavior change.
7. F-REL-1/2: tag `v0.2.0` at the Phase 0C tree with recorded gate
   evidence; adopt the commit-attribution convention in
   CONTRIBUTING/DECISIONS; document the release procedure.
8. F-TEST-3: ratchet the coverage floor from 85 to 88 (actual is
   ~90); keep the floor two points under actual so honest refactors
   do not flap the gate.
9. ∆ Wave-C additions from section 27 (final list after verification
   completes; each ships with its own regression).
10. (D-10) DECISIONS.md boundary record + capability-manifest
    taxonomy revision in one reviewed change.
11. (D-11) ADR 0004 amendment + staged-migration-during-restore +
    provenance-correct audit events + upgrade-recovery test.
12. (D-1) ADR 0008 draft for Kevin: persisted agent inferences,
    including the day-one retraction table and the ADR 0003
    amendment language.
13. (D-1) Migration 0005 + adoption service (ledger re-validation,
    secret rescan, size bounds) + `assist adopt` CLI verb.
14. (D-1) Markdown export labeling + doctor coverage for inference
    citation integrity + retraction round-trip tests.
15. (D-1) Injection-shaped adversarial fixtures: candidate statements
    carrying instruction-smuggling, markup, and secret-shaped content.
16. (D-2) ADR 0009 draft: principals, transport choice, grants,
    replay defense, threat model.
17. (D-2) Migration 0006 + principal/grant tables + CLI
    administration + audit vocabulary.
18. (D-2) Signed-envelope verification library + adversarial vectors.
19. (D-2) ADR 0010 + Athena adapter: authenticated request intake →
    existing fulfillment → result return; `run_origins`; idempotency
    store + already-fulfilled stable reply.
20. (D-3) ADR 0011 draft + experiment artifact DTO pair + golden
    fixtures + verify CLI + `external_artifacts` registry wiring
    through existing `source import`.

## 20. Exact source files likely to change

Phase 0C (issues 1–9):

- `src/minerva/core/doctor.py` (read-only inspection connection)
- `src/minerva/core/db.py`, `src/minerva/core/operations.py`,
  `src/minerva/synthesis/request_fulfillment.py` (directory fsync at
  publication boundaries)
- `src/minerva/assist/service.py` and/or both files under
  `src/minerva/integrations/ai/` (interrupt-safe terminal audit)
- `src/minerva/web/app.py` + `src/minerva/web/templates/` (pagination)
- `src/minerva/integrations/research_packet.py`,
  `src/minerva/integrations/research_request.py`, new
  `src/minerva/integrations/canonical.py` (helper consolidation)
- `pyproject.toml` (version, coverage floor), `docs/*` (release
  procedure, scope-boundary documentation), plus one test module per
  item.

Phase 1 (D-1): `src/minerva/core/migrations/0005_agent_inferences.sql`
(new), `src/minerva/assist/service.py`, `src/minerva/assist/models.py`,
`src/minerva/cli/main.py`, `src/minerva/synthesis/service.py`
(Markdown labeling only), `src/minerva/core/doctor.py`,
`scripts/verify_dist.py`, `tests/test_assist.py`,
`docs/adr/0008-*.md` (new), PRD/ROADMAP/DECISIONS/README.

Phase 2 (D-2): new `src/minerva/fleet/` (or `integrations/fleet/`)
package for envelope verification and the adapter;
`src/minerva/core/migrations/0006_run_origins.sql` (new);
`src/minerva/cli/main.py` (principal/grant administration);
`docs/adr/0009-*.md`, `docs/adr/0010-*.md` (new);
`docs/THREAT_MODEL.md` (first non-OS-user trust boundary).

Phase 3 (D-3): `src/minerva/integrations/experiment_request.py`,
`experiment_result.py` (new), migration 0007,
`docs/adr/0011-*.md` (new).

## 21. Test and evaluation matrix

Baseline at `b26268c` (verified in section 28): full AGENTS.md gate
suite green; suite of 628 tests; branch coverage ≈ 90%; 177
security-marked tests; golden fixtures byte-stable across migrations
0003 and 0004.

| Area | Existing proof | Phase 0C adds | Gated phases add |
| --- | --- | --- | --- |
| Snapshot immutability & citations | Trigger + tamper + double-read tests | — | inference citations reuse identical verifiers (D-1) |
| Append-only enforcement | Update/delete trigger tests, recursive_triggers regression | — | new tables ship with the same trigger tests (D-1/D-2/D-3) |
| Determinism | Golden fixtures, byte-equality across history/migrations | fixture byte-equality across helper consolidation (F-DUP-2) | inference labeling determinism (D-1); envelope excluded from digests (D-2) |
| Availability / work bounds | Budget-exhaustion + false-refusal regressions | — | per-principal rate bounds (D-2) |
| Fail-closed error paths | Tamper, sidecar, masking, interrupt suites | doctor read-only proof; fsync fault injection; KeyboardInterrupt injection | adoption-window races (D-1); replay/nonce exhaustion (D-2) |
| Disclosure control | Preview/digest-consent tests; non-reflective errors | — | adoption secret-rescan (D-1); grant revocation immediacy (D-2) |
| Provider adapters | Fakes-only, hostile-response fixtures | interrupt audit honesty | injection-shaped adopted-text fixtures (D-1) |
| Static/network gates | AST ban list + suite-wide socket denial | — | fleet package joins the same gates (D-2) |
| Release honesty | — | tag + recorded gate evidence (F-REL-1) | per-phase tagged releases |

Evaluation policy unchanged: a test that cannot fail is not evidence;
every regression lands with proof it fails on the pre-fix code; skipped
or unavailable checks are reported as open verification, never as a
pass.

## 22. Operational and backup requirements

Carried forward and re-verified; changes marked ∆.

- Backups are non-overwriting, sidecar-refusing (∆ now on both backup
  and restore ends), identity-checked on compensation, and audited;
  restore stages, deep-validates, and publishes exclusively, never
  removing a public replacement on failure.
- ∆ `doctor` now reports staging remnants and unfinished assistance as
  *notices*, never affecting `ok` and never auto-cleaning — ADR 0006's
  contract. Partial export/fulfillment output directories remain
  honestly undiscoverable, and the ADR says so.
- Upgrade procedure: verified standalone backup → `minerva init` →
  `doctor --deep`. An older binary refuses a newer schema version;
  recovery is restore-with-prior-binary. ∆ D-11 (staged migration
  during restore) would close the remaining gap: restoring a
  pre-upgrade backup after the binary upgraded.
- ∆ Directory-entry durability after publication (export, backup,
  restore, fulfillment outputs) is a known open item (F-OPS-6): a crash
  immediately after success can lose the directory entry while the
  audit row survives. Scheduled in this plan, ungated.
- Free-space and permission failures fail closed with stable errors;
  the demo refuses an existing database.

## 23. Rollout and rollback plan

Unchanged doctrine, restated against the current tree:

- Every slice is one reviewed commit on a dedicated branch, merged by
  Kevin through a PR that names its review-gated surfaces. `main` is
  never pushed directly.
- Migrations are additive and forward-only; rollback is always "restore
  the verified pre-upgrade backup with the prior binary into a new
  path." No in-place downgrade exists or will.
- Gated phases (D-1, D-2, D-3, D-5) each ship dark: the migration and
  service land first behind their CLI verb with no default-on behavior;
  the capabilities manifest advertises a surface only when it is
  usable and reviewed.
- A failed slice reverts as one commit; append-only tables guarantee
  research history survives any code rollback.

## 24. Open human decisions

D-9 is **RESOLVED** (option (a), delivered as Milestone 1.5 — the
labeled append-only retraction record; ADR 0007). Every other gate from
plan 1 remains open and is restated here so a decision can be a
one-word reply. Numbering is preserved so prior discussion stays
referable. Opus must not infer an answer from silence.

- **D-1 — Persist human-adopted agent inferences?** The single
  highest-leverage open decision. Today the assist surface produces
  candidates that die in the terminal: an operator who accepts one
  retypes it as a finding and the model-contribution provenance is
  lost, which is exactly the dishonesty-by-omission the doctrine
  exists to prevent. *Recommendation: yes — Phase 1 as specified,
  now including day-one retraction so the D-9 lesson is applied
  rather than relearned.*
- **D-2 — Build the authenticated Athena seam, and which transport?**
  Gates Phases 2 and 4 and ADRs 0009/0010. *Recommendation: yes when
  Athena exists concretely enough to hold a keypair; prefer UNIX
  socket + Ed25519 envelopes for the smaller ambient surface. If
  Athena is not imminent, adopt ADR 0009 on paper so MCP and Icarus
  plans stop floating.*
- **D-3 — Icarus artifact contract now or when Icarus is real?**
  *Recommendation: draft ADR 0011 only when an Icarus repo/contract
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
  defer; Phase 2 principals give a natural future signer identity,
  and doing it earlier duplicates that design.*
- **D-8 — License.** Explicitly deferred in DECISIONS.md as a human
  legal decision; remains open; nothing in this plan requires it.
- **D-10 — REST evidence-withdrawal endpoint and manifest taxonomy.**
  *Recommendation: defer the endpoint until D-2 (first real protocol
  consumer), but record the CLI-only boundary and fix the manifest
  label taxonomy now — the ungated recording half sits in Phase 0C
  issue 10 awaiting only your one-word go.*
- **D-11 — Restoring pre-upgrade backups with an upgraded binary.**
  *Recommendation: allow staged migration during restore — the
  staging + deep-doctor pipeline already supports it safely, and
  Phase 0's staged-initialize work made the pattern routine.*

## 25. Explicitly rejected ideas

Carried forward from plan 1 (all seven rejections re-affirmed) plus two
new entries earned in Phase 0:

- **R-1 Confidence scoring / truth determination** — permanently out;
  the doctrine is the product.
- **R-2 Additional model providers or local models now** — every
  adapter multiplies the reviewed audit surface; no fleet need exists.
- **R-3 Autonomous research loops / workers** — unbounded loops are
  banned by the assignment; bounded ones need Athena-side design first.
- **R-4 URL fetching / crawling / retrieval inside Minerva** — a
  separate collector may someday produce files for the reviewed import
  door; Minerva itself never fetches.
- **R-5 Shared database or package imports with siblings** — permanent.
- **R-6 Mutable records or in-place edits anywhere** — permanent;
  corrections are append-only records.
- **R-7 MCP before authentication** — an unauthenticated local MCP
  hands every local process the research corpus.
- **∆ R-8 Auto-retraction of findings on evidence withdrawal** —
  rejected in ADR 0007: withdrawing one of several citations may not
  invalidate a finding; Minerva records the operator's judgement
  rather than inferring it.
- **∆ R-9 Carrying retracted findings inside `research-brief.v2`** —
  rejected in ADR 0007 as a v2 change with no consumer; recorded as
  the v3 question in section 14 rather than silently dropped.

## 26. Recommended first Opus implementation slice

**Wave C hardening: issues 1–6 of section 19, one PR.** No gate blocks
it, every item has a verified defect or drift behind it, and the
pattern is proven — Opus shipped waves A and B the same way. Scope
discipline: one commit per concern inside the PR, one regression per
fix verified to fail on the pre-fix code, no migration, no new
surface, and the PR description names any review-gated file it
touches. Issues 7–8 (release tag + coverage ratchet) follow as a
second, trivially reviewable PR — a tag is only meaningful after the
tree it tags is final, so it must not share a PR with code changes.

If Kevin records D-1 before or during that work, Phase 1 (issues
12–15) becomes the next slice; its ADR draft (issue 12) can proceed in
parallel with wave C since it is a document, not code. If Kevin also
gives the one-word go on D-10's recording half (issue 10), it rides
along as its own commit.

What Opus must NOT do without a recorded decision, restated: persist
inferences (D-1), build any transport or principal machinery (D-2),
draft sibling contracts (D-3), expose anything beyond loopback (D-4),
add MCP (D-5), add retrieval (D-6), sign exports (D-7), choose a
license (D-8), add the REST withdrawal endpoint (D-10), or let restore
migrate (D-11).

<!-- SECTIONS 3, 4, 27, 28 PENDING VERIFICATION SWEEP RESULTS -->
