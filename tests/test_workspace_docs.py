from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "docs" / "WORKSPACE.md"
VISION = ROOT / "docs" / "VISION.md"
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


def test_workspace_install_does_not_send_seats_into_grok_clone() -> None:
    """Other seats keep their own clones. The install snippet must not cd into Grok's.

    WORKSPACE.md used to show `cd ~/ai-workspace/grok/minerva` as the only
    install path while also telling seats not to scratch-edit another tree.
    """

    workspace = WORKSPACE.read_text(encoding="utf-8")
    assert "cd ~/ai-workspace/grok/minerva" not in workspace


def test_workspace_seat_loop_writes_through_persistent_db() -> None:
    """A non-Grok seat must be able to file a card from this page against the live DB."""

    workspace = WORKSPACE.read_text(encoding="utf-8")
    assert "uv run minerva mission list --db ~/data/minerva/research.db" in workspace
    assert "minerva evidence add --db ~/data/minerva/research.db" in workspace
    assert "minerva-ws" not in workspace


def test_vision_seat_file_loop_is_documented() -> None:
    """VISION.md item 4 is the season checklist.

    'In progress' is a lie once WORKSPACE.md has the live CLI loop.
    """

    vision = VISION.read_text(encoding="utf-8")
    assert "database. **In progress**" not in vision
    assert "database. **Done**" in vision
    assert "wrapper stays machine-local" in vision
