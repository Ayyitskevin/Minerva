"""Immutable source snapshot domain objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    source_id: str
    snapshot_id: str
    mission_id: str
    sha256: str
    byte_length: int
    encoding: str
    media_type: str
    original_label: str
    url_metadata: str | None
    imported_at: str
    creator_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class SnapshotContent:
    metadata: SourceSnapshot
    content: bytes
