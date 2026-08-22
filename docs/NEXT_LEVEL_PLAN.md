# Next-level implementation plan

Status: deployed to mickey at `bfe5a2c` on 2026-08-22; a formal tagged
release remains pending.

Kevin authorized the complete plan and delegated delivery order to the implementing
seat. Work proceeds in this order:

1. Establish the pillar scorecard, dogfood baseline, and recovery evidence.
2. Build the read-only operator workbench and concise CLI overview.
3. Add real-corpus retrieval evaluation and improve safe local intake.
4. Complete sustainability, documentation, release, and operational gates.
5. Re-evaluate authenticated integrations only after their existing security and
   counterpart-readiness gates are proven and separately approved.

Later phases do not become authorized merely because this order is recorded. The
boundaries in `VISION.md`, `AGENTS.md`, the threat model, and accepted ADRs still
govern each slice. In particular, Decision 0 remains in force: this season optimizes
Minerva as mickey's research-memory, while D-2, MCP, remote bind, automatic adoption,
and publication remain closed until their explicit gates are satisfied.

Each phase must produce measurement evidence, pass the eleven repository gates, and
be usable against the persistent mickey workflow before the next phase begins.

## Owner decisions

- Genuine research records may be added to the persistent mickey database when they
  capture evidence produced by real implementation or evaluation work. Synthetic
  records remain confined to disposable databases and checked-in fixtures; usage
  counts must never be inflated to simulate adoption.
- Repository doctrine and rules are amendable when an improvement is supported by
  evidence. Amendments must name the superseded rule or decision, preserve history,
  update the authoritative document, and add regression coverage where behavior
  changes. This authorization does not silently amend fleet-wide doctrine or open a
  gated security, identity, publication, or remote-access capability.
- The owner approved Apache License 2.0 for the public repository. Adding the license
  is part of the sustainability/release phase; the release record must name the
  licensing change rather than implying earlier tagged source carried that license.
- The owner declined DeepAPI setup for this project. Minerva must not gain a DeepAPI
  dependency or integration. External comparative research is skipped by owner
  override; operator-visible changes instead require repository evidence, realistic
  local measurement, and explicit owner review before release.

## Phase outcome

1. Pillar scorecard, genuine dogfood mission, and recovery drill: complete.
2. Read-only operator workbench and concise CLI overview: complete.
3. Real-corpus evaluation and digest-pinned local intake: complete.
4. License, documentation, package verification, and all eleven gates: complete.
5. D-2 and authenticated integrations: evaluated and deferred. Athena still
   cannot hold the required keypair, so the prerequisite is not proven.

The owner explicitly overrode the pending non-author re-review and authorized
shipping. Commit `bfe5a2c` is on GitHub `main` and deployed to the mickey loopback
service. No tag, package release, remote bind, or publication was performed.

## Next build sequence

Owner decision recorded 2026-08-21: implement the next season in this order.

Cockpit status: implemented and measured locally. Safe intake is implemented and
measured locally. The persistent-corpus research-quality evaluation surface is now
implemented, measured, and deployed to mickey. The owner explicitly overrode the
pending non-author trust-boundary re-review after its first HOLD findings were
corrected.

Owner sequencing decision, confirmed 2026-08-21: implement safe source intake next,
then build the research-quality evaluation surface against that improved workflow.
Do not reverse these slices; evaluation should measure the intended intake path rather
than institutionalize the current friction as a baseline product assumption.

1. Build a unified controlled read/write mission cockpit for the daily research loop.
2. Improve safe source intake from preview through evidence filing.
3. Add an evaluation surface for research quality, uncertainty, and operator effort.
   **Complete locally:** the aggregate read-only evaluator measured three genuine
   missions without exporting content, identifiers, or paths.
4. Integration and loopback deployment are complete at `bfe5a2c`; a formal tagged
   release remains pending.

This sequence does not open D-2, MCP, remote bind, automatic adoption,
publication, network fetching, or provider-backed research. Each slice must remain
local-first, use the shared command/service layer, and preserve explicit uncertainty.

### Scoped decisions

- The existing mission detail page becomes the canonical unified cockpit. Do not add
  a parallel global dashboard or a second mission-cockpit route.
- The cockpit is action-first: unsupported claims, review blockers, and queued work
  appear before supporting evidence and chronological history.
- Agents are primary operators. The canonical agent interface remains explicit CLI
  commands through the shared service layer; the loopback cockpit may expose the same
  narrow domain commands for operator use. Do not add generic CRUD.
- Safe intake will be a guided CLI source-to-evidence flow. It should carry an agent
  from bounded local preview and digest confirmation through immutable import, exact
  UTF-8 byte-span selection, explicit stance, and audited evidence creation. The
  cockpit may later mirror this flow, but it is not the canonical intake interface.
- Every mutation must be validated, atomic, audited, and protected by an idempotency
  or precondition mechanism where repetition or stale state could corrupt intent.
  Evidence, citations, and audit history remain immutable; corrections append or
  supersede instead of overwriting history.
- The first writable cockpit slice includes review decisions, queue transitions, and
  claim/finding creation. Source intake and citation attachment remain in the next
  separately verified intake slice.

### Slice design

- “Queue transition” means an explicit claim workflow-status transition selected
  while inspecting a structural cue. Mission Research Queue v1 remains a read-only,
  non-normative index; no assignment, deferment, resolution, completion, or task
  state is added.
