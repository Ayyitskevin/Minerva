# Decision index

- [ADR 0001: Use immutable snapshots and exact byte-span evidence](adr/0001-research-evidence-model.md)
- [ADR 0002: Keep sibling systems behind artifact/protocol seams](adr/0002-system-boundaries.md)
- [ADR 0003: Require explicit BYOK consent for bounded model assistance](adr/0003-explicit-byok-model-assistance.md)
- [ADR 0004: Audit restored databases before exclusive publication](adr/0004-staged-restore-audit-publication.md)

## Milestone 1 implementation decisions

- Linux/POSIX with Python 3.12–3.14 is the tested alpha boundary. FastAPI, Jinja2,
  stdlib `sqlite3`, and stdlib `argparse` keep the runtime small and avoid a
  JavaScript build chain. Other operating systems remain unverified.
- Migrations are explicit packaged SQL files with recorded checksums. An ORM is not
  required for the bounded schema and would not replace domain validation.
- Source locations are UTF-8 byte offsets, not code-point offsets or line numbers.
- Duplicate source bytes produce equal digests but distinct provenance registrations.
- User-supplied Markdown/HTML is displayed as escaped text; Milestone 1 does not need
  a rich renderer or sanitizer dependency.
- The fixed `research-brief.json` export is the one canonical agent packet. Version 2
  adds strict SQLite-independent parsing and verification, complete research and
  provenance preservation, and an explicit no-execute/no-approve/no-orchestrate/
  no-publish ownership boundary instead of creating a parallel format.
- Export digests cover the compact, sorted-key canonical semantic payload; the digest
  envelope itself is excluded to avoid circular hashing.
- Capability manifest schema v2 is additive: packet/export and optional CLI-only
  assistance support are advertised while sibling exchange, orchestration, experiment
  execution, approval authority, and the future shared run envelope remain explicitly
  unavailable.
- A future shared run envelope is separately versioned from packet content. Its
  artifact references bind schema version plus SHA-256, not paths or URLs, and its
  fields provide correlation metadata rather than authentication, authority, truth,
  approval, or guaranteed recovery.
- Existing databases and export targets are never overwritten by normal commands.
- Migrations are forward-only; recovery from an unwanted upgrade uses a verified
  standalone pre-upgrade backup and the prior binary, not an in-place downgrade.
- The project license is intentionally not selected here; licensing is a human legal
  decision and is not required to prove the vertical slice.

## Milestone 1.2 implementation decisions

- The existing `minerva.research-brief.v2` document remains the only packet format.
  Standalone tooling calls its canonical parser and verifier rather than introducing a
  second validation path.
- Packet intake is a Linux file-boundary adapter: it rejects parent segments, walks
  path components with descriptor-relative no-follow opens, pins and type-checks the
  final target with `O_PATH`, accepts only one stable regular file, enforces the 20 MiB
  limit before decoding, and parses only bytes captured from the pinned descriptor.
- `packet verify` and `packet inspect` are database-free, offline commands. Their
  compact JSON outputs are fixed-key and bounded; inspection exposes inventory and
  provenance/audit coverage, not stored research text, identifiers, URLs, or paths.
- Audit references must respect dependency order as well as coverage: a recorded
  mutation cannot precede the entities or evidence state it depends on.
- Untrusted sequence fields stop validation on the first invalid item; JSON
  object-width/nesting preflight and bounded error classification prevent hostile
  packets from multiplying validation errors into attacker-sized output or memory.
- Canonical digest verification establishes self-consistency only. Packet
  authenticity, source-byte revalidation, transport, signing, Athena/Icarus exchange,
  and any execution or approval authority remain future seams.

## Milestone 1.3 implementation decisions

- `minerva.research-request.v1` is an inert canonical selection contract, not an
  Athena adapter or shared run envelope. It contains only exact Minerva identifiers,
  complete-ledger selection, and requested output schema; its digest is
  self-consistency, not authentication or authority.
- `complete_claim_ledger` is the only policy. Its sorted active citation IDs are an
  exact freshness precondition, never a subset: fulfillment preserves every active
  stance and all withdrawn/supersession/status history needed by canonical v2.
- Fulfillment validates the request before database open and resolves mission, claim,
  ledger, and claim-scoped synthesis through one query-only read snapshot. It does not
  call the mutating/audited brief-export path.
- Fulfillment bounds cumulative SQLite virtual-machine work with a connection-local
  progress handler and maps only its own exhaustion interrupt to the existing
  `brief_work_limit` refusal. This schema-free hardening accepts possible false refusal
  on scan-heavy databases; targeted indexes are deferred to a human-reviewed migration.
- Before full database text or snapshot content is returned to Python, claim-scoped
  synthesis preflights NUL-safe storage-byte lengths at every emitted string's exact
  packet multiplicity. UTF-8 is exact and UTF-16 uses a conservative two-to-one
  threshold; canonical serialization remains authoritative. SQLite still inspects the
  stored values, so this is a Python-materialization guard rather than an SQLite-memory
  limit.
- Claim-scoped output remains `minerva.research-brief.v2`; request/scope metadata does
  not fork or extend the packet schema. Minimal `minerva.research-result.v1` binds the
  request digest to exact output bytes. Consumers need that external binding to
  interpret selection completeness.
- Fixed request-result files use the existing exclusive no-follow writer and caught-
  error cleanup. No migration, identity/run, audit record, provider/model, network,
  transport, publication, messaging, execution, approval, or automatic adoption is
  added.

## Milestone 2B implementation decisions

- Model assistance is an optional CLI-only exception to the offline Milestone 1
  boundary, not a general integration or autonomous-research platform.
- Provider choice and model are explicit. Credentials are BYOK environment values,
  loaded only after the operator authorizes the exact preview digest.
- OpenAI and Anthropic are separate optional extras. Network/provider imports are
  restricted to one reviewed adapter file per provider.
- Exact active evidence is disclosed only after preview; model output is validated,
  ephemeral candidate `agent_inference` and never research state.
- Requested and terminal audit metadata bracket the external call but cannot be
  transactionally atomic with it. Timeouts have unknown provider outcomes and are not
  retried automatically.
