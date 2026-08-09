# Minerva product requirements: provenance foundation through Lens Evidence Adoption v1

## Product identity

Minerva is a local-first, provenance-first research laboratory for humans and AI
agents.

> **Minerva — Ask carefully. Cite everything.**

The central doctrine is: **Minerva records evidence and uncertainty; it does not
manufacture certainty.** Minerva manages a disciplined path from questions to
claims, evidence, contradictions, uncertainty, reproducible work, and defensible
conclusions. It never claims to determine truth.

## Milestone 1 outcome

A reviewer working completely offline after installation can create a mission,
question, and falsifiable claim; import an immutable UTF-8 source snapshot; create
exactly located supporting and opposing evidence; inspect the evidence ledger;
record labeled findings and uncertainty; and export deterministic Markdown and JSON
briefs whose material statements resolve to stored snapshots and citations. Every
state change is attributable through an append-only audit trail.

## Milestone 1.2 outcome

An offline operator or future local consumer can verify and inspect the canonical
`research-brief.json` directly from an installed Minerva command without opening
SQLite, contacting a network, or loading provider credentials. Verification applies
the existing strict `minerva.research-brief.v2` contract, including canonical digest,
ownership, citation/evidence, provenance, audit coverage, and audit dependency-order
checks. Inspection exposes bounded inventory and verification metadata, never
research text or private path/identity values.

Digest verification proves packet self-consistency, not authenticity, origin, truth,
approval, or the contents of source snapshots that are not embedded in the packet.
Athena/Icarus exchange and every execution, orchestration, approval, publication, or
remote transport surface remain deferred.

## Milestone 1.3 outcome

An offline producer can create a strict deterministic `minerva.research-request.v1`
artifact selecting one mission/claim and asserting the exact complete active evidence
ledger expected at fulfillment time. An installed Minerva command verifies the file
without SQLite, network access, provider code, or credentials. A separate command
validates the request before database open, resolves it in one query-only read
snapshot, and exclusively writes a claim-scoped canonical v2 brief plus a minimal
digest-bound result manifest without changing research, audit, run, or export state.

The one supported selection policy prevents arbitrary evidence subsets: every active
stance must be present, while canonical output retains withdrawn and supersession
history and exact provenance closure. Request/result digests establish internal
self-consistency and binding only. They do not authenticate an Athena caller, grant
authority, approve work, establish completeness beyond the selected claim, or permit
disclosure. No Athena adapter, transport, shared database/run envelope, Icarus request,
MCP surface, execution, orchestration, publication, messaging, or automatic adoption
is implemented.

## Lens v1 outcome

An offline human or agent can search only the immutable snapshots already imported
into one mission and receive bounded, deterministically ranked candidate context.
Every lead identifies its mission/source/snapshot, exact UTF-8 byte span and bytes,
query and snapshot-set digests, algorithm/Unicode versions, score components, bounds,
and omissions. Identical valid inputs against identical state produce byte-identical
CLI output.

Lens is discovery, not adjudication. It has no identity or mutation path, creates no
audit event, stance, evidence, finding, confidence, or inference, and cannot expand
the explicit mission/corpus scope. A reviewed lead becomes evidence only through the
existing separate evidence workflow and its normal local OS-user attribution,
validation, operator-supplied stance, and audit behavior. Lens adds no schema
migration, provider/model runtime, network
fetch, crawl, OCR, embedding, vector index, API, web, MCP, or packet revision.

## Lens Evidence Adoption v1 outcome

A trusted local CLI operator can select exactly one candidate from an
operator-captured Lens receipt, repeat its receipt digest, rank, snapshot digest,
half-open byte span, and quote digest, and choose one existing claim and explicit
evidence stance. Minerva verifies the hostile receipt before database open, then in
one `BEGIN IMMEDIATE` transaction exactly reproduces it against current state,
refuses an identical existing evidence evaluation, applies the existing exact-byte
evidence validation, and atomically records one `EvidenceCard` plus its normal
creation audit and a bounded `lens.candidate.adopted` provenance event.

