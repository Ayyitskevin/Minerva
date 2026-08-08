"""Immutable Lens v1 request bounds and retrieval receipts."""

from __future__ import annotations

from dataclasses import dataclass

LENS_SCHEMA_VERSION = "minerva.lens-search.v1"
LENS_SNAPSHOT_SET_SCHEMA_VERSION = "minerva.lens-snapshot-set.v1"
LENS_ALGORITHM = "bounded-unicode-line-lexical"
LENS_ALGORITHM_VERSION = "1"
LENS_QUERY_NORMALIZATION = "unicode-nfkc-casefold-whitespace-collapse-word-token-v1"


@dataclass(frozen=True, slots=True)
class LensBounds:
    max_results: int = 20
    max_snapshots: int = 50
    max_corpus_bytes: int = 16_777_216
    max_quote_bytes: int = 1_024


@dataclass(frozen=True, slots=True)
class LensCorpusFilter:
    source_ids: tuple[str, ...] | None
    snapshot_ids: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class LensSnapshotIdentity:
    source_id: str
    snapshot_id: str
    snapshot_sha256: str
    byte_length: int
    media_type: str
    original_label: str


@dataclass(frozen=True, slots=True)
class LensScore:
    exact_phrase_match: bool
    matched_distinct_terms: int
    query_distinct_terms: int
    total_term_occurrences: int
    candidate_term_count: int
    density_ppm: int


@dataclass(frozen=True, slots=True)
class LensCandidateContext:
    kind: str
    rank: int
    mission_id: str
    source_id: str
    source_label: str
    snapshot_id: str
    snapshot_sha256: str
    media_type: str
    start_byte: int
    end_byte: int
    quote: str
    quote_utf8_base64: str
    quote_sha256: str
    stance: str
    evidence_status: str
    score: LensScore
    why: str


@dataclass(frozen=True, slots=True)
class LensOmissions:
    mission_snapshot_count: int
    snapshots_excluded_by_corpus_filter: int
    eligible_snapshot_count: int
    eligible_corpus_bytes: int
    omitted_snapshot_count: int
    omitted_corpus_bytes: int
    snapshot_limit_reached: bool
    corpus_byte_limit_reached: bool
    empty_passages_excluded: int
    nonmatching_passages_excluded: int
    oversized_passages_omitted: int
    oversized_passage_bytes_omitted: int
    matching_candidates_omitted_by_result_limit: int
    source_retraction_metadata: str


@dataclass(frozen=True, slots=True)
class LensSemanticBoundary:
    candidate_context_only: bool = True
    creates_evidence: bool = False
    alters_claim_status: bool = False
    creates_or_retracts_findings: bool = False
    changes_confidence: bool = False
    persists_agent_inference: bool = False
    modifies_sources_or_snapshots: bool = False
    silently_expands_corpus: bool = False
    requires_separate_explicit_evidence_adoption: bool = True


@dataclass(frozen=True, slots=True)
class LensSearchResult:
    schema_version: str
    kind: str
    mission_id: str
    normalized_query: str
    query_sha256: str
    query_terms: tuple[str, ...]
    query_normalization: str
    unicode_database_version: str
    algorithm: str
    algorithm_version: str
    scoring: str
    stable_tie_break: tuple[str, ...]
    bounds: LensBounds
    corpus_filter: LensCorpusFilter
    searched_snapshots: tuple[LensSnapshotIdentity, ...]
    searched_snapshot_count: int
    searched_corpus_bytes: int
    snapshot_set_sha256: str
    matching_candidate_count: int
    result_count: int
    truncated: bool
    omissions: LensOmissions
    candidates: tuple[LensCandidateContext, ...]
    semantic_notice: str
    semantic_boundary: LensSemanticBoundary
    retrieval_receipt_sha256: str
