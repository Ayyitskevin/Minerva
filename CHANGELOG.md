# Changelog

Entries describe behaviour a reader would notice. Each release records the gate
evidence observed at the time it was prepared, not evidence expected of it.

Minerva is not deployed or published to a package index from this repository. A
release here is a tag plus this record.

## Unreleased

### Research record

- `minerva lens search` returns deterministic, model-free **candidate context**
  from snapshots already imported into one mission. A candidate is an unassessed
  lead, not evidence, a finding, or research state. Captured receipts can be
  verified without a database and replayed against the current local snapshot
  set; neither operation authenticates the receipt or archives the corpus.
- `minerva claim review`, `claim lineage`, `mission queue`, and `dossier build`
  are complete-or-refuse local read-only receipts: gaps and correction impacts,
  claim-owned provenance topology, a structural review index, and an atomic
  composition of those views plus one captured Lens replay. Cues are not tasks,
  lineage is not truth, and a dossier does not promote evidence.
- `minerva evidence add-from-lens` adopts **one** reproduced candidate after
  explicit receipt, snapshot, span, and quote confirmations plus a chosen claim
  and stance. Search and replay stay read-only. There is no bulk or automatic
  adoption. `doctor --deep` reconciles `lens.candidate.adopted` against the
  evidence card in both directions, alongside the existing inference
  adopt/retract/promote audit links from Phase 0E.
- A model-drafted candidate the operator judges correct can be **adopted** into
  the record as a labeled `agent_inference` (gate D-1, ADR 0008): its statement,
  uncertainty, and citations, plus the provenance needed to reconstruct what
  produced it — provider, model, request and response digests, prompt version,
  and the adopting actor and run. Adoption is a human act on one candidate from
  one preview, CLI-only, and it revalidates every citation against the live
  record and rescans the text for secrets before storing anything. An inference
  is never evidence and never a finding: it cannot influence claim status and
  counts toward nothing.
- `assist retract-inference` records that an adopted inference is no longer
  asserted, keeping the row and its history, exactly as finding retraction does.
  `finding add --from-inference` promotes one into a human finding — the
  operator's own assertion — linked to the inference that remains its
  provenance.
- Inferences and their retraction state (reason, timestamp, actor) are visible
  wherever findings are read: `mission show`, `claim show`, the REST finding
  endpoints, the web review page, and their own labeled section of the Markdown
  brief. Retracted inferences leave the brief as retracted findings do.
- The Markdown brief marks a **withdrawn citation** behind an adopted inference,
  so model-drafted text cannot render a citation as active when the ledger says
  otherwise.

### Contracts

- `minerva.capabilities.v2` gained `evidence.withdraw.cli` and
  `finding.retract.cli`, so a consumer can discover the correction vocabulary and
  see that it is CLI-only rather than absent. Additive: no entry was removed or
  altered.
- Canonical `minerva.research-brief.v2` bytes are unchanged by adoption.
  Inferences appear in the Markdown brief only; the golden fixtures are
  byte-identical.
- Digest-algorithm constants now drive packet emission, and CLI capability claims
  are checked against actual parser verbs.

### Refusals that now describe the right problem

- `assist adopt` requires `--expected-request-sha256`, the digest of the request
  the operator actually reviewed. Adoption regenerates the preview from live
  state, so without the pin a ledger change between generation and adoption
  stored an adopt-time request digest beside a generation-time response digest,
  and the same reviewed candidate could be adopted twice. A digest that no
  longer matches refuses with `assistant_context_changed` and persists nothing.
- Withdrawing evidence an already-adopted inference cites no longer reports as
  corruption. `doctor --deep` reports it as state, the brief marks the citation,
  backups are not refused, and retracting the inference remains the operator's
  judgment rather than something Minerva does on their behalf. A missing,
  tampered, or wrong-claim citation still fails the check.
- A JSON number that *overflows* to infinity (`1e400`) in a research packet or
  request now reports `packet_nonstandard_number` / `request_nonstandard_number`
  like `Infinity` does, instead of the generic malformed-document code. Both
  were always rejected; only one said why.
- A claim carrying more active evidence than a request may enumerate refuses
  with "The claim has more active evidence than a request may enumerate."
  instead of "The active evidence selection has changed." Nothing had changed in
  that case, and the old wording sent the operator looking for drift. The
  refusal, its class, and its code are unchanged.

### Security

- The unwired `CsrfProtector` primitive is removed from `minerva.web.security`.
  It protected no route — the review server has no unsafe form — and a security
  control that guards nothing reads as a defense the application does not have.
  The loopback host, origin, body-limit, and strict-header enforcement is
  unchanged. `SECURITY.md`, the architecture, and the threat model's mitigation
  column no longer describe that primitive as something Minerva has; the
  standing requirement that a future unsafe form carry both an accepted local
  origin and a CSRF token stays where it was, in the security invariants.

### Operator-facing

- Lens, Claim Review, Lineage, Queue, Dossier, and `evidence add-from-lens` are
  on the CLI. Packet `v2` bytes are unchanged; capabilities do not advertise a
  sibling or MCP surface for them.
- `docs/VISION.md` records Decision 0 (2026-08-20): this season treats Minerva
  as the fleet's research-memory on mickey. Doctrine is unchanged. Gate D-2,
  MCP, and remote bind stay closed. `docs/WORKSPACE.md` is the checkout,
  database, and seat-loop map. The mickey runtime (loopback serve, persistent
  DB, first mission) is documented there without putting database bytes in git.
