# ADR 0010: The Athena coordination adapter seam

- Status: **Proposed — not accepted, not implemented.**
- Date: 2026-07-30
- Decision: **pending, gate D-2 (after ADR 0009). Review: Kevin.** Nothing
  described here is in effect: no adapter, intake path, or signing call-site
  exists in either repository. This ADR is inert until ADR 0009's registry
  exists, and both are inert until Athena ships its side — a precondition the
  survey below records as currently **unmet**.
- Precondition: drafted against a fresh survey of the Athena repository
  (v0.1.0a1, FastAPI + SQLite, six weeks old, disciplined). Zero references to
  Minerva or Oracle exist in that repo today.

## Context

ADR 0009 proposes who an external actor is and how a research request is
attributed to one. This ADR proposes the actual seam: how an authenticated
Athena produces `minerva.research-request.v1` artifacts Minerva will accept,
and how it consumes `minerva.research-result.v1` and packet artifacts back.

The remarkable fact from the survey is how little new shape either side needs.
Minerva's request/result/packet artifacts were designed for exactly this
(ADR 0002, Milestone 1.3): strict, canonical, size-capped, verified before
trust, fulfilled read-only under a work budget. Athena, independently, already
produces and consumes schema-versioned JSON artifacts atomically
(`athena.portability.v1` and friends) and versioned envelopes
(`athena.icarus_dispatch.v1`) under the same `<system>.<artifact>.v<N>`
convention as Minerva's own. Producing a conformant
`minerva.research-request.v1` is idiomatic for Athena, not foreign.

What the survey found missing — the precondition this ADR names — is the
signing half. Athena has stable named agent principals as database rows
(`is_agent` users, integer ids, scoped `ath_` bearer tokens, SHA-256 hashed at
rest; every write attributed), and reserved run-prefix namespaces
(`automation:`, `icarus:`) — but those are namespaces for runs, not principals,
and no `athena:planner-1`-style external principal URN exists today. More
fundamentally, **Athena holds no asymmetric keys and signs nothing
asymmetrically**: all inter-service trust is shared-secret HMAC-SHA256,
outbound (`X-Athena-Signature: sha256=<hmac>`, env-keyed) and inbound
(constant-time verified). The gap to "hold a keypair" is exactly five items,
each narrow and idiomatic to close:

1. a private-key store (0600 file or DB column), following Athena's shown-once
   secret lifecycle and token-rotation conventions;
2. an external-facing principal URN bound 1:1 to a public key (a principal
   registry);
3. request signing over canonical request bytes or digest;
4. out-of-band public-key publication to Minerva; and
5. optionally, an artifact-writing seam — though atomic versioned JSON writes
   already exist there.

`cryptography` is already a transitive dependency on the Athena side via
`pyjwt[crypto]`, so ed25519 needs no new dependency there. (Minerva's new
dependency for verification is recorded as a consequence of ADR 0009, not this
one.)

## Decision (proposed)

### The flow

1. Athena composes a `minerva.research-request.v1` artifact (existing strict
   schema, existing canonical serializer rules, complete-ledger precondition —
   unchanged) and signs the request's canonical SHA-256 digest with the
   principal's ed25519 private key.
2. The request plus signature travels through whichever seam ADR 0009's open
   questions select (recommended there: a local-file drop-box first).
3. Minerva verifies **fail-closed, before any research work**: unknown
   principal, revoked principal, bad signature, or digest mismatch each refuse
   with a stable, non-reflective error. This mirrors `request verify`'s
   existing hostile-input posture — the same file discipline, the same
   size caps, the same strict canonical validation — extended with a query-only
   registry read. A refused request creates no artifacts, no state, and no
   success audit event.
4. Fulfillment proceeds **exactly** as the existing local `request fulfill`:
   same `complete_claim_ledger` selection policy, same exact active-citation
   freshness precondition, same query-only read snapshot, same cumulative work
   budget and fail-closed `brief_work_limit`. The adapter adds no query
   surface; it is a door onto the reviewed fulfillment path, not a new path.
5. The result artifact (`minerva.research-result.v1` and the claim-scoped v2
   packet) returns through the seam. Audit events record principal URN and
   request digest as attribution, per ADR 0009 — bounded metadata, never key
   material.

### What this ADR must not change

- **No new fulfillment semantics.** Selection policy, budgets, limits, and
  output bytes are the local command's, unchanged.
- **No packet format change.** `minerva.research-brief.v2` canonical bytes are
  untouched; the v3 question stays deferred to the first consumer-facing
  packet revision.
- **No network server beyond what ADR 0009 decides.** This ADR adds no
  listener of its own.
- **No external write path beyond requesting.** Athena cannot add sources,
  evidence, findings, or inferences, cannot withdraw or retract, and cannot
  invoke assist. Research remains local human/agent work; an external actor's
  only verb is "please produce this brief." Results become evidence only
  through the existing explicit import-and-cite doors, exactly as ADR 0002
  fixed for every sibling.

### Dependency ordering

