# Minerva product requirements: Milestones 1, 1.2, 1.3, and 2B

## Product identity

Minerva is a local-first, provenance-first research laboratory for humans and AI
agents.

> **Minerva — Ask carefully. Cite everything.**

The central doctrine is: **Minerva records evidence and uncertainty; it does not
manufacture certainty.** Minerva manages a disciplined path from questions to
claims, evidence, contradictions, uncertainty, reproducible work, and defensible
conclusions. It never claims to determine truth.

## Milestone 1 outcome

A reviewer working completely offline after installation can create a mission,
question, and falsifiable claim; import an immutable UTF-8 source snapshot; create
exactly located supporting and opposing evidence; inspect the evidence ledger;
record labeled findings and uncertainty; and export deterministic Markdown and JSON
briefs whose material statements resolve to stored snapshots and citations. Every
state change is attributable through an append-only audit trail.

## Milestone 1.2 outcome

An offline operator or future local consumer can verify and inspect the canonical
`research-brief.json` directly from an installed Minerva command without opening
SQLite, contacting a network, or loading provider credentials. Verification applies
the existing strict `minerva.research-brief.v2` contract, including canonical digest,
ownership, citation/evidence, provenance, audit coverage, and audit dependency-order
checks. Inspection exposes bounded inventory and verification metadata, never
research text or private path/identity values.

Digest verification proves packet self-consistency, not authenticity, origin, truth,
approval, or the contents of source snapshots that are not embedded in the packet.
Athena/Icarus exchange and every execution, orchestration, approval, publication, or
remote transport surface remain deferred.

## Milestone 1.3 outcome

An offline producer can create a strict deterministic `minerva.research-request.v1`
artifact selecting one mission/claim and asserting the exact complete active evidence
ledger expected at fulfillment time. An installed Minerva command verifies the file
without SQLite, network access, provider code, or credentials. A separate command
validates the request before database open, resolves it in one query-only read
snapshot, and exclusively writes a claim-scoped canonical v2 brief plus a minimal
digest-bound result manifest without changing research, audit, run, or export state.

The one supported selection policy prevents arbitrary evidence subsets: every active
stance must be present, while canonical output retains withdrawn and supersession
history and exact provenance closure. Request/result digests establish internal
self-consistency and binding only. They do not authenticate an Athena caller, grant
authority, approve work, establish completeness beyond the selected claim, or permit
disclosure. No Athena adapter, transport, shared database/run envelope, Icarus request,
MCP surface, execution, orchestration, publication, messaging, or automatic adoption
is implemented.

## Milestone 2B outcome

A local CLI operator can optionally ask OpenAI or Anthropic to draft finding
candidates from one claim and its bounded active evidence. Before any external call,
Minerva renders the exact disclosure context and a digest-bound request manifest. The
operator must review that preview and explicitly authorize the same digest. The
provider response is untrusted, validated candidate output only: it is labeled as
agent inference, includes uncertainty and existing evidence IDs, and is neither
persisted nor adopted as research state.

This is a reviewed exception to the offline Milestone 1 boundary, not a general model
or integration platform. It adds no model invocation to the REST API or web interface,
no URL fetching, tools, code execution, provider fallback, automatic retry,
publication, messaging, or autonomous research.

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
- **Research request:** an inert canonical file that names one existing mission/claim,
  binds an exact active-ledger precondition, and requests canonical v2 output. It is not
  authenticated work coordination or authorization.
- **Research result manifest:** a minimal canonical file binding one verified request
  digest to the schema and exact SHA-256 of its fulfilled brief bytes.

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
6. Domain mutations and their audit records share one SQLite transaction. Rejected
   mutations and failures that return control to Minerva leave neither domain state
   nor misleading success events. Ephemeral Milestone 2B assistance is not a domain
   mutation; its metadata-only audit records bracket an external call and therefore
   cannot share one atomic transaction with that call. This does not claim crash
   atomicity across SQLite and exported files or external providers.
7. Export ordering and canonical serialization are explicit. The export digest is
   SHA-256 over the canonical brief payload before the digest envelope is added.
8. An export cannot include a material finding with a missing, withdrawn, detectably
   inconsistent, or unresolvable citation. Opposing and inconclusive evidence remain
   visible. Minerva has no external signature or anchor for detecting a determined
   same-OS-user coordinated rewrite.
