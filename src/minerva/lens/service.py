"""Model-free, mission-scoped lexical retrieval over immutable snapshots."""

from __future__ import annotations

import base64
import bisect
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from typing import Any

from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.lens.models import (
    LENS_ALGORITHM,
    LENS_ALGORITHM_VERSION,
    LENS_CANDIDATE_KIND,
    LENS_QUERY_NORMALIZATION,
    LENS_RESULT_KIND,
    LENS_SCHEMA_VERSION,
    LENS_SCORING,
    LENS_SEMANTIC_NOTICE,
    LENS_SNAPSHOT_SET_SCHEMA_VERSION,
    LENS_STABLE_TIE_BREAK,
    LensBounds,
    LensCandidateContext,
    LensCorpusFilter,
    LensOmissions,
    LensReplayResult,
    LensScore,
    LensSearchResult,
    LensSemanticBoundary,
    LensSnapshotIdentity,
)
from minerva.sources.integrity import verify_snapshot_integrity

DEFAULT_LENS_BOUNDS = LensBounds()
MAX_QUERY_BYTES = 512
MAX_QUERY_TERMS = 32
MAX_QUERY_TERM_BYTES = 128
MAX_FILTER_IDS = 200

_MAX_RESULTS = 100
_MAX_SNAPSHOTS = 200
_MAX_CORPUS_BYTES = 67_108_864
_MIN_QUOTE_BYTES = 32
_MAX_QUOTE_BYTES = 4_096
_SOURCE_ID = re.compile(r"src_[0-9a-f]{32}\Z")
_SNAPSHOT_ID = re.compile(r"snp_[0-9a-f]{32}\Z")
_WORD = re.compile(r"\w+", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)
_NORMALIZATION_APPLICATION_CAP = 4


@dataclass(frozen=True, slots=True)
class _SnapshotReference:
    source_id: str
    snapshot_id: str
    snapshot_sha256: str
    byte_length: int
    media_type: str
    original_label: str
    imported_at: str

    def identity(self) -> LensSnapshotIdentity:
        return LensSnapshotIdentity(
            source_id=self.source_id,
            snapshot_id=self.snapshot_id,
            snapshot_sha256=self.snapshot_sha256,
            byte_length=self.byte_length,
            media_type=self.media_type,
            original_label=self.original_label,
        )


@dataclass(slots=True)
class _PassageCounts:
    empty: int = 0
    nonmatching: int = 0
    oversized: int = 0
    oversized_bytes: int = 0
    matching: int = 0


