# Minerva

**Ask carefully. Cite everything.**

Minerva is a local-first, provenance-first research laboratory for humans and AI
agents. It records evidence and uncertainty; it does not manufacture certainty.

Milestone 1 supports an offline research vertical slice: create a mission, question,
and falsifiable claim; snapshot local UTF-8 source material; attach exact supporting,
opposing, contextual, or inconclusive evidence; inspect its ledger; record labeled
findings; and export a deterministic Markdown brief plus a canonical, machine-verifiable
JSON research packet with resolvable citations and append-only audit provenance.

Milestone 1.2 adds a standalone offline operator surface for that packet. An installed
`minerva` command can verify or inspect `research-brief.json` directly without a
Minerva database, network connection, sibling system, provider SDK, or credential.

Milestone 1.3 adds an inert, deterministic `minerva.research-request.v1` artifact for
requesting one claim's complete evidence ledger. The CLI can verify it entirely
offline, then resolve it against one local database snapshot and write a claim-scoped
canonical v2 brief plus a digest-bound result manifest without changing research or
audit state.

Milestone 2B adds one deliberately narrow, optional assistance surface. A local CLI
operator can preview a bounded request made from one claim and its active evidence,
then explicitly authorize that exact request for OpenAI or Anthropic using their own
API key. Returned text is untrusted, ephemeral candidate material; Minerva does not
adopt it as evidence, a finding, or research state.

## Trust boundary

Minerva is alpha software for one trusted OS user. The web server binds to
`127.0.0.1`; loopback is not authentication. Do not expose it remotely. Source data
remains local during every Milestone 1 workflow, URL metadata is never fetched, and
the offline demo performs no network operation. Milestone 1 has no model, shell,
notebook, plugin, sibling-repository exchange, orchestration, experiment execution,
approval, external publishing, or messaging surface. Local brief export is not
publication.

The reviewed Milestone 2B exception is CLI-only and opt-in. Preview performs no
network operation and shows the exact JSON context, destination, limits, and request
SHA-256. Egress occurs only when the operator re-runs the command with explicit
confirmation and that exact digest. See [the threat model](docs/THREAT_MODEL.md),
[security policy](SECURITY.md), and [ADR 0003](docs/adr/0003-explicit-byok-model-assistance.md).

## Platform and development install

Milestone 1 is tested on Linux/POSIX with Python 3.12–3.14. Other operating
systems are not yet verified or supported. Install `uv`, then create the locked
development environment:

```bash
uv sync --extra dev
uv run minerva --help
```

For an installed artifact, build the project and install the generated wheel into an
isolated environment. The package distribution name is `minerva-research`; its command
is `minerva`.

Model assistance is not installed in the base package. Install only the provider you
intend to use, or the combined extra:

```bash
uv sync --extra ai-openai
uv sync --extra ai-anthropic
uv sync --extra ai
```

## Synthetic demo

```bash
uv run minerva-demo --db /tmp/minerva-demo.db --export-dir /tmp/minerva-export
uv run minerva serve --db /tmp/minerva-demo.db
```

The demo refuses to overwrite an existing database, uses only synthetic sources,
performs no outbound network operation, writes a deterministic brief, and prints the
loopback review URL. Delete the disposable paths yourself when finished; Minerva never
removes them automatically.

## CLI vertical slice

The exact text offsets below are UTF-8 byte offsets. Use `source show` to inspect the
stored snapshot and calculate a span; the submitted quote must match exactly.

```bash
minerva init --db research.db
minerva mission create --db research.db --title "Local inference comparison" \
  --objective "Compare bounded local inference strategies"
minerva question add --db research.db --mission MIS_ID \
  --text "Which strategy best preserves reproducibility?"
minerva claim add --db research.db --mission MIS_ID --question QUE_ID \
  --statement "Pinned runtimes improve reproducibility." \
  --falsification-criteria "Repeated pinned runs diverge more than unpinned controls."
minerva source import --db research.db --mission MIS_ID --root ./sources \
  --file study.txt --media-type text/plain
minerva evidence add --db research.db --mission MIS_ID --claim CLM_ID \
  --snapshot SNP_ID --start 0 --end 42 --quote "EXACT QUOTE" --stance supports
minerva claim show --db research.db --claim CLM_ID
minerva brief export --db research.db --mission MIS_ID --output-dir ./export
minerva audit list --db research.db --mission MIS_ID
minerva doctor --db research.db --deep
```

