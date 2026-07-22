from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minerva.core.db import Database
from minerva.core.types import local_identity
from minerva.evidence.service import EvidenceService
from minerva.synthesis.service import SynthesisService
from minerva.web.app import create_app


@pytest.fixture
def web_client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "web.db"
    Database(database_path).initialize()
    with TestClient(create_app(database_path, testing=True)) as client:
        yield client


def _create_review_data(client: TestClient) -> dict[str, Any]:
    mission = client.post(
        "/api/v1/missions",
        json={
            "title": "Mission <script>window.pwned=true</script>",
            "objective": "Review escaped research statements.",
        },
    ).json()
    question = client.post(
        f"/api/v1/missions/{mission['id']}/questions",
        json={"text": "Does local inference improve privacy?"},
    ).json()
    claim = client.post(
        f"/api/v1/missions/{mission['id']}/claims",
        json={
            "question_id": question["id"],
            "statement": "<img src=x onerror=window.pwned=true> Local inference is preferable.",
            "falsification_criteria": "Opposing capacity evidence outweighs local privacy.",
        },
    ).json()
    source_text = (
        "<script>window.source_pwned=true</script> Local execution avoids upload. "
        "Hosted execution offers greater capacity."
    )
    source = client.post(
        f"/api/v1/missions/{mission['id']}/sources",
        json={
            "content": source_text,
            "original_label": "<unsafe-label>.txt",
            "media_type": "text/plain",
        },
    ).json()

    support_quote = "<script>window.source_pwned=true</script> Local execution avoids upload."
    oppose_quote = "Hosted execution offers greater capacity."
    support_start = len(source_text[: source_text.index(support_quote)].encode())
    oppose_start = len(source_text[: source_text.index(oppose_quote)].encode())
    supporting = client.post(
        f"/api/v1/missions/{mission['id']}/evidence",
        json={
            "claim_id": claim["id"],
            "snapshot_id": source["snapshot_id"],
            "start_byte": support_start,
            "end_byte": support_start + len(support_quote.encode()),
            "quote": support_quote,
            "stance": "supports",
        },
    ).json()
    opposing = client.post(
        f"/api/v1/missions/{mission['id']}/evidence",
        json={
            "claim_id": claim["id"],
            "snapshot_id": source["snapshot_id"],
            "start_byte": oppose_start,
            "end_byte": oppose_start + len(oppose_quote.encode()),
            "quote": oppose_quote,
            "stance": "opposes",
        },
    ).json()
    finding = client.post(
        f"/api/v1/missions/{mission['id']}/findings",
        json={
            "claim_id": claim["id"],
            "statement": "Privacy and capacity evidence remain contested.",
            "statement_kind": "agent_inference",
            "status": "contested",
            "uncertainty": "<svg onload=window.pwned=true> No workload benchmark exists.",
            "evidence_ids": [supporting["id"], opposing["id"]],
        },
    ).json()
    return {
        "mission": mission,
        "question": question,
        "claim": claim,
        "source": source,
        "supporting": supporting,
        "opposing": opposing,
        "finding": finding,
    }


def test_empty_mission_list_and_packaged_styles_render(web_client: TestClient) -> None:
    missions = web_client.get("/missions")
    styles = web_client.get("/static/style.css")

    assert missions.status_code == 200
    assert "No research missions have been recorded." in missions.text
    assert "Review-only local interface" in missions.text
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    assert "--opposes" in styles.text


def test_mission_review_escapes_stored_content_and_shows_uncertainty(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]

    listing = web_client.get("/missions")
    detail = web_client.get(f"/missions/{mission_id}")

    assert listing.status_code == 200
    assert "&lt;script&gt;window.pwned=true&lt;/script&gt;" in listing.text
    assert "<script>window.pwned=true</script>" not in listing.text

    assert detail.status_code == 200
    assert "Research questions" in detail.text
    assert "Claims under evaluation" in detail.text
    assert "Immutable source snapshots" in detail.text
    assert "Findings and uncertainty" in detail.text
    assert "&lt;img src=x onerror=window.pwned=true&gt;" in detail.text
    assert "&lt;unsafe-label&gt;.txt" in detail.text
    assert created["source"]["snapshot_id"] in detail.text
    assert "&lt;svg onload=window.pwned=true&gt;" in detail.text
    assert "<img src=x onerror=window.pwned=true>" not in detail.text
    assert "<svg onload=window.pwned=true>" not in detail.text


