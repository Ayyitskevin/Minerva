# Architecture

## Shape

Minerva is one installable Linux/POSIX application tested with Python 3.12–3.14,
with several adapters around a single command/service layer. Other operating systems
are not yet verified or supported:

```text
CLI -----------\
REST API -------+--> commands/services --> SQLite transaction + audit
server HTML ---/             |                     |
                              +--> immutable blobs  +--> deterministic exporter

assist CLI --> preview + exact digest confirmation --> reviewed provider adapter
                                                        |
                                                        +--> OpenAI or Anthropic

packet CLI --> no-follow bounded file reader --> strict packet parser/verifier
                                                     |
                                                     +--> bounded JSON report

request verify --> no-follow 64 KiB reader --> strict request parser/verifier

request fulfill --> verified inert request --> one query-only SQLite snapshot
                                                  |
                                                  +--> claim-scoped canonical v2
                                                       + digest-bound result file

lens CLI --> bounded lexical query --> one query-only SQLite snapshot
                                           |
                                           +--> verified immutable bytes
                                                 + deterministic candidate receipt

claim review CLI --> complete structural query --> one query-only SQLite snapshot
                                                     |
                                                     +--> verified citation/correction
                                                          impact receipt

claim lineage CLI --> complete claim-owned closure --> one query-only SQLite snapshot
                                                        |
                                                        +--> verified typed nodes/edges
                                                             + deterministic JSON receipt

mission queue CLI --> complete Claim Review cue index --> one query-only SQLite snapshot
                                                               |
                                                               +--> reviewed claims/cues
                                                                    + deterministic receipt
```

The SQLite database is authoritative for structured research state and source
snapshot bytes. REST, HTML, and CLI adapters perform parsing and presentation only;
they may not reimplement domain validation or write SQL directly.

## Package responsibilities

- `core`: connection policy, versioned migrations, identity/run context, audit,
  identifiers, hashing, errors, and transactional primitives.
- `research`: missions, questions, claims, findings, and their command/query service.
- `sources`: safe local-file reading, validation, secret-pattern defense, and
  immutable snapshot registration.
- `evidence`: byte-span citations, stance, ledgers, withdrawal, and supersession.
- `lens`: bounded, model-free candidate-context retrieval and deterministic
  query/corpus/score receipts over verified immutable snapshots.
- `review`: complete-or-refuse structural evidence-gap, active-stance-conflict,
  and correction-impact receipts over existing claim ledgers.
- `lineage`: complete-or-refuse typed provenance topology over one existing
  claim-owned ledger closure, with exact citation and snapshot verification.
- `research_queue`: complete-or-refuse mission-wide aggregation of the pinned Claim
  Review cue taxonomy into a non-normative structural review index.
- `synthesis`: canonical research-packet assembly, citation verification,
  claim-scoped request fulfillment, Markdown/JSON rendering, digesting, and contained
  file export.
- `api`: strict Pydantic request/response adapters and structured error mapping.
- `web`: loopback-only, read-only server-rendered review pages, and local HTTP
  controls. There is no CSRF primitive; any future unsafe browser form must add one.
- `assist`: provider-neutral preview, authorization, bounded context, response
  validation, candidate labeling, and metadata-only invocation audit coordination.
- `cli`: local operator commands, optional external-assistance consent, demo,
  backup/restore, doctor, and server startup.
- `integrations`: strict, SQLite-independent research-packet and research-request DTOs,
  parsers, canonical serializers, verifiers, shared safe standalone file reader, and
  bounded metadata reports plus two live, narrowly reviewed provider adapters. Only
  `integrations/ai/openai.py` and `integrations/ai/anthropic.py` may import their SDK
  and network client; there are no live sibling-system adapters.

Imports point inward: adapters may import domain services; domain packages do not
import FastAPI, Jinja, or CLI modules. Cross-domain writes are coordinated by an
application service using one connection and transaction.

## External assistance boundary

Milestone 2B assistance starts with a read-only snapshot of one claim and its evidence
ledger. The service excludes withdrawn evidence, preserves opposing and inconclusive
evidence, enforces card/byte/output bounds, rejects secret-pattern matches, and
serializes canonical JSON containing the exact claim, falsification criterion,
and active evidence citation IDs, quotes, and stances. Byte offsets, snapshot digests,
and supersession references remain local request-manifest provenance. Preview returns
the exact provider payload, fixed destination, and a request SHA-256 without reading a
credential or calling a network.

