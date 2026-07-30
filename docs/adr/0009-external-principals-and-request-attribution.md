# ADR 0009: External principals and signed request attribution

- Status: **Proposed — not accepted, not implemented.**
- Date: 2026-07-30
- Decision: **pending, gate D-2. Review: Kevin.** Nothing described here is in
  effect: no migration, table, registry, or signature verification path exists,
  and none may be built before this gate is opened. This ADR creates the first
  proposed trust boundary beyond the OS user, so it sits behind the same review
  bar as migration history and security contracts under AGENTS.md.
- Precondition: drafted against a fresh survey of the Athena repository
  (v0.1.0a1). Athena today holds no asymmetric keys and signs nothing
  asymmetrically; the precondition "Athena can hold a keypair" is currently
  **unmet** — narrow and idiomatic to close, but unmet. The five gap items and
  the Athena-side work list are recorded in ADR 0010, which depends on this one.

## Context

Today Minerva has exactly one security principal: the OS account that can read
the database and start the process. The threat model says so plainly, and every
authentication-shaped shortcut — actor headers, caller-supplied identity,
loopback origin — is explicitly refused. That is the correct posture for a
single-operator evidence core, and nothing in this ADR weakens it.

Kevin's directive makes Minerva the fleet's research pillar: other systems must
be able to *ask* it questions. The artifact half of that already exists. ADR
0002 and Milestone 1.3 defined `minerva.research-request.v1` as an inert,
strict, canonical request artifact with verify/fulfill tooling that is
fail-closed, work-bounded, and database-read-only. What does not exist is any
answer to "who is asking." The request digest establishes self-consistency
only; the threat model states verbatim that it does not establish origin,
authenticity, authority, disclosure permission, or freshness. ADR 0002 said a
future adapter "must first authenticate and map identity at the boundary." This
ADR proposes what that identity is and what *authenticated* means for a
research request.

A scope note, because Plan 2's ADR table gives 0009 a wider brief (transport,
signed envelopes, capability grants, replay defense). This draft deliberately
narrows it to the two things every later D-2 surface — the Athena adapter
(0010), MCP (0012), anything after — must agree on first: the principal model,
and how a request is attributed to one. Transport, envelope machinery, and a
grant vocabulary are left to the seam ADRs that need them, so that this
decision stays small enough to review on its own.

Prior decisions constrain the shape:

- **ADR 0001** rejected editing and deleting in favour of append-only
  correction. A principal registry must be correctable the same way: revocation
  is a new record, never an edit.
- **ADR 0007 (D-9)** is the standing lesson: the correction story ships in the
  same migration as the record it corrects, or it arrives as an emergency.
  The revocation table ships with the principals table, not after it.
- **ADR 0002** fixed that digests never authenticate and that no remote actor
  header is ever trusted. Attribution here is cryptographic, not claimed.
- The threat model's hostile-offline-request row already establishes the
  posture any signed intake must mirror: validate everything, refuse
  fail-closed, reflect nothing.

## Decision (proposed)

### Principal registry (migration 0006 sketch — proposal only)

Two append-only tables, `principals` and `principal_revocations`, mirroring
migration 0005's style exactly: STRICT, CHECKed identifiers and fields,
`BEFORE UPDATE` / `BEFORE DELETE` `RAISE(ABORT)` triggers. **No existing table
changes.** Sketch, not final SQL:

