# Security policy

## Support boundary

Minerva is an alpha, single-OS-user local application tested on Linux/POSIX with
Python 3.12–3.14. Other operating systems are not currently verified or supported.
It binds to `127.0.0.1` by default. The read-only HTML surface, loopback Host/Origin
checks, and REST Origin checks reduce browser-origin risk; they are not authentication
and do not isolate mutually untrusted processes running as the same OS user. There is
no CSRF primitive in the code, and the read-only HTML surface has no form to forge; any
future unsafe browser form must add same-site CSRF protection as well as the
local-origin check. Do not expose the server through a reverse proxy, tunnel, container
port publish, or non-loopback bind.

Source snapshots and research databases can contain sensitive material. Protect the
database and export directory with OS permissions and backups. Secret-pattern scanning
is defense in depth, not a substitute for reviewing material before import. Milestone
1 does not encrypt storage or exports.

Append-only triggers, digests, doctor, and export detect partial or inconsistent
tampering. They are not an external signature or trust anchor: a determined process
inside the same OS-user boundary can coordinate changes to content and integrity
metadata. Standalone backups must therefore be protected and versioned outside the
working database when recovery assurance matters.

Milestone 1 has no URL fetching, model invocation, code/notebook execution, plugin
loading, publication, or messaging surface. URL values are inert metadata. Milestone
2B adds only the reviewed CLI assistance exception described below; it does not add an
API or web invocation surface.

## Standalone packet verification

`minerva packet verify` and `minerva packet inspect` are offline, file-only commands.
They do not open SQLite, contact a network, load provider credentials, publish an
artifact, or invoke a sibling system. Packet input must be one stable regular file;
parent (`..`) segments, symbolic links in any path component, and non-regular targets
are rejected. The final target is type-checked through a path-only descriptor before a
readable handle is opened. The 20 MiB protocol limit is enforced from file metadata
and by a bounded read before UTF-8 or JSON decoding. Expected validation failures use
fixed messages that do not include submitted content or filesystem paths. Sequence
validation stops at the first invalid element, object width and nesting are bounded,
and error classification never expands an attacker-sized validation-error set.
Inspection returns bounded counts rather than stored research text or identifiers.

A successful canonical SHA-256 check establishes internal packet consistency only.
It is not a digital signature, identity assertion, proof of origin, authenticity
guarantee, approval record, or evidence that a claim/source assertion is true. A
determined same-OS-user actor can rewrite the semantic payload and compute its new
digest. The packet carries source digests, citation locations, and quotes but not the
source snapshot bytes, so this standalone workflow cannot independently recompute a
source digest or prove that unavailable source content matched the recorded quote.
Protect packets through separate OS access control or a future approved signing seam
when origin assurance matters.

## Offline research requests

`minerva request verify` applies the standalone no-follow file boundary to a strict
`minerva.research-request.v1` file with a 64 KiB pre-decode limit. It does not open
SQLite, read provider credentials, construct a provider, or contact a network.
Identifiers are fixed Minerva prefix/lowercase-hex forms; unknown fields, free text,
paths, URLs, credentials, identity/authority, transport, callback, execution, approval,
and run-control fields are rejected by the contract. Verification output and errors
are bounded and non-reflective.

`minerva request fulfill` validates the complete request before database construction
or open, then uses one connection-local query-only read snapshot. The only policy
requires the request's sorted active citation IDs to equal the target claim's complete
active ledger. Unknown/out-of-scope, withdrawn, omitted, and newly added evidence fail
closed, so the request cannot silently filter opposing, contextual, or inconclusive
stances. Fulfilled output retains the claim's withdrawn/supersession/status and exact
source/audit/run closure.

The query-only snapshot has one cumulative SQLite virtual-machine instruction budget.
Exhaustion fails closed as `brief_work_limit` (CLI exit `3`) before artifact publication;
it is not a wall-clock timeout. Migration 0003 (ADR 0005) adds targeted indexes on
`audit_events(event_type, entity_id)` and
`findings(mission_id, claim_id, created_at, id)`, so the audit and claim-scoped finding
lookups are point searches and fulfillment work no longer scales with unrelated missions'
history. The budget is retained unchanged as defense in depth and still refuses genuinely
oversized work, including same-mission history the claim-scoped audit query must examine
row by row.

Before full database text or snapshot content is returned to Python, claim-scoped
synthesis asks SQLite for NUL-safe storage-byte lengths at every emitted string's exact
packet multiplicity. UTF-8 is compared directly and UTF-16 uses a conservative
two-to-one threshold. A derived lower bound above the export byte cap fails as
`brief_work_limit`; canonical serialization remains the final byte-size check. This
prevents cumulative quote, metadata, provenance, and finding text from being returned
to Python when the packet cannot fit. SQLite still inspects the stored values, so this
is not an SQLite-memory limit.

`minerva doctor` reports two operator remnants without ever removing them: private
staging copies left beside the database by an interrupted restore or initialization,
and assistance invocations recorded as requested with no terminal outcome. Both are
counts with no filenames, and neither affects readiness or exit status. Partial export
and fulfillment output directories cannot be reported because Minerva deliberately
stores no export paths; that residue remains an operator responsibility.

Fulfillment creates no Minerva identity/run, audit event, export row, or research
mutation and has no network/provider dependency. Fixed `research-brief.json` and
`research-result.json` files use exclusive owner-only no-follow writes; caught second-
write failures remove only files created by that operation. SQLite and filesystem
writes are not crash-atomic, so process or power loss can leave a partial new output
directory that Minerva will refuse to overwrite.

## Publication durability

