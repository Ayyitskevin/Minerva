"""Strict storage-independent parser for captured Lens v1 CLI receipts."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from pydantic import BaseModel, ConfigDict

from minerva.integrations.canonical_json import (
    require_bounded_json_shape,
    strict_json_loads,
)
from minerva.lens.models import (
    LensBounds,
    LensCandidateContext,
    LensCorpusFilter,
    LensOmissions,
    LensScore,
    LensSearchResult,
    LensSemanticBoundary,
    LensSnapshotIdentity,
)
from minerva.lens.receipt import verify_lens_receipt

MAX_LENS_RECEIPT_BYTES = 8_388_608


class LensReceiptTooLargeError(ValueError):
    """The captured Lens envelope exceeds its local input limit."""


class LensReceiptShapeError(ValueError):
    """The captured envelope omits or adds a canonical Lens field."""


class _LensReceiptEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    lens: LensSearchResult


def parse_lens_receipt(data: bytes | str) -> LensSearchResult:
    """Strictly parse and internally verify one captured Lens CLI envelope."""

    encoded = data if isinstance(data, bytes) else data.encode("utf-8", errors="strict")
    _require_receipt_size(encoded)
    text = encoded.decode("utf-8", errors="strict")
    parsed = strict_json_loads(text)
    require_bounded_json_shape(parsed, subject="Lens receipt")
    _require_sequence_bounds(parsed)
    _require_exact_field_sets(parsed)
    envelope = _LensReceiptEnvelope.model_validate_json(text, strict=True)
    return verify_lens_receipt(envelope.lens)


def _require_receipt_size(data: bytes) -> None:
    if len(data) > MAX_LENS_RECEIPT_BYTES:
        raise LensReceiptTooLargeError("Lens receipt exceeds the local input limit")


def _require_sequence_bounds(parsed: object) -> None:
    """Refuse producer-impossible fanout before strict DTO construction."""

    if not isinstance(parsed, dict):
        return
    receipt = parsed.get("lens")
    if not isinstance(receipt, dict):
        return
    _bounded_list(receipt.get("query_terms"), maximum=32)
    _bounded_list(receipt.get("stable_tie_break"), maximum=3)
    _bounded_list(receipt.get("searched_snapshots"), maximum=200)
    _bounded_list(receipt.get("candidates"), maximum=100)
    corpus_filter = receipt.get("corpus_filter")
    if isinstance(corpus_filter, dict):
        _bounded_list(corpus_filter.get("source_ids"), maximum=200)
        _bounded_list(corpus_filter.get("snapshot_ids"), maximum=200)


def _bounded_list(value: object, *, maximum: int) -> None:
    if isinstance(value, list) and len(value) > maximum:
        raise ValueError("Lens receipt JSON sequence exceeds the safety limit")


def _require_exact_field_sets(parsed: object) -> None:
    """Prevent DTO defaults from repairing an incomplete captured wire object."""

    if not isinstance(parsed, dict):
        return
    _require_fields(parsed, ("lens",))
    receipt = parsed.get("lens")
    if not isinstance(receipt, dict):
        return
    _require_dataclass_fields(receipt, LensSearchResult)
    _require_nested_dataclass(receipt.get("bounds"), LensBounds)
    _require_nested_dataclass(receipt.get("corpus_filter"), LensCorpusFilter)
    _require_nested_dataclass(receipt.get("omissions"), LensOmissions)
    _require_nested_dataclass(receipt.get("semantic_boundary"), LensSemanticBoundary)
    _require_dataclass_sequence(receipt.get("searched_snapshots"), LensSnapshotIdentity)
    candidates = receipt.get("candidates")
    _require_dataclass_sequence(candidates, LensCandidateContext)
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                _require_nested_dataclass(candidate.get("score"), LensScore)


def _require_nested_dataclass(value: object, model: type[Any]) -> None:
    if isinstance(value, dict):
        _require_dataclass_fields(value, model)


def _require_dataclass_sequence(value: object, model: type[Any]) -> None:
    if isinstance(value, list):
        for item in value:
            _require_nested_dataclass(item, model)


def _require_dataclass_fields(value: dict[str, object], model: type[Any]) -> None:
    _require_fields(value, tuple(field.name for field in fields(model)))


def _require_fields(value: dict[str, object], expected: tuple[str, ...]) -> None:
    if set(value) != set(expected):
        raise LensReceiptShapeError("Lens receipt field set is not canonical")
