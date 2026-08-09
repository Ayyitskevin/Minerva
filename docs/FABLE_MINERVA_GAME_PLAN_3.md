---
repository: Ayyitskevin/Minerva
phase: FABLE_PLANNING
status: READY_FOR_OPUS
base_commit: b650c01 (merge of PR #31)
supersedes: docs/FABLE_MINERVA_GAME_PLAN_2.md
---

# Fable Minerva game plan 3

Plan 1 carried Minerva through Phase 0. Plan 2 carried it through Phase
0C and the first four recorded decision gates (D-9; then D-1/D-10/D-11
on 2026-07-30). This plan supersedes plan 2 as the working document;
plans 1 and 2 and the Kimi plan are preserved unchanged as historical
records. Everything below was verified against `main` at `b650c01` on
2026-08-09; nothing is quoted from a prior document without re-checking.

Reading order for Opus: section 3 (the findings this plan exists to
fix), section 5 (the ordered issues), section 6 (what not to touch).

## 1. Executive summary

The repository is healthy and completely integrated. All eleven
AGENTS.md gates pass at `b650c01` in the locked environment: **759
tests, 90.46% branch coverage** against the 88% floor; ruff, mypy,
build, dist verification, installed-wheel smoke, static security check,
`uv pip check`, and `git diff --check` all clean. Every one of the
sixteen remote branches is an ancestor of `main`; nothing is unmerged.
Tag `v0.2.0a1` is published and peels to `b162573`.

One process fact drives this plan's shape: **PR #31 — the gate D-1,
D-10, and D-11 implementation (migration 0005, `assist adopt`,
`assist retract-inference`, `finding add --from-inference`, the
manifest correction vocabulary, staged restore migration) — merged
2026-07-30 with no recorded review.** This plan's section 3 is the
first recorded review of that work. The review confirmed the work is
substantially sound — trigger coverage, promotion atomicity, canonical
v2 byte-stability, adoption revalidation, D-11 fail-closed staging all
have real failing-test witnesses — and found **two high defects and
one medium**, all three reproduced against the shipped code, all three
instances of contract clauses the accepted ADR 0008 states but nothing
enforced. That is the same failure class plan 2 found after D-9
("landed in the database but not on the reading surfaces"), now on the
verification surfaces, and it is fixable without any new gate.

Phase 0E is therefore narrow: fix the three confirmed findings with
invariant-level regressions, retire the small ungated debt plan 2 left
(one unwired security primitive, two ledger backlog items), and
reconcile the two documents that have drifted (CHANGELOG, execution
state). No migration, no new surface, no contract change. Entirely
within Opus's standing authority, with the two judgment calls flagged
for Kevin inside the PR rather than silently absorbed.

Beyond Phase 0E, every increment of value still runs through gate D-2,
and the facts around D-2 have changed since plan 2 wrote "hold D-2
until Athena can hold a keypair" — Athena now ships credential
primitives. Section 4 is decision material for Kevin, not work: this
plan does not begin D-2.

## 2. What landed since plan 2 (verified)

- Phase 0C issues 1–12 all closed (PRs #15–#25), plus three closure
  gaps a Codex audit surfaced, closed by PRs #28 (release record), #30
  (retraction-rendering and `sendmsg` guard witnesses), and #29
  (directory-entry durability for publication).
- Post-Phase-0C verification fixed two unenforced contract claims:
  digest-algorithm constants now drive packet emission, and manifest
  `.cli` entries are checked against real parser verbs.
- PR #31 delivered the three gates Kevin recorded on 2026-07-30:
  - **D-1** (ADR 0008 accepted): persisted, human-adopted, retractable
    agent inferences — migration 0005 (schema 4→5, four append-only
    tables, eight triggers), mandatory same-claim citations, secret
    rescan at adoption, promotion links, Markdown-only rendering in a
    labeled section, REST read surface, web badges.
  - **D-10**: the CLI-only correction boundary recorded;
    `evidence.withdraw.cli` and `finding.retract.cli` manifest entries.
  - **D-11**: `restore_from` migrates a pre-upgrade backup forward on
    the private staged copy with a `database.migrated` provenance
    event, deep-validated before exclusive publication.

## 3. First recorded review of PR #31 — findings ledger

Method: adversarial review of `758fe8a` and `c3e142f` against ADR 0008,
the three DECISIONS.md gate sections, and ADR 0004's second amendment;
every claimed property traced to code and to a witness test; both high
findings and the medium reproduced with standalone scripts against the
shipped code. Verified-sound properties are recorded at the end of this
section so the good work is on the record.

### F3-DOCTOR-1 — high, CONFIRMED (reproduced)

**Deep doctor never reconciles the four new inference tables against
their audit events, so a tampered delete silently resurrects a
retracted model inference into the exported brief.**

`_verify_material_audit_links` (`core/doctor.py:511-524`) lists eleven
expected event types — none of `assist.inference.adopted`,
`assist.inference.retracted`, `assist.inference.promoted` — and its
body has no loop over `agent_inferences`,
`agent_inference_retractions`, or `agent_inference_promotions`. The new
`inference_integrity` check validates citations of live inferences
only; it reconciles nothing against audit history.

Reproduced: adopt an inference, retract it, then drop the two
retraction triggers, `DELETE` the retraction row, and recreate the
triggers byte-identically. `doctor --deep` stays green (the trigger
fingerprints match), the retracted inference returns to the Markdown
brief as asserted, and the `assist.inference.retracted` audit event
dangles with no row — undetected. The identical tamper on a *finding*
retraction fails `material_audit_integrity`, because the finding path
has exactly the reconciliation the inference path was not given. This
is the outcome ADR 0008 exists to prevent (machine text laundered into
the record), surviving on the surface whose job is to catch it.

### F3-ADOPT-1 — high, CONFIRMED (reproduced)

**Adoption stores a locally recomputed `request_sha256` that need not
match the request that produced the recorded `response_sha256`, and the
idempotency key built on it is unstable.**

`_cmd_assist_adopt` regenerates the preview from live state at adopt
time and stores `preview.request_sha256` verbatim
(`assist/adoption.py:154`); the `adopt` subparser has no
`--expected-request-sha256` and nothing cross-checks the supplied
`response_sha256` against the recorded terminal audit event. The invoke
path already implements the pin (`assist/service.py:331-346`); adopt —
the verb that *persists* — is the one place it is missing.

Reproduced: change the evidence ledger between invoke and adopt. The
stored record pairs an adopt-time request digest with the
generation-time response digest — a provenance link that never existed
on the wire — and because the unique triple
`(request_sha256, candidate_index, claim_id)` incorporates the unstable
digest, the same reviewed candidate adopts twice. ADR 0008 promises
both the reconstructable provenance pair and the refusal of repeated
adoption; neither holds across any ledger change in the review window.

### F3-BRIEF-1 — medium, CONFIRMED (reproduced)

**Inference reading surfaces do not carry per-citation withdrawal
state; after post-adoption withdrawal, the brief renders the citation
as if active while deep doctor fails and backups are blocked.**

The Agent-inferences Markdown section renders citations with no
withdrawal marker (`synthesis/service.py:1686`), unlike the findings
section (`:1653`). Meanwhile `inference_integrity` verifies citations
with `allow_withdrawn=False` (`core/doctor.py:373`) and is not in
`BACKUP_ADVISORY_CHECKS`, so withdrawing evidence an old inference
cites — two documented first-class verbs used in sequence — produces a
clean-looking export, a deep-doctor failure, and a refused backup, with
no guidance toward the remedy (retract the inference). Honest use must
not read as corruption, and a machine inference must not out-assert a
human finding on the same surface.

### F3-GIT-1 — low, recorded only

The D-10 manifest entries and their witness test shipped in `758fe8a`
(the D-1 commit) while `c3e142f`'s message and the DECISIONS.md D-10
section present them as the D-10 change. Functionally correct and fully
tested; attribution across the two commits is off. No code change —
this entry is the record.

### Verified sound (witnesses confirmed, kept on record)

- All eight migration-0005 append-only triggers exist, are derived into
  doctor's required set, and are exercised end to end.
- Canonical `minerva.research-brief.v2` bytes are unchanged; the golden
  fixture predates the PR and still passes; inferences render in
  Markdown only.
- Promotion is atomic (one transaction), once-only
  (`UNIQUE(inference_id)`), refuses retracted inferences, and leaves
  nothing behind on failure; the `add_finding` refactor threads a
  shared connection rather than duplicating the writer.
- Adoption revalidates citations against the live record with
  `allow_withdrawn=False` and claim-scope checks, rescans for secrets,
  bounds stored values, and stores injection-shaped content verbatim
  and safely.
- No new trust surface: adoption is CLI-only; REST exposes a read-only
  sibling array; web is display-only; `model.output.auto_adopt` is
  explicitly listed unavailable.
- Manifest `.cli` entries added by the PR name real verbs, pinned by
  test.
- D-11 staged migration is fail-closed and provenance-correct:
  validation before staging, deep doctor on the migrated staging state
  before publication, `migration + database.migrated +
  database.restored` in one transaction on the staged copy,
  `database.migrated` recorded only when history actually advances.

## 4. Gate D-2 readiness (decision material for Kevin — not work)

Plan 2 closed with "hold D-2 until Athena can hold a keypair." Verified
2026-08-09 against Athena at `6235ec9`: Athena now ships scoped agent
tokens, OIDC, signed webhooks, run lineage, MCP, and a credential kill
switch as product primitives, and `cryptography` is already in its
transitive dependency set. The precondition is no longer hypothetical;
the five-item Athena-side gap list in the Kimi plan (0600 key store,
principal URNs, signing call-site, out-of-band public-key export,
artifact seam) is real but bounded work.

ADRs 0009 and 0010 are drafted and internally consistent. Before
recording D-2, the acceptance should resolve, explicitly rather than by
silence:

1. **The scope narrowing.** ADR 0009 is deliberately narrower than plan
   2 §15 briefed: transport selection, capability-grant vocabulary,
   nonce/expiry replay defense, and per-principal rate bounds are all
   deferred. The drafts substitute a digest-uniqueness registry for
   replay defense and a file drop-box for transport. Accepting them as
   drafted should either adopt those substitutes on the record or name
   the follow-up ADRs that will carry the deferred concerns.
2. **Key validity.** The ed25519 CHECK validates 64-hex shape, not
   curve validity; registration must parse the key with the chosen
   library and refuse garbage.
3. **Rotation.** Revoke-and-re-register forces URN churn; attribution
   continuity across rotation is explicitly punted. Say so in the
   acceptance or fix the shape first.
4. **Trust-on-first-registration.** The registry is only as strong as
   the operator's manual key delivery; the runbook is part of the
   boundary.
5. **The sidecar/envelope format** for the signature is unspecified in
   both ADRs and will need its own strict parser with hostile-input
   tests.
6. **Minerva's first crypto runtime dependency** (ed25519 verification)
   needs naming, pinning, and a static-gate allowlist decision — a
   review-gated surface.

This plan does not begin D-2, and Phase 0E must not either.

## 5. Phase 0E — ordered implementation issues (ungated)

Standing constraints, unchanged: no migration, no new trust surface, no
contract change; every fix carries an invariant-level regression test
verified to fail on the pre-fix code; canonical JSON output stays
byte-identical (the golden-fixture tests must pass untouched); all
eleven gates green before "complete."

1. **F3-DOCTOR-1 fix.** Extend `_verify_material_audit_links` to
   reconcile `agent_inferences`, `agent_inference_retractions`, and
   `agent_inference_promotions` against `assist.inference.adopted` /
   `.retracted` / `.promoted`, mirroring the finding/retraction
   reconciliation in both directions (row without event, event without
   row, count mismatch). Regressions: the trigger-drop/delete/recreate
   tamper on each of the three tables must fail deep doctor; the
   dangling-event direction must fail too; a healthy database with
   adopted, retracted, and promoted inferences stays green.
2. **F3-ADOPT-1 fix.** Give `assist adopt` the same
   `--expected-request-sha256` pin the invoke path has, compared
   against the freshly recomputed preview digest before anything
   persists; mismatch refuses with the existing stable
   context-changed error shape and persists nothing. Make the flag
   required: an optional pin is no pin, the verb is ten days old in an
   `a1` pre-release, and README/help text updates travel in the same
   change. The stored `(request_sha256, response_sha256)` pair then
   always reflects a real wire exchange, and the idempotency triple is
   stable for a given reviewed request. Regressions: ledger change
   between invoke and adopt refuses; double adoption of the same
   reviewed candidate refuses; steady-state adoption unchanged.
3. **F3-BRIEF-1 fix.** Two coordinated changes, flagged in the PR
   description as a semantic change to a doctor check:
   (a) render per-citation withdrawal state inline in the
   Agent-inferences Markdown section exactly as the findings section
   does; (b) verify inference citations in `inference_integrity` with
   `allow_withdrawn=True` so post-adoption withdrawal is visible state
   rather than an integrity failure — withdrawal marked on the surface,
   retraction remaining the operator's judgment (the D-9 rule: never
   auto-retract), backups no longer blocked by honest use. Citation
   *absence or tampering* must still fail the check. Regressions: the
   reproduced scenario now exports with a withdrawn marker, deep doctor
   green, backup succeeds; a genuinely dangling inference citation
   still fails; a DECISIONS.md entry records the semantics.
4. **CHANGELOG reconciliation.** The Unreleased section says nothing
   about anything PR #31 shipped. Add the reader-noticeable entries
   (adopt/retract-inference/promote verbs, manifest entries, staged
   restore migration) and the Phase 0E entries, in the changelog's
   established voice.
5. **Execution-state reconciliation.** `docs/OPUS_EXECUTION_STATE.md`
   still holds integration on PR #29 (merged), lists D-1/D-10/D-11 as
   awaiting Kevin (decided 2026-07-30), and carries schema-4/30-trigger
   baselines superseded by migration 0005. Follow the file's own
   convention: a dated corrections section, never silent edits.
6. **F2-SURFACES-4 retirement.** `CsrfProtector`
   (`web/security.py:401`) is implemented, tested, and wired to
   nothing; no unsafe form exists to protect. Delete it and its tests,
   with the removal recorded in DECISIONS.md ("re-add with the first
   unsafe form" — the git history keeps the implementation). An unwired
   security primitive is a false affordance. Flagged in the PR: it
   touches a security file.
7. **Ledger remainder.** F2-INTEGRATIONS-2 (overflow-literal
   classification) and the F2-SYNTHESIS-3 residual wording nit ("The
   active evidence selection has changed" is inaccurate for the
   overflow case) — both small, both carry a regression or a corrected
   string with its test.

Estimated shape: one PR, seven commits in the order above, no
migration. Issues 1–3 are the substance; 4–7 are hygiene the doctrine
requires (R12: entropy is the enemy).

## 6. What Opus must not do

- No D-2, D-3, or D-5 implementation, however finished the drafted ADRs
  look. Two empty principal tables shipped early is still a trust
  surface shipped without its gate.
- No packet v3; the question waits for its first consumer (D-2 era).
- No new providers, retrieval, semantic search, MCP, or web/API
  adoption surfaces.
- No edits to plans 1/2, the Kimi plan, or accepted ADR texts (new
  DECISIONS.md sections and dated corrections are the amendment
  vehicle).
- No changelog entries for unreleased behavior described as released.

## 7. Decision-gate frontier (verified 2026-08-09)

| Gate | Subject | Status |
| --- | --- | --- |
| D-1 | Persisted agent inferences | Decided 2026-07-30, implemented (PR #31), first review = this plan |
| D-9 | Finding retraction | Decided, delivered, verified |
| D-10 | CLI-only correction boundary | Decided 2026-07-30, implemented |
| D-11 | Staged restore migration | Decided 2026-07-30, implemented |
| **D-2** | **Athena principals + adapter** | **Proposed (ADRs 0009/0010); section 4 is the acceptance checklist** |
| D-3 | Icarus artifacts | Unopened; follows D-2's shape |
| D-4 | Remote/multi-user | Unopened; stays banned |
| D-5 | MCP | Unopened; blocked on D-2 auth |
| D-6 | Retrieval/OCR/crawling | Unopened; out of this horizon |
| D-7 | Signed exports | Unopened; D-2 would supply the signer |
| D-8 | License | Unopened; human legal decision |
