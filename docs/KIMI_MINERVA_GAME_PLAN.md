# KIMI Minerva Game Plan

- Author: Kimi (execution/planning agent), for Kevin
- Date: 2026-07-30
- Status: active working plan
- Relationship to prior plans: builds on `FABLE_MINERVA_GAME_PLAN_2.md` and
  `OPUS_EXECUTION_STATE.md`. It does not replace them; it sequences the work
  Kevin has now directed: Minerva becomes the **second pillar of the AI
  workspace — the fleet's AI research center**.

## 1. Vision

Kevin's directive (2026-07-30): Minerva is the **research pillar** of the AI
workspace. Where Athena coordinates and Oracle archives, Minerva is where
questions live: every claim falsifiable, every statement cited to immutable
local evidence, every correction appended rather than rewritten, and every
machine contribution labeled as machine contribution. The doctrine stands:

> Minerva records evidence and uncertainty; it does not manufacture certainty.

What "AI research center" adds to the existing foundation: the fleet's agents
(Kevin included) must be able to *accumulate* audited research, not just
produce one-off briefs. That means the two gaps that matter most are the ones
Plan 2 already identified:

1. **Model work cannot enter the record.** Assist candidates evaporate at the
   terminal; the provenance of what the model drafted is lost (gate D-1).
2. **No other system can ask Minerva anything.** The request/packet artifacts
   exist but no authenticated producer/consumer seam exists (gates D-2/D-3),
   and no MCP surface exists for agent-driven use (gate D-5).

## 2. Current state (verified 2026-07-30)

- v0.2.0a1 tagged; milestones M1, M1.1–1.5, and M2B complete and gate-green.
- Baseline re-verified this session: **691 tests pass, 90.03% branch coverage**
  (floor 88%), zero TODO/FIXME/NotImplemented markers in the tree.
- All 27 CLI verbs, REST API, web review UI, offline packet/request tooling,
  and BYOK assist flow work as documented.
- Nothing beyond M2B is implemented — by design. Every further surface is
  behind a recorded decision gate (D-1 … D-11).

## 3. Gate decisions taken under Kevin's directive

Kevin's instruction — "build up a game plan and then execute on it" — opens
the gates below. Each resolution follows the recommendation already drafted in
Plan 2 / the ADRs, and each remains reversible by Kevin at review time.

### D-1 (ADR 0008, persisted agent inferences): OPENED — accept and implement

The single highest-leverage decision. Resolutions for ADR 0008's four open
questions:

1. **Packet format:** leave `minerva.research-brief.v2` canonical bytes
   unchanged for this milestone. Inferences appear in the Markdown brief in
   their own clearly labeled section; the v2-omits-inferences divergence is
   documented in the ADR and DECISIONS.md, and the `v3` packet question is
   deferred to the first consumer-facing packet revision (the D-2 era), when a
   version bump will be forced anyway. Rationale: smallest reviewed change to
   the highest-integrity surface; preserves golden fixtures and the offline
   verifier contract.
2. **Promotion into a finding:** yes, explicitly, never automatically.
   `finding add --from-inference <id>` creates the human finding and records
   an append-only promotion link in the same atomic transaction (a fourth
   table, because `BEFORE UPDATE` triggers correctly forbid setting a link
   column after insert). The finding is the human's assertion; the inference
   remains as provenance.
3. **Doctor:** yes — `doctor` verifies inference citation integrity,
   symmetric with findings.
