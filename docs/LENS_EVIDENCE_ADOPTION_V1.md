# Lens Evidence Adoption v1: one explicit lead into evidence

Status: accepted and implemented under the repository owner's 2026-08-08 instruction
to proceed with the next recommended slice. The authorization is limited to the local,
CLI-only, single-candidate bridge described here.

Lens search, receipt verification, receipt replay, and Review Dossier remain read-only.
Adoption is a separate evidence mutation initiated by a trusted local operator. It
does not authorize bulk or automatic adoption, a web/API/MCP surface, an external
principal, a provider or network call, a migration or index, a packet change, a
capability-manifest entry, or a standards exporter.

## Operator workflow

First capture and inspect the ordinary Lens search envelope:

```bash
minerva lens search --db research.db --mission MIS_ID \
  --query "immutable provenance" --limit 10 > lens-receipt.json
minerva lens verify --input lens-receipt.json
minerva lens replay --db research.db --input lens-receipt.json
```

After selecting exactly one returned candidate and independently choosing how it
evaluates one existing claim, repeat the receipt and candidate values explicitly:

```bash
minerva evidence add-from-lens \
  --db research.db \
  --mission MIS_ID \
  --claim CLM_ID \
  --lens-input lens-receipt.json \
  --candidate-rank 1 \
  --stance supports \
  --expected-retrieval-receipt-sha256 RECEIPT_SHA256 \
  --expected-snapshot-sha256 SNAPSHOT_SHA256 \
  --expected-start-byte 120 \
  --expected-end-byte 184 \
  --expected-quote-sha256 QUOTE_SHA256
```

`--stance` is required and accepts `supports`, `opposes`, `context`, or
`inconclusive`. `--supersedes EVD_ID` is optional and invokes the normal append-only
evidence-supersession validation. Rank is only a selector into the captured ordered
result; it is never evidence strength, confidence, source quality, or epistemic
weight.

“Operator-supplied” records trusted-local-operator intent at this single-user boundary.
Minerva attributes the mutation to its local OS-user identity context; it does not
authenticate a human or prove who chose the candidate, claim, stance, or supersession.

The receipt digest, rank, snapshot digest, half-open byte span, and quote digest are
all confirmations, not conveniences inferred from claim text. A mismatch refuses the
operation. The command never accepts raw quote text from the operator: the verified,
currently reproduced candidate supplies the exact bytes to the normal evidence
service.

## Trust-bound execution order

The implementation has one ordered path:

1. The CLI reads `--lens-input` through the existing descriptor-pinned, no-follow,
   stable regular-file reader. The 8 MiB cap and strict Lens JSON/DTO verification run
   before a `Database` is constructed or SQLite is opened.
2. The service strictly verifies the receipt again, validates the mission/claim and
   optional supersession identifier shapes, requires the receipt mission to equal the
   explicit mission, and checks every explicit candidate confirmation.
3. One `BEGIN IMMEDIATE` transaction owns the remaining work. A package-private Lens
   seam reproduces the complete receipt against the current database through the same
   mission/filter selection, snapshot-integrity, normalization, scoring, omission,
   ordering, and digest path as ordinary Lens replay. It uses the caller-owned write
   transaction; public Lens search/replay still open query-only read snapshots.
4. The service refuses an already-recorded identical evidence evaluation.
5. For an optional supersession, the bridge first applies the evidence package's
   bounded predecessor-chain check. The package-private `EvidenceService` transaction
   seam then applies its normal direct target, claim/snapshot mission, exact UTF-8
   byte-span/quote, immutable-snapshot, and stance validation.
6. The new `EvidenceCard`, its existing `evidence.card.created` audit event, and one
   additional `lens.candidate.adopted` provenance event commit together. Any caught
   refusal or failure rolls all three back.

Reproduction inside the write transaction prevents a same-database race between the
current-state check and evidence creation. It does not turn a captured receipt into an
as-of corpus archive: any relevant current-state mismatch still refuses as normal
Lens replay does.

## Duplicate and supersession policy

The bridge refuses an existing card with the same mission, claim, snapshot identity
and digest, byte span, exact quote, stance, and `supersedes_evidence_id`. The check
includes withdrawn cards; withdrawal preserves history and is not permission to
silently recreate the same evaluation. A different stance is a distinct operator
evaluation, and a different explicit supersession target is a distinct historical
relationship.

