---
repository: Ayyitskevin/Minerva
phase: FABLE_PLANNING
status: READY_FOR_OPUS
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

The repository's foundation is materially stronger than plan 1's: the
data-loss race is closed and proven closed, append-only enforcement
survived hostile probing on all fifteen tables, determinism holds
byte-for-byte, and the provider boundary matches ADR 0003 exactly
(section 3 lists what was probed). But the fresh sweep did **not**
come back empty, and this plan will not pretend otherwise. Eleven
defects survived adversarial verification, including two rated high,
and two further candidates were refuted and are recorded with their
disproof rather than quietly dropped (section 27).

The dominant theme of the new findings is worth stating plainly,
because it is a lesson about how Minerva changes rather than a list of
bugs: **D-9 landed in the database but not on the reading surfaces.**
A retracted finding is correctly absent from briefs and packets, and
correctly skipped by doctor's finding check — and is rendered as an
ordinary asserted finding by the REST endpoint, the CLI, and the web
review page, while doctor cannot detect tampering with the retraction
records themselves. The database is honest; several surfaces reading
it are not. That is false-certainty manufacture by omission, which is
the precise failure the doctrine exists to prevent, and it is the
first thing to fix.

What remains falls into three categories:

1. **One ungated phase (0C):** the two confirmed highs above, nine
   confirmed mediums (doctor mutating what it inspects, missing
   publication durability, backup masking an outdated schema, two
   synthesis honesty gaps, silent web truncation, three test-suite
   honesty gaps), and fourteen lows and documentation defects. Twelve
   ordered issues, no migration, no new surface, entirely within
   Opus's standing authority.
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

## 3. Verified strengths

Everything below was probed, not read. Six independent reviewers each
took one subsystem, formed hypotheses, and ran them against scratch
databases and the real code paths. These are the contracts that held.

**Append-only enforcement is complete and load-bearing.** All fifteen
tables across migrations 0001–0004 carry `BEFORE UPDATE` and
`BEFORE DELETE` `RAISE(ABORT)` triggers. Through product connections,
`UPDATE`, `DELETE`, and `INSERT OR REPLACE` are all blocked on
`schema_migrations`, `research_runs`, and `audit_events`. The
`recursive_triggers` pragma was demonstrated to be load-bearing:
turning it off re-opens the `INSERT OR REPLACE` bypass, turning it on
closes it.

**Migration integrity fails closed.** A tampered checksum is refused
with `migration_checksum_mismatch`; a future version-5 row with
`database_too_new`; non-contiguous or non-integer histories are
rejected. `_validate_migration_state` re-runs inside the same
transaction after applying pending migrations.

**The staged-initialize fix is sound.** Unpredictable owner-only
`mkstemp` staging, `fstat` regular-file check, device/inode-verified
cleanup, exclusive `os.link` publication that refuses to overwrite,
and the idempotent fallback when losing the publication race. A losing
initializer returns success against the winner's database instead of
destroying it — the defect plan 1 rated high is genuinely closed.

**Citation safety is airtight at both write and read.** Mid-codepoint
start, mid-codepoint end, negative offsets, zero-length, inverted,
past-end, 10^18 end, bool offsets, quote mismatch, NFD-vs-NFC quote,
NUL and lone-surrogate quotes — every case refused with a domain error
code. The `end_byte == byte_length` boundary is correctly accepted.
The same invariants are re-verified on every read, which also re-hashes
the snapshot and fails closed with `citation_tampered`.

**Evidence stance is never collapsed.** Supports/opposes/context/
inconclusive survive verbatim through the claim ledger, packet
citations, Markdown render, and assist context. Claim-status evidence
rules are presence-based only, and the packet verifier independently
re-derives the identical required-stances mapping. The derived
`contested` flag supplements per-citation stance rather than replacing
it.

**Source intake is hostile-input hardened.** Path traversal, absolute
paths, backslashes, NUL-in-path, Windows drive forms, symlinked files
and symlinked directory components, FIFOs, invalid UTF-8, and oversize
content are all refused. The double-read fail-closed behaviour was
reproduced deterministically three ways: in-place same-inode mutation,
rename-swap, and append growth mid-import each refuse with
`source_changed`.

**Determinism holds under adversarial probing.** Every list-producing
query in the synthesis service terminates in a unique key. Repeated
builds of mission-wide and claim-scoped briefs were byte-identical, and
two exports of the same mission to different directories produced
byte-identical Markdown and JSON with equal digests. The payload
carries only `str`/`int`/`bool`/`None` — the strict DTOs reject floats,
so there is no float-formatting hazard.

**The VM-step budget cannot be reset mid-read.** Every statement of
fulfillment runs inside the bounded-work context;
`set_progress_handler` appears exactly once in the repository. On
exhaustion, fulfillment refuses with `brief_work_limit` and creates no
output directory and no partial files.

**Retraction exclusion is symmetric and audit-consistent.** After
retracting a claim-linked finding, both mission-wide and claim-scoped
packets drop the finding, its uncertainty entry, and its creation audit
reference. The packet's exact-cover audit validator structurally
prevents referencing an event for content the packet does not carry.

**No-overwrite export behaviour is exact.** `O_EXCL`+`O_NOFOLLOW` per
file with dev/inode-verified cleanup; re-export into an occupied
directory refuses leaving existing bytes untouched; a pre-existing
result file causes fulfillment to refuse *and* remove the brief it had
just written; a concurrent mutation between assembly and the export
transaction is caught by the audit watermark with both files cleaned
up and no export row recorded.