Invocation requires an explicit CLI confirmation plus that exact digest. The digest
binds the provider, model, destination, prompt hash, context hash, active-evidence
provenance, and output limits. Only then does the CLI construct the selected optional
adapter and read `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` from the OS-user
environment. The adapters use fixed official API origins, ignore proxy environment
variables, fail closed on SDK header/account-routing environment controls, refuse
redirects, make one attempt with no SDK retry, request structured output, and expose
no tools or fallback. OpenAI requests set `store=false`; provider retention outside
available request controls remains governed by the operator's account and provider
terms.

The service re-reads the claim/evidence context after the provider returns and discards
the response if its authorized digest changed. It validates response structure,
limits, evidence-ID membership, metadata, and secret patterns. Successful text is
returned only as ephemeral `agent_inference` candidates with uncertainty. Credentials,
request content, response content, and candidates are not persisted or adopted.

## State and transactions

Each command receives an `IdentityContext` containing an application-created run ID,
an actor derived honestly from the local OS-user trust boundary, and an actor kind.
Remote actor headers are rejected. On first mutation in a run, the service inserts the
run and its audit record in the same transaction as the requested state change.

SQLite connections enable foreign keys, WAL journal mode, a busy timeout, and safe
row access. Connections open a `mode=rw` URI, so opening never creates a database and
a missing one fails closed as `database_missing`; a failed open removes nothing.
Fresh initialization stages into an unpredictable owner-only file, migrates and runs
its audit callback inside that staged transaction, and publishes with an exclusive
hard link, so concurrent initializers cannot destroy a published database
(see [ADR 0004](adr/0004-staged-restore-audit-publication.md)). Migrations are ordered
package resources with recorded SHA-256 checksums. A newer or checksum-mismatched
database fails closed.

Audit rows are insert-only. Database triggers reject updates and deletes. Snapshot
rows, snapshot content, evidence cards, and finding-citation links are likewise
append-only. Evidence withdrawal is modeled as a new row rather than an edit.

An authorized assistance call is deliberately not modeled as a domain mutation. A
metadata-only `requested` audit event commits before egress and a separate terminal
event commits after success, refusal, incomplete output, validation failure, stale
context, or a caught provider failure. No database transaction can include the remote
operation. Process termination can leave only the requested event, and a timeout or
connection loss is recorded as an unknown provider outcome because the provider may
have processed the request. Minerva does not retry it automatically.

## Lens read boundary

`LensService` is a query application service, not a source importer or evidence
service. Its SQL remains inside the service layer; the CLI only parses bounds and
presents the returned DTO. Search validates query, limits, and canonical allowlists
before opening one `Database.read()` transaction, then enables connection-local
`PRAGMA query_only=ON`. Mission lookup, allowlist validation, deterministic corpus
selection, snapshot loading, integrity verification, and scoring all occur against
that same consistent read snapshot.

Snapshot selection is a bounded prefix ordered by `(imported_at, snapshot_id)`.
Source and snapshot filters intersect and every requested identifier must resolve in
the mission. The existing source-integrity verifier checks stored bytes, length,
SHA-256, UTF-8 decoding, and import-audit provenance before Lens sees text. Ranking is
pure Python over original bytes using the versioned lexical rule in
[`LENS_V1.md`](LENS_V1.md); SQLite collation, `LIKE`, FTS, provider code, and mutable
indexes are not part of the result.

The service returns immutable candidate DTOs and a receipt only. It has no identity,
clock, ID factory, audit sink, transaction writer, provider, credential, export, or
adoption dependency. Candidate text carries exact source byte coordinates but remains
semantically distinct from `EvidenceCard`, `Finding`, and `AgentInference`. The
existing evidence service is the only path from a reviewed lead into evidence state.

## Claim Review read boundary

`ClaimReviewService` is a query application service over the existing claim,
evidence, finding, and adopted-inference ledgers. The CLI supplies an explicit mission,
claim, and deterministic bounds; all SQL, scope validation, derivation, integrity
checking, and receipt construction remain in the service. One `Database.read()`
transaction with `PRAGMA query_only=ON` owns the complete operation.