9. Assistance preview performs no credential read or network operation. It discloses
   the exact canonical JSON that would be sent: the claim ID, statement, and
   falsification criterion plus bounded active evidence citation IDs, quotes, and
   stances. Withdrawn evidence is excluded; opposing and inconclusive evidence remains
   visible. Byte offsets, snapshot digests, and supersession references remain local
   but are bound into the request digest as provenance.
10. Assistance authorization requires an explicit confirmation flag and the exact
    SHA-256 from a fresh preview. The digest binds the provider, model, fixed
    destination, prompt, exact context, candidate limit, and output-token limit.
11. Provider credentials come only from the current OS-user environment after
    authorization. Minerva does not persist credentials, provider prompts/responses,
    or returned candidates. Locally accepted candidates are always labeled
    `agent_inference` and never become evidence, findings, truth, confidence, or claim
    status automatically.
12. Each authorized provider call is attempted once, with no redirects, environment
    proxy use, automatic retries, provider fallback, or tools. A timeout or connection
    loss is an unknown provider outcome. Requested and terminal audit events contain
    bounded metadata and digests only and are separate transactions around the call.
13. Research-request DTOs are strict, SQLite-independent, canonical, and limited to
    mission/claim identifiers, the one complete-ledger policy, a sorted exact active
    citation set, and output schema. Paths, URLs, credentials, free text, actors,
    authority, approvals, timestamps, callbacks, transports, and run controls are not
    request fields.
14. Request verification completes before any fulfillment database construction/open.
    Mission, claim, ledger, and synthesis use the same query-only read snapshot. The
    requested set must equal the complete active claim ledger; unknown, out-of-scope,
    withdrawn, omitted, or newly added evidence fails closed without stance filtering.
15. Fulfillment is read-only research behavior. It creates no identity/run, audit
    event, `brief_exports` row, domain mutation, provider request, or network activity.
    Fixed output files are canonical, owner-only, exclusive, and cleaned as a group
    after caught write failures; existing files are never overwritten.
16. A claim-scoped v2 packet preserves exact target-claim evidence/provenance closure
    but carries no selection marker. Its request/result binding supplies that external
    meaning; standalone packet verification does not prove database completeness.

17. Request fulfillment caps cumulative SQLite virtual-machine work across its query-only
    snapshot. Exhaustion is a stable `brief_work_limit` refusal before output; this is an
    availability guard, not a wall-clock or successful-fulfillment guarantee.
    Claim-scoped preflight also refuses before full database text or snapshot content
    is returned to Python when the exact-multiplicity NUL-safe storage-byte lower bound
    for emitted strings exceeds the export byte cap. SQLite may inspect those values;
    canonical serialization remains the final byte check.

## User surfaces

- The `minerva` CLI proves the entire workflow without a browser and provides init,
  mutation, inspection, audit, backup/restore, doctor, export, and serve operations.
- `minerva packet verify` and `minerva packet inspect` are file-only offline commands;
  they require no database and return bounded JSON success or error records.
- `minerva request verify` is a file-only offline command. `minerva request fulfill`
  adds one explicitly supplied local database and output directory while remaining
  read-only with respect to Minerva state.
- `minerva-demo` creates a disposable synthetic mission and exports its brief without
  contacting a network service. It refuses an existing database.
- The web interface is a restrained, server-rendered review surface.
- `/api/v1` exposes strict contracts for later protocol adapters. Unknown fields are
  rejected, input sizes and pagination are bounded, and errors have stable codes.
- `/healthz`, `/readyz`, and `/api/v1/capabilities` support local operations.
- `minerva assist finding-candidates` is the only Milestone 2B model surface. It
  previews by default and can invoke one of the two reviewed adapters only after exact
  digest confirmation. There is no equivalent REST or web operation.

## Acceptance priorities

When trade-offs are necessary: source immutability, citation correctness, opposing
evidence, transaction/audit integrity, deterministic export, tests, documentation,
then UI polish.

For Milestone 2B, authorization integrity, bounded exact disclosure, credential
secrecy, candidate-only semantics, and honest unknown-outcome audit records take
priority over convenience or provider availability.
