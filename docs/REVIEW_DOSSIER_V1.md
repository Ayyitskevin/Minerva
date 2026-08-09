# Review Dossier v1

## Purpose

Review Dossier v1 composes Minerva's existing deterministic review surfaces into one
current-state, query-only reading of a mission and focal claim. It is intended for the
trusted local operator who has already captured a Lens search receipt and wants the
mission queue, the queue's exact focal Claim Review, the focal Claim Lineage graph,
and that Lens search reproduced and cross-checked together.

The dossier is a review receipt, not research state. It does not infer a Lens query
from claim text, assess a candidate against the claim, convert a queue cue into work,
or turn a candidate into evidence. Correction and evidence adoption remain separate,
explicit, human-attributed, audited operations.

## Accepted surface

The repository owner's 2026-08-08 instruction to continue the dependency-ordered
plan narrowly accepts this schema-free local read surface:

```bash
minerva dossier build --db research.db --mission MIS_ID --claim CLM_ID \
  --lens-input lens-receipt.json
```

The CLI emits one compact, sorted-key JSON envelope:

```json
{"review_dossier":{"schema_version":"minerva.review-dossier.v1"}}
```

The corresponding local Python application-service surface is:

```python
ReviewDossierService(database).build_dossier(
    mission_id=mission_id,
    claim_id=claim_id,
    lens_receipt=lens_receipt,
    bounds=bounds,
)
```

The service accepts a typed `LensSearchResult`; the CLI alone reads the file through
the existing captured-Lens-receipt loader. There is no dossier file writer, canonical
export, REST or web route, capability-manifest entry, MCP tool, or authenticated
external/agent-facing interface.

## Why the input is a captured Lens receipt

The captured receipt preserves the operator's explicit query, normalized token
sequence, corpus filters, deterministic bounds, omissions, candidates, and receipt
digest. A fresh live query inside the dossier would discard the prior review event's
exact binding and make Lens receipt verification/reproduction an unnecessary
dependency. Deriving a query from the focal claim would additionally create an
unapproved semantic relationship.

The ordinary captured CLI file is still neither trusted nor canonical. The existing
safe file reader and strict Lens parser verify it before the dossier database is
opened. Its mission must equal the explicitly supplied mission. The verified request
is then reproduced through the normal Lens search/integrity path inside the same
current SQLite read snapshot as every other component. Exact equality is required.
This establishes deterministic self-consistency and equality to one current database
read only; it does not establish the receipt's origin, author, authority, approval,
historical freshness, truth, evidence quality, or disclosure permission.

## Versioned contract

| Field | Value |
| --- | --- |
| Schema | `minerva.review-dossier.v1` |
| Component-set schema | `minerva.review-dossier-components.v1` |
| Kind | `review_dossier` |
| Algorithm | `current-snapshot-review-composition` |
| Algorithm version | `1` |
| Scope | `mission_claim_with_captured_lens_v1` |
| Completion policy | `complete_or_refuse` |

Success always records `complete: true` and `truncated: false`. The embedded Lens
search may independently be bounded and truncated; its exact state is preserved in
both `lens_search.truncated` and `lens_retrieval_truncated`. Dossier completeness
means all five declared components and all required cross-checks are present, not that
Lens searched an unbounded mission corpus.

No generated dossier ID or observation timestamp is added. Repeating the same valid
request against the same database state with the same runtime produces byte-identical
canonical JSON.

## Components

The fixed `component_order` is:

1. `mission_research_queue`
2. `claim_review`
3. `claim_lineage`
4. `lens_search`
5. `lens_replay`

The result embeds the complete existing DTO for each component:

- the complete mission-wide `minerva.mission-research-queue.v1` receipt;
- the exact focal `minerva.claim-review.v1` receipt retained while that queue is
  built, rather than a second independently derived review;
- the complete focal `minerva.claim-lineage.v1` graph;
- the verified captured `minerva.lens-search.v1` receipt; and
- the `minerva.lens-replay.v1` exact-current-database reproduction report.

The queue remains mission-wide. The Claim Review and Lineage components remain
claim-scoped. The Lens component remains mission-scoped according to the operator's
captured filters and bounds. Composition does not broaden any child scope.

## One current database snapshot

After the Lens receipt passes standalone verification, `ReviewDossierService` opens
one `Database.read()` transaction and enables connection-local `query_only`. In fixed
order it:

1. exactly reproduces the captured Lens receipt, failing early on corpus or result
   drift;
2. builds the complete Mission Research Queue and retains the focal review already
   produced by that queue; and
3. builds the focal Claim Lineage graph.

Package-private connection-bound seams let these established services reuse the
caller's connection. They do not define new public search, queue, review, or graph
contracts. A single cumulative SQLite progress handler covers the complete
composition; child services leave it installed. The queue and lineage
`max_sqlite_vm_steps` values must equal the dossier's global value so an embedded
receipt never advertises a smaller limit that the composition did not enforce.

This is an atomic read in the SQLite consistency sense only. It is not a write
transaction, persisted run, audit event, historical checkpoint, or durable artifact.

