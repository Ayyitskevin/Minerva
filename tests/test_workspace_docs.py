from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "docs" / "WORKSPACE.md"
CONTRIB_UNIT = ROOT / "contrib" / "systemd" / "minerva-serve.service.example"


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


def test_contrib_serve_unit_example_stays_loopback() -> None:
    """The copy-paste unit is the bind operators will run. It must stay loopback.

    `minerva serve` rejects any host other than 127.0.0.1. An example that
    drifted to 0.0.0.0 or dropped the host pin would teach the opposite.
    """

    unit = CONTRIB_UNIT.read_text(encoding="utf-8")
    assert "--host 127.0.0.1 --port 8765" in unit
    assert "0.0.0.0" not in unit
    assert "[::]" not in unit
