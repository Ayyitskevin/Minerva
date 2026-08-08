# Claim Lineage Graph v1

## Decision and purpose

The repository owner's 2026-08-08 continuation accepts one narrow capability:
a local, schema-free, read-only graph of the complete provenance lineage owned by
one existing claim. This acceptance does not authorize a family of graph APIs,
mission-wide traversal, mutation, a new packet version, or an external agent
protocol.

Claim Lineage Graph v1 answers a structural question: *which recorded Minerva
objects and append-only correction relationships make up this claim's provenance?*
It does not answer whether the claim is true, how confident anyone should be, or
what its workflow status should become.

## Public local surfaces

The installed operator command is:

```bash
minerva claim lineage --db research.db --mission MIS_ID --claim CLM_ID
```

The local Python application-service surface is:

```python
from minerva.lineage import ClaimLineageService

result = ClaimLineageService(database).build_graph(
    mission_id="MIS_ID",
    claim_id="CLM_ID",
)
```

The CLI is a parsing and JSON-only presentation adapter. Success emits one compact
`{"claim_lineage": <receipt>}` object; stable failures use the existing JSON error
envelope. Mission/claim resolution, SQL, scope enforcement, integrity checks, bounds,
deterministic ordering, and receipt construction remain in `ClaimLineageService`.
There is no equivalent REST, web, MCP, capability-manifest, packet, or authenticated
external surface.

## Versioned receipt

A successful build returns one compact deterministic receipt with:

- `schema_version: minerva.claim-lineage.v1`;
- `kind: claim_lineage_graph`;
- `algorithm: structural-ledger-lineage` and `algorithm_version: "1"`;
- `scope: claim_owned_closure_v1`;
- `completion_policy: complete_or_refuse`, `complete: true`, and
  `truncated: false`;
- the explicit mission, claim, question, and root-node identities;
- configured bounds and measured work;
- typed node and edge inventories plus per-kind counts;
- `node_set_sha256`, `edge_set_sha256`, `snapshot_set_sha256`, and
  `lineage_receipt_sha256`;
- explicit excluded-record kinds, scope notice, semantic notice, and
  machine-readable semantic non-effects.

The node, edge, and snapshot subreceipts are canonical compact sorted-key JSON
under `minerva.claim-lineage-nodes.v1`, `minerva.claim-lineage-edges.v1`, and
`minerva.claim-lineage-snapshots.v1`. The whole-receipt digest is computed with
its own digest field absent. No generated identifier or observation timestamp is
added, so identical valid inputs against identical database state and bounds
produce byte-identical ordered output.

These hashes prove deterministic receipt self-consistency only. They are not a
signature or proof of origin, authenticity, authority, approval, truth,
freshness after the read snapshot, or permission to disclose local research.

## Complete claim-owned closure

The graph starts from the explicitly named mission and claim. It includes every
record admitted by existing owner rows to this claim-owned closure:

1. the owning question and target claim;
2. the claim's complete append-only status-event chain;
3. every evidence card owned by the claim, including supersession edges and
   every evidence-withdrawal record;
4. every finding owned by the claim, all of its evidence citations, and every
   finding-retraction record;
5. every adopted agent inference owned by the claim, all of its evidence
   citations, every inference-retraction record, and every recorded promotion;
6. each promoted finding connected by a recorded promotion, already included as
   a claim-owned finding; and
7. every immutable snapshot referenced by an included citation, with its source
   metadata and verified snapshot identity.

Corrections remain nodes rather than destructive state changes. Superseded,
withdrawn, and retracted records stay present and connected to their append-only
correction history. Promotion connects an inference to its promotion record and
the human finding created by that promotion; it does not collapse the inference
and finding into one assertion or make their later retractions transitive.

The named scope reports these exact excluded-record kinds:
`sibling_claims`, `claimless_findings`, `unreferenced_snapshots`, `audit_events`,
`research_runs`, `brief_exports`, `lens_candidates`,
`ephemeral_assistance_candidates`, and `reverse_dependents`. In particular,
mission-level claimless findings remain excluded even when they cite target-claim
evidence; sibling claims and unreferenced snapshots do not enter the graph; and
research-run or audit-event nodes remain excluded although recorded creator, run, and
time provenance is attached to the relevant typed node or edge. The graph does not
follow reverse dependents or admit a record only through a foreign owner row.

