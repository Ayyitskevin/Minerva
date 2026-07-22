"""Deterministic brief and export result objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BriefArtifacts:
    payload: dict[str, Any]
    export_digest: str
    markdown: bytes
    json: bytes
    markdown_sha256: str
    json_sha256: str


@dataclass(frozen=True, slots=True)
class ExportResult:
    export_id: str
    export_digest: str
    markdown_sha256: str
    json_sha256: str
    markdown_path: Path
    json_path: Path