The bridge is not part of Lens search and does not make Lens mutating. Rank is only a
candidate selector. The operation does not choose stance, determine truth or source
quality, calculate confidence, change claim status, create/retract findings, persist
agent inference, withdraw older evidence, modify source/snapshot bytes, or perform
bulk/automatic adoption. It adds no migration, index, provider/model/network path,
REST/web/MCP operation, packet field/version, capability-manifest entry, external
principal, or cryptographic identity.

## Claim Lineage Graph v1 outcome

An offline human or local application-service consumer can name one mission and claim
and receive the complete bounded topology of that claim's recorded provenance. The
`minerva.claim-lineage.v1` receipt retains the owning question, complete claim-status
history, all claim-owned evidence, findings, adopted inferences, withdrawals,
retractions, promotions, and every immutable snapshot referenced by their citations.
Every citation retains exact UTF-8 byte coordinates, quote text and base64 bytes,
quote/snapshot digests, source/snapshot metadata, stance, and creator/run/time
provenance.

The versioned `structural-ledger-lineage` algorithm uses scope
`claim_owned_closure_v1` and one query-only SQLite snapshot. Explicit node, edge,
citation-byte, distinct-snapshot-byte, canonical-output-byte, and SQLite-work bounds
are complete-or-refuse: success is never a partial or silently truncated graph.
Claimless findings, sibling claims, unreferenced snapshots, audit/run nodes, and
reverse dependents are intentionally outside this claim-owned closure.

The graph is structural provenance, not adjudication or work coordination. It assigns
no truth, quality, confidence, sufficiency, relevance score, or recommended status;
creates no correction, research state, queue, audit event, export, file, or packet;
and invokes no provider, credential, network, or external-agent protocol. Human
correction and adoption remain separate explicit audited operations.

## Mission Research Queue v1 outcome

An offline human or local application-service consumer can name one mission and
receive a deterministic structural review index covering every mission-owned claim.
`minerva.mission-research-queue.v1` retains a reviewed-claim summary and exact Claim
Review receipt digest for every claim and emits one `structural_review_cue` item for
every pinned Claim Review v1 cue. Claim Lineage remains separately inspectable but is
not invoked because topology does not define queue reason codes.

The versioned `claim-review-cue-aggregation` algorithm uses scope
`mission_claim_review_cues_v1` and one query-only SQLite snapshot. Aggregate claim,
item, distinct verified-evidence-card, distinct evidence-quote-byte, affected-record,
relationship, actual snapshot-byte, canonical-output-byte, and SQLite-work bounds are
complete-or-refuse: success never hides a later claim or returns a partial index. Stable claim/cue
presentation order and claim-set, review-set, item-set, and whole-receipt digests bind
the result without a generated identifier or observation time.

The name “queue” is non-normative. Every current Claim Review claim necessarily has a
cue, so item presence cannot mean unfinished or required work. No item assigns
priority, severity, confidence, age, actionability, recommended traversal, ownership,
assignment, deferment, resolution, or completion. The view creates no persisted queue
or research state, writes no audit/export/file/packet, invokes no model, credential,
network, or Claim Lineage service, and exposes no external-agent protocol.

## Review Dossier v1 outcome

An offline trusted operator can combine one explicit mission and focal claim with an
operator-captured Lens receipt and receive one deterministic
`minerva.review-dossier.v1` result. It embeds the complete mission Queue, the exact
focal Claim Review retained during that Queue build, the focal Claim Lineage graph,
the verified Lens search, and its exact current-database replay report.

The captured Lens receipt is verified before database open and must name the same
mission. All five components are then resolved or reproduced inside one query-only
SQLite snapshot under one cumulative VM budget. Cross-checks require Queue/Review
digest and cue agreement, Review/Lineage claim/status/evidence/withdrawal agreement,
agreement for Review-reported claim-owned finding/inference citations, retractions,
promotions, and provenance, matching identities for any snapshots shared by Lens and
Lineage, and exact Lens receipt equality to that current read. The affected-record
check is intentionally a Review-reported subset; Lineage can retain additional
unaffected owned records. Ordered component and whole-dossier digests bind the result
without a generated identifier or observation time.

