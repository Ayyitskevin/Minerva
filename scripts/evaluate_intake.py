"""Measure guided local source-to-evidence intake on 20 realistic UTF-8 cases."""

from __future__ import annotations

import argparse
import json
import socket
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from unittest.mock import patch

from minerva.core.db import Database, latest_schema_version
from minerva.core.doctor import run_doctor
from minerva.core.errors import MinervaError
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence import EvidenceStance
from minerva.intake import EvidenceIntakePreview, EvidenceIntakeService
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

_CLOCK = "2026-08-21T12:00:00.000000Z"


@dataclass(frozen=True, slots=True)
class _Case:
    label: str
    content: str
    quote: str
    candidate_rank: int
    expected_candidates: int


_CASES = (
    _Case("ascii-unique", "The control group remained stable.", "control group", 1, 1),
    _Case("ascii-repeat", "Baseline rose. Baseline fell.", "Baseline", 2, 2),
    _Case("latin-cjk", "Préface: Café 東京 remained exact.", "Café 東京", 1, 1),
    _Case("emoji", "Observed 🔬 evidence before review.", "🔬 evidence", 1, 1),
    _Case("arabic", "أظهرت النتائج دليلاً قابلاً للمراجعة.", "دليلاً", 1, 1),
    _Case("devanagari", "यह साक्ष्य स्थानीय रिकॉर्ड में है।", "साक्ष्य", 1, 1),
    _Case("combining", "The form Cafe\u0301 is decomposed.", "Cafe\u0301", 1, 1),
    _Case("newline", "First line.\nSecond line is material.", "line.\nSecond", 1, 1),
    _Case("tab", "measure\tvalue\tuncertainty", "value\tuncertainty", 1, 1),
    _Case("overlap", "aaaa", "aa", 2, 3),
    _Case("curly-quotes", "The report called it “provisional”.", "“provisional”", 1, 1),
    _Case("greek", "Η παρατήρηση παραμένει αβέβαιη.", "παραμένει", 1, 1),  # noqa: RUF001
    _Case("cyrillic", "Наблюдение требует проверки.", "требует проверки", 1, 1),
    _Case("spanish", "La medición fue reproducible y explícita.", "medición", 1, 1),
    _Case("chinese", "证据必须保留原始字节。", "保留原始字节", 1, 1),
    _Case("korean", "근거는 정확한 바이트 범위를 유지합니다.", "정확한 바이트", 1, 1),
    _Case("hebrew", "הראיה נשמרת עם מקור מדויק.", "מקור מדויק", 1, 1),
    _Case("long-context", "before " + "x" * 180 + " target " + "y" * 180, "target", 1, 1),
    _Case("start-boundary", "Evidence begins the source.", "Evidence", 1, 1),
    _Case("end-boundary", "The source ends with evidence", "evidence", 1, 1),
)


class _SequenceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


def _fixed_clock() -> str:
    return _CLOCK


def _error_code(action: Callable[[], object]) -> str | None:
    try:
        action()
    except MinervaError as error:
        return error.code
    return None


