# ADR 0002: Keep sibling systems behind artifact/protocol seams

- Status: Accepted
- Date: 2026-07-22

## Context

Athena may later coordinate work, Icarus may execute approved experiments, Tribunal
may represent a separate approval boundary, and Oracle may preserve source documents
and final artifacts. Vanguard and Warren may also exchange bounded artifacts after
their roles are defined elsewhere. Coupling the evidence core directly to any sibling
repository would make that system's current schema, availability, and trust choices
part of Minerva's foundation.

Minerva needs a useful artifact seam without accidentally claiming orchestration,
execution, approval, publication, authentication, or trust that does not exist.

## Decision

Milestone 1.1 has no live cross-repository integrations. Minerva researches; it does
not execute, approve, orchestrate, or publish. Local export of operator-owned files is
not external publication.

### Canonical research artifact

The existing fixed `research-brief.json` export becomes the single canonical
agent-facing artifact under `minerva.research-brief.v2`; Minerva does not introduce a
parallel packet format. Its contract preserves:

- mission and research questions;
- proposition-only claims and falsification criteria;
- supporting, opposing, contextual, and inconclusive evidence stances;
- exact citation byte locations, quotes, and source SHA-256 digests;
- findings, assumptions, unresolved questions, and uncertainty;
- creator/run provenance and relevant append-only audit references; and
- an explicit machine-readable ownership boundary.

The packet's strict DTO, canonical serializer, parser, and semantic verifier are
independent of SQLite. The export digest is SHA-256 over the compact sorted-key
semantic payload, excluding its envelope to avoid circular hashing. Verification
rejects malformed documents, digest mismatches, unresolved or invalid citations,
broken cross-references, and evidence-valid statuses that lack the required active
citation stances. Open and inconclusive claims remain legitimate research states
rather than verification failures.

### Future sibling artifact exchange

- Minerva owns research questions, claims, source snapshots, evidence, citations,
  uncertainty, findings, and brief synthesis.
- A portable identity/run context is created internally and never trusts arbitrary
  remote actor headers. Athena may coordinate future work, but an adapter must first
  authenticate and map identity at the boundary; Minerva does not become the
  orchestrator.
- A future Icarus seam may accept a versioned experiment request artifact and return
  a versioned result manifest. Results become evidence only after explicit snapshot
  import and citation; execution output is not automatically evidence.
- A future Tribunal approval record may reference a specific packet schema and digest.
  Approval does not reclassify claims, alter evidence stance, or grant Minerva approval
  authority.
- A future Oracle seam may archive versioned source/brief artifacts by digest. Oracle
  is not Minerva's live structured database and Minerva never writes directly into its
  repository in Milestone 1.1.
- Future Vanguard and Warren seams are limited here to bounded, versioned artifact
  exchange. This decision assigns them no workflow behavior, authority, or trust.
- Artifact references bind an artifact `schema_version` and SHA-256 digest. They are
  opaque integrity references, not filesystem paths or URLs for Minerva to dereference.

`api/v1/capabilities` and the versioned JSON packet are the only current
protocol-ready surfaces for future sibling work; neither exchanges artifacts. The
additive `minerva.capabilities.v2` manifest advertises local packet support and the
reviewed optional CLI-only provider-assistance exception while explicitly reporting
sibling exchange, orchestration, experiment execution, approval authority, and a
shared run envelope as unavailable. The provider adapters are not sibling-system
integrations. There is no MCP server, remote actor-header trust, remote authentication,
or multi-user boundary.

### Future shared run envelope

If sibling exchange is approved later, its shared run envelope is a separately
versioned contract outside the research packet and outside the packet's semantic
digest. The candidate envelope contains exactly these protocol concepts:

- `run_id`
- `task_id`
- `actor`
- `capability`
- `scope`
- `artifact_refs`
- `idempotency_key`
- `status`
- `timestamps`
- `model`
- `node`
- `recovery_checkpoint`

These fields support correlation, version negotiation, retry planning, and observation.
They are metadata, not authentication, authority, truth, approval, or a guarantee that
recovery is possible. Packet verification remains necessary, and transport identity
must be authenticated separately before any future adapter maps it into Minerva's
local identity/run context.

## Consequences

The vertical slice remains offline, testable, and independently deployable. A sibling
can eventually verify a portable research packet without reading Minerva's database,
while a packet cannot silently trigger work or imply approval. Later integrations must
handle authentication, replay/idempotency, artifact verification, authorization,
recovery, and version negotiation explicitly rather than reaching into Minerva tables.

## Rejected alternatives

- Importing sibling repository packages: creates release and trust coupling.
- Shared database tables: destroys ownership and migration boundaries.
- Putting run coordination fields inside the research packet: couples immutable
  research meaning to per-execution transport metadata and destabilizes its digest.
- Treating artifact references as paths or URLs: creates an implicit fetch surface and
  crosses the offline boundary.
- Building MCP before the core is proven: exposes an unstable contract and expands the
  attack surface.