```sql
CREATE TABLE principals (
    id TEXT PRIMARY KEY CHECK(id GLOB 'prn_[0-9a-f]*' AND length(id) = 36
        AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    urn TEXT NOT NULL CHECK(length(urn) BETWEEN 3 AND 200
        AND urn NOT GLOB '*[^0-9a-z:_-]*'),
    display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 200),
    public_key_ed25519 TEXT NOT NULL CHECK(length(public_key_ed25519) = 64
        AND public_key_ed25519 NOT GLOB '*[^0-9a-f]*'),
    registered_by TEXT NOT NULL CHECK(length(registered_by) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(urn),
    UNIQUE(public_key_ed25519)
) STRICT;

CREATE TABLE principal_revocations (
    id TEXT PRIMARY KEY CHECK(id GLOB 'prv_[0-9a-f]*' AND length(id) = 36
        AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    principal_id TEXT NOT NULL REFERENCES principals(id) ON DELETE RESTRICT,
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
    revoked_by TEXT NOT NULL CHECK(length(revoked_by) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(principal_id)
) STRICT;
```

The principal URN is an external-facing name of the form
`<system>:<agent-name>` — `athena:planner-1` — bound 1:1 to an ed25519 public
key (32 bytes, stored lowercase hex). `registered_by` and `revoked_by` are
local actors under the existing `IdentityContext`; registration and revocation
are ordinary atomic mutation-plus-audit transactions.

Revocation mirrors the retraction pattern (ADR 0007, ADR 0008): a revocation is
a new append-only row, never an edit or delete, and `UNIQUE(principal_id)`
means a revoked principal stays revoked. Re-introducing an actor means a new
principal row and a new key, so the history of who held which key when can
never be confused. This is the D-9 lesson applied on purpose: the correction
record is in the same migration as the record it corrects.

Run-lineage records for externally-originated work (Plan 2's `run_origins`,
new actor kind `external_agent`) are part of the D-2 *implementation* and may
share migration 0006, but they are not what this ADR decides; this ADR decides
the registry and attribution rule they would reference.

### Request attribution

A signed research request is the existing `minerva.research-request.v1`
artifact — canonical bytes and payload digest **unchanged** — plus an ed25519
signature over the request's 32-byte canonical SHA-256 digest, produced by the
private key of a registered, unrevoked principal. The signature travels outside
the artifact (sidecar or envelope, whichever seam ADR 0010 and its open
questions select); it never enters the canonical bytes, so the packet and
request contracts, golden fixtures, and the offline verifier are untouched.

Verification of such a signature proves that the holder of the principal's
private key authored exactly this request — not a similar one, not a modified
one. This is the distinction the docs have carried since Milestone 1.3 made
explicit: the digest establishes integrity (self-consistency); the signature
establishes authenticity (origin). "Digests are self-consistency only" gains
its first signed counterpart here, and this ADR is where the first real
authenticity anchor enters the design.

Attribution is recorded in audit events as principal URN plus request digest
plus outcome — bounded metadata, never key material. The public key lives only
in the registry; the private key never enters Minerva's process, database, or
files at all.

### Why asymmetric, and not shared-secret HMAC

Athena's existing inter-service idiom is HMAC-SHA256 over a shared secret
(`X-Athena-Signature`, env-keyed, constant-time compared). It is rejected here
for one reason that matters more than familiarity: with a shared secret,
Minerva itself holds the material needed to forge attribution. Any audit record
that says "Athena requested this" would then be only as trustworthy as
Minerva's own self-restraint, and an auditor could not independently confirm
origin. With ed25519, Minerva holds only public verification material; it
cannot mint a request and attribute it to Athena, and an auditor can verify
attribution from the registry rows and the signature alone. For a system whose
entire purpose is records a third party can check, the verifier must not also
be a potential forger.

The honest costs are recorded below as consequences: a new pinned dependency on
the Minerva side, and a key lifecycle that did not previously exist.

### Out of scope

Transport selection, remote access, multi-user authorization (D-4 stays
closed), any network listener change, a capability-grant vocabulary beyond the
single capability "may submit research requests," replay machinery, and any
change to the request, result, or packet artifact formats. External actors gain
no write path into research state under this ADR; they gain only a name and a
way to prove a request is theirs.

## Open questions for the decision

These are genuine forks, recorded for Kevin at gate D-2:

