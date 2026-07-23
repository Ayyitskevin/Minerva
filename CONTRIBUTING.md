# Contributing

## Development setup

Development and CI are supported on Linux/POSIX with Python 3.12, 3.13, or 3.14.
Other operating systems are currently unverified. Install `uv`, then create the
locked development environment:

```bash
uv sync --extra dev
```

Update `uv.lock` intentionally with `uv lock`; CI uses `--frozen` and rejects drift.
Do not add a runtime dependency when the standard library or an existing dependency
can implement the requirement clearly and safely.

## Design and implementation

Read the product requirements, architecture, threat model, and accepted ADRs before
editing. Add or amend an ADR when changing a durable contract such as citation
coordinates, snapshot identity, export canonicalization, audit semantics, or a system
boundary.

Domain validation belongs in commands/services. Adapters parse requests and render
responses. Tests should prove why an invariant exists and must fail if it is removed.
Use only synthetic, non-sensitive fixtures.

## Verification

Run the complete command list in `AGENTS.md`. The 85% initial branch-coverage floor is
not a security claim; it prevents a greenfield project from accumulating large
untested regions while invariant-specific negative tests provide the meaningful
assurance. Raise the floor as the application stabilizes.

Build verification must inspect both sdist and wheel package data and run the wheel
from outside the checkout. Security verification combines dynamic adversarial tests
with a static ban on execution surfaces and on network clients outside the exact
reviewed provider adapters. Only `src/minerva/integrations/ai/openai.py` and
`src/minerva/integrations/ai/anthropic.py` may import their provider SDK and `httpx`;
expanding that allowlist is a security-boundary change requiring an ADR/review and
negative tests.

Provider tests must use injected or monkeypatched fakes and synthetic evidence. They
must never use a real API key, contact a live provider, depend on provider availability,
or create a billable request. Test the base installation without provider extras as
well as each optional extra so development dependencies do not hide packaging errors.

## Changes and review

Keep commits coherent and diffs surgical. PR descriptions must state observed command
results, not anticipated results. A change is not merge-ready while exact-head CI is
red, the branch is stale, or confirmed blocker/high/medium review findings remain.
Minerva is not deployed or externally published as part of repository development.
