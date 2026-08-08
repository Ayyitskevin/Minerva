"""Complete-or-refuse provenance graph over one claim-owned research closure."""

from __future__ import annotations

import base64
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from typing import Any, Never, cast

from minerva.assist.models import ModelProvider
from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.evidence.integrity import (
    SnapshotCache,
    VerifiedCitation,
    new_snapshot_cache,
    verify_evidence_reference,
)
from minerva.evidence.models import EvidenceStance
from minerva.lineage.models import (
    CLAIM_LINEAGE_ALGORITHM,
    CLAIM_LINEAGE_ALGORITHM_VERSION,
    CLAIM_LINEAGE_EDGE_SET_SCHEMA_VERSION,
    CLAIM_LINEAGE_NODE_SET_SCHEMA_VERSION,
    CLAIM_LINEAGE_SCHEMA_VERSION,
    CLAIM_LINEAGE_SCOPE,
    CLAIM_LINEAGE_SNAPSHOT_SET_SCHEMA_VERSION,
    AgentInferenceLineageData,
    ClaimLineageBounds,
    ClaimLineageData,
    ClaimLineageEdge,
    ClaimLineageKindCount,
    ClaimLineageNode,
    ClaimLineageNodeKind,
    ClaimLineageRelation,
    ClaimLineageResult,
    ClaimLineageSemanticBoundary,
    ClaimLineageWork,
    ClaimStatusEventLineageData,
    CorrectionLineageData,
    EvidenceLineageData,
    FindingLineageData,
    LineageProvenance,
    PromotionLineageData,
    QuestionLineageData,
    SnapshotLineageData,
)
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind

DEFAULT_CLAIM_LINEAGE_BOUNDS = ClaimLineageBounds()

_MAX_NODES = 2_000
_MAX_EDGES = 5_000
_MAX_CITATION_BYTES = 67_108_864
_MAX_SNAPSHOT_BYTES = 67_108_864
_MAX_OUTPUT_BYTES = 134_217_728
_MIN_SQLITE_VM_STEPS = 1_000
_MAX_SQLITE_VM_STEPS = 16_000_000
_QUERY_PROGRESS_GRANULARITY = 1_000
_SQL_IDENTIFIER_CHUNK = 200
_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"clm_[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")

_NODE_ORDER = {kind: index for index, kind in enumerate(ClaimLineageNodeKind)}
_EDGE_ORDER = {relation: index for index, relation in enumerate(ClaimLineageRelation)}
_EXCLUDED_RECORD_KINDS = (
    "sibling_claims",
    "claimless_findings",
    "unreferenced_snapshots",
    "audit_events",
    "research_runs",
    "brief_exports",
    "lens_candidates",
    "ephemeral_assistance_candidates",
    "reverse_dependents",
)