The `BEGIN IMMEDIATE` lock serializes the duplicate check and insert without a new
schema constraint. Supersession remains append-only lineage, not automatic
withdrawal, revision, or invalidation. The bridge requires the target to already
exist, belong to the same mission and claim, and lead through a valid, bounded,
acyclic predecessor history. An
operator still uses `evidence withdraw` separately when an older card should no longer
stand.

## Result contract

CLI success uses the normal JSON envelope:

```text
{"lens_evidence_adoption": { ... }}
```

The enclosed DTO has schema `minerva.lens-evidence-adoption.v1`, kind
`single_candidate_evidence_adoption`, and status `adopted`. It binds:

- mission and claim identity;
- retrieval-receipt, normalized-query, and searched-snapshot-set SHA-256 values;
- selected candidate rank and source/snapshot identity;
- snapshot digest, exact half-open byte coordinates, and quote digest;
- whether the reproduced retrieval receipt was truncated;
- the operator-supplied stance and optional supersession target;
- the complete newly created `EvidenceCard` and its exact quote;
- the `lens.candidate.adopted` audit-event identifier; and
- a fixed semantic notice and machine-readable semantic-boundary flags.

Its exact top-level field set is:

```text
schema_version, kind, status, mission_id, claim_id,
retrieval_receipt_sha256, query_sha256, snapshot_set_sha256,
candidate_rank, source_id, snapshot_id, snapshot_sha256,
start_byte, end_byte, quote_sha256, retrieval_truncated,
stance, supersedes_evidence_id, evidence, adoption_audit_event_id,
semantic_notice, semantic_boundary
```

The nested `evidence` object is the normal `EvidenceCard` DTO with exact fields
`id`, `mission_id`, `claim_id`, `snapshot_id`, `snapshot_sha256`, `start_byte`,
`end_byte`, `quote`, `stance`, `supersedes_evidence_id`, `creator_id`, `run_id`, and
`created_at`.

The exact semantic-boundary booleans are:

| Field | Value |
| --- | --- |
| `single_candidate_only` | `true` |
| `receipt_strictly_verified` | `true` |
| `current_database_exactly_reproduced` | `true` |
| `candidate_explicitly_confirmed` | `true` |
| `normal_evidence_validation_applied` | `true` |
| `creates_one_evidence_card` | `true` |
| `writes_append_only_audit_history` | `true` |
| `operator_supplied_stance` | `true` |
| `lens_search_remains_read_only` | `true` |
| `rank_used_as_epistemic_weight` | `false` |
| `performs_bulk_or_automatic_adoption` | `false` |
| `determines_truth_or_source_quality` | `false` |
| `calculates_confidence` | `false` |
| `alters_claim_status` | `false` |
| `creates_or_retracts_findings` | `false` |
| `persists_agent_inference` | `false` |
| `modifies_source_or_snapshot_bytes` | `false` |
| `invokes_model_provider_or_network` | `false` |
| `exposes_external_agent_protocol` | `false` |

The fixed notice states that one operator-selected lead was reproduced and added through
normal validation, that rank has no epistemic weight, that stance came from the
operator, and that truth, confidence, claim status, findings, and source quality are
unchanged.

The result is not byte-identical across successful invocations because evidence,
identity/run, audit, and creation-time provenance are generated mutation state. Its
receipt and source digests deterministically bind the selected lead; they are not a
signature, authenticated approval, source-truth proof, or permission to disclose it.

## Audit provenance

Normal evidence creation retains its established `evidence.card.created` event and
exact detail contract. The additional append-only `lens.candidate.adopted` event uses
entity type `evidence_card`, the new evidence ID, and the same mission, actor, run, and
transaction. Its fixed details are:

- `candidate_rank`, `claim_id`, `start_byte`, and `end_byte`;
- `query_sha256`, `retrieval_receipt_sha256`, `snapshot_set_sha256`,
  `snapshot_id`, and `snapshot_sha256`;
- `quote_sha256`, `stance`, and `supersedes`; and
- `retrieval_truncated`.

Audit details deliberately omit the query, quote, source label, input path, and other
raw receipt text. `minerva doctor --deep` reconciles every adoption event to exactly
one evidence card, the card's creator/run/mission and later audit sequence, the fixed
detail set, and the existing creation event. The receipt digest remains correlation
and self-consistency provenance, not cryptographic identity or authenticity.