Repeat `evidence add` with an opposing source to make contradiction visible. Material
findings are created with `finding add` and require evidence IDs; assumptions and
unresolved questions remain explicitly labeled.

Corrections extend the record rather than rewriting it. `evidence withdraw` marks an
observation as no longer standing while leaving it visible in the ledger, and
`finding retract --finding FND_ID --reason "..."` records that a finding built on it is
no longer asserted. A retracted finding leaves the brief but keeps its row, citations,
and audit history, so a withdrawal no longer blocks the mission's export.

Retraction is visible wherever a finding is read, not only in the brief it leaves.
`mission show`, `GET /api/v1/missions/{id}/findings`, and the web review page each
carry `retracted` with the recorded reason, timestamp, and actor, so a retracted
statement is never presented as a live one. `doctor` verifies the retraction records
themselves: their append-only triggers are required, and every retraction row is
reconciled against its `research.finding.retracted` audit event.

## Command reference

Every verb the CLI exposes. `--help` on any of them lists its arguments, and the
sections below cover the packet, request, assistance, and operations verbs in
depth. A test asserts this table stays complete, so a new verb cannot ship
undocumented.

| Command | Purpose |
| --- | --- |
| `minerva init` | initialize or migrate a database |
| `minerva mission create` | create a research mission |
| `minerva mission list` | list missions, newest first |
| `minerva mission show` | show one mission and its questions |
| `minerva question add` | add a research question to a mission |
| `minerva claim add` | add a falsifiable claim under a question |
| `minerva claim show` | show one claim, its status, and its findings |
| `minerva claim ledger` | show a claim's complete evidence ledger, withdrawals included |
| `minerva claim status` | append a claim status, never overwriting one |
| `minerva source import` | import one file as an immutable snapshot |
| `minerva source show` | show snapshot metadata, or its stored bytes |
| `minerva evidence add` | cite an exact byte span of a snapshot |
| `minerva evidence withdraw` | mark evidence as no longer standing, keeping it in the ledger |
| `minerva finding add` | record a labeled finding, assumption, or open question |
| `minerva finding retract` | record that a finding is no longer asserted, keeping its history |
| `minerva brief preview` | render a mission brief without writing files |
| `minerva brief export` | write a mission's canonical brief to a new directory |
| `minerva packet verify` | verify one canonical research packet without a database |
| `minerva packet inspect` | show bounded metadata for one verified research packet |
| `minerva request verify` | verify one canonical research request without a database |
| `minerva request fulfill` | write a claim-scoped canonical brief without mutating research state |
| `minerva audit list` | list append-only audit events |
| `minerva doctor` | validate local database integrity |
| `minerva backup` | create a non-overwriting backup |
| `minerva restore` | restore into a new database |
| `minerva assist finding-candidates` | draft candidate agent inferences from one claim's active evidence |
| `minerva assist adopt` | adopt one reviewed candidate as a persisted, labeled agent inference |
| `minerva assist retract-inference` | record that an adopted inference is no longer asserted, keeping its history |
| `minerva serve` | start the loopback review server |

There is no verb that deletes a mission, claim, snapshot, citation, finding, or
audit event. Corrections extend the record: `claim status` appends, `evidence
withdraw` and `finding retract` mark without removing, and `backup` refuses to
overwrite. That absence is the contract, not an unfinished surface.

## Canonical research packet

`research-brief.json` is the single canonical agent-facing artifact; Milestone 1.1
upgraded that existing fixed filename in place to the strict
`minerva.research-brief.v2` contract rather than adding a parallel packet format. It
preserves the mission and questions, proposition-only claims, every evidence stance,
exact citation locations and quotes, source digests, findings, assumptions, unresolved
questions, uncertainties, creator/run provenance, and relevant audit references.

The packet is independent of SQLite at the protocol boundary. Its strict parser and
verifier reject malformed structure, digest mismatches, broken references, and a
status presented as evidence-valid without its required active, resolvable citation
stances. Supersession validation is linear in citation count, and untrusted packet
input is rejected above the 20 MiB protocol ceiling. Honest open and inconclusive
states remain visible. The export digest is SHA-256 over the compact, sorted-key
canonical semantic payload, so fixed research state and schema produce byte-identical
packet output. The packet also states its authority boundary in data: Minerva
researches; it does not execute, approve, orchestrate, or publish.

