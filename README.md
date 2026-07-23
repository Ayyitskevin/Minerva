# Minerva

**Ask carefully. Cite everything.**

Minerva is a local-first, provenance-first research laboratory for humans and AI
agents. It records evidence and uncertainty; it does not manufacture certainty.

Milestone 1.1 supports an offline research vertical slice: create a mission, question,
and falsifiable claim; snapshot local UTF-8 source material; attach exact supporting,
opposing, contextual, or inconclusive evidence; inspect its ledger; record labeled
findings; and export a deterministic Markdown brief plus a canonical, machine-verifiable
JSON research packet with resolvable citations and append-only audit provenance.

Milestone 1.2 adds a standalone offline operator surface for that packet. An installed
`minerva` command can verify or inspect `research-brief.json` directly without a
Minerva database, network connection, sibling system, provider SDK, or credential.

Milestone 2B adds one deliberately narrow, optional assistance surface. A local CLI
operator can preview a bounded request made from one claim and its active evidence,
then explicitly authorize that exact request for OpenAI or Anthropic using their own
API key. Returned text is untrusted, ephemeral candidate material; Minerva does not
adopt it as evidence, a finding, or research state.

## Trust boundary

Minerva is alpha software for one trusted OS user. The web server binds to
`127.0.0.1`; loopback is not authentication. Do not expose it remotely. Source data
remains local during every Milestone 1.1 workflow, URL metadata is never fetched, and
the offline demo performs no network operation. Milestone 1.1 has no model, shell,
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

## Canonical research packet

`research-brief.json` is the single canonical agent-facing artifact; Milestone 1.1
upgrades that existing fixed filename in place to the strict
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
`minerva doctor --db backups/research.db --deep`. There is no in-place downgrade. To roll
back an upgrade, stop the newer process and use the older binary to restore a pre-upgrade
backup into a new database path; verify that restored path before deliberately replacing
any operator-owned file.

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