def test_claim_ledger_keeps_opposing_evidence_and_exact_citation_visible(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    response = web_client.get(f"/claims/{created['claim']['id']}")

    assert response.status_code == 200
    assert "Evidence ledger" in response.text
    assert "Supporting, opposing, contextual, and inconclusive evidence" in response.text
    assert "SUPPORTS" in response.text
    assert "OPPOSES" in response.text
    assert 'data-stance="supports"' in response.text
    assert 'data-stance="opposes"' in response.text
    assert "Exact UTF-8 byte span" in response.text
    assert created["source"]["sha256"] in response.text
    assert created["source"]["snapshot_id"] in response.text
    assert "&lt;script&gt;window.source_pwned=true&lt;/script&gt;" in response.text
    assert "<script>window.source_pwned=true</script>" not in response.text


def test_brief_preview_is_plain_escaped_text_inside_pre(web_client: TestClient) -> None:
    created = _create_review_data(web_client)
    response = web_client.get(f"/missions/{created['mission']['id']}/brief")

    assert response.status_code == 200
    assert '<pre class="brief-preview">' in response.text
    assert created["source"]["sha256"] in response.text
    assert "OPPOSES" in response.text
    assert "<script>window.source_pwned=true</script>" not in response.text
    assert "&lt;script&gt;" in response.text or "&amp;lt;script&amp;gt;" in response.text


def test_withdrawn_finding_provenance_is_explicit_in_web(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    identity = local_identity(purpose="web provenance regression")
    EvidenceService(web_client.app.state.database).withdraw_evidence(
        evidence_id=created["supporting"]["id"],
        reason="Synthetic review invalidated this citation.",
        identity=identity,
    )

    response = web_client.get(f"/missions/{created['mission']['id']}")
    claim_response = web_client.get(f"/claims/{created['claim']['id']}")

    assert response.status_code == 200
    assert "Provenance invalidated:" in response.text
    assert "recorded status is not current support" in response.text
    assert claim_response.status_code == 200
    assert "Withdrawn by:" in claim_response.text
    assert identity.actor_id in claim_response.text


def test_web_surface_is_review_only(web_client: TestClient) -> None:
    response = web_client.post("/missions", data={"title": "No mutation route"})

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_testserver_is_not_allowed_in_production_configuration(tmp_path: Path) -> None:
    database_path = tmp_path / "production.db"
    Database(database_path).initialize()
    with TestClient(create_app(database_path, testing=False)) as client:
        response = client.get("/missions")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_web_mission_and_claim_views_each_use_one_read_transaction(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create_review_data(web_client)
    database = web_client.app.state.database
    original_read = database.read
    read_count = 0

    @contextmanager
    def counted_read() -> Iterator[sqlite3.Connection]:
        nonlocal read_count
        read_count += 1
        with original_read() as connection:
            yield connection

    monkeypatch.setattr(database, "read", counted_read)

    mission_response = web_client.get(f"/missions/{created['mission']['id']}")
    assert mission_response.status_code == 200
    assert read_count == 1

    read_count = 0
    claim_response = web_client.get(f"/claims/{created['claim']['id']}")
    assert claim_response.status_code == 200
    assert read_count == 1


def test_brief_downloads_are_deterministic_in_memory_and_read_only(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]
    database = web_client.app.state.database
    artifacts = SynthesisService(database).build_brief(mission_id)

    with database.read() as connection:
        audit_count_before = int(
            connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        )
    files_before = {item.name for item in database.path.parent.iterdir()}

    preview = web_client.get(f"/missions/{mission_id}/brief")
    markdown_first = web_client.get(f"/missions/{mission_id}/brief/markdown")
    markdown_second = web_client.get(f"/missions/{mission_id}/brief/markdown")
    json_download = web_client.get(f"/missions/{mission_id}/brief/json")

    assert preview.status_code == 200
    assert f"/missions/{mission_id}/brief/markdown" in preview.text
    assert f"/missions/{mission_id}/brief/json" in preview.text
    assert markdown_first.status_code == 200
    assert markdown_first.content == artifacts.markdown
    assert markdown_second.content == markdown_first.content
    assert markdown_first.headers["content-disposition"] == (
        'attachment; filename="research-brief.md"'
    )
    assert markdown_first.headers["content-type"] == "text/markdown; charset=utf-8"
    assert json_download.status_code == 200
    assert json_download.content == artifacts.json
    assert json_download.headers["content-disposition"] == (
        'attachment; filename="research-brief.json"'
    )
    assert json_download.headers["content-type"] == "application/json"

    with database.read() as connection:
        audit_count_after = int(
            connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        )
    assert audit_count_after == audit_count_before
    assert {item.name for item in database.path.parent.iterdir()} == files_before
