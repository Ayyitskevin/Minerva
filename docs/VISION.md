# Vision

**Ask carefully. Cite everything.**

Minerva records evidence and uncertainty; it does not manufacture certainty.
That governing rule does not move.

## Product identity

Minerva is a local-first, provenance-first research laboratory for one trusted
OS user and the AI seats that share that user. It owns the path from a research
mission to falsifiable claims, immutable source snapshots, exact byte-span
evidence, labeled findings, and a deterministic brief. Chat is not the record.
An Athena issue is not evidence. A digest is integrity, not authenticity.

## Workspace role (Decision 0, 2026-08-20)

Kevin recorded Decision 0 on 2026-08-20: this season optimizes Minerva as the
fleet's **research-memory**, not as the next identity/protocol project.

Minerva is the append-only place where missions, claims, citations, and
uncertainty live so that agent sessions, Buzz messages, and Athena issues stop
being treated as proof. Sibling systems keep their jobs:

| System | Owns |
| --- | --- |
| Minerva | Research questions, claims, snapshots, evidence, findings, uncertainty, briefs |
| Athena | Operator workspace: issues, docs, run lineage, work coordination |
| Buzz | Live conversation |
| `shared/handoffs/` | Ownership transfer between seats |
| ORACLE | Living technical wiki; may later archive digest-addressed packets |
| Chronos | Trading research and decision-support, with its own provenance grammar |
| Icarus | Execution of approved experiments |
| Vulcan | Local inference gateway |

Minerva does not orchestrate, execute, approve, or publish. Local export of
operator-owned files is not external publication. Loopback is not
authentication. Same-OS-user CLI access to one local database is the existing
trust model; it is not gate D-2.

See [WORKSPACE.md](WORKSPACE.md) for the mickey checkout, database, and seat
loop. Product vocabulary and invariants remain in [PRD.md](PRD.md). Sibling
seams remain in [ADR 0002](adr/0002-system-boundaries.md).

## This season

1. Freeze this identity in-repo without rewriting the PRD or accepted ADRs.
   **Done** (Decision 0, PR #37).
2. Recover the unpublished local Lens/review stack onto current `main` after
   rebase and the eleven repository gates. **Done** (PR #38).
3. Run one persistent local database on mickey, with loopback review, so a
   real mission can accrue evidence. **Running** — see [WORKSPACE.md](WORKSPACE.md).
4. Document how a seat files a snapshot and an evidence card against that
   database. **Done** (WORKSPACE.md live CLI loop; wrapper stays machine-local).
5. Put deterministic review receipts in a concise operator workbench while
   preserving their semantic boundary: cues are not tasks and lineage is not
   truth. **Deployed to mickey at `bfe5a2c`; the owner explicitly overrode the
   non-author review gate.**
6. Establish a dated pillar scorecard, a real-corpus evaluation, and a recovery
   drill before expanding trust boundaries. **Deployed; a formal tagged release
   remains pending.**

## Non-goals this season

These remain gated or deferred. Naming them here does not open them.

- Gate D-2: Athena principals, ed25519 request attribution, and the Athena
  coordination adapter (proposed ADRs 0009 and 0010). Athena cannot yet hold a
  keypair.
- Gate D-3 Icarus experiment exchange, and D-5 a bounded read-only agent
  protocol.
- MCP, remote or Tailscale bind, multi-user authorization, cloud hosting.
- Packet `v3`, a PROV-O/RO-Crate exporter, extra model providers, local-model
  assistance beyond the existing CLI-only surface, vector search, URL fetching.

A signature still attests only to the extent the verifier could not have
produced it. A server-held key attests a deployment, never an agent. That
reading of D-2 is already recorded; this season does not reopen it.

## What does not move

- Snapshots are immutable. Corrections append: withdraw, retract, supersede.
- Claims have workflow states, never a `true` state. Counts are not confidence.
- Model output is labeled inference until a human adopts it. Adoption is
  CLI-only and never automatic.
- CLI, API, and web share one service layer. Adapters do not write SQL.
- Artifact exchange with siblings is versioned files, never shared tables.
- The eleven gates in `AGENTS.md` are the definition of "complete."
