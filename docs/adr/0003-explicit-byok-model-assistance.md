# ADR 0003: Require explicit BYOK consent for bounded model assistance

- Status: Accepted
- Date: 2026-07-22

## Context

Minerva's Milestone 1 evidence workflow is deliberately offline, but a human operator
may benefit from optional model-drafted finding candidates after evidence has already
been captured and cited. A general model abstraction, automatic background call, or
opaque summarization step would weaken the local-first boundary, hide what leaves the
machine, create credential and spending risk, and blur model text with evidence.

An external request also cannot be made transactionally atomic with SQLite. A provider
can process or bill a request even when a timeout, connection loss, or process death
prevents Minerva from receiving or recording its result.

## Decision

Milestone 2B permits one narrow model surface: `minerva assist finding-candidates`.
There is no API or web invocation surface. The base distribution has no provider SDK;
operators install `ai-openai`, `ai-anthropic`, or the aggregate `ai` extra.

The CLI first performs a network-free preview. It serializes bounded canonical JSON
containing one claim's ID, statement, and falsification criterion plus every active
evidence excerpt's citation ID, quote, and stance. Withdrawn evidence is excluded and
identified separately; opposing and inconclusive evidence remains visible. The
preview prints that exact JSON, fixed destination, limits, hashes, and a request
SHA-256. Byte offsets, snapshot digests, and supersession references remain local and
are bound into the request digest as provenance; they are not sent to the provider.

Egress requires a second invocation with `--confirm-external-send` and the exact
`--expected-request-sha256` from a fresh preview. The digest binds provider, model,
fixed destination, prompt, exact context, active-evidence provenance, candidate count,
and output-token limit. A bound context or parameter change requires new consent.

Credentials are BYOK values read only after authorization from `OPENAI_API_KEY` or
`ANTHROPIC_API_KEY`. Provider/model preferences may come from CLI arguments or
`MINERVA_AI_PROVIDER` and `MINERVA_AI_MODEL`; credentials are never CLI arguments.
Minerva keeps credentials in memory for the call and does not persist them.

Only `src/minerva/integrations/ai/openai.py` and
`src/minerva/integrations/ai/anthropic.py` may import their provider SDK and network
client. Requests go only to `https://api.openai.com/v1/responses` or
`https://api.anthropic.com/v1/messages`. Adapters ignore proxy environment variables,
fail closed on SDK environment controls that could inject headers or account routing,
refuse redirects, make one attempt with no SDK retry or provider fallback, expose no
tools or external retrieval, and request strict structured output. OpenAI requests set
`store=false`; provider retention not controlled by that flag remains subject to the
operator's account and provider terms. The operator owns disclosure authority and
cost responsibility.

Returned data is untrusted. Minerva validates the structured schema, bounds, provider
metadata, evidence-ID membership, secret patterns, and unchanged post-call context.
Accepted text is returned only as ephemeral `agent_inference` candidates with explicit
uncertainty. It is not stored, automatically adopted, treated as evidence, used to
determine truth/confidence, or allowed to change claim status.

A metadata-only requested audit event commits before the call and a separate terminal
event commits after a received outcome. Neither contains credentials, prompts,
evidence text, response text, or candidates. This audit is intentionally non-atomic
with the provider. Timeout and connection errors are recorded as unknown outcomes and
are never retried automatically.

Provider tests, installed-artifact checks, and CI use synthetic inputs and fakes only.
They never load a real API key, contact a live provider, or create a billable request.

## Consequences

- Operators see and authorize the exact bounded disclosure instead of consenting to a
  vague task description.
- The base installation and all Milestone 1 workflows remain offline-capable.
- Optional provider SDKs and their network attack surface are isolated and testable.
- Candidate generation can help drafting without changing Minerva's evidence model.
- Minerva cannot guarantee provider retention behavior, price, availability, model
  quality, or a definitive outcome after interruption.
- Audit chronology is honest but cannot prove that every requested call reached a
  provider or that every provider outcome was received.

## Rejected alternatives

- Automatic or background model calls: hide disclosure and spending decisions.
- Consent to a mutable task without an exact digest: permits context drift between
  review and send.
- API/web invocation: expands the caller, authentication, and browser threat boundary.
- Persistent provider credentials or candidate output: creates secret-management and
  provenance ambiguity without a product requirement.
- Automatic retry or fallback: can duplicate disclosure and cost after an unknown
  outcome and changes which provider receives the data.
- Model tools, URL retrieval, or autonomous research: breaks the bounded evidence-only
  request and requires a separate milestone and threat model.
- Treating model output as evidence or an automatic finding: violates the provenance
  doctrine and bypasses human review.
