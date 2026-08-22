# Persistent-corpus research-quality evaluation — 2026-08-22

## Scope

This evaluation closes the planned research-quality, uncertainty, and operator-effort
slice before integration. It reads Minerva's owner-managed persistent local corpus,
emits aggregate metrics only, and omits content, identifiers, and filesystem paths.
It performs no network or provider calls and refuses a corpus with fewer than three
missions.

Command, with the local database path supplied by the operator:

```bash
uv run python scripts/evaluate_research_quality.py \
  --db LOCAL_RESEARCH_DB --minimum-missions 3
```

## Corpus and integrity

- 3 genuine missions, 12 claims, 36 evidence cards, 17 findings, 205 audit events
- Deep doctor: pass at schema 5
- Logical state receipt before and after:
  `5bf9fbc14d34ebe56215ef43f44398f1afc0449f77f718c5c69e18168a80d7aa`
- Read-only assertion: pass
- Provider calls: 0
- Network calls: 0

## Research quality

| Measure | Result |
| --- | ---: |
| Claims with active evidence | 12 / 12 (100%) |
| Claims with active opposing evidence | 2 |
| Claims with both active supporting and opposing evidence | 2 |
| Mixed-stance claims acknowledged as contested or inconclusive | 2 / 2 (100%) |
| Supported or contested findings with an active citation | 14 / 14 (100%) |

These are structural provenance measures. They verify that conclusions remain tied to
active evidence and that recorded contradiction is acknowledged; they do not
independently establish external truth or source quality.

## Uncertainty

| Measure | Result |
| --- | ---: |
| Findings with explicit uncertainty text | 17 / 17 (100%) |
| Claims with a recorded workflow status | 12 / 12 (100%) |
| Inconclusive or unresolved findings | 3 |

The result shows that uncertainty has a durable place in the current corpus. It does
not grade whether each uncertainty statement is sufficiently cautious.

## Operator effort

The evaluator derives effort from actual append-only audit sequences rather than a
hard-coded workflow step count.

| Measure across three missions | Minimum | Median | Maximum |
| --- | ---: | ---: | ---: |
| Audited domain events to first evidence | 10 | 11 | 12 |
| Mission creation to first evidence | 1.862s | 1.905s | 89.146s |
| First source import to first evidence | 0.545s | 1.383s | 54.148s |

Audited events are a lower bound on effort. They do not count reading time, clicks,
keystrokes, or deliberation that occurred outside Minerva. Three missions establish a
baseline, not an SLA or trend.

## Conclusion

The planned evaluation surface is implemented and exercised against the persistent
corpus. It is repeatable, privacy-bounded, and read-only. Continued use should rerun
the same instrument as genuine missions accrue; independent factual review remains a
human research responsibility.