The writer also verifies the durable audit postcondition before commit rather than
trusting an injected `AuditSink` return value. For the new evidence ID there must be
exactly two matching feature rows: `evidence.card.created` immediately followed at the
next audit sequence by `lens.candidate.adopted`. Both rows must have canonical audit-ID
shape, entity type `evidence_card`, the exact evidence/mission/actor/run metadata, and
compact sorted-key JSON equal to their fixed expected detail maps. The second row's ID
must equal the `adoption_audit_event_id` returned by the sink and the result DTO. A
silent, forged, reordered, noncanonical, or otherwise nonconforming sink raises
`lens_adoption_audit_invalid` inside the same transaction, rolling back the evidence
card, both feature events, and any new run/audit state.

## Semantic effects and non-effects

One successful command creates exactly one evidence card and the append-only audit
history described above. It does not:

- mutate Lens search/replay behavior or make candidate context itself evidence;
- choose a claim, candidate, stance, or supersession target for the operator;
- calculate truth, confidence, sufficiency, relevance, or source quality;
- alter claim status or create, retract, or modify a finding;
- persist, retract, promote, or otherwise change an agent inference;
- withdraw or retract any older evidence automatically;
- modify source registrations or immutable snapshot bytes;
- create a packet, export, queue item, dossier, capability, external request, or
  persistent Lens artifact; or
- read a credential or invoke a model, provider, network, URL fetch, shell, plugin,
  Athena/Icarus adapter, REST/web endpoint, MCP tool, or other external agent.

A returned candidate from an explicitly truncated Lens receipt may be adopted because
the selected lead is reproduced exactly. The operation makes no claim that Lens
searched an unbounded corpus or that omitted passages could not affect an operator
assessment.

## Refusal contract

Captured-file and receipt failures retain the stable Lens codes documented in
[`LENS_V1.md`](LENS_V1.md). Adoption-specific refusals include:

| Error code | Meaning |
| --- | --- |
| `lens_adoption_scope_invalid` | Mission/claim/supersession scope is malformed or the receipt names another mission. |
| `lens_adoption_confirmation_invalid` | An explicit digest/span confirmation is malformed. |
| `lens_adoption_candidate_rank_invalid` | The selector is not a valid one-based integer into the returned candidate array. |
| `lens_adoption_confirmation_mismatch` | Receipt digest or selected candidate coordinates/digests do not match exactly. |
| `lens_candidate_already_adopted` | The identical evidence evaluation already exists, including if withdrawn. |
| `lens_adoption_audit_invalid` | The same-transaction creation/adoption audit postcondition is incomplete or inconsistent. |

Current-database drift retains `lens_replay_mismatch`; normal claim, snapshot,
citation, stance, supersession, database, and migration refusals retain their existing
codes. Expected domain refusals use the existing CLI exit status `3` and reflect no
raw quote, query, receipt path, or foreign identifier.

## Evaluation

Run the fixed, local, model-free harness:

```bash
uv run python scripts/evaluate_lens_evidence_adoption.py
```

Its `minerva.lens-evidence-adoption-evaluation.v1` result measures exact selected-
candidate binding, 1,000,000 ppm multibyte UTF-8 span accuracy, preservation of the
operator-supplied stance, card/creation/adoption-audit binding, the exact authorized state delta,
rollback when the second audit fails, duplicate/corpus-drift/mission-isolation
refusals, declared semantic non-effects, deep-doctor integrity, schema-v5 stability,
zero provider/network invocation, and zero unauthorized mutation on a fixed two-
mission fixture. Repeated runs must return the same evaluation document.

These are fixture-bound implementation measurements. They do not score truth,
relevance, evidence strength, source quality, confidence, or operator judgment. Unit,
CLI, integrity, migration/legacy-database, installed-wheel, hostile-receipt,
concurrency, exact audit-detail, and immutable-byte regressions enforce the wider
contract.

## Persistence and authorization boundary

This slice uses the existing schema v5 tables and append-only audit ledger. It adds no
migration, table, column, trigger, or index. `minerva.research-brief.v2`,
`minerva.capabilities.v2`, Lens receipt schemas, Review Dossier, and every external
trust boundary are unchanged. No equivalent REST, web, API, MCP, packet, or
capability-manifest operation exists.

The same owner instruction accepts the PROV-O/RO-Crate decision packet only as
non-authorizing architectural guidance. No serializer, public profile/IRI, context
asset, canonical standards artifact, attached-source disclosure mode, exporter, or
publication surface is authorized or implemented.

The next dependency gates remain D-2 authenticated Athena identity/authorization
after counterpart reverification, D-3 Icarus artifact exchange after D-2, and D-5 a
bounded read-only agent protocol after D-2/D-3. Each needs its own explicit owner
decision. Packet v3, persistent queue operations, scholarly network adapters,
standards export, cryptographic identity, and any additional Lens adoption surface
remain deferred.
