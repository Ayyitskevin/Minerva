# Controlled mission cockpit evaluation — 2026-08-21

## Scope

This evaluation covers the action-first mission cockpit and its first controlled-write
slice: claim creation, append-only claim status decisions, and finding creation. The
change is based on `origin/main` at `ee4edb6`, is not deployed or released, and
received no external-provider or DeepAPI traffic. Kevin previously declined DeepAPI;
the substitute evidence is the real local corpus plus disposable-database mutation and
refusal cases.

## Preconditions

- Live database: owner-managed local research database (path intentionally omitted)
- Live database before measurement: SHA-256
  `3c7eacdb2c40e753242ab630ed8c8ee9b763371357476515a739faceb96c5a81`,
  205 audit events, three missions
- Write/refusal measurement: temporary initialized databases created by pytest
- Focused command:
  `uv run pytest tests/test_web_security.py tests/test_research.py tests/test_web.py --no-cov -q`

## Realistic cases

| # | Case | Result |
| ---: | --- | --- |
| 1 | Render live sibling-ownership mission through the new app | Pass: HTTP 200, 29,231 bytes |
| 2 | Render live checkout-ownership mission through the new app | Pass: HTTP 200, 21,950 bytes |
| 3 | Render live Minerva dogfood mission through the new app | Pass: HTTP 200, 17,550 bytes |
| 4 | Verify action cockpit precedes controlled writes and research history on all three live missions | Pass: strict ordering true for all three |
| 5 | Verify live pages expose only per-claim status plus claim/finding forms | Pass: 7, 6, and 5 forms for 5, 4, and 3 claims |
| 6 | Issue a signed CSRF cookie on first cockpit GET | Pass |
| 7 | Reuse the valid cookie without another Set-Cookie response | Pass |
| 8 | Create a claim through the strict form adapter | Pass: 303; one claim, status, and domain audit plus run receipt |
| 9 | Replay the stale claim-creation form | Pass: 409 `mission_version_conflict`; no additional state |
| 10 | Submit a claim form without Origin | Pass: 403 `form_origin_required`; no state |
| 11 | Submit a claim form without CSRF field | Pass: 403 `csrf_invalid`; no state |
| 12 | Submit a tampered signed token | Pass: 403 `csrf_invalid`; no state |
| 13 | Submit an unknown form field | Pass: 422 `form_contract_invalid`; no state |
| 14 | Submit the wrong media type | Pass: 415 `form_content_type_invalid`; no state |
| 15 | Append a claim status with current version and active opposing/supporting evidence | Pass: 303; one status row plus two audit receipts |
| 16 | Replay the stale status version | Pass: 409 `claim_version_conflict`; no additional state |
| 17 | Record an explicit assumption finding with current mission sequence | Pass: 303; one finding plus two audit receipts |
| 18 | Replay the stale finding form | Pass: 409 `mission_version_conflict`; no additional state |
| 19 | Compose mission queue and cockpit context in one read snapshot | Pass: exactly one `Database.read()` transaction |
| 20 | Reject stale service-level claim/finding creation before partial rows | Pass: claim/status/finding/citation/audit/run counts unchanged |

Focused result: 113 passed in 5.92 seconds. The full repository suite then passed
1,169 tests at 91.69% coverage. All eleven required gates passed, including locked
sync, Ruff, formatting, mypy over 74 source files, build, wheel/sdist verification,
installed-wheel smoke, static security over 72 Python files, dependency compatibility,
and diff whitespace. The only warning is the existing TestClient/httpx deprecation.

## Live-data non-mutation check

The live cases used GET only. After all three renders, the database SHA-256 remained
`3c7eacdb2c40e753242ab630ed8c8ee9b763371357476515a739faceb96c5a81` and the audit
count remained 205. The CSRF cookie existed only in the evaluator client. No live
research row, audit event, file export, provider request, network egress, deployment,
or publication was produced.

## Findings

- The canonical mission page can be action-first without turning the deterministic
  Mission Research Queue receipt into persisted task or priority state.
- Mission audit sequence is an effective schema-free freshness token for create
  commands because every successful mission mutation already advances the append-only
  audit ledger.
- A successful browser command produces two audit receipts when its local run is new:
  the run-start receipt and the domain event. Tests pin that behavior explicitly.
- The controlled browser layer is intentionally narrower than the CLI/API. Generic
  CRUD, source intake, evidence attachment, retraction, withdrawal, assistance, and
  adoption remain absent.
- The real corpus is still small; rendering success and invariant checks establish
  operational fit, not research quality or external validity.

## Release gate

This measurement supports implementation readiness, not integration authority. The
eleven repository gates pass; one non-author review is still required. Human review is
mandatory before merging because this amends the loopback/browser trust boundary.