- `contrib/systemd/` holds a loopback-only example unit. It is not a deploy.
- `restore` accepts an intact backup at any older recorded schema version and
  migrates it forward on the private staged copy, deep-validated before
  publication, recording a `database.migrated` event where the migration
  actually happened. Restoring a pre-upgrade backup no longer needs the prior
  binary.
- `doctor --deep` reconciles adopted, retracted, and promoted inferences against
  their audit history in both directions. A deleted retraction row — which
  returns model text to the brief as an asserted statement — is now detected
  instead of silently accepted.
- Release records now reflect the published `v0.2.0a1` tag.

## v0.2.0a1 — 2026-07-28

`v0.2.0a1`, tagging commit `b162573`. `v0.2.0a1` was chosen over `v0.2.0`
deliberately: it matches the declared version and makes no claim that the
pre-release period is over.

The annotated tag is published on GitHub and peels to
`b1625737345a8d3d017678d1f26ab11eedf9ff57`. Before publication, a fresh detached
checkout of that exact commit repeated all eleven repository gates on Linux with
Python 3.14.6: 689 tests passed at 90.00% branch coverage, the distributions
verified, and installed-wheel smoke passed.

### Research record

- Findings can be **retracted** (Milestone 1.5). Retraction never edits or deletes:
  it appends a record with its own no-update/no-delete triggers, and the finding,
  its citations, and its history stay. Surfaces that read findings return a
  retracted one marked with its reason, timestamp, and actor; synthesis excludes it
  from the brief rather than presenting it as asserted.
- An **assumption may cite withdrawn evidence**, matching what export has always
  allowed. Material findings still cannot; that refusal is unchanged.

### Contracts

- `minerva.capabilities.v2` gained `research.packet.v2.verify.cli` and
  `research.packet.v2.inspect.cli`. Additive: no entry was removed or altered.
- Canonical-JSON serialization and strict parsing for
  `minerva.research-packet.v2` and `minerva.research-request.v1` now come from one
  module. The golden fixtures are byte-identical across the change.

### Refusals that now describe the right problem

- A **concurrent upgrade** of the same database reports success on both sides
  instead of one spurious `migration_failed`. Losing to a *newer* installation
  reports `database_too_new`. A genuinely failed migration still reports
  `migration_failed` and leaves the database at its previous version.
- Float citation offsets refuse with `citation_offsets_invalid` instead of raising
  an unmapped `TypeError`.
- A symlinked database path reports `database_symlink` regardless of the
  `refuse_existing` flag.
- The research-request digest-mismatch classifier is anchored to the envelope root,
  so no other validation error can claim `request_digest_mismatch`.

### Operator-facing

- **Interrupting a provider call** (Ctrl-C) now records a terminal
  `outcome_unknown` audit event instead of leaving the invocation unmatched
  forever. The outcome is unknown rather than failed: the request had already left
  the machine, so the provider may have processed and charged for it.
- `doctor` reports staging remnants, unfinished assistance invocations, and
  retraction/audit reconciliation.
- `backup` refuses an outdated-but-intact database with
  `database_migration_required` rather than implying corruption.
- The README documents every CLI verb, and every subcommand has `--help` text.

### Security

- The identity-header denylist covers the mainstream proxy families (Google IAP,
  oauth2-proxy, Azure EasyAuth, Kong, Cloudflare Access). This is defence in depth:
  no code path reads an actor from a header, so accepting one never granted
  anything.
- The suite-wide outbound-network guard covers `connect`, `connect_ex`,
  `create_connection`, `sendto`, and `sendmsg`.
- The static security gate catches aliases bound through tuple, list, and starred
  unpacking, and its own detection branches are held to the coverage floor.

### Development

- Branch-coverage floor ratcheted from 85% to 88%.
- `scripts/regenerate_golden_fixtures.py` rebuilds the golden fixtures. It defaults
  to checking and exits non-zero with a diff; `--write` is explicit.
- `CONTRIBUTING.md` records the release runbook and the commit-attribution
  convention.

### Gate evidence

Observed on Linux, Python 3.12.3, on the tagged commit `b162573`:

| Gate | Result |
| --- | --- |
| `ruff check .` | passed |
| `ruff format --check .` | passed, 77 files |
| `mypy` | passed, 53 source files |
| `pytest` | **689 passed**, 90.00% branch coverage against an 88% floor |
| `pytest` (Python 3.13) | 689 passed, 90.00% branch coverage |
| `pytest` (Python 3.14.6, CI) | 689 passed, 90.00% branch coverage |
| `python -m build` | `minerva_research-0.2.0a1{-py3-none-any.whl,.tar.gz}` |
| `verify_dist.py dist` | verified wheel and sdist |
| `installed_smoke.py dist` | passed |
| `static_security_check.py` | passed, 51 files |
| `uv pip check` | 41 packages compatible |
| `git diff --check` | clean |

Python 3.14 could not be measured on the development machine: the only interpreter
available there is `3.14.0rc2`, on which the pinned pydantic fails with
`_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`. It was
recorded as open verification until CI measured it on released `3.14.6`, where the
suite reports the same 689 passed and 90.00% as 3.12 and 3.13. The rc-only failure
is an interpreter mismatch on that machine, not a defect in Minerva.

No gate is currently unverified.
