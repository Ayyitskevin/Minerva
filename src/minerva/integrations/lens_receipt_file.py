"""Safe local-file boundary for captured Lens v1 CLI receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from minerva.core.errors import IntegrityError
from minerva.integrations.lens_receipt import (
    MAX_LENS_RECEIPT_BYTES,
    LensReceiptShapeError,
    LensReceiptTooLargeError,
    parse_lens_receipt,
)
from minerva.integrations.safe_artifact_file import (
    ArtifactReadError,
    ArtifactReadFailureKind,
    read_stable_artifact_bytes,
)
from minerva.lens.models import LensSearchResult


def load_lens_receipt(path: Path) -> LensSearchResult:
    """Read and verify one no-follow regular Lens receipt file."""

    try:
        data = read_stable_artifact_bytes(path, max_bytes=MAX_LENS_RECEIPT_BYTES)
    except ArtifactReadError as error:
        _raise_read_failure(error.kind)

    try:
        return parse_lens_receipt(data)
    except LensReceiptTooLargeError:
        _fail("lens_receipt_too_large", "The Lens receipt exceeds the 8 MiB input limit.")
    except LensReceiptShapeError:
        _fail(
            "lens_receipt_invalid",
            "The Lens receipt failed strict structure or semantic verification.",
        )
    except UnicodeDecodeError:
        _fail("lens_receipt_malformed", "The Lens receipt is not valid UTF-8 JSON.")
    except json.JSONDecodeError:
        _fail("lens_receipt_malformed", "The Lens receipt contains malformed JSON.")
    except ValidationError:
        _fail(
            "lens_receipt_invalid",
            "The Lens receipt failed strict structure or semantic verification.",
        )
    except RecursionError:
        _fail("lens_receipt_malformed", "The Lens receipt JSON nesting is invalid.")
    except ValueError as error:
        message = str(error)
        if message.startswith("duplicate JSON object key:"):
            _fail(
                "lens_receipt_duplicate_field",
                "The Lens receipt contains a duplicate JSON field.",
            )
        if message.startswith("non-finite JSON number is forbidden:"):
            _fail(
                "lens_receipt_nonstandard_number",
                "The Lens receipt contains a non-standard JSON number.",
            )
        if message.startswith("Lens receipt JSON "):
            _fail(
                "lens_receipt_too_complex",
                "The Lens receipt JSON structure exceeds a safety limit.",
            )
        _fail("lens_receipt_malformed", "The Lens receipt contains invalid JSON.")


def _raise_read_failure(kind: ArtifactReadFailureKind) -> Never:
    if kind is ArtifactReadFailureKind.UNSAFE:
        _fail("lens_receipt_input_unsafe", "The Lens receipt input path is unsafe.")
    if kind is ArtifactReadFailureKind.SYMLINK:
        _fail("lens_receipt_input_symlink", "Lens receipt paths may not use symbolic links.")
    if kind is ArtifactReadFailureKind.NOT_FOUND:
        _fail("lens_receipt_input_not_found", "The Lens receipt input was not found.")
    if kind is ArtifactReadFailureKind.UNREADABLE:
        _fail("lens_receipt_input_unreadable", "The Lens receipt could not be read safely.")
    if kind is ArtifactReadFailureKind.CHANGED:
        _fail("lens_receipt_input_changed", "The Lens receipt changed while it was read.")
    _fail("lens_receipt_too_large", "The Lens receipt exceeds the 8 MiB input limit.")


def _fail(code: str, message: str) -> Never:
    raise IntegrityError(code, message)
