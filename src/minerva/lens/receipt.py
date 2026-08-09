"""Offline verification and exact local replay for Lens v1 receipts."""

from __future__ import annotations

import base64
import binascii
import re
import sqlite3
import unicodedata
from dataclasses import fields
from hashlib import sha256
from itertools import pairwise
from pathlib import PurePosixPath, PureWindowsPath
from typing import Never

from minerva.core.errors import IntegrityError
from minerva.lens.models import (
    LENS_ALGORITHM,
    LENS_ALGORITHM_VERSION,
    LENS_CANDIDATE_KIND,
    LENS_QUERY_NORMALIZATION,
    LENS_RECEIPT_VERIFICATION_SCHEMA_VERSION,
    LENS_REPLAY_SCHEMA_VERSION,
    LENS_RESULT_KIND,
    LENS_SCHEMA_VERSION,
    LENS_SCORING,
    LENS_SEMANTIC_NOTICE,
    LENS_STABLE_TIE_BREAK,
    LensCandidateContext,
    LensCorpusFilter,
    LensOmissions,
    LensReceiptCheckBoundary,
    LensReceiptVerificationResult,
    LensReplayResult,
    LensScore,
    LensSearchResult,
    LensSemanticBoundary,
    LensSnapshotIdentity,
)
from minerva.lens.service import (
    _SNAPSHOT_ID,
    _SOURCE_ID,
    LensService,
    _candidate_rank_key,
    _canonical_filter,
    _receipt_digest,
    _score_quote,
    _snapshot_set_digest,
    _validate_bounds,
    _validate_normalized_query,
    _why,
)

