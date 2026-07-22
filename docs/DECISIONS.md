# Decision index

- [ADR 0001: Use immutable snapshots and exact byte-span evidence](adr/0001-research-evidence-model.md)
- [ADR 0002: Keep Athena, Icarus, and Oracle behind artifact/protocol seams](adr/0002-system-boundaries.md)

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
- Export digests cover a canonical semantic payload; the digest envelope itself is
  excluded to avoid circular hashing.
- Existing databases and export targets are never overwritten by normal commands.
- Migrations are forward-only; recovery from an unwanted upgrade uses a verified
  standalone pre-upgrade backup and the prior binary, not an in-place downgrade.
- The project license is intentionally not selected here; licensing is a human legal
  decision and is not required to prove the vertical slice.