class ClaimLineageService:
    """Build a deterministic graph without changing research or audit state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def build_graph(
        self,
        *,
        mission_id: str,
        claim_id: str,
        bounds: ClaimLineageBounds = DEFAULT_CLAIM_LINEAGE_BOUNDS,
    ) -> ClaimLineageResult:
        safe_bounds = _validate_bounds(bounds)
        _validate_scope_ids(mission_id=mission_id, claim_id=claim_id)

        try:
            with self.database.read() as connection:
                connection.execute("PRAGMA query_only = ON")
                with _bounded_query_work(connection, safe_bounds.max_sqlite_vm_steps):
                    _require_mission(connection, mission_id)
                    claim_row = _claim_row(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                    )
                    question_row = _question_row(
                        connection,
                        mission_id=mission_id,
                        question_id=_identifier(claim_row["question_id"], "que"),
                    )
                    status_rows = _status_rows(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                        limit=safe_bounds.max_nodes,
                    )
                    evidence_count, citation_bytes = _preflight_evidence_quotes(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                        max_nodes=safe_bounds.max_nodes,
                        max_citation_bytes=safe_bounds.max_citation_bytes,
                    )
                    evidence_rows = _evidence_rows(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                        limit=safe_bounds.max_nodes,
                        expected_count=evidence_count,
                    )
                    finding_rows = _finding_rows(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                        limit=safe_bounds.max_nodes,
                    )
                    inference_rows = _inference_rows(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                        limit=safe_bounds.max_nodes,
                    )

                    evidence_ids = tuple(_identifier(row["id"], "evd") for row in evidence_rows)
                    evidence_id_set = frozenset(evidence_ids)
                    finding_ids = tuple(_identifier(row["id"], "fnd") for row in finding_rows)
                    inference_ids = tuple(_identifier(row["id"], "inf") for row in inference_rows)
                    finding_citations = _finding_citation_rows(
                        connection,
                        owner_ids=finding_ids,
                        limit=safe_bounds.max_edges,
                    )
                    inference_citations = _inference_citation_rows(
                        connection,
                        owner_ids=inference_ids,
                        limit=safe_bounds.max_edges,
                    )
                    finding_citation_map = _validate_citation_rows(
                        finding_citations,
                        mission_id=mission_id,
                        owner_ids=finding_ids,
                        evidence_ids=evidence_id_set,
                        owner_column="finding_id",
                    )
                    inference_citation_map = _validate_citation_rows(
                        inference_citations,
                        mission_id=mission_id,
                        owner_ids=inference_ids,
                        evidence_ids=evidence_id_set,
                        owner_column="inference_id",
                    )
                    _validate_finding_citation_policy(
                        finding_rows,
                        citation_map=finding_citation_map,
                    )
                    _validate_inference_citation_policy(
                        inference_rows,
                        citation_map=inference_citation_map,
                    )
                    _validate_promotions(
                        inference_rows,
                        finding_rows=finding_rows,
                        finding_citations=finding_citation_map,
                        inference_citations=inference_citation_map,
                        mission_id=mission_id,
                        claim_id=claim_id,
                    )
                    _validate_supersession(evidence_rows, evidence_ids=evidence_id_set)

                    snapshot_ids = tuple(
                        sorted({_identifier(row["snapshot_id"], "snp") for row in evidence_rows})
                    )
                    snapshot_rows, snapshot_bytes = _snapshot_rows(
                        connection,
                        mission_id=mission_id,
                        snapshot_ids=snapshot_ids,
                        max_snapshot_bytes=safe_bounds.max_snapshot_bytes,
                    )
                    snapshot_cache = new_snapshot_cache()
                    verified_by_id = _verify_evidence(
                        connection,
                        mission_id=mission_id,
                        claim_id=claim_id,
                        evidence_rows=evidence_rows,
                        snapshot_cache=snapshot_cache,
                    )
                    _validate_snapshot_cache(
                        snapshot_rows,
                        snapshot_cache=snapshot_cache,
                    )

                    nodes = _build_nodes(
                        question_row=question_row,
                        claim_row=claim_row,
                        status_rows=status_rows,
                        snapshot_rows=snapshot_rows,
                        evidence_rows=evidence_rows,
                        verified_by_id=verified_by_id,
                        finding_rows=finding_rows,
                        inference_rows=inference_rows,
                    )
                    edges = _build_edges(
                        question_row=question_row,
                        claim_row=claim_row,
                        status_rows=status_rows,
                        evidence_rows=evidence_rows,
                        finding_rows=finding_rows,
                        inference_rows=inference_rows,
                        finding_citations=finding_citations,
                        inference_citations=inference_citations,
                    )
                    _validate_graph(
                        nodes,
                        edges,
                        max_nodes=safe_bounds.max_nodes,
                        max_edges=safe_bounds.max_edges,
                    )
        except (IntegrityError, NotFoundError):
            raise
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise IntegrityError(
                "claim_lineage_inconsistent",
                "Stored claim lineage state is invalid.",
            ) from error

        node_set_sha256 = _node_set_digest(
            mission_id=mission_id,
            claim_id=claim_id,
            nodes=nodes,
        )
        edge_set_sha256 = _edge_set_digest(
            mission_id=mission_id,
            claim_id=claim_id,
            edges=edges,
        )
        snapshot_set_sha256 = _snapshot_set_digest(
            mission_id=mission_id,
            claim_id=claim_id,
            snapshot_rows=snapshot_rows,
        )
        graph_payload_bytes = len(
            _canonical_json_bytes(
                {
                    "nodes": [asdict(node) for node in nodes],
                    "edges": [asdict(edge) for edge in edges],
                }
            )
        )
        node_counts = Counter(node.kind.value for node in nodes)
        edge_counts = Counter(edge.relation.value for edge in edges)
        correction_count = sum(
            node_counts[kind.value]
            for kind in (
                ClaimLineageNodeKind.EVIDENCE_WITHDRAWAL,
                ClaimLineageNodeKind.FINDING_RETRACTION,
                ClaimLineageNodeKind.AGENT_INFERENCE_RETRACTION,
            )
        )
        work = ClaimLineageWork(
            node_count=len(nodes),
            edge_count=len(edges),
            status_event_count=node_counts[ClaimLineageNodeKind.CLAIM_STATUS_EVENT.value],
            evidence_count=node_counts[ClaimLineageNodeKind.EVIDENCE.value],
            finding_count=node_counts[ClaimLineageNodeKind.FINDING.value],
            inference_count=node_counts[ClaimLineageNodeKind.AGENT_INFERENCE.value],
            correction_count=correction_count,
            promotion_count=node_counts[ClaimLineageNodeKind.AGENT_INFERENCE_PROMOTION.value],
            citation_edge_count=(
                edge_counts[ClaimLineageRelation.FINDING_CITES_EVIDENCE.value]
                + edge_counts[ClaimLineageRelation.AGENT_INFERENCE_CITES_EVIDENCE.value]
            ),
            citation_bytes=citation_bytes,
            distinct_snapshot_count=len(snapshot_rows),
            distinct_snapshot_bytes=snapshot_bytes,
            graph_payload_bytes=graph_payload_bytes,
        )
        provisional = ClaimLineageResult(
            schema_version=CLAIM_LINEAGE_SCHEMA_VERSION,
            kind="claim_lineage_graph",
            algorithm=CLAIM_LINEAGE_ALGORITHM,
            algorithm_version=CLAIM_LINEAGE_ALGORITHM_VERSION,
            scope=CLAIM_LINEAGE_SCOPE,
            completion_policy="complete_or_refuse",
            complete=True,
            truncated=False,
            mission_id=mission_id,
            claim_id=claim_id,
            question_id=_identifier(question_row["id"], "que"),
            root_node_id=claim_id,
            bounds=safe_bounds,
            work=work,
            node_kind_counts=tuple(
                ClaimLineageKindCount(kind=kind.value, count=node_counts[kind.value])
                for kind in ClaimLineageNodeKind
            ),
            edge_kind_counts=tuple(
                ClaimLineageKindCount(
                    kind=relation.value,
                    count=edge_counts[relation.value],
                )
                for relation in ClaimLineageRelation
            ),
            nodes=nodes,
            edges=edges,
            node_set_sha256=node_set_sha256,
            edge_set_sha256=edge_set_sha256,
            snapshot_set_sha256=snapshot_set_sha256,
            excluded_record_kinds=_EXCLUDED_RECORD_KINDS,
            scope_notice=(
                "This graph is complete only for records owned by the named claim. It "
                "deliberately excludes sibling claims, claimless mission findings, "
                "unreferenced snapshots, audit/run nodes, and reverse dependents."
            ),
            semantic_notice=(
                "Claim Lineage reports recorded provenance topology and retains corrected "
                "history. Edges do not establish entailment, causality, truth, confidence, "
                "quality, sufficiency, or a recommended claim status."
            ),
            semantic_boundary=ClaimLineageSemanticBoundary(),
            lineage_receipt_sha256="",
        )
        result = replace(
            provisional,
            lineage_receipt_sha256=_lineage_receipt_digest(provisional),
        )
        if len(_canonical_json_bytes(asdict(result))) > safe_bounds.max_output_bytes:
            _raise_work_limit()
        return result


def _validate_bounds(bounds: ClaimLineageBounds) -> ClaimLineageBounds:
    if not isinstance(bounds, ClaimLineageBounds):
        raise IntegrityError(
            "claim_lineage_bounds_invalid",
            "Claim lineage bounds are invalid.",
        )
    values = (
        bounds.max_nodes,
        bounds.max_edges,
        bounds.max_citation_bytes,
        bounds.max_snapshot_bytes,
        bounds.max_output_bytes,
        bounds.max_sqlite_vm_steps,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise IntegrityError(
            "claim_lineage_bounds_invalid",
            "Claim lineage bounds are invalid.",
        )
    if (
        not 1 <= bounds.max_nodes <= _MAX_NODES
        or not 1 <= bounds.max_edges <= _MAX_EDGES
        or not 1 <= bounds.max_citation_bytes <= _MAX_CITATION_BYTES
        or not 1 <= bounds.max_snapshot_bytes <= _MAX_SNAPSHOT_BYTES
        or not 1 <= bounds.max_output_bytes <= _MAX_OUTPUT_BYTES
        or not _MIN_SQLITE_VM_STEPS <= bounds.max_sqlite_vm_steps <= _MAX_SQLITE_VM_STEPS
    ):
        raise IntegrityError(
            "claim_lineage_bounds_invalid",
            "Claim lineage bounds are invalid.",
        )
    return bounds


def _validate_scope_ids(*, mission_id: object, claim_id: object) -> None:
    if not isinstance(mission_id, str) or _MISSION_ID.fullmatch(mission_id) is None:
        raise NotFoundError("mission_not_found")
    if not isinstance(claim_id, str) or _CLAIM_ID.fullmatch(claim_id) is None:
        raise IntegrityError(
            "claim_lineage_scope_invalid",
            "The claim lineage scope is invalid for this mission.",
        )


@contextmanager
def _bounded_query_work(
    connection: sqlite3.Connection,
    max_sqlite_vm_steps: int,
) -> Iterator[None]:
    callbacks_remaining = max_sqlite_vm_steps // _QUERY_PROGRESS_GRANULARITY
    exhausted = False

    def progress() -> int:
        nonlocal callbacks_remaining, exhausted
        callbacks_remaining -= 1
        if callbacks_remaining <= 0:
            exhausted = True
            return 1
        return 0

    connection.set_progress_handler(progress, _QUERY_PROGRESS_GRANULARITY)
    try:
        yield
    except sqlite3.DatabaseError as error:
        if exhausted and getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
            raise IntegrityError(
                "claim_lineage_work_limit",
                "The complete claim lineage graph exceeds its configured work limits.",
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _raise_work_limit() -> Never:
    raise IntegrityError(
        "claim_lineage_work_limit",
        "The complete claim lineage graph exceeds its configured work limits.",
    )


def _raise_inconsistent() -> Never:
    raise IntegrityError(
        "claim_lineage_inconsistent",
        "Stored claim lineage state is invalid.",
    )


def _require_mission(connection: sqlite3.Connection, mission_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM research_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        is None
    ):
        raise NotFoundError("mission_not_found")


def _claim_row(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, mission_id, question_id, statement, falsification_criteria,
               creator_id, run_id, created_at
        FROM claims
        WHERE id = ? AND mission_id = ?
        """,
        (claim_id, mission_id),
    ).fetchone()
    if row is None:
        raise IntegrityError(
            "claim_lineage_scope_invalid",
            "The claim lineage scope is invalid for this mission.",
        )
    if not isinstance(row, sqlite3.Row):
        _raise_inconsistent()
    if _identifier(row["id"], "clm") != claim_id or str(row["mission_id"]) != mission_id:
        _raise_inconsistent()
    return row