Before using the shared claim reader, the review service verifies that the claim's
question resolves in the mission and that its complete status-event chain starts at
version one, remains contiguous, and contains no foreign-mission event. The selected
status DTO must then match the verified latest event exactly.

The service first bounds the target evidence ledger and every correction-relevant
finding, inference, and citation relationship. It also caps distinct snapshot bytes
and cumulative local SQLite virtual-machine work. Stored BLOB length is checked
against declared snapshot length and the configured byte ceiling before snapshot
content is returned to Python. A limit that would omit required admitted state raises
`claim_review_work_limit`; no partial prefix is returned. Every referenced evidence
card then passes the shared exact-citation and immutable-snapshot verifier with one
snapshot cache. Stable entity ordering and compact sorted-key JSON produce a
whole-result SHA-256 receipt with no generated ID or observation time.

The derived status check reuses the existing presence-only rule: provisional support
requires active support, contested requires active support and opposition, and
unsupported requires active opposition. Coexisting active support and opposition is
reported separately as a structural stance conflict. Neither condition is a truth,
quality, confidence, sufficiency, or replacement-status judgment. Supersession remains
lineage rather than deactivation; only an explicit withdrawal changes the active
stance set.

Affected records retain withdrawal, retraction, and inference-promotion provenance.
Selected promotion targets must resolve in the same mission and claim with the copied
statement, uncertainty, statement kind, and citation set before that provenance is
returned. Promotion-target citation rows count against the relationship ceiling even
when that finding is not otherwise an affected output record. Supersession self-links
and cycles are rejected.
The receipt describes current synthesis/promotion consequences but performs no
correction and creates no queue. The service has no identity, writer, audit, export,
provider, credential, network, packet, capability-manifest, HTTP/external/agent API,
or web dependency. Its local Python application-service interface is public. See
[`CLAIM_REVIEW_V1.md`](CLAIM_REVIEW_V1.md) for the versioned read contract.

Claim Review is not a replacement for deep doctor. Its complete-or-refuse promise is
over the records admitted to the named mission by their stored owner rows. If a
same-OS-user attacker has already disabled foreign keys/triggers and moved an owner
record into another mission while forging a target-mission relationship row, the
owner-first query excludes that foreign owner rather than scanning every mission.
Deep doctor remains responsible for detecting such whole-database referential
corruption; the view never returns the foreign record's text.

## Claim Lineage Graph read boundary

`ClaimLineageService.build_graph(...)` is a public local query application service
over the existing research, evidence, correction, and adopted-inference ledgers. The
CLI supplies an explicit mission, claim, and deterministic bounds and emits the
returned receipt inside a JSON-only `claim_lineage` envelope. All SQL, scope checks,
closure discovery, integrity resolution, ordering, and digest construction remain in
the service. One
`Database.read()` transaction with connection-local `PRAGMA query_only=ON` owns the
complete operation.

The versioned algorithm is `structural-ledger-lineage` with scope
`claim_owned_closure_v1`. Starting at the target claim, it admits the owning question,
complete status chain, every claim-owned evidence card, finding, and adopted inference,
their withdrawals/retractions/promotions and citation relationships, plus exactly the
referenced immutable snapshots. Snapshot nodes carry source identity/metadata and both
source and snapshot provenance. Evidence nodes carry exact quote text/base64 bytes,
UTF-8 coordinates, quote/snapshot digests, stance, supersession, and provenance. The
typed edges preserve status order, citation, supersession, correction, and promotion
topology without interpreting any edge as truth, causality, confidence, or priority.

The excluded record classes are explicit in the receipt:
`sibling_claims`, `claimless_findings`, `unreferenced_snapshots`, `audit_events`,
`research_runs`, `brief_exports`, `lens_candidates`,
`ephemeral_assistance_candidates`, and `reverse_dependents`. Creator/run/time values
remain attached as provenance, but audit and run records do not become graph nodes.
Claimless findings stay excluded even when they cite target-claim evidence, and the
service never follows reverse dependents or expands to a sibling claim.

