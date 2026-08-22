# Pillar baseline evaluation — 2026-08-21

## Scope and owner decision

This evaluation covers the local Minerva corpus and the next-level working
change based on `origin/main` at `ee4edb6`. Kevin approved genuine research
writes and Apache-2.0, and explicitly declined DeepAPI integration. No external
research service was called. The substitute evidence is a real local corpus,
repository tests, a recovery drill, and explicit human review of the scope.

The working change was not deployed, tagged, pushed, or published during this
evaluation.

## Preconditions

- Live database: owner-managed local research database (path intentionally omitted)
- Runtime: `minerva.service` active, loopback only
- Backup timer: `minerva-backup.timer` active and waiting
- Corpus before new dogfood work: 2 missions, 13 snapshots, 32 citations,
  14 findings, 171 audit events
- Deep doctor: all checks green, schema 5 of 5

## Realistic cases

| # | Case | Result |
| ---: | --- | --- |
| 1 | Deep-doctor the live database | Pass: all checks green |
| 2 | Verify the loopback service is active | Pass |
| 3 | Verify the nightly backup timer is active | Pass |
| 4 | Restore the 503,808-byte pre-slice backup to a new `/tmp` database | Pass in 0.22s |
| 5 | Deep-doctor the restored database | Pass in 0.21s |
| 6 | Overview the sibling-ownership mission | Pass: 5 claims, 5 cues, task flag false |
| 7 | Overview the live-checkout mission | Pass: 4 claims, 4 cues, task flag false |
| 8 | Build the first mission queue | Pass: 5 reviewed claims, receipt `1dd02f8d…` |
| 9 | Build the second mission queue | Pass: 4 reviewed claims, receipt `6340d0fa…` |
| 10 | Review a contested claim in mission one | Pass: 1 cue, receipt `ed42637b…` |
| 11 | Review a contested claim in mission two | Pass: 1 cue, receipt `f6061745…` |
| 12 | Build lineage for mission-one contested claim | Pass: 11 nodes, 17 edges |
| 13 | Build lineage for mission-two contested claim | Pass: 9 nodes, 11 edges |
| 14 | Render mission-one queue page against the live corpus | Pass: HTTP 200, 9,950 bytes |
| 15 | Render mission-two queue page against the live corpus | Pass: HTTP 200, 8,880 bytes |
| 16 | Render both representative claim-review pages | Pass: HTTP 200, 3,946 and 3,340 bytes |
| 17 | Render both representative lineage pages | Pass: HTTP 200, 7,481 and 6,224 bytes |
| 18 | Run source preview and digest-pin focused behavior | Pass in source and CLI tests |
| 19 | Run workbench, source, and CLI focused suites | Pass: 62 tests; ruff and mypy green |

All passing cases used real repository code. Cases 6–17 read the real persistent
corpus. Cases 4–5 wrote only a fresh disposable destination.

## Corrections during measurement

Two initial web probes were invalid harness calls: one passed a `Database`
object where `create_app` requires a path, and one used TestClient's
non-loopback default host, correctly receiving HTTP 400 from Minerva's host
guard. The corrected loopback probe passed all six pages. These were evaluator
errors, not hidden product passes, and are retained here because verification
should expose its own mistakes.

## Findings

- The new overview makes the semantic boundary machine-visible with
  `structural_cues_are_tasks: false`; both real missions preserved it.
- Existing receipts compose cleanly into web views without a new data model or
  write path.
- The corpus is genuine but small. Counts establish use, not external validity.
- Backup existence alone was insufficient evidence; the restore-and-doctor drill
  materially raised confidence.
- D-2 still lacks its prerequisite. Opening it would not improve the weakest
  current pillar.

## Post-evaluation dogfood

The working branch then created live mission
`mis_ecf8bb02986247f18fc1695ba2707146`, imported four reviewed sources with
digest pins, added four exact citations and three supported findings with
explicit uncertainty, and exported a brief with digest
`38139ad6f699836ec7ccc016dc9c7fcb46a320accb82abfc35eb29d5b90a2fe3`.
Post-write deep doctor passed with 3 missions, 17 snapshots, 36 citations,
17 findings, 205 audit events, and 228 material rows reconciled. The snapshot
of this evaluation stored inside that mission remains the earlier immutable
edition by design.

## Limitations and next check

This baseline does not measure time to first evidence, retrieval-to-adoption
rate, repeated recovery variance, accessibility, or deployment behavior. The eleven
gates passed with 1,155 tests at 91.80% coverage; non-author review remains
required. Repeat this
evaluation after deployment or after the live corpus reaches the next material
size, whichever comes first.