def _question_row(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    question_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, mission_id, question_text, creator_id, run_id, created_at
        FROM research_questions
        WHERE id = ?
        """,
        (question_id,),
    ).fetchone()
    if (
        row is None
        or not isinstance(row, sqlite3.Row)
        or _identifier(row["id"], "que") != question_id
        or str(row["mission_id"]) != mission_id
    ):
        _raise_inconsistent()
    return cast(sqlite3.Row, row)


def _status_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    rows = tuple(
        connection.execute(
            """
            SELECT id, claim_id, mission_id, version, status, reason,
                   creator_id, run_id, created_at
            FROM claim_status_events INDEXED BY idx_claim_status_claim
            WHERE claim_id = ?
            ORDER BY version ASC, id ASC
            LIMIT ?
            """,
            (claim_id, limit + 1),
        )
    )
    if len(rows) > limit:
        _raise_work_limit()
    if not rows:
        _raise_inconsistent()
    resolved_ids: set[str] = set()
    for expected_version, row in enumerate(rows, start=1):
        event_id = _identifier(row["id"], "cst")
        if (
            event_id in resolved_ids
            or str(row["mission_id"]) != mission_id
            or _identifier(row["claim_id"], "clm") != claim_id
            or _integer(row["version"]) != expected_version
        ):
            _raise_inconsistent()
        ClaimStatus(str(row["status"]))
        resolved_ids.add(event_id)
    return rows


def _preflight_evidence_quotes(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    max_nodes: int,
    max_citation_bytes: int,
) -> tuple[int, int]:
    rows = tuple(
        connection.execute(
            """
            SELECT id, mission_id, claim_id, start_byte, end_byte,
                   LENGTH(CAST(quote AS BLOB)) AS quote_bytes
            FROM evidence_cards INDEXED BY idx_evidence_claim
            WHERE claim_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (claim_id, max_nodes + 1),
        )
    )
    if len(rows) > max_nodes:
        _raise_work_limit()
    total_bytes = 0
    identifiers: set[str] = set()
    for row in rows:
        evidence_id = _identifier(row["id"], "evd")
        start = _integer(row["start_byte"])
        end = _integer(row["end_byte"])
        quote_bytes = _integer(row["quote_bytes"])
        if (
            evidence_id in identifiers
            or str(row["mission_id"]) != mission_id
            or _identifier(row["claim_id"], "clm") != claim_id
            or start < 0
            or end <= start
            or quote_bytes != end - start
        ):
            _raise_inconsistent()
        identifiers.add(evidence_id)
        total_bytes += quote_bytes
    if total_bytes > max_citation_bytes:
        _raise_work_limit()
    return len(rows), total_bytes


def _evidence_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    limit: int,
    expected_count: int,
) -> tuple[sqlite3.Row, ...]:
    rows = tuple(
        connection.execute(
            """
            SELECT evidence.id, evidence.mission_id, evidence.claim_id,
                   evidence.snapshot_id, evidence.snapshot_sha256,
                   evidence.start_byte, evidence.end_byte, evidence.quote,
                   evidence.stance, evidence.supersedes_evidence_id,
                   evidence.creator_id, evidence.run_id, evidence.created_at,
                   withdrawal.id AS withdrawal_id,
                   withdrawal.mission_id AS withdrawal_mission_id,
                   withdrawal.evidence_id AS withdrawal_evidence_id,
                   withdrawal.reason AS withdrawal_reason,
                   withdrawal.creator_id AS withdrawal_creator_id,
                   withdrawal.run_id AS withdrawal_run_id,
                   withdrawal.created_at AS withdrawal_created_at
            FROM evidence_cards AS evidence INDEXED BY idx_evidence_claim
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            WHERE evidence.claim_id = ?
            ORDER BY evidence.created_at ASC, evidence.id ASC
            LIMIT ?
            """,
            (claim_id, limit + 1),
        )
    )
    if len(rows) > limit:
        _raise_work_limit()
    if len(rows) != expected_count:
        _raise_inconsistent()
    resolved_ids: set[str] = set()
    withdrawal_ids: set[str] = set()
    for row in rows:
        evidence_id = _identifier(row["id"], "evd")
        if (
            evidence_id in resolved_ids
            or str(row["mission_id"]) != mission_id
            or _identifier(row["claim_id"], "clm") != claim_id
        ):
            _raise_inconsistent()
        resolved_ids.add(evidence_id)
        EvidenceStance(str(row["stance"]))
        _digest(row["snapshot_sha256"])
        _provenance(row)
        if row["withdrawal_id"] is not None:
            withdrawal_id = _identifier(row["withdrawal_id"], "wdr")
            if (
                withdrawal_id in withdrawal_ids
                or str(row["withdrawal_mission_id"]) != mission_id
                or _identifier(row["withdrawal_evidence_id"], "evd") != evidence_id
            ):
                _raise_inconsistent()
            withdrawal_ids.add(withdrawal_id)
            _prefixed_provenance(row, "withdrawal_")
    return rows


