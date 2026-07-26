#!/usr/bin/env python3
"""Rebuild the checked-in golden fixtures from a deterministic scenario.

Golden fixtures pin exact canonical bytes for `minerva.research-brief.v2` and
`minerva.research-request.v1`. Before this script they could only be updated by
hand, which is how a fixture and the contract it pins drift apart without either
looking wrong.

The default mode is `--check`: it rebuilds both fixtures in memory and reports
whether the checked-in bytes still match, changing nothing. `--write` updates
them, and prints the semantic diff first.

**Regenerating is never how a failure gets fixed.** A golden that stops matching
means either the contract changed on purpose or something broke; this script
cannot tell you which, and rewriting the fixture makes the question unanswerable.
Read the diff, decide which it is, and only then write. Bytes changing with no
intended contract change is a defect in the code, not a stale fixture.

This script deliberately re-declares its scenario rather than importing the test
suite's. Sharing the code would make the two definitions equal by construction
and prove nothing; instead `test_golden_fixtures_are_reproducible_by_the_script`
runs this script in check mode, so the script, the test suite's scenario, and the
checked-in bytes are all pinned to each other and cannot diverge silently.

Not a release gate: this is a developer tool, and the byte equality it would
assert is already asserted by the test suite.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.integrations.research_request import (
    build_research_request,
    serialize_research_request,
)
from minerva.research.models import FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService
from minerva.synthesis.service import SynthesisService

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
BRIEF_FIXTURE = FIXTURES / "minerva.research-brief.v2.golden.json"
REQUEST_FIXTURE = FIXTURES / "minerva.research-request.v1.golden.json"

# Identifiers, timestamps, and actor come from fixed generators so the output is
# a pure function of the code. Any byte difference is a contract difference.
FIXED_TIMESTAMP = "2026-07-22T12:00:00.000000Z"
ACTOR_ID = "os-user:test"
RUN_PURPOSE = "verify Minerva invariants"

SOURCE_CONTENT = (
    b"Evidence supports the claim.\n"
    b"Evidence opposes the claim.\n"
    b"Caf\xc3\xa9 context remains uncertain.\n"
)
SOURCE_LABEL = "notes/source.txt"

REQUEST_MISSION_ID = "mis_00000000000000000000000000000001"
REQUEST_CLAIM_ID = "clm_00000000000000000000000000000002"
REQUEST_EVIDENCE_IDS = (
    "evd_00000000000000000000000000000003",
    "evd_00000000000000000000000000000004",
)


class SequenceIds:
    """Deterministic identifier factory: the nth identifier is always the nth."""

    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


def fixed_clock() -> str:
    return FIXED_TIMESTAMP


def build_brief_fixture() -> bytes:
    """Return the canonical packet bytes for the golden research scenario.

    One mission, one question, one contested claim, one source, two citations
    taking opposite stances, and three statements: a cited observed fact, an
    uncited assumption, and an uncited unresolved question. The opposing
    citation and the contested status are the point -- a golden that recorded
    only agreement would not exercise the contradiction-preserving contract.
    """

    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "golden.sqlite3")
        database.initialize()

        ids = SequenceIds()
        identity = IdentityContext(
            actor_id=ACTOR_ID,
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose=RUN_PURPOSE,
        )
        research = ResearchService(database, clock=fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=fixed_clock, id_factory=ids)
        evidence = EvidenceService(database, clock=fixed_clock, id_factory=ids)
        synthesis = SynthesisService(database, clock=fixed_clock, id_factory=ids)

        mission = research.create_mission(
            title="Bounded research mission",
            objective="Evaluate a falsifiable proposition from exact local evidence.",
            identity=identity,
        )
        question = research.add_question(
            mission_id=mission.id,
            text="Does the recorded evidence support the proposition?",
            identity=identity,
        )
        claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="The proposition is supported by the cited source.",
            falsification_criteria=("An exact opposing observation would falsify the proposition."),
            identity=identity,
        )
        snapshot = sources.import_bytes(
            mission_id=mission.id,
            content=SOURCE_CONTENT,
            original_label=SOURCE_LABEL,
            media_type="text/plain",
            identity=identity,
        )

        def cite(quote: str, stance: EvidenceStance) -> str:
            quoted = quote.encode("utf-8")
            start = SOURCE_CONTENT.index(quoted)
            return evidence.add_evidence(
                mission_id=mission.id,
                claim_id=claim.id,
                snapshot_id=snapshot.snapshot_id,
                start_byte=start,
                end_byte=start + len(quoted),
                quote=quote,
                stance=stance,
                identity=identity,
            ).id

        support = cite("Evidence supports the claim.", EvidenceStance.SUPPORTS)
        cite("Evidence opposes the claim.", EvidenceStance.OPPOSES)

        research.add_finding(
            mission_id=mission.id,
            claim_id=claim.id,
            statement="The source contains a direct supporting observation.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.CONTESTED,
            uncertainty="The same source also contains an opposing observation.",
            evidence_ids=(support,),
            identity=identity,
        )
        research.add_finding(
            mission_id=mission.id,
            statement="The local observation is representative of a wider population.",
            statement_kind=StatementKind.ASSUMPTION,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="Representativeness has not been established.",
            evidence_ids=(),
            identity=identity,
        )
        research.add_finding(
            mission_id=mission.id,
            statement="Which independent source can resolve the contradiction?",
            statement_kind=StatementKind.UNRESOLVED_QUESTION,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="No independent source has been imported.",
            evidence_ids=(),
            identity=identity,
        )

        return synthesis.build_brief(mission.id).json


def build_request_fixture() -> bytes:
    """Return the canonical request bytes for the golden request scenario.

    The request contract is storage-independent, so this needs no database: the
    identifiers are synthetic by design and the digest is a pure function of
    them.
    """

    return serialize_research_request(
        build_research_request(
            mission_id=REQUEST_MISSION_ID,
            claim_id=REQUEST_CLAIM_ID,
            expected_active_citation_ids=REQUEST_EVIDENCE_IDS,
        )
    )


def _readable(data: bytes) -> list[str]:
    """Expand canonical single-line JSON so a diff shows the field that moved."""

    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data.decode("utf-8", errors="replace").splitlines(keepends=True)
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).splitlines(
        keepends=True
    )


def _report(path: Path, rebuilt: bytes) -> bool:
    """Print any difference between the checked-in fixture and *rebuilt*."""

    name = path.name
    if not path.exists():
        print(f"{name}: MISSING (would be created, {len(rebuilt)} bytes)")
        return False
    current = path.read_bytes()
    if current == rebuilt:
        print(f"{name}: unchanged ({len(current)} bytes)")
        return True
    print(f"{name}: DIFFERS ({len(current)} -> {len(rebuilt)} bytes)")
    diff = difflib.unified_diff(
        _readable(current),
        _readable(rebuilt),
        fromfile=f"{name} (checked in)",
        tofile=f"{name} (rebuilt)",
    )
    sys.stdout.writelines(diff)
    print()
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="report whether the fixtures still match (default; writes nothing)",
    )
    group.add_argument(
        "--write",
        action="store_true",
        help="rewrite the fixtures after printing the diff",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rebuilt = {
        BRIEF_FIXTURE: build_brief_fixture(),
        REQUEST_FIXTURE: build_request_fixture(),
    }

    unchanged = [_report(path, data) for path, data in rebuilt.items()]
    if all(unchanged):
        return 0

    if not args.write:
        print(
            "Fixtures differ. Read the diff and decide whether the contract changed "
            "on purpose before running with --write.",
            file=sys.stderr,
        )
        return 1

    for path, data in rebuilt.items():
        path.write_bytes(data)
    print(f"wrote {sum(1 for ok in unchanged if not ok)} fixture(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