**The provider boundary matches ADR 0003 exactly.** Transport pinned
`trust_env=False`, `follow_redirects=False`, `max_retries=0`; base URLs
stay fixed even when `OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL` are set;
neither adapter passes tools. Terminal-status ordering is correct in
both directions (a failed response carrying a refusal item is
`provider_response_invalid`, not a refusal). Credential ephemerality
holds on success *and* every error path: `ProviderCredential` blocks
copy/deepcopy/pickle and redacts `repr`/`str`, and audit details carry
only hashes, counts, codes, and a hashed response id.

**The loopback trust boundary is deny-by-default.** The middleware
allows only `http` and `lifespan` scopes and closes websockets with
1008; an unknown scope type is dropped with no send and no forward.
Host and Origin are checked with matching effective port; bodies are
buffered to the cap before framework parsing; CORS headers are
stripped. Templates use autoescape with `StrictUndefined` and no
`|safe` anywhere.

**Error details do not reflect attacker bytes.** Probed with a
`<script>` marker: extra fields map to a fixed `unknown_field`, and
every middleware error body is static.

**Adapters never own rules.** `api/routes.py` and `web/app.py` contain
no raw SQL and no re-implemented validation; their only use of
`database.read()` is to obtain a connection passed into the shared
services.

**Test-suite strength was itself tested.** Reviewers broke product
behaviour in scratch copies to confirm the guards actually fail:
dropping the CSP header, loosening the Host parser, bypassing the body
cap, making CSRF validation always-true, disabling the secret scan,
disabling the authorized-digest check, allowing withdrawn evidence
through fulfillment, and removing the VM budget each fail a specific
named test. The concurrent-initialization test is a genuine six-thread
barrier race. Fixtures use a fixed clock and monotonic id factory, so
golden bytes are reproducible regardless of wall-clock date.

## 4. Verified weaknesses and risks

Eleven defects survived adversarial verification; two candidates were
refuted and are recorded as such in section 27. The full ledger with
reproductions is in section 27; this section states the shape of the
risk.

**The dominant theme is that D-9 landed in the database but not on the
reading surfaces.** Retraction is correct where it was designed —
briefs, packets, doctor's finding check — and absent everywhere else.
Two of the three highest-severity findings are direct consequences:

1. **Retracted findings still render as asserted** on the REST
   findings endpoint, the CLI mission view, and the web review page,
   with no marker at all. A reviewer looking at the human review
   surface cannot tell an asserted finding from a retracted one. The
   database is honest; the reading surfaces are not. This is
   false-certainty manufacture by omission, which is the one thing the
   doctrine exists to prevent.
2. **Doctor is blind to migration-0004 tampering.** The required-trigger
   set was never extended for `finding_retractions`, and deep doctor
   never reconciles retraction rows against their audit events. A
   reviewer dropped both triggers, edited a retraction, deleted it, and
   `doctor --deep` still returned all-green. The one record type whose
   whole purpose is to *silence* a finding is the one record type
   integrity checking ignores.

