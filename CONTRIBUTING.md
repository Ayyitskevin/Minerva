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

Run the complete command list in `AGENTS.md`. The branch-coverage floor is not a
security claim; it prevents a greenfield project from accumulating large untested
regions while invariant-specific negative tests provide the meaningful assurance.

The floor is a ratchet, currently **88%** against a measured 90.00%. Raise it only
after the measured figure has held above the intended floor with a couple of points
of headroom, and never by lowering it to make a red gate green: coverage that
disappeared is a change to explain, not a threshold to adjust.

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

### Commit attribution

Every commit records who or what wrote it. A commit authored with machine assistance
carries a `Co-Authored-By:` trailer naming the model, in addition to the human author
who reviewed and accepted it:

```
Co-Authored-By: <Model Name> <noreply@anthropic.com>
```

The human author remains accountable for the change. The trailer records how it was
produced, not who is responsible for it, and it is never a substitute for reading the
diff. Do not rewrite another author's commits to add or change attribution.

## Releasing

Releases are tags plus recorded evidence. There is no deployment, no package index
upload, and no external publication step in this repository.

1. Confirm the working tree is clean and the branch is even with `main`.
2. Run every gate in `AGENTS.md` and record the **observed** output — test count,
   coverage figure, and the distribution filenames `verify_dist.py` reports. A gate
   that was skipped or unavailable is recorded as open verification, never as a pass.
3. Update `CHANGELOG.md`: the release heading, the date, and what changed. Entries
   describe behaviour a reader would notice, not commit subjects.
4. Confirm `version` in `pyproject.toml` is exactly the version being tagged. An
   `aN`/`bN`/`rcN` suffix means the tag must carry it too; dropping the suffix is a
   product decision that says the pre-release period is over, and it is made
   deliberately rather than as a side effect of tagging.
5. Create an annotated tag `v<version>` whose message carries the gate evidence from
   step 2, then push the tag.
6. Verify the tag: build from a clean checkout of it and confirm `verify_dist.py` and
   `installed_smoke.py` still pass against the artifacts that checkout produces.

Never move or delete a published tag. A tag that turns out to be wrong is superseded
by the next one, with the reason recorded in `CHANGELOG.md` — the same no-overwrite
rule the rest of the system follows.