Dossier success is complete-or-refuse. Its `truncated: false` does not erase the
embedded Lens search's own explicit bounded truncation. Composition does not assess a
Lens candidate against the claim, turn it into evidence, make a Queue cue actionable,
or interpret a Lineage edge as truth. It creates no durable dossier, research/task
state, identity, audit event, export, file, packet, provider call, network activity, or
external-agent surface.

## Milestone 2B outcome

A local CLI operator can optionally ask OpenAI or Anthropic to draft finding
candidates from one claim and its bounded active evidence. Before any external call,
Minerva renders the exact disclosure context and a digest-bound request manifest. The
operator must review that preview and explicitly authorize the same digest. The
provider response is untrusted, validated candidate output only: it is labeled as
agent inference, includes uncertainty and existing evidence IDs, and is neither
persisted nor adopted as research state.

This is a reviewed exception to the offline Milestone 1 boundary, not a general model
or integration platform. It adds no model invocation to the REST API or web interface,
no URL fetching, tools, code execution, provider fallback, automatic retry,
publication, messaging, or autonomous research.

## Research vocabulary

- **Research mission:** a bounded research objective that owns its questions,
  claims, sources, runs, findings, and briefs.
- **Research question:** an open, answerable prompt inside one mission. A question
  frames inquiry; it is not itself a conclusion.
- **Claim:** a declarative, falsifiable statement evaluated by evidence. Minerva
  requires a separate falsification criterion and stores a workflow status, never a
  truth value. Milestone 1 validates that the criterion is present and bounded; it
  does not pretend software can decide whether arbitrary natural language is
  scientifically falsifiable.
- **Source:** the provenance record describing where submitted material was said to
  come from. Milestone 1 sources are local registrations only; URL metadata is inert.
- **Immutable source snapshot:** the exact validated UTF-8 bytes captured at import,
  identified by SHA-256 and insulated from later changes to the original file.
- **Evidence card:** an attributable evaluation of one claim using one exact byte
  span from one source snapshot, with a stance and verbatim quote.
- **Citation:** the stable identifier and location tuple that resolves an evidence
  card to a snapshot digest, byte offsets, and exact quoted bytes.
- **Evidence stance:** `supports`, `opposes`, `context`, or `inconclusive`. Stance is
  an evaluator's classification, not a confidence score or truth judgment.
- **Finding:** a labeled research statement assembled by a human or agent from cited
  evidence. Material findings require citations.
- **Assumption:** an explicitly labeled premise not established as observed evidence.
- **Uncertainty:** a stated limitation, ambiguity, missing observation, or unresolved
  conflict that constrains a finding or claim.
- **Research run:** an attributable unit of work performed by an identity context.
- **Review:** an assessment of research artifacts and their provenance; it may accept,
  challenge, or request changes but does not rewrite history.
- **Research brief:** a deterministic, portable Markdown/JSON synthesis of a mission,
  including claims, both favorable and adverse evidence, findings, assumptions,
  uncertainty, citations, and digests.
- **Research request:** an inert canonical file that names one existing mission/claim,
  binds an exact active-ledger precondition, and requests canonical v2 output. It is not
  authenticated work coordination or authorization.
- **Research result manifest:** a minimal canonical file binding one verified request
  digest to the schema and exact SHA-256 of its fulfilled brief bytes.
- **Candidate context:** a deterministic Lens lead locating potentially relevant
  bytes in an immutable snapshot. Its stance is unassessed and its evidence status is
  candidate-only; it is neither a citation nor an evidence card.
- **Lens evidence adoption:** one explicit trusted-local-operator mutation that binds a strictly
  verified and currently reproduced Lens candidate to one claim and operator-supplied
  stance through the normal evidence service. It is not an inference from search rank
  and does not change Lens's candidate-only semantics.
