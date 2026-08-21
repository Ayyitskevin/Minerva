"""Run the deterministic, model-free Lens v1 synthetic evaluation."""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from minerva.core.db import Database
from minerva.core.errors import IntegrityError
from minerva.core.types import ActorKind, IdentityContext
from minerva.lens import (
    LensBounds,
    LensSearchResult,
    LensService,
    lens_receipt_verification_result,
    verify_lens_receipt,
)
from minerva.research.service import ResearchService
from minerva.sources.models import SourceSnapshot
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


def _with_receipt_digest(receipt: LensSearchResult) -> LensSearchResult:
    provisional = replace(receipt, retrieval_receipt_sha256="")
    payload = asdict(provisional)
    payload.pop("retrieval_receipt_sha256")
    return replace(
        provisional,
        retrieval_receipt_sha256=sha256(_canonical_bytes(payload)).hexdigest(),
    )


def _replay_error_code(service: LensService, receipt: LensSearchResult) -> str | None:
    try:
        service.replay_receipt(receipt)
    except IntegrityError as error:
        return error.code
    return None


def evaluate_lens() -> dict[str, object]:
    """Return deterministic quality metrics over fixed, mission-isolated fixtures."""
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
                mission.id,
                "unicode.txt",
                "ß́ replay survives the normalization boundary.\n".encode(),
            ),
            (
                foreign_mission.id,
                "foreign.txt",
                b"Immutable provenance correction retraction citation bytes must remain foreign.\n",
            ),
        )
        snapshot_bytes: dict[str, bytes] = {}
        snapshots_by_label: dict[str, SourceSnapshot] = {}
        for mission_id, label, content in fixtures:
            snapshot = sources.import_bytes(
                mission_id=mission_id,
                content=content,
                original_label=label,
                media_type="text/plain",
                identity=identity,
            )
            snapshot_bytes[snapshot.snapshot_id] = content
            snapshots_by_label[label] = snapshot

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

        primary_receipt = first[0]
        primary_verification = lens_receipt_verification_result(primary_receipt)
        repeated_verification = lens_receipt_verification_result(primary_receipt)
        primary_replay = service.replay_receipt(primary_receipt)
        repeated_replay = service.replay_receipt(primary_receipt)

        methods = snapshots_by_label["methods.txt"]
        noise = snapshots_by_label["noise.txt"]
        filtered_receipt = service.search(
            mission_id=mission.id,
            query="immutable",
            source_ids=(methods.source_id, noise.source_id, methods.source_id),
            snapshot_ids=(noise.snapshot_id, methods.snapshot_id, noise.snapshot_id),
            bounds=bounds,
        )
        reordered_filter_receipt = service.search(
            mission_id=mission.id,
            query="immutable",
            source_ids=(noise.source_id, methods.source_id),
            snapshot_ids=(methods.snapshot_id, noise.snapshot_id),
            bounds=bounds,
        )
        filtered_replay = service.replay_receipt(filtered_receipt)

        empty_filter_receipt = service.search(
            mission_id=mission.id,
            query="immutable provenance",
            source_ids=(),
            bounds=bounds,
        )
        empty_filter_replay = service.replay_receipt(empty_filter_receipt)

        unicode_receipt = service.search(
            mission_id=mission.id,
            query="ß\u0301 replay",
            bounds=bounds,
        )
        unicode_public_rerun = service.search(
            mission_id=mission.id,
            query=unicode_receipt.normalized_query,
            bounds=bounds,
        )
        unicode_replay = service.replay_receipt(unicode_receipt)

        original_candidate = primary_receipt.candidates[0]
        tampered_quote = original_candidate.quote.replace("durable", "falsity")
        if tampered_quote == original_candidate.quote:
            raise RuntimeError("Lens evaluation tamper fixture no longer matches")
        tampered_bytes = tampered_quote.encode("utf-8")
        tampered_candidate = replace(
            original_candidate,
            quote=tampered_quote,
            quote_utf8_base64=base64.b64encode(tampered_bytes).decode("ascii"),
            quote_sha256=sha256(tampered_bytes).hexdigest(),
        )
        tampered_receipt = _with_receipt_digest(
            replace(
                primary_receipt,
                candidates=(tampered_candidate, *primary_receipt.candidates[1:]),
            )
        )
        tamper_verified_offline = verify_lens_receipt(tampered_receipt) == tampered_receipt
        tamper_replay_error = _replay_error_code(service, tampered_receipt)
        after_current_reads = _state(database)

        sources.import_bytes(
            mission_id=foreign_mission.id,
            content=b"A later foreign snapshot must not perturb the scoped receipt.\n",
            original_label="foreign-later.txt",
            media_type="text/plain",
            identity=identity,
        )
        before_foreign_replays = _state(database)
        primary_after_foreign = service.replay_receipt(primary_receipt)
        filtered_after_foreign = service.replay_receipt(filtered_receipt)
        empty_after_foreign = service.replay_receipt(empty_filter_receipt)
        after_foreign_replays = _state(database)

        sources.import_bytes(
            mission_id=mission.id,
            content=b"Immutable provenance added after the captured receipt.\n",
            original_label="mission-drift.txt",
            media_type="text/plain",
            identity=identity,
        )
        before_drift_replays = _state(database)
        corpus_drift_error = _replay_error_code(service, primary_receipt)
        filtered_drift_error = _replay_error_code(service, filtered_receipt)
        after_drift_replays = _state(database)

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
        unauthorized_mutation_count = sum(
            (
                int(before[0] != after_current_reads[0]),
                int(before[1] != after_current_reads[1]),
                int(before_foreign_replays[0] != after_foreign_replays[0]),
                int(before_foreign_replays[1] != after_foreign_replays[1]),
                int(before_drift_replays[0] != after_drift_replays[0]),
                int(before_drift_replays[1] != after_drift_replays[1]),
            )
        )

        verification_passed = (
            primary_verification == repeated_verification
            and primary_verification.status == "verified"
            and primary_verification.canonical_digest_verified
            and primary_verification.internal_consistency_verified
            and primary_verification.runtime_compatible
            and not primary_verification.searched_snapshot_content_verified
            and not primary_verification.semantic_boundary.reads_research_database
            and primary_verification.retrieval_receipt_sha256
            == primary_receipt.retrieval_receipt_sha256
        )
        exact_replay_passed = (
            primary_replay == repeated_replay == primary_after_foreign
            and primary_replay.status == "reproduced"
            and primary_replay.exact_receipt_match
            and primary_replay.current_database_snapshot_matched
            and not primary_replay.historical_corpus_replay
            and primary_replay.searched_snapshot_content_verified
            and primary_replay.semantic_boundary.reads_research_database
        )
        canonical_filter_and_foreign_mission_stability = (
            filtered_receipt == reordered_filter_receipt
            and filtered_replay == filtered_after_foreign
            and filtered_replay.exact_receipt_match
            and filtered_receipt.corpus_filter.source_ids
            == tuple(sorted({methods.source_id, noise.source_id}))
            and filtered_receipt.corpus_filter.snapshot_ids
            == tuple(sorted({methods.snapshot_id, noise.snapshot_id}))
        )
        empty_filter_isolation = (
            empty_filter_receipt.corpus_filter.source_ids == ()
            and empty_filter_receipt.searched_snapshot_count == 0
            and empty_filter_receipt.result_count == 0
            and empty_filter_replay == empty_after_foreign
            and empty_filter_replay.exact_receipt_match
        )
        canonical_unicode_replay = (
            unicode_receipt.normalized_query == "sś replay"
            and unicode_public_rerun == unicode_receipt
            and unicode_replay.exact_receipt_match
        )
        deterministic_receipt_operations = (
            first_bytes == second_bytes
            and primary_verification == repeated_verification
            and primary_replay == repeated_replay
        )

        return {
            "schema_version": "minerva.lens-evaluation.v1",
            "algorithm": first[0].algorithm,
            "algorithm_version": first[0].algorithm_version,
            "k": _K,
            "precision_at_k_ppm": _ppm(correct, returned),
            "recall_at_k_ppm": _ppm(correct, relevant),
            "byte_span_accuracy_ppm": _ppm(accurate_spans, candidate_count),
            "receipt_verification": verification_passed,
            "current_database_exact_replay": exact_replay_passed,
            "self_consistent_tamper_replay_mismatch": (
                tamper_verified_offline and tamper_replay_error == "lens_replay_mismatch"
            ),
            "in_scope_corpus_drift_replay_mismatch": (
                corpus_drift_error == "lens_replay_mismatch"
                and filtered_drift_error == "lens_replay_mismatch"
            ),
            "canonical_filter_and_foreign_mission_stability": (
                canonical_filter_and_foreign_mission_stability
            ),
            "canonical_unicode_exact_replay": canonical_unicode_replay,
            "empty_filter_isolation": empty_filter_isolation,
            "determinism": deterministic_receipt_operations,
            "mission_isolation": mission_isolation,
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_source_count": len(fixtures) + 2,
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