def _finding_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    rows = tuple(
        connection.execute(
            """
            SELECT finding.id, finding.mission_id, finding.claim_id,
                   finding.statement, finding.statement_kind, finding.status,
                   finding.uncertainty, finding.creator_id, finding.run_id,
                   finding.created_at,
                   retraction.id AS retraction_id,
                   retraction.mission_id AS retraction_mission_id,
                   retraction.finding_id AS retraction_finding_id,
                   retraction.reason AS retraction_reason,
                   retraction.creator_id AS retraction_creator_id,
                   retraction.run_id AS retraction_run_id,
                   retraction.created_at AS retraction_created_at
            FROM findings AS finding INDEXED BY idx_findings_claim
            LEFT JOIN finding_retractions AS retraction
              ON retraction.finding_id = finding.id
            WHERE finding.mission_id = ? AND finding.claim_id = ?
            ORDER BY finding.created_at ASC, finding.id ASC
            LIMIT ?
            """,
            (mission_id, claim_id, limit + 1),
        )
    )
    if len(rows) > limit:
        _raise_work_limit()
    resolved_ids: set[str] = set()
    retraction_ids: set[str] = set()
    for row in rows:
        finding_id = _identifier(row["id"], "fnd")
        if (
            finding_id in resolved_ids
            or str(row["mission_id"]) != mission_id
            or _identifier(row["claim_id"], "clm") != claim_id
        ):
            _raise_inconsistent()
        resolved_ids.add(finding_id)
        StatementKind(str(row["statement_kind"]))
        FindingStatus(str(row["status"]))
        _provenance(row)
        if row["retraction_id"] is not None:
            retraction_id = _identifier(row["retraction_id"], "ret")
            if (
                retraction_id in retraction_ids
                or str(row["retraction_mission_id"]) != mission_id
                or _identifier(row["retraction_finding_id"], "fnd") != finding_id
            ):
                _raise_inconsistent()
            retraction_ids.add(retraction_id)
            _prefixed_provenance(row, "retraction_")
    return rows


def _inference_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    rows = tuple(
        connection.execute(
            """
            SELECT inference.id, inference.mission_id, inference.claim_id,
                   inference.statement, inference.uncertainty,
                   inference.provider, inference.model,
                   inference.request_sha256, inference.candidate_index,
                   inference.response_sha256, inference.system_prompt_version,
                   inference.creator_id, inference.run_id, inference.created_at,
                   retraction.id AS retraction_id,
                   retraction.mission_id AS retraction_mission_id,
                   retraction.inference_id AS retraction_inference_id,
                   retraction.reason AS retraction_reason,
                   retraction.creator_id AS retraction_creator_id,
                   retraction.run_id AS retraction_run_id,
                   retraction.created_at AS retraction_created_at,
                   promotion.id AS promotion_id,
                   promotion.mission_id AS promotion_mission_id,
                   promotion.inference_id AS promotion_inference_id,
                   promotion.finding_id AS promotion_finding_id,
                   promotion.creator_id AS promotion_creator_id,
                   promotion.run_id AS promotion_run_id,
                   promotion.created_at AS promotion_created_at
            FROM agent_inferences AS inference INDEXED BY idx_agent_inferences_claim
            LEFT JOIN agent_inference_retractions AS retraction
              ON retraction.inference_id = inference.id
            LEFT JOIN agent_inference_promotions AS promotion
              ON promotion.inference_id = inference.id
            WHERE inference.mission_id = ? AND inference.claim_id = ?
            ORDER BY inference.created_at ASC, inference.id ASC
            LIMIT ?
            """,
            (mission_id, claim_id, limit + 1),
        )
    )
    if len(rows) > limit:
        _raise_work_limit()
    resolved_ids: set[str] = set()
    retraction_ids: set[str] = set()
    promotion_ids: set[str] = set()
    for row in rows:
        inference_id = _identifier(row["id"], "inf")
        if (
            inference_id in resolved_ids
            or str(row["mission_id"]) != mission_id
            or _identifier(row["claim_id"], "clm") != claim_id
        ):
            _raise_inconsistent()
        resolved_ids.add(inference_id)
        ModelProvider(str(row["provider"]))
        _digest(row["request_sha256"])
        _digest(row["response_sha256"])
        candidate_index = _integer(row["candidate_index"])
        if not 0 <= candidate_index <= 2:
            _raise_inconsistent()
        _provenance(row)
        if row["retraction_id"] is not None:
            retraction_id = _identifier(row["retraction_id"], "inr")
            if (
                retraction_id in retraction_ids
                or str(row["retraction_mission_id"]) != mission_id
                or _identifier(row["retraction_inference_id"], "inf") != inference_id
            ):
                _raise_inconsistent()
            retraction_ids.add(retraction_id)
            _prefixed_provenance(row, "retraction_")
        if row["promotion_id"] is not None:
            promotion_id = _identifier(row["promotion_id"], "inp")
            if (
                promotion_id in promotion_ids
                or str(row["promotion_mission_id"]) != mission_id
                or _identifier(row["promotion_inference_id"], "inf") != inference_id
            ):
                _raise_inconsistent()
            promotion_ids.add(promotion_id)
            _identifier(row["promotion_finding_id"], "fnd")
            _prefixed_provenance(row, "promotion_")
    return rows


