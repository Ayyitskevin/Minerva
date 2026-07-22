# ADR 0001: Use immutable snapshots and exact byte-span evidence

- Status: Accepted
- Date: 2026-07-22

## Context

Research software can overstate certainty when it blurs source material, evaluator
interpretation, and synthesized conclusions. Minerva needs portable citations that
survive changes to original files and can be verified without network access.

## Decision

Store validated UTF-8 source bytes inside SQLite as immutable snapshots identified by
SHA-256. Evidence cards reference exactly one claim and one snapshot in the same
mission using zero-based half-open UTF-8 byte offsets and a verbatim quote. Creation
and export re-check the stored digest, bounds, character boundaries, and quote.

Evidence has one explicit stance: supports, opposes, context, or inconclusive. Cards
are append-only. Withdrawal is a separate event record and supersession creates a new
card pointing back to the prior card. Claim status is a research workflow label, not a
truth determination, and no confidence score is derived from evidence count.

Findings carry a statement class. Material classes require evidence citations;
assumptions and unresolved questions may be uncited only while clearly labeled.

## Consequences

- Exact provenance is reproducible after the original file changes or disappears.
- Unicode-facing tools must translate human selections to byte offsets deliberately.
- Duplicate bytes may appear in distinct source registrations; equal digests expose
  that fact without silently joining provenance across missions.
- Storage grows with imported content, which is acceptable under the Milestone 1 size
  bound and preferable to fragile external references.
- Doctor/export detect partial or inconsistent database tampering. A determined
  same-OS-user coordinated rewrite remains outside the boundary because Milestone 1
  has no external signature or integrity anchor.

## Rejected alternatives

- File paths as evidence references: mutable, private, and non-portable.
- Line numbers alone: ambiguous across newline forms and edits.
- Model-produced summaries as evidence: provenance-breaking and epistemically unsafe.
- Confidence from evidence counts: ignores quality, dependence, and contradiction.
