# ADR 0002: Keep sibling systems behind artifact/protocol seams

- Status: Accepted
- Date: 2026-07-22
- Amended: 2026-07-23 (Milestone 1.3 local request/result artifacts)

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

### Offline research request and result artifacts

Milestone 1.3 adds strict `minerva.research-request.v1` as an inert local input
artifact. It binds one Minerva mission and claim, the sole
`complete_claim_ledger` policy, a sorted exact active-citation freshness precondition,
and requested output schema `minerva.research-brief.v2`. It contains no request/run
identity, free text, path, URL, credential, remote actor, authority, approval,
transport, callback, execution, publication, or orchestration field. Its canonical
payload digest establishes self-consistency only.

The installed CLI may verify this artifact without SQLite and may fulfill it against
one local database in one query-only read snapshot. Fulfillment requires the declared
claim to belong to the mission and the supplied active-citation set to equal the
claim's complete active ledger. The resulting claim-scoped v2 packet retains every
stance plus withdrawn, supersession, status, source, finding, uncertainty, audit, and
run closure required by the canonical verifier; unrelated mission entities are
omitted. The packet contract itself is unchanged and carries no request/scope fields.

The fixed local `minerva.research-result.v1` file contains only bounded fulfilled
status, request digest, output schema, and SHA-256 over exact v2 file bytes. It is not
an Athena response, run envelope, publication record, authentication token, approval,
or authority grant. Request fulfillment creates only operator-selected files; it does
not mutate research, audit, identity/run, or export records.

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

`api/v1/capabilities`, the versioned JSON packet, and the inert local request/result
contracts are the only current protocol-ready surfaces for future sibling work; none
exchanges artifacts. The additive `minerva.capabilities.v2` manifest advertises local
packet/request CLI support and the reviewed optional CLI-only provider-assistance
exception while explicitly reporting sibling exchange, orchestration, experiment
execution, approval authority, and a shared run envelope as unavailable. The provider
adapters are not sibling-system integrations. There is no Athena adapter, MCP server,
remote actor-header trust, remote authentication, or multi-user boundary.

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

The vertical slice remains offline, testable, and independently deployable. A future
sibling can construct the reviewed request bytes or verify a portable packet without
reading Minerva's database, while neither artifact can silently trigger work or imply
approval. A claim-scoped packet's selection meaning is established by its request and
result binding, not by new packet fields. Later integrations must handle
authentication, replay/idempotency, artifact verification, authorization, recovery,
and version negotiation explicitly rather than reaching into Minerva tables.

## Rejected alternatives

- Importing sibling repository packages: creates release and trust coupling.
- Shared database tables: destroys ownership and migration boundaries.
- Putting run coordination fields inside the research packet: couples immutable
  research meaning to per-execution transport metadata and destabilizes its digest.
- Putting request/run identity or transport controls inside the local research request:
  turns an inert research selection into an unauthenticated coordination surface.
- Allowing arbitrary evidence subsets: permits a requester to suppress adverse or
  contextual evidence and breaks complete-ledger semantics.
- Treating artifact references as paths or URLs: creates an implicit fetch surface and
  crosses the offline boundary.
- Building MCP before the core is proven: exposes an unstable contract and expands the
  attack surface.
