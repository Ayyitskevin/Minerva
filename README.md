# Minerva

**Ask carefully. Cite everything.**

Minerva is a local-first, provenance-first research laboratory for humans and AI
agents. It records evidence and uncertainty; it does not manufacture certainty.

Milestone 1 supports an offline research vertical slice: create a mission, question,
and falsifiable claim; snapshot local UTF-8 source material; attach exact supporting
and opposing evidence; inspect its ledger; record labeled findings; and export a
deterministic Markdown/JSON brief with resolvable citations and an append-only audit
trail.

Milestone 2B adds one deliberately narrow, optional assistance surface. A local CLI
operator can preview a bounded request made from one claim and its active evidence,
then explicitly authorize that exact request for OpenAI or Anthropic using their own
API key. Returned text is untrusted, ephemeral candidate material; Minerva does not
adopt it as evidence, a finding, or research state.

## Trust boundary

Minerva is alpha software for one trusted OS user. The web server binds to
`127.0.0.1`; loopback is not authentication. Do not expose it remotely. Source data
remains local during every Milestone 1 workflow, URL metadata is never fetched, and
the offline demo performs no network operation. The first milestone has no model,
shell, notebook, plugin, sibling-repository integration, publishing, or messaging
surface.

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