def _finding_citation_rows(
    connection: sqlite3.Connection,
    *,
    owner_ids: tuple[str, ...],
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    rows: list[sqlite3.Row] = []
    for chunk in _identifier_chunks(owner_ids):
        placeholders = _placeholders(chunk)
        remaining = limit - len(rows)
        if remaining < 0:
            _raise_work_limit()
        rows.extend(
            connection.execute(
                f"""
                SELECT finding_id, mission_id, evidence_id,
                       creator_id, run_id, created_at
                FROM finding_citations INDEXED BY idx_finding_citations_finding
                WHERE finding_id IN ({placeholders})
                ORDER BY finding_id ASC, evidence_id ASC
                LIMIT ?
                """,  # noqa: S608 - only fixed-count placeholders are composed.
                (*chunk, remaining + 1),
            )
        )
        if len(rows) > limit:
            _raise_work_limit()
    return tuple(sorted(rows, key=lambda row: (str(row["finding_id"]), str(row["evidence_id"]))))


def _inference_citation_rows(
    connection: sqlite3.Connection,
    *,
    owner_ids: tuple[str, ...],
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    rows: list[sqlite3.Row] = []
    for chunk in _identifier_chunks(owner_ids):
        placeholders = _placeholders(chunk)
        remaining = limit - len(rows)
        if remaining < 0:
            _raise_work_limit()
        rows.extend(
            connection.execute(
                f"""
                SELECT inference_id, mission_id, evidence_id,
                       creator_id, run_id, created_at
                FROM agent_inference_citations
                    INDEXED BY idx_agent_inference_citations_inference
                WHERE inference_id IN ({placeholders})
                ORDER BY inference_id ASC, evidence_id ASC
                LIMIT ?
                """,  # noqa: S608 - only fixed-count placeholders are composed.
                (*chunk, remaining + 1),
            )
        )
        if len(rows) > limit:
            _raise_work_limit()
    return tuple(sorted(rows, key=lambda row: (str(row["inference_id"]), str(row["evidence_id"]))))


def _validate_citation_rows(
    rows: tuple[sqlite3.Row, ...],
    *,
    mission_id: str,
    owner_ids: tuple[str, ...],
    evidence_ids: frozenset[str],
    owner_column: str,
) -> dict[str, tuple[str, ...]]:
    owner_prefix = "fnd" if owner_column == "finding_id" else "inf"
    owner_set = frozenset(owner_ids)
    grouped: dict[str, list[str]] = {owner_id: [] for owner_id in owner_ids}
    resolved: set[tuple[str, str]] = set()
    for row in rows:
        owner_id = _identifier(row[owner_column], owner_prefix)
        evidence_id = _identifier(row["evidence_id"], "evd")
        relationship = (owner_id, evidence_id)
        if (
            owner_id not in owner_set
            or evidence_id not in evidence_ids
            or str(row["mission_id"]) != mission_id
            or relationship in resolved
        ):
            _raise_inconsistent()
        resolved.add(relationship)
        grouped[owner_id].append(evidence_id)
        _provenance(row)
    return {owner_id: tuple(sorted(citations)) for owner_id, citations in grouped.items()}


def _validate_finding_citation_policy(
    rows: tuple[sqlite3.Row, ...],
    *,
    citation_map: dict[str, tuple[str, ...]],
) -> None:
    for row in rows:
        finding_id = _identifier(row["id"], "fnd")
        kind = StatementKind(str(row["statement_kind"]))
        if kind.requires_citation and not citation_map.get(finding_id):
            _raise_inconsistent()


def _validate_inference_citation_policy(
    rows: tuple[sqlite3.Row, ...],
    *,
    citation_map: dict[str, tuple[str, ...]],
) -> None:
    for row in rows:
        inference_id = _identifier(row["id"], "inf")
        if not citation_map.get(inference_id):
            _raise_inconsistent()


def _validate_promotions(
    rows: tuple[sqlite3.Row, ...],
    *,
    finding_rows: tuple[sqlite3.Row, ...],
    finding_citations: dict[str, tuple[str, ...]],
    inference_citations: dict[str, tuple[str, ...]],
    mission_id: str,
    claim_id: str,
) -> None:
    findings = {_identifier(row["id"], "fnd"): row for row in finding_rows}
    for row in rows:
        if row["promotion_id"] is None:
            continue
        inference_id = _identifier(row["id"], "inf")
        finding_id = _identifier(row["promotion_finding_id"], "fnd")
        target = findings.get(finding_id)
        if (
            target is None
            or str(target["mission_id"]) != mission_id
            or _identifier(target["claim_id"], "clm") != claim_id
            or str(target["statement"]) != str(row["statement"])
            or str(target["statement_kind"]) != StatementKind.AGENT_INFERENCE.value
            or str(target["uncertainty"]) != str(row["uncertainty"])
            or finding_citations.get(finding_id, ()) != inference_citations.get(inference_id, ())
        ):
            _raise_inconsistent()


def _validate_supersession(
    rows: tuple[sqlite3.Row, ...],
    *,
    evidence_ids: frozenset[str],
) -> None:
    parent_by_id: dict[str, str | None] = {}
    for row in rows:
        evidence_id = _identifier(row["id"], "evd")
        parent = (
            _identifier(row["supersedes_evidence_id"], "evd")
            if row["supersedes_evidence_id"] is not None
            else None
        )
        if parent is not None and (parent == evidence_id or parent not in evidence_ids):
            _raise_inconsistent()
        parent_by_id[evidence_id] = parent
    for evidence_id in parent_by_id:
        seen: set[str] = set()
        current: str | None = evidence_id
        while current is not None:
            if current in seen:
                _raise_inconsistent()
            seen.add(current)
            current = parent_by_id.get(current)


def _snapshot_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    snapshot_ids: tuple[str, ...],
    max_snapshot_bytes: int,
) -> tuple[tuple[sqlite3.Row, ...], int]:
    if not snapshot_ids:
        return (), 0
    rows: list[sqlite3.Row] = []
    for chunk in _identifier_chunks(snapshot_ids):
        placeholders = _placeholders(chunk)
        rows.extend(
            connection.execute(
                f"""
                SELECT snapshot.id, snapshot.source_id, snapshot.mission_id,
                       snapshot.sha256, snapshot.byte_length, snapshot.encoding,
                       snapshot.media_type,
                       snapshot.original_label AS snapshot_original_label,
                       snapshot.imported_at, snapshot.creator_id, snapshot.run_id,
                       TYPEOF(snapshot.content) AS content_type,
                       LENGTH(snapshot.content) AS actual_byte_length,
                       source.id AS source_row_id,
                       source.mission_id AS source_mission_id,
                       source.source_kind, source.original_label AS source_original_label,
                       source.url_metadata AS source_url_metadata,
                       source.creator_id AS source_creator_id,
                       source.run_id AS source_run_id,
                       source.created_at AS source_created_at
                FROM source_snapshots AS snapshot
                LEFT JOIN sources AS source ON source.id = snapshot.source_id
                WHERE snapshot.id IN ({placeholders})
                ORDER BY snapshot.imported_at ASC, snapshot.id ASC
                """,  # noqa: S608 - only fixed-count placeholders are composed.
                chunk,
            )
        )
    ordered = tuple(sorted(rows, key=lambda row: (str(row["imported_at"]), str(row["id"]))))
    resolved_ids = tuple(_identifier(row["id"], "snp") for row in ordered)
    if len(resolved_ids) != len(snapshot_ids) or set(resolved_ids) != set(snapshot_ids):
        _raise_inconsistent()
    total_bytes = 0
    for row in ordered:
        source_id = _identifier(row["source_id"], "src")
        declared_bytes = _integer(row["byte_length"])
        actual_bytes = _integer(row["actual_byte_length"])
        if (
            str(row["mission_id"]) != mission_id
            or row["content_type"] != "blob"
            or declared_bytes <= 0
            or actual_bytes != declared_bytes
            or row["source_row_id"] is None
            or _identifier(row["source_row_id"], "src") != source_id
            or str(row["source_mission_id"]) != mission_id
            or str(row["encoding"]) != "utf-8"
        ):
            _raise_inconsistent()
        _digest(row["sha256"])
        _provenance(row, recorded_at_key="imported_at")
        _prefixed_provenance(row, "source_")
        total_bytes += actual_bytes
    if total_bytes > max_snapshot_bytes:
        _raise_work_limit()
    return ordered, total_bytes


def _verify_evidence(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    evidence_rows: tuple[sqlite3.Row, ...],
    snapshot_cache: SnapshotCache,
) -> dict[str, VerifiedCitation]:
    verified_by_id: dict[str, VerifiedCitation] = {}
    for row in evidence_rows:
        evidence_id = _identifier(row["id"], "evd")
        try:
            verified = verify_evidence_reference(
                connection,
                evidence_id=evidence_id,
                mission_id=mission_id,
                allow_withdrawn=True,
                snapshot_cache=snapshot_cache,
            )
        except NotFoundError as error:
            raise IntegrityError(
                "claim_lineage_inconsistent",
                "Stored claim lineage state is invalid.",
            ) from error
        withdrawn = row["withdrawal_id"] is not None
        if (
            verified.evidence_id != evidence_id
            or verified.mission_id != mission_id
            or verified.claim_id != claim_id
            or verified.snapshot_id != _identifier(row["snapshot_id"], "snp")
            or verified.snapshot_sha256 != _digest(row["snapshot_sha256"])
            or verified.start_byte != _integer(row["start_byte"])
            or verified.end_byte != _integer(row["end_byte"])
            or verified.quote != str(row["quote"])
            or verified.stance is not EvidenceStance(str(row["stance"]))
            or verified.withdrawn is not withdrawn
            or verified.withdrawal_reason != (str(row["withdrawal_reason"]) if withdrawn else None)
            or verified.withdrawn_at != (str(row["withdrawal_created_at"]) if withdrawn else None)
        ):
            _raise_inconsistent()
        verified_by_id[evidence_id] = verified
    return verified_by_id


def _validate_snapshot_cache(
    rows: tuple[sqlite3.Row, ...],
    *,
    snapshot_cache: SnapshotCache,
) -> None:
    row_by_id = {_identifier(row["id"], "snp"): row for row in rows}
    if set(row_by_id) != set(snapshot_cache):
        _raise_inconsistent()
    for snapshot_id, (cached, raw_content) in snapshot_cache.items():
        row = row_by_id.get(snapshot_id)
        if row is None:
            _raise_inconsistent()
        if (
            _identifier(cached["id"], "snp") != snapshot_id
            or _identifier(cached["source_id"], "src") != _identifier(row["source_id"], "src")
            or str(cached["mission_id"]) != str(row["mission_id"])
            or _digest(cached["sha256"]) != _digest(row["sha256"])
            or _integer(cached["byte_length"]) != _integer(row["byte_length"])
            or str(cached["encoding"]) != str(row["encoding"])
            or str(cached["media_type"]) != str(row["media_type"])
            or str(cached["original_label"]) != str(row["snapshot_original_label"])
            or str(cached["creator_id"]) != str(row["creator_id"])
            or _identifier(cached["run_id"], "run") != _identifier(row["run_id"], "run")
            or len(raw_content) != _integer(row["byte_length"])
        ):
            _raise_inconsistent()


def _build_nodes(
    *,
    question_row: sqlite3.Row,
    claim_row: sqlite3.Row,
    status_rows: tuple[sqlite3.Row, ...],
    snapshot_rows: tuple[sqlite3.Row, ...],
    evidence_rows: tuple[sqlite3.Row, ...],
    verified_by_id: dict[str, VerifiedCitation],
    finding_rows: tuple[sqlite3.Row, ...],
    inference_rows: tuple[sqlite3.Row, ...],
) -> tuple[ClaimLineageNode, ...]:
    nodes: list[ClaimLineageNode] = []
    question_id = _identifier(question_row["id"], "que")
    claim_id = _identifier(claim_row["id"], "clm")
    nodes.append(
        ClaimLineageNode(
            node_id=question_id,
            kind=ClaimLineageNodeKind.QUESTION,
            state="recorded",
            payload=QuestionLineageData(
                mission_id=_identifier(question_row["mission_id"], "mis"),
                question_text=_text(question_row["question_text"]),
                provenance=_provenance(question_row),
            ),
        )
    )
    nodes.append(
        ClaimLineageNode(
            node_id=claim_id,
            kind=ClaimLineageNodeKind.CLAIM,
            state="recorded",
            payload=ClaimLineageData(
                mission_id=_identifier(claim_row["mission_id"], "mis"),
                question_id=question_id,
                statement=_text(claim_row["statement"]),
                falsification_criteria=_text(claim_row["falsification_criteria"]),
                provenance=_provenance(claim_row),
            ),
        )
    )
    current_version = len(status_rows)
    for row in status_rows:
        version = _integer(row["version"])
        nodes.append(
            ClaimLineageNode(
                node_id=_identifier(row["id"], "cst"),
                kind=ClaimLineageNodeKind.CLAIM_STATUS_EVENT,
                state="current" if version == current_version else "historical",
                payload=ClaimStatusEventLineageData(
                    mission_id=_identifier(row["mission_id"], "mis"),
                    claim_id=_identifier(row["claim_id"], "clm"),
                    version=version,
                    status=ClaimStatus(str(row["status"])),
                    reason=_text(row["reason"]),
                    is_current=version == current_version,
                    provenance=_provenance(row),
                ),
            )
        )
    for row in snapshot_rows:
        nodes.append(
            ClaimLineageNode(
                node_id=_identifier(row["id"], "snp"),
                kind=ClaimLineageNodeKind.SNAPSHOT,
                state="immutable",
                payload=SnapshotLineageData(
                    mission_id=_identifier(row["mission_id"], "mis"),
                    source_id=_identifier(row["source_id"], "src"),
                    source_kind=_text(row["source_kind"]),
                    source_original_label=_text(row["source_original_label"]),
                    source_url_metadata=(
                        _text(row["source_url_metadata"])
                        if row["source_url_metadata"] is not None
                        else None
                    ),
                    source_provenance=_prefixed_provenance(row, "source_"),
                    snapshot_sha256=_digest(row["sha256"]),
                    byte_length=_integer(row["byte_length"]),
                    encoding=_text(row["encoding"]),
                    media_type=_text(row["media_type"]),
                    snapshot_original_label=_text(row["snapshot_original_label"]),
                    provenance=_provenance(row, recorded_at_key="imported_at"),
                ),
            )
        )
    for row in evidence_rows:
        evidence_id = _identifier(row["id"], "evd")
        verified = verified_by_id[evidence_id]
        quote_bytes = verified.quote.encode("utf-8", errors="strict")
        nodes.append(
            ClaimLineageNode(
                node_id=evidence_id,
                kind=ClaimLineageNodeKind.EVIDENCE,
                state="withdrawn" if row["withdrawal_id"] is not None else "active",
                payload=EvidenceLineageData(
                    mission_id=_identifier(row["mission_id"], "mis"),
                    claim_id=_identifier(row["claim_id"], "clm"),
                    snapshot_id=verified.snapshot_id,
                    snapshot_sha256=verified.snapshot_sha256,
                    start_byte=verified.start_byte,
                    end_byte=verified.end_byte,
                    quote=verified.quote,
                    quote_utf8_base64=base64.b64encode(quote_bytes).decode("ascii"),
                    quote_byte_length=len(quote_bytes),
                    quote_sha256=sha256(quote_bytes).hexdigest(),
                    stance=verified.stance,
                    supersedes_evidence_id=(
                        _identifier(row["supersedes_evidence_id"], "evd")
                        if row["supersedes_evidence_id"] is not None
                        else None
                    ),
                    provenance=_provenance(row),
                ),
            )
        )
        if row["withdrawal_id"] is not None:
            nodes.append(
                ClaimLineageNode(
                    node_id=_identifier(row["withdrawal_id"], "wdr"),
                    kind=ClaimLineageNodeKind.EVIDENCE_WITHDRAWAL,
                    state="recorded",
                    payload=CorrectionLineageData(
                        mission_id=_identifier(row["withdrawal_mission_id"], "mis"),
                        target_id=evidence_id,
                        reason=_text(row["withdrawal_reason"]),
                        provenance=_prefixed_provenance(row, "withdrawal_"),
                    ),
                )
            )
    for row in finding_rows:
        finding_id = _identifier(row["id"], "fnd")
        nodes.append(
            ClaimLineageNode(
                node_id=finding_id,
                kind=ClaimLineageNodeKind.FINDING,
                state="retracted" if row["retraction_id"] is not None else "active",
                payload=FindingLineageData(
                    mission_id=_identifier(row["mission_id"], "mis"),
                    claim_id=_identifier(row["claim_id"], "clm"),
                    statement=_text(row["statement"]),
                    statement_kind=StatementKind(str(row["statement_kind"])),
                    status=FindingStatus(str(row["status"])),
                    uncertainty=_text(row["uncertainty"], allow_empty=True),
                    provenance=_provenance(row),
                ),
            )
        )
        if row["retraction_id"] is not None:
            nodes.append(
                ClaimLineageNode(
                    node_id=_identifier(row["retraction_id"], "ret"),
                    kind=ClaimLineageNodeKind.FINDING_RETRACTION,
                    state="recorded",
                    payload=CorrectionLineageData(
                        mission_id=_identifier(row["retraction_mission_id"], "mis"),
                        target_id=finding_id,
                        reason=_text(row["retraction_reason"]),
                        provenance=_prefixed_provenance(row, "retraction_"),
                    ),
                )
            )
    for row in inference_rows:
        inference_id = _identifier(row["id"], "inf")
        nodes.append(
            ClaimLineageNode(
                node_id=inference_id,
                kind=ClaimLineageNodeKind.AGENT_INFERENCE,
                state="retracted" if row["retraction_id"] is not None else "active",
                payload=AgentInferenceLineageData(
                    mission_id=_identifier(row["mission_id"], "mis"),
                    claim_id=_identifier(row["claim_id"], "clm"),
                    statement=_text(row["statement"]),
                    uncertainty=_text(row["uncertainty"]),
                    provider=ModelProvider(str(row["provider"])),
                    model=_text(row["model"]),
                    request_sha256=_digest(row["request_sha256"]),
                    candidate_index=_integer(row["candidate_index"]),
                    response_sha256=_digest(row["response_sha256"]),
                    system_prompt_version=_text(row["system_prompt_version"]),
                    provenance=_provenance(row),
                ),
            )
        )
        if row["retraction_id"] is not None:
            nodes.append(
                ClaimLineageNode(
                    node_id=_identifier(row["retraction_id"], "inr"),
                    kind=ClaimLineageNodeKind.AGENT_INFERENCE_RETRACTION,
                    state="recorded",
                    payload=CorrectionLineageData(
                        mission_id=_identifier(row["retraction_mission_id"], "mis"),
                        target_id=inference_id,
                        reason=_text(row["retraction_reason"]),
                        provenance=_prefixed_provenance(row, "retraction_"),
                    ),
                )
            )
        if row["promotion_id"] is not None:
            nodes.append(
                ClaimLineageNode(
                    node_id=_identifier(row["promotion_id"], "inp"),
                    kind=ClaimLineageNodeKind.AGENT_INFERENCE_PROMOTION,
                    state="recorded",
                    payload=PromotionLineageData(
                        mission_id=_identifier(row["promotion_mission_id"], "mis"),
                        inference_id=inference_id,
                        finding_id=_identifier(row["promotion_finding_id"], "fnd"),
                        provenance=_prefixed_provenance(row, "promotion_"),
                    ),
                )
            )
    return tuple(sorted(nodes, key=_node_sort_key))


def _build_edges(
    *,
    question_row: sqlite3.Row,
    claim_row: sqlite3.Row,
    status_rows: tuple[sqlite3.Row, ...],
    evidence_rows: tuple[sqlite3.Row, ...],
    finding_rows: tuple[sqlite3.Row, ...],
    inference_rows: tuple[sqlite3.Row, ...],
    finding_citations: tuple[sqlite3.Row, ...],
    inference_citations: tuple[sqlite3.Row, ...],
) -> tuple[ClaimLineageEdge, ...]:
    edges: list[ClaimLineageEdge] = []
    question_id = _identifier(question_row["id"], "que")
    claim_id = _identifier(claim_row["id"], "clm")
    edges.append(
        ClaimLineageEdge(
            relation=ClaimLineageRelation.QUESTION_HAS_CLAIM,
            source_node_id=question_id,
            target_node_id=claim_id,
            provenance=_provenance(claim_row),
        )
    )
    previous_status_id: str | None = None
    for row in status_rows:
        status_id = _identifier(row["id"], "cst")
        provenance = _provenance(row)
        edges.append(
            ClaimLineageEdge(
                relation=ClaimLineageRelation.CLAIM_HAS_STATUS_EVENT,
                source_node_id=claim_id,
                target_node_id=status_id,
                provenance=provenance,
            )
        )
        if previous_status_id is not None:
            edges.append(
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.STATUS_EVENT_PRECEDES,
                    source_node_id=previous_status_id,
                    target_node_id=status_id,
                    provenance=provenance,
                )
            )
        previous_status_id = status_id
    for row in evidence_rows:
        evidence_id = _identifier(row["id"], "evd")
        provenance = _provenance(row)
        edges.extend(
            (
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.CLAIM_HAS_EVIDENCE,
                    source_node_id=claim_id,
                    target_node_id=evidence_id,
                    provenance=provenance,
                ),
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.EVIDENCE_CITES_SNAPSHOT,
                    source_node_id=evidence_id,
                    target_node_id=_identifier(row["snapshot_id"], "snp"),
                    provenance=provenance,
                ),
            )
        )
        if row["supersedes_evidence_id"] is not None:
            edges.append(
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.EVIDENCE_SUPERSEDES_EVIDENCE,
                    source_node_id=evidence_id,
                    target_node_id=_identifier(row["supersedes_evidence_id"], "evd"),
                    provenance=provenance,
                )
            )
        if row["withdrawal_id"] is not None:
            edges.append(
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.EVIDENCE_HAS_WITHDRAWAL,
                    source_node_id=evidence_id,
                    target_node_id=_identifier(row["withdrawal_id"], "wdr"),
                    provenance=_prefixed_provenance(row, "withdrawal_"),
                )
            )
    for row in finding_rows:
        finding_id = _identifier(row["id"], "fnd")
        edges.append(
            ClaimLineageEdge(
                relation=ClaimLineageRelation.CLAIM_HAS_FINDING,
                source_node_id=claim_id,
                target_node_id=finding_id,
                provenance=_provenance(row),
            )
        )
        if row["retraction_id"] is not None:
            edges.append(
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.FINDING_HAS_RETRACTION,
                    source_node_id=finding_id,
                    target_node_id=_identifier(row["retraction_id"], "ret"),
                    provenance=_prefixed_provenance(row, "retraction_"),
                )
            )
    for row in finding_citations:
        edges.append(
            ClaimLineageEdge(
                relation=ClaimLineageRelation.FINDING_CITES_EVIDENCE,
                source_node_id=_identifier(row["finding_id"], "fnd"),
                target_node_id=_identifier(row["evidence_id"], "evd"),
                provenance=_provenance(row),
            )
        )
    for row in inference_rows:
        inference_id = _identifier(row["id"], "inf")
        edges.append(
            ClaimLineageEdge(
                relation=ClaimLineageRelation.CLAIM_HAS_AGENT_INFERENCE,
                source_node_id=claim_id,
                target_node_id=inference_id,
                provenance=_provenance(row),
            )
        )
        if row["retraction_id"] is not None:
            edges.append(
                ClaimLineageEdge(
                    relation=ClaimLineageRelation.AGENT_INFERENCE_HAS_RETRACTION,
                    source_node_id=inference_id,
                    target_node_id=_identifier(row["retraction_id"], "inr"),
                    provenance=_prefixed_provenance(row, "retraction_"),
                )
            )
        if row["promotion_id"] is not None:
            promotion_id = _identifier(row["promotion_id"], "inp")
            promotion_provenance = _prefixed_provenance(row, "promotion_")
            edges.extend(
                (
                    ClaimLineageEdge(
                        relation=ClaimLineageRelation.AGENT_INFERENCE_HAS_PROMOTION,
                        source_node_id=inference_id,
                        target_node_id=promotion_id,
                        provenance=promotion_provenance,
                    ),
                    ClaimLineageEdge(
                        relation=ClaimLineageRelation.PROMOTION_CREATED_FINDING,
                        source_node_id=promotion_id,
                        target_node_id=_identifier(row["promotion_finding_id"], "fnd"),
                        provenance=promotion_provenance,
                    ),
                )
            )
    for row in inference_citations:
        edges.append(
            ClaimLineageEdge(
                relation=ClaimLineageRelation.AGENT_INFERENCE_CITES_EVIDENCE,
                source_node_id=_identifier(row["inference_id"], "inf"),
                target_node_id=_identifier(row["evidence_id"], "evd"),
                provenance=_provenance(row),
            )
        )
    return tuple(sorted(edges, key=_edge_sort_key))


