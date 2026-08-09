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

## Lens v1: bounded local retrieval (narrow D-6 exception)

- `minerva lens search` performs deterministic, model-free lexical retrieval only
  over immutable snapshots already imported into one named mission.
- One query-only SQLite snapshot owns mission/filter validation, deterministic
  `(imported_at, snapshot_id)` corpus selection, and shared snapshot integrity checks.
- Every `candidate_context` lead carries exact UTF-8 bytes and half-open coordinates,
  source/snapshot identity, normalized query and digest, searched snapshot-set digest,
  algorithm/Unicode versions, integer score components, total rank, configured bounds,
  omissions, truncation, and a whole-receipt digest.
- Candidate stance is unassessed and evidence status is candidate-only. Search has no
  identity, audit, mutation, evidence, finding, inference, provider, network, export,
  or packet side effect; normal evidence creation remains separate and explicit.
- No migration or index is added. Legacy databases still follow the normal explicit
  migration contract; packet v2 and the capability manifest are unchanged.
- A checked-in synthetic harness measures precision/recall, exact byte round trips,
  byte-identical determinism, mission isolation, and zero unauthorized mutation.

## Claim Review v1: evidence gaps and correction impacts

- `minerva claim review` derives one deterministic
  `minerva.claim-review.v1` receipt from an explicitly named mission and claim.
- The view reports active/withdrawn stance counts, missing support or opposition,
  active support-and-opposition conflict, recorded-status requirements, and the
  impacts of evidence withdrawal and finding/inference retraction. These are
  structural observations, never truth, evidence quality, confidence, sufficiency,
  or a recommended status.
- The complete target-claim evidence ledger retains snapshot digest, exact UTF-8
  coordinates, quote digest, supersession lineage, provenance, and correction state.
  Supersession does not deactivate an older card; only an explicit withdrawal removes
  it from the active stance set.
- Correction-relevant findings and inferences show retained retraction history,
  synthesis effects, promotion relationships, and live citations that became
  inactive. A retracted inference does not retract its promoted human finding, and
  retracting that finding does not retract a still-live source inference.
- The view is complete-or-refuse. Evidence, affected-record, relationship,
  distinct-snapshot-byte, and SQLite-work bounds return
  `claim_review_work_limit` instead of a truncated result; success always records
  `complete: true`, `truncated: false`, measured work, and a whole-receipt SHA-256.
  That hash establishes deterministic self-consistency only, not origin,
  authenticity, authority, approval, disclosure permission, or research correctness.
- One query-only SQLite snapshot owns scope and reads. Shared citation/snapshot
  integrity checks run before the receipt returns. There is no identity, audit,
  evidence, finding, inference, status, queue, provider, network, export, packet, or
  capability-manifest side effect, and no migration or index is added.
- A current risk is made explicit rather than repaired: an unretracted adopted
  inference remains in the Markdown brief after one of its citations is withdrawn,
  although an unpromoted inference can no longer be promoted. An earlier promotion
  remains append-only history and its finding is reviewed separately. Claim Review
  flags the inactive-citation condition; canonical v2 JSON still contains no adopted
  inferences, and correction remains a separate human retraction.
- The fixed synthetic Claim Review harness measures four structural gap labels,
  recorded-status validity, six withdrawal-impact edge classes, repeated determinism,
  identifier-based mission isolation, and database-dump/main-file non-mutation.
  UTF-8 citation/digest, promotion, bounds, hostile scope, non-invocation, digest
  verification, and installed-wheel behavior remain separate tests, not evaluation
  metrics.

## Claim Lineage Graph v1: complete claim-owned provenance topology

- The repository owner's 2026-08-08 continuation narrowly accepts
  `minerva claim lineage` and the public local
  `minerva.lineage.ClaimLineageService.build_graph` application service. No family of
  graph APIs or later roadmap item is accepted by implication.
- `minerva.claim-lineage.v1` uses algorithm `structural-ledger-lineage`, scope
  `claim_owned_closure_v1`, fixed typed node/edge order, compact canonical JSON, and
  node-set, edge-set, snapshot-set, and whole-receipt SHA-256 values.
- The graph retains the owning question, complete status history, all claim-owned
  evidence, findings, adopted inferences, withdrawals, retractions, promotions, and
  every referenced snapshot. Exact citation text/base64 bytes, UTF-8 coordinates,
  quote/snapshot digests, source/snapshot metadata, stance, and provenance remain
  inspectable.
- Fixed exclusions prevent silent expansion to sibling claims, claimless findings,
  unreferenced snapshots, audit/run/export/candidate nodes, or reverse dependents.
  Creator/run/time values remain attached as provenance rather than becoming run or
  audit nodes.
- Node, edge, citation-byte, actual distinct-snapshot-byte, output-byte, and cumulative
  SQLite-VM bounds are complete-or-refuse. One query-only read snapshot supplies the
  whole graph; an exceeded bound returns `claim_lineage_work_limit`, never a partial
  topology.
- The graph is structural recorded provenance only. It assigns no truth, evidence
  quality, confidence, sufficiency, score, priority, or recommended status and creates
  no correction, research state, queue, audit event, export/file/packet, provider call,
  network activity, protocol, migration, index, or capability claim.

