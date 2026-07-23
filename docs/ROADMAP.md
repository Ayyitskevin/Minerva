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
- Machine-readable ownership states that Minerva researches but does not execute,
  approve, orchestrate, or publish.
- The additive `minerva.capabilities.v2` manifest advertises canonical packet support
  and truthfully marks sibling exchange, a shared run envelope, orchestration,
  experiment execution, and approval authority unavailable.

## Milestone 2B: explicit evidence-constrained model assistance

- Optional OpenAI and Anthropic extras with operator-supplied environment credentials
- CLI-only exact-context preview and digest-bound external-send confirmation
- Bounded active-evidence disclosure with opposing/inconclusive evidence preserved
- One fixed-destination call with no retry, redirect, fallback, tools, or URL fetching
- Strict structured-response and evidence-ID validation
- Ephemeral, candidate-only `agent_inference` output with no automatic persistence
- Metadata-only requested/terminal audit events with honest unknown-outcome handling

## Later milestones, not implemented now

- Authenticated Athena mission/identity coordination adapter
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
