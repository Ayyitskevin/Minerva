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
