"""Public domain objects, never raw SQLite rows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClaimStatus(StrEnum):
    OPEN = "open"
    PROVISIONALLY_SUPPORTED = "provisionally_supported"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class StatementKind(StrEnum):
    OBSERVED_FACT = "observed_fact"
    SOURCE_ASSERTION = "source_assertion"
    AGENT_INFERENCE = "agent_inference"
    ASSUMPTION = "assumption"
    CALCULATION = "calculation"
    RECOMMENDATION = "recommendation"
    UNRESOLVED_QUESTION = "unresolved_question"

    @property
    def requires_citation(self) -> bool:
        return self not in {StatementKind.ASSUMPTION, StatementKind.UNRESOLVED_QUESTION}


class FindingStatus(StrEnum):
    SUPPORTED = "supported"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class CitationStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class Mission:
    id: str
    title: str
    objective: str
    creator_id: str
    run_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    mission_id: str
    text: str
    creator_id: str
    run_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    mission_id: str
    question_id: str
    statement: str
    falsification_criteria: str
    status: ClaimStatus
    version: int
    status_reason: str
    status_creator_id: str
    status_run_id: str
    status_changed_at: str
    status_evidence_valid: bool
    creator_id: str
    run_id: str
    created_at: str

    @property
    def etag(self) -> str:
        return f'"claim-{self.id}-v{self.version}"'


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    mission_id: str
    claim_id: str | None
    statement: str
    statement_kind: StatementKind
    status: FindingStatus
    uncertainty: str
    evidence_ids: tuple[str, ...]
    citation_status: CitationStatus
    creator_id: str
    run_id: str
    created_at: str
    # Retraction mirrors evidence withdrawal on LedgerEntry. A retracted finding
    # leaves synthesis but stays here: `status` records what was asserted at the
    # time, so a reader who cannot see `retracted` would read a withdrawn
    # assertion as a live one.
    retracted: bool = False
    retraction_reason: str | None = None
    retracted_at: str | None = None
    retracted_by: str | None = None


def claim_status_evidence_valid(
    status: ClaimStatus,
    *,
    has_active_support: bool,
    has_active_opposition: bool,
) -> bool:
    """Whether a recorded status still matches the claim's active evidence.

    This is presence-based, never count-based: a status is valid when the
    stances it asserts are still present, not when enough of them are. The
    packet verifier re-derives the same rule independently, so a change here
    must be mirrored there or exports will refuse.
    """

    if status is ClaimStatus.PROVISIONALLY_SUPPORTED:
        return has_active_support
    if status is ClaimStatus.CONTESTED:
        return has_active_support and has_active_opposition
    if status is ClaimStatus.UNSUPPORTED:
        return has_active_opposition
    return True