This is a claim-owned provenance closure, not a mission graph, whole-database
doctor, dependency impact search, or recursive graph query language.

## Typed topology

Nodes use a stable `node_id`, `kind`, lifecycle `state`, and a typed payload.
The v1 kinds are:

| Node kind | Recorded payload |
| --- | --- |
| `question` | mission, question text, and provenance |
| `claim` | mission, question, statement, falsification criterion, and provenance |
| `claim_status_event` | mission, claim, version, recorded status/reason, current marker, and provenance |
| `snapshot` | mission/source identities and metadata, source provenance, snapshot digest/length/encoding/media type/label, and snapshot provenance |
| `evidence` | mission/claim/snapshot identities, exact citation, stance, supersession target, and provenance |
| `evidence_withdrawal` | mission, target evidence, reason, and provenance |
| `finding` | mission/claim, statement, statement kind, current recorded state, uncertainty, and provenance |
| `finding_retraction` | mission, target finding, reason, and provenance |
| `agent_inference` | mission/claim, labeled statement and uncertainty, provider/model request-response provenance, and recorded provenance |
| `agent_inference_retraction` | mission, target inference, reason, and provenance |
| `agent_inference_promotion` | mission, inference, created finding, and provenance |

The v1 edge relations are:

- `question_has_claim`, `claim_has_status_event`, and
  `status_event_precedes`;
- `claim_has_evidence`, `evidence_cites_snapshot`,
  `evidence_supersedes_evidence`, and `evidence_has_withdrawal`;
- `claim_has_finding`, `finding_cites_evidence`, and
  `finding_has_retraction`; and
- `claim_has_agent_inference`, `agent_inference_cites_evidence`,
  `agent_inference_has_retraction`, `agent_inference_has_promotion`, and
  `promotion_created_finding`.

Edges are structural ledger relationships, not causal, logical, probabilistic,
or truth relationships. The receipt assigns no relevance score, confidence,
weight, or recommended traversal priority. Nodes use fixed node-kind order; status
events then order by `(version, id)`, snapshots by `(recorded_at, id)`, and every
other same-kind record by `(recorded_at, id)`. Edges use fixed relation-enum order,
then source and target node ID. This total ordering makes serialization independent of
SQL row order.

## Exact citation and snapshot custody

Every included evidence citation retains:

- mission, claim, evidence, source, and snapshot identity;
- the stored snapshot SHA-256;
- zero-based half-open UTF-8 byte coordinates `[start_byte, end_byte)`;
- exact quote text and exact quoted bytes encoded as base64;
- quote byte length and SHA-256;
- stance, supersession, lifecycle state, and creator/run/time provenance.

Every referenced card is resolved with Minerva's shared exact-citation verifier.
Each distinct referenced snapshot is loaded at most once per build and rechecked
for declared length, actual bytes, SHA-256, UTF-8 validity, ownership, source
metadata, and import provenance. The graph never substitutes normalized text,
page coordinates, search snippets, or a later version of a source. Stored source URL
metadata remains inert and is never dereferenced.

## Bounds and complete-or-refuse behavior

The caller may configure these deterministic bounded positive integers:

| Bound | Accepted range | Default | What it limits |
| --- | ---: | ---: | --- |
| `max_nodes` | 1–2,000 | 1,000 | all typed nodes required by the admitted closure |
| `max_edges` | 1–5,000 | 2,000 | all typed relationships required by the admitted closure |
| `max_citation_bytes` | 1–67,108,864 | 16,777,216 | cumulative exact quoted UTF-8 bytes represented by included evidence |
| `max_snapshot_bytes` | 1–67,108,864 | 16,777,216 | actual bytes of distinct referenced snapshots verified during the build |
| `max_output_bytes` | 1–134,217,728 | 67,108,864 | final canonical whole-receipt JSON bytes |
| `max_sqlite_vm_steps` | 1,000–16,000,000 | 4,000,000 | cumulative SQLite virtual-machine work for the read snapshot |

