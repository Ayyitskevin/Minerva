"""Shared console output and failure handling for Minerva CLI entry points."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import TextIO

from minerva.core.errors import MinervaError

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_DOMAIN = 3
EXIT_OPERATIONAL = 4


@dataclass(frozen=True, slots=True)
class Outcome:
    payload: object
    exit_code: int = EXIT_OK


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, Path):
        return value.name
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [_jsonable(item) for item in value]
    raise TypeError(f"unsupported console result type: {type(value).__name__}")


def emit_json(payload: object, *, stream: TextIO | None = None) -> None:
    """Write one stable JSON document without reflecting Python representations."""
    destination = stream or sys.stdout
    print(
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=destination,
    )


def emit_error(code: str, message: str) -> None:
    emit_json({"error": {"code": code, "message": message}}, stream=sys.stderr)


def run_safely(action: Callable[[], Outcome]) -> int:
    """Run a console action with stable, presentation-safe exit behavior."""
    try:
        outcome = action()
        emit_json(outcome.payload)
        return outcome.exit_code
    except MinervaError as error:
        emit_error(error.code, error.public_message)
        return EXIT_DOMAIN
    except (OSError, sqlite3.Error):
        emit_error("local_operation_failed", "The local operation failed safely.")
        return EXIT_OPERATIONAL
    except Exception:
        emit_error("internal_error", "Minerva encountered an unexpected local error.")
        return EXIT_INTERNAL
