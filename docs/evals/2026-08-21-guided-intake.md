# Guided Evidence Intake v1 evaluation — 2026-08-21

## Decision and assumptions

Kevin selected two explicit audited commits: digest-pinned source import first,
evidence filing second. He delegated the remaining choices to the implementing seat
and requested the recommended option each time. The resulting assumptions were:

- agents need a non-interactive JSON CLI rather than a TTY wizard;
- exact matching is safer than fuzzy or model-assisted selection for citation bytes;
- repeated text must be surfaced completely under a fixed bound, never resolved by
  silently taking the first occurrence;
- one reviewed preview must bind snapshot identity, quote, candidate order, and the
  mission state observed before filing;
- source import, immutable snapshot state, evidence validation, and audit storage
  remain owned by their existing services.

The risky-change workflow normally adds external comparative research. Kevin had
already declined DeepAPI and explicitly overrode external comparative research for
this Minerva season. No web or provider research was substituted silently. This
evaluation therefore uses repository evidence plus live local measurement, as
recorded in `docs/NEXT_LEVEL_PLAN.md`.

## Reproducible measurement

Run from the repository root:

```bash
uv run python scripts/evaluate_intake.py
```

The script creates a fresh temporary SQLite database and 20 local UTF-8 source files.
Every case exercises the real four-operation path: safe file preview, digest-pinned
immutable import, exact-quote intake preview, and explicit intake filing. Cases cover
unique, repeated, and overlapping text; start/end boundaries; long bounded context;
newlines and tabs; composed and decomposed accents; emoji; and Arabic, Chinese,
Cyrillic, Devanagari, Greek, Hebrew, Japanese, Korean, and Spanish text.

Observed result:

| Measure | Result |
| --- | ---: |
| Realistic cases | 20 |
| Successful source-to-evidence paths | 20/20 |
| Exact UTF-8 span accuracy | 1,000,000 ppm |
| Expected candidate-count accuracy | 1,000,000 ppm |
| Source preview/import digest binding | 1,000,000 ppm |
| Preview left evidence/audit state unchanged | 1,000,000 ppm |
| Evidence creation audit binding | 1,000,000 ppm |
| Stale/replayed preview refusal | 1,000,000 ppm |
| Re-previewed exact-duplicate refusal | 1,000,000 ppm |
| Operator operations from local file to evidence | 4 |
| Provider invocations | 0 |
| Network invocations | 0 |
| Schema version changed | no (remained 5) |
| Deep doctor after all cases | pass |

The checked-in regression calls the evaluator twice and requires byte-equivalent
results, then runs the CLI entry point and requires one stable JSON document.

## Interpretation

The measurement supports the implementation choice: exact-quote guidance removes
manual byte arithmetic while preserving immutable source custody and explicit human
or agent judgment. It does not show that exact matching is sufficient for PDF, OCR,
HTML, URL, fuzzy, or semantic retrieval; those capabilities were outside the tested
scope and remain closed.

Twenty fixed realistic fixtures are not genuine adoption or production traffic. They
prove deterministic behavior on the intended path, not that operators will select the
right claim, occurrence, stance, or source. Real use should be measured after a
non-author review and owner-approved integration; synthetic records from this suite
never enter the persistent mickey database.
