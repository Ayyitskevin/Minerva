# ADR 0008: Persist human-adopted agent inferences as a separate labeled record

- Status: **Accepted**
- Date: 2026-07-26
- Decision: **accepted 2026-07-30, decision gate D-1 opened by Kevin's
  directive.** The four open questions below are resolved as recorded there.
- Review: Kevin. This adds migration history, persists untrusted model output, and
  changes what a research brief contains — three separately review-gated surfaces
  under AGENTS.md.

## Context

ADR 0003 built the assistance surface so that model output cannot become evidence:
candidates are validated, returned as ephemeral `agent_inference` drafts, and
never stored. That was the right default while the shape of the feature was
unknown.

It has a cost that shows up only in use. A candidate the operator judges correct
has exactly one path into the record: the operator retypes it as a finding. What
survives is a human finding indistinguishable from one the operator reasoned out
alone. The fact that a model drafted it, which provider and model, against which
exact evidence, and under which prompt version — all of it is gone the moment the
terminal scrolls.

That is dishonesty by omission, and it is the specific kind Minerva exists to
prevent. The doctrine says Minerva records evidence and uncertainty; a record that
silently absorbs machine-drafted text as human assertion records neither
faithfully.

Two prior decisions constrain the shape of any fix:

- **ADR 0001** rejected editing and deleting in favour of append-only correction.
  Anything persisted here must be correctable the same way.
- **ADR 0007 (D-9)** was the lesson about *what* to build on day one. Findings got
  an append-only retraction record only after the missing one had made exports
  permanently unreachable, and slice 7 then had to fix a second defect: retraction
  was invisible on every reading surface except the packet. A new persisted record
  type must ship with both halves — the retraction record *and* its visibility —
  or it will repeat that sequence exactly.

## Decision

### What is persisted

Adoption is an explicit human act on one candidate from one preview. It records:

- the candidate's `statement` and `uncertainty` verbatim;
- its evidence citations, which are **mandatory** — `CandidateDraft` already
  requires at least one, and adoption revalidates them rather than trusting the
  generation-time check;
- provenance sufficient to reconstruct what produced it: provider, model,
  `request_sha256`, `candidate_index`, `response_sha256`, system prompt version,
  and the adopting actor, run, and timestamp.

It does **not** record the prompt text, the raw provider response, the credential,
or any provider account identifier. ADR 0003's audit rule is unchanged: digests
and bounded metadata, never content that was not already local.

### Four append-only tables (migration 0005)

`agent_inferences`, `agent_inference_citations`,
`agent_inference_retractions`, and `agent_inference_promotions` — STRICT,
CHECKed identifiers, mission-composite foreign keys, and `BEFORE UPDATE` /
`BEFORE DELETE` `RAISE(ABORT)` triggers, mirroring the existing finding tables
exactly. No existing table changes.

The retraction table ships **in the same migration as the record it retracts.**
That is the whole D-9 lesson and it is not negotiable in this design.

The promotion table is a separate append-only link rather than a column on
`agent_inferences`, because the update triggers correctly forbid setting a link
column after insert. `UNIQUE(inference_id)` permits one promotion per
inference; the finding it names is the human's assertion and the inference
remains as its provenance.

### Visibility, from day one

Every surface that reads findings also reads inferences, and reports retraction
state with reason, timestamp, and actor: `mission show`, `claim show`, the REST
finding endpoints, and the web review page. This is stated as a requirement of
the change rather than a follow-up, because in D-9 it was the follow-up and that
was the defect.

### What an inference is never allowed to do

- It is never evidence, and never a finding. It is a distinct record type with its
  own label.
- It cannot influence claim status, and does not count toward anything. Counts are
  not confidence — the existing rule applies unchanged.
- It cannot be cited by a finding. Findings cite snapshots through evidence cards;
  an inference is not a source.
- It is not automatically adopted, promoted, or converted. Adoption is a human
  action, one candidate at a time.

### Adoption-time validation

Adoption is a normal atomic mutation-plus-audit transaction, and it revalidates
rather than trusting the preview:

