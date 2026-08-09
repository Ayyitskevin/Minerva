# PROV-O and RO-Crate interoperability decision packet

- Status: **Proposed — design record only; not accepted, not implemented.**
- Date: 2026-08-08
- Decision: **pending explicit owner review.** Acceptance of this design would not
  authorize an exporter, new canonical artifact, packet revision, file writer,
  capability, import path, publication, migration, trust-model change, external
  principal, signature, Athena/Icarus adapter, MCP/API surface, or source-byte
  disclosure.
- Scope: a field-level interoperability mapping and proof plan. Schema v5,
  `minerva.research-brief.v2`, and every accepted trust boundary remain unchanged.

## Decision needed

Minerva can expose useful PROV-O and RO-Crate metadata without weakening its native
record, but only after the owner decides exactly **which Minerva projection is being
mapped**, **which bytes may leave SQLite**, and **what canonical bytes a verifier is
expected to reproduce**.

The proposed direction is:

1. Treat standards output as an additive, derived interoperability view. It never
   replaces Minerva's native schema, exact citation validation, packet v2, correction
   ledger, or audit record.
2. Target the current [RO-Crate 1.3 Recommendation](https://www.researchobject.org/ro-crate/specification/1.3/index.html)
   and [W3C PROV-O Recommendation](https://www.w3.org/TR/prov-o/), supplemented by a
   versioned Minerva profile for semantics those standards do not define.
3. Prove a bounded **claim-owned closure** first. A mission-wide or whole-database
   export is a separate, larger disclosure and completeness decision.
4. Make metadata-only output the default proposal. Attached immutable snapshot bytes
   require a separate explicit disclosure mode and owner authorization.
5. Define deterministic Minerva JSON-LD carrier bytes with explicit identifiers and
   no blank nodes. Do not call those bytes RDF canonicalization. If serialization-
   independent graph digests are later required, decide and bound RDFC-1.0 separately.
6. Preserve withdrawals, retractions, supersession, and promotion as explicit native
   history. Do not erase old entities or mislabel inspectable records as unavailable.

This packet does not accept those recommendations. It makes the forks reviewable and
records the evidence needed for an owner decision.

## Why no existing artifact is a lossless source

"Lossless" is meaningful only relative to a named input projection. No current
Minerva artifact contains every schema-v5 provenance field and immutable source byte:

- `minerva.research-brief.v2` is lossless for its own validated payload, not for a
  mission or database. It intentionally omits source BLOBs, previous claim-status
  events, adopted agent inferences, inference citations/retractions/promotions,
  retracted findings, retraction row identifiers, finding-citation provenance, most
  audit events and audit details, export rows, and migration history. The inference
  omission is an accepted packet-v2 constraint in
  [ADR 0008](adr/0008-persisted-agent-inferences.md).
- [Claim Lineage v1](CLAIM_LINEAGE_V1.md) includes all status events and claim-owned findings, inferences,
  corrections, promotions, typed edges, and exact cited quotes for one claim. It
  intentionally excludes mission-wide audit/run closure, claimless and sibling-claim
  records, unreferenced snapshots, export records, and full snapshot BLOBs.
- [Review Dossier v1](REVIEW_DOSSIER_V1.md) composes Queue, one focal Review, focal Lineage, and one captured
  Lens receipt in a current SQLite snapshot. It is an ephemeral review view, not a
  mission export, and intentionally creates no durable artifact or audit event.
- SQLite schema v5 is the only complete structured record. Even it does not retain
  historical brief file bytes or make external-source authenticity claims; export
  rows retain digests, not the old files.

Accordingly, an implementation must use one of these precise claims:

| Claim | Honest meaning | What it does not prove |
|---|---|---|
| Packet-projection faithful | The profile can reconstruct the complete validated packet-v2 payload | Full schema-v5 provenance, source-byte custody, or omitted correction/inference history |
| Structured-closure faithful | The profile can reconstruct every declared database field and relation in one bounded scope | Bytes deliberately excluded by its disclosure mode or records outside its declared scope |
| Byte-custody complete | Structured-closure faithful, with every included snapshot BLOB reproduced exactly and checked against its stored SHA-256 and byte length | Authenticity of the external source, identity, authority, approval, truth, or disclosure permission |

No document, CLI help, capability, or success report may shorten one of these claims to
"lossless export" without naming its scope and byte-disclosure mode.

## Standards truth

### RO-Crate 1.3

RO-Crate 1.3 was published on 2026-06-22 as the current Recommendation. Its versioned
permalink is `https://w3id.org/ro/crate/1.3`, and its context is
`https://w3id.org/ro/crate/1.3/context`. The metadata document is UTF-8 JSON-LD with a
flat graph, a metadata descriptor, and a root `Dataset`. The descriptor identifies
base-version conformance; a profile is declared on the root entity. The root requires
an ISO-8601 `datePublished`; it also recommends a license statement, which Minerva
does not currently model for missions or imported sources. See the official sections on
[metadata](https://www.researchobject.org/ro-crate/specification/1.3/metadata),
[the root data entity](https://www.researchobject.org/ro-crate/specification/1.3/root-data-entity.html),
[profiles](https://www.researchobject.org/ro-crate/specification/1.3/profiles.html), and
[JSON-LD](https://www.researchobject.org/ro-crate/specification/1.3/appendix/jsonld.html).

RO-Crate graph order is not semantic, and equivalent contexts can produce the same RDF
graph from different JSON bytes. RO-Crate therefore does not define Minerva's byte-
canonical serialization. It also explicitly does not require an exhaustive file or
fixity manifest.

An attached RO-Crate `File` with a relative identifier promises that the file is
present in the crate. A detached crate requires file data entities to be web-based.
Minerva has no authorized publication URL, so metadata-only snapshot nodes must not be
misrepresented as downloadable or attached `File` entities. `url_metadata` remains an
inert captured string, never a retrieval instruction, identity, `contentUrl`, or
`sameAs`. See [RO-Crate data entities](https://www.researchobject.org/ro-crate/specification/1.3/data-entities.html).

### PROV-O

PROV-O supplies `Entity`, `Activity`, and `Agent`, plus derivation, usage,
generation, attribution, association, quotation, revision, and qualified relations.
Its `prov:wasQuotedFrom` and qualified quotation pattern are a useful standards hook
for a distinct quoted-span entity. PROV-O does not define UTF-8 byte selectors,
Minerva's evidence stance, status validity, correction rules, inference labels,
review-cue semantics, or deterministic receipt fields.

PROV invalidation means an entity becomes unavailable after invalidation. Minerva's
withdrawn evidence, retracted findings, and retracted inferences remain immutable and
inspectable, so directly mapping them to `prov:wasInvalidatedBy` would state the wrong
thing. Likewise, `prov:wasRevisionOf` is appropriate only for a real derived revision;
an evidence supersession link does not itself deactivate or rewrite the earlier card.

PROV provenance is not inherently authoritative or correct. Trust and signatures are
separate concerns, as the W3C [PROV-AQ security discussion](https://www.w3.org/TR/prov-aq/#interpreting-provenance-records)
also makes explicit.

### RDF canonicalization

The W3C [RDFC-1.0 Recommendation](https://www.w3.org/TR/rdf-canon/) produces canonical
N-Quads for isomorphic RDF datasets. It is different from sorted-key JSON bytes. Its
security section warns that adversarial blank-node graphs can consume unreasonable
time and recommends configurable time or iteration limits.

The first Minerva mapping should avoid blank nodes entirely and should not claim an
RDF graph digest. If an owner later requires representation-independent graph equality,
RDFC-1.0 needs a pinned implementation, exact algorithm/hash identifiers, official
test vectors, schema validation, size/node/edge/depth/iteration/time ceilings, and
fail-closed poisoning tests.

## Proposed profile architecture

### Two non-interchangeable layers

1. **RO-Crate/PROV semantic graph.** A standards-compatible flat JSON-LD graph with
   explicit identifiers and a versioned Minerva profile for custom semantics.
2. **Deterministic Minerva carrier.** One exact UTF-8 JSON representation with fixed
   key ordering, node ordering, array ordering, scalar encodings, newline rule,
   algorithm version, context digest, profile digest, and an explicitly framed
   carrier SHA-256. The owner must choose whether the digest excludes one in-document
   field or lives in a detached receipt; a digest cannot recursively cover itself.

The carrier digest establishes self-consistency of those exact bytes. It does not
establish RDF isomorphism across alternative serializations, origin, authenticity,
signature, human identity, authority, approval, freshness, truth, research quality,
or disclosure permission.

Every graph node and qualified relationship should have an explicit deterministic
identifier. Blank nodes are forbidden. Two snapshot registrations with the same
content digest remain two distinct provenance entities; digest equality never dedupes
registration history.

### Context and profile

The output must use the exact RO-Crate 1.3 context semantics without making a runtime
network request. The safe implementation design is an owner-reviewed, pinned context
copy or exact by-value context with a recorded SHA-256, a deny-all JSON-LD document
loader, and descriptor `conformsTo` set to the 1.3 permalink. A future parser may
accept the exact 1.3 context URI only when it resolves from the pinned local copy;
every other remote `@context`, `@import`, unexpected `@base`/`@vocab`, and arbitrary
extension context is refused.

Minerva-specific terms require a durable HTTPS vocabulary and a resolvable, versioned
profile URI. No such public namespace exists today. Until the owner approves and
publishes one, output must not claim conformance to a Minerva RO-Crate profile. A
placeholder namespace would turn a deterministic artifact into a misleading public
contract and is rejected.

Any future conformance proof must pin the complete crate scaffold, not merely the
domain nodes:

- exactly one metadata descriptor with `@id` equal to `ro-crate-metadata.json`,
  `@type` equal to `CreativeWork`, `about` pointing to the distinct projection root,
  and descriptor `conformsTo` pointing to the RO-Crate 1.3 permalink;
- exactly one projection root whose `@type` includes `Dataset`, with the required
  `datePublished` and the owner-approved handling of recommended name, description,
  and license metadata;
- if the root declares conformance to a Minerva profile, a matching contextual entity
  whose `@id` is that exact profile URI and whose `@type` includes `Profile`; and
- one unique `@id` and an `@type` for every graph entity, explicit `{"@id": ...}`
  references, and declared reachability from the root.

The RO-Crate specification is Apache-2.0 licensed, while its JSON-LD context and
examples are offered under CC0. Whether Minerva vendors those bytes or publishes a
profile/context is nevertheless a legal/public-facing repository decision and is
outside this packet's authorization.

### Stable publication time

RO-Crate requires root `datePublished`, while deterministic Minerva receipts do not
invent an observation timestamp. Mission creation, source import, and last audit time
are not crate publication time and must not be repurposed.

Recommendation: require an explicit, validated `published_at` input for a future
export and bind it into the configuration and receipt. Repeating the export with the
same database snapshot and explicit inputs then remains byte-identical. Whether an
export operation also persists/audits that time is a separate owner decision.

## Proposed field mapping

This table names the minimum mapping obligations. PROV-O and Schema.org terms are
secondary interoperability hooks; the versioned Minerva terms are the lossless source
of native semantics.

| Minerva record | Standards hook | Required Minerva semantics and caveats |
|---|---|---|
| Interoperability projection | RO root `Dataset`, optionally `prov:Collection` | A distinct immutable description of this crate's declared scope, configuration, members, omissions, disclosure mode, and receipt; it is not the live Mission |
| Mission | `CreativeWork`, `prov:Entity` | Native ID, title, objective, creator/run/time, and a link from the projection; a claim-owned crate must not imply that it contains every mission record |
| Research question | `CreativeWork`, `prov:Entity` | Native ID, exact question text, mission membership, creator/run/time |
| Claim | `CreativeWork`, `prov:Entity` | Native ID, exact statement and falsification criteria, question link; status is recorded state, never truth |
| Claim-status event | explicitly identified `prov:Entity` and custom status-event relation | Preserve every event ID, version, status, reason, actor/run/time, and total order; never collapse to current status |
| Research run | `prov:Activity` | Native ID, purpose, local actor ID/kind, created time; absence of end/status remains explicit |
| Local actor | optionally `prov:Agent` under a local-attribution profile | Never `prov:Person`, global identity, authenticated principal, or `sameAs`; record local OS attribution assurance explicitly |
| Logical source | `prov:Entity` or `CreativeWork` | Source kind, label, inert URL metadata, registration provenance; do not turn metadata into a network locator or infer the epistemic `prov:hadPrimarySource` relation |
| Immutable snapshot, metadata mode | `prov:Entity` plus Minerva Snapshot type | Source registration, SHA-256, byte length, UTF-8 encoding, media type, label, import provenance; not an RO `File` when bytes are absent |
| Immutable snapshot, attached mode | RO `File`, `prov:Entity` | All metadata above plus exact packaged bytes at the declared relative path; verify content length and SHA-256 before and after writing |
| Evidence card | `prov:Entity` plus Minerva Evidence type | Claim/snapshot IDs, stored snapshot digest, exact half-open UTF-8 start/end, quote text, quote Base64/SHA-256/length, stance, supersedes ID, creator/run/time |
| Quoted span relation | `prov:wasQuotedFrom` plus identified `prov:Quotation` | Quote entity points to snapshot; qualified relation retains exact byte selector and native evidence semantics |
| Evidence withdrawal | identified correction entity/activity | Withdrawal ID, target, reason, actor/run/time; custom `withdraws` relation; do not invalidate or remove the immutable record |
| Finding/assumption/unresolved question | `CreativeWork`, `prov:Entity` | Native type, nullable claim, statement, status, uncertainty, creator/run/time; status is not confidence or truth |
| Finding citation | identified qualified relation | Preserve join actor/run/time and cited evidence ID; generic derivation alone loses native provenance |
| Finding retraction | identified correction entity/activity | Retraction ID, target, reason, actor/run/time; custom relation; retained history remains reachable |
| Adopted agent inference | Minerva AgentInference `prov:Entity` | Never a `prov:Agent`; preserve statement, uncertainty, claim, provider/model literals, request/response digests, candidate index, prompt version, adopter/run/time |
| Inference citation | identified qualified relation | Preserve evidence IDs and join provenance; inference remains non-evidence |
| Inference retraction | identified correction entity/activity | Retraction ID, target, reason, actor/run/time; retained history remains reachable |
| Inference promotion | `prov:Activity` plus Minerva Promotion type | Uses inference, generates the separately asserted finding, retains promotion actor/run/time; each side retracts independently |
| Audit event | `prov:Activity` plus Minerva AuditEvent type | ID, monotonic sequence, event/entity type and ID, mission, actor, run, timestamp, canonical details; no transaction ID exists |
| Brief export row | export `prov:Activity` and artifact entities | Schema and semantic/file digests plus provenance; historical paths and file bytes are not reconstructible from the row |
| Migration row | Minerva ledger entity/activity | Version, name, SQL checksum, applied time; normally outside a claim-scoped disclosure |
| Lens receipt/candidate | search `prov:Activity`, plan and result entities | Preserve normalized query, algorithm/Unicode/bounds/filter/corpus/set receipt, score/rank/omissions, exact candidate span, and candidate-only semantic boundary; no timestamp/identity invented |
| Queue, Review, Lineage, Dossier | derived collection/view entities | Preserve their exact scope, completeness, work bounds, digests, omissions, and semantic non-effects; never promote cues, edges, or candidate grouping into truth/evidence/task semantics |

The mapping must preserve exact native identifiers as literals even if a deterministic
IRI is also emitted. IRI namespace and cross-database collision policy remain an owner
choice; an unregistered or unowned namespace must not be presented as durable.
Stored timestamp text must likewise survive exactly. It may receive an `xsd:dateTime`
type only after lexical validation, and `created_at`, `imported_at`, `occurred_at`, and
crate publication time must never be silently conflated.
Lens, Queue, Review, Lineage, and Dossier receipts are future profile extensions and
are not part of the recommended first claim-owned proof.

## Proposed first proof scope

Recommendation: prove one **claim-owned structured closure** before attempting a
mission-wide crate. The declared scope would include:

- the mission scope record, focal question, focal claim, and complete claim-status
  chain;
- every evidence card for the claim, all their source registrations and immutable
  snapshot metadata, and all evidence withdrawals/supersession links;
- every claim-owned finding and adopted inference, including all citation joins,
  retractions, promotions, and promoted findings needed for referential closure;
- all referenced research runs and locally scoped actor identifiers;
- a precisely defined subset of audit rows that names included entities, plus any
  additional rows required for referential closure;
- the projection configuration, disclosure mode, counts, omissions/exclusions,
  schema/profile/context/algorithm versions, and deterministic receipt.

It would explicitly exclude sibling claims, unrelated mission records, claimless
findings, unreferenced snapshots, backups, credentials, provider prompts/responses,
external files, and unrelated audit rows. Those exclusions make this a claim-owned
closure, not a mission provenance export. The exact audit-closure rule must be fixed
before implementation; a vague "relevant audit" filter is not reproducible.

Packet-v2-to-JSON-LD can be a separate database-free compatibility proof, but its
success report must say `packet_projection_faithful`, never `mission_lossless`.

## Disclosure modes

### Metadata-only — recommended default

Includes exact structured fields, digests, citation quotes/coordinates, correction
history, and the explicit omission `snapshot_payloads_included=false`. Snapshot nodes
are contextual provenance entities, not promised files. This mode cannot independently
revalidate a citation against the full immutable source bytes.

The owner must decide whether exact quotes, source labels, inert URL metadata, local
actor IDs, provider/model names, request/response digests, audit details, and migration
metadata are permitted. A redaction that removes a declared field is a different,
versioned projection—not a "lossless" mode.

### Attached snapshot bytes — separately gated

Packages each included immutable snapshot BLOB exactly once per registration, even
when multiple registrations share a digest. The metadata path, byte length, and
SHA-256 must round-trip. Citation verification must prove
`snapshot[start_byte:end_byte] == quote.encode("utf-8")` for multibyte content.

This mode materially discloses imported sources and may implicate privacy, licensing,
copyright, and repository-size policy. This packet does not authorize it. A safe writer
also needs staged output, no-follow path handling, exclusive publication, fsync/crash
semantics, remnant reporting, and an exact archive/manifest decision.

## Security and trust boundary

A future verifier/exporter must remain local, model-free, provider-free, credential-
free, and network-denied. It must never dereference JSON-LD contexts, profile IRIs,
entity IRIs, source URL metadata, `contentUrl`, or `sameAs`. Input and output are
bounded before expensive parsing, graph expansion, hashing, canonicalization, or byte
materialization.

Minimum refusal classes include duplicate JSON keys, non-finite numbers, invalid
UTF-8, unsupported schema/profile/context/algorithm versions, unexpected fields,
unknown relations, dangling or cross-mission identifiers, duplicate IRIs, blank nodes,
remote contexts/imports/bases, malformed date/time values, digest/length/span mismatch,
overlapping or invalid source paths, output-limit exhaustion, and any incomplete
declared closure.

Provider and model strings are captured literals, not verified software identities.
Local actor IDs are OS-account attribution already inside Minerva's trust boundary,
not cryptographic persons or external principals. A standards graph and its SHA-256
remain attackable self-asserted provenance. Nothing here opens D-2 or supplies a
signature.

## Determinism and proof obligations

Before an exporter can be proposed for acceptance, a proof implementation must pass:

1. Field-by-field mapping coverage for every record and enum in the declared scope,
   with an independently maintained inverse mapping test.
2. Exact inverse equality for all structured native fields, including IDs, timestamps,
   empty/null distinctions, correction history, relationship provenance, and duplicate-
   digest snapshot registrations.
3. Multibyte UTF-8 source fixtures proving exact half-open byte spans, quote text,
   Base64, byte length, and SHA-256; attached mode additionally proves full BLOB
   round-trip.
4. All evidence stances, claim/finding statuses, statement kinds, withdrawals,
   supersession, finding/inference retractions, inference promotion, and independent
   post-promotion correction states.
5. Fixed cross-runtime golden carrier bytes, insertion-order independence, unique
   explicit IRIs, complete descriptor/root/profile scaffolding, referential closure,
   declared root reachability, and no blank nodes.
6. Exact pinned context/profile checksums and a deny-all loader proving zero network,
   provider, credential, subprocess, plugin, or publication invocation.
7. Hostile JSON-LD and canonicalization bounds: bytes, nodes, edges, fields, depth,
   fanout, literal length, work steps, and output bytes; any future RDFC path also needs
   poisoning time/iteration limits.
8. Mission/claim isolation and metadata-only sentinel tests proving excluded source
   bytes, foreign text, sensitive fields, and unrelated audit details do not leak.
9. Query-only snapshot consistency, byte-identical repeated output, and exact zero
   mutation of research state, snapshots, audit state, packet v2, capability manifests,
   and unrelated files.
10. Fresh-wheel/off-checkout verification if any CLI or Python surface becomes public,
    plus unchanged schema-v5 migration/legacy refusal behavior.

An evaluator may report structural mapping coverage, inverse-field accuracy, citation
byte accuracy, deterministic equality, isolation, disclosure-mode compliance, and zero
mutation. It may not report provenance authenticity, truth, confidence, evidence
quality, authority, legal permission, or research completeness.

## Owner decisions

The following must be resolved explicitly before implementation:

1. **First projection:** packet-v2 projection, claim-owned schema-v5 closure, mission
   closure, or whole database? Recommendation: claim-owned closure, with a separate
   packet-projection compatibility test.
2. **Source payload:** metadata-only, attached snapshot bytes, or both as separately
   versioned modes? Recommendation: metadata-only default; attached bytes require an
   explicit per-export disclosure choice and separate writer review.
3. **Profile namespace:** which owner-controlled HTTPS vocabulary/profile URI is
   durable, resolvable, versioned, and publishable? This is currently unmet.
4. **Context custody:** vendor/embed the exact RO-Crate 1.3 context or use full IRIs
   with a pinned local validator? Runtime network resolution is not an option.
5. **Canonicalization and digest placement:** deterministic Minerva JSON-LD carrier
   only, or also an RDFC-1.0 graph digest; in-document digest with one fixed exclusion,
   or detached receipt? Recommendation: carrier only with a framed detached receipt in
   the first slice. Explicit IDs/no blank nodes preserve deterministic graph
   construction without adding an expensive second integrity contract.
6. **Publication time:** require an explicit `published_at` input, persist an export
   event, or choose another semantically correct source? Recommendation: explicit
   input; never wall-clock default or reused mission/import time.
7. **License statement:** what, if anything, can the crate say about reuse of its
   metadata and included records? Minerva stores no mission/source rights model, and
   must not invent a license or imply a grant.
8. **IRI policy:** exact deterministic native-ID mapping, database namespace, relation
   node identifiers, and stability across copied/restored databases.
9. **Correction semantics:** custom Minerva correction relations only, or narrowly
   typed PROV assertion-state specializations? Recommendation: custom relations in v1;
   never invalidate the retained underlying record.
10. **Identity representation:** whether local actor IDs appear as scoped `prov:Agent`
   nodes or literals only. Recommendation: scoped agents with an explicit
   `local_os_attribution` assurance, never Person/SoftwareAgent/sameAs/authentication.
11. **Disclosure fields:** exact policy for quotes, labels, URL metadata, actor IDs,
    provider/model literals, request/response digests, audit details, migration data,
    and existing receipt contents.
12. **Artifact lifecycle:** stdout-only preview, safe immutable file, attached directory,
    or archive; whether export must create an audit event and durable export ledger.
    Existing `brief_exports` cannot honestly represent a new crate artifact.
13. **Acceptance boundary:** whether approving this mapping only accepts terminology,
    or authorizes a separately reviewed proof implementation. Recommendation: mapping
    acceptance alone authorizes no exporter.

## Consequences if the mapping is later accepted

- Minerva gains a precise standards vocabulary without weakening native semantics or
  changing packet v2.
- A future implementation still needs its own owner-reviewed contract, threat-model
  update, public profile decision, deterministic fixture, and full repository gates.
- Claim-scoped output improves interoperability but is intentionally not a complete
  mission record. Mission-wide output remains a later disclosure and work-bounding
  problem.
- Metadata-only output is portable structured provenance but not independent source-
  byte custody. Attached mode is the only proposed route to full citation revalidation
  away from the database.
- No standards mapping can turn recorded provenance into authenticity, truth, approval,
  or authority. Cryptographic identity and signatures remain behind their existing
  gates.

## Rejected shortcuts

- **Call packet v2 a lossless mission export.** It deliberately omits schema-v5 history
  and source bytes.
- **Wrap Lineage or Dossier and call it complete.** Both have narrower declared scopes
  and omit full snapshot bytes and audit/run closure.
- **Use base PROV-O/RO-Crate terms only.** They cannot represent Minerva's exact byte,
  stance, correction, inference, and receipt semantics.
- **Map withdrawal/retraction to entity deletion or unconditional PROV invalidation.**
  The native record remains available and inspectable.
- **Treat evidence supersession as automatic revision/invalidation.** Supersession does
  not deactivate the earlier card; withdrawal is separate.
- **Treat a registered source as `prov:hadPrimarySource`.** Minerva records custody and
  submitted metadata, not the epistemic claim that a source has direct knowledge.
- **Use the live web context at runtime.** It violates local/offline determinism and
  makes term resolution mutable outside the artifact.
- **Invent a Minerva profile URL or publish one implicitly.** Namespace ownership and
  publication are owner decisions.
- **Use generated wall-clock time for `datePublished`.** Hidden time makes identical
  inputs produce different bytes and can misstate publication provenance.
- **Hash sorted JSON and call it canonical RDF.** JSON carrier equality and RDF graph
  isomorphism are different contracts.
- **Use blank nodes and hope JSON order is enough.** It makes cross-serializer identity
  ambiguous and opens unnecessary canonicalization work/poisoning risk.
- **Map local actor/provider strings to authenticated Persons or SoftwareAgents.** The
  stored data does not establish those identities.
- **Emit attached source bytes by default.** It silently expands disclosure and legal
  risk beyond the accepted local trust boundary.

## Decision checkpoint

Until the owner resolves the choices above, this packet is the terminal dependency for
standards interoperability. The repository may refine documentation and test designs,
but must not add a canonical exporter, profile claim, context asset, new artifact,
source-byte writer, capability, audit event, migration, packet v3 field, or external
protocol on the strength of this proposal alone.
