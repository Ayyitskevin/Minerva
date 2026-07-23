# Security policy

## Support boundary

Minerva is an alpha, single-OS-user local application tested on Linux/POSIX with
Python 3.12–3.14. Other operating systems are not currently verified or supported.
It binds to `127.0.0.1` by default. The read-only HTML surface, loopback Host/Origin
checks, and REST Origin checks reduce browser-origin risk; they are not authentication
and do not isolate mutually untrusted processes running as the same OS user. A CSRF
primitive is reserved for a future unsafe browser form but is not part of the current
read-only HTML boundary. Do not expose the server through a reverse proxy, tunnel,
container port publish, or non-loopback bind.

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