- every cited evidence ID must still exist, still belong to the same claim and
  mission, and still be active — evidence may have been withdrawn between
  generation and adoption;
- the text is rescanned for secret patterns, because this is the first point at
  which untrusted model output becomes durable;
- size bounds are enforced against the stored value, not the provider's claim;
- re-adopting the same `(request_sha256, candidate_index, claim_id)` is refused by
  unique constraint, so a repeated command cannot silently duplicate the record.

A failed adoption leaves nothing behind, and regret is handled by retraction, not
deletion.

### Export

`minerva.research-brief.v2` is **unchanged**. Inferences appear in the Markdown
brief in their own section, labeled so they cannot be mistaken for human
findings. The v2-omits-inferences divergence is documented in DECISIONS.md, and
the `v3` packet question is deferred to the first consumer-facing packet
revision, when a version bump will be forced anyway.

## Open questions — resolved 2026-07-30 under gate D-1

These were genuine forks, not rhetorical ones. Kevin's directive of 2026-07-30
opened gate D-1 and resolved each as follows; the resolutions follow the
recommendations already drafted above and remain reversible by Kevin at review
time.

1. **Does the v2 packet need to say inferences exist?** Resolved: leave
   `minerva.research-brief.v2` canonical bytes unchanged for this milestone.
   Inferences appear in the Markdown brief in their own clearly labeled
   section; the divergence is documented here and in DECISIONS.md, and the
   `v3` packet question is deferred to the first consumer-facing packet
   revision (the D-2 era), when a version bump will be forced anyway.
   Rationale: smallest reviewed change to the highest-integrity surface;
   preserves golden fixtures and the offline verifier contract.

2. **May a human promote an inference into a finding?** Resolved: yes,
   explicitly, never automatically. `finding add --from-inference <id>`
   creates the human finding and records an append-only promotion link in the
   same atomic transaction — a fourth table, because the `BEFORE UPDATE`
   triggers correctly forbid setting a link column after insert. The finding
   is the human's assertion; the inference remains as provenance.

3. **Does `doctor` verify inference citation integrity?** Resolved: yes,
   symmetric with findings, at the cost of another deep-check query.

4. **CLI verb shape.** Resolved: `assist adopt`, keeping the assistance
   surface together per ADR 0003's boundary.

## Consequences

- Model contribution becomes part of the permanent record instead of terminal
  output, with enough provenance to audit what produced it.
- Adopted text is untrusted model output persisting locally for the first time.
  The threat model gains a row: injection-shaped content is now durable and
  rendered, so export labeling and the existing autoescape/CSP rules carry weight
  they did not before. Adversarial adoption fixtures are required, not optional.
- Schema version 4 → 5. Existing databases need `minerva init`; an older binary
  refuses a version-5 database, which is the existing fail-closed behaviour.
- The capability manifest gains an adoption entry, additively.
- Minerva still cannot say a claim is true. An inference is one more labeled,
  cited, retractable statement — it moves no epistemic needle, by construction.

## Rejected alternatives

- **Keep candidates ephemeral (status quo).** Loses the provenance that makes the
  brief defensible, and pushes operators toward retyping, which launders machine
  text into human assertion. This is the failure mode the doctrine names.
- **Store inferences as findings with a flag.** Cheaper, and wrong: every query,
  export path, and integrity check that means "human finding" would silently start
  including model text, and one missed call site becomes a doctrine violation
  rather than a bug.
- **Ship without retraction, add it later.** Exactly D-9. It produced an
  unreachable export and a second defect on the reading surfaces. Repeating it
  knowingly would be worse than having done it once unknowingly.
- **Auto-adopt high-confidence candidates.** There is no confidence to be high.
  ADR 0003 forbids automatic adoption and this does not reopen it.
- **Let inferences influence claim status or counts.** Would make model output
  into evidence through arithmetic instead of through assertion. Same violation,
  harder to see.
- **API or web adoption.** ADR 0003 kept assistance CLI-only, and adoption is the
  more consequential half. A read-only REST listing could follow later as its own
  reviewed change.