4. **CLI verb shape:** `assist adopt` (keeps the assistance surface together,
   per ADR 0003's boundary).

Non-negotiables carried from the ADR: migration 0005 ships the retraction
table and the reading-surface visibility **in the same change** (the D-9
lesson); adoption revalidates citations, rescans for secrets, and is
idempotent by unique constraint; inferences never influence claim status,
never count, and can never be cited as evidence.

### D-10 (manifest taxonomy + CLI-only withdrawal boundary): DONE 2026-07-30

Record the CLI-only evidence-withdrawal boundary in DECISIONS.md and fix the
capability-manifest `.cli` taxonomy in one reviewed change. The REST
withdrawal endpoint stays deferred until D-2 creates a real protocol consumer.

Delivered: DECISIONS.md gained the "CLI-only correction verbs and the manifest
taxonomy (gate D-10)" section; `minerva.capabilities.v2` additively gained
`evidence.withdraw.cli` and `finding.retract.cli` (the symmetric correction
vocabulary, both CLI-only), with the manifest/verb correspondence test
extended. No REST withdrawal endpoint was added.

### D-11 (ADR 0004 amendment, staged migration during restore): DONE 2026-07-30

Allow `restore_from` to migrate the staged copy inside the audited staging
pipeline before publication, with deep-doctor on the migrated staging state
and provenance-correct audit events. Closes the pre-upgrade-backup recovery
gap.

Delivered: ADR 0004 carries the second amendment recording the gate decision;
`restore_from` accepts an intact older-schema backup, migrates the staged copy
(never the live DB), records `database.migrated`
(`from_schema_version`/`to_schema_version`) atomically with the migration and
`database.restored`, deep-validates the migrated staging state, and publishes
exclusively. Upgrade-recovery and fail-closed migration-failure tests added;
DECISIONS.md, ROADMAP.md, ARCHITECTURE.md, and README updated.

### Gates NOT opened now

- **D-2 (authenticated Athena seam):** blocked on a real counterpart — Athena
  must be able to hold a keypair first. Revisit after Phases 1–2 land, with a
  concrete Athena-side design in hand.
- **D-3 (Icarus experiment exchange):** follows D-2's shape.
- **D-5 (MCP server):** correctly deferred until D-2 authentication exists;
  read-only tools first when it happens.
- **D-4, D-6, D-7, D-8:** remain closed (multi-user/remote, retrieval &
  ingestion expansion, signing, confidence methods). No work without Kevin.

## 4. Execution phases

Each phase is one or more reviewed PRs on `kimi/*` branches, full AGENTS.md
gate suite green before merge, no force-pushes, no direct commits to main.

### Phase 1 — D-1: persisted agent inferences (the research-center unlock)

1. Mark ADR 0008 accepted with the four resolutions above; record D-1 in
   DECISIONS.md and the gate register.
2. Migration 0005: `agent_inferences`, `agent_inference_citations`,
   `agent_inference_retractions`, `agent_inference_promotions` — STRICT,
   CHECKed identifiers, mission-composite FKs, append-only triggers, recorded
   SHA-256 checksum, mirroring the finding tables.
3. Service layer: adoption (preview-digest-bound, revalidating), retraction,
   promotion; metadata-only audit events; capability-manifest adoption entry.
4. CLI: `assist adopt`, `assist retract-inference`, and
   `finding add --from-inference`; README command table updated (the
   table-completeness test enforces this).
5. Visibility, same change: `mission show`, `claim show`, REST finding
   endpoints, web review page — retraction state with reason/timestamp/actor
   everywhere findings appear.
6. Markdown brief: labeled agent-inference section; v2 JSON unchanged and a
   regression test pinning that.
7. Doctor deep-check for inference citation integrity.
8. Tests: adversarial adoption fixtures (injection-shaped content, withdrawn
   evidence between preview and adoption, secret-pattern re-scan, duplicate
   adoption), retraction-visibility on every reading surface, migration
   checksum, coverage floor held.

### Phase 2 — D-10 + D-11: operational hardening — DONE 2026-07-30

- D-10: DECISIONS.md boundary record + manifest taxonomy revision, one PR.
- D-11: ADR 0004 amendment + staged-migration-during-restore + audit events +
  upgrade-recovery test, one PR.

### Phase 3 — D-2 preparation (no code in Minerva until Kevin opens D-2) — DONE 2026-07-30

Athena survey and ADR drafting complete. Survey summary: Athena (v0.1.0a1,
FastAPI + SQLite) has stable named agent principals as DB rows (`is_agent`
users, scoped `ath_` bearer tokens SHA-256 hashed at rest, every write
attributed) and reserved run-prefix namespaces (`automation:`, `icarus:`) — but
those are run namespaces, not principals, and no `athena:planner-1`-style
external principal URN exists. Athena holds no asymmetric keys and signs
nothing asymmetrically; all inter-service trust is shared-secret HMAC-SHA256
(env-keyed outbound signatures, constant-time inbound verification). It already
produces/consumes schema-versioned JSON artifacts atomically under the same
`<system>.<artifact>.v<N>` convention as Minerva, and `cryptography` is already
a transitive dependency via `pyjwt[crypto]`. Zero references to Minerva or
Oracle exist in the Athena repo. The gap to "hold a keypair" — the D-2
precondition, currently **unmet** — is five narrow, idiomatic items:

1. a private-key store (0600 file or DB column), following its shown-once
   secret lifecycle and token-rotation conventions;
2. an external-facing principal URN bound 1:1 to a public key;
3. request signing over canonical request bytes/digest;
4. out-of-band public-key publication to Minerva; and
5. optionally an artifact-writing seam (atomic versioned JSON writes already
   exist).

Delivered: `docs/adr/0009-external-principals-and-request-attribution.md`
(principal registry + signed request attribution, migration 0006 sketch,
ed25519 over HMAC with the HMAC counterpoint recorded) and
`docs/adr/0010-athena-coordination-adapter-seam.md` (the seam flow, the five
gap items, and an Athena-side work list) — both **Proposed, gate D-2, decision
pending Kevin's review**; indexed in DECISIONS.md. No code, no migration.

### Later (gated, in order)

D-2 implementation → D-3 (Icarus artifacts, migration 0007) → D-5 (read-only
MCP) → packet v3 (inferences visible at the protocol boundary) → D-6-era
ingestion/retrieval design discussions.

## 5. Working protocol

- Gates before any "done": the full AGENTS.md command list — ruff (check +
  format), strict mypy, pytest with the 88% branch floor, build + verify_dist
  + installed_smoke, static_security_check, `uv pip check`, `git diff --check`.
- Provider tests use fakes only; never a live or billable call.
- Append-only means append-only: corrections extend the record.
- Honest verification: anything not actually run is reported as open
  verification, not a pass.
- Commit attribution follows CONTRIBUTING.md; PR descriptions carry no real
  sources, credentials, private paths, or personal data.

## 6. Execution state (checkpoint, 2026-07-30)

Branch `kimi/d1-agent-inferences`, all work **uncommitted** awaiting Kevin's
go-ahead to commit and open the PR. Parent agent independently re-ran the gate
suite after all three phases: **737 tests passed, branch coverage 90.46%**
(floor 88%), strict mypy clean (54 files), ruff check + format clean,
static_security_check clean, `git diff --check` clean. Build/verify_dist/
installed_smoke last run green by the implementing agents after Phases 1–2.

Delivered:

- **Phase 1 — D-1 (ADR 0008, accepted):** migration 0005
  (`agent_inferences` + citations + retractions + promotions, append-only
  triggers, ids `inf_`/`inr_`/`inp_`); `assist/adoption.py` `AdoptionService`;
  CLI `assist adopt`, `assist retract-inference`,
  `finding add --from-inference`; visibility on `mission show`/`claim show`/
  `claim ledger`, REST (read-only sibling array), web pages (autoescaped);
  labeled Markdown brief section with v2 JSON bytes provably unchanged;
  doctor `inference_integrity` deep check; capability manifest entries;
  audit events `assist.inference.adopted/.retracted/.promoted`.
- **Phase 2 — D-10 + D-11:** manifest truthfulness (`evidence.withdraw.cli`,
  `finding.retract.cli`) + CLI-only correction boundary recorded; ADR 0004
  amendment — restore migrates the staged copy, deep-doctor validates the
  migrated staging state pre-publication, `database.migrated` provenance
  event; upgrade-recovery and fail-closed tests.
- **Phase 3 — D-2 preparation:** Athena survey (precondition "holds a
  keypair" UNMET, five idiomatic gap items) + ADR 0009 (principals and
  signed request attribution, migration 0006 sketch) + ADR 0010 (Athena
  seam) drafted as **Proposed, decision pending Kevin**.

Awaiting Kevin, in order:

1. Go-ahead to commit + open the PR for Phases 1–2 (git mutations are held
   for explicit approval).
2. Review of ADR 0008's four resolutions and ADRs 0009/0010's open questions.
3. Gate D-2 decision — blocked on the Athena-side keypair work regardless
   (surveyed gap list lives in ADR 0010).
4. D-3 / D-5 / packet-v3 / D-6+ remain closed until then.

Known small follow-ups recorded for review: `finding add` argument errors
moved from argparse exit-2 to structured exit-3; `finding.retract.cli` was
added alongside the requested withdrawal entry (same truthfulness class);
ADR 0009 notes accepting it adds Minerva's first crypto runtime dependency
(ed25519 verification). Resolved since this list was drafted: the synthesis
preflight counts adopted-inference statement/uncertainty bytes at exact
Markdown multiplicity on both paths — claim-scoped and mission-wide —
non-retracted only, Markdown builds only (JSON-only builds are unaffected),
with exact-delta, refusal-before-assembly, just-under, retracted, and
JSON-only regression tests on each path. Preflight parity is complete.