class LensService:
    """Return deterministic leads without creating research state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def search(
        self,
        *,
        mission_id: str,
        query: str,
        source_ids: Sequence[str] | None = None,
        snapshot_ids: Sequence[str] | None = None,
        bounds: LensBounds = DEFAULT_LENS_BOUNDS,
    ) -> LensSearchResult:
        safe_bounds = _validate_bounds(bounds)
        normalized_query, query_terms = _normalize_query(query)
        return self._search_normalized(
            mission_id=mission_id,
            normalized_query=normalized_query,
            query_terms=query_terms,
            source_ids=source_ids,
            snapshot_ids=snapshot_ids,
            bounds=safe_bounds,
        )

    def replay_receipt(self, receipt: LensSearchResult) -> LensReplayResult:
        """Verify and reproduce a captured receipt against the current database."""

        # Local import keeps the pure receipt verifier dependent on the search
        # service without creating a module-import cycle.
        from minerva.lens.receipt import replay_lens_receipt

        return replay_lens_receipt(self, receipt)

    def _search_normalized(
        self,
        *,
        mission_id: str,
        normalized_query: str,
        query_terms: tuple[str, ...],
        source_ids: Sequence[str] | None,
        snapshot_ids: Sequence[str] | None,
        bounds: LensBounds,
    ) -> LensSearchResult:
        return self._search_normalized_with_connection(
            mission_id=mission_id,
            normalized_query=normalized_query,
            query_terms=query_terms,
            source_ids=source_ids,
            snapshot_ids=snapshot_ids,
            bounds=bounds,
            connection=None,
        )

    def _search_normalized_in_snapshot(
        self,
        *,
        mission_id: str,
        normalized_query: str,
        query_terms: tuple[str, ...],
        source_ids: Sequence[str] | None,
        snapshot_ids: Sequence[str] | None,
        bounds: LensBounds,
        connection: sqlite3.Connection,
    ) -> LensSearchResult:
        """Run an already-verified request in a caller-owned read snapshot."""

        return self._search_normalized_with_connection(
            mission_id=mission_id,
            normalized_query=normalized_query,
            query_terms=query_terms,
            source_ids=source_ids,
            snapshot_ids=snapshot_ids,
            bounds=bounds,
            connection=connection,
        )

    def _search_normalized_with_connection(
        self,
        *,
        mission_id: str,
        normalized_query: str,
        query_terms: tuple[str, ...],
        source_ids: Sequence[str] | None,
        snapshot_ids: Sequence[str] | None,
        bounds: LensBounds,
        connection: sqlite3.Connection | None,
    ) -> LensSearchResult:
        """Execute an already-canonical Lens request for receipt replay.

        Public callers still use :meth:`search`. Receipt replay first verifies
        the captured fixed-point text and tokens, then uses that exact request
        representation instead of interpreting it as new raw operator input.
        """

        safe_bounds = _validate_bounds(bounds)
        safe_query_terms = _validate_normalized_query(normalized_query, query_terms)
        safe_source_ids = _canonical_filter(source_ids, pattern=_SOURCE_ID)
        safe_snapshot_ids = _canonical_filter(snapshot_ids, pattern=_SNAPSHOT_ID)
        corpus_filter = LensCorpusFilter(
            source_ids=safe_source_ids,
            snapshot_ids=safe_snapshot_ids,
        )

        with _lens_connection(self.database, connection) as connection:
            connection.execute("PRAGMA query_only = ON")
            _require_mission(connection, mission_id)
            _require_filters_in_mission(
                connection,
                mission_id=mission_id,
                source_ids=safe_source_ids,
                snapshot_ids=safe_snapshot_ids,
            )
            mission_snapshot_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM source_snapshots WHERE mission_id = ?",
                    (mission_id,),
                ).fetchone()[0]
            )
            eligible_count, eligible_bytes = _eligible_totals(
                connection,
                mission_id=mission_id,
                source_ids=safe_source_ids,
                snapshot_ids=safe_snapshot_ids,
            )
            prefix = _eligible_snapshot_prefix(
                connection,
                mission_id=mission_id,
                source_ids=safe_source_ids,
                snapshot_ids=safe_snapshot_ids,
                limit=safe_bounds.max_snapshots,
            )
            snapshot_limit_reached = eligible_count > len(prefix)

            searched: list[_SnapshotReference] = []
            searched_bytes = 0
            corpus_byte_limit_reached = False
            ranked: list[tuple[tuple[int | str, ...], LensCandidateContext]] = []
            passage_counts = _PassageCounts()

            for reference in prefix:
                if searched_bytes + reference.byte_length > safe_bounds.max_corpus_bytes:
                    corpus_byte_limit_reached = True
                    break
                row = _snapshot_row(
                    connection,
                    mission_id=mission_id,
                    snapshot_id=reference.snapshot_id,
                )
                content = verify_snapshot_integrity(connection, row)
                if (
                    str(row["source_id"]) != reference.source_id
                    or str(row["sha256"]) != reference.snapshot_sha256
                    or len(content) != reference.byte_length
                ):
                    raise IntegrityError(
                        "snapshot_tampered",
                        "Stored source snapshot integrity failed.",
                    )
                searched.append(reference)
                searched_bytes += len(content)
                _search_snapshot(
                    mission_id=mission_id,
                    reference=reference,
                    content=content,
                    query_terms=safe_query_terms,
                    max_quote_bytes=safe_bounds.max_quote_bytes,
                    max_results=safe_bounds.max_results,
                    ranked=ranked,
                    counts=passage_counts,
                )

        candidates = tuple(
            replace(candidate, rank=index)
            for index, (_key, candidate) in enumerate(ranked, start=1)
        )
        searched_identities = tuple(reference.identity() for reference in searched)
        omitted_snapshot_count = eligible_count - len(searched)
        omitted_corpus_bytes = eligible_bytes - searched_bytes
        omitted_candidates = passage_counts.matching - len(candidates)
        omissions = LensOmissions(
            mission_snapshot_count=mission_snapshot_count,
            snapshots_excluded_by_corpus_filter=mission_snapshot_count - eligible_count,
            eligible_snapshot_count=eligible_count,
            eligible_corpus_bytes=eligible_bytes,
            omitted_snapshot_count=omitted_snapshot_count,
            omitted_corpus_bytes=omitted_corpus_bytes,
            snapshot_limit_reached=snapshot_limit_reached,
            corpus_byte_limit_reached=corpus_byte_limit_reached,
            empty_passages_excluded=passage_counts.empty,
            nonmatching_passages_excluded=passage_counts.nonmatching,
            oversized_passages_omitted=passage_counts.oversized,
            oversized_passage_bytes_omitted=passage_counts.oversized_bytes,
            matching_candidates_omitted_by_result_limit=omitted_candidates,
            source_retraction_metadata="not_modeled",
        )
        truncated = (
            omitted_snapshot_count > 0 or passage_counts.oversized > 0 or omitted_candidates > 0
        )
        query_sha256 = sha256(normalized_query.encode("utf-8")).hexdigest()
        snapshot_set_sha256 = _snapshot_set_digest(mission_id, searched_identities)
        provisional = LensSearchResult(
            schema_version=LENS_SCHEMA_VERSION,
            kind=LENS_RESULT_KIND,
            mission_id=mission_id,
            normalized_query=normalized_query,
            query_sha256=query_sha256,
            query_terms=safe_query_terms,
            query_normalization=LENS_QUERY_NORMALIZATION,
            unicode_database_version=unicodedata.unidata_version,
            algorithm=LENS_ALGORITHM,
            algorithm_version=LENS_ALGORITHM_VERSION,
            scoring=LENS_SCORING,
            stable_tie_break=LENS_STABLE_TIE_BREAK,
            bounds=safe_bounds,
            corpus_filter=corpus_filter,
            searched_snapshots=searched_identities,
            searched_snapshot_count=len(searched_identities),
            searched_corpus_bytes=searched_bytes,
            snapshot_set_sha256=snapshot_set_sha256,
            matching_candidate_count=passage_counts.matching,
            result_count=len(candidates),
            truncated=truncated,
            omissions=omissions,
            candidates=candidates,
            semantic_notice=LENS_SEMANTIC_NOTICE,
            semantic_boundary=LensSemanticBoundary(),
            retrieval_receipt_sha256="",
        )
        return replace(
            provisional,
            retrieval_receipt_sha256=_receipt_digest(provisional),
        )


@contextmanager
def _lens_connection(
    database: Database,
    connection: sqlite3.Connection | None,
) -> Iterator[sqlite3.Connection]:
    if connection is not None:
        yield connection
        return
    with database.read() as opened:
        yield opened


def _validate_bounds(bounds: LensBounds) -> LensBounds:
    if not isinstance(bounds, LensBounds):
        raise IntegrityError("lens_bounds_invalid", "Lens search bounds are invalid.")
    values = (
        bounds.max_results,
        bounds.max_snapshots,
        bounds.max_corpus_bytes,
        bounds.max_quote_bytes,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise IntegrityError("lens_bounds_invalid", "Lens search bounds are invalid.")
    if (
        not 1 <= bounds.max_results <= _MAX_RESULTS
        or not 1 <= bounds.max_snapshots <= _MAX_SNAPSHOTS
        or not 1 <= bounds.max_corpus_bytes <= _MAX_CORPUS_BYTES
        or not _MIN_QUOTE_BYTES <= bounds.max_quote_bytes <= _MAX_QUOTE_BYTES
    ):
        raise IntegrityError("lens_bounds_invalid", "Lens search bounds are invalid.")
    return bounds


def _normalize_query(query: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(query, str) or "\x00" in query:
        raise IntegrityError("lens_query_invalid", "The Lens query is invalid.")
    try:
        raw = query.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise IntegrityError("lens_query_invalid", "The Lens query is invalid.") from error
    if not raw or len(raw) > MAX_QUERY_BYTES:
        raise IntegrityError("lens_query_invalid", "The Lens query is invalid.")
    normalized = _normalize_text(query)
    try:
        normalized_bytes = normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise IntegrityError("lens_query_invalid", "The Lens query is invalid.") from error
    if not normalized_bytes or len(normalized_bytes) > MAX_QUERY_BYTES:
        raise IntegrityError("lens_query_invalid", "The Lens query is invalid.")
    terms = tuple(_WORD.findall(normalized))
    if (
        not terms
        or len(terms) > MAX_QUERY_TERMS
        or any(len(term.encode("utf-8")) > MAX_QUERY_TERM_BYTES for term in terms)
    ):
        raise IntegrityError("lens_query_invalid", "The Lens query is invalid.")
    return normalized, terms


def _validate_normalized_query(
    normalized_query: str,
    query_terms: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(normalized_query, str) or "\x00" in normalized_query:
        raise IntegrityError("lens_receipt_invalid", "The Lens receipt is invalid.")
    try:
        encoded = normalized_query.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise IntegrityError("lens_receipt_invalid", "The Lens receipt is invalid.") from error
    if (
        not encoded
        or len(encoded) > MAX_QUERY_BYTES
        or _normalize_text(normalized_query) != normalized_query
        or not isinstance(query_terms, tuple)
        or query_terms != tuple(_WORD.findall(normalized_query))
        or not 1 <= len(query_terms) <= MAX_QUERY_TERMS
        or any(len(term.encode("utf-8")) > MAX_QUERY_TERM_BYTES for term in query_terms)
    ):
        raise IntegrityError("lens_receipt_invalid", "The Lens receipt is invalid.")
    return query_terms


def _normalize_text(value: str) -> str:
    current = value
    for _application in range(_NORMALIZATION_APPLICATION_CAP):
        updated = unicodedata.normalize("NFKC", current).casefold()
        if updated == current:
            return _WHITESPACE.sub(" ", current).strip()
        current = updated
    raise IntegrityError(
        "lens_normalization_unsupported",
        "Lens Unicode normalization did not converge within its deterministic bound.",
    )


def _canonical_filter(
    values: Sequence[str] | None,
    *,
    pattern: re.Pattern[str],
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, str | bytes):
        raise IntegrityError("lens_corpus_filter_invalid", "The Lens corpus filter is invalid.")
    try:
        candidates = tuple(values)
    except TypeError as error:
        raise IntegrityError(
            "lens_corpus_filter_invalid", "The Lens corpus filter is invalid."
        ) from error
    if len(candidates) > MAX_FILTER_IDS or any(
        not isinstance(value, str) or pattern.fullmatch(value) is None for value in candidates
    ):
        raise IntegrityError("lens_corpus_filter_invalid", "The Lens corpus filter is invalid.")
    return tuple(sorted(set(candidates)))


def _require_mission(connection: sqlite3.Connection, mission_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM research_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        is None
    ):
        raise NotFoundError("mission_not_found")


def _require_filters_in_mission(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    source_ids: tuple[str, ...] | None,
    snapshot_ids: tuple[str, ...] | None,
) -> None:
    if source_ids is not None and _matching_identifier_count(
        connection,
        table="sources",
        mission_id=mission_id,
        identifiers=source_ids,
    ) != len(source_ids):
        raise IntegrityError(
            "lens_corpus_filter_invalid",
            "The Lens corpus filter is invalid for this mission.",
        )
    if snapshot_ids is not None and _matching_identifier_count(
        connection,
        table="source_snapshots",
        mission_id=mission_id,
        identifiers=snapshot_ids,
    ) != len(snapshot_ids):
        raise IntegrityError(
            "lens_corpus_filter_invalid",
            "The Lens corpus filter is invalid for this mission.",
        )


def _matching_identifier_count(
    connection: sqlite3.Connection,
    *,
    table: str,
    mission_id: str,
    identifiers: tuple[str, ...],
) -> int:
    if not identifiers:
        return 0
    if table not in {"sources", "source_snapshots"}:
        raise AssertionError("identifier table is not allowlisted")
    placeholders = ",".join("?" for _ in identifiers)
    row = connection.execute(
        f"SELECT COUNT(*) FROM {table} WHERE mission_id = ? AND id IN ({placeholders})",  # noqa: S608 - table is allowlisted and values are parameters.
        (mission_id, *identifiers),
    ).fetchone()
    return int(row[0])


def _scope_where(
    *,
    mission_id: str,
    source_ids: tuple[str, ...] | None,
    snapshot_ids: tuple[str, ...] | None,
) -> tuple[str, tuple[object, ...]]:
    clauses = ["ss.mission_id = ?"]
    parameters: list[object] = [mission_id]
    for column, identifiers in (("ss.source_id", source_ids), ("ss.id", snapshot_ids)):
        if identifiers is None:
            continue
        if not identifiers:
            clauses.append("0")
            continue
        placeholders = ",".join("?" for _ in identifiers)
        clauses.append(f"{column} IN ({placeholders})")
        parameters.extend(identifiers)
    return " AND ".join(clauses), tuple(parameters)


def _eligible_totals(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    source_ids: tuple[str, ...] | None,
    snapshot_ids: tuple[str, ...] | None,
) -> tuple[int, int]:
    where, parameters = _scope_where(
        mission_id=mission_id,
        source_ids=source_ids,
        snapshot_ids=snapshot_ids,
    )
    row = connection.execute(
        f"""
        SELECT COUNT(*), COALESCE(SUM(ss.byte_length), 0)
        FROM source_snapshots AS ss
        WHERE {where}
        """,  # noqa: S608 - only fixed clauses and placeholders are composed.
        parameters,
    ).fetchone()
    return int(row[0]), int(row[1])


def _eligible_snapshot_prefix(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    source_ids: tuple[str, ...] | None,
    snapshot_ids: tuple[str, ...] | None,
    limit: int,
) -> tuple[_SnapshotReference, ...]:
    where, parameters = _scope_where(
        mission_id=mission_id,
        source_ids=source_ids,
        snapshot_ids=snapshot_ids,
    )
    rows = connection.execute(
        f"""
        SELECT
            ss.source_id,
            ss.id AS snapshot_id,
            ss.sha256,
            ss.byte_length,
            ss.media_type,
            ss.original_label,
            ss.imported_at
        FROM source_snapshots AS ss
        WHERE {where}
        ORDER BY ss.imported_at ASC, ss.id ASC
        LIMIT ?
        """,  # noqa: S608 - only fixed clauses and placeholders are composed.
        (*parameters, limit),
    )
    return tuple(
        _SnapshotReference(
            source_id=str(row["source_id"]),
            snapshot_id=str(row["snapshot_id"]),
            snapshot_sha256=str(row["sha256"]),
            byte_length=int(row["byte_length"]),
            media_type=str(row["media_type"]),
            original_label=str(row["original_label"]),
            imported_at=str(row["imported_at"]),
        )
        for row in rows
    )


def _snapshot_row(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    snapshot_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT ss.*, s.url_metadata
        FROM source_snapshots AS ss
        JOIN sources AS s ON s.id = ss.source_id AND s.mission_id = ss.mission_id
        WHERE ss.mission_id = ? AND ss.id = ?
        """,
        (mission_id, snapshot_id),
    ).fetchone()
    if not isinstance(row, sqlite3.Row):
        raise IntegrityError("snapshot_tampered", "Stored source snapshot integrity failed.")
    return row


