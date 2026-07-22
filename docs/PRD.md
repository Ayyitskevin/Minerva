# Minerva Milestone 1 product requirements

## Product identity

Minerva is a local-first, provenance-first research laboratory for humans and AI
agents.

> **Minerva — Ask carefully. Cite everything.**

The central doctrine is: **Minerva records evidence and uncertainty; it does not
manufacture certainty.** Minerva manages a disciplined path from questions to
claims, evidence, contradictions, uncertainty, reproducible work, and defensible
conclusions. It never claims to determine truth.

## Milestone outcome

A reviewer working completely offline after installation can create a mission,
question, and falsifiable claim; import an immutable UTF-8 source snapshot; create
exactly located supporting and opposing evidence; inspect the evidence ledger;
record labeled findings and uncertainty; and export deterministic Markdown and JSON
briefs whose material statements resolve to stored snapshots and citations. Every
state change is attributable through an append-only audit trail.

## Research vocabulary

- **Research mission:** a bounded research objective that owns its questions,
  claims, sources, runs, findings, and briefs.
- **Research question:** an open, answerable prompt inside one mission. A question
  frames inquiry; it is not itself a conclusion.
- **Claim:** a declarative, falsifiable statement evaluated by evidence. Minerva
  requires a separate falsification criterion and stores a workflow status, never a
  truth value. Milestone 1 validates that the criterion is present and bounded; it
  does not pretend software can decide whether arbitrary natural language is
  scientifically falsifiable.
- **Source:** the provenance record describing where submitted material was said to
  come from. Milestone 1 sources are local registrations only; URL metadata is inert.
- **Immutable source snapshot:** the exact validated UTF-8 bytes captured at import,
  identified by SHA-256 and insulated from later changes to the original file.
- **Evidence card:** an attributable evaluation of one claim using one exact byte
  span from one source snapshot, with a stance and verbatim quote.
- **Citation:** the stable identifier and location tuple that resolves an evidence
  card to a snapshot digest, byte offsets, and exact quoted bytes.
- **Evidence stance:** `supports`, `opposes`, `context`, or `inconclusive`. Stance is
  an evaluator's classification, not a confidence score or truth judgment.
- **Finding:** a labeled research statement assembled by a human or agent from cited
  evidence. Material findings require citations.
- **Assumption:** an explicitly labeled premise not established as observed evidence.
- **Uncertainty:** a stated limitation, ambiguity, missing observation, or unresolved
  conflict that constrains a finding or claim.
- **Research run:** an attributable unit of work performed by an identity context.
- **Review:** an assessment of research artifacts and their provenance; it may accept,
  challenge, or request changes but does not rewrite history.
- **Research brief:** a deterministic, portable Markdown/JSON synthesis of a mission,
  including claims, both favorable and adverse evidence, findings, assumptions,
  uncertainty, citations, and digests.

## Statement classes

Minerva preserves the difference between:

| Class | Meaning | Citation rule |
| --- | --- | --- |
| Observed fact | Directly recorded observation in a source snapshot | Required |
| Source assertion | Something a source says, without adopting it as true | Required |
| Agent inference | A reasoned interpretation produced by an agent | Required and labeled |
| Assumption | A premise used without evidentiary establishment | May be uncited; always labeled |
| Calculation | A deterministic transform of stated inputs | Inputs must be cited |
| Recommendation | A proposed action derived from research | Required and labeled |
| Unresolved question | A known gap or open inquiry | May be uncited; always labeled |

A model-generated statement never becomes evidence merely because a model produced
it. It can only be stored as a labeled inference, assumption, recommendation, or
unresolved question under the same citation rules as human-authored material.

## Domain invariants

1. Snapshots are immutable, content-digested, size-bounded UTF-8 records. Importing
   the same bytes twice creates distinct provenance registrations with the same
   digest; there is no silent cross-mission deduplication.
2. Citation locations use zero-based, half-open UTF-8 **byte offsets** `[start, end)`.
   The bytes must decode independently as UTF-8 and equal the submitted quote.
3. Evidence belongs to the same mission as its claim and snapshot. Cards are never
   edited; withdrawal is a separate historical record, and supersession creates a
   new card.
4. Claims have workflow states (`open`, `provisionally_supported`, `contested`,
   `unsupported`, `inconclusive`) but never a `true` state. Counts do not calculate
   confidence.
5. A material finding cannot be created without at least one same-mission evidence
   citation. Assumptions and unresolved questions may remain uncited only because
   their labels explicitly say they are not evidence-backed.
6. Mutations and their audit records share one SQLite transaction. Rejected mutations
   and failures that return control to Minerva leave neither domain state nor misleading
   success events. This does not claim crash atomicity across SQLite and exported files.
7. Export ordering and canonical serialization are explicit. The export digest is
   SHA-256 over the canonical brief payload before the digest envelope is added.
8. An export cannot include a material finding with a missing, withdrawn, detectably
   inconsistent, or unresolvable citation. Opposing and inconclusive evidence remain
   visible. Minerva has no external signature or anchor for detecting a determined
   same-OS-user coordinated rewrite.

## User surfaces

- The `minerva` CLI proves the entire workflow without a browser and provides init,
  mutation, inspection, audit, backup/restore, doctor, export, and serve operations.
- `minerva-demo` creates a disposable synthetic mission and exports its brief without
  contacting a network service. It refuses an existing database.
- The web interface is a restrained, server-rendered review surface.
- `/api/v1` exposes strict contracts for later protocol adapters. Unknown fields are
  rejected, input sizes and pagination are bounded, and errors have stable codes.
- `/healthz`, `/readyz`, and `/api/v1/capabilities` support local operations.

## Acceptance priorities

When trade-offs are necessary: source immutability, citation correctness, opposing
evidence, transaction/audit integrity, deterministic export, tests, documentation,
then UI polish.