Every point that publishes a new filename — the exclusive `os.link` behind
initialization, backup, and restore, plus the exported brief and the fulfillment
output files — syncs the containing directory before the operation reports success
or records it. Before an export or fulfillment writes anything, Minerva always syncs
the pinned parent directory that names its output directory, including when that output
directory already existed. This closes the race where one process observes a newly
created directory whose creator has not yet made the name durable. Minerva then syncs
the output directory after writing the files inside it. Failure at either barrier is
reported as `output_publication_durability_unknown` (CLI exit `4`), records no export
audit success, and requires inspection before retry. The visible output directory is
not deleted automatically; after a later output-directory sync failure, Minerva
attempts to remove only operation-created files whose recorded identities still match.
Cleanup is best effort, does not follow symbolic links, and checks recorded identities
before removal; mutually untrusted processes running as the same OS user remain outside
the security boundary. Without those steps, durable file contents could still disappear
because a parent directory entry existed only in the page cache, leaving a successful
operation or committed audit row describing a path that did not survive the crash.

Database publication has one unavoidable uncertain-outcome case. If the exclusive hard
link succeeds but syncing its parent directory fails, the public target is already
visible and another process may have adopted it. Minerva therefore does not delete that
target or report success. It reports `database_publication_durability_unknown` (CLI exit
`4`) and attempts best-effort removal of only its private staging name. A backup failure
at this point records no `database.backup.created` event in the source database; an
initialization or restore target can already contain the corresponding event committed
into the staged database before publication. Stop concurrent use, inspect the exact
target with `doctor --deep`, then either persist its parent directory with trusted OS
tooling and reverify before adopting it, or human-confirm removal of that exact target
and sync the parent before retrying. Minerva has no application-level command that
resolves this OS durability state, so blind retry or deletion is unsafe.

This closes exactly one window and claims nothing further. It does not make a
multi-file export atomic: a crash between the two exported files still leaves the
partial directory described above, which Minerva refuses to overwrite. It does not
cover a crash inside SQLite's own write path, which is SQLite's contract through
`synchronous = FULL`. It does not survive a filesystem or device that acknowledges
`fsync` without persisting, and it says nothing about media failure. Backups remain
an operator responsibility to verify, version, and store outside the database
directory.

The request digest and result artifact SHA-256 prove self-consistency and exact byte
binding only. They do not authenticate a producer, establish origin/authority,
approve work, grant disclosure permission, or prove database completeness. The
claim-scoped v2 packet contains no request/scope marker; retain its request/result
binding when scope interpretation matters. Milestone 1.3 adds no Athena adapter,
transport, remote identity, shared run envelope, MCP, publication, execution,
messaging, approval, or automatic adoption.

## Optional external model assistance

Model assistance is disabled unless the operator installs an optional provider extra,
selects OpenAI or Anthropic and a model, previews the request, and re-runs the CLI with
`--confirm-external-send` plus the exact preview `request_sha256`. Preview does not
read a credential or perform network I/O. Authorization covers one provider, model,
fixed provider destination, bounded context, system prompt, and output limits. Any
change invalidates the digest.

The disclosed context is exact, not a summary: it contains the claim ID, statement,
and falsification criterion plus bounded active evidence citation IDs, quotes, and
stances. Byte offsets, snapshot digests, and supersession references remain local but
are bound into the authorization digest. Treat the preview as the disclosure decision.
Secret-pattern scanning is defense in depth and cannot determine whether research
material is confidential, regulated, licensed, privileged, or otherwise unsuitable
for an external provider. The operator is responsible for authorization to disclose
it and for reviewing the provider's retention, training, residency, and other
data-handling terms.

Credentials are accepted only from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the
current OS-user environment after confirmation. Minerva keeps the selected key in
process memory for the call and does not persist it in SQLite, audit details, output,
or configuration. Environment variables and process memory are still visible to
sufficiently privileged local software; use a short-lived shell/session and provider
key controls appropriate to the data and spending risk.

The two reviewed adapters are pinned to the providers' official API origins. Proxy
environment variables, redirects, automatic retries, provider fallback, model tools,
and external-source retrieval are disabled. SDK environment controls that could inject
headers or account routing also fail closed: `OPENAI_ADMIN_KEY`,
`OPENAI_CUSTOM_HEADERS`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, and
`ANTHROPIC_CUSTOM_HEADERS`. OpenAI requests also disable provider-side response
storage through the available request flag. This is not a promise that either provider
retains no operational data; provider policy and account settings remain outside
Minerva's control. Every authorized request can incur cost.

Claim and evidence text is untrusted prompt content. The system prompt instructs the
model to ignore embedded instructions, use no tools or outside knowledge, preserve
contradiction, and cite only the supplied evidence IDs. Structured output is validated
locally, including evidence-ID membership and secret-pattern checks, but prompt
injection and incorrect model output remain residual risks. Returned candidates are
labeled `agent_inference`, kept ephemeral, and never persisted or adopted as evidence,
a finding, truth, confidence, or claim status.

The audit ledger records a metadata-only requested event before egress and a separate
terminal event afterward. These SQLite transactions cannot be atomic with an external
provider call. Process termination can leave only the requested event. A timeout or
connection failure has an unknown provider outcome: the provider may have processed
or charged for the request even though Minerva received no response. Minerva records
that uncertainty and does not retry automatically.

## Reporting a vulnerability

Do not include source contents, database files, credentials, private paths, or working
exploits in a public issue. Use GitHub private vulnerability reporting for this
repository when available, or contact the repository owner through an already trusted
private channel. Include the affected version, a minimal synthetic reproduction, and
impact. No service-level response time is promised during alpha development.

## Supported versions

Until the first stable release, only the latest commit on the maintained branch is
eligible for security fixes. No released version is currently supported for remote or
multi-user operation.