def _search_snapshot(
    *,
    mission_id: str,
    reference: _SnapshotReference,
    content: bytes,
    query_terms: tuple[str, ...],
    max_quote_bytes: int,
    max_results: int,
    ranked: list[tuple[tuple[int | str, ...], LensCandidateContext]],
    counts: _PassageCounts,
) -> None:
    for start_byte, end_byte in _line_spans(content):
        quote_bytes = content[start_byte:end_byte]
        if not quote_bytes:
            counts.empty += 1
            continue
        if len(quote_bytes) > max_quote_bytes:
            counts.oversized += 1
            counts.oversized_bytes += len(quote_bytes)
            continue
        quote = quote_bytes.decode("utf-8", errors="strict")
        score = _score_quote(quote, query_terms)
        if score is None:
            counts.nonmatching += 1
            continue
        candidate = LensCandidateContext(
            kind=LENS_CANDIDATE_KIND,
            rank=0,
            mission_id=mission_id,
            source_id=reference.source_id,
            source_label=reference.original_label,
            snapshot_id=reference.snapshot_id,
            snapshot_sha256=reference.snapshot_sha256,
            media_type=reference.media_type,
            start_byte=start_byte,
            end_byte=end_byte,
            quote=quote,
            quote_utf8_base64=base64.b64encode(quote_bytes).decode("ascii"),
            quote_sha256=sha256(quote_bytes).hexdigest(),
            stance="unassessed",
            evidence_status="candidate_only",
            score=score,
            why=_why(score),
        )
        key = _candidate_rank_key(candidate)
        bisect.insort(ranked, (key, candidate), key=lambda item: item[0])
        if len(ranked) > max_results:
            ranked.pop()
        counts.matching += 1


