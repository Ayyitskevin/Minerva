# Roadmap

## Milestone 1: provenance-first local foundation

- Immutable local UTF-8 source snapshots and exact citations
- Mission, question, falsifiable claim, evidence, finding, and uncertainty workflow
- Append-only audit with SQLite mutation/audit transaction atomicity
- Deterministic Markdown/JSON briefs
- Shared services behind CLI, strict REST, and server-rendered review UI
- Offline synthetic demo, packaging, backup/restore, doctor, and security gates

## Milestone 1.1: protocol-ready research packet

- The existing `research-brief.json` is upgraded in place to the canonical strict
  `minerva.research-brief.v2` packet; no parallel interchange artifact is introduced.
- Deterministic canonical serialization and SHA-256 verification are independent of
  SQLite at the protocol boundary.
- The packet preserves exact citations and all evidence stances, research findings and
  uncertainty classes, creator/run provenance, and relevant audit references.
- Local source intake double-reads the same pinned descriptor and fails closed when
  content or path identity changes during the snapshot window.
- Restore audit writes and deep validation complete on unpublished staging state before
  exclusive publication; public replacements are never removed during failed restore.
  Since the gate D-11 amendment to ADR 0004, a pre-upgrade backup is migrated forward
  on the staged copy — with a `database.migrated` provenance event — before that deep
  validation and publication.
- Machine-readable ownership states that Minerva researches but does not execute,
  approve, orchestrate, or publish.
- The additive `minerva.capabilities.v2` manifest advertises canonical packet support
  and truthfully marks sibling exchange, a shared run envelope, orchestration,
  experiment execution, and approval authority unavailable.

## Milestone 1.2: portable packet tooling

- Installed `minerva packet verify` reads and verifies the canonical artifact directly
  without SQLite, network access, provider credentials, or a second packet format.
- `minerva packet inspect` returns bounded schema, digest, count, provenance/audit,
  and ownership metadata without disclosing research contents or private paths/IDs.
- Packet file intake rejects parent segments, symlinks, non-regular or changing files,
  and over-limit input before JSON decoding; expected errors are stable and
  non-reflective, with fail-fast sequence validation and bounded error classification.
- Audit verification rejects dependency-order inversions and forward citation
  supersession with linear-time dependency and supersession checks.
- Installed-wheel smoke exercises both commands outside the source checkout.
- Digest integrity remains explicitly distinct from authenticity, and Athena/Icarus
  artifact exchange remains unimplemented.

## Milestone 1.3: offline research request contract

- Strict `minerva.research-request.v1` canonical JSON and SHA-256 self-verification
  are independent of SQLite, provider credentials, network access, and sibling systems.
- The sole `complete_claim_ledger` selection policy uses a sorted exact active-citation
  set as a freshness/completeness precondition, preventing silent adverse-evidence
  omission while retaining withdrawn and supersession history in fulfilled output.
- `minerva request verify` returns bounded, non-reflective metadata and rejects unsafe
  files, hostile JSON, unsupported versions/policies, invalid identifiers, and digest
  changes before any database is constructed or opened.
- `minerva request fulfill` resolves mission, claim, ledger, and claim-scoped synthesis
  in one query-only read snapshot, writes fixed canonical brief/result files without
  overwrite, and performs no research, audit, identity/run, or export-table mutation.
- Fulfillment caps cumulative SQLite virtual-machine work across the complete read
  snapshot and fails closed with `brief_work_limit` before artifact writes; this
  milestone includes no schema migration.
- Before full database text or snapshot content is returned to Python, claim-scoped
  preflight applies an exact-multiplicity NUL-safe storage-byte lower bound, preventing
  oversized valid-schema history from reaching Python when the canonical packet cannot
  fit. SQLite may still inspect the stored values.
- `minerva.research-result.v1` binds the request digest to the exact canonical v2 output
  bytes and carries no path, URL, actor, authority, timestamp, or coordination fields.
