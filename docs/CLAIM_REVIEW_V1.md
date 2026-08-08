# Claim Review v1: complete evidence gaps and correction impacts

Status: implemented under the repository owner's 2026-08-08 continuation
directive for schema-free, local, read-only research views.

Claim Review derives a deterministic structural review of one claim from
Minerva's existing append-only ledgers. It answers questions such as “does the
active ledger contain support and opposition?”, “does the recorded workflow
status still have the active stance it requires?”, and “what still-live records
are affected by a withdrawal or retraction?” It does not decide whether the
claim is true, score evidence quality, calculate confidence, recommend a status,
or perform a correction.

## Operator workflow

```bash
minerva claim review --db research.db --mission MIS_ID --claim CLM_ID
```

The default bounds may be changed explicitly:

```bash
minerva claim review --db research.db --mission MIS_ID --claim CLM_ID \
  --max-evidence-cards 200 \
  --max-affected-records 200 \
  --max-relationships 2000 \
  --max-snapshot-bytes 16777216 \
  --max-sqlite-vm-steps 4000000
```

The CLI follows Minerva's compact JSON convention and returns the receipt under
the `claim_review` key. The public local Python service interface is
`ClaimReviewService.review_claim(mission_id=..., claim_id=..., bounds=...)`.
Both mission and claim are required so a claim identifier from another mission
cannot silently widen the review scope. Neither surface is an authenticated
external or agent-protocol API.

## Receipt

A successful `minerva.claim-review.v1` receipt has kind
`evidence_gap_and_retraction_impact` and records the
`structural-ledger-review` algorithm at version `1`. It contains:

- the mission, question, claim, falsification criterion, creator, run, and
  creation identity;
- the recorded claim status, version, rationale and provenance, the active
  stances that status requires, any required stance that is missing, and the
  derived `evidence_valid` flag;
- separate active and withdrawn counts for `supports`, `opposes`, `context`,
  and `inconclusive`, plus the explicit
  `active_support_and_opposition_present` observation;
- ordered gap and impact codes with operator-facing explanations and the
  affected record identifiers where applicable;
- every evidence card in the target claim, including source and snapshot
  identity, snapshot digest, exact half-open UTF-8 byte coordinates, quote byte
  length and quote SHA-256, stance, supersession, provenance, and any
  append-only withdrawal record;
- correction-relevant findings and adopted inferences, their complete citation
  sets, correction state, effect codes, and, where present, the promotion row's
  identifier, finding identifier, actor, run, timestamp, and current retraction
  state of the finding;
- a per-withdrawal impact map showing affected active/retracted material
  findings, optional statements, inferences, and direct superseding evidence;
- configured bounds, measured work, algorithm/version, completion policy,
  semantic boundary, and `review_receipt_sha256`.

The receipt digest is SHA-256 over compact, sorted-key UTF-8 JSON for the whole
receipt except the digest field itself. The service introduces no current
timestamp, random identifier, or environment-dependent score. Stored provenance
timestamps and identifiers remain part of the receipt because they identify the
ledger state being reviewed.

The digest establishes deterministic self-consistency only. It is not a
signature or proof of origin, authenticity, authority, approval, disclosure
permission, or independent correctness of the recorded research.

“Affected findings” and “affected inferences” are correction-impact views, not
unbounded replacements for the normal finding and inference lists. They include
related retracted records and still-live records whose citations are affected by
withdrawn target-claim evidence. The complete target-claim evidence ledger is
always present on success.

## Complete-or-refuse bounds

Claim Review never returns a plausible-looking prefix. A successful receipt
always says `completion_policy: complete_or_refuse`, `complete: true`, and
`truncated: false`. If any configured bound would omit required evidence,
affected records, citation relationships, verified snapshot bytes, or SQLite
work, the entire operation refuses with `claim_review_work_limit` (CLI exit
`3`). Raising a bound against the same database is an explicit operator choice;
retrying unchanged limits cannot make an incomplete review complete.