Verify an exported packet directly from its file:

```bash
minerva packet verify --input research-brief.json
```

Success returns one compact JSON object on stdout with `status: "verified"`, the
schema version, canonical export digest, integrity/authenticity distinction, and
ownership boundary. The command rejects parent (`..`) segments, symbolic links in any
path component, non-regular or changing files, packets above 20 MiB before JSON
decoding, malformed or duplicate JSON fields, non-standard numbers, unsupported
schemas, excessive JSON shape or validation-error fanout, digest changes, and every
structural or semantic inconsistency enforced by the canonical verifier.

Inspect bounded packet metadata without exposing its research text:

```bash
minerva packet inspect --input research-brief.json
```

Inspection uses the CLI's normal machine-readable JSON convention. It reports only
fixed-key metadata: verification status, schema and digest, mission/question/claim and
finding-class counts, citation stance and active/withdrawn counts, source counts,
creator/run and audit coverage, and the ownership boundary. Counts are inventory,
not confidence. It does not print mission, claim, finding, source, quote, actor, run,
audit, URL, credential, or input-path values.

Both commands are file-only and offline: they do not open SQLite, contact a network,
load provider credentials, or import source bytes from elsewhere. Exit status is
stable:

| Status | Meaning |
| --- | --- |
| `0` | Packet verified; bounded JSON is on stdout. |
| `2` | Command-line usage error from `argparse`. |
| `3` | Expected unsafe-input, malformed-packet, or verification failure; bounded JSON error is on stderr. |
| `4` | Unexpected local operating-system failure. |
| `1` | Unexpected internal failure. |

The export SHA-256 establishes canonical payload self-consistency only. It is not a
signature, proof of origin, authenticity guarantee, approval, or evidence that a
claim is true. A same-OS-user actor can rewrite a packet and recompute its digest, and
the packet contains source digests and citation metadata rather than source bytes, so
standalone verification cannot independently rehash the original source content.

No sibling system consumes or receives the packet in this milestone. The future
Athena coordination and Icarus experiment exchange seams remain unimplemented. Any
future exchange must use explicit versioned artifact references and the protocol
boundary described in [ADR 0002](docs/adr/0002-system-boundaries.md); neither packet
command publishes, sends, fetches, executes, approves, or orchestrates anything.

## Offline research request contract

`minerva.research-request.v1` is a strict, SQLite-independent input artifact. Its
envelope contains only a canonical payload digest and this bounded payload shape:

```json
{
  "schema_version": "minerva.research-request.v1",
  "request_digest": "<SHA-256 of the canonical request payload>",
  "request": {
    "schema_version": "minerva.research-request.v1",
    "mission_id": "mis_<32 lowercase hex characters>",
    "claim_id": "clm_<32 lowercase hex characters>",
    "evidence_selection": {
      "policy": "complete_claim_ledger",
      "expected_active_citation_ids": ["evd_<32 lowercase hex characters>"]
    },
    "requested_output_schema": "minerva.research-brief.v2"
  }
}
```

The citation IDs must be unique and lexicographically sorted, with at most 200 entries.
The list is an exact active-ledger freshness precondition, not a subset selector:
fulfillment refuses omitted, newly added, unknown, out-of-scope, or explicitly
withdrawn evidence. This prevents a requester from suppressing opposing, contextual,
or inconclusive active evidence. A successful brief also retains the claim's withdrawn
history, supersession chain, status provenance, linked findings and uncertainty, source
snapshots, and exact audit/run closure.

Verify a request without opening SQLite or loading provider/network code:

```bash
minerva request verify --input research-request.json
```

Verification rejects files above 64 KiB before JSON decoding, unsafe or changing file
paths, malformed/duplicate/non-standard JSON, unsupported schema, policy, or output
versions, digest changes, unknown fields, invalid identifier shapes, and excessive JSON
depth, width, or validation fanout. Success is compact fixed-key JSON that reports only
the schema, request digest, output schema, selection policy/count, and the distinction
between digest integrity and unestablished authenticity/authorization.

Fulfill a verified request into a new local output directory:

```bash
minerva request fulfill --db research.db --input research-request.json \
  --output-dir ./research-result
```

The request is completely validated before Minerva constructs or opens the database.
Fulfillment resolves the mission, claim, complete ledger, and canonical synthesis in
one query-only SQLite read snapshot. It creates no identity/run, audit event,
`brief_exports` row, research mutation, provider call, network operation, publication,
message, execution, approval, or orchestration. It exclusively writes fixed owner-only
files and never overwrites an existing target:

Across that snapshot, fulfillment caps cumulative SQLite virtual-machine work. Exhaustion
fails closed as the stable `brief_work_limit` domain refusal (CLI exit `3`) before either
artifact is written. This is an instruction-work bound, not a wall-clock timeout, and
retrying against the same unchanged database is not a remedy. Migration 0003 adds targeted
audit and claim-scoped finding indexes, so fulfillment work no longer grows with unrelated
missions' history; the bound itself is unchanged and still refuses genuinely oversized
requests.

Before full mission/question/claim, source, citation, finding, audit, or run text—or
snapshot content—is returned to Python, claim-scoped preflight asks SQLite for
identifiers, content byte lengths, and aggregate NUL-safe storage-byte lengths at each
string's exact packet multiplicity. UTF-8 is compared directly with the export limit;
UTF-16 uses a conservative two-to-one threshold. If the derived lower bound cannot fit,
fulfillment refuses with `brief_work_limit`; canonical serialization still enforces the
final byte limit. The aggregate queries inspect stored values inside SQLite, so this is
a Python-materialization guard, not an SQLite-memory limit.

- `research-brief.json` — the canonical `minerva.research-brief.v2` claim-scoped packet.
- `research-result.json` — strict `minerva.research-result.v1` status containing only
  the request digest and the exact output schema/SHA-256.

The result SHA-256 covers the complete `research-brief.json` bytes, including its final
newline, and is distinct from the packet's inner semantic export digest. The v2 packet
deliberately contains no request/scope marker or request-specific authority, approval,
transport, callback, or run-control fields. It does retain canonical v2 research and
provenance fields, including source labels (which may be path-like), inert URL metadata,
creator/actor identifiers, and run/audit references; review the packet itself as a
disclosure-bearing artifact. Consequently, standalone packet verification proves
internal consistency, not completeness relative to a database; retain the request and
result manifest when the claim-scoped selection meaning matters.

Both request commands use the existing CLI exit contract: `0` success, `2` usage,
`3` expected validation/scope/domain refusal, `4` unexpected local OS/SQLite failure,
and `1` unexpected internal failure. Errors are bounded and never reflect request
contents, identifiers, credentials, or filesystem paths.

This milestone implements no Athena adapter, transport, authentication, remote actor,
shared run envelope, MCP server, Icarus artifact, or automatic request adoption. A
future adapter must authenticate and authorize its caller independently; a valid
request digest establishes self-consistency only, never identity, authority, approval,
or permission to disclose the selected research.

## Optional external finding candidates

Choose a supported provider and a provider-specific model identifier with CLI options
or non-secret preference environment variables. Keep the provider key only in the
current OS-user environment:

```bash
export MINERVA_AI_PROVIDER=openai
export MINERVA_AI_MODEL=provider-model-id
export OPENAI_API_KEY=your-provider-key

minerva assist finding-candidates --db research.db --claim CLM_ID
```

For Anthropic, select `anthropic` and set `ANTHROPIC_API_KEY` instead. Do not put API
keys in command-line arguments, source files, databases, fixtures, logs, or committed
environment files.

The first command is preview-only: it does not read the provider credential or call a
network service. Review `context_json`, `destination`, limits, and `request_sha256`.
The context contains the exact claim ID, statement, and falsification criterion plus
the bounded active evidence citation IDs, quotes, and stances that will leave the
machine. Withdrawn evidence is excluded and reported as such. Byte offsets, snapshot
digests, and supersession references remain local but are bound into the authorization
digest as provenance. To authorize only that reviewed request, re-run with both
confirmation fields:

```bash
minerva assist finding-candidates --db research.db --claim CLM_ID \
  --confirm-external-send \
  --expected-request-sha256 REQUEST_SHA256_FROM_PREVIEW
```

Any change to the selected context or digest-bound request parameters changes the
digest and requires a fresh preview. The selected provider may charge for the request
and may retain or process submitted data under its own terms and settings; the
operator must review those terms and must not send material they are not authorized
to disclose. Minerva disables automatic retries, redirects, provider fallback, tool
use, and provider-side storage where the provider API exposes a request control. A
timeout or connection loss has an unknown provider outcome, so Minerva does not retry
automatically.

