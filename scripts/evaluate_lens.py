"""Run the deterministic, model-free Lens v1 synthetic evaluation."""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.lens import LensBounds, LensService
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

_CLOCK = "2026-08-08T12:00:00.000000Z"
_K = 3


class _SequenceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


def _fixed_clock() -> str:
    return _CLOCK


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _state(database: Database) -> tuple[tuple[str, ...], str]:
    with database.read() as connection:
        dump = tuple(connection.iterdump())
    return dump, sha256(database.path.read_bytes()).hexdigest()


def _ppm(numerator: int, denominator: int) -> int:
    return numerator * 1_000_000 // denominator if denominator else 1_000_000


def evaluate_lens() -> dict[str, object]:
    """Return integer-only quality metrics over fixed, mission-isolated fixtures."""
    with tempfile.TemporaryDirectory(prefix="minerva-lens-evaluation-") as temporary:
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:lens-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="evaluate deterministic Lens candidate retrieval",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)
        mission = research.create_mission(
            title="Lens evaluation mission",
            objective="Measure bounded lexical retrieval without changing research state.",
            identity=identity,
        )
        foreign_mission = research.create_mission(
            title="Lens isolation control",
            objective="Ensure retrieval cannot cross mission boundaries.",
            identity=identity,
        )
        fixtures = (
            (
                mission.id,
                "methods.txt",
                b"Immutable snapshots preserve durable provenance.\n",
            ),
            (
                mission.id,
                "audit.txt",
                b"Correction and retraction records preserve history.\n",
            ),
            (
                mission.id,
                "bytes.txt",
                "Citation bytes round trip exactly across UTF-8 Café 東京.\n".encode(),
            ),
            (
                mission.id,
                "noise.txt",
                b"Immutable caches improve speed but omit source custody.\n",
            ),
            (
                foreign_mission.id,
                "foreign.txt",
                b"Immutable provenance correction retraction citation bytes must remain foreign.\n",
            ),
        )
        snapshot_bytes: dict[str, bytes] = {}
        for mission_id, label, content in fixtures:
            snapshot = sources.import_bytes(
                mission_id=mission_id,
                content=content,
                original_label=label,
                media_type="text/plain",
                identity=identity,
            )
            snapshot_bytes[snapshot.snapshot_id] = content

        queries = (
            ("immutable provenance", frozenset({"methods.txt"})),
            ("correction retraction", frozenset({"audit.txt"})),
            ("citation bytes", frozenset({"bytes.txt"})),
        )
        bounds = LensBounds(max_results=_K, max_snapshots=10, max_corpus_bytes=1_000_000)
        service = LensService(database)
        before = _state(database)
        first = tuple(
            service.search(mission_id=mission.id, query=query, bounds=bounds)
            for query, _gold in queries
        )
        second = tuple(
            service.search(mission_id=mission.id, query=query, bounds=bounds)
            for query, _gold in queries
        )
        after = _state(database)

        correct = 0
        returned = 0
        relevant = 0
        accurate_spans = 0
        candidate_count = 0
        for result, (_query, gold) in zip(first, queries, strict=True):
            labels = {candidate.source_label for candidate in result.candidates}
            correct += len(labels & gold)
            returned += len(labels)
            relevant += len(gold)
            for candidate in result.candidates:
                candidate_count += 1
                quoted = base64.b64decode(candidate.quote_utf8_base64, validate=True)
                content = snapshot_bytes[candidate.snapshot_id]
                if (
                    content[candidate.start_byte : candidate.end_byte] == quoted
                    and quoted.decode("utf-8") == candidate.quote
                    and sha256(quoted).hexdigest() == candidate.quote_sha256
                ):
                    accurate_spans += 1

        first_bytes = _canonical_bytes([asdict(result) for result in first])
        second_bytes = _canonical_bytes([asdict(result) for result in second])
        foreign_snapshot_ids = {
            snapshot_id
            for snapshot_id, content in snapshot_bytes.items()
            if b"must remain foreign" in content
        }
        mission_isolation = all(
            candidate.mission_id == mission.id
            and candidate.snapshot_id not in foreign_snapshot_ids
            and candidate.source_label != "foreign.txt"
            for result in first
            for candidate in result.candidates
        )
        unauthorized_mutation_count = int(before[0] != after[0]) + int(before[1] != after[1])

        return {
            "schema_version": "minerva.lens-evaluation.v1",
            "algorithm": first[0].algorithm,
            "algorithm_version": first[0].algorithm_version,
            "k": _K,
            "precision_at_k_ppm": _ppm(correct, returned),
            "recall_at_k_ppm": _ppm(correct, relevant),
            "byte_span_accuracy_ppm": _ppm(accurate_spans, candidate_count),
            "determinism": first_bytes == second_bytes,
            "mission_isolation": mission_isolation,
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_source_count": len(fixtures),
            "query_count": len(queries),
            "result_count": candidate_count,
            "relevant_result_count": relevant,
            "correct_result_count": correct,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(_canonical_bytes(evaluate_lens()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
