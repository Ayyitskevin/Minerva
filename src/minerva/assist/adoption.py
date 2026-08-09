"""Human adoption, retraction, and promotion of persisted agent inferences.

Adoption is the first point at which untrusted model output becomes durable, so
it revalidates rather than trusting the generation-time checks: every citation
is re-verified against the live record, the text is rescanned for secret
patterns, and size bounds are enforced against the stored value. Every mutation
is a normal atomic mutation-plus-audit transaction; a failed adoption leaves
nothing behind, and regret is handled by retraction, never deletion.
"""

from __future__ import annotations

import hmac
import re
import sqlite3

from minerva.assist.models import (
    AgentInference,
    CandidatePreview,
    FindingCandidate,
    ModelProvider,
)
from minerva.assist.service import MAX_ASSISTANCE_EVIDENCE_CARDS
from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError, SecurityBoundaryError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now, validate_text
from minerva.evidence.integrity import new_snapshot_cache, verify_evidence_reference
from minerva.research.models import Finding, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.files import scan_secret_patterns

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class AdoptionService:
    def __init__(
        self,
        database: Database,
        *,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> None:
        self.database = database
        self._clock = clock
        self._id_factory = id_factory
        self._audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)

    def adopt_inference(
        self,
        *,
        preview: CandidatePreview,
        expected_request_sha256: str,
        candidate_index: int,
        candidate: FindingCandidate,
        response_sha256: str,
        identity: IdentityContext,
    ) -> AgentInference:
        """Persist one candidate from one exact preview as a labeled agent inference.

        `expected_request_sha256` is the digest of the request the operator
        actually reviewed and sent, and it is the same pin the invoke path
        requires. Adoption regenerates the preview from live state, so without
        it a ledger change between generation and adoption stores an adopt-time
        request digest beside the generation-time response digest -- a
        provenance pair that never existed on the wire -- and the unique triple
        `(request_sha256, candidate_index, claim_id)` moves with it, so the same
        reviewed candidate adopts twice. The pin is compared before anything is
        read or written, and a mismatch persists nothing.
        """

        if _DIGEST.fullmatch(expected_request_sha256) is None:
            raise IntegrityError(
                "inference_request_digest_invalid",
                "The expected request digest is invalid.",
            )
        if not hmac.compare_digest(expected_request_sha256, preview.request_sha256):
            raise ConflictError(
                "assistant_context_changed",
                "Research context changed since the reviewed request; nothing was adopted.",
            )
        if (
            isinstance(candidate_index, bool)
            or not isinstance(candidate_index, int)
            or not 0 <= candidate_index < preview.max_candidates
        ):
            raise IntegrityError(
                "inference_candidate_index_invalid",
                "The adopted candidate index is outside the authorized preview.",
            )
        if _DIGEST.fullmatch(response_sha256) is None:
            raise IntegrityError(
                "inference_response_digest_invalid",
                "The provider response digest is invalid.",
            )
        statement = validate_text(candidate.statement, field="statement", maximum=4_000)
        uncertainty = validate_text(candidate.uncertainty, field="uncertainty", maximum=2_000)
        if (
            scan_secret_patterns(statement) is not None
            or scan_secret_patterns(uncertainty) is not None
        ):
            raise SecurityBoundaryError(
                "assistant_adoption_secret_detected",
                "The adopted candidate matches a blocked secret pattern.",
            )
        unique_evidence = tuple(dict.fromkeys(candidate.evidence_ids))
        if not unique_evidence:
            raise IntegrityError(
                "inference_citation_required",
                "An adopted inference requires at least one citation.",
            )
        if len(unique_evidence) > MAX_ASSISTANCE_EVIDENCE_CARDS:
            raise IntegrityError(
                "inference_citation_limit",
                "An adopted inference exceeds its citation limit.",
            )
        inference_id = self._id_factory("inf")
        created_at = self._clock()
        with self.database.transaction() as connection:
            claim = connection.execute(
                "SELECT 1 FROM claims WHERE id = ? AND mission_id = ?",
                (preview.claim_id, preview.mission_id),
            ).fetchone()
            if claim is None:
                raise NotFoundError("claim_not_found")
            if connection.execute(
                """
                SELECT 1 FROM agent_inferences
                WHERE request_sha256 = ? AND candidate_index = ? AND claim_id = ?
                """,
                (preview.request_sha256, candidate_index, preview.claim_id),
            ).fetchone():
                raise ConflictError(
                    "inference_already_adopted",
                    "This candidate has already been adopted.",
                )
            # Citations are revalidated, not trusted: each cited card must still
            # exist, still belong to this claim and mission, and still be
            # active. Evidence may have been withdrawn since the preview.
            snapshot_cache = new_snapshot_cache()
            for evidence_id in unique_evidence:
                citation = verify_evidence_reference(
                    connection,
                    evidence_id=evidence_id,
                    mission_id=preview.mission_id,
                    allow_withdrawn=False,
                    snapshot_cache=snapshot_cache,
                )
                if citation.claim_id != preview.claim_id:
                    raise IntegrityError(
                        "inference_citation_scope_invalid",
                        "An inference citation must evaluate its linked claim.",
                    )
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO agent_inferences(
                    id, mission_id, claim_id, statement, uncertainty, provider, model,
                    request_sha256, candidate_index, response_sha256, system_prompt_version,
                    creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inference_id,
                    preview.mission_id,
                    preview.claim_id,
                    statement,
                    uncertainty,
                    preview.provider.value,
                    preview.model,
                    preview.request_sha256,
                    candidate_index,
                    response_sha256,
                    preview.system_prompt_version,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            for evidence_id in unique_evidence:
                connection.execute(
                    """
                    INSERT INTO agent_inference_citations(
                        inference_id, mission_id, evidence_id, creator_id, run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inference_id,
                        preview.mission_id,
                        evidence_id,
                        identity.actor_id,
                        identity.run_id,
                        created_at,
                    ),
                )
            self._audit.record(
                connection,
                identity=identity,
                event_type="assist.inference.adopted",
                entity_type="agent_inference",
                entity_id=inference_id,
                mission_id=preview.mission_id,
                # Digests and bounded metadata only, exactly as for the
                # invocation audit events: the adopted text lives in the
                # record itself, never in the audit log.
                details={
                    "candidate_index": candidate_index,
                    "citation_count": len(unique_evidence),
                    "model": preview.model,
                    "provider": preview.provider.value,
                    "request_sha256": preview.request_sha256,
                    "response_sha256": response_sha256,
                    "system_prompt_version": preview.system_prompt_version,
                },
            )
        return AgentInference(
            id=inference_id,
            mission_id=preview.mission_id,
            claim_id=preview.claim_id,
            statement=statement,
            uncertainty=uncertainty,
            provider=preview.provider,
            model=preview.model,
            request_sha256=preview.request_sha256,
            candidate_index=candidate_index,
            response_sha256=response_sha256,
            system_prompt_version=preview.system_prompt_version,
            evidence_ids=unique_evidence,
            creator_id=identity.actor_id,
            run_id=identity.run_id,
            created_at=created_at,
        )

    def retract_inference(
        self,
        *,
        inference_id: str,
        reason: str,
        identity: IdentityContext,
    ) -> str:
        """Record that an adopted inference is no longer asserted, without editing it.

        Mirrors finding retraction exactly: a separate append-only record, with
        the inference, its citations, and its audit history all remaining.
        """

        reason = validate_text(reason, field="reason", maximum=1_000)
        retraction_id = self._id_factory("inr")
        created_at = self._clock()
        with self.database.transaction() as connection:
            inference = connection.execute(
                "SELECT mission_id FROM agent_inferences WHERE id = ?",
                (inference_id,),
            ).fetchone()
            if inference is None:
                raise NotFoundError("inference_not_found")
            if connection.execute(
                "SELECT 1 FROM agent_inference_retractions WHERE inference_id = ?",
                (inference_id,),
            ).fetchone():
                raise ConflictError(
                    "inference_already_retracted", "The inference is already retracted."
                )
            mission_id = str(inference["mission_id"])
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO agent_inference_retractions(
                    id, mission_id, inference_id, reason, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retraction_id,
                    mission_id,
                    inference_id,
                    reason,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="assist.inference.retracted",
                entity_type="agent_inference",
                entity_id=inference_id,
                mission_id=mission_id,
                details={"retraction_id": retraction_id},
            )
        return retraction_id

    def promote_inference_to_finding(
        self,
        *,
        inference_id: str,
        status: FindingStatus,
        identity: IdentityContext,
    ) -> Finding:
        """Create the human finding for an inference and link them in one transaction.

        The finding is the human's assertion; the inference remains as its
        provenance. The link is a separate append-only row because the update
        triggers correctly forbid setting a link column after insert, and one
        inference promotes at most once.
        """

        if not isinstance(status, FindingStatus):
            raise IntegrityError("finding_status_invalid", "Finding status is invalid.")
        research = ResearchService(
            self.database,
            audit=self._audit,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        promotion_id = self._id_factory("inp")
        created_at = self._clock()
        with self.database.transaction() as connection:
            inference = connection.execute(
                """
                SELECT mission_id, claim_id, statement, uncertainty
                FROM agent_inferences WHERE id = ?
                """,
                (inference_id,),
            ).fetchone()
            if inference is None:
                raise NotFoundError("inference_not_found")
            if connection.execute(
                "SELECT 1 FROM agent_inference_retractions WHERE inference_id = ?",
                (inference_id,),
            ).fetchone():
                raise ConflictError(
                    "inference_retracted", "A retracted inference cannot be promoted."
                )
            if connection.execute(
                "SELECT 1 FROM agent_inference_promotions WHERE inference_id = ?",
                (inference_id,),
            ).fetchone():
                raise ConflictError(
                    "inference_already_promoted", "The inference is already promoted."
                )
            mission_id = str(inference["mission_id"])
            claim_id = str(inference["claim_id"])
            evidence_ids = tuple(
                str(item["evidence_id"])
                for item in connection.execute(
                    """
                    SELECT evidence_id FROM agent_inference_citations
                    WHERE inference_id = ? ORDER BY evidence_id
                    """,
                    (inference_id,),
                )
            )
            finding = research.add_finding(
                mission_id=mission_id,
                claim_id=claim_id,
                statement=str(inference["statement"]),
                statement_kind=StatementKind.AGENT_INFERENCE,
                status=status,
                uncertainty=str(inference["uncertainty"]),
                evidence_ids=evidence_ids,
                identity=identity,
                connection=connection,
            )
            connection.execute(
                """
                INSERT INTO agent_inference_promotions(
                    id, mission_id, inference_id, finding_id, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    promotion_id,
                    mission_id,
                    inference_id,
                    finding.id,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="assist.inference.promoted",
                entity_type="agent_inference",
                entity_id=inference_id,
                mission_id=mission_id,
                details={"finding_id": finding.id, "promotion_id": promotion_id},
            )
        return finding

    def get_inference(
        self,
        inference_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> AgentInference:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.get_inference(inference_id, connection=owned_connection)
        row = connection.execute(
            f"""
            SELECT {_INFERENCE_READ_COLUMNS}
            {_INFERENCE_READ_SOURCE}
            WHERE inference.id = ?
            """,
            (inference_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("inference_not_found")
        return _inference_from_row(connection, row)

    def list_inferences(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[AgentInference, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_inferences(mission_id, connection=owned_connection)
        if (
            connection.execute(
                "SELECT 1 FROM research_missions WHERE id = ?",
                (mission_id,),
            ).fetchone()
            is None
        ):
            raise NotFoundError("mission_not_found")
        rows = list(
            connection.execute(
                f"""
                SELECT {_INFERENCE_READ_COLUMNS}
                {_INFERENCE_READ_SOURCE}
                WHERE inference.mission_id = ?
                ORDER BY inference.created_at ASC, inference.id ASC
                """,
                (mission_id,),
            )
        )
        return tuple(_inference_from_row(connection, row) for row in rows)

    def list_inferences_for_claim(
        self,
        claim_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[AgentInference, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_inferences_for_claim(claim_id, connection=owned_connection)
        claim = connection.execute(
            "SELECT mission_id FROM claims WHERE id = ?",
            (claim_id,),
        ).fetchone()
        if claim is None:
            raise NotFoundError("claim_not_found")
        rows = list(
            connection.execute(
                f"""
                SELECT {_INFERENCE_READ_COLUMNS}
                {_INFERENCE_READ_SOURCE}
                WHERE inference.mission_id = ? AND inference.claim_id = ?
                ORDER BY inference.created_at ASC, inference.id ASC
                """,
                (str(claim["mission_id"]), claim_id),
            )
        )
        return tuple(_inference_from_row(connection, row) for row in rows)


# Inferences are read through one left join pair so a retracted inference can
# never be presented as an asserted one and a promoted one always names its
# finding. Both joins are on mission-composite keys and both side tables carry
# UNIQUE(inference_id), so they cannot multiply rows; every column is aliased
# because the tables share `mission_id`, `created_at`, and `creator_id`.
_INFERENCE_READ_COLUMNS = """
                    inference.id AS id,
                    inference.mission_id AS mission_id,
                    inference.claim_id AS claim_id,
                    inference.statement AS statement,
                    inference.uncertainty AS uncertainty,
                    inference.provider AS provider,
                    inference.model AS model,
                    inference.request_sha256 AS request_sha256,
                    inference.candidate_index AS candidate_index,
                    inference.response_sha256 AS response_sha256,
                    inference.system_prompt_version AS system_prompt_version,
                    inference.creator_id AS creator_id,
                    inference.run_id AS run_id,
                    inference.created_at AS created_at,
                    retraction.reason AS retraction_reason,
                    retraction.created_at AS retracted_at,
                    retraction.creator_id AS retracted_by,
                    promotion.finding_id AS promoted_finding_id
""".strip()

_INFERENCE_READ_SOURCE = """
                    FROM agent_inferences AS inference
                    LEFT JOIN agent_inference_retractions AS retraction
                      ON retraction.inference_id = inference.id
                     AND retraction.mission_id = inference.mission_id
                    LEFT JOIN agent_inference_promotions AS promotion
                      ON promotion.inference_id = inference.id
                     AND promotion.mission_id = inference.mission_id
""".strip()


def _inference_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> AgentInference:
    citation_rows = list(
        connection.execute(
            """
            SELECT evidence_id FROM agent_inference_citations
            WHERE inference_id = ? ORDER BY evidence_id
            """,
            (str(row["id"]),),
        )
    )
    retracted_at = row["retracted_at"]
    promoted_finding_id = row["promoted_finding_id"]
    return AgentInference(
        id=str(row["id"]),
        mission_id=str(row["mission_id"]),
        claim_id=str(row["claim_id"]),
        statement=str(row["statement"]),
        uncertainty=str(row["uncertainty"]),
        provider=ModelProvider(str(row["provider"])),
        model=str(row["model"]),
        request_sha256=str(row["request_sha256"]),
        candidate_index=int(row["candidate_index"]),
        response_sha256=str(row["response_sha256"]),
        system_prompt_version=str(row["system_prompt_version"]),
        evidence_ids=tuple(str(item["evidence_id"]) for item in citation_rows),
        creator_id=str(row["creator_id"]),
        run_id=str(row["run_id"]),
        created_at=str(row["created_at"]),
        retracted=retracted_at is not None,
        retraction_reason=(
            str(row["retraction_reason"]) if row["retraction_reason"] is not None else None
        ),
        retracted_at=(str(retracted_at) if retracted_at is not None else None),
        retracted_by=(str(row["retracted_by"]) if row["retracted_by"] is not None else None),
        promoted_finding_id=(str(promoted_finding_id) if promoted_finding_id is not None else None),
    )