The CLI exposes the same fields as `--max-nodes`, `--max-edges`,
`--max-citation-bytes`, `--max-snapshot-bytes`, `--max-output-bytes`, and
`--max-sqlite-vm-steps`.

Bounds prevent a plausible-looking prefix. If any node, edge, citation byte,
distinct snapshot byte, canonical output byte, or SQLite-work ceiling would omit
required admitted state, the service raises `claim_lineage_work_limit` and refuses the
entire graph. Invalid bounds raise `claim_lineage_bounds_invalid`; an invalid or
foreign claim scope raises `claim_lineage_scope_invalid`, while an unknown or malformed
mission keeps the existing `mission_not_found` behavior. Inconsistent admitted state
raises `claim_lineage_inconsistent` or the existing citation/snapshot integrity error
as applicable. It never returns a truncated graph and never silently drops a node or
relationship. The work receipt reports node/edge and record-kind counts, dependent
citation edges and included quote bytes, distinct snapshots/bytes, and canonical graph
payload bytes.

The SQLite instruction ceiling is an availability guard tied to the local SQLite
version and query plan, not a portable wall-clock, memory, or successful-build
guarantee. A valid maximum-size graph can still be large, and the trusted local
operator remains responsible for whether its text may be displayed or shared.

## Synthetic evaluation

Run the fixed model-free evaluation with:

```bash
uv run python scripts/evaluate_claim_lineage.py
```

Its independently labeled two-mission, three-claim fixture reports integer parts per
million for typed node/lifecycle precision and recall, owner-link payload precision and
recall, exact edge precision and recall, and citation-byte accuracy. It also checks
byte-identical repeated receipts, mission-and-claim isolation against foreign IDs and
text, and zero database or main-file mutation. The evaluator uses the expected
citation count as its accuracy denominator; a missing evidence node cannot become a
perfect empty result. Broader corruption, bound, provider/network prohibition, legacy
migration, CLI, and installed-wheel behavior remain invariant tests rather than
evaluation metrics.

## Read and semantic boundaries

One `Database.read()` transaction with connection-local `PRAGMA query_only=ON`
owns mission/claim validation, complete closure discovery, integrity resolution,
and receipt construction. The service receives no identity context, clock, ID
factory, writer, audit sink, provider adapter, credential loader, network client,
exporter, queue, or protocol adapter.

Building a graph never:

- determines truth, source quality, logical validity, sufficiency, or confidence;
- recommends, appends, or changes a claim status;
- creates, withdraws, retracts, promotes, adopts, or edits research state;
- creates a mission queue, assignment, completion marker, run, audit event,
  export row, file, or packet;
- changes source or immutable snapshot bytes;
- invokes a model/provider, reads a provider credential, or contacts a network;
  or
- exposes an HTTP, web, MCP, Athena, Icarus, or other external-agent protocol.

A human who identifies a problem in the graph must use the existing separate
audited withdrawal, retraction, status, evidence, finding, adoption, or promotion
workflow. The graph itself has no adoption or correction verb.

## Integrity boundary and deferred work

The complete-or-refuse promise covers records admitted to the named mission and
claim by their stored owner rows. If a same-OS-user attacker first disables
foreign keys or append-only triggers and forges foreign-owner relationships, this
scoped view refuses inconsistent admitted relationships but does not scan every
mission for hidden reverse dependents. `minerva doctor --deep` remains the
whole-database referential and audit-integrity surface. Receipt and snapshot
hashes are not an external integrity anchor against coordinated database rewrite.

No schema migration, index, trust-model change, capability entry, canonical packet
change, cryptographic identity, external principal, Athena/Icarus adapter,
scholarly-source adapter, PROV-O/RO-Crate export, or MCP/API surface is accepted by
this decision. The next proposed dependency is a derived, non-persisted,
human-owned mission research queue built from existing deterministic reason codes;
Lens receipt verification/replay follows it. Each still requires a separate owner
decision, and persistence or external protocol work remains separately gated.
