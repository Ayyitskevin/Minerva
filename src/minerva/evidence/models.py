"""Evidence card and exact-citation domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    CONTEXT = "context"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class EvidenceCard:
    id: str
    mission_id: str
    claim_id: str
    snapshot_id: str
    snapshot_sha256: str
    start_byte: int
    end_byte: int
    quote: str
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    creator_id: str
    run_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    evidence: EvidenceCard
    citation_id: str
    snapshot_sha256: str
    source_label: str
    withdrawn: bool
    withdrawal_reason: str | None
    withdrawn_at: str | None
    withdrawn_by: str | None