_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,49}/[a-z0-9][a-z0-9!#$&^_.+-]{0,48}\Z")


def verify_lens_receipt(receipt: LensSearchResult) -> LensSearchResult:
    """Verify one parsed Lens v1 receipt without opening a database."""

    if not isinstance(receipt, LensSearchResult):
        _invalid()
    if (
        not isinstance(receipt.retrieval_receipt_sha256, str)
        or _SHA256.fullmatch(receipt.retrieval_receipt_sha256) is None
    ):
        _invalid()
    try:
        expected_receipt_digest = _receipt_digest(receipt)
    except (TypeError, UnicodeEncodeError, ValueError) as error:
        raise IntegrityError(
            "lens_receipt_invalid",
            "The Lens receipt failed strict structure or semantic verification.",
        ) from error
    if receipt.retrieval_receipt_sha256 != expected_receipt_digest:
        raise IntegrityError(
            "lens_receipt_digest_mismatch",
            "The Lens receipt digest does not match its canonical payload.",
        )
    if receipt.schema_version != LENS_SCHEMA_VERSION:
        raise IntegrityError(
            "lens_receipt_schema_unsupported",
            "The Lens receipt schema version is unsupported.",
        )
    if (
        receipt.algorithm != LENS_ALGORITHM
        or receipt.algorithm_version != LENS_ALGORITHM_VERSION
        or receipt.query_normalization != LENS_QUERY_NORMALIZATION
    ):
        raise IntegrityError(
            "lens_receipt_algorithm_unsupported",
            "The Lens receipt algorithm or normalization version is unsupported.",
        )
    if receipt.unicode_database_version != unicodedata.unidata_version:
        raise IntegrityError(
            "lens_receipt_runtime_incompatible",
            "The Lens receipt requires an incompatible Unicode runtime.",
        )

    if (
        receipt.kind != LENS_RESULT_KIND
        or receipt.scoring != LENS_SCORING
        or receipt.stable_tie_break != LENS_STABLE_TIE_BREAK
        or receipt.semantic_notice != LENS_SEMANTIC_NOTICE
        or not _valid_semantic_boundary(receipt.semantic_boundary)
        or not isinstance(receipt.mission_id, str)
        or _MISSION_ID.fullmatch(receipt.mission_id) is None
    ):
        _invalid()

    try:
        bounds = _validate_bounds(receipt.bounds)
        query_terms = _validate_normalized_query(
            receipt.normalized_query,
            receipt.query_terms,
        )
        if not isinstance(receipt.corpus_filter, LensCorpusFilter):
            _invalid()
        source_ids = _canonical_filter(receipt.corpus_filter.source_ids, pattern=_SOURCE_ID)
        snapshot_ids = _canonical_filter(receipt.corpus_filter.snapshot_ids, pattern=_SNAPSHOT_ID)
    except IntegrityError as error:
        raise IntegrityError(
            "lens_receipt_invalid",
            "The Lens receipt failed strict structure or semantic verification.",
        ) from error
    if (
        source_ids != receipt.corpus_filter.source_ids
        or snapshot_ids != receipt.corpus_filter.snapshot_ids
        or not isinstance(receipt.query_sha256, str)
        or _SHA256.fullmatch(receipt.query_sha256) is None
        or receipt.query_sha256
        != sha256(receipt.normalized_query.encode("utf-8", errors="strict")).hexdigest()
    ):
        _invalid()

    snapshots = _verify_snapshots(receipt, max_corpus_bytes=bounds.max_corpus_bytes)
    _verify_candidates(receipt, snapshots=snapshots, query_terms=query_terms)
    _verify_omissions(receipt)

    if receipt.snapshot_set_sha256 != _snapshot_set_digest(
        receipt.mission_id,
        receipt.searched_snapshots,
    ):
        _invalid()
    return receipt


def lens_receipt_verification_result(
    receipt: LensSearchResult,
) -> LensReceiptVerificationResult:
    """Return a bounded report for a verified receipt."""

    verified = verify_lens_receipt(receipt)
    return LensReceiptVerificationResult(
        schema_version=LENS_RECEIPT_VERIFICATION_SCHEMA_VERSION,
        kind="receipt_verification",
        status="verified",
        receipt_schema_version=verified.schema_version,
        algorithm=verified.algorithm,
        algorithm_version=verified.algorithm_version,
        unicode_database_version=verified.unicode_database_version,
        query_sha256=verified.query_sha256,
        snapshot_set_sha256=verified.snapshot_set_sha256,
        retrieval_receipt_sha256=verified.retrieval_receipt_sha256,
        searched_snapshot_count=verified.searched_snapshot_count,
        result_count=verified.result_count,
        truncated=verified.truncated,
        canonical_digest_verified=True,
        internal_consistency_verified=True,
        runtime_compatible=True,
        searched_snapshot_content_verified=False,
        semantic_boundary=LensReceiptCheckBoundary(reads_research_database=False),
    )


def replay_lens_receipt(
    service: LensService,
    receipt: LensSearchResult,
) -> LensReplayResult:
    """Reproduce a verified request against one current local DB snapshot."""

    return _replay_verified_receipt(
        service,
        verify_lens_receipt(receipt),
        connection=None,
    )


def _replay_lens_receipt_in_snapshot(
    service: LensService,
    receipt: LensSearchResult,
    *,
    connection: sqlite3.Connection,
) -> LensReplayResult:
    """Reproduce a verified request inside a caller-owned read snapshot."""

    return _replay_verified_receipt(
        service,
        verify_lens_receipt(receipt),
        connection=connection,
    )


def _replay_verified_receipt(
    service: LensService,
    verified: LensSearchResult,
    *,
    connection: sqlite3.Connection | None,
) -> LensReplayResult:
    try:
        if connection is None:
            actual = service._search_normalized(
                mission_id=verified.mission_id,
                normalized_query=verified.normalized_query,
                query_terms=verified.query_terms,
                source_ids=verified.corpus_filter.source_ids,
                snapshot_ids=verified.corpus_filter.snapshot_ids,
                bounds=verified.bounds,
            )
        else:
            actual = service._search_normalized_in_snapshot(
                mission_id=verified.mission_id,
                normalized_query=verified.normalized_query,
                query_terms=verified.query_terms,
                source_ids=verified.corpus_filter.source_ids,
                snapshot_ids=verified.corpus_filter.snapshot_ids,
                bounds=verified.bounds,
                connection=connection,
            )
    except IntegrityError as error:
        if error.code == "lens_corpus_filter_invalid":
            raise IntegrityError(
                "lens_replay_mismatch",
                "The current database does not exactly reproduce the Lens receipt.",
            ) from error
        raise

    verify_lens_receipt(actual)
    if actual != verified:
        raise IntegrityError(
            "lens_replay_mismatch",
            "The current database does not exactly reproduce the Lens receipt.",
        )
    return LensReplayResult(
        schema_version=LENS_REPLAY_SCHEMA_VERSION,
        kind="current_database_exact_reproduction",
        status="reproduced",
        receipt_schema_version=verified.schema_version,
        algorithm=verified.algorithm,
        algorithm_version=verified.algorithm_version,
        unicode_database_version=verified.unicode_database_version,
        query_sha256=verified.query_sha256,
        snapshot_set_sha256=verified.snapshot_set_sha256,
        retrieval_receipt_sha256=verified.retrieval_receipt_sha256,
        searched_snapshot_count=actual.searched_snapshot_count,
        result_count=actual.result_count,
        exact_receipt_match=True,
        current_database_snapshot_matched=True,
        historical_corpus_replay=False,
        searched_snapshot_content_verified=True,
        semantic_boundary=LensReceiptCheckBoundary(reads_research_database=True),
    )


def _verify_snapshots(
    receipt: LensSearchResult,
    *,
    max_corpus_bytes: int,
) -> dict[str, LensSnapshotIdentity]:
    snapshots: dict[str, LensSnapshotIdentity] = {}
    total_bytes = 0
    if not isinstance(receipt.searched_snapshots, tuple):
        _invalid()
    for snapshot in receipt.searched_snapshots:
        if (
            not isinstance(snapshot, LensSnapshotIdentity)
            or not isinstance(snapshot.source_id, str)
            or _SOURCE_ID.fullmatch(snapshot.source_id) is None
            or not isinstance(snapshot.snapshot_id, str)
            or _SNAPSHOT_ID.fullmatch(snapshot.snapshot_id) is None
            or not isinstance(snapshot.snapshot_sha256, str)
            or _SHA256.fullmatch(snapshot.snapshot_sha256) is None
            or isinstance(snapshot.byte_length, bool)
            or not isinstance(snapshot.byte_length, int)
            or not 1 <= snapshot.byte_length <= max_corpus_bytes
            or not isinstance(snapshot.media_type, str)
            or _MEDIA_TYPE.fullmatch(snapshot.media_type) is None
            or not _valid_source_label(snapshot.original_label)
            or snapshot.snapshot_id in snapshots
            or (
                receipt.corpus_filter.source_ids is not None
                and snapshot.source_id not in receipt.corpus_filter.source_ids
            )
            or (
                receipt.corpus_filter.snapshot_ids is not None
                and snapshot.snapshot_id not in receipt.corpus_filter.snapshot_ids
            )
        ):
            _invalid()
        snapshots[snapshot.snapshot_id] = snapshot
        total_bytes += snapshot.byte_length
    if (
        isinstance(receipt.searched_snapshot_count, bool)
        or not isinstance(receipt.searched_snapshot_count, int)
        or isinstance(receipt.searched_corpus_bytes, bool)
        or not isinstance(receipt.searched_corpus_bytes, int)
        or receipt.searched_snapshot_count != len(receipt.searched_snapshots)
        or receipt.searched_snapshot_count > receipt.bounds.max_snapshots
        or receipt.searched_corpus_bytes != total_bytes
        or total_bytes > max_corpus_bytes
    ):
        _invalid()
    return snapshots


def _verify_omissions(receipt: LensSearchResult) -> None:
    omissions = receipt.omissions
    if not isinstance(omissions, LensOmissions):
        _invalid()
    integer_values = (
        omissions.mission_snapshot_count,
        omissions.snapshots_excluded_by_corpus_filter,
        omissions.eligible_snapshot_count,
        omissions.eligible_corpus_bytes,
        omissions.omitted_snapshot_count,
        omissions.omitted_corpus_bytes,
        omissions.empty_passages_excluded,
        omissions.nonmatching_passages_excluded,
        omissions.oversized_passages_omitted,
        omissions.oversized_passage_bytes_omitted,
        omissions.matching_candidates_omitted_by_result_limit,
        receipt.matching_candidate_count,
        receipt.result_count,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in integer_values
    ) or any(
        type(value) is not bool
        for value in (
            omissions.snapshot_limit_reached,
            omissions.corpus_byte_limit_reached,
            receipt.truncated,
        )
    ):
        _invalid()
    expected_corpus_limit = receipt.searched_snapshot_count < min(
        omissions.eligible_snapshot_count,
        receipt.bounds.max_snapshots,
    )
    total_passages = (
        omissions.empty_passages_excluded
        + omissions.nonmatching_passages_excluded
        + omissions.oversized_passages_omitted
        + receipt.matching_candidate_count
    )
    omitted_candidates = receipt.matching_candidate_count - receipt.result_count
    returned_candidate_bytes = sum(
        candidate.end_byte - candidate.start_byte for candidate in receipt.candidates
    )
    minimum_passage_bytes = (
        omissions.oversized_passage_bytes_omitted
        + omissions.nonmatching_passages_excluded
        + max(0, omitted_candidates)
        + returned_candidate_bytes
        + max(0, total_passages - receipt.searched_snapshot_count)
    )
    source_filter = receipt.corpus_filter.source_ids
    snapshot_filter = receipt.corpus_filter.snapshot_ids
    empty_filter = source_filter == () or snapshot_filter == ()
    remaining_corpus_bytes = receipt.bounds.max_corpus_bytes - receipt.searched_corpus_bytes
    largest_possible_omitted_snapshot = omissions.omitted_corpus_bytes - max(
        0, omissions.omitted_snapshot_count - 1
    )
    expected_truncated = (
        omissions.omitted_snapshot_count > 0
        or omissions.oversized_passages_omitted > 0
        or omitted_candidates > 0
    )
    if (
        omissions.mission_snapshot_count < omissions.eligible_snapshot_count
        or (source_filter is not None and len(source_filter) > omissions.mission_snapshot_count)
        or (snapshot_filter is not None and len(snapshot_filter) > omissions.mission_snapshot_count)
        or (empty_filter and omissions.eligible_snapshot_count != 0)
        or (
            snapshot_filter is not None
            and source_filter is None
            and omissions.eligible_snapshot_count != len(snapshot_filter)
        )
        or (
            snapshot_filter is not None and omissions.eligible_snapshot_count > len(snapshot_filter)
        )
        or (
            source_filter is not None
            and snapshot_filter is None
            and omissions.eligible_snapshot_count < len(source_filter)
        )
        or omissions.eligible_snapshot_count < receipt.searched_snapshot_count
        or omissions.eligible_corpus_bytes < omissions.eligible_snapshot_count
        or (omissions.eligible_snapshot_count == 0) != (omissions.eligible_corpus_bytes == 0)
        or omissions.eligible_corpus_bytes < receipt.searched_corpus_bytes
        or (
            receipt.corpus_filter.source_ids is None
            and receipt.corpus_filter.snapshot_ids is None
            and omissions.snapshots_excluded_by_corpus_filter != 0
        )
        or omissions.snapshots_excluded_by_corpus_filter
        != omissions.mission_snapshot_count - omissions.eligible_snapshot_count
        or omissions.omitted_snapshot_count
        != omissions.eligible_snapshot_count - receipt.searched_snapshot_count
        or omissions.omitted_corpus_bytes
        != omissions.eligible_corpus_bytes - receipt.searched_corpus_bytes
        or omissions.omitted_corpus_bytes < omissions.omitted_snapshot_count
        or (omissions.omitted_snapshot_count == 0) != (omissions.omitted_corpus_bytes == 0)
        or omissions.snapshot_limit_reached
        != (omissions.eligible_snapshot_count > receipt.bounds.max_snapshots)
        or omissions.corpus_byte_limit_reached != expected_corpus_limit
        or (
            omissions.corpus_byte_limit_reached
            and largest_possible_omitted_snapshot <= remaining_corpus_bytes
        )
        or total_passages < receipt.searched_snapshot_count
        or total_passages > receipt.searched_corpus_bytes
        or (omissions.oversized_passages_omitted == 0)
        != (omissions.oversized_passage_bytes_omitted == 0)
        or omissions.oversized_passage_bytes_omitted
        < omissions.oversized_passages_omitted * (receipt.bounds.max_quote_bytes + 1)
        or omissions.oversized_passage_bytes_omitted > receipt.searched_corpus_bytes
        or omissions.oversized_passage_bytes_omitted
        + total_passages
        - omissions.oversized_passages_omitted
        > receipt.searched_corpus_bytes
        or minimum_passage_bytes > receipt.searched_corpus_bytes
        or omitted_candidates < 0
        or omissions.matching_candidates_omitted_by_result_limit != omitted_candidates
        or receipt.result_count != min(receipt.bounds.max_results, receipt.matching_candidate_count)
        or receipt.truncated != expected_truncated
        or omissions.source_retraction_metadata != "not_modeled"
    ):
        _invalid()


def _verify_candidates(
    receipt: LensSearchResult,
    *,
    snapshots: dict[str, LensSnapshotIdentity],
    query_terms: tuple[str, ...],
) -> None:
    if (
        not isinstance(receipt.candidates, tuple)
        or isinstance(receipt.result_count, bool)
        or not isinstance(receipt.result_count, int)
        or receipt.result_count != len(receipt.candidates)
        or receipt.result_count > receipt.bounds.max_results
    ):
        _invalid()
    seen_spans: set[tuple[str, int, int]] = set()
    spans_by_snapshot: dict[str, list[tuple[int, int]]] = {}
    prior_key: tuple[int | str, ...] | None = None
    for expected_rank, candidate in enumerate(receipt.candidates, start=1):
        if not isinstance(candidate, LensCandidateContext) or not isinstance(
            candidate.snapshot_id, str
        ):
            _invalid()
        snapshot = snapshots.get(candidate.snapshot_id)
        if snapshot is None:
            _invalid()
        if (
            candidate.kind != LENS_CANDIDATE_KIND
            or isinstance(candidate.rank, bool)
            or not isinstance(candidate.rank, int)
            or candidate.rank != expected_rank
            or candidate.mission_id != receipt.mission_id
            or candidate.source_id != snapshot.source_id
            or candidate.source_label != snapshot.original_label
            or candidate.snapshot_sha256 != snapshot.snapshot_sha256
            or candidate.media_type != snapshot.media_type
            or candidate.stance != "unassessed"
            or candidate.evidence_status != "candidate_only"
            or isinstance(candidate.start_byte, bool)
            or isinstance(candidate.end_byte, bool)
            or not isinstance(candidate.start_byte, int)
            or not isinstance(candidate.end_byte, int)
            or not 0 <= candidate.start_byte < candidate.end_byte <= snapshot.byte_length
            or not isinstance(candidate.quote, str)
            or not isinstance(candidate.quote_utf8_base64, str)
            or not isinstance(candidate.quote_sha256, str)
            or not isinstance(candidate.why, str)
            or not _valid_score_types(candidate.score)
        ):
            _invalid()
        try:
            quote_bytes = base64.b64decode(candidate.quote_utf8_base64, validate=True)
            decoded_quote = quote_bytes.decode("utf-8", errors="strict")
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise IntegrityError(
                "lens_receipt_invalid",
                "The Lens receipt failed strict structure or semantic verification.",
            ) from error
        score = _score_quote(candidate.quote, query_terms)
        span = (candidate.snapshot_id, candidate.start_byte, candidate.end_byte)
        key = _candidate_rank_key(candidate)
        if (
            not quote_bytes
            or b"\n" in quote_bytes
            or b"\x00" in quote_bytes
            or len(quote_bytes) != candidate.end_byte - candidate.start_byte
            or len(quote_bytes) > receipt.bounds.max_quote_bytes
            or decoded_quote != candidate.quote
            or base64.b64encode(quote_bytes).decode("ascii") != candidate.quote_utf8_base64
            or _SHA256.fullmatch(candidate.quote_sha256) is None
            or sha256(quote_bytes).hexdigest() != candidate.quote_sha256
            or score is None
            or candidate.score != score
            or candidate.why != _why(score)
            or span in seen_spans
            or (prior_key is not None and prior_key >= key)
        ):
            _invalid()
        seen_spans.add(span)
        spans_by_snapshot.setdefault(candidate.snapshot_id, []).append(
            (candidate.start_byte, candidate.end_byte)
        )
        prior_key = key
    for spans in spans_by_snapshot.values():
        ordered = sorted(spans)
        if any(
            left_end >= right_start
            for (_left_start, left_end), (right_start, _right_end) in pairwise(ordered)
        ):
            _invalid()


def _valid_utf8_text(value: object, *, min_chars: int, max_chars: int) -> bool:
    if not isinstance(value, str) or not min_chars <= len(value) <= max_chars:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def _valid_source_label(value: object) -> bool:
    if not _valid_utf8_text(value, min_chars=1, max_chars=500):
        return False
    assert isinstance(value, str)
    if value != value.strip() or "\x00" in value or "\\" in value or value.startswith("/"):
        return False
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return not (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    )


def _valid_semantic_boundary(value: object) -> bool:
    expected = LensSemanticBoundary()
    return (
        type(value) is LensSemanticBoundary
        and all(type(getattr(value, field.name)) is bool for field in fields(LensSemanticBoundary))
        and value == expected
    )


def _valid_score_types(value: object) -> bool:
    if type(value) is not LensScore or type(value.exact_phrase_match) is not bool:
        return False
    return all(
        type(component) is int
        for component in (
            value.matched_distinct_terms,
            value.query_distinct_terms,
            value.total_term_occurrences,
            value.candidate_term_count,
            value.density_ppm,
        )
    )


def _invalid() -> Never:
    raise IntegrityError(
        "lens_receipt_invalid",
        "The Lens receipt failed strict structure or semantic verification.",
    )