- Installed-wheel smoke exercises verify, fulfill, and packet verification outside the
  checkout. Capabilities advertise only these local CLI/file surfaces.
- A claim-scoped v2 packet remains internally canonical but has no completeness marker;
  request/result artifacts carry the selection meaning. Digest integrity is not
  authentication, authorization, approval, origin, or permission to disclose.

## Milestone 2B: explicit evidence-constrained model assistance

- Optional OpenAI and Anthropic extras with operator-supplied environment credentials
- CLI-only exact-context preview and digest-bound external-send confirmation
- Bounded active-evidence disclosure with opposing/inconclusive evidence preserved
- One fixed-destination call with no retry, redirect, fallback, tools, or URL fetching
- Strict structured-response and evidence-ID validation
- Ephemeral, candidate-only `agent_inference` output with no automatic persistence
- Metadata-only requested/terminal audit events with honest unknown-outcome handling

## Milestone 1.4: targeted fulfillment indexing

- Forward-only migration 0003 adds `idx_audit_event_entity` on
  `audit_events(event_type, entity_id)` and `idx_findings_claim` on
  `findings(mission_id, claim_id, created_at, id)`; no table, column, trigger, or
  data change.
- Claim-scoped fulfillment work becomes independent of unrelated missions' audit
  history, redeeming the Milestone 1.3 indexing deferral.
- Claim-scoped finding queries name `idx_findings_claim` with `INDEXED BY`, so a
  missing index fails loudly at statement preparation. The hint does not guarantee
  a seek, and `idx_audit_event_entity` is planner-selected; the query plans are
  pinned by an `EXPLAIN QUERY PLAN` regression test.
- The cumulative work budget, `brief_work_limit` refusal, storage-byte preflight,
  and every other Milestone 1.3 control are retained unchanged.
- Canonical output is unchanged: every order-sensitive read orders by a unique key,
  and regression tests assert byte-identical fulfillment across added history.

## Milestone 1.5: finding retraction (decision gate D-9)

- Append-only `finding_retractions` (migration 0004) lets an operator record
  that a finding is no longer asserted, so withdrawing cited evidence no longer
  disables brief export and claim-scoped fulfillment for the mission forever.
- `minerva finding retract` mirrors `evidence withdraw` as a CLI-only correction
  verb; the finding, its citations, and its audit history are all retained.
- The withdrawn-citation refusal is scoped to material findings, matching PRD
  invariant 8, so an assumption or unresolved question may keep an optional
  citation to withdrawn evidence with the citation marked withdrawn.
- `minerva.research-brief.v2` is unchanged: a retracted finding is absent from
  the packet rather than flagged inside it.

## Later milestones, not implemented now
- Authenticated Athena mission/identity coordination adapter that may produce the
  existing request artifact only after a separately reviewed identity/authorization
  boundary; no transport or adapter exists in Milestone 1.3
- Approved Icarus experiment request/result artifacts
- Tribunal approval references that bind a packet digest without changing research
  claim status
- Bounded versioned artifact exchange with Vanguard and Warren after their roles and
  trust contracts are separately approved
- A separately versioned shared run envelope for correlation and recovery metadata
- Oracle archival adapter for digest-addressed sources and final artifacts
- MCP after the core contract is stable and authenticated
- Autonomous web research, URL fetching, crawling, PDF/OCR ingestion
- Semantic/vector search and optional local search indexes
- Additional LLM providers, local-model adapters, or model-assisted synthesis beyond
  the bounded ephemeral finding-candidate surface
- Confidence/quality assessment methods that do not reduce to evidence counts
- Sandboxed notebook/experiment execution
- Signed exports, encryption at rest, remote access, multi-user authorization, and
  multi-tenancy
- Carefully governed plugin protocol (not a marketplace or arbitrary code loader)

Medical diagnosis, legal conclusions, live financial actions, external publishing,
cloud hosting, email, Slack, and other messaging remain out of scope unless a future
approved product milestone establishes an appropriate safety boundary.