def _validate_graph(
    nodes: tuple[ClaimLineageNode, ...],
    edges: tuple[ClaimLineageEdge, ...],
    *,
    max_nodes: int,
    max_edges: int,
) -> None:
    if len(nodes) > max_nodes or len(edges) > max_edges:
        _raise_work_limit()
    if nodes != tuple(sorted(nodes, key=_node_sort_key)):
        _raise_inconsistent()
    if edges != tuple(sorted(edges, key=_edge_sort_key)):
        _raise_inconsistent()
    node_ids = tuple(node.node_id for node in nodes)
    if len(set(node_ids)) != len(node_ids):
        _raise_inconsistent()
    node_id_set = frozenset(node_ids)
    edge_keys = tuple(
        (edge.relation.value, edge.source_node_id, edge.target_node_id) for edge in edges
    )
    if len(set(edge_keys)) != len(edge_keys):
        _raise_inconsistent()
    if any(
        edge.source_node_id not in node_id_set or edge.target_node_id not in node_id_set
        for edge in edges
    ):
        _raise_inconsistent()
    claim_nodes = tuple(node.node_id for node in nodes if node.kind is ClaimLineageNodeKind.CLAIM)
    question_nodes = tuple(
        node.node_id for node in nodes if node.kind is ClaimLineageNodeKind.QUESTION
    )
    status_nodes = tuple(
        node.node_id for node in nodes if node.kind is ClaimLineageNodeKind.CLAIM_STATUS_EVENT
    )
    if len(claim_nodes) != 1 or len(question_nodes) != 1 or not status_nodes:
        _raise_inconsistent()
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        adjacency[edge.source_node_id].add(edge.target_node_id)
        adjacency[edge.target_node_id].add(edge.source_node_id)
    reachable: set[str] = set()
    pending = [claim_nodes[0]]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(sorted(adjacency[current] - reachable, reverse=True))
    if reachable != set(node_ids):
        _raise_inconsistent()


