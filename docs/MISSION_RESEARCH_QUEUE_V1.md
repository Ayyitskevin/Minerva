# Mission Research Queue v1: deterministic structural review index

Mission Research Queue v1 is the smallest local, schema-free view that lets an
operator inspect every Claim Review cue across one mission without running a separate
claim command by hand. Despite the product name, it is not a persisted task queue and
does not decide what work is open, actionable, important, assigned, or complete.

The result is a deterministic, complete-or-refuse structural review index. It reads
existing Claim Review state, binds every cue to the exact child review receipt that
produced it, and changes nothing.

## Local surfaces

The installed CLI surface is JSON-only:

```bash
minerva mission queue --db research.db --mission MIS_ID
```

The public local Python surface is:

```python
from minerva.core.db import Database
from minerva.research_queue import MissionResearchQueueService

queue = MissionResearchQueueService(Database("research.db")).build_queue(
    mission_id="mis_...",
)
```

The CLI emits `{"mission_research_queue": <receipt>}` using Minerva's compact,
sorted-key JSON convention. Stable failures use the existing JSON error envelope.
There is no equivalent REST, web, packet, capability-manifest, MCP, or authenticated
external-agent operation.

## Versioned receipt

A successful receipt contains:

- `schema_version: minerva.mission-research-queue.v1`;
- `kind: mission_research_queue`;
- `algorithm: claim-review-cue-aggregation` and `algorithm_version: "1"`;
- `scope: mission_claim_review_cues_v1`;
- `completion_policy: complete_or_refuse`, `complete: true`, and
  `truncated: false`;
- mission identity, title, objective, creator, run, and creation time;
- the pinned Claim Review schema, algorithm, version, and fixed per-claim bounds;
- configured aggregate bounds and measured work;
- canonical ordering labels and explicit non-priority sequence semantics;
- the complete pinned reason catalog and per-code counts;
- one summary for every reviewed mission claim and one item for every cue;
- claim-set, claim-review-set, item-set, and whole-receipt SHA-256 values;
- fixed exclusions, scope and semantic notices, and machine-readable non-effects.

The CLI receipt contains no generated queue ID and no observation time. Recorded
mission, claim, status, and review provenance remain in the payload because they
identify the state that was actually reviewed.

## Exact mission scope

The caller supplies one mission and no claim, question, reason, or status filter. One
`Database.read()` transaction with connection-local `PRAGMA query_only=ON` owns
mission validation, complete claim discovery, all child Claim Review derivations,
integrity verification, bounds, and receipt construction.

Every owner-admitted mission claim is reviewed in `(claim_created_at, claim_id)`
order. An existing mission with no claims succeeds with empty reviewed-claim and item
arrays. Queue v1 never returns only the claims that happened to fit a limit.

The fixed excluded record kinds are:

- `foreign_mission_records`;
- `unrelated_claimless_findings`;
- `lens_candidates`;
- `claim_lineage_topology`;
- `audit_events`;
- `research_runs`;
- `brief_exports`; and
- `reverse_dependents_outside_claim_review_scope`.

Creator and run identifiers may remain attached as provenance, but audit and run rows
do not become queue items. A mission-owned claimless finding may appear only as a
related record ID when the existing Claim Review service admits it through a target
claim's correction impact. It never becomes a queue root. Questions without claims
also produce no invented cue; the scope is explicitly the mission's Claim Review cue
closure, not an assertion that all possible mission research gaps have been modeled.

## Pinned reason catalog

Queue v1 does not invent, score, filter, or summarize away Claim Review reasons. It
pins the exact Claim Review v1 cue catalog in this order:

| Position | Category | Code | Structural meaning |
| ---: | --- | --- | --- |
| 1 | `structural_gap` | `no_active_evidence` | No evidence card in the claim is currently active. |
| 2 | `structural_gap` | `no_active_support` | The active ledger contains no supporting evidence card. |
| 3 | `structural_gap` | `no_active_opposition` | The active ledger contains no opposing evidence card. |
| 4 | `structural_gap` | `status_required_active_stance_missing` | The recorded workflow status no longer has every active stance it requires. |
| 5 | `structural_impact` | `active_stance_contradiction` | The active ledger contains both supporting and opposing evidence. |
| 6 | `structural_impact` | `withdrawn_evidence_history_present` | One or more evidence cards have an append-only withdrawal record. |
| 7 | `structural_impact` | `recorded_status_requirement_unmet` | The recorded status is retained, but its active-evidence requirement is unmet. |
| 8 | `structural_impact` | `live_material_finding_uses_withdrawn_evidence` | An unretracted material finding cites withdrawn evidence and blocks applicable synthesis. |
| 9 | `structural_impact` | `optional_statement_uses_withdrawn_evidence` | An unretracted assumption or unresolved question retains an optional withdrawn citation. |
| 10 | `structural_impact` | `retracted_finding_history_present` | A related finding retraction remains in the append-only history. |
| 11 | `structural_impact` | `live_inference_uses_withdrawn_evidence` | An unretracted adopted inference cites evidence that is no longer active. |
| 12 | `structural_impact` | `retracted_inference_history_present` | A related adopted-inference retraction remains in the append-only history. |
| 13 | `structural_impact` | `promoted_finding_remains_independently_asserted` | A retracted inference's promoted finding remains asserted until separately retracted. |
| 14 | `structural_impact` | `live_inference_remains_after_promoted_finding_retraction` | Retracting a promoted finding does not retract its still-live source inference. |

The receipt's catalog retains these canonical Claim Review explanation strings. An
unknown emitted cue or a missing, duplicate, reordered, recategorized, or differently
explained catalog entry is inconsistent state, not a new Queue v1 policy. An otherwise
self-consistent empty child cue set is retained in its reviewed-claim summary.

## Non-normative item semantics

Every catalog cue becomes one item with:

- deterministic display `sequence` and `kind: structural_review_cue`;
- claim and owning-question identity;
- exact reason code, category, and Claim Review explanation;
- the ordered related record IDs emitted by Claim Review; and
- the exact source `review_receipt_sha256`.

The current Claim Review taxonomy guarantees at least one cue for every claim. If
support or opposition is absent, a structural gap exists; if both are present, the
structural stance-conflict cue exists. Consequently, Queue v1 is not designed to
become empty when research is “done,” and item presence never means unresolved work.
Historical withdrawal and retraction cues also remain after the correction because
the index preserves the complete pinned catalog instead of imposing an unapproved
actionability filter.

An item has no task identifier, score, rank, severity, priority, age policy, owner,
assignee, due date, open/closed status, deferral, resolution, or completion marker. It
does not recommend evidence collection, a status change, or a correction. A human may
inspect the cue and separately decide whether to use an existing audited research or
correction command.

## Reviewed-claim and reason provenance

Every mission claim has a separate reviewed-claim summary containing its display
sequence, claim/question IDs, claim statement, recorded status and version, creation
time, ordered cue codes, item count, and exact Claim Review receipt digest. This binds
claim-set completeness directly rather than asking a consumer to infer which claims
exist from the item array. The assembler retains a self-consistent zero-cue child
review with an empty reason-code tuple and `item_count: 0`. That is a defensive
receipt-completeness rule; the honest current Claim Review v1 derivation still
guarantees at least one cue per claim.

Queue items deliberately do not duplicate evidence quotes, finding/inference text, or
the full child review. The review digest identifies the deterministic Claim Review
receipt that produced the cue, and the operator can run `minerva claim review`
separately for its exact citations and correction details. A digest is not a database
locator or a promise that a later rerun will match after separate research mutations.

Claim Lineage remains separately available through `minerva claim lineage`. Queue v1
does not invoke it or treat status/correction `reason` text as a reason code: the graph
defines provenance topology and recorded rationale, not task actionability.

## Ordering and digests

The receipt records these exact ordering rules:

- `reviewed_claims:claim_created_at_ascending_then_claim_id_ascending`;
- `items:reviewed_claim_order_then_claim_review_cue_catalog_order`; and
- `sequence_semantics: deterministic_display_order_not_priority`.

Equal claim timestamps therefore use the claim ID as a total tie-break. Cue items use
the pinned catalog order, never lexical explanation order, record count, status,
severity, or age. Sequence values expose that canonical presentation and nothing
more.

The subreceipts use compact sorted-key UTF-8 JSON under:

- `minerva.mission-research-queue-claims.v1` for the admitted claim set;
- `minerva.mission-research-queue-claim-reviews.v1` for reviewed-claim summaries and
  their child receipt digests; and
- `minerva.mission-research-queue-items.v1` for the complete ordered cue-item set.

`claim_set_sha256`, `claim_review_set_sha256`, and `item_set_sha256` bind those
corresponding ordered payloads. The claim frame contains sequence, claim/question IDs,
statement, recorded status/version, and claim creation time. The review frame contains
sequence, claim ID, ordered reason codes, item count, and child review digest. The item
frame contains every item field. Each frame also binds the queue algorithm/version,
scope, and mission ID. `queue_receipt_sha256` hashes compact sorted-key UTF-8 JSON for
the whole receipt except that digest field itself. Identical valid inputs against
identical admitted state therefore produce byte-identical service DTOs and CLI JSON.

These hashes establish deterministic self-consistency only. They are not signatures
and do not prove freshness, origin, authenticity, authority, approval, truth,
actionability, priority, completeness outside the named scope, or permission to
disclose mission data.

## Bounds and complete-or-refuse behavior

Queue bounds are aggregate across the entire mission build:

| Bound | Accepted range | Default | What it limits |
| --- | ---: | ---: | --- |
| `max_claims` | 1–200 | 100 | owner-admitted mission claims that must be reviewed |
| `max_items` | 1–2,800 | 1,400 | all pinned cue items |
| `max_evidence_cards` | 1–40,000 | 5,000 | distinct evidence cards verified across target ledgers and admitted correction-citation closure |
| `max_distinct_evidence_quote_bytes` | 1–67,108,864 | 67,108,864 | stored UTF-8 quote bytes across those distinct verified evidence cards |
| `max_affected_records` | 1–100,000 | 10,000 | cumulative affected findings and inferences |
| `max_relationships` | 1–1,000,000 | 50,000 | cumulative citation/lineage relationships inspected by child reviews |
| `max_distinct_snapshot_bytes` | 1–67,108,864 | 67,108,864 | actual bytes of distinct verified snapshots across the queue build |
| `max_output_bytes` | 1–134,217,728 | 67,108,864 | final canonical whole-receipt JSON bytes |
| `max_sqlite_vm_steps` | 1,000–16,000,000 | 8,000,000 | cumulative SQLite virtual-machine work in the one read snapshot |

The CLI exposes these as `--max-claims`, `--max-items`, `--max-evidence-cards`,
`--max-distinct-evidence-quote-bytes`, `--max-affected-records`, `--max-relationships`,
`--max-distinct-snapshot-bytes`, `--max-output-bytes`, and
`--max-sqlite-vm-steps`.

Each child review retains Claim Review v1's fixed maximum of 200 evidence cards, 500
affected records, and 5,000 relationships. Its snapshot-byte bound equals the queue's
distinct-snapshot-byte bound. The queue owns the one cumulative SQLite VM budget;
child reviews cannot reset it. One shared snapshot cache prevents the same referenced
snapshot from silently escaping aggregate distinct-byte accounting. A separate shared
verified-citation cache counts each evidence identifier once across target claim
ledgers and any admitted finding/inference citation closure. Before a child verifies a
new evidence identifier, a metadata-only preflight proves its stored quote byte length
matches the declared half-open span, then its complete new-ID and quote-byte sets must
fit the remaining `max_evidence_cards` and `max_distinct_evidence_quote_bytes` budgets.
Quote text is not returned to Python until that admission succeeds. The fixed 200-card
child ceiling still bounds each target ledger query; it is not incorrectly reduced
when that target card was already verified through an earlier correction closure.

Crossing any aggregate or fixed child ceiling raises
`mission_research_queue_work_limit` and refuses the entire result. It never emits a
bounded prefix, a partial final claim, or a result whose `complete` flag is false.
Invalid bounds raise `mission_research_queue_bounds_invalid`. A malformed or unknown
mission returns `mission_not_found`. Inconsistent cue/review state raises
`mission_research_queue_inconsistent`; existing exact citation or snapshot tamper
errors remain specific where applicable. Legacy databases continue to use the normal
explicit `database_migration_required` contract.