- Existing `ResearchService` mutations remain authoritative. The web adapter adds no
  SQL and the existing CLI remains the canonical agent interface.
- The mission page renders the complete structural cue index before evidence/history,
  then exposes narrow POST forms for claim status, claim creation, and finding
  creation. Each successful POST uses post/redirect/get.
- Claim status retains its required claim-version precondition. Claim and finding
  creation gain a mission-audit-sequence precondition checked inside the same
  `BEGIN IMMEDIATE` transaction before any run, domain, or audit row is written.
- The first unsafe HTML forms restore the reviewed signed double-submit CSRF primitive
  from repository history and wire it to every form in the same change. Loopback
  Host/Origin checks, strict form fields, body bounds, local OS-user identity, Jinja
  autoescaping, and non-reflective errors remain in force.
- No schema migration, generic CRUD, REST contract change, external principal,
  remote bind, MCP surface, provider call, automatic adoption, or publication is
  introduced.

### Safe intake decisions

Owner decision recorded 2026-08-21: source import and evidence filing remain two
explicit audited commits. Kevin delegated the remaining intake choices to the
implementing seat and requested the recommended option in each case.

- Preserve `SourceService` as the authority for bounded preview, digest-pinned local
  import, secret screening, immutable snapshots, and source-import audit history.
  Do not combine source import and evidence creation into one mutation.
- Add one deep `EvidenceIntakeService` module with two public operations: a read-only
  preview and an explicit commit. Its small interface hides exact quote matching,
  UTF-8 byte-boundary validation, bounded context rendering, preview-digest creation,
  mission-sequence preconditions, replay protection, and the existing evidence
  transaction. The CLI is an adapter to this module, not the home of domain logic.
- Expose a non-interactive, JSON-first CLI flow for agent operators. After the
  existing source preview/import step, `intake preview` locates exact quote
  occurrences in an immutable snapshot and returns bounded candidates, canonical
  byte spans, snapshot digest, mission audit sequence, and an intake-preview digest.
  `intake file` requires that digest, a selected candidate, and an explicit stance.
  No TTY prompts or inferred answers are allowed.
- Exact matching is authoritative. When a quote occurs more than once, preview
  returns every bounded candidate and commit requires an explicit occurrence;
  silently choosing the first match is forbidden. Line and column values may be
  shown for humans, but UTF-8 byte offsets remain canonical.
- Stance is always one of the existing explicit domain values and is never guessed
  from wording or generated by a model. One invocation operates on one mission,
  one claim, one imported snapshot, and one evidence card.
- The commit regenerates and verifies the preview inside the write boundary, checks
  the expected mission audit sequence before writing, and creates exactly one
  evidence card plus its audit event atomically. A successful first commit advances
  the sequence, so an identical replay fails closed without duplicate evidence.
- Preview output is an inert versioned DTO on stdout, not a new canonical packet,
  database draft, integration artifact, or durable source of truth. The immutable
  snapshot, evidence card, and audit log remain authoritative.
- Limit this slice to bounded local UTF-8 text already supported by Minerva. Do not
  add URLs, network fetching, PDF/OCR, HTML extraction, watched folders, batch
  manifests, fuzzy matching, model-assisted stance, provider calls, or automatic
  evidence adoption.
- Add focused unit and CLI tests for unique and repeated quotes, multibyte text,
  invalid boundaries, digest mismatch, stale mission state, replay, scope mismatch,
  withdrawn or unavailable objects, transaction rollback, and secret-screened
  source import. No schema migration or external protocol change is expected.
- Measure the finished path with realistic local cases before designing the later
  research-quality evaluation surface. Record task completion, failure clarity,
  citation accuracy, operator steps, and replay/stale-state behavior; do not count
  synthetic records as genuine adoption.
- Keep the cockpit out of this implementation slice. It may mirror the reviewed
  service later, but CLI plus the shared service layer remains the canonical agent
  interface until the intake evaluation and non-author review are complete.

Implementation status recorded 2026-08-21: complete locally. The deep intake module,
JSON CLI adapter, public documentation, regression suite, and reproducible 20-case
measurement are present. After the first non-author review fixes, all eleven
repository gates pass with 1,200 tests and 91.65% coverage. No commit, push,
deployment, release, live-database write, or trust
boundary expansion was performed; non-author review remains required.

Research-quality evaluation status recorded 2026-08-22: complete locally. The
repeatable evaluator measured 3 genuine missions, 12 claims, 36 evidence cards, 17
findings, and 205 audit events. Active-evidence claim coverage, mixed-stance status
acknowledgement, supported/contested finding citation coverage, explicit finding
uncertainty, and claim-status coverage were each 100% on this corpus. Actual audited
events to first evidence were 10/11/12 (minimum/median/maximum). The before/after
logical state receipt matched; provider and network calls were zero. This measures
structural research quality and durable workflow effort, not external factual truth,
source quality, clicks, reading time, or unrecorded deliberation. Evidence:
`docs/evals/2026-08-22-research-quality.md`.

Integration and release remain separate. This approved integration does not move or
reuse the immutable `v0.2.0a1` tag and does not publish a package. A new version,
dated release section, tag, and release verification remain required before any
future release.
