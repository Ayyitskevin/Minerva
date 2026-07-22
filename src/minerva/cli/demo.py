"""Create Minerva's disposable, synthetic, fully offline demonstration."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from minerva.cli._common import Outcome, run_safely
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError
from minerva.core.operations import OperationsService
from minerva.core.types import IdentityContext, system_identity
from minerva.evidence.models import EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.research.models import FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.models import SourceSnapshot
from minerva.sources.service import SourceService
from minerva.synthesis.service import SynthesisService

_MARKDOWN_NAME = "research-brief.md"
_JSON_NAME = "research-brief.json"


def _span(content: bytes, quote: str) -> tuple[int, int]:
    encoded_quote = quote.encode("utf-8")
    start = content.index(encoded_quote)
    return start, start + len(encoded_quote)


def _preflight(database_path: Path, output_directory: Path) -> None:
    if database_path.exists() or database_path.is_symlink():
        raise ConflictError("database_exists", "Refusing to overwrite an existing database.")
    if output_directory.is_symlink() or (
        output_directory.exists() and not output_directory.is_dir()
    ):
        raise IntegrityError("export_path_invalid", "The export directory is invalid.")
    for filename in (_MARKDOWN_NAME, _JSON_NAME):
        target = output_directory / filename
        if target.exists() or target.is_symlink():
            raise ConflictError(
                "export_target_exists",
                "Refusing to overwrite an existing research brief.",
            )


def _add_evidence(
    evidence_service: EvidenceService,
    *,
    mission_id: str,
    claim_id: str,
    snapshot: SourceSnapshot,
    content: bytes,
    quote: str,
    stance: EvidenceStance,
    identity: IdentityContext,
) -> str:
    start, end = _span(content, quote)
    return evidence_service.add_evidence(
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot.snapshot_id,
        start_byte=start,
        end_byte=end,
        quote=quote,
        stance=stance,
        identity=identity,
    ).id


def create_demo(database_path: Path, output_directory: Path) -> Outcome:
    """Create the synthetic mission and deterministic export after refusal preflight."""
    _preflight(database_path, output_directory)

    database = Database(database_path)
    identity = system_identity(purpose="synthetic offline demonstration")
    OperationsService(database).initialize(identity=identity, refuse_existing=True)
    research = ResearchService(database)
    sources = SourceService(database)
    evidence = EvidenceService(database)

    mission = research.create_mission(
        title="Comparing local AI inference strategies",
        objective=(
            "Compare reproducibility and time-to-result without treating synthetic "
            "observations as universal conclusions."
        ),
        identity=identity,
    )
    question = research.add_question(
        mission_id=mission.id,
        text=(
            "How do pinned and adaptive local inference strategies trade off "
            "reproducibility and time-to-result?"
        ),
        identity=identity,
    )
    reproducibility_claim = research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement=(
            "Pinned local inference runtimes produce more reproducible results "
            "than adaptive runtimes."
        ),
        falsification_criteria=(
            "Across controlled repeats, adaptive runtimes show equal or lower result variance."
        ),
        identity=identity,
    )
    alternative_reproducibility_claim = research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement=(
            "Adaptive local inference runtimes are at least as reproducible as pinned runtimes."
        ),
        falsification_criteria=(
            "Across controlled repeats, pinned runtimes show lower result "
            "variance than adaptive runtimes."
        ),
        identity=identity,
    )

    synthetic_sources = (
        (
            "synthetic/pinned-repeats.txt",
            "Across five controlled repeats, the pinned runtime selected identical "
            "dependencies and produced identical result digests.",
        ),
        (
            "synthetic/adaptive-repeats.txt",
            "Across five controlled repeats, the adaptive runtime produced identical "
            "result digests while the pinned runtime had one divergent cold start.",
        ),
        (
            "synthetic/adaptive-timing.txt",
            "The adaptive runtime reached a usable result in 18 seconds; the pinned "
            "runtime required 31 seconds.",
        ),
        (
            "synthetic/pinned-timing.txt",
            "With a warm local cache, the pinned runtime reached a usable result 7 "
            "seconds before the adaptive resolver.",
        ),
    )
    imported: list[tuple[SourceSnapshot, bytes, str]] = []
    for label, text in synthetic_sources:
        content = text.encode("utf-8")
        snapshot = sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label=label,
            media_type="text/plain",
            identity=identity,
        )
        imported.append((snapshot, content, text))

    support_reproducibility = _add_evidence(
        evidence,
        mission_id=mission.id,
        claim_id=reproducibility_claim.id,
        snapshot=imported[0][0],
        content=imported[0][1],
        quote=imported[0][2],
        stance=EvidenceStance.SUPPORTS,
        identity=identity,
    )
    oppose_reproducibility = _add_evidence(
        evidence,
        mission_id=mission.id,
        claim_id=reproducibility_claim.id,
        snapshot=imported[1][0],
        content=imported[1][1],
        quote=imported[1][2],
        stance=EvidenceStance.OPPOSES,
        identity=identity,
    )
    support_alternative = _add_evidence(
        evidence,
        mission_id=mission.id,
        claim_id=alternative_reproducibility_claim.id,
        snapshot=imported[1][0],
        content=imported[1][1],
        quote=imported[1][2],
        stance=EvidenceStance.SUPPORTS,
        identity=identity,
    )
    oppose_alternative = _add_evidence(
        evidence,
        mission_id=mission.id,
        claim_id=alternative_reproducibility_claim.id,
        snapshot=imported[0][0],
        content=imported[0][1],
        quote=imported[0][2],
        stance=EvidenceStance.OPPOSES,
        identity=identity,
    )

    research.add_finding(
        mission_id=mission.id,
        statement=(
            "The synthetic comparison does not resolve a universally preferable "
            "local inference strategy."
        ),
        statement_kind=StatementKind.AGENT_INFERENCE,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty=(
            "The small synthetic sample does not isolate hardware, cache, or workload effects."
        ),
        evidence_ids=(
            support_reproducibility,
            oppose_reproducibility,
            support_alternative,
            oppose_alternative,
        ),
        identity=identity,
    )
    research.add_finding(
        mission_id=mission.id,
        statement="The synthetic benchmark represents typical local developer workloads.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="This assumption has not been validated against real workloads.",
        evidence_ids=(),
        identity=identity,
    )
    research.add_finding(
        mission_id=mission.id,
        statement="How do the strategies behave across different local accelerators?",
        statement_kind=StatementKind.UNRESOLVED_QUESTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="No cross-hardware synthetic observations are included.",
        evidence_ids=(),
        identity=identity,
    )

    export = SynthesisService(database).export_brief(
        mission_id=mission.id,
        output_dir=output_directory,
        identity=identity,
    )
    return Outcome(
        {
            "status": "demo_created",
            "mission_id": mission.id,
            "claim_ids": [reproducibility_claim.id, alternative_reproducibility_claim.id],
            "evidence_ids": [
                support_reproducibility,
                oppose_reproducibility,
                support_alternative,
                oppose_alternative,
            ],
            "export_digest": export.export_digest,
            "export_files": [_MARKDOWN_NAME, _JSON_NAME],
            "review_url": "http://127.0.0.1:8765/",
            "next_step": (
                "Run minerva serve --db <the-demo-database-you-supplied> "
                "and open the loopback review URL."
            ),
        }
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minerva-demo",
        description="Create an offline synthetic Minerva research mission.",
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument(
        "--export-dir",
        type=Path,
        help="new export directory (default: <database-stem>-export beside the database)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_path = Path(args.db)
    output_directory = (
        Path(args.export_dir)
        if args.export_dir is not None
        else database_path.with_name(f"{database_path.stem}-export")
    )
    return run_safely(lambda: create_demo(database_path, output_directory))


if __name__ == "__main__":
    raise SystemExit(main())
