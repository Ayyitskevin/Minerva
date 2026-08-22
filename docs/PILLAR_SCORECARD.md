# Pillar scorecard

Baseline: 2026-08-21

This scorecard turns Minerva's vision into falsifiable operating evidence.
Scores are judgment summaries; the linked measurements are the claims that
matter.

## Scale

- 0 — only an idea
- 1 — designed or prototyped
- 2 — implemented with narrow verification
- 3 — exercised against a real local corpus
- 4 — repeatable operating evidence with a maintained feedback loop

## Baseline

| Pillar | Score | Evidence | Next bar |
| --- | ---: | --- | --- |
| Research integrity | 4 | Deep doctor passed schema, SQLite, triggers, 17 snapshots, 36 citations, 17 findings, 205 audits, and 228 material-row reconciliations | Keep every live doctor check green as the corpus grows |
| Operator legibility | 3 | Three real missions reached first evidence after 10/11/12 audited domain events; median mission-to-evidence time was 1.905s | Repeat after deployment and enough genuine missions to establish a trend |
| Safety and control | 3 | Loopback-only runtime; complete source preview is read-only; digest mismatch refuses before persistence; 227 focused reviewer-regression tests passed | Add repeated real operator use and retain refusal tests in the full suite |
| Reliability and recovery | 3 | Nightly timer active; a real backup restored in 0.22s and deep doctor passed in 0.21s | Repeat drills across three backup ages before declaring an RTO trend |
| Real use and adoption | 3 | Persistent corpus has 3 genuine missions, 12 claims, 17 snapshots, 36 citations, and 17 findings; all claims have active evidence | Track completed research questions, corrections, and briefs actually consumed |
| Sustainability | 2 | Status, scorecard, evaluation, changelog, and Apache-2.0 metadata exist; all eleven gates pass | Receive non-author review, then publish a release with notes |

Overall baseline: **3.0 / 4.0**. This is not a confidence score or a claim that
Minerva is production-ready. The weakest pillar controls the next investment:
sustainability must reach 3 before opening a new protocol or identity gate.

## Operating measures

Measure these from real missions; never manufacture synthetic success counts.

| Measure | Definition | Baseline |
| --- | --- | --- |
| Time to first evidence | Mission creation to first persisted evidence card | 1.905s median across 3 genuine missions; 1.862–89.146s range, not an SLA |
| Retrieval-to-adoption rate | Lens candidates explicitly adopted divided by candidates reviewed | Not yet instrumented |
| Opposition coverage | Claims with active opposing evidence, or an explicit structural cue showing none | 2 of 12 claims have active opposition; both mixed-stance claims are contested or inconclusive |
| Finding citation coverage | Supported/contested findings with at least one active citation | 14 of 14 (100%) |
| Explicit uncertainty | Findings with non-empty uncertainty text | 17 of 17 (100%) |
| Recovery observation | Restore plus deep-doctor wall time on a fresh destination | 0.43s combined for one 503,808-byte backup; not an SLA |
| Backup recency | Age of newest verified backup | Timer active; do not infer integrity from age alone |
| Workbench correctness | Real-corpus GET views returning complete receipts without mutation | 6 of 6 sampled views passed |
| Gate health | Repository completion commands passing at the same commit | Pass: 1,200 tests at 91.65% coverage plus all ten companion gates |

## Investment rule

Improve the lowest-scoring pillar with the smallest reversible change. A new
provider, protocol, remote surface, or trust model does not raise a score unless
it improves a measured operator outcome without weakening integrity, safety, or
recovery.