def evaluate_intake() -> dict[str, object]:
    """Run real file preview/import and evidence intake against a fresh database."""

    with tempfile.TemporaryDirectory(prefix="minerva-intake-evaluation-") as temporary:
        root = Path(temporary) / "sources"
        root.mkdir(mode=0o700)
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:intake-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="measure guided exact-quote intake",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)
        intake = EvidenceIntakeService(database, clock=_fixed_clock, id_factory=ids)

        def _file_preview(
            preview: EvidenceIntakePreview,
            candidate_rank: int,
            stance: EvidenceStance,
        ) -> object:
            return intake.file_evidence(
                mission_id=preview.mission_id,
                claim_id=preview.claim_id,
                snapshot_id=preview.snapshot_id,
                quote=preview.quote,
                candidate_rank=candidate_rank,
                expected_intake_preview_sha256=preview.intake_preview_sha256,
                expected_snapshot_sha256=preview.snapshot_sha256,
                expected_mission_audit_sequence=preview.mission_audit_sequence,
                stance=stance,
                identity=identity,
            )

        exact_spans = 0
        candidate_counts = 0
        source_digest_matches = 0
        preview_read_only = 0
        replay_refusals = 0
        duplicate_refusals = 0
        audit_bindings = 0
        provider_calls = 0
        network_calls = 0

        def _forbid_provider(*_args: object, **_kwargs: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("guided intake attempted provider construction")

        def _forbid_network(*_args: object, **_kwargs: object) -> object:
            nonlocal network_calls
            network_calls += 1
            raise AssertionError("guided intake attempted network access")

        with (
            patch("minerva.integrations.ai.candidate_provider", _forbid_provider),
            patch.object(socket, "create_connection", _forbid_network),
            patch.object(socket.socket, "connect", _forbid_network),
            patch.object(socket.socket, "connect_ex", _forbid_network),
            patch.object(socket.socket, "sendto", _forbid_network),
            patch.object(socket.socket, "sendmsg", _forbid_network),
        ):
            for index, case in enumerate(_CASES, start=1):
                mission = research.create_mission(
                    title=f"Intake evaluation {index:02d}",
                    objective="Measure exact local source-to-evidence handling.",
                    identity=identity,
                )
                question = research.add_question(
                    mission_id=mission.id,
                    text="Can this exact observation be filed without manual offsets?",
                    identity=identity,
                )
                claim = research.add_claim(
                    mission_id=mission.id,
                    question_id=question.id,
                    statement="The selected observation is represented by exact stored bytes.",
                    falsification_criteria="The filed span does not reproduce the selected text.",
                    identity=identity,
                )
                relative_path = f"case-{index:02d}-{case.label}.txt"
                (root / relative_path).write_text(case.content, encoding="utf-8")
                source_preview = sources.preview_file(root=root, relative_path=relative_path)
                snapshot = sources.import_file(
                    mission_id=mission.id,
                    root=root,
                    relative_path=relative_path,
                    media_type="text/plain",
                    expected_sha256=source_preview.sha256,
                    identity=identity,
                )
                source_digest_matches += int(source_preview.sha256 == snapshot.sha256)

                with database.read() as connection:
                    evidence_before = int(
                        connection.execute("SELECT COUNT(*) FROM evidence_cards").fetchone()[0]
                    )
                    audit_before = int(
                        connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
                    )
                preview = intake.preview(
                    mission_id=mission.id,
                    claim_id=claim.id,
                    snapshot_id=snapshot.snapshot_id,
                    quote=case.quote,
                )
                with database.read() as connection:
                    evidence_after_preview = int(
                        connection.execute("SELECT COUNT(*) FROM evidence_cards").fetchone()[0]
                    )
                    audit_after_preview = int(
                        connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
                    )
                preview_read_only += int(
                    (evidence_before, audit_before) == (evidence_after_preview, audit_after_preview)
                )
                candidate_counts += int(preview.candidate_count == case.expected_candidates)

                result = intake.file_evidence(
                    mission_id=mission.id,
                    claim_id=claim.id,
                    snapshot_id=snapshot.snapshot_id,
                    quote=case.quote,
                    candidate_rank=case.candidate_rank,
                    expected_intake_preview_sha256=preview.intake_preview_sha256,
                    expected_snapshot_sha256=preview.snapshot_sha256,
                    expected_mission_audit_sequence=preview.mission_audit_sequence,
                    stance=tuple(EvidenceStance)[(index - 1) % len(EvidenceStance)],
                    identity=identity,
                )
                selected = preview.candidates[case.candidate_rank - 1]
                content_bytes = case.content.encode("utf-8")
                exact_spans += int(
                    content_bytes[selected.start_byte : selected.end_byte].decode("utf-8")
                    == case.quote
                    == result.evidence.quote
                )
                with database.read() as connection:
                    audit_rows = list(
                        connection.execute(
                            """
                            SELECT id, event_type FROM audit_events
                            WHERE entity_id = ? ORDER BY sequence
                            """,
                            (result.evidence.id,),
                        )
                    )
                audit_bindings += int(
                    len(audit_rows) == 1
                    and str(audit_rows[0]["id"]) == result.creation_audit_event_id
                    and str(audit_rows[0]["event_type"]) == "evidence.card.created"
                )
                replay_refusals += int(
                    _error_code(
                        partial(
                            _file_preview,
                            preview,
                            case.candidate_rank,
                            result.stance,
                        )
                    )
                    == "mission_version_conflict"
                )
                current = intake.preview(
                    mission_id=mission.id,
                    claim_id=claim.id,
                    snapshot_id=snapshot.snapshot_id,
                    quote=case.quote,
                )
                duplicate_refusals += int(
                    _error_code(
                        partial(
                            _file_preview,
                            current,
                            case.candidate_rank,
                            result.stance,
                        )
                    )
                    == "intake_evidence_already_exists"
                )

        with database.read() as connection:
            evidence_count = int(
                connection.execute("SELECT COUNT(*) FROM evidence_cards").fetchone()[0]
            )
            mission_count = int(
                connection.execute("SELECT COUNT(*) FROM research_missions").fetchone()[0]
            )

        case_count = len(_CASES)
        return {
            "schema_version": "minerva.evidence-intake-evaluation.v1",
            "algorithm": "local-file-preview-import-exact-quote-intake",
            "algorithm_version": "1",
            "realistic_case_count": case_count,
            "successful_source_to_evidence_count": evidence_count,
            "exact_utf8_span_accuracy_ppm": exact_spans * 1_000_000 // case_count,
            "candidate_count_accuracy_ppm": candidate_counts * 1_000_000 // case_count,
            "source_digest_binding_ppm": source_digest_matches * 1_000_000 // case_count,
            "preview_read_only_ppm": preview_read_only * 1_000_000 // case_count,
            "creation_audit_binding_ppm": audit_bindings * 1_000_000 // case_count,
            "stale_replay_refusal_ppm": replay_refusals * 1_000_000 // case_count,
            "duplicate_refusal_ppm": duplicate_refusals * 1_000_000 // case_count,
            "operator_steps_source_to_evidence": 4,
            "fixture_mission_count": mission_count,
            "schema_version_unchanged": latest_schema_version() == 5,
            "deep_integrity": run_doctor(database, deep=True).ok,
            "provider_invocation_count": provider_calls,
            "network_invocation_count": network_calls,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(
        json.dumps(
            evaluate_intake(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
