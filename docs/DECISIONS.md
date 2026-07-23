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
