# ADR 0002: Keep Athena, Icarus, and Oracle behind artifact/protocol seams

- Status: Accepted
- Date: 2026-07-22

## Context

Athena may later coordinate missions and identities, Icarus may execute approved
experiments, and Oracle may preserve source documents and final artifacts. Coupling a
new evidence core directly to those repositories would make their current schemas,
availability, and trust choices part of Minerva's foundation.

## Decision

Milestone 1 has no live cross-repository integrations.

- Minerva owns research questions, claims, source snapshots, evidence, citations,
  uncertainty, findings, and brief synthesis.
- A portable identity/run context is created internally and never trusts arbitrary
  remote actor headers. A future Athena adapter must authenticate and map identity at
  the boundary.
- A future Icarus seam may accept a versioned experiment request artifact and return
  a versioned result manifest. Results become evidence only after explicit snapshot
  import and citation; execution output is not automatically evidence.
- A future Oracle seam may archive versioned source/brief artifacts by digest. Oracle
  is not Minerva's live structured database and Minerva never writes directly into its
  repository in Milestone 1.
- `api/v1/capabilities` and versioned JSON brief schemas are the initial protocol
  surfaces. No MCP server is built yet.

## Consequences

The vertical slice remains offline, testable, and independently deployable. Later
integrations must handle authentication, replay/idempotency, artifact verification,
and version negotiation explicitly rather than reaching into Minerva tables.

## Rejected alternatives

- Importing sibling repository packages: creates release and trust coupling.
- Shared database tables: destroys ownership and migration boundaries.
- Building MCP before the core is proven: exposes an unstable contract and expands the
  attack surface.