The service preflights and measures all required nodes, edges, citation bytes,
distinct snapshot bytes, canonical output bytes, and cumulative SQLite virtual-machine
work. Crossing any configured ceiling raises `claim_lineage_work_limit`; invalid bounds
or scope raise `claim_lineage_bounds_invalid` or `claim_lineage_scope_invalid`, and
inconsistent admitted ledger state raises `claim_lineage_inconsistent` or the existing
exact citation/snapshot integrity error. Success is always complete and untruncated.

Determinism does not depend on SQL row order. Node kinds use their fixed enum order;
status events then order by `(version, id)`, snapshots by `(recorded_at, id)`, and other
same-kind records by `(recorded_at, id)`. Edges order by fixed relation-enum order,
then source and target node ID. Compact sorted-key serialization produces node-set,
edge-set, snapshot-set, and whole-receipt SHA-256 values without a generated ID or
observation time.

The lineage service has no identity, clock, ID factory, writer, audit sink, export,
queue, provider, credential, network, packet, capability-manifest, HTTP/web, MCP, or
other external-agent dependency. It makes no truth, quality, confidence, sufficiency,
score, or status recommendation and performs no correction or adoption. Its scoped
owner-first closure is not a replacement for deep doctor's whole-database referential
and audit-integrity scan. See [`CLAIM_LINEAGE_V1.md`](CLAIM_LINEAGE_V1.md) for the
receipt and semantic contract.

## Mission Research Queue read boundary

`MissionResearchQueueService.build_queue(...)` is a public local query application
service over every owner-admitted claim in one explicitly named mission. The CLI
supplies the mission and aggregate deterministic bounds and emits the returned receipt
inside a JSON-only `mission_research_queue` envelope. All claim discovery, review
derivation, scope checks, integrity resolution, bounds, ordering, and digest
construction remain in the service.

One `Database.read()` transaction with connection-local `PRAGMA query_only=ON` owns
the whole mission build. Claims are admitted in `(created_at, id)` order. A
connection-bound internal Claim Review derivation reuses the existing review SQL,
scope, citation/snapshot verification, cue taxonomy, and receipt construction under
the queue's one cumulative SQLite progress handler; the queue neither loops the
public multi-connection wrapper nor creates a parallel review implementation.

Every complete pinned Claim Review v1 receipt yields a reviewed-claim summary and
review digest. Every cue yields one `structural_review_cue` item carrying category,
code, explanation, related record IDs, claim/question identity, and the source review
digest. Claim summaries remain separately represented so claim-set completeness is
bound directly rather than inferred from the item array. Under the current taxonomy
every claim emits at least one cue, because missing support/opposition is a gap while
coexistence is a structural stance conflict. The assembler nevertheless retains a
self-consistent zero-cue child review with `item_count: 0`; that defensive shape does
not assert that honest Claim Review v1 state can be cue-free.

Claim Lineage is not part of this build path. Its typed graph remains a separate
operator inspection surface, but it defines topology and recorded human rationale,
not queue reason codes or actionability. Mission-owned claimless findings may occur
only as related IDs already admitted by Claim Review through a target claim's
correction impact; they never become queue roots.

Claims order by `(created_at, id)` and cues use the fixed Claim Review catalog order.
That canonical sequence is presentation only; it is not priority, severity, age,
confidence, actionability, or recommended traversal. Compact sorted-key serialization
produces claim-set, review-set, item-set, and whole-receipt SHA-256 values without a
generated identifier or observation time.

Aggregate claim, item, distinct verified-evidence-card, distinct evidence-quote-byte,
affected-record, relationship, actual snapshot-byte, canonical-output-byte, and
cumulative SQLite-VM ceilings protect the whole operation. One internal
verified-citation cache binds the evidence count and quote-byte sum to the union of
target ledgers and admitted correction-citation closure; a metadata-only length
preflight must admit every new evidence ID and its quote bytes against the remaining
aggregate budgets before quote text reaches Python. Crossing any ceiling raises
`mission_research_queue_work_limit` and returns no prefix. Invalid bounds raise
`mission_research_queue_bounds_invalid`; inconsistent admitted review/cue state raises
`mission_research_queue_inconsistent` or the existing exact citation/snapshot integrity
error as applicable.

