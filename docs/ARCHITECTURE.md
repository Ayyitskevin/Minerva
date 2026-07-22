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
- `synthesis`: canonical brief assembly, citation verification, Markdown/JSON
  rendering, digesting, and contained file export.
- `api`: strict Pydantic request/response adapters and structured error mapping.
- `web`: loopback-only, read-only server-rendered review pages, local HTTP controls,
  and CSRF primitives reserved for any future unsafe browser form.
- `cli`: local operator commands, demo, backup/restore, doctor, and server startup.
- `integrations`: documentation-only protocol seams for now; no live adapters.

Imports point inward: adapters may import domain services; domain packages do not
import FastAPI, Jinja, or CLI modules. Cross-domain writes are coordinated by an
application service using one connection and transaction.

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

## Deterministic synthesis

Queries use explicit stable ordering. The canonical brief payload contains no export
wall-clock time. JSON uses UTF-8, sorted keys, compact separators, and a trailing
newline. SHA-256 is computed over that canonical payload; both output formats include
the same digest envelope. Markdown is rendered from the payload without interpreting
stored text as HTML. Fixed database state plus fixed export schema/config therefore
produces byte-identical output.

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

- **State lives** in the migrated SQLite database and immutable export files.
- **Feedback lives** in structured errors, CLI exit status, health/ready endpoints,
  doctor output, tests, and the append-only audit ledger.
- **Deleting a snapshot breaks** evidence and brief provenance, so foreign keys and
  append-only triggers prohibit it. Deleting/rewriting the database is outside the app.
- **Timing works** because one command owns one `BEGIN IMMEDIATE` transaction; WAL
  permits readers, bounded busy waits expose write contention, and deterministic query
  ordering removes completion-order ambiguity.
