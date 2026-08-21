from __future__ import annotations

from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1] / "docs" / "WORKSPACE.md"


def test_workspace_nightly_backup_example_cannot_collide() -> None:
    """Nightly backup docs must not recommend a path backup would refuse to reuse.

    `minerva backup` refuses to overwrite an existing file. WORKSPACE.md used to
    show `--output ~/data/minerva/backups/research.db` as the nightly command,
    which can succeed once and then fail forever. The dated example is the
    contract; this fails if the colliding filename returns.
    """

    workspace = WORKSPACE.read_text(encoding="utf-8")

    assert "--output ~/data/minerva/backups/research.db" not in workspace
    assert "--output ~/data/minerva/backups/research-$(date -u +%Y%m%dT%H%M%SZ).db" in workspace