def _node_sort_key(node: ClaimLineageNode) -> tuple[int, int, str, str]:
    kind_order = _NODE_ORDER[node.kind]
    if isinstance(node.payload, ClaimStatusEventLineageData):
        return (kind_order, node.payload.version, "", node.node_id)
    return (
        kind_order,
        0,
        node.payload.provenance.recorded_at,
        node.node_id,
    )


def _edge_sort_key(edge: ClaimLineageEdge) -> tuple[int, str, str]:
    return (
        _EDGE_ORDER[edge.relation],
        edge.source_node_id,
        edge.target_node_id,
    )


def _identifier(value: object, prefix: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            rf"{re.escape(prefix)}_[0-9a-f]{{32}}\Z",
            value,
        )
        is None
    ):
        _raise_inconsistent()
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _raise_inconsistent()
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _raise_inconsistent()
    return value


def _text(value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        _raise_inconsistent()
    if "\x00" in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        _raise_inconsistent()
    value.encode("utf-8", errors="strict")
    return value


def _provenance(
    row: sqlite3.Row,
    *,
    recorded_at_key: str = "created_at",
) -> LineageProvenance:
    return LineageProvenance(
        creator_id=_text(row["creator_id"]),
        run_id=_identifier(row["run_id"], "run"),
        recorded_at=_text(row[recorded_at_key]),
    )


def _prefixed_provenance(row: sqlite3.Row, prefix: str) -> LineageProvenance:
    return LineageProvenance(
        creator_id=_text(row[f"{prefix}creator_id"]),
        run_id=_identifier(row[f"{prefix}run_id"], "run"),
        recorded_at=_text(row[f"{prefix}created_at"]),
    )


def _placeholders(values: Sequence[object]) -> str:
    if not values:
        raise AssertionError("SQL placeholder list cannot be empty")
    return ",".join("?" for _ in values)


def _identifier_chunks(values: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    for start in range(0, len(values), _SQL_IDENTIFIER_CHUNK):
        yield values[start : start + _SQL_IDENTIFIER_CHUNK]


def _node_set_digest(
    *,
    mission_id: str,
    claim_id: str,
    nodes: tuple[ClaimLineageNode, ...],
) -> str:
    return sha256(
        _canonical_json_bytes(
            {
                "schema_version": CLAIM_LINEAGE_NODE_SET_SCHEMA_VERSION,
                "mission_id": mission_id,
                "claim_id": claim_id,
                "nodes": [asdict(node) for node in nodes],
            }
        )
    ).hexdigest()


def _edge_set_digest(
    *,
    mission_id: str,
    claim_id: str,
    edges: tuple[ClaimLineageEdge, ...],
) -> str:
    return sha256(
        _canonical_json_bytes(
            {
                "schema_version": CLAIM_LINEAGE_EDGE_SET_SCHEMA_VERSION,
                "mission_id": mission_id,
                "claim_id": claim_id,
                "edges": [asdict(edge) for edge in edges],
            }
        )
    ).hexdigest()


def _snapshot_set_digest(
    *,
    mission_id: str,
    claim_id: str,
    snapshot_rows: tuple[sqlite3.Row, ...],
) -> str:
    snapshots = [
        {
            "source_id": _identifier(row["source_id"], "src"),
            "snapshot_id": _identifier(row["id"], "snp"),
            "snapshot_sha256": _digest(row["sha256"]),
            "byte_length": _integer(row["byte_length"]),
            "encoding": _text(row["encoding"]),
            "media_type": _text(row["media_type"]),
            "original_label": _text(row["snapshot_original_label"]),
            "imported_at": _text(row["imported_at"]),
        }
        for row in snapshot_rows
    ]
    return sha256(
        _canonical_json_bytes(
            {
                "schema_version": CLAIM_LINEAGE_SNAPSHOT_SET_SCHEMA_VERSION,
                "mission_id": mission_id,
                "claim_id": claim_id,
                "snapshots": snapshots,
            }
        )
    ).hexdigest()


def _lineage_receipt_digest(result: ClaimLineageResult) -> str:
    payload = asdict(result)
    payload.pop("lineage_receipt_sha256")
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
