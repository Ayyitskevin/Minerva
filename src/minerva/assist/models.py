"""Provider-neutral assistance contracts with no SDK response types."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, SupportsIndex

from pydantic import BaseModel, ConfigDict, Field

from minerva.core.errors import IntegrityError, SecurityBoundaryError
from minerva.research.models import StatementKind
from minerva.sources.files import scan_secret_patterns

_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class ModelProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

    @property
    def credential_environment_variable(self) -> str:
        return {
            ModelProvider.OPENAI: "OPENAI_API_KEY",
            ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
        }[self]

    @property
    def destination(self) -> str:
        return {
            ModelProvider.OPENAI: "https://api.openai.com/v1/responses",
            ModelProvider.ANTHROPIC: "https://api.anthropic.com/v1/messages",
        }[self]


class ProviderOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"


class ProviderCredential:
    """A deliberately non-serializable, redacted in-memory credential."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "ProviderCredential(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __copy__(self) -> ProviderCredential:
        raise TypeError("provider credentials cannot be copied")

    def __deepcopy__(self, _memo: object) -> ProviderCredential:
        raise TypeError("provider credentials cannot be copied")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> str | tuple[Any, ...]:
        raise TypeError("provider credentials cannot be serialized")


class CandidateDraft(BaseModel):
    """Strict provider output before local citation revalidation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    statement: str = Field(min_length=1, max_length=4_000)
    uncertainty: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)


class CandidateDraftBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidateDraft] = Field(max_length=3)


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: ModelProvider
    model: str
    source: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    system_prompt: str
    context_json: str
    max_candidates: int
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    outcome: ProviderOutcome
    returned_model: str
    response_id: str | None
    candidates: tuple[CandidateDraft, ...]
    usage: ProviderUsage


@dataclass(frozen=True, slots=True)
class CandidatePreview:
    request_schema_version: str
    context_schema_version: str
    system_prompt_version: str
    provider: ModelProvider
    model: str
    selection_source: str
    destination: str
    mission_id: str
    claim_id: str
    claim_version: int
    evidence_ids: tuple[str, ...]
    excluded_withdrawn_evidence_ids: tuple[str, ...]
    context_bytes: int
    context_sha256: str
    system_prompt_sha256: str
    request_sha256: str
    max_candidates: int
    max_output_tokens: int
    context_json: str
    external_data_notice: str


@dataclass(frozen=True, slots=True)
class FindingCandidate:
    statement: str
    statement_kind: StatementKind
    uncertainty: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateBundle:
    schema_version: str
    invocation_id: str
    outcome: ProviderOutcome
    provider: ModelProvider
    requested_model: str
    returned_model: str
    response_id: str | None
    request_sha256: str
    context_sha256: str
    response_sha256: str
    candidates: tuple[FindingCandidate, ...]
    usage: ProviderUsage
    candidate_only: bool
    disclaimer: str


def validate_model_id(value: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError("assistant_model_invalid", "The provider model identifier is invalid.")
    candidate = value.strip()
    if candidate != value or _MODEL_ID.fullmatch(candidate) is None:
        raise IntegrityError("assistant_model_invalid", "The provider model identifier is invalid.")
    if scan_secret_patterns(candidate) is not None:
        raise SecurityBoundaryError(
            "assistant_model_secret_detected",
            "The provider model identifier matches a blocked secret pattern.",
        )
    return candidate


def candidate_output_schema(max_candidates: int) -> dict[str, object]:
    """Build the shared provider-safe structured-output schema.

    Provider structured-output subsets omit several Pydantic constraints. Minerva
    communicates the requested count here and in the previewed task, then enforces
    every string, list, and candidate bound again on the parsed response.
    """

    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int):
        raise ValueError("candidate output limit is invalid")
    if not 1 <= max_candidates <= 3:
        raise ValueError("candidate output limit is invalid")
    candidate = {
        "additionalProperties": False,
        "properties": {
            "evidence_ids": {
                "description": "Active citation IDs from the supplied context only.",
                "items": {"type": "string"},
                "type": "array",
            },
            "statement": {"type": "string"},
            "uncertainty": {"type": "string"},
        },
        "required": ["statement", "uncertainty", "evidence_ids"],
        "type": "object",
    }
    return {
        "additionalProperties": False,
        "properties": {
            "candidates": {
                "description": f"Return at most {max_candidates} candidates.",
                "items": candidate,
                "type": "array",
            }
        },
        "required": ["candidates"],
        "type": "object",
    }
