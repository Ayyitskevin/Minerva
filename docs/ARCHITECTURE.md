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
- `synthesis`: canonical research-packet assembly, citation verification,
  claim-scoped request fulfillment, Markdown/JSON rendering, digesting, and contained
  file export.
- `api`: strict Pydantic request/response adapters and structured error mapping.
- `web`: loopback-only, read-only server-rendered review pages, local HTTP controls,
  and CSRF primitives reserved for any future unsafe browser form.
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
row access. Migrations are ordered package resources with recorded SHA-256 checksums.
A newer or checksum-mismatched database fails closed.

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
Unrelated mission entities and mission-global findings are omitted. Existing
full-mission packet contracts and output bytes remain unchanged. The claim-scoped result
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

Milestone 1.3 deliberately adds no indexing migration. Existing claim/audit access paths
can therefore make a valid sparse request exceed the work budget; a separately
human-reviewed migration may add targeted indexes to reduce false refusals while
retaining the cumulative guard as defense in depth.

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
pre-upgrade backup. Rollback means stopping the new binary and restoring that backup to
a new path with the prior binary; no in-place schema downgrade is implemented.

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
reject non-local browser origins. A signed same-site CSRF cookie/token primitive exists
and must be wired into any future unsafe browser form. There is no CORS middleware.
Jinja autoescaping and plain `<pre>` brief previews prevent stored content from becoming
executable HTML; Minerva does not render user Markdown as raw HTML.

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
