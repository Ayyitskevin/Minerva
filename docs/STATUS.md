# Status

Updated: 2026-08-22

Minerva is alpha research-memory software for one trusted OS user. The latest
published tag is `v0.2.0a1`; commit `bfe5a2c` is deployed on mickey but is
not a tagged package release.

## State at a glance

| Layer | Current state |
| --- | --- |
| Product contract | Decision 0: local, provenance-first research-memory; no orchestration or publication |
| Live runtime | Loopback service active on mickey against the persistent SQLite database |
| Live corpus | 3 missions, 17 immutable snapshots, 36 citations, 17 findings, 207 audit events |
| Integrity | `doctor --deep` passed all checks at schema 5 on 2026-08-22 |
| Recovery | A 503,808-byte backup restored and deep-verified in a fresh `/tmp` path |
| Deployed change | Controlled cockpit, guided intake, real-corpus quality evaluator, scorecard, and license at `bfe5a2c` |
| Release state | Local gates and exact-head GitHub CI pass; deployed by explicit owner override; tag and package release remain separate |

The counts above are a dated observation, not a promise that the database will
remain at those counts. Re-run the commands in the evaluation record before
using them as current state.

## What is already established

- Immutable snapshots, exact byte-span evidence, append-only corrections, and
  deterministic briefs share one service layer.
- The persistent mickey database, loopback service, and nightly backup timer are
  active.
- Three genuine missions exercise the research-memory role.
- Queue, review, lineage, Lens, dossier, assistance adoption, backup, restore,
  and deep integrity checks already exist.

## What the deployed change adds

- `mission overview` for a compact, deterministic scan of structural cues.
- GET-only queue, claim-review, and lineage pages. They expose receipts; they do
  not create tasks or mutate the research record.
- `source preview` and `source import --expected-sha256` so an operator can
  review safe local bytes and pin the exact digest before persistence.
- `intake preview` and `intake file` for exact occurrence selection without manual
  byte arithmetic, with explicit stance, digest/sequence preconditions, duplicate
  refusal, and the normal atomic evidence audit.
- A measured pillar scorecard plus dated cockpit, intake, and persistent-corpus
  research-quality evaluation records.
- Apache-2.0 licensing from this change forward.
- The mission detail page is now an action-first cockpit with narrow claim, status,
  and finding commands protected by Origin, signed CSRF, exact form contracts,
  append-only audit, and stale/replay preconditions.

## Gates that remain closed

Gate D-2 remains closed because Athena cannot hold the required keypair. MCP,
remote bind, multi-user authorization, automatic evidence adoption, and
publication remain non-goals for this season. DeepAPI is intentionally not a
Minerva dependency; the owner declined that integration on 2026-08-21.

The current package version remains `0.2.0a1` because this deployment is not a
release. The immutable `v0.2.0a1` tag will not move or be reused; any future release
requires a new version and dated changelog section.

## Update discipline

Update this page after a release, deploy, trust-boundary change, or material
scorecard movement. Put measurements in a dated file under `docs/evals/`; do
not overwrite historical observations with current aspirations.