Minerva validates the structured response against the authorized evidence IDs and
returns at most three labeled `agent_inference` candidates with explicit uncertainty.
Candidates are not evidence or truth, do not update claim status, and are not stored
or adopted by Minerva. The audit ledger records bounded request/result metadata and
digests, not credentials, prompts, evidence text, or returned candidate text.

A candidate the operator judges correct can be adopted explicitly, one candidate from
one exact preview at a time. Adoption re-supplies the reviewed candidate text, its
citation IDs, the provider response digest, and `--expected-request-sha256` — the same
request digest that authorized the invocation. Minerva regenerates the preview from
live state, refuses with `assistant_context_changed` if it no longer matches that
digest, and revalidates every citation against the live record before persisting a
labeled `agent_inference` with full provenance:

```bash
minerva assist adopt --db research.db --claim CLM_ID \
  --expected-request-sha256 REQUEST_SHA256 \
  --candidate-index 0 --response-sha256 RESPONSE_SHA256 \
  --statement "ADOPTED STATEMENT" --uncertainty "RECORDED UNCERTAINTY" \
  --evidence EVD_ID
```

The pin is required, not optional: it is what makes the stored
`(request_sha256, response_sha256)` pair describe one real exchange with the provider
rather than an adopt-time request digest beside a generation-time response digest, and
it is what keeps the `(request_sha256, candidate_index, claim_id)` uniqueness that
refuses a repeated adoption stable across any change to the evidence ledger.

An adopted inference is never evidence and never a finding; it cannot influence claim
status and does not count toward anything. `assist retract-inference --inference INF_ID
--reason "..."` records that one is no longer asserted, keeping its row and history,
and `finding add --from-inference INF_ID --status STATUS` promotes one into a human
finding — the operator's own assertion — linked to the inference that remains as its
provenance. Inferences and their retraction state (reason, timestamp, actor) are
visible wherever findings are read: `mission show`, `claim show`,
`GET /api/v1/missions/{id}/findings`, the web review page, and their own clearly
labeled section of the Markdown brief, which retracted inferences leave exactly as
retracted findings do. The canonical `minerva.research-brief.v2` JSON is unchanged by
adoption. `doctor --deep` verifies inference citation integrity symmetric with
findings.

## Web and API

```bash
minerva serve --db research.db --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. Health, readiness, and the capability manifest are at
`/healthz`, `/readyz`, and `/api/v1/capabilities`. Versioned REST contracts live under
`/api/v1`; OpenAPI is available locally while the process is running. Model assistance
cannot be invoked from the API or web interface.

## Operations and verification

```bash
minerva backup --db research.db --output backups/research.db
minerva restore --backup backups/research.db --db restored.db
minerva doctor --db restored.db --deep
```

Backups use SQLite's online backup API. Restore, demo, and export refuse existing
targets. The complete lint, formatting, typing, tests, coverage, build, installed-wheel,
dependency, security, and diff gates are listed in [AGENTS.md](AGENTS.md).

Minerva migrations are forward-only. Before running `minerva init` against an existing
database, create a standalone backup and verify it with
`minerva doctor --db backups/research.db --deep`. Restoring that pre-upgrade backup with
the upgraded binary works directly: restore migrates the staged copy forward inside the
audited staging pipeline, records a `database.migrated` audit event, and deep-validates
the migrated state before publication (ADR 0004, gate D-11). There is no in-place
downgrade, so rolling back to an older version still means stopping the newer process and
using the older binary to restore a pre-upgrade backup into a new database path; verify
that restored path before deliberately replacing any operator-owned file.

`doctor` also reports remnants it will never remove: private staging copies left beside
the database by an interrupted restore or initialization, and assistance invocations
recorded as requested with no terminal outcome. Both are counts, they do not affect the
exit status or readiness, and cleanup is yours to decide — Minerva does not delete files
it cannot prove it created. Partial export or fulfillment output directories cannot be
reported, because Minerva deliberately stores no export paths.

A backup is a standalone Minerva SQLite artifact containing the research and audit state
committed before its online copy. Protect and version it independently. It has no external
signature or integrity anchor, so a determined same-OS-user coordinated rewrite of both
content and integrity metadata is outside the Milestone 1 detection boundary.

## Design references

- [Product requirements and research vocabulary](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Decision log](docs/DECISIONS.md)
- [Roadmap and explicit non-goals](docs/ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