The work receipt's `evidence_card_count` is the number of distinct evidence identifiers
actually verified across the complete admitted queue closure, not the sum of per-claim
target-ledger lengths. `distinct_evidence_quote_bytes` is the exact sum of their stored
UTF-8 quote lengths. The receipt also reports reviewed claims, items, affected findings
and inferences, their combined affected-record count, citation relationships, distinct
snapshot count/bytes, and final canonical output bytes. SQLite VM steps are a control,
not reported deterministic work: the local SQLite version and query plan determine
instruction callbacks.

## Read and semantic boundaries

The queue service receives no identity context, clock, ID factory, writer, audit sink,
exporter, filesystem target, provider adapter, credential loader, network client,
Claim Lineage service, packet builder, or external protocol adapter.

The machine-readable semantic boundary records:

- `read_only: true`, `structural_review_index_only: true`, and
  `current_claim_review_taxonomy_guarantees_a_cue: true`;
- `item_presence_means_action_required: false`,
  `item_presence_means_open_or_unresolved: false`, and
  `item_order_is_priority_or_severity: false`;
- `assigns_work: false` and `records_completion_or_deferral: false`;
- `determines_truth: false`, `calculates_confidence: false`, and
  `recommends_or_alters_claim_status: false`;
- `creates_or_changes_research_state: false`,
  `writes_audit_event_or_export: false`, and
  `modifies_source_or_snapshot_bytes: false`; and
- `invokes_claim_lineage: false`, `invokes_model_provider: false`,
  `invokes_network: false`, and `exposes_external_agent_protocol: false`.

Building the index never:

- determines truth, source quality, logical validity, sufficiency, or confidence;
- recommends, appends, or changes a claim status;
- creates, withdraws, retracts, promotes, adopts, or edits research state;
- creates a persisted queue row, assignment, ownership record, completion marker,
  deferment, resolution, identity, run, or audit event;
- writes an export, file, canonical packet, or capability entry;
- changes source or immutable snapshot bytes;
- invokes Claim Lineage, a model/provider, a provider credential, or a network; or
- exposes an HTTP, web, MCP, Athena, Icarus, or other external-agent protocol.

Rebuilding after a separate audited human mutation may produce different cues and
digests. That is a fresh derived view, not a Queue state transition.

## Verification expectations

Invariant tests should cover the complete pinned cue catalog, claim/cue ordering and
equal-timestamp tie-breaking, every digest framing, empty missions, reviewed-claim
completeness, exact-bound success and one-below refusal, late-claim refusal without a
prefix, one query-only read snapshot, cumulative VM work, shared snapshot verification,
mission and text isolation, claimless-related-record scope, hostile inputs, legacy
migration behavior, zero database/file mutation, and no graph/provider/credential/
network invocation. Installed-wheel tests should import the public package and execute
the public CLI command rather than relying on the source checkout.

Run the fixed synthetic evaluator with:

```bash
uv run python scripts/evaluate_mission_research_queue.py
```

It measures exact claim coverage; reason-label accuracy over a fixed claim-by-14-code
universe; exact cue-entry precision/recall including related record-ID sets; 14/14
reason-code coverage; canonical ordering; claim-set, claim-review-set, item-set, and
whole-receipt digest validity; deterministic bytes; mission isolation against foreign
IDs and text; and `unauthorized_mutation_count`.

Those fixture metrics make no priority, relevance, truth, confidence, severity,
actionability, completion, source-quality, or real-corpus-performance claim. Unit,
CLI, integrity, distribution, installed-wheel, and migration regressions cover the
remaining contract rather than being relabeled as evaluation metrics.

## Authorization and deferred work

The repository owner's 2026-08-08 instruction to continue the accepted dependency
order narrowly accepts this local schema-free read model. It does not authorize a
persisted queue, queue mutation verbs, or later roadmap capabilities.

A durable assign/defer/resolve queue requires its own owner-approved migration and a
day-one correction model. Lens receipt verification/replay and a local review dossier
remain the next proposed read-only dependencies. No migration, index, trust-model
change, packet version, capability entry, external principal, cryptographic identity,
Athena/Icarus adapter, scholarly network adapter, PROV-O/RO-Crate exporter, MCP/API,
Lens-to-evidence bridge, provider runtime, publishing, messaging, or deployment is
accepted by this decision.