def _line_spans(content: bytes) -> Iterator[tuple[int, int]]:
    start = 0
    for index, byte in enumerate(content):
        if byte != 0x0A:
            continue
        end = index - 1 if index > start and content[index - 1] == 0x0D else index
        yield start, end
        start = index + 1
    if start < len(content):
        yield start, len(content)


def _contains_sequence(candidate: tuple[str, ...], query: tuple[str, ...]) -> bool:
    if len(query) > len(candidate):
        return False
    return any(
        candidate[index : index + len(query)] == query
        for index in range(len(candidate) - len(query) + 1)
    )


def _score_quote(quote: str, query_terms: tuple[str, ...]) -> LensScore | None:
    candidate_terms = tuple(_WORD.findall(_normalize_text(quote)))
    distinct_query_terms = tuple(dict.fromkeys(query_terms))
    term_counts = {term: candidate_terms.count(term) for term in distinct_query_terms}
    matched_distinct_terms = sum(count > 0 for count in term_counts.values())
    if matched_distinct_terms == 0:
        return None
    total_occurrences = sum(term_counts.values())
    return LensScore(
        exact_phrase_match=_contains_sequence(candidate_terms, query_terms),
        matched_distinct_terms=matched_distinct_terms,
        query_distinct_terms=len(distinct_query_terms),
        total_term_occurrences=total_occurrences,
        candidate_term_count=len(candidate_terms),
        density_ppm=(
            total_occurrences * 1_000_000 // len(candidate_terms) if candidate_terms else 0
        ),
    )


