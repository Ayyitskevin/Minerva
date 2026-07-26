# Changelog

Entries describe behaviour a reader would notice. Each release records the gate
evidence observed at the time it was prepared, not evidence expected of it.

Minerva is not deployed or published to a package index from this repository. A
release here is a tag plus this record.

## Unreleased

Prepared for `v0.2.0a1`; not yet tagged. `pyproject.toml` declares version
`0.2.0a1`, so the tag must be `v0.2.0a1` unless the pre-release period is
deliberately declared over and the version bumped to `0.2.0` first. See the
release runbook in `CONTRIBUTING.md`.

### Research record

- Findings can be **retracted** (Milestone 1.5). Retraction never edits or deletes:
  it appends a record with its own no-update/no-delete triggers, and the finding,
  its citations, and its history stay. Surfaces that read findings return a
  retracted one marked with its reason, timestamp, and actor; synthesis excludes it
  from the brief rather than presenting it as asserted.
- An **assumption may cite withdrawn evidence**, matching what export has always
  allowed. Material findings still cannot; that refusal is unchanged.

### Contracts

- `minerva.capabilities.v2` gained `research.packet.v2.verify.cli` and
  `research.packet.v2.inspect.cli`. Additive: no entry was removed or altered.
- Canonical-JSON serialization and strict parsing for
  `minerva.research-packet.v2` and `minerva.research-request.v1` now come from one
  module. The golden fixtures are byte-identical across the change.

### Refusals that now describe the right problem

- A **concurrent upgrade** of the same database reports success on both sides
  instead of one spurious `migration_failed`. Losing to a *newer* installation
  reports `database_too_new`. A genuinely failed migration still reports
  `migration_failed` and leaves the database at its previous version.
- Float citation offsets refuse with `citation_offsets_invalid` instead of raising
  an unmapped `TypeError`.
- A symlinked database path reports `database_symlink` regardless of the
  `refuse_existing` flag.
- The research-request digest-mismatch classifier is anchored to the envelope root,
  so no other validation error can claim `request_digest_mismatch`.

### Operator-facing

- **Interrupting a provider call** (Ctrl-C) now records a terminal
  `outcome_unknown` audit event instead of leaving the invocation unmatched
  forever. The outcome is unknown rather than failed: the request had already left
  the machine, so the provider may have processed and charged for it.
- `doctor` reports staging remnants, unfinished assistance invocations, and
  retraction/audit reconciliation.
- `backup` refuses an outdated-but-intact database with
  `database_migration_required` rather than implying corruption.
- The README documents every CLI verb, and every subcommand has `--help` text.

### Security

- The identity-header denylist covers the mainstream proxy families (Google IAP,
  oauth2-proxy, Azure EasyAuth, Kong, Cloudflare Access). This is defence in depth:
  no code path reads an actor from a header, so accepting one never granted
  anything.
- The suite-wide outbound-network guard covers `connect`, `connect_ex`,
  `create_connection`, `sendto`, and `sendmsg`.
- The static security gate catches aliases bound through tuple, list, and starred
  unpacking, and its own detection branches are held to the coverage floor.

### Development

- Branch-coverage floor ratcheted from 85% to 88%.
- `scripts/regenerate_golden_fixtures.py` rebuilds the golden fixtures. It defaults
  to checking and exits non-zero with a diff; `--write` is explicit.
- `CONTRIBUTING.md` records the release runbook and the commit-attribution
  convention.

### Gate evidence

Observed on Linux, Python 3.12.3, at the head of this entry's work:

| Gate | Result |
| --- | --- |
| `ruff check .` | passed |
| `ruff format --check .` | passed, 77 files |
| `mypy` | passed, 53 source files |
| `pytest` | **689 passed**, 90.00% branch coverage against an 88% floor |
| `pytest` (Python 3.13) | 689 passed, 90.00% branch coverage |
| `pytest` (Python 3.14) | **not verified locally** — see below |
| `python -m build` | `minerva_research-0.2.0a1{-py3-none-any.whl,.tar.gz}` |
| `verify_dist.py dist` | verified wheel and sdist |
| `installed_smoke.py dist` | passed |
| `static_security_check.py` | passed, 51 files |
| `uv pip check` | 41 packages compatible |
| `git diff --check` | clean |

**Open verification.** Python 3.14 could not be measured locally: the only
interpreter available here is `3.14.0rc2`, and the pinned pydantic fails on it with
`_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`. CI installs a
released 3.14.x where the same suite passes. This is an environment limitation, not
a known defect, and it is recorded as unverified rather than counted as a pass.