## Mission Research Queue v1: deterministic structural review index

- The repository owner's 2026-08-08 instruction to continue the accepted dependency
  order narrowly accepts `minerva mission queue` and the public local
  `minerva.research_queue.MissionResearchQueueService.build_queue` application
  service. It does not accept persistence, a family of queue operations, or any later
  roadmap item by implication.
- `minerva.mission-research-queue.v1` uses algorithm
  `claim-review-cue-aggregation` and scope `mission_claim_review_cues_v1`. One
  query-only SQLite snapshot admits every mission-owned claim in stable
  `(created_at, id)` order and derives a complete pinned Claim Review v1 receipt for
  each claim.
- Every pinned Claim Review cue becomes one `structural_review_cue` item. Each item
  retains its category, code, explanation, related record IDs, source review digest,
  and claim/question identity. Every reviewed claim has a separate summary and review
  digest, so claim-set completeness is bound independently from the item array.
- Item order is deterministic presentation, not a relevance score, severity, priority,
  age, actionability judgment, or recommended traversal. Under Claim Review v1 every
  claim has at least one cue: missing support or opposition is a gap, while both
  coexisting is a structural stance conflict. Item presence therefore never means
  unresolved or required work. The assembler still retains a self-consistent zero-cue
  child review as a reviewed-claim summary rather than inferring claim completeness
  from items.
- Claim Lineage remains a separate inspection surface. It supplies deterministic
  topology but no queue reason-code contract, so Queue v1 neither invokes it nor
  converts status/correction rationale into work items. Mission-owned claimless
  findings may appear only as related IDs when existing Claim Review admits their
  correction impact; they never become queue roots.
- Aggregate claim, item, evidence, affected-record, relationship, snapshot-byte,
  output-byte, and SQLite-VM bounds are complete-or-refuse. Claim-set, review-set,
  item-set, and whole-receipt digests bind the result without a generated ID or
  observation time.
- The fixed synthetic Queue harness measures exact claim coverage, reason labels and
  cue entries across the 14-code catalog, related record-ID sets, canonical ordering,
  digest validity, determinism, mission isolation, and zero mutation. It reports no
  priority, relevance, truth, confidence, severity, actionability, or completion
  metric.
- The index is non-normative and read-only. It creates no persisted queue, assignment,
  defer/resolve/completion state, identity, run, audit event, evidence, finding,
  inference, status, correction, export/file/packet, provider call, network activity,
  protocol, migration, index, or capability claim.

## Lens v1 receipt verification and current-database reproduction

- The repository owner's instruction to continue the accepted dependency order
  narrowly accepts local `minerva lens verify`, `minerva lens replay`, the strict
  captured-receipt loader/verifier, and `LensService.replay_receipt(...)`. It does not
  accept a canonical Lens export, historical corpus archive, adoption bridge, external
  protocol, or any later roadmap item by implication.
- Both commands accept the normal `{"lens": {...}}` search CLI envelope through the
  shared no-follow stable regular-file reader. The input is capped at 8 MiB before
  strict UTF-8 JSON decoding; duplicate fields, non-standard numbers, excessive JSON
  shape/fanout, omitted or unknown fields, unsupported versions, and inconsistent
  derived values fail with stable bounded errors.
- Database-free verification recomputes the canonical receipt digest and every
  receipt-contained v1 invariant needed to trust its internal structure: pinned
  schema/algorithm/normalization/runtime, canonical query and filters, snapshot-set
  identity/count/bytes, quote byte/text/digest/span relationships, integer
  scoring/explanation/order, omissions, and truncation. Its bounded report explicitly
  says searched snapshot content was not independently verified.
- Database-backed reproduction first verifies the receipt, then executes its captured
  mission, normalized query/token sequence, filters, and bounds through the existing
  Lens search/integrity path in one current query-only SQLite snapshot. A
  package-private normalized-search seam preserves the exact captured request after
  validation proves it is the version-2 Unicode normalization fixed point; it is not
  a second public search contract.
- Success requires exact complete-receipt equality and reports
  `historical_corpus_replay: false`. Any same-mission snapshot append changes at least
  mission/filter accounting and causes `lens_replay_mismatch`, even if an explicit
  filter excludes that snapshot and candidate results are unchanged. Foreign-mission
  changes do not affect the receipt. No as-of database or historical-source promise
  is made.
- Verification/reproduction writes no artifact, database row, source byte, evidence,
  finding, inference, status, confidence, queue state, packet, or audit event; creates
  no identity/run; reads no credential; and invokes no model, provider, network,
  REST/web endpoint, MCP, Athena/Icarus adapter, or external-agent protocol.
- Receipt digests and successful reproduction establish deterministic
  self-consistency and equality to one current read, not origin, external
  authenticity, identity, authority, approval, truth, quality, historical freshness,
  or disclosure permission. Schema remains v5; no migration, index, capability entry,
  or packet field/version is added.