The queue service has no identity, clock, ID factory, writer, audit sink, export,
provider, credential, network, packet, capability-manifest, Claim Lineage, HTTP/web,
MCP, or other external-agent dependency. The result is a non-normative review index,
not a persisted task queue: it creates no assignment, deferment, resolution,
completion, research state, or action recommendation. See
[`MISSION_RESEARCH_QUEUE_V1.md`](MISSION_RESEARCH_QUEUE_V1.md) for the receipt and
semantic contract.

## Exact citations

Snapshots store original UTF-8 bytes as a BLOB. A citation is:

```text
(snapshot_id, snapshot_sha256, start_byte, end_byte, exact_quote)
```

Offsets are zero-based and half-open. Creation verifies bounds, UTF-8 code-point
boundaries, exact byte equality, mission ownership, and snapshot digest. Reads and
exports re-verify the tuple so partial or inconsistent database tampering fails closed
rather than producing a plausible-looking brief. This is not an external signature or
integrity anchor; a determined same-OS-user coordinated rewrite remains outside the
trust boundary.

Stable human-readable citation IDs are the evidence card IDs. Brief JSON contains the
full tuple; Markdown footnotes display the card ID, source label, digest, and offsets.

## Deterministic synthesis and packet verification

Queries use explicit stable ordering. The canonical brief payload contains no export
wall-clock time. JSON uses UTF-8, sorted keys, compact separators, and a trailing
newline. SHA-256 is computed over that canonical payload; both output formats include
the same digest envelope. Markdown is rendered from the payload without interpreting
stored text as HTML. Fixed database state plus fixed export schema/config therefore
produces byte-identical output.

The fixed `research-brief.json` filename is the single canonical agent-facing artifact
under `minerva.research-brief.v2`; there is no redundant packet file. Its semantic
payload preserves the mission, questions, proposition-only claims, all evidence
stances, exact byte-span locations and quotes, source digests, findings, assumptions,
unresolved questions, uncertainties, creator/run provenance, and relevant append-only
audit references. Its machine-readable ownership block says Minerva researches and
does not execute, approve, orchestrate, or publish.

The protocol model does not import SQLite. Strict parsing rejects unknown or duplicate
fields and non-standard numeric values. Semantic verification recomputes the canonical
SHA-256 digest and resolves cross-references, provenance, audit references, citations,
and evidence requirements before another component may accept the packet. A claim that
honestly remains open or inconclusive is preserved; a status presented as
evidence-valid must satisfy its stance requirements with active, resolvable citations.
Citation supersession cycles are checked in linear time, and protocol parsing rejects
input above 20 MiB before JSON decoding. Untrusted JSON receives a bounded object/depth
preflight; sequence DTOs fail on their first invalid element, and error classification
inspects only a fixed maximum number of validation details.

`minerva packet verify` and `minerva packet inspect` apply that same verifier to a
direct operator-selected file. The adapter rejects parent segments, lexically anchors
the path, and walks every component through directory descriptors with symbolic-link
following disabled. It pins the final target with Linux `O_PATH`, verifies that target
is regular before opening a readable handle through the pinned descriptor, checks the
size from metadata before reading, performs a limit-plus-one bounded read, and confirms
stable path/file identity and identical bytes across two reads. It then parses only the
captured bytes. Expected failures map to fixed, non-reflective JSON errors.

These commands construct no database or identity context, use no provider adapter or
credential loader, and perform no network operation. Verification output contains
only schema, digest, integrity/authenticity status, and ownership. Inspection adds
bounded counts and provenance/audit coverage; it omits stored research text, labels,
URLs, identifiers, and paths. The digest proves internal canonical consistency, not
authenticity or source truth; source bytes are not embedded for independent rehashing.

## Offline research request validation and fulfillment

`minerva.research-request.v1` is a second protocol contract, not a second research
packet. Its strict canonical envelope binds a mission ID, claim ID, the sole
`complete_claim_ledger` selection policy, a sorted exact active-citation precondition,
and the requested `minerva.research-brief.v2` schema. It has no free text, path, URL,
credential, actor, authority, approval, timestamp, callback, transport, execution, or
run-coordination field. Request bytes are limited to 64 KiB and use the same hostile
JSON and stable descriptor-walk defenses as packet input.