**Two known-open items from plan 1 are confirmed still live**, now with
reproductions rather than inference: doctor persistently rewrites the
journal-mode header of any non-WAL database it inspects (changing its
SHA-256, which breaks byte-stable-artifact provenance and makes two of
doctor's own checks tautological), and no directory `fsync` follows any
hard-link publication, so an audited success can vanish on power loss.

**One new operational inversion:** `backup_to` collapses every doctor
failure into `database_invalid`, so an intact schema-3 database — the
exact state an operator holds immediately before upgrading — cannot be
backed up at all, and the refusal implies corruption. This inverts safe
upgrade ordering: you must migrate first, then back up, leaving no
pre-migration snapshot. It is the same masking defect that was fixed in
`restore_from` during Phase 0, surviving in the sibling path.

**Two honesty gaps in synthesis:** claim-scoped briefs silently omit
mission-level findings and uncertainties that cite the target claim's
own evidence (emitting empty arrays indistinguishable from "none
exist"), and the mission-wide preflight has no text accounting, so an
oversized brief surfaces as `packet_integrity_invalid` — a false tamper
alarm for an intact database.

**One presentation gap:** the web mission list truncates at 100 with no
indicator, while the REST equivalent honestly returns a continuation
cursor.

**Three test-suite honesty gaps:** the suite-wide network guard patches
only `connect`/`create_connection` while its docstring claims to fail
any non-loopback socket (`connect_ex` and UDP `sendto` demonstrably
escape); the coverage floor excludes the entire `scripts/` tree, so the
static security gate's own detection branches sit at 39% with the
eval/exec/compile rule having no test witness at all; and the alias
tests sample only `Name`-target aliasing while tuple/list-unpack
aliasing evades the scanner untested.

**Documentation overstates one security control.** THREAT_MODEL,
ARCHITECTURE, and ADR 0005's consequences all claim
`idx_audit_event_entity` is pinned with `INDEXED BY` and cannot be
dropped without loud failure. No such hint exists in product code —
the index is planner-selected, and dropping it degrades silently. This
is the same class of error Opus caught and corrected once during Phase
0 (the "cannot silently regress to a scan" claim); it survives in three
other documents, and ROADMAP/ARCHITECTURE still carry the corrected
claim's original wording, directly contradicting ADR 0005.

**Risk assessment.** None of these is a data-loss defect, and none
weakens an append-only guarantee — the append-only core, citation
model, determinism, and provider boundary all survived hostile probing
intact. The concentration is instead in *honesty of presentation*: five
of the eleven are cases where a surface reports something more
confident, more complete, or more verified than the underlying state
warrants. That is the correct thing to fix first in a system whose
entire value proposition is not manufacturing certainty.

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
| Symmetric correction vocabulary (withdraw + retract) | ∆ Complete in the database and synthesis; **invisible on REST/CLI/web reads, unverified by doctor** (F2-RES-1, F2-CORE-1) | Visible and integrity-checked everywhere | ∆ partial → planned (issues 1–2) |
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
- **Capability / scope:** section 19 issues 1–12, every one traceable
  to a reproduced finding in section 27. Headline items: finish D-9 on
  the reading surfaces (F2-RES-1), make doctor see migration 0004
  (F2-CORE-1), resolve the `INDEXED BY` documentation overstatement
  (F1-IDX-AUDIT/F2-IDX-SCAN), stop doctor mutating what it inspects
  (F2-CORE-2/F-OPS-5), add publication durability (F2-CORE-3/F-OPS-6),
  stop backup masking an outdated schema (F2-CORE-4), close the two
  synthesis honesty gaps (F2-SYNTHESIS-1/2), paginate the web mission
  list honestly (F2-SURFACES-1/F-PAR-3), close the three test-suite
  honesty gaps (F2-TESTS-1/2/3), sweep the lows, and finish with
  interrupt-safe assist audit (F-AI-4), helper consolidation
  (F-DUP-2), release discipline (F-REL-1/2), and the coverage ratchet.
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
  pre-fix code. Named proofs: a retracted finding must be
  distinguishable on REST, CLI, and web (F2-RES-1); the
  drop-triggers-then-tamper sequence must make `doctor --deep` fail
  (F2-CORE-1); a byte-compare of a delete-journal database before and
  after `doctor --deep` (F2-CORE-2); fault injection at the
  publication boundary (F2-CORE-3); an intact schema-3 database must
  back up or refuse honestly (F2-CORE-4); an oversized-but-intact
  mission must refuse with `brief_work_limit`, never
  `packet_integrity_invalid` (F2-SYNTHESIS-2); `connect_ex` and UDP
  `sendto` must trip the network guard (F2-TESTS-1); tuple/list/starred
  alias forms must raise MIN002 (F2-TESTS-3); KeyboardInterrupt
  injection inside the provider-call window (F-AI-4).
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

## 19. Ordered implementation issues

Issues 1–12 constitute Phase 0C and are all ungated; the recommended
first slice covers 1–6 (section 26). Issues 13–23 are gated and must
not begin before their decision is recorded. Every Phase 0C issue
traces to a finding in section 27 with a reproduction behind it.

1. **F2-RES-1 (high): finish D-9 on the reading surfaces.** Add
   `retracted` + reason/at/by to `Finding` and `FindingRead`,
   `LEFT JOIN finding_retractions` in `list_findings`/`page_findings`
   /`_findings_from_rows`, render a RETRACTED badge in
   `mission_detail.html`, include it in CLI mission-show output.
   Read models only — the frozen v2 packet does not move. Regression:
   a retracted finding must be distinguishable on all three surfaces.
2. **F2-CORE-1 (high): make doctor see migration 0004.** Register
   both retraction triggers, and derive `_REQUIRED_TRIGGERS` from the
   packaged migrations so a future migration cannot repeat the drift
   (with a test asserting derived == declared). Extend
   `_verify_material_audit_links` to reconcile retraction rows against
   `research.finding.retracted` events. Regression: the drop-triggers-
   then-tamper sequence must make `doctor --deep` fail.
3. **F1-IDX-AUDIT + F2-IDX-SCAN: make the index claims true or
   correct them.** Decide once: either add `INDEXED BY
   idx_audit_event_entity` at the three audit access sites, or fix
   THREAT_MODEL.md:27, ARCHITECTURE.md:251–256, ADR 0005's
   consequences, ROADMAP.md:91–92, and the migration 0003 comment to
   claim only the narrow guarantee ADR 0005 already states correctly.
   Recommendation: correct the docs — the `EXPLAIN QUERY PLAN` test is
   the real pin and already exists.
4. **F2-CORE-2 (F-OPS-5): doctor stops mutating what it inspects.**
   Open doctor and `read()` with `mode=ro`, skip the WAL-forcing
   pragma on read paths, report the journal mode actually found.
   Regression: byte-compare a delete-journal database before/after
   `doctor --deep`.
5. **F2-CORE-3 (F-OPS-6): durability at publication.** Directory
   fsync after every exclusive publication (staged-init publish,
   backup, restore, brief export, fulfillment outputs); fault
   injection at the publication boundary; SECURITY.md durability
   statement naming what fsync does and does not guarantee.
6. **F2-CORE-4: backup must not mask an outdated schema.** Mirror the
   F-OPS-2 restore fix — determine outdated schema separately and
   refuse with `database_migration_required` (or permit backing up an
   intact outdated database, which is the operator-friendly answer and
   the one that restores safe upgrade ordering). Reserve
   `database_invalid` for genuine validation failure.
7. **F2-SYNTHESIS-2: mission-wide preflight text accounting.** Add
   materialized-text accounting to the mission-wide branch mirroring
   `_preflight_claim_synthesis`, refusing with `brief_work_limit`
   before assembly; separately distinguish the size `ValueError` from
   validation errors so an oversized-but-intact database never reports
   as `packet_integrity_invalid`.
8. **F2-SYNTHESIS-1 (F-SYN-1): make the claim-scoped boundary
   explicit.** Document the scope rule in the PRD and pin it with a
   regression. Assess (do not assume) whether mission-level findings
   whose citations intersect the target ledger should be included —
   the audit CTE is already symmetric, so inclusion is defensible; if
   they stay excluded, the emptiness must not read as "none exist."
9. **F2-SURFACES-1 (F-PAR-3): honest web pagination.** Cursor
   pagination like the REST route, or an explicit "showing first 100"
   banner. Never present a capped list as the whole set.
10. **F2-TESTS-1/2/3: close the test-suite honesty gaps.** Patch
    `connect_ex`/`sendto`/`sendmsg` in the network guard (or narrow
    its docstring to what it covers); add MIN003 cases and a coverage
    floor over `scripts/`; add tuple/list/starred-unpack alias cases
    and extend `_bind_alias` to walk those targets.
11. **Low-severity sweep:** F2-CORE-5 (recompute pending migrations
    inside the write transaction), F2-CORE-6 (check unsafe path before
    `refuse_existing`), F2-RES-2 (`allow_withdrawn=not
    kind.requires_citation` in `add_finding`, or amend ADR 0007),
    F2-EVD-1 (`isinstance` int check on offsets), F2-INTEGRATIONS-1
    (anchor the request digest classifier like the packet's),
    F2-SURFACES-3 (extend the identity-header denylist),
    F2-TESTS-4 (`scripts/regenerate_goldens.py` + procedure doc),
    F3-MILESTONE-TITLES, F4-CLI-UNDOC, F5-CAP-PACKET-CLI, and the
    `OPUS_EXECUTION_STATE.md` corrections listed in section 27.
12. **F-AI-4 + F-DUP-2 + release discipline:** interrupt-safe terminal
    assist audit; consolidate the canonical-JSON/strict-parse helpers
    into one reviewed module (golden fixtures prove no behavior
    change); tag `v0.2.0` with recorded gate evidence and adopt the
    commit-attribution convention; ratchet the coverage floor from 85
    to 88.
13. (D-10) DECISIONS.md boundary record + capability-manifest
    taxonomy revision in one reviewed change (subsumes
    F5-CAP-PACKET-CLI if the packet-CLI entries are added).
14. (D-11) ADR 0004 amendment + staged-migration-during-restore +
    provenance-correct audit events + upgrade-recovery test.
15. (D-1) ADR 0008 draft for Kevin: persisted agent inferences,
    including the day-one retraction table and the ADR 0003
    amendment language.
16. (D-1) Migration 0005 + adoption service (ledger re-validation,
    secret rescan, size bounds) + `assist adopt` CLI verb.
17. (D-1) Markdown export labeling + doctor coverage for inference
    citation integrity + retraction round-trip tests. Note: issue 1's
    read-model work is a prerequisite in spirit — do not repeat the
    D-9 mistake of persisting a record type whose retraction is
    invisible to every surface but the packet.
18. (D-1) Injection-shaped adversarial fixtures: candidate statements
    carrying instruction-smuggling, markup, and secret-shaped content.
19. (D-2) ADR 0009 draft: principals, transport choice, grants,
    replay defense, threat model.
20. (D-2) Migration 0006 + principal/grant tables + CLI
    administration + audit vocabulary.
21. (D-2) Signed-envelope verification library + adversarial vectors.
22. (D-2) ADR 0010 + Athena adapter: authenticated request intake →
    existing fulfillment → result return; `run_origins`; idempotency
    store + already-fulfilled stable reply.
23. (D-3) ADR 0011 draft + experiment artifact DTO pair + golden
    fixtures + verify CLI + `external_artifacts` registry wiring
    through existing `source import`.

## 20. Exact source files likely to change

Phase 0C (issues 1–12):

- `src/minerva/research/service.py`, `src/minerva/research/models.py`,
  `src/minerva/api/models.py`, `src/minerva/cli/main.py`,
  `src/minerva/web/templates/mission_detail.html` (retraction read
  model — issue 1)
- `src/minerva/core/doctor.py` (migration-0004 triggers + retraction
  audit reconciliation, derived required-trigger set, read-only
  inspection connection — issues 2 and 4)
- `src/minerva/core/db.py`, `src/minerva/core/operations.py`,
  `src/minerva/synthesis/request_fulfillment.py` (directory fsync at
  publication boundaries; backup schema-state distinction;
  migration-runner TOCTOU; symlink check ordering — issues 5, 6, 11)
- `src/minerva/synthesis/service.py` (mission-wide text-accounting
  preflight, size-error classification, claim-scope pinning — issues
  7 and 8)
- `src/minerva/web/app.py` + `src/minerva/web/templates/missions.html`
  (honest pagination — issue 9)
- `tests/conftest.py`, `tests/test_gate_scripts.py`,
  `scripts/static_security_check.py`, `pyproject.toml` (network-guard
  coverage, MIN003 witness, alias walking, coverage scope — issue 10)
- `src/minerva/evidence/service.py`,
  `src/minerva/integrations/research_request_file.py`,
  `src/minerva/api/routes.py` (low sweep — issue 11)
- `src/minerva/assist/service.py` and/or both files under
  `src/minerva/integrations/ai/` (interrupt-safe terminal audit),
  `src/minerva/integrations/research_packet.py`,
  `src/minerva/integrations/research_request.py`, new
  `src/minerva/integrations/canonical.py`, new
  `scripts/regenerate_goldens.py` (issue 12)
- `docs/THREAT_MODEL.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
  `docs/adr/0005-targeted-fulfillment-indexing.md`,
  `src/minerva/core/migrations/0003_fulfillment_indexes.sql` comment
  (index-claim correction — issue 3), plus `docs/PRD.md`,
  `README.md`, `docs/DECISIONS.md`, and
  `docs/OPUS_EXECUTION_STATE.md` corrections.

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

**Issues 1–2 of section 19, alone, as the first PR: finish D-9.**
Not the whole of wave C — these two and nothing else. They share one
user outcome (a retracted finding is visibly retracted and its
retraction record is integrity-checked), they are the two confirmed
highs, and together they close the gap between what D-9 promised and
what it delivered. Shipping them separately from the durability and
documentation work keeps the reviewable diff about one idea, which is
the discipline that made Phase 0's slices reviewable.

Then, in order, as separate PRs: issue 3 (the `INDEXED BY`
documentation correction — docs-only, trivially reviewable, and it
retires a false security claim); issues 4–7 (doctor read-only,
publication durability, backup schema honesty, preflight text
accounting — the operational-integrity group); issues 8–10 (scope
pinning, honest pagination, test-suite honesty); issue 11 (the low
sweep); issue 12 (interrupt audit, helper consolidation, release tag,
coverage ratchet). The release tag must not share a PR with code
changes — a tag is only meaningful once the tree it names is final.

Scope discipline for every one of them: one commit per concern, one
regression per fix verified to fail on the pre-fix code, no migration,
no new surface, and a PR description naming any review-gated file
touched. Section 19 issue 3 touches THREAT_MODEL and ADR text, which
is a review-gated surface under AGENTS.md.

If Kevin records D-1 before or during that work, its ADR draft (issue
15) can proceed in parallel with wave C since it is a document, not
code — but issue 1 should land first regardless, because Phase 1
persists a second record type whose retraction must be visible from
day one, and shipping the inference door on top of an invisible-
retraction read model would repeat the exact mistake D-9 just taught.
If Kevin gives the one-word go on D-10's recording half (issue 13), it
rides along as its own commit.

What Opus must NOT do without a recorded decision, restated: persist
inferences (D-1), build any transport or principal machinery (D-2),
draft sibling contracts (D-3), expose anything beyond loopback (D-4),
add MCP (D-5), add retrieval (D-6), sign exports (D-7), choose a
license (D-8), add the REST withdrawal endpoint (D-10), or let restore
migrate (D-11).

## 27. Fable findings ledger v2

Method: six independent subsystem reviewers, each followed by an
adversarial verifier instructed to **refute** — to default to REFUTED
when evidence did not survive its own reproduction. Every high and
medium finding went through that gate. Low findings were not sent to a
verifier (a deliberate cost bound, disclosed here) and are marked
`unrefereed`; treat their severity as the finder's own claim, not a
verified one. Two findings were refuted and are recorded below with
their disproof rather than deleted.

### Summary

| ID | Severity | Verdict | Summary | Disposition |
| --- | --- | --- | --- | --- |
| F2-RES-1 | high | CONFIRMED | Retracted findings render as asserted on REST, CLI, and web surfaces | wave C |
| F2-CORE-1 | high | CONFIRMED | Doctor ignores migration-0004 triggers and retraction audit links | wave C |
| F1-IDX-AUDIT | high* | unrefereed | Docs claim `idx_audit_event_entity` is `INDEXED BY`-pinned; it is not | wave C |
| F2-CORE-2 | medium | CONFIRMED | Doctor rewrites the journal-mode header of what it inspects (F-OPS-5) | wave C |
| F2-CORE-3 | medium | CONFIRMED | No directory fsync after publication (F-OPS-6) | wave C |
| F2-CORE-4 | medium | CONFIRMED | `backup_to` masks an outdated schema as `database_invalid` | wave C |
| F2-SYNTHESIS-1 | medium | CONFIRMED | Claim-scoped briefs silently omit mission-level statements (F-SYN-1) | wave C |
| F2-SYNTHESIS-2 | medium | CONFIRMED | Mission-wide preflight lacks text accounting; oversize reads as tampering | wave C |
| F2-SURFACES-1 | medium | CONFIRMED | Web mission list truncates at 100 with no indicator (F-PAR-3) | wave C |
| F2-TESTS-1 | medium | CONFIRMED | Network guard misses `connect_ex`/UDP; docstring overclaims | wave C |
| F2-TESTS-2 | medium | CONFIRMED | Coverage floor excludes `scripts/`; MIN003 has no test witness | wave C |
| F2-TESTS-3 | medium | CONFIRMED | Tuple/list-unpack aliasing evades the static gate, untested | wave C |
| F2-IDX-SCAN | medium | unrefereed | ROADMAP/ARCHITECTURE contradict ADR 0005 on `INDEXED BY` semantics | wave C |
| F2-CORE-5 | low | unrefereed | Migration-runner TOCTOU yields spurious `migration_failed` | wave C |
| F2-CORE-6 | low | unrefereed | Symlinked path + `refuse_existing` reports `database_exists` | wave C |
| F2-RES-2 | low | unrefereed | `add_finding` refuses withdrawn citations for assumptions, against ADR 0007 | wave C |
| F2-EVD-1 | low | unrefereed | Float citation offsets raise raw `TypeError` | wave C |
| F2-INTEGRATIONS-1 | low | unrefereed | Request digest classifier is substring-based, unlike the packet's | wave C |
| F2-INTEGRATIONS-2 | low | unrefereed | Overflow literals (`1e400`) classify generically, not as non-finite | backlog |
| F2-SURFACES-3 | low | unrefereed | Identity-header denylist omits mainstream proxy headers | wave C |
| F2-SURFACES-4 | low | unrefereed | `CsrfProtector` is implemented but unwired | backlog |
| F2-TESTS-4 | low | unrefereed | No documented golden-fixture regeneration procedure | wave C |
| F3-MILESTONE-TITLES | low | unrefereed | PRD/THREAT_MODEL titled "through 1.4"; repo ships 1.5 | wave C |
| F4-CLI-UNDOC | low | unrefereed | Real CLI verbs (incl. `claim status`) documented nowhere | wave C |
| F5-CAP-PACKET-CLI | low | unrefereed | ADR 0002 claims a packet-CLI manifest entry that does not exist | wave C |
| F2-SYNTHESIS-3 | medium | **REFUTED** | ">200 citations permanently unfulfillable" | dropped; wording nit remains |
| F2-SURFACES-2 | medium | **REFUTED** | "static gate bypassable via `getattr`" | dropped; already disclosed |

\* F1-IDX-AUDIT's "high" is the finding agent's own rating and was not
independently verified. It is a documentation-integrity defect (a
security control described as stronger than it is), not a code defect;
Opus should re-rate it when fixing.

### Confirmed high findings

**F2-RES-1 — Retracted findings are presented as active on every
listing surface.** `src/minerva/research/service.py:709`. ADR 0007
defines retraction as "the finding stops being asserted," and synthesis
honors that. But the `Finding` domain object has no retraction field,
`list_findings`/`page_findings` never join `finding_retractions`, and
`FindingRead` has no retraction field — so
`GET /api/v1/missions/{id}/findings`, `minerva mission show`, and the
web review page all render a retracted finding identically to an
asserted one. Reproduced three ways (service, REST, web); the verifier
rebuilt the reproduction from scratch with neutral wording after its
first probe false-hit on its own seed text, and every claim held. Fix:
mirror the withdrawal read model — add `retracted` plus reason/at/by to
`Finding` and `FindingRead`, `LEFT JOIN finding_retractions`, render a
badge. Read models only; the frozen v2 packet is untouched.

**F2-CORE-1 — Doctor is blind to migration-0004 tampering.**
`src/minerva/core/doctor.py:51`. `_REQUIRED_TRIGGERS` lists 28
triggers, none from migration 0004, so `append_only_triggers` ignores
`finding_retractions_no_update`/`_no_delete`. Deep doctor also never
reconciles retraction rows against their `research.finding.retracted`
audit events. Reproduced independently by both agents: drop both
triggers, `UPDATE` and `DELETE` the retraction row, and
`doctor --deep` still returns `ok=True` on 11/11 checks while the
database holds one retraction audit event and zero retraction rows —
a silently resurrected finding. Control: dropping a 0001–0002 trigger
*is* caught, confirming the gap is specific to the unregistered
migration. Fix: register the two triggers, and — better — derive the
required set from the packaged migrations so a future migration cannot
repeat the drift, with a test asserting the two sets match.

**F1-IDX-AUDIT — Documentation claims an index pin that does not
exist** (unrefereed). THREAT_MODEL.md:27 lists as a control "targeted
audit and claim-scoped finding indexes (migration 0003) pinned with
`INDEXED BY`"; ARCHITECTURE.md:251–256 names both indexes and repeats
it; ADR 0005's consequences say both names "are named by `INDEXED BY`
hints … so they cannot be renamed or dropped without changing those
queries in the same commit"; migration 0003's own comment says
"renaming or dropping either one makes those queries fail to prepare."
In fact `grep` finds `idx_audit_event_entity` only in the migration —
no `INDEXED BY` names it anywhere. It is planner-selected and would
degrade silently if dropped, guarded solely by
`test_targeted_fulfillment_indexes_are_present_and_selected`. Fix:
either add the hints at the three audit access sites, or correct all
four documents to claim only what is true. This is the same
overstatement class Opus corrected once in Phase 0 — it survived in
adjacent documents.

### Confirmed medium findings

- **F2-CORE-2 (F-OPS-5 confirmed)** — `Database._connect` executes
  `PRAGMA journal_mode = WAL` on every open, and `read()`/doctor use
  that read-write connection. Inspecting any delete-journal database
  persistently rewrites its header: reproduced twice with differing
  SHA-256 before and after `doctor`, so a recorded artifact digest no
  longer matches after a health check. It also makes the `wal` and
  `foreign_keys` checks tautological — they report what `connect` just
  forced. Fix: open doctor and `read()` with `mode=ro`, skip the
  WAL-forcing pragma, and report the journal mode actually found.
- **F2-CORE-3 (F-OPS-6 confirmed)** — `_publish_private_database`
  publishes via `os.link` with no directory fsync; repository-wide
  there is exactly one `fsync` (the export file descriptor) and none in
  `core/`. Backup's ordering makes it worse: the audit event is
  committed durably to the source database after the non-durably
  published target. Structural verification only; power loss was not
  simulated, and both agents say so.
- **F2-CORE-4** — `backup_to` maps any not-ok doctor report to
  `IntegrityError('database_invalid')`, and doctor fails for an
  outdated schema. Reproduced by building a legitimate schema-3
  database (correct checksums, `integrity_check ok`) and calling
  `backup_to`: refused as having "failed validation." Restore already
  distinguishes this case correctly (`database_migration_required`);
  backup does not.
- **F2-SYNTHESIS-1 (F-SYN-1 confirmed)** — the claim-scoped findings
  query filters `claim_id = ?`, so mission-level findings (`claim_id`
  NULL) never match even when they cite the target claim's evidence.
  The scoped packet carries the cited card while dropping the finding,
  its unresolved question, and its uncertainty, emitting empty arrays
  indistinguishable from "none exist." Both agents reproduced it.
- **F2-SYNTHESIS-2** — the mission-wide preflight bounds record counts,
  reference counts, and snapshot bytes, but never quote/statement text.
  215 cards quoting the same 99 KB range (21.3 MB of aggregate quote
  text, 99 KB of snapshots) pass preflight, then fail at serialization
  with the size `ValueError` swallowed by a blanket handler and
  reported as `packet_integrity_invalid` — a tamper alarm for an intact
  database. The claim-scoped branch, which *does* have text accounting,
  honestly refuses the same data with `brief_work_limit`.
- **F2-SURFACES-1 (F-PAR-3 confirmed)** — 150 seeded missions render
  exactly 100 cards with no count, banner, or pagination, while the
  REST route returns a `next_cursor`. Verified independently via ASGI.
- **F2-TESTS-1** — the autouse `deny_outbound_network` fixture claims
  to "fail any test that opens a non-loopback socket" but patches only
  `connect` and `create_connection`. Verified against the real fixture:
  `connect_ex` to 127.0.0.2 returned ECONNREFUSED and UDP `sendto`
  delivered 5 bytes, both silently. The realistic provider path (TCP
  connect) *is* caught, so this is honesty-of-guarantee rather than an
  open hole — but the docstring must not promise more than it does.
- **F2-TESTS-2** — coverage is scoped to `--cov=minerva`, so the entire
  `scripts/` tree sits outside the floor at 39% measured, with
  `static_security_check.py` at 79% and its MIN003 (eval/exec/compile)
  emit branch uncovered and unwitnessed by any test.
- **F2-TESTS-3** — `_bind_alias` returns early for any non-`ast.Name`
  target, so `(runner,) = (os.system,)` and `[runner] = [os.system]`
  evade MIN002 while the tested `runner = os.system` form is caught.
  The verifier extended the probe set: 2-tuple and starred unpacking
  also evade. The tests assert a stronger guarantee than the code
  provides.
- **F2-IDX-SCAN** (unrefereed) — ROADMAP.md:91–92 and
  ARCHITECTURE.md:255–256 assert `INDEXED BY` means "a budgeted read
  cannot silently regress to a scan"; ADR 0005:73–77 documents the
  opposite and correct semantics. A direct contradiction between
  governing documents.

### Confirmed low findings (unrefereed)

`F2-CORE-5` migration-runner TOCTOU (pending set computed outside the
write transaction; a concurrent upgrade makes the loser report
`migration_failed` though the database is intact — reproduced
deterministically, retry succeeds) · `F2-CORE-6` symlinked path with
`refuse_existing=True` reports `database_exists` instead of
`database_symlink`, so identical filesystem state yields two codes
depending on a flag · `F2-RES-2` `add_finding` passes a blanket
`allow_withdrawn=False`, refusing an assumption that cites already-
withdrawn evidence — a state ADR 0007 explicitly says is supported, and
which *is* reachable by creating in the other order · `F2-EVD-1` float
offsets bypass the guards and raise a raw `TypeError` inside the
transaction instead of `citation_offsets_invalid` (nothing persists) ·
`F2-INTEGRATIONS-1` the request digest-mismatch classifier uses an
unanchored substring test where the packet classifier deliberately uses
an anchored exact match with a comment explaining why ·
`F2-INTEGRATIONS-2` `1e400` overflows to infinity without triggering
`parse_constant`, so it classifies as generic `*_invalid` rather than
`*_nonstandard_number` (always rejected, just less precisely) ·
`F2-SURFACES-3` the identity-header denylist omits Cloudflare Access,
Google IAP, oauth2-proxy, EasyAuth, Kong, and bare `remote-user`
headers (defense-in-depth only — identity is always
`getpass.getuser()`) · `F2-SURFACES-4` `CsrfProtector` is fully
implemented and exported but wired into nothing · `F2-TESTS-4` no
in-repo golden-fixture regeneration procedure exists, so a maintainer
facing a legitimate schema change has no deterministic path ·
`F3-MILESTONE-TITLES` PRD and THREAT_MODEL are titled "Milestones 1
through 1.4" while the repo ships 1.5, and THREAT_MODEL never mentions
retraction · `F4-CLI-UNDOC` `mission list`, `mission show`,
`claim ledger`, `claim status`, `init --refuse-existing`,
`source show --metadata-only`, `audit list --after-sequence`, and
`evidence add --supersedes` appear in no governing document —
`claim status` is state-changing · `F5-CAP-PACKET-CLI` ADR 0002 says
the manifest advertises packet CLI support; the manifest has request
and assist CLI entries but no packet-CLI entry.

### Refuted findings (recorded, not deleted)

- **F2-SYNTHESIS-3 — "a claim with >200 active citations is permanently
  unfulfillable."** The raw behaviour reproduces, but the defect claims
  fail. The overflow is deliberately pinned by a named security test
  that seeds 201 cards and asserts exactly this refusal before
  synthesis, consistent with PRD invariant 14. "Permanently" is
  disproved: withdrawing one card made the identical request fulfill.
  The retry-loop impact assumes a consumer violating its own declared
  complete-ledger policy, and a 201-id request is terminally rejected
  at the contract layer. **Residual kernel worth fixing:** the message
  "The active evidence selection has changed" is literally inaccurate
  for the overflow case — an info-level wording polish, logged to the
  backlog.
- **F2-SURFACES-2 — "the static security gate is bypassable via
  `getattr`/`sys.modules`."** The mechanism is real and the verifier
  reproduced it against the real script. The *finding* is refuted on
  three independent grounds: THREAT_MODEL.md line 46 already discloses
  this exact residual ("static analysis cannot see dynamically
  constructed attribute access"); plan 1 explicitly considered and
  rejected the fix as an inherent static-analysis limit; and the threat
  requires a committer, who is inside the trust boundary and needs no
  bypass. The gate is paired with mandatory human review as
  defense-in-depth, not sole enforcement, so it does not present a
  guarantee it fails to deliver. Severity would be informational at
  most.

### Corrections to `docs/OPUS_EXECUTION_STATE.md`

The execution state file is substantively accurate — all twelve
load-bearing claims verified — but carries drift Opus should refresh:
`INDEXED BY` line references (622/645/1206 → 630/653/1216, shifted by
the retraction clauses), the provenance-lookup and preflight line
citations, test counts (581/551 → 628) and security-marked counts
(142 → 177), and frontmatter still naming `base_commit b70fbdd` and the
pre-merge branch with no mention of PR #12. Two statements are loose
rather than wrong: the index test's "no residual scan or temp-b-tree
sort" applies the no-scan assertion only to the audit plan and the
no-temp-b-tree assertion only to the findings plan; and
`recursive_triggers` is set on every connection that executes
application SQL, but not on the ancillary backup/restore page-copy
connections (harmless — they issue no DML).

## 28. Verification evidence and unavailable checks

### Gates

All eleven AGENTS.md gates were re-run independently at `b26268c`:

| Gate | Result | Detail |
| --- | --- | --- |
| `uv sync --frozen --extra dev` | PASS | 41 packages, no drift |
| `uv run ruff check .` | PASS | all checks passed |
| `uv run ruff format --check .` | PASS | 74 files |
| `uv run mypy` | PASS | strict, 51 source files |
| `uv run pytest` | PASS | 628 passed; branch coverage 90.12% (floor 85) |
| `uv run python -m build` | PASS | sdist + wheel |
| `uv run python scripts/verify_dist.py dist` | PASS | wheel + sdist verified |
| `uv run python scripts/installed_smoke.py dist` | PASS | outside the checkout |
| `uv run python scripts/static_security_check.py` | PASS | 49 files |
| `uv pip check` | PASS | 41 packages compatible |
| `git diff --check` | PASS | clean |

Security-marked tests: 177 of 628. Golden fixtures for
`minerva.research-brief.v2` and `minerva.research-request.v1` were
confirmed by `git log --follow` to predate migrations 0003 and 0004 and
still pass byte-exactly — the strongest available determinism evidence,
since they were generated before the schema changes they are asserted
against.

One reporting nuance, disclosed rather than smoothed over: running
`pytest -m security --co -q` to count security tests emits a coverage
failure line, because collect-only executes nothing. That is an
artifact of the collection command, not a gate failure; the real run
exits 0 at 90.12%.

### Method

Fourteen agents: one gate runner, one claim verifier against
`OPUS_EXECUTION_STATE.md`, one documentation-drift sweep, six
subsystem finders (core, domain, synthesis, integrations, surfaces,
tests), and five adversarial verifiers instructed to refute. Finders
were told a reproduction beats a speculation and to report clean areas
as well as defects; verifiers were told to default to REFUTED when
evidence did not survive their own reproduction. Two of thirteen
high/medium findings were refuted on that basis and are recorded in
section 27 with their disproof.

### Unavailable checks (open verification, not passes)

- **Python 3.13 / 3.14** — this environment runs 3.12.3 only. CI covers
  the matrix on push; the gate results above are single-version.
- **Live provider behaviour** — never exercised, by contract. All
  provider evidence is from fakes, code reading, and enumeration of the
  SDK constructors' environment reads.
- **Power-loss durability (F2-CORE-3)** — verified structurally
  (absence of any `fsync` in `core/`, `os.link` as the sole publication
  primitive), not by simulating power loss. The gap is inferred from
  code shape, and both the finder and its verifier say so.
- **Non-Linux platforms** — outside the supported boundary.
- **Real-corpus scale** — all measurements use synthetic databases.
  The 8,000,000-step budget's headroom on a real corpus is unmeasured.
- **Multi-host / multi-process concurrency beyond same-host threads** —
  the initialization race is genuinely threaded, but nothing tests
  competing processes across hosts or filesystems.
- **Low-severity findings** — nine findings plus five documentation
  findings were not sent to an adversarial verifier, a deliberate cost
  bound. Their severities are the finding agent's own claims.