- **Claim lineage graph:** a deterministic, typed, complete-or-refuse view of the
  provenance records and append-only relationships owned by one claim. It preserves
  corrected history and exact citation custody but is neither a truth graph nor a
  correction, status, adoption, or queue operation.
- **Mission research queue:** a deterministic, mission-wide structural index of the
  pinned Claim Review cue taxonomy. Despite its name, it is neither persisted task
  state nor a claim that a cue is actionable, unresolved, prioritized, assigned, or
  complete.
- **Review dossier:** a deterministic, complete-or-refuse local composition of one
  mission Queue, its exact focal Claim Review, the focal Claim Lineage graph, and one
  operator-captured Lens receipt reproduced in their shared current database read. It
  is neither a durable artifact nor a semantic association between the claim and Lens
  candidates.

## Statement classes

Minerva preserves the difference between:

| Class | Meaning | Citation rule |
| --- | --- | --- |
| Observed fact | Directly recorded observation in a source snapshot | Required |
| Source assertion | Something a source says, without adopting it as true | Required |
| Agent inference | A reasoned interpretation produced by an agent | Required and labeled |
| Assumption | A premise used without evidentiary establishment | May be uncited; always labeled |
| Calculation | A deterministic transform of stated inputs | Inputs must be cited |
| Recommendation | A proposed action derived from research | Required and labeled |
| Unresolved question | A known gap or open inquiry | May be uncited; always labeled |

A model-generated statement never becomes evidence merely because a model produced
it. It can only be stored as a labeled inference, assumption, recommendation, or
unresolved question under the same citation rules as human-authored material.

## Domain invariants

1. Snapshots are immutable, content-digested, size-bounded UTF-8 records. Importing
   the same bytes twice creates distinct provenance registrations with the same
   digest; there is no silent cross-mission deduplication.
2. Citation locations use zero-based, half-open UTF-8 **byte offsets** `[start, end)`.
   The bytes must decode independently as UTF-8 and equal the submitted quote.
3. Evidence belongs to the same mission as its claim and snapshot. Cards are never
   edited; withdrawal is a separate historical record, and supersession creates a
   new card.
4. Claims have workflow states (`open`, `provisionally_supported`, `contested`,
   `unsupported`, `inconclusive`) but never a `true` state. Counts do not calculate
   confidence.
5. A material finding cannot be created without at least one same-mission evidence
   citation. Assumptions and unresolved questions may remain uncited only because
   their labels explicitly say they are not evidence-backed. A finding is never
   edited or deleted; retraction is a separate append-only record that removes it
   from synthesis while preserving the finding, its citations, and its history.
   Every surface that reads a finding reports whether it is retracted, with the
   recorded reason, timestamp, and actor: a retracted statement is never presented
   as an asserted one merely because it left the brief.
6. Domain mutations and their audit records share one SQLite transaction. Rejected
   mutations and failures that return control to Minerva leave neither domain state
   nor misleading success events. Ephemeral Milestone 2B assistance is not a domain
   mutation; its metadata-only audit records bracket an external call and therefore
   cannot share one atomic transaction with that call. This does not claim crash
   atomicity across SQLite and exported files or external providers.
7. Export ordering and canonical serialization are explicit. The export digest is
   SHA-256 over the canonical brief payload before the digest envelope is added.
8. An export cannot include a material finding with a missing, withdrawn, detectably
   inconsistent, or unresolvable citation. This governs material findings only:
   an assumption or unresolved question may keep an optional citation to withdrawn
   evidence, which the packet marks as withdrawn. A retracted finding is not
   exported at all. Opposing and inconclusive evidence remain
   visible. Minerva has no external signature or anchor for detecting a determined
   same-OS-user coordinated rewrite.
