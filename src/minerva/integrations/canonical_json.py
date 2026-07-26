"""One canonical-JSON and strict-parse implementation for the wire contracts.

`minerva.research-packet.v2` and `minerva.research-request.v1` both pin exact
canonical bytes and both parse untrusted files, and each carried its own copy of
these four helpers. The copies were byte-identical apart from one noun, which is
exactly the shape that drifts silently: a fix applied to one reader and not the
other changes what the two contracts accept without either looking wrong. F-SEC-1
and F2-INTEGRATIONS-1 were both cases of the two readers having diverged.

Nothing here is a general-purpose JSON utility. Other modules in the tree also
call `json.dumps(..., sort_keys=True)` and they are deliberately *not* routed
through this module: `api/routes.py` builds ASCII-only cursor tokens,
`cli/_common.py` writes to a stream after coercing values, and `core/audit.py`,
`core/doctor.py`, and `sources/integrity.py` serialize one field for comparison.
Those differ in ways that matter, and collapsing them would be consolidation for
its own sake.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

MAX_JSON_DEPTH = 64
MAX_JSON_OBJECT_FIELDS = 64


def canonical_json_bytes(value: object) -> bytes:
    """Serialize to the one byte form both contracts hash and compare.

    Every argument is load-bearing: `sort_keys` and `separators` make the bytes a
    function of the value alone, `allow_nan=False` keeps non-standard tokens out
    of a document another implementation must be able to read, and
    `ensure_ascii=False` means the digest covers the text rather than an escaped
    rendering of it.
    """

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def strict_json_loads(text: str) -> object:
    """Parse untrusted JSON, refusing what `json.loads` would quietly accept.

    A duplicate key would otherwise let the last occurrence win, so two readers
    could disagree about the same bytes; `Infinity` and `NaN` are not JSON and
    would not survive a round trip through another implementation.
    """

    def reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_non_finite(token: str) -> object:
        raise ValueError(f"non-finite JSON number is forbidden: {token}")

    return cast(
        object,
        json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        ),
    )


def require_bounded_json_shape(value: object, *, subject: str, depth: int = 0) -> None:
    """Bound nesting and object width before a document reaches strict DTOs.

    `subject` is the noun each contract uses in its message -- "research packet"
    or "research request". It is a parameter rather than a constant because both
    file readers classify on `str(error).startswith(f"{subject} JSON ")` to
    produce `packet_too_complex` / `request_too_complex`. Changing the wording
    here changes which error code an oversized document gets, so the two must be
    edited together.
    """

    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{subject} JSON nesting exceeds the safety limit")
    if isinstance(value, dict):
        if len(value) > MAX_JSON_OBJECT_FIELDS:
            raise ValueError(f"{subject} JSON object exceeds the field safety limit")
        for child in value.values():
            require_bounded_json_shape(child, subject=subject, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            require_bounded_json_shape(child, subject=subject, depth=depth + 1)
