"""Small, dependency-free shared types."""

from __future__ import annotations

import getpass
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from minerva.core.errors import IntegrityError

Clock = Callable[[], str]
IdFactory = Callable[[str], str]


class ActorKind(StrEnum):
    OS_USER = "os_user"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class IdentityContext:
    actor_id: str
    actor_kind: ActorKind
    run_id: str
    purpose: str


_SAFE_ACTOR = re.compile(r"[^a-zA-Z0-9_.:@+-]")


def local_identity(*, purpose: str, run_id: str | None = None) -> IdentityContext:
    """Create honest local attribution without accepting a remote actor claim."""

    username = _SAFE_ACTOR.sub("_", getpass.getuser())[:100] or "unknown"
    return IdentityContext(
        actor_id=f"os-user:{username}",
        actor_kind=ActorKind.OS_USER,
        run_id=run_id or new_id("run"),
        purpose=purpose[:200],
    )


def system_identity(*, purpose: str, run_id: str | None = None) -> IdentityContext:
    return IdentityContext(
        actor_id="system:minerva",
        actor_kind=ActorKind.SYSTEM,
        run_id=run_id or new_id("run"),
        purpose=purpose[:200],
    )


def new_id(prefix: str) -> str:
    if not re.fullmatch(r"[a-z]{3}", prefix):
        raise ValueError("identifier prefixes must contain exactly three lowercase letters")
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_text(
    value: str,
    *,
    field: str,
    maximum: int,
    allow_newlines: bool = True,
) -> str:
    normalized = value.strip()
    if not normalized:
        raise IntegrityError(f"{field}_required", f"{field.replace('_', ' ').title()} is required.")
    if len(normalized) > maximum:
        raise IntegrityError(
            f"{field}_too_long", f"{field.replace('_', ' ').title()} exceeds its size limit."
        )
    if "\x00" in normalized:
        raise IntegrityError(f"{field}_invalid", f"{field.replace('_', ' ').title()} is invalid.")
    if not allow_newlines and ("\n" in normalized or "\r" in normalized):
        raise IntegrityError(
            f"{field}_invalid", f"{field.replace('_', ' ').title()} must be one line."
        )
    return normalized