This ADR is inert until ADR 0009's principal registry exists — there is
nothing to verify a signature against before then. Both ADRs are inert until
Athena ships its side of the seam. The survey finding bears repeating as a
planning fact: the precondition is **currently unmet** on the Athena side, but
it is narrow and idiomatic to close (the five gap items above), and it
introduces no new dependency and no new architectural pattern there — Athena
already has the secret lifecycle, the artifact conventions, and the signing
call-site shape (its HMAC site) to model each piece on.

### Corresponding Athena-side work list

A proposal for that repository, not a commitment — recorded here so gate D-2
can be decided with both sides' costs visible:

1. Keypair generation, storage, and rotation, following Athena's existing
   token-lifecycle conventions (shown-once secrets, 0600 storage, rotation as
   reissue).
2. Principal registry rows binding each external-facing URN
   (`athena:planner-1`, …) 1:1 to a public key.
3. A request-signing call-site, modeled on the existing HMAC signing site in
   `icarus_commands.py`, but producing ed25519 signatures over the canonical
   request digest.
4. Public-key export via Athena's existing versioned-JSON portability
   convention, for out-of-band delivery to the Minerva operator, who registers
   it by CLI (ADR 0009, open question 3).

## Open questions for the decision

These are genuine forks, recorded for Kevin at gate D-2:

1. **Artifact directory location and ownership: a shared watched directory,
   or explicit hand-off paths?** A watched directory implies a standing
   watcher — a daemon Minerva does not currently run and a new attack surface.
   Explicit hand-off paths (the operator or a CLI invocation names where
   requests land and where results go) keep Minerva invocation-driven.
   *Recommendation: explicit hand-off paths*, consistent with the drop-box
   recommendation in ADR 0009 and with Minerva running no daemons.
2. **Does fulfillment for external requests get a tighter work budget than
   local?** The existing budget guards against adversarial input; an
   authenticated principal is less adversarial than an anonymous file but more
   numerous than one operator. *Recommendation: ship with the same budgets
   initially* — they are already sized for hostile input — and revisit only if
   per-principal rate bounds (a later, transport-shaped question) prove
   necessary.
3. **Replay protection: a request-digest uniqueness registry, a nonce-plus-
   expiry envelope, or accept replays?** Honest analysis: fulfillment is
   read-only and deterministic, so a replay cannot corrupt research state —
   the worst cases are repeated bounded work and re-written output files, i.e.
   a work-amplification nuisance, not an integrity hole. But the fulfillment
   log is needed for audit anyway, and Plan 2 already fixes "one request
   digest → at most one fulfillment output; replays detected by digest and
   refused with a stable error naming the original result digest." A nonce
   scheme buys freshness guarantees that need envelope machinery and clock
   dependence this seam does not otherwise require. *Recommendation: the
   digest uniqueness registry* — one append-only table with
   `UNIQUE(request_sha256)`, the simplest defensible option, and idempotent
   fulfillment falls out of it for free.
4. **What is the error vocabulary for refusal events?** *Recommendation:* a
   small set of stable, non-reflective codes in the existing style —
   `unknown_principal`, `revoked_principal`, `bad_signature`,
   `request_digest_mismatch`, `duplicate_request` — recorded as bounded audit
   metadata, never echoing submitted bytes or key material, symmetric with the
   packet tooling's error-classification rules.

## Consequences if accepted

- The audit ledger gains its first non-OS-user attribution: principal URN plus
  request digest on every external request, accepted or refused. Run lineage
  for externally-originated work (`run_origins`, actor kind `external_agent`)
  lands with the D-2 implementation, per ADR 0009's scope note.
- Fulfillment gains a uniqueness registry (if open question 3 resolves as
  recommended) — one more append-only table, additive only.
- Both ADRs together still change no observable behaviour until Athena ships
  its side; a Minerva with the registry and no counterpart is a Minerva with
  two empty tables.
- The threat model gains the seam rows named in ADR 0009 (key theft, replay,
  floods) plus this one's refusal vocabulary; same-OS-user malware remains
  inside the boundary until D-4.
- The dependency direction stays exactly as ADR 0002 fixed it: artifacts and
  verification across the seam, never shared tables, never package imports,
  never a path or URL to dereference.

## Rejected alternatives

- **Shared database tables or direct ORM access.** Permanently rejected by
  ADR 0002; it destroys ownership and migration boundaries. The seam exists
  precisely so this never happens.
- **REST mutation endpoints for Athena.** Would require the server, the
  authorization model, and the threat model of D-4, which stays closed — and
  would hand an external actor verbs (source import, withdrawal) this ADR
  explicitly withholds.
- **MCP first.** Deferred to D-5 by design: the adapter comes first because
  the artifacts already exist and are reviewed; an MCP surface without a
  principal model would be unauthenticated by construction.
- **Unsigned requests trusted by filesystem permissions alone.** Attribution
  would collapse to the OS user; an auditor could not distinguish an
  Athena-authored request from an operator-authored one, which defeats the
  entire purpose of ADR 0009.
- **A new signed-request wrapper format replacing `research-request.v1`.**
  Forks the reviewed contract, invalidates golden fixtures, and couples
  research selection to transport metadata — ADR 0002 rejected putting
  transport inside research artifacts, and the signature rides outside the
  canonical bytes instead.