- Fixture-bound evaluation and regression tests cover strict hostile/tampered input,
  deterministic reports, exact current reproduction, algorithm/Unicode/corpus/result
  drift, mission isolation, content verification only on replay, no model/provider/
  network invocation, and zero research/audit mutation. They make no external quality
  or authenticity claim.

## Review Dossier v1: atomic local review composition

- The repository owner's 2026-08-08 continuation instruction narrowly accepts the
  next dependency only: local `minerva dossier build` and
  `minerva.dossier.ReviewDossierService.build_dossier(...)`. It does not accept a
  persisted/canonical dossier artifact, REST/web or agent-facing surface, mutation
  control, capability claim, or any later roadmap item by implication.
- `minerva.review-dossier.v1` uses algorithm
  `current-snapshot-review-composition` version `"1"` and scope
  `mission_claim_with_captured_lens_v1`. Its five fixed components are the complete
  mission Queue, the exact focal Review retained by that Queue build, focal Claim
  Lineage, the verified operator-captured Lens search, and exact current-database Lens
  replay.
- The existing bounded captured-receipt reader and strict verifier run before database
  open. The receipt must name the explicit dossier mission. One query-only SQLite
  snapshot and one cumulative VM guard then own Lens reproduction, Queue/Review, and
  Lineage. Package-private connection seams reuse existing component services rather
  than creating parallel query or validation paths.
- All structural cross-checks are mandatory: component mission/question scope; exactly
  one focal queue summary; Queue/Review receipt and cue equality; Review/Lineage claim,
  current-status, evidence, and withdrawal agreement; affected claim-owned
  finding/inference payload, citation, retraction, promotion, and provenance agreement;
  any shared Lens/Lineage snapshot identity; and exact Lens replay. The affected-record
  check is limited to the subset reported by Review; unaffected owned Lineage records
  need not appear in Review. A disjoint Lens/Lineage snapshot set is allowed and makes
  no relevance claim.
- Queue, Lineage, Lens, component-output, cumulative SQLite, and final dossier-output
  bounds remain explicit. Dossier success is complete and untruncated, while the
  embedded Lens receipt may independently retain its explicit bounded truncation and
  omissions. Work fields record component and output counts.
- Existing component receipts remain intact. A fixed ordered component-set digest and
  whole-dossier SHA-256 bind compact sorted-key UTF-8 JSON without a generated ID or
  observation time. The replay report is bound by a digest of its complete canonical
  representation. Hashes establish self-consistency, not identity, signature,
  authority, approval, historical freshness, truth, quality, or disclosure permission.
- The dossier is local composition only. It creates no durable artifact, identity,
  run, audit event, task/queue state, evidence, finding, inference, status, correction,
  export, file, packet, provider call, network activity, protocol, migration, index, or
  capability. Lens candidates remain unassessed non-evidence; queue items remain
  non-actionable cues; Lineage edges remain structural provenance.
- Regression, evaluation, and installed-wheel coverage bind deterministic output,
  hostile pre-open input refusal, current Lens equality, cross-component reconciliation,
  multibyte citation custody, mission/claim isolation, bounded complete-or-refuse
  behavior, non-invocation, and zero research/audit mutation. They make no truth,
  relevance, priority, actionability, or research-quality claim.

## Next dependency-ordered capabilities

Review Dossier v1 is now the accepted completed dependency. The following remaining
order is proposed, not implementation authorization. Each future slice needs an
explicit owner decision. No migration, trust-model, external-principal,
cryptographic-identity, adapter, external/agent-facing API, packet-version, canonical
standards exporter, or broad D-6 gate is open.

1. **PROV-O/RO-Crate decision packet (design only):** prove a lossless mapping for
   exact spans, stance, corrections, inference labels, activities, and audit lineage;
   decide canonicalization, context pinning, and source-byte disclosure before any new
   canonical exporter is accepted.
2. **Explicit Lens-to-evidence bridge (owner-gated):** if approved, require a
   verified receipt, selected candidate, claim, stance, and exact digest confirmation,
   then reuse normal evidence validation/audit. It may never make search itself
   mutating or perform autonomous/bulk adoption.
3. **Authenticated Athena seam (gate D-2):** first reverify the counterpart, then
   separately decide ADRs 0009/0010, the external-principal migration, asymmetric
   verification dependency, revocation, replay, and transport. No external research
   mutation is implied.
4. **Icarus artifact exchange (gate D-3 after D-2):** requires its own canonical
   request/result and import-before-evidence decision, likely including a migration;
   Minerva still performs no experiment or automatic adoption.
5. **Read-only agent protocol (gate D-5 after D-2/D-3):** MCP or any new agent-facing
   API starts with authenticated, bounded read tools backed by existing services and
   exposes no correction, adoption, assistance, publication, or execution verbs.
6. **Packet v3 (separate decision after a real consumer exists):** define the exact
   correction/inference delta, independent verifier, backward compatibility, and
   hostile-input limits without changing frozen v2 bytes by accident.

Scholarly-source adapters follow only after licensing/network/import-custody approval.
A read-only agent protocol follows only after D-2 authentication. Semantic retrieval
follows only when a pinned local index/model receipt can preserve deterministic custody.

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