`request verify` is file-only. It validates size and stable file identity before
decoding, rejects duplicate/non-standard/excessively shaped JSON, applies strict DTO
and identifier validation, recomputes the request-payload digest, and emits only
bounded fixed-key metadata. The digest proves canonical self-consistency; authenticity
and authorization remain explicitly unestablished.

`request fulfill` invokes that complete file validation before it constructs a
`Database` or opens SQLite. The fulfillment application service then owns one
`Database.read()` transaction, enables connection-local `PRAGMA query_only=ON`, and
passes the same connection through mission lookup, claim lookup, evidence-ledger
verification, and synthesis. The claim must belong to the declared mission. Every
supplied citation must belong to that claim and be active, and the supplied set must
equal the snapshot's complete active set. Unknown/out-of-scope, withdrawn, omitted,
or newly added evidence fails closed; no evidence stance is filtered.

Fulfillment installs a connection-local SQLite progress handler around that complete
snapshot. All SQLite work used by mission/claim lookup, complete-ledger validation,
claim-scoped preflight, assembly, and provenance closure shares one cumulative SQLite
virtual-machine instruction budget. Only an interrupt raised by that handler maps to
`brief_work_limit`; the handler is always cleared, and artifact publication begins after
the guarded snapshot succeeds. This guard is specific to `request fulfill`; ordinary
full-mission brief preview/export retains its existing source/record/reference
preflights without the cumulative handler.

Before full database text or snapshot content is returned to Python, claim-scoped
preflight asks SQLite for identifiers, content byte lengths, and aggregate NUL-safe
storage-byte lengths at each emitted string's canonical JSON multiplicity. The fields
cover target scope, citations and ledger, distinct source metadata, findings and
references, audits, and runs. UTF-8 storage bytes are exact; UTF-16 storage is at most
twice the UTF-8 output size, so its threshold is doubled. Exceeding the threshold is a
sound early refusal. These aggregate queries still inspect values inside SQLite, so the
control bounds Python materialization rather than SQLite's internal memory use.

The selected synthesis path constructs a fresh claim-scoped v2 payload before packet
serialization. It includes the mission, target question and claim, complete active and
withdrawn ledger, supersession and status provenance, referenced sources, claim-linked
findings/assumptions/unresolved questions and uncertainty, and exact audit/run closure.
Unrelated mission entities and mission-global findings are omitted — including a
mission-global finding that cites the target claim's own evidence, so the packet can
carry an evidence card while carrying nothing that rests on it. Including such
statements would force the other claims' cards they cite into the packet, because the
canonical verifier requires every finding's citations to be present; that is recorded
in `docs/DECISIONS.md` as a v3 question rather than done here, and
`test_claim_scoped_packet_omits_mission_level_statements_by_design` pins the current
boundary. Existing full-mission packet contracts and output bytes remain unchanged. The claim-scoped result
is revalidated by the existing canonical v2 builder; request/scope/result metadata
never enters v2.

After the SQLite snapshot closes, fulfillment builds `minerva.research-result.v1` with
only a bounded fulfilled status, request digest, output schema, and SHA-256 over the
exact newline-terminated `research-brief.json` bytes. The fixed `research-brief.json`
and `research-result.json` files are published with owner-only modes, no-follow
descriptor-relative writes, `O_EXCL`, file `fsync`, and inode-aware caught-error
cleanup. The service has no identity, clock, ID factory, audit sink, mutation
transaction, provider, credential, or network dependency. It never calls the normal
brief export method because that method intentionally records export state and audit.

A scoped v2 packet is internally canonical but v2 has no database-completeness marker.
The request digest and result artifact hash bind the external selection meaning; packet
verification alone does not prove that unrelated mission state was included. A future
Athena adapter must authenticate and authorize independently before creating or moving
these inert files. Milestone 1.3 adds no adapter, transport, remote identity, shared
database, shared run envelope, MCP surface, Icarus exchange, publication, messaging,
execution, approval, or automatic adoption.