9. Assistance preview performs no credential read or network operation. It discloses
   the exact canonical JSON that would be sent: the claim ID, statement, and
   falsification criterion plus bounded active evidence citation IDs, quotes, and
   stances. Withdrawn evidence is excluded; opposing and inconclusive evidence remains
   visible. Byte offsets, snapshot digests, and supersession references remain local
   but are bound into the request digest as provenance.
10. Assistance authorization requires an explicit confirmation flag and the exact
    SHA-256 from a fresh preview. The digest binds the provider, model, fixed
    destination, prompt, exact context, candidate limit, and output-token limit.
11. Provider credentials come only from the current OS-user environment after
    authorization. Minerva does not persist credentials, provider prompts/responses,
    or returned candidates. Locally accepted candidates are always labeled
    `agent_inference` and never become evidence, findings, truth, confidence, or claim
    status automatically.
12. Each authorized provider call is attempted once, with no redirects, environment
    proxy use, automatic retries, provider fallback, or tools. A timeout or connection
    loss is an unknown provider outcome. Requested and terminal audit events contain
    bounded metadata and digests only and are separate transactions around the call.
13. Research-request DTOs are strict, SQLite-independent, canonical, and limited to
    mission/claim identifiers, the one complete-ledger policy, a sorted exact active
    citation set, and output schema. Paths, URLs, credentials, free text, actors,
    authority, approvals, timestamps, callbacks, transports, and run controls are not
    request fields.
14. Request verification completes before any fulfillment database construction/open.
    Mission, claim, ledger, and synthesis use the same query-only read snapshot. The
    requested set must equal the complete active claim ledger; unknown, out-of-scope,
    withdrawn, omitted, or newly added evidence fails closed without stance filtering.
15. Fulfillment is read-only research behavior. It creates no identity/run, audit
    event, `brief_exports` row, domain mutation, provider request, or network activity.
    Fixed output files are canonical, owner-only, exclusive, and cleaned as a group
    after caught write failures; existing files are never overwritten.
16. A claim-scoped v2 packet preserves exact target-claim evidence/provenance closure
    but carries no selection marker. Its request/result binding supplies that external
    meaning; standalone packet verification does not prove database completeness.
    Scope is by claim: only findings, unresolved questions, assumptions, and
    uncertainties recorded against the target claim appear. A mission-level statement
    (one with no claim) is omitted **even when it cites the target claim's own
    evidence**, so the packet can carry an evidence card while carrying nothing that
    rests on it, and an empty statement array means "none for this claim" rather than
    "none in this mission". A consumer that needs mission-level statements requests a
    mission-wide brief.

17. Request fulfillment caps cumulative SQLite virtual-machine work across its query-only
    snapshot. Exhaustion is a stable `brief_work_limit` refusal before output; this is an
    availability guard, not a wall-clock or successful-fulfillment guarantee.
    Claim-scoped preflight also refuses before full database text or snapshot content
    is returned to Python when the exact-multiplicity NUL-safe storage-byte lower bound
    for emitted strings exceeds the export byte cap. SQLite may inspect those values;
    canonical serialization remains the final byte check.
18. Lens validates all bounds and filters, resolves one mission in one query-only read
    snapshot, searches a deterministic bounded prefix, and re-verifies every snapshot
    before scoring original bytes. Its versioned integer scoring has a total tie-break;
    the receipt names every exclusion and omission class. Lens returns DTOs only and
    leaves every database table and the database main-file bytes unchanged.
19. Claim Lineage Graph resolves one explicit mission/claim in one query-only read
    snapshot and emits the complete `claim_owned_closure_v1` or refuses. All
    claim-owned status, evidence, finding, inference, correction, promotion, and cited
    snapshot records are represented as typed, stably ordered nodes and edges; every
    citation and distinct snapshot is re-verified. Claimless findings, sibling claims,
    unreferenced snapshots, audit/run nodes, and reverse dependents are excluded by
    contract. The result creates no state and makes no truth, confidence, scoring,
    status-recommendation, correction, queue, provider, network, or protocol claim.
