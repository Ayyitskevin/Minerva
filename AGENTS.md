# AGENTS.md — Minerva repository contract

## Purpose

Minerva is a local-first, provenance-first research laboratory. Its governing rule is:

> Minerva records evidence and uncertainty; it does not manufacture certainty.

This file narrows the fleet-wide autonomy contract for this repository. Explicit user
instructions and the fleet safety rules still take precedence.

## Working agreement

- Read `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, and the ADRs
  before changing domain or security behavior.
- Preserve the shared command/service layer. CLI, API, and web adapters must not write
  SQL or implement alternative validation paths.
- Treat source bytes, citations, audit history, migration history, and deterministic
  exports as high-integrity surfaces. Make the smallest reviewed change and add an
  invariant-level regression test.
- Never add network fetches, model calls, shell/subprocess execution, notebook
  execution, dynamic plugins, publication, messaging, or live sibling-repository
  integrations in Milestone 1.
- Do not claim that a claim is true or derive confidence from evidence counts.
- Do not place real research sources, credentials, private paths, or personal data in
  fixtures, docs, logs, commits, audit records, or PR descriptions.

## Red and green boundaries

Green in an isolated checkout: documentation, tests, local code, reversible fixtures,
builds, and an approved branch/PR workflow.

Human review is required before merging changes to the source/citation coordinate
model, immutability triggers, audit atomicity, migration history, loopback/auth trust
boundary, secret scanning policy, or future integration authentication. Deployment,
external publishing, security-sensitive remote access, live-data migration, and legal
or licensing decisions are not authorized by this repository contract.

## Required gates

Use the locked environment and run all gates before describing a change as complete:

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python -m build
uv run python scripts/verify_dist.py dist
uv run python scripts/installed_smoke.py dist
uv run python scripts/static_security_check.py
uv pip check
git diff --check
```

Skipped tests or unavailable tools must be reported as open verification, not a pass.
No deployment is part of this gate.

## Four invariants to re-check

- State lives in migrated SQLite plus intentionally exported immutable artifacts.
- Feedback lives in structured errors, audit rows, doctor, health/readiness, and tests.
- Deleting snapshots/evidence/audit rows must fail because downstream citations depend
  on them.
- Timing works through explicit transactions, WAL readers, bounded write waits, and
  deterministic ordering.