def _candidate_rank_key(candidate: LensCandidateContext) -> tuple[int | str, ...]:
    score = candidate.score
    return (
        -int(score.exact_phrase_match),
        -score.matched_distinct_terms,
        -score.total_term_occurrences,
        -score.density_ppm,
        candidate.snapshot_id,
        candidate.start_byte,
        candidate.end_byte,
    )


def _why(score: LensScore) -> str:
    phrase = "exact query phrase; " if score.exact_phrase_match else "no exact query phrase; "
    return (
        f"{phrase}{score.matched_distinct_terms}/{score.query_distinct_terms} distinct "
        f"query terms; {score.total_term_occurrences} total term occurrences; "
        f"density {score.density_ppm} ppm."
    )


def _snapshot_set_digest(
    mission_id: str,
    snapshots: tuple[LensSnapshotIdentity, ...],
) -> str:
    return sha256(
        _canonical_json_bytes(
            {
                "schema_version": LENS_SNAPSHOT_SET_SCHEMA_VERSION,
                "mission_id": mission_id,
                "snapshots": [asdict(snapshot) for snapshot in snapshots],
            }
        )
    ).hexdigest()


def _receipt_digest(result: LensSearchResult) -> str:
    payload = asdict(result)
    payload.pop("retrieval_receipt_sha256")
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
