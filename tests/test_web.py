from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import minerva.research_queue.service as queue_service_module
import minerva.web.app as app_module
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import FindingCandidate, ModelProvider, ProviderSelection
from minerva.assist.service import AssistanceService
from minerva.core.db import Database
from minerva.core.types import local_identity
from minerva.evidence.service import EvidenceService
from minerva.research.models import StatementKind
from minerva.research.service import ResearchService
from minerva.research_queue import MissionResearchQueueBounds, MissionResearchQueueService
from minerva.synthesis.service import SynthesisService
from minerva.web.app import create_app

_COUNT_QUERIES = {
    "audit_events": "SELECT COUNT(*) FROM audit_events",
    "claims": "SELECT COUNT(*) FROM claims",
    "claim_status_events": "SELECT COUNT(*) FROM claim_status_events",
    "finding_citations": "SELECT COUNT(*) FROM finding_citations",
    "findings": "SELECT COUNT(*) FROM findings",
}


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


@pytest.mark.security
def test_interactive_api_docs_stay_disabled(web_client: TestClient) -> None:
    """The README must name the OpenAPI document; Swagger UI is not a surface.

    create_app sets docs_url and redoc_url to None and serves the spec only at
    /api/v1/openapi.json. README used to say OpenAPI was "available" without a
    path, which reads as FastAPI's default /docs.
    """

    readme = " ".join(
        (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8").split()
    )
    docs = web_client.get("/docs")
    redoc = web_client.get("/redoc")
    default_spec = web_client.get("/openapi.json")
    spec = web_client.get("/api/v1/openapi.json")

    assert "The OpenAPI document is at `/api/v1/openapi.json`." in readme
    assert "Interactive `/docs` and `/redoc` are disabled" in readme
    assert "FastAPI's default `/openapi.json` is not served." in readme
    assert docs.status_code == 404
    assert redoc.status_code == 404
    assert default_spec.status_code == 404
    assert spec.status_code == 200
    payload = spec.json()
    assert str(payload["openapi"]).startswith("3.")
    assert payload["info"]["title"] == "Minerva"
    assert "/api/v1/missions" in payload["paths"]
    assert "/docs" not in payload["paths"]
    assert "/redoc" not in payload["paths"]


def test_empty_mission_list_and_packaged_styles_render(web_client: TestClient) -> None:
    missions = web_client.get("/missions")
    styles = web_client.get("/static/style.css")

    assert missions.status_code == 200
    assert "No research missions have been recorded." in missions.text
    assert "Controlled local research interface" in missions.text
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


def test_retracted_finding_is_marked_retracted_in_web(
    web_client: TestClient,
) -> None:
    """The human review surface must show that a finding is no longer asserted."""

    created = _create_review_data(web_client)
    identity = local_identity(purpose="web retraction regression")
    database = web_client.app.state.database
    research = ResearchService(database)
    with database.read() as connection:
        finding_id = research.list_findings(created["mission"]["id"], connection=connection)[0].id
    before = web_client.get(f"/missions/{created['mission']['id']}")
    research.retract_finding(
        finding_id=finding_id,
        reason="Synthetic review withdrew this assertion.",
        identity=identity,
    )

    response = web_client.get(f"/missions/{created['mission']['id']}")

    assert before.status_code == 200
    assert "RETRACTED" not in before.text
    assert response.status_code == 200
    assert "RETRACTED" in response.text
    assert "no longer asserted" in response.text
    assert "Synthetic review withdrew this assertion." in response.text


def test_mission_list_says_when_it_is_showing_only_part_of_the_set(
    web_client: TestClient,
) -> None:
    """A capped list must never be presented as the whole set.

    The route rendered exactly 100 of any number of missions with no count,
    banner, or pagination affordance, while the REST route on the same data
    returned a continuation cursor. A reviewer had no way to know newer missions
    existed and were being hidden.
    """

    research = ResearchService(web_client.app.state.database)
    identity = local_identity(purpose="web pagination regression")
    for index in range(app_module.WEB_MISSION_PAGE_SIZE + 5):
        research.create_mission(
            title=f"Mission {index:03d}",
            objective="Objective recorded for the pagination regression.",
            identity=identity,
        )

    response = web_client.get("/missions")

    assert response.status_code == 200
    assert f"Showing the first {app_module.WEB_MISSION_PAGE_SIZE} missions" in response.text
    assert "More exist than this page displays" in response.text
    assert "minerva mission list" in response.text
    assert response.text.count('<li class="card">') == app_module.WEB_MISSION_PAGE_SIZE


def test_mission_list_does_not_claim_truncation_when_it_shows_everything(
    web_client: TestClient,
) -> None:
    """The exact-count signal must not over-warn on a full-but-complete page.

    A `len(missions) == limit` heuristic would claim more missions existed
    whenever the count landed exactly on the page size, so the route asks for one
    extra row instead and reports what it actually found.
    """

    research = ResearchService(web_client.app.state.database)
    identity = local_identity(purpose="web pagination boundary regression")
    for index in range(app_module.WEB_MISSION_PAGE_SIZE):
        research.create_mission(
            title=f"Mission {index:03d}",
            objective="Objective recorded for the pagination boundary regression.",
            identity=identity,
        )

    response = web_client.get("/missions")

    assert response.status_code == 200
    assert f"Showing all {app_module.WEB_MISSION_PAGE_SIZE} recorded missions" in response.text
    assert "More exist than this page displays" not in response.text
    assert response.text.count('<li class="card">') == app_module.WEB_MISSION_PAGE_SIZE


def test_undefined_html_mutation_routes_remain_closed(web_client: TestClient) -> None:
    response = web_client.post("/missions", data={"title": "No mutation route"})

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def _cockpit_write_context(
    client: TestClient,
    mission_id: str,
) -> tuple[str, int, str]:
    response = client.get(f"/missions/{mission_id}")
    token = client.cookies.get("minerva_csrf")
    match = re.search(
        r'name="expected_mission_audit_sequence" value="([0-9]+)"',
        response.text,
    )

    assert response.status_code == 200
    assert token is not None
    assert f'name="csrf_token" value="{token}"' in response.text
    assert match is not None
    return token, int(match.group(1)), response.text


def _table_counts(client: TestClient, *tables: str) -> tuple[int, ...]:
    with client.app.state.database.read() as connection:
        return tuple(
            int(connection.execute(_COUNT_QUERIES[table]).fetchone()[0]) for table in tables
        )


def test_cockpit_is_action_first_and_issues_hardened_csrf_cookie(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    token, _, document = _cockpit_write_context(web_client, created["mission"]["id"])

    assert document.index('id="action-cockpit"') < document.index('id="record-research"')
    assert document.index('id="record-research"') < document.index("Research questions")
    assert "Controlled writes · shared audited service layer" in document
    assert "not generic CRUD" in document
    assert token
    response = web_client.get(f"/missions/{created['mission']['id']}")
    assert "set-cookie" not in response.headers


@pytest.mark.security
def test_cockpit_claim_create_requires_origin_csrf_and_exact_form_contract(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]
    token, sequence, _ = _cockpit_write_context(web_client, mission_id)
    path = f"/missions/{mission_id}/claims"
    valid = {
        "csrf_token": token,
        "expected_mission_audit_sequence": str(sequence),
        "question_id": created["question"]["id"],
        "statement": "A controlled browser claim.",
        "falsification_criteria": "A recorded counterexample would falsify it.",
    }
    before = _table_counts(web_client, "claims", "claim_status_events", "audit_events")

    missing_origin = web_client.post(path, data=valid, follow_redirects=False)
    missing_csrf = web_client.post(
        path,
        data={key: value for key, value in valid.items() if key != "csrf_token"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    tampered = web_client.post(
        path,
        data={**valid, "csrf_token": token[:-1] + ("A" if token[-1] != "A" else "B")},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    unknown_field = web_client.post(
        path,
        data={**valid, "surprise": "not allowed"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    wrong_media = web_client.post(
        path,
        content="{}",
        headers={"Origin": "http://testserver", "Content-Type": "application/json"},
        follow_redirects=False,
    )

    assert (missing_origin.status_code, missing_origin.json()["error"]["code"]) == (
        403,
        "form_origin_required",
    )
    assert (missing_csrf.status_code, missing_csrf.json()["error"]["code"]) == (
        403,
        "csrf_invalid",
    )
    assert (tampered.status_code, tampered.json()["error"]["code"]) == (403, "csrf_invalid")
    assert (unknown_field.status_code, unknown_field.json()["error"]["code"]) == (
        422,
        "form_contract_invalid",
    )
    assert (wrong_media.status_code, wrong_media.json()["error"]["code"]) == (
        415,
        "form_content_type_invalid",
    )
    assert _table_counts(web_client, "claims", "claim_status_events", "audit_events") == before


def test_cockpit_claim_create_is_audited_and_stale_replay_is_refused(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]
    token, sequence, _ = _cockpit_write_context(web_client, mission_id)
    payload = {
        "csrf_token": token,
        "expected_mission_audit_sequence": str(sequence),
        "question_id": created["question"]["id"],
        "statement": "A controlled browser claim.",
        "falsification_criteria": "A recorded counterexample would falsify it.",
    }
    before = _table_counts(web_client, "claims", "claim_status_events", "audit_events")

    created_response = web_client.post(
        f"/missions/{mission_id}/claims",
        data=payload,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    after_create = _table_counts(web_client, "claims", "claim_status_events", "audit_events")
    replay = web_client.post(
        f"/missions/{mission_id}/claims",
        data=payload,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )

    assert created_response.status_code == 303
    assert created_response.headers["location"].endswith(f"/missions/{mission_id}")
    assert after_create == (
        before[0] + 1,
        before[1] + 1,
        before[2] + 2,
    )
    assert (replay.status_code, replay.json()["error"]["code"]) == (
        409,
        "mission_version_conflict",
    )
    assert (
        _table_counts(web_client, "claims", "claim_status_events", "audit_events") == after_create
    )


def test_cockpit_status_and_finding_writes_are_fresh_scoped_and_audited(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]
    claim_id = created["claim"]["id"]
    token, _, _ = _cockpit_write_context(web_client, mission_id)
    headers = {"Origin": "http://testserver"}

    status_payload = {
        "csrf_token": token,
        "expected_version": "1",
        "status": "contested",
        "reason": "Supporting and opposing evidence are both active.",
    }
    status_before = _table_counts(web_client, "claim_status_events", "audit_events")
    changed = web_client.post(
        f"/missions/{mission_id}/claims/{claim_id}/status",
        data=status_payload,
        headers=headers,
        follow_redirects=False,
    )
    status_after = _table_counts(web_client, "claim_status_events", "audit_events")
    stale_status = web_client.post(
        f"/missions/{mission_id}/claims/{claim_id}/status",
        data=status_payload,
        headers=headers,
        follow_redirects=False,
    )

    assert changed.status_code == 303
    assert status_after == (status_before[0] + 1, status_before[1] + 2)
    assert (stale_status.status_code, stale_status.json()["error"]["code"]) == (
        409,
        "claim_version_conflict",
    )
    assert _table_counts(web_client, "claim_status_events", "audit_events") == status_after

    # The status decision advanced the mission audit sequence, so reload before
    # recording a distinct finding command.
    token, sequence, _ = _cockpit_write_context(web_client, mission_id)
    finding_payload = {
        "csrf_token": token,
        "expected_mission_audit_sequence": str(sequence),
        "claim_id": claim_id,
        "statement_kind": "assumption",
        "status": "inconclusive",
        "statement": "The workload remains representative.",
        "uncertainty": "Representativeness is not established by the sources.",
        "evidence_ids": "",
    }
    finding_before = _table_counts(web_client, "findings", "finding_citations", "audit_events")
    finding = web_client.post(
        f"/missions/{mission_id}/findings",
        data=finding_payload,
        headers=headers,
        follow_redirects=False,
    )
    finding_after = _table_counts(web_client, "findings", "finding_citations", "audit_events")
    replay = web_client.post(
        f"/missions/{mission_id}/findings",
        data=finding_payload,
        headers=headers,
        follow_redirects=False,
    )

    assert finding.status_code == 303
    assert finding_after == (
        finding_before[0] + 1,
        finding_before[1],
        finding_before[2] + 2,
    )
    assert (replay.status_code, replay.json()["error"]["code"]) == (
        409,
        "mission_version_conflict",
    )
    assert (
        _table_counts(web_client, "findings", "finding_citations", "audit_events") == finding_after
    )


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


def _adopt_review_inference(
    web_client: TestClient,
    created: dict[str, Any],
    *,
    statement: str,
    uncertainty: str = "The evidence does not establish generality.",
) -> Any:
    database = web_client.app.state.database
    preview = AssistanceService(database).preview_finding_candidates(
        claim_id=created["claim"]["id"],
        selection=ProviderSelection(ModelProvider.OPENAI, "test-model-1", "test"),
        max_candidates=2,
        max_output_tokens=512,
    )
    return AdoptionService(database).adopt_inference(
        preview=preview,
        expected_request_sha256=preview.request_sha256,
        candidate_index=0,
        candidate=FindingCandidate(
            statement=statement,
            statement_kind=StatementKind.AGENT_INFERENCE,
            uncertainty=uncertainty,
            evidence_ids=(created["supporting"]["id"],),
        ),
        response_sha256="0" * 64,
        identity=local_identity(purpose="web inference adoption"),
    )


def test_mission_review_renders_adopted_inferences_as_escaped_text(
    web_client: TestClient,
) -> None:
    """Rendered inference text is untrusted model output: inert, labeled, escaped."""

    created = _create_review_data(web_client)
    payload = "<script>window.inference_pwned=true</script> Adopted model draft."
    inference = _adopt_review_inference(web_client, created, statement=payload)

    detail = web_client.get(f"/missions/{created['mission']['id']}")
    claim_detail = web_client.get(f"/claims/{created['claim']['id']}")

    assert detail.status_code == 200
    assert "Agent inferences (model-drafted, human-adopted)" in detail.text
    assert "agent inference · openai / test-model-1" in detail.text
    assert "never evidence or a human finding" in detail.text
    assert inference.id in detail.text
    assert "&lt;script&gt;window.inference_pwned=true&lt;/script&gt;" in detail.text
    assert "<script>window.inference_pwned=true</script>" not in detail.text

    assert claim_detail.status_code == 200
    assert "Agent inferences (model-drafted, human-adopted)" in claim_detail.text
    assert inference.id in claim_detail.text
    assert "<script>window.inference_pwned=true</script>" not in claim_detail.text


def test_retracted_inference_is_marked_retracted_in_web(
    web_client: TestClient,
) -> None:
    """A retracted adoption must never read as a live one on the review surface."""

    created = _create_review_data(web_client)
    inference = _adopt_review_inference(
        web_client,
        created,
        statement="A model draft later withdrawn from assertion.",
    )
    before = web_client.get(f"/missions/{created['mission']['id']}")
    identity = local_identity(purpose="web inference retraction")
    AdoptionService(web_client.app.state.database).retract_inference(
        inference_id=inference.id,
        reason="Synthetic review withdrew this adoption.",
        identity=identity,
    )

    response = web_client.get(f"/missions/{created['mission']['id']}")

    assert before.status_code == 200
    assert "RETRACTED" not in before.text
    assert response.status_code == 200
    assert "RETRACTED" in response.text
    assert "no longer asserted" in response.text
    assert "Synthetic review withdrew this adoption." in response.text
    assert identity.actor_id in response.text


def test_structural_workbench_renders_existing_receipts_without_mutation(
    web_client: TestClient,
) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]
    claim_id = created["claim"]["id"]
    database = web_client.app.state.database

    with database.read() as connection:
        audit_count_before = int(
            connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        )
    files_before = {item.name for item in database.path.parent.iterdir()}

    mission = web_client.get(f"/missions/{mission_id}")
    claim = web_client.get(f"/claims/{claim_id}")
    queue = web_client.get(f"/missions/{mission_id}/queue")
    review = web_client.get(f"/missions/{mission_id}/claims/{claim_id}/review")
    lineage = web_client.get(f"/missions/{mission_id}/claims/{claim_id}/lineage")

    assert mission.status_code == claim.status_code == 200
    assert f"/missions/{mission_id}/queue" in mission.text
    assert f"/missions/{mission_id}/claims/{claim_id}/review" in claim.text
    assert f"/missions/{mission_id}/claims/{claim_id}/lineage" in claim.text

    assert queue.status_code == review.status_code == lineage.status_code == 200
    assert "structural cues, not tasks" in queue.text
    assert "active_stance_contradiction" in queue.text
    assert created["claim"]["statement"].replace("<", "&lt;").replace(">", "&gt;") in queue.text
    assert created["claim"]["statement"] not in queue.text
    assert "Cues describe recorded structure" in review.text
    assert "active_stance_contradiction" in review.text
    assert created["supporting"]["id"] in review.text
    assert created["opposing"]["id"] in review.text
    assert "Nodes and edges are recorded provenance" in lineage.text
    assert "claim_has_evidence" in lineage.text
    assert created["supporting"]["id"] in lineage.text
    assert created["opposing"]["id"] in lineage.text

    with database.read() as connection:
        audit_count_after = int(
            connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        )
    assert audit_count_after == audit_count_before
    assert {item.name for item in database.path.parent.iterdir()} == files_before


def test_structural_workbench_routes_remain_get_only(web_client: TestClient) -> None:
    created = _create_review_data(web_client)
    mission_id = created["mission"]["id"]
    claim_id = created["claim"]["id"]

    paths = (
        f"/missions/{mission_id}/queue",
        f"/missions/{mission_id}/claims/{claim_id}/review",
        f"/missions/{mission_id}/claims/{claim_id}/lineage",
    )
    for path in paths:
        response = web_client.post(path)
        assert response.status_code == 405
        assert response.json()["error"]["code"] == "method_not_allowed"


def test_mission_cockpit_enforces_queue_vm_limit_on_shared_snapshot(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create_review_data(web_client)
    original = MissionResearchQueueService.build_queue
    monkeypatch.setattr(queue_service_module, "_QUERY_PROGRESS_GRANULARITY", 1)
    monkeypatch.setattr(queue_service_module, "_MIN_SQLITE_VM_STEPS", 1)

    def bounded_build(
        self: MissionResearchQueueService,
        *,
        mission_id: str,
        bounds: MissionResearchQueueBounds | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> Any:
        del bounds
        return original(
            self,
            mission_id=mission_id,
            bounds=MissionResearchQueueBounds(max_sqlite_vm_steps=1),
            connection=connection,
        )

    monkeypatch.setattr(MissionResearchQueueService, "build_queue", bounded_build)

    response = web_client.get(f"/missions/{created['mission']['id']}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "mission_research_queue_work_limit"