1. **First seam shape: local-file drop-box, or loopback-only authenticated
   endpoint?** A drop-box (Athena writes request + signature files into a
   designated directory; Minerva reads them on operator or CLI invocation)
   needs no listener, no new process, and no socket — but couples both systems
   to directory layout and gives no synchronous refusal. A loopback endpoint
   gives immediate, structured refusal but is a standing server surface the
   threat model does not currently have. *Recommendation: drop-box first* — it
   is the smallest possible seam, matches the artifact discipline already in
   place, and keeps the no-listener rule intact; an endpoint can follow as its
   own reviewed change once the flow is proven.
2. **Principal URNs per-agent or per-Athena-deployment?** Per-agent
   (`athena:planner-1`, `athena:curator-2`) makes attribution and revocation
   precise at the cost of more registry rows; per-deployment (`athena:main`)
   is simpler but blurs exactly the provenance this ADR exists to keep.
   *Recommendation: per-agent*, since Athena already has stable named agent
   principals as database rows.
3. **Is registration and revocation CLI-only?** *Recommendation: yes,
   initially.* The OS user administers the registry with the same
   mutation-plus-audit discipline as every other correction verb; no REST or
   web administration surface is proposed, matching the CLI-only posture of
   adoption and correction in ADRs 0003 and 0008.
4. **What is the key-rotation story?** *Recommendation: rotation = revoke the
   old principal row, register a new one.* No in-place key change (the triggers
   correctly forbid it), no overlapping-validity windows in v1; a principal
   that must keep a stable URN across rotation is a later, separately reviewed
   question.

## Consequences if accepted

- Schema version 5 → 6 (additively). Existing databases need `minerva init`;
  an older binary refuses a version-6 database — the existing fail-closed
  behaviour.
- Minerva gains its first trust boundary beyond the OS user. The threat model
  gains rows: private-key theft on the Athena host, replay of a signed request,
  request floods, and registry tampering by the OS user (who remains inside the
  boundary until D-4).
- Minerva takes a new pinned runtime dependency for ed25519 verification
  (`cryptography` or PyNaCl — chosen at implementation). The dependency set is
  deliberately minimal today, so this addition is itself review material, and
  the verifier joins the same static/network gates as everything else.
- The threat-model line "digest self-consistency does not establish origin or
  authenticity" is amended for signed requests: the digest still does not, but
  the signature over it now does, for registered unrevoked principals only.
- The capability manifest gains an additive entry describing signed-request
  intake; `minerva.capabilities.v2` stays truthful about what does not exist
  until it does.
- Nothing about fulfillment, evidence, findings, or claim status changes. A
  signed request is still only a request for a complete-ledger, work-bounded,
  read-only brief. Minerva still cannot say a claim is true, and no external
  actor can make it say anything.

## Rejected alternatives

- **Shared-secret HMAC, following the Athena–Icarus idiom.** Simpler, and
  already proven in the sibling ecosystem — but Minerva would hold forging
  material, an auditor could not verify attribution from public material, and
  Minerva would inherit a per-peer env-secret lifecycle it has no other reason
  to have. The verifier-must-not-forge property is worth the dependency.
- **URN-only attribution (trust a claimed principal name).** This is the actor
  header with extra steps. ADR 0002 and the threat model refuse it; a name
  without a signature is a claim, not attribution.
- **Mutual TLS or client certificates.** Heavier lifecycle, couples attribution
  to transport, and has no answer for the recommended file-based seam. If a
  loopback endpoint is chosen later, transport hardening is that change's
  review, not this one's.
- **A mutable principals table with a status column.** Violates the append-only
  rule and erases the history of who held which key when; revocation-as-edit is
  exactly the pattern D-9 taught us not to ship.
- **Defer identity until D-4 (real multi-user auth).** D-2's need is narrower
  and sooner: one local seam for one known sibling. Deferring would force the
  adapter and MCP ADRs to each invent identity on their own, which is how a
  fleet ends up with three principal models.
