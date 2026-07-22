from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.research.models import Claim, Mission, Question
from minerva.research.service import ResearchService
from minerva.sources.models import SourceSnapshot
from minerva.sources.service import SourceService
from minerva.synthesis.service import SynthesisService


class SequenceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


def fixed_clock() -> str:
    return "2026-07-22T12:00:00.000000Z"


@dataclass(frozen=True, slots=True)
class ClaimSeed:
    mission: Mission
    question: Question
    claim: Claim
    snapshot: SourceSnapshot
    content: bytes


@dataclass(slots=True)
class Lab:
    database: Database
    identity: IdentityContext
    ids: SequenceIds
    research: ResearchService
    sources: SourceService
    evidence: EvidenceService
    synthesis: SynthesisService

    def seed_claim(
        self,
        *,
        content: bytes = (
            b"Evidence supports the claim.\n"
            b"Evidence opposes the claim.\n"
            b"Caf\xc3\xa9 context remains uncertain.\n"
        ),
        source_label: str = "notes/source.txt",
    ) -> ClaimSeed:
        mission = self.research.create_mission(
            title="Bounded research mission",
            objective="Evaluate a falsifiable proposition from exact local evidence.",
            identity=self.identity,
        )
        question = self.research.add_question(
            mission_id=mission.id,
            text="Does the recorded evidence support the proposition?",
            identity=self.identity,
        )
        claim = self.research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="The proposition is supported by the cited source.",
            falsification_criteria="An exact opposing observation would falsify the proposition.",
            identity=self.identity,
        )
        snapshot = self.sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label=source_label,
            media_type="text/plain",
            identity=self.identity,
        )
        return ClaimSeed(mission, question, claim, snapshot, content)

    def cite(
        self,
        seed: ClaimSeed,
        quote: str,
        stance: EvidenceStance,
        *,
        supersedes_evidence_id: str | None = None,
    ) -> EvidenceCard:
        quoted_bytes = quote.encode("utf-8")
        start = seed.content.index(quoted_bytes)
        return self.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=start,
            end_byte=start + len(quoted_bytes),
            quote=quote,
            stance=stance,
            identity=self.identity,
            supersedes_evidence_id=supersedes_evidence_id,
        )


@pytest.fixture
def database(tmp_path: Path) -> Database:
    result = Database(tmp_path / "research.db")
    result.initialize()
    return result


@pytest.fixture
def lab(database: Database) -> Lab:
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify Minerva invariants",
    )
    return Lab(
        database=database,
        identity=identity,
        ids=ids,
        research=ResearchService(database, clock=fixed_clock, id_factory=ids),
        sources=SourceService(database, clock=fixed_clock, id_factory=ids),
        evidence=EvidenceService(database, clock=fixed_clock, id_factory=ids),
        synthesis=SynthesisService(database, clock=fixed_clock, id_factory=ids),
    )