20. Mission Research Queue resolves one explicit mission in one query-only read
    snapshot and derives a complete pinned Claim Review v1 receipt for every
    mission-owned claim. Every cue is represented in canonical claim/cue order and
    bound to its source review digest; claims remain separately summarized. The
    receipt is complete-or-refuse and creates no persisted task/research state. Cue
    presence and array position make no actionability, unresolved-work, severity,
    priority, confidence, assignment, completion, truth, correction, provider,
    network, or protocol claim.
21. Review Dossier verifies its captured Lens input before database open, then
    reproduces it and composes Queue, focal Review, and focal Lineage in one current
    query-only SQLite snapshot with cumulative work and final-output bounds. Every
    declared structural cross-check must pass or no dossier is returned. Success does
    not create a persistent artifact or assert candidate relevance, evidence, truth,
    actionability, confidence, priority, correction, adoption, provider, network, or
    protocol meaning.
22. Lens Evidence Adoption validates one captured receipt and every explicit
    confirmation before database open. Exact current replay, exact-evaluation
    duplicate refusal, normal evidence creation, `evidence.card.created`, and
    `lens.candidate.adopted` share one `BEGIN IMMEDIATE` transaction. The duplicate
    check includes withdrawn cards. A successful operation creates exactly one card
    and no other semantic state; search/replay remain query-only and no rank, digest,
    or truncation state becomes truth, confidence, stance, quality, or completeness.

## User surfaces

- The `minerva` CLI proves the entire workflow without a browser and provides init,
  mutation, inspection, audit, backup/restore, doctor, export, and serve operations.
- `minerva packet verify` and `minerva packet inspect` are file-only offline commands;
  they require no database and return bounded JSON success or error records.
- `minerva request verify` is a file-only offline command. `minerva request fulfill`
  adds one explicitly supplied local database and output directory while remaining
  read-only with respect to Minerva state.
- `minerva lens search` returns compact deterministic JSON candidate receipts over one
  immutable mission corpus. No equivalent REST, web, provider, or MCP operation exists.
- `minerva evidence add-from-lens` and the public local
  `minerva.evidence.LensEvidenceAdoptionService.adopt_candidate` application service
  adopt one explicitly confirmed candidate through the existing evidence boundary.
  No equivalent REST, web, provider, packet, capability, or MCP operation exists.
- `minerva claim lineage` and the public local
  `minerva.lineage.ClaimLineageService.build_graph` application service return one
  deterministic, complete-or-refuse claim provenance graph. No equivalent REST, web,
  provider, packet, capability, or MCP operation exists.
- `minerva mission queue` and the public local
  `minerva.research_queue.MissionResearchQueueService.build_queue` application
  service return one deterministic, complete-or-refuse mission structural review
  index. No equivalent REST, web, provider, packet, capability, or MCP operation
  exists.
- `minerva dossier build` and the public local
  `minerva.dossier.ReviewDossierService.build_dossier` application service return one
  deterministic atomic-read composition from an explicit mission, claim, and captured
  Lens receipt. No file writer, REST, web, provider, packet, capability, or MCP
  operation exists.
- `minerva-demo` creates a disposable synthetic mission and exports its brief without
  contacting a network service. It refuses an existing database.
- The web interface is a restrained, server-rendered review surface.
- `/api/v1` exposes strict contracts for later protocol adapters. Unknown fields are
  rejected, input sizes and pagination are bounded, and errors have stable codes.
- `/healthz`, `/readyz`, and `/api/v1/capabilities` support local operations.
- `minerva assist finding-candidates` is the only Milestone 2B model surface. It
  previews by default and can invoke one of the two reviewed adapters only after exact
  digest confirmation. There is no equivalent REST or web operation.

## Acceptance priorities

When trade-offs are necessary: source immutability, citation correctness, opposing
evidence, transaction/audit integrity, deterministic export, tests, documentation,
then UI polish.

For Milestone 2B, authorization integrity, bounded exact disclosure, credential
secrecy, candidate-only semantics, and honest unknown-outcome audit records take
priority over convenience or provider availability.