Migration 0003 supplies the indexes that access path needs: `idx_audit_event_entity` on
`audit_events(event_type, entity_id)` serves both the snapshot import-event
lookup and the run-started branch of the scoped audit CTE, and `idx_findings_claim` on
`findings(mission_id, claim_id, created_at, id)` serves the claim-scoped finding and
reference queries. The claim-scoped finding and reference queries name
`idx_findings_claim` with `INDEXED BY`, so its absence fails loudly at statement
preparation; `idx_audit_event_entity` is planner-selected and names no hint, so its
absence degrades silently to a scan. Neither hint guarantees a *seek*: `INDEXED BY`
only requires that the named index exist, and a query that lost its equality predicate
would scan the named index without error. The plans themselves are pinned by
`test_targeted_fulfillment_indexes_are_present_and_selected`, which asserts on
`EXPLAIN QUERY PLAN` output. The cumulative guard is retained unchanged as defense in
depth. See [ADR 0005](adr/0005-targeted-fulfillment-indexing.md).

Synthesis work is bounded before rendering, and each rendered output is checked against
its byte limit before exposure or export. File export uses fixed filenames beneath an
operator-selected root, rejects symlinks and pre-existing targets, and never publishes
or sends the artifacts.

SQLite domain mutations and their audit rows are atomic for caught exceptions and
rejected operations. Export cleanup likewise removes files it created when an exception
returns control to Minerva. SQLite and the filesystem do not share a transaction,
however: process termination, power loss, or an uncatchable crash can leave a partial
export directory. Minerva never overwrites that directory on retry; the operator must
inspect and remove the disposable partial target explicitly.

Database migrations are forward-only. Operators must create and verify a standalone
pre-upgrade backup. An upgraded binary restores that backup directly: the staged copy is
migrated forward inside the audited staging pipeline and deep-validated before
publication (ADR 0004, gate D-11 amendment). Rollback to an older version means stopping
the new binary and restoring that backup to a new path with the prior binary; no in-place
schema downgrade is implemented.

## Future protocol seam

Milestone 1.1 exposes the packet and capability manifest locally but performs no
sibling artifact exchange. A future shared run envelope, if approved, is separately
versioned and remains outside the packet and its semantic digest. It can carry run and
task correlation, actor/capability/scope declarations, schema-and-digest artifact
references, idempotency and status metadata, timestamps, model/node observations, and
a recovery checkpoint. Those fields are correlation metadata, not authentication,
authority, truth, approval, or a recovery guarantee. Artifact references bind a schema
version and SHA-256 digest; they are not filesystem paths or URLs for Minerva to
dereference. See [ADR 0002](adr/0002-system-boundaries.md) for the bounded roles of
Athena, Icarus, Tribunal, Oracle, Vanguard, and Warren.

## Web and local trust boundary

The application binds to `127.0.0.1` by default and refuses a non-loopback host unless
future authenticated multi-user work deliberately changes the boundary. Middleware
enforces loopback `Host`/`Origin`, a body limit, CSP and defensive response headers.
The Milestone 1 HTML surface is read-only; REST mutations use strict JSON contracts and
reject non-local browser origins. Minerva has no CSRF primitive; any future unsafe
browser form must add same-site CSRF protection to the local-origin check, taken from
the git history (`git log -- src/minerva/web/security.py`) rather than written from
scratch. There is no CORS middleware. Jinja autoescaping and plain `<pre>` brief
previews prevent stored content from becoming executable HTML; Minerva does not render
user Markdown as raw HTML.

## Four operational invariants

- **State lives** in the migrated SQLite database and intentionally written immutable
  export/request-result files. Provider credentials and candidate responses are
  ephemeral and never become research state.
- **Feedback lives** in structured errors, CLI exit status, health/ready endpoints,
  doctor output, tests, and the append-only audit ledger. External assistance adds
  metadata-only requested/terminal events and explicit unknown outcomes.
- **Deleting a snapshot breaks** evidence and brief provenance, so foreign keys and
  append-only triggers prohibit it. Deleting/rewriting the database is outside the app.
- **Timing works** because one command owns one transaction; mutations use
  `BEGIN IMMEDIATE`, while request fulfillment uses one query-only WAL read snapshot.
  Bounded busy waits expose contention and deterministic ordering removes completion-
  order ambiguity. The declared external-call exception is bracketed, not atomic: it
  has one attempt, bounded timeout, post-call context revalidation, and no automatic
  retry.