## Required cross-checks

Every boolean in `cross_checks` must be true or the entire operation refuses with
`review_dossier_inconsistent`:

- `component_missions_match`: Queue, Review, Lineage, Lens, and the request name the
  same mission.
- `focal_claim_is_reviewed_once`: exactly one queue summary names the requested focal
  claim; that identifier also equals the retained Review claim, the Lineage claim and
  root, and the sole Lineage Claim node. Its question, statement, current
  status/version, and creation time match the retained Review.
- `focal_question_matches`: Queue, Review, and Lineage agree on the owning question.
- `queue_review_receipt_matches`: the queue summary digest equals the recomputed focal
  Claim Review digest.
- `queue_review_cues_match`: the queue's focal cue items exactly preserve the Review
  cue order, codes, categories, explanations, related record IDs, and source digest.
- `review_lineage_claim_matches`: the requested, Review, Lineage, root, and Claim-node
  identifiers agree, and claim text, falsification criterion, ownership, and
  creator/run/time provenance agree between Review and Lineage.
- `review_lineage_status_matches`: the Review status agrees with the one current
  Lineage status-event payload and its recorded reason and provenance.
- `review_lineage_evidence_matches`: every focal evidence card, exact byte-span
  metadata, stance, supersession, withdrawal, source, snapshot, and provenance value
  agrees across Review and Lineage, and their focal evidence identifier sets match.
- `review_lineage_owned_records_match`: every claim-owned finding or inference that
  Claim Review reports as affected agrees with its corresponding Lineage payload and
  provenance, exact citation set, and retraction record; inference agreement also
  covers its promotion record/provenance and the promoted finding's current retracted
  state. This is intentionally the Review-reported affected subset. Lineage may retain
  additional claim-owned records that Review does not report because they are
  unaffected.
- `shared_snapshot_identities_match`: whenever a searched Lens snapshot is also in
  the claim-owned graph, source, snapshot digest, length, media type, and label agree.
  Disjoint snapshot sets are allowed and make no relevance claim.
- `lens_current_database_exact_match`: the replay report confirms exact whole-receipt
  equality to the current read and binds the captured retrieval receipt digest.

These checks reconcile duplicated structural facts; they do not prove semantic
entailment, contradiction, causality, relevance, source quality, or truth.

## Bounds and work accounting

The default `ReviewDossierBounds` embeds the normal Queue and Lineage bounds, with one
shared SQLite limit:

| Bound | Default |
| --- | ---: |
| Queue claims | 100 |
| Queue items | 1,400 |
| Queue evidence cards | 5,000 |
| Queue distinct evidence quote bytes | 67,108,864 |
| Queue affected records | 10,000 |
| Queue relationships | 50,000 |
| Queue distinct snapshot bytes | 67,108,864 |
| Queue canonical output bytes | 67,108,864 |
| Lineage nodes | 1,000 |
| Lineage edges | 2,000 |
| Lineage citation bytes | 16,777,216 |
| Lineage distinct snapshot bytes | 16,777,216 |
| Lineage canonical output bytes | 67,108,864 |
| Complete dossier canonical output bytes | 134,217,728 |
| Cumulative SQLite VM steps | 4,000,000 |

The CLI exposes these as `--queue-max-claims`, `--queue-max-items`,
`--queue-max-evidence-cards`, `--queue-max-distinct-evidence-quote-bytes`,
`--queue-max-affected-records`, `--queue-max-relationships`,
`--queue-max-distinct-snapshot-bytes`, `--queue-max-output-bytes`,
`--lineage-max-nodes`, `--lineage-max-edges`,
`--lineage-max-citation-bytes`, `--lineage-max-snapshot-bytes`,
`--lineage-max-output-bytes`, `--max-output-bytes`, and
`--max-sqlite-vm-steps`.

The Lens search retains its captured, already verified bounds. Dossier work reports
the component count; reviewed-claim and queue-item counts; focal Review evidence
count; Lineage node and edge counts; Lens searched-snapshot, corpus-byte, and result
counts; and the fixed-point canonical dossier byte length. Every child keeps its own
more detailed work record.

The cumulative SQLite limit is an instruction budget tied to the local SQLite build
and query plan, not a portable wall-clock or memory guarantee. Queue, Lineage, Lens,
and final-output bounds remain independently effective. No bound permits a partial
Queue, Review, Lineage, or dossier result; only Lens retains its already explicit
bounded omissions and truncation semantics.

## Digests

Every embedded component retains its existing whole-receipt digest. The replay report,
which has no internal receipt field, is represented by SHA-256 over its complete
compact sorted-key UTF-8 JSON.

Each entry in `component_receipts` binds the component kind, schema, algorithm,
algorithm version, and receipt digest. SHA-256 over a compact sorted-key frame
containing the component-set schema, dossier algorithm/version/scope, mission, claim,
and the five ordered component entries produces `component_set_sha256`.

