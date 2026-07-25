# ADR 0007: Retract findings instead of blocking export forever

- Status: Accepted
- Date: 2026-07-25
- Decision: Kevin, decision gate D-9
- Review: Kevin review required because this adds migration history and changes
  what a research brief contains

## Context

Minerva's documented correction workflow is to withdraw evidence: an observation
turns out to be mismeasured, the operator records a withdrawal, and the card
stays visible in the ledger marked withdrawn. That is the right shape, and ADR
0001 chose it deliberately over editing or deleting.

It had a fatal interaction with findings. Any material finding citing that
evidence made `_assemble_brief` refuse with `citation_withdrawn`, and there was
no way back:

- findings and finding citations are append-only (migration 0002 triggers);
- withdrawal is append-only and has no reversal;
- no record could express "this finding is no longer asserted".

So `brief preview`, `brief export`, claim-scoped `request fulfill`, the REST
brief-preview endpoint, and the web brief pages all failed permanently for that
mission, and `doctor --deep` reported a standing `finding_integrity` failure —
all as a direct consequence of following the documented process correctly. The
milestone's central deliverable became unreachable through honest use.

A second, narrower defect sat beside it. The withdrawn-citation check ran before
the statement-kind branch, so an *assumption* or *unresolved question* that
optionally cited evidence — a supported workflow with its own passing test —
also blocked the whole export when that evidence was later withdrawn. PRD
invariant 8 governs *material* findings only; the code was stricter than the
contract it implemented.

## Decision

Add `finding_retractions` (migration 0004): an append-only record, one per
finding, mirroring `evidence_withdrawals` exactly — reason, creator, run,
timestamp, `UNIQUE(finding_id)`, mission-composite foreign key, and
update/delete triggers.

`ResearchService.retract_finding` writes that record and its
`research.finding.retracted` audit event in one transaction, refusing an unknown
finding and a second retraction. `minerva finding retract --finding --reason`
exposes it, matching `evidence withdraw` as a CLI-only correction verb.

A retracted finding leaves synthesis. It is excluded from the mission-wide and
claim-scoped assembly queries, from its uncertainty entry, from the audit
references the packet carries, and from the deep-doctor finding check. It is
never deleted: the row, its citations, its creation audit event, and the
retraction record all remain in the database.

Separately, the withdrawn-citation refusal is now gated on
`kind.requires_citation` in the service, the packet verifier, and doctor, so it
applies to material findings exactly as PRD invariant 8 says and no longer to
statements whose label already declares they are not evidence-backed.

## Consequences

- The correction workflow terminates. Withdraw the evidence, retract the finding
  that rested on it, and the mission exports again; `doctor` returns to healthy.
- An assumption or unresolved question may keep an optional citation to
  withdrawn evidence. The packet's `CitationRecord` carries `withdrawn: true`,
  so a consumer sees the state rather than being denied the document.
- History is preserved and inspectable. Nothing about retraction removes or
  edits a finding.
- `minerva.research-brief.v2` is unchanged. A retracted finding is simply absent
  from the packet, exactly as it was before the finding was recorded, so no
  schema version, canonical byte layout, or golden fixture moves. Consumers
  reading v2 need no change.
- Schema version 3 → 4. Existing databases require `minerva init`; an older
  binary refuses a version-4 database, the existing fail-closed behaviour.

## Rejected alternatives

- **Declaring the permanent refusal intended doctrine** (option (b) at the
  decision gate). It punishes exactly the correction discipline the doctrine
  demands, and it makes an irreversible mistake out of an honest one.
- **Un-withdrawing evidence.** Withdrawal is a historical fact. Reversing it
  would rewrite the record rather than extend it, which ADR 0001 rejects.
- **Editing or deleting the finding.** Same objection, and it would destroy the
  provenance that makes the brief defensible.
- **Carrying retracted findings inside the packet under a `retracted` flag.**
  This is the closest alternative and a defensible future move — it mirrors how
  withdrawn evidence stays visible in the ledger. It is not taken now because it
  changes `minerva.research-brief.v2`, which ADR 0002 froze as the fleet-facing
  contract, and no consumer exists that needs retraction history in the packet.
  The database and audit ledger retain it in full. Revisit with a v3 when a
  consumer actually needs it.
- **Auto-retracting findings when their evidence is withdrawn.** Retraction is a
  research judgement: withdrawing one of several citations may not invalidate
  the finding. Minerva records the operator's decision rather than inferring it.