| Bound | Default | Accepted range |
| --- | ---: | ---: |
| Evidence cards in the claim | 200 | 1–200 |
| Affected findings plus inferences | 200 | 1–500 |
| Finding/inference citation relationships | 2,000 | 1–5,000 |
| Distinct verified snapshot bytes | 16,777,216 | 1–67,108,864 |
| SQLite virtual-machine steps | 4,000,000 | 1,000–16,000,000 |

`work` reports the evidence-card, affected-finding, affected-inference,
relationship, distinct-snapshot, and distinct-snapshot-byte totals admitted by
the successful review. Relationship totals include promotion-target citations
inspected to authenticate lineage even when the promoted finding is not otherwise an
affected output record. The virtual-machine ceiling is a local instruction-work
guard, not a wall-clock timeout or a portable replay metric: SQLite version and
query-plan differences can change how quickly a run reaches it. Consumed VM
steps are therefore not included in the receipt; every successful result is
still a complete deterministic function of the admitted ledger state and its
recorded bound.

## Checked-in evaluation scope

`scripts/evaluate_claim_review.py` uses fixed, independently labeled synthetic
fixtures. It measures four structural gap labels across three reviewed claims,
recorded-status validity, six expected withdrawal-impact edge classes, repeated
receipt determinism, identifier-based isolation from a second mission, and
zero mutation of the database dump or main database-file bytes.

Those metrics do not claim source-quality, truth, logical-contradiction, or
real-corpus performance. The evaluation fixture uses ASCII citations and does
not score promotion lineage. Separate unit, CLI, and installed-distribution
tests cover UTF-8 byte coordinates and quote digests, promotion/retraction
behavior, bounds and hostile scope, receipt-digest verification, provider/network
non-invocation, and installed-wheel behavior; those checks are not reported as
evaluation precision or recall.

## Gap, status, and contradiction semantics

Gap codes describe structural absence only:

- `no_active_evidence`: every evidence card is withdrawn or none was recorded;
- `no_active_support`: no active `supports` card exists;
- `no_active_opposition`: no active `opposes` card exists;
- `status_required_active_stance_missing`: the recorded workflow status has
  lost at least one active stance it requires.

The existing claim-status rule is re-derived rather than replaced:

- `provisionally_supported` requires active supporting evidence;
- `contested` requires active supporting and opposing evidence;
- `unsupported` requires active opposing evidence;
- `open` and `inconclusive` impose no required active stance.

The historical status remains recorded when its requirement becomes unmet.
Claim Review reports that mismatch but neither rewrites the status nor infers a
replacement.

`active_stance_contradiction` means only that at least one active supporting
card and one active opposing card coexist. It is an explicit stance conflict,
not proof that either source is correct, that the propositions are logically
exclusive, or that the evidence has equal quality. `context` and
`inconclusive` are counted and retained but do not satisfy support/opposition
requirements. Counts never become votes, weights, confidence, sufficiency, or
truth.

Impact codes keep distinct conditions distinct:

- `active_stance_contradiction` records coexisting active support/opposition;
- `withdrawn_evidence_history_present` retains the correction history;
- `recorded_status_requirement_unmet` names a stale active-evidence basis for
  the recorded workflow status;
- `live_material_finding_uses_withdrawn_evidence` and
  `optional_statement_uses_withdrawn_evidence` distinguish a synthesis blocker
  from an allowed but review-worthy optional citation;
- `retracted_finding_history_present` and
  `retracted_inference_history_present` retain corrected records;
- `live_inference_uses_withdrawn_evidence` names an inference that is still
  asserted even though its adoption-time citation policy no longer holds;
- `promoted_finding_remains_independently_asserted` prevents inference
  retraction from being mistaken for retraction of the human finding it once
  produced;
- `live_inference_remains_after_promoted_finding_retraction` records the inverse
  boundary: retracting the human finding does not silently retract its source
  inference.

## Withdrawal, retraction, and inference impacts

Corrections extend the record:

- A withdrawn evidence card leaves the active stance set but keeps its exact
  citation, provenance, withdrawal reason, actor, run, and timestamp.
- Supersession is provenance lineage, not an implicit correction action. Both
  cards remain active unless separately withdrawn; a withdrawal impact names
  direct superseding evidence only to make that history navigable.