`dossier_receipt_sha256` is SHA-256 over the complete compact sorted-key UTF-8 dossier
payload excluding only that field. `work.canonical_output_bytes` is calculated to a
fixed point with a 64-character digest placeholder. These hashes establish internal
self-consistency only. They are not signatures, external integrity anchors, identities,
authorizations, approval records, or evidence of truth.

## Exclusions and semantic non-effects

The receipt explicitly excludes foreign-mission records, full reviews and lineage for
sibling claims, claimless Lineage nodes, reverse dependents outside Claim Review
scope, unreferenced snapshots, nonmatching Lens passages, audit/run/export records,
ephemeral assistance candidates, and external-agent protocols.

Building a dossier:

- creates no identity, run, audit event, evidence, finding, inference, status,
  correction, promotion, assignment, queue state, export, file, packet, or approval;
- does not modify source/snapshot bytes or any SQLite row;
- does not assess Lens candidates against the focal claim or make them evidence;
- does not make Queue items tasks, open work, priority, or recommended action;
- does not make Lineage edges entailment, causality, or truth;
- does not determine truth, evidence quality, confidence, sufficiency, or claim
  status;
- reads no credential and invokes no model, provider, network, URL fetch, REST/web
  route, MCP tool, Athena/Icarus adapter, or other external agent; and
- still requires a separate explicit human correction or evidence-adoption operation.

## Error contract

Captured-file safety and receipt verification retain the established bounded Lens
codes, including `lens_receipt_input_*`, `lens_receipt_too_large`, malformed/duplicate/
non-standard/complex JSON errors, unsupported schema/algorithm/runtime errors,
`lens_receipt_invalid`, and receipt digest mismatch. Current database inequality
remains `lens_replay_mismatch`.

Dossier-specific refusals are:

- `review_dossier_bounds_invalid` for invalid or incoherent aggregate/child bounds;
- `review_dossier_scope_invalid` for an invalid claim scope, foreign claim, missing
  focal queue review, or Lens mission mismatch;
- `review_dossier_work_limit` for cumulative SQLite or final dossier output exhaustion;
  and
- `review_dossier_inconsistent` for failed component version, digest, or structural
  cross-checks.

An invalid or unknown mission retains the existing non-reflective
`mission_not_found`. Child output/work ceilings and stored citation/snapshot integrity
errors retain their established component codes. Expected domain refusals use CLI
exit status 3 and do not reflect private research text or foreign identifiers.

## Trust and persistence boundary

The schema remains v5. Review Dossier v1 adds no migration, table, index, immutable
artifact, packet field/version, capability name, external principal, cryptographic
identity, signature, authentication, new provider destination, scholarly-source
adapter, PROV-O/RO-Crate exporter, Lens-to-evidence bridge, or broad D-6 behavior.

The captured Lens file remains an operator-managed copy of ordinary CLI output, not a
Minerva export. The composed stdout may contain extensive private claim, correction,
provenance, source-label, and exact quoted-source content. It stays within the same
trusted OS-user disclosure boundary as its component commands.

## Verification expectations

Run the fixed, model-free synthetic evaluator with:

```bash
uv run python scripts/evaluate_review_dossier.py
```

It reports component order and digest binding, nested receipt integrity, all required
cross-checks, exact multibyte citation and Lens-candidate bytes, repeated-run
determinism, mission isolation, explicit Lens truncation, the candidate/evidence
boundary, and unauthorized mutation count.

Regression and installed-distribution coverage must establish:

- byte-identical output for identical input and current state;
- strict pre-database refusal of hostile or tampered Lens input;
- exact Lens reproduction and explicit preservation of Lens truncation;
- one query-only SQLite snapshot and one cumulative progress budget;
- exact focal Queue/Review digest and cue binding;
- Review/Lineage claim, status, exact evidence/withdrawal, affected claim-owned
  citation/retraction/promotion payload and provenance, promoted-finding retracted
  state, and shared-snapshot agreement, including multibyte UTF-8 citation spans;
- mission, claim, and Lens-receipt isolation;
- child, cumulative work, and final-output refusal without partial output;
- no provider, model, credential, network, REST/web, protocol, or external adapter
  invocation; and
- unchanged database dump, main-file bytes, claims, evidence, findings, inferences,
  snapshots, queue state, and audit history.

Evaluation claims remain fixture-bound structural reconciliation and determinism
measurements. They do not measure truth, relevance, source quality, confidence,
priority, actionability, or research completeness beyond each explicitly declared
component scope.

## Deferred work

This acceptance completes the local read-only composition dependency only. The next
proposed step is a PROV-O/RO-Crate compatibility decision packet that proves a
lossless mapping and resolves canonicalization, context pinning, and source-byte
disclosure before any exporter is considered.

An explicit Lens-to-evidence bridge remains owner-gated and must reuse normal evidence
validation, stance, human identity, and atomic audit. Athena authentication and
external-principal/cryptographic-identity work, Icarus exchange, any read-only agent
protocol, packet v3, persistent queue operations, scholarly network adapters,
publication, messaging, and deployment remain separately gated.