- An unretracted material finding that cites withdrawn evidence remains visible
  as an invalid live assertion and blocks the applicable claim/mission
  synthesis until the operator performs an explicit correction. An assumption
  or unresolved question may retain an optional withdrawn citation and is
  reported separately.
- A retracted finding remains in the review history and is excluded from
  synthesis.
- A retracted adopted inference remains in the review history and is excluded
  from the Markdown brief. If it was promoted, the receipt retains the full
  promotion provenance, while the separately created human finding remains
  asserted until that finding is separately retracted.
- A retracted promoted finding remains in finding history. Its source inference
  is independently asserted until separately retracted, and Claim Review retains
  the promotion edge rather than treating either correction as transitive.
- A still-live adopted inference whose evidence was later withdrawn has
  `active_citation_policy_satisfied: false`; Claim Review identifies its
  withdrawn citations. It reports `inference_promotion_blocked` only when no
  promotion was already recorded. An earlier promotion remains append-only
  history, and the separately created finding carries its own
  withdrawal/retraction effects.

The last case is a current reading-surface risk, not something Claim Review
silently repairs: synthesis currently renders every unretracted adopted
inference in the Markdown brief even when a cited evidence card has since been
withdrawn. The canonical `minerva.research-brief.v2` JSON contains no adopted
inferences at all. Operators should run Claim Review before relying on the
Markdown inference section and explicitly retract an inference that is no
longer asserted. Changing Markdown eligibility is a separate behavioral
decision; this read model only makes the condition inspectable.

## Integrity and semantic non-effects

One SQLite read snapshot owns scope validation, work bounds, all reads, and
integrity checks, with `PRAGMA query_only = ON`. Every evidence reference in
the result is resolved through the shared citation verifier, and every distinct
snapshot used by target evidence or an affected record is digest-checked before
the receipt is returned. Actual stored BLOB length is compared with the declared
snapshot length and byte ceiling before content is materialized. Selected
promotion targets must match the inference mission, claim, copied
statement/uncertainty/kind, and citation set. Cross-mission scope, admitted broken
citation/supersession relationships, inconsistent status derivation, or tampered
bytes fail closed.

The claim's question must resolve inside the mission. Every status event for the
claim must also remain in that mission with a contiguous version chain beginning at
one, and the selected status must exactly match its verified latest event. A forged
foreign status reason or actor therefore produces only the fixed integrity refusal,
never receipt text.

“Complete” means complete for correction-relevant records admitted by stored owner
rows to the explicitly named mission and claim. Claim Review deliberately does not
scan foreign-mission owners for relationship rows that could exist only after direct
database corruption with foreign keys/triggers defeated; doing so would let unrelated
missions consume target-query work. Such whole-file referential corruption belongs to
deep doctor. The mission-scoped view never returns the foreign owner's text.

Claim Review:

- writes no identity, run, audit, export, or research row;
- creates, withdraws, retracts, or promotes nothing;
- does not alter claim status or confidence;
- creates no research queue;
- invokes no provider, model, credential, network, adapter, or external system;
- changes neither `minerva.research-brief.v2` nor
  `minerva.capabilities.v2`.

Every correction remains a separate explicit human operation through the
existing audited service. Claim Review is a local operator CLI/read model with a
public local Python service, not an authenticated external/agent protocol or
permission to disclose research.

## Authorization boundary and next dependencies

The first 2026-08-08 continuation directive authorized Claim Review itself. The
repository owner's subsequent continuation separately accepts Claim Lineage Graph v1
only. The remaining dependency-ordered plan proposes a derived non-persisted mission
research queue, then Lens receipt verification/replay and a local review dossier, but
recording that plan does not authorize implementation. Each future slice needs an
explicit owner decision before work begins, even if it remains schema-free, local, and
read-only.

A persisted queue, schema migration, external principal, cryptographic identity,
Athena/Icarus adapter, MCP or other external/agent-facing API, packet v3,
scholarly network adapter, broader retrieval, or autonomous adoption remains
under its existing recorded owner gate.
