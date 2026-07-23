from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minerva.core.db import Database
from minerva.core.types import local_identity
from minerva.evidence.service import EvidenceService
from minerva.web.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "minerva.db"
    Database(database_path).initialize()
    with TestClient(create_app(database_path, testing=True)) as test_client:
        yield test_client


def _json(response: Any) -> dict[str, Any]:
    document = response.json()
    assert isinstance(document, dict)
    return document


def _create_vertical_slice(client: TestClient) -> dict[str, Any]:
    mission_response = client.post(
        "/api/v1/missions",
        json={
            "title": "Compare local inference strategies",
            "objective": "Compare privacy and capacity trade-offs without manufacturing certainty.",
        },
    )
    assert mission_response.status_code == 201
    mission = _json(mission_response)

    question_response = client.post(
        f"/api/v1/missions/{mission['id']}/questions",
        json={"text": "Which inference strategy best protects private research?"},
    )
    assert question_response.status_code == 201
    question = _json(question_response)

    claim_response = client.post(
        f"/api/v1/missions/{mission['id']}/claims",
        json={
            "question_id": question["id"],
            "statement": "Local inference is preferable for private research.",
            "falsification_criteria": (
                "Opposing evidence shows hosted inference protects the same data more reliably."
            ),
        },
    )
    assert claim_response.status_code == 201
    claim = _json(claim_response)
    assert claim_response.headers["etag"] == claim["etag"]

    source_text = (
        "  Local inference keeps source material on the operator's machine. "
        "Hosted inference may provide substantially greater model capacity.\n"
    )
    source_response = client.post(
        f"/api/v1/missions/{mission['id']}/sources",
        json={
            "content": source_text,
            "original_label": "synthetic-strategies.txt",
            "media_type": "text/plain",
            "url_metadata": "https://example.test/metadata-only",
        },
    )
    assert source_response.status_code == 201
    source = _json(source_response)

    supporting_quote = "  Local inference keeps source material on the operator's machine."
    opposing_quote = "Hosted inference may provide substantially greater model capacity.\n"
    support_start = len(source_text[: source_text.index(supporting_quote)].encode())
    support_end = support_start + len(supporting_quote.encode())
    oppose_start = len(source_text[: source_text.index(opposing_quote)].encode())
    oppose_end = oppose_start + len(opposing_quote.encode())

    supporting_response = client.post(
        f"/api/v1/missions/{mission['id']}/evidence",
        json={
            "claim_id": claim["id"],
            "snapshot_id": source["snapshot_id"],
            "start_byte": support_start,
            "end_byte": support_end,
            "quote": supporting_quote,
            "stance": "supports",
        },
    )
    assert supporting_response.status_code == 201
    supporting = _json(supporting_response)

    opposing_response = client.post(
        f"/api/v1/missions/{mission['id']}/evidence",
        json={
            "claim_id": claim["id"],
            "snapshot_id": source["snapshot_id"],
            "start_byte": oppose_start,
            "end_byte": oppose_end,
            "quote": opposing_quote,
            "stance": "opposes",
        },
    )
    assert opposing_response.status_code == 201
    opposing = _json(opposing_response)

    finding_response = client.post(
        f"/api/v1/missions/{mission['id']}/findings",
        json={
            "claim_id": claim["id"],
            "statement": "Local privacy benefits coexist with a capacity trade-off.",
            "statement_kind": "agent_inference",
            "status": "contested",
            "uncertainty": "The synthetic sources do not measure workload-specific quality.",
            "evidence_ids": [supporting["id"], opposing["id"]],
        },
    )
    assert finding_response.status_code == 201
    finding = _json(finding_response)

    return {
        "mission": mission,
        "question": question,
        "claim": claim,
        "source": source,
        "source_text": source_text,
        "supporting": supporting,
        "opposing": opposing,
        "finding": finding,
    }


def test_health_and_readiness_are_truthful(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.db"
    with TestClient(create_app(missing_path, testing=True)) as unready:
        health = unready.get("/healthz")
        readiness = unready.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "not_ready"
    assert str(tmp_path) not in readiness.text

    Database(missing_path).initialize()
    with TestClient(create_app(missing_path, testing=True)) as ready:
        ready_response = ready.get("/readyz")

    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ready"
    assert all(item["ok"] for item in ready_response.json()["checks"])


def test_readiness_fails_safely_for_malformed_migration_values(tmp_path: Path) -> None:
    path = tmp_path / "malformed-migration.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE schema_migrations(version TEXT, name TEXT, checksum TEXT)")
        connection.execute(
            "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
            ("not-an-integer", "0001_research_core.sql", "0" * 64),
        )
        connection.commit()

    with TestClient(create_app(path, testing=True)) as malformed:
        response = malformed.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    checks = response.json()["checks"]
    assert any(item["name"] == "schema" and item["ok"] is False for item in checks)
    assert "not-an-integer" not in response.text


def test_capability_manifest_is_versioned_and_truthful(client: TestClient) -> None:
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    document = response.json()
    assert document == {
        "schema_version": "minerva.capabilities.v2",
        "api_version": "v1",
        "local_only": False,
        "loopback_only": True,
        "external_egress": "disabled_by_default_cli_only",
        "supported_external_providers": ["openai", "anthropic"],
        "identity_boundary": "local_os_user",
        "citation_scheme": "utf8-byte-offset-v1",
        "brief_schema_version": "minerva.research-brief.v2",
        "research_request_schema_version": "minerva.research-request.v1",
        "capabilities": [
            "mission.create",
            "question.create",
            "claim.create",
            "claim.status.append",
            "source.utf8_bytes.import",
            "evidence.exact_byte_span.create",
            "finding.create",
            "claim.evidence_ledger.read",
            "brief.preview.markdown_json",
            "brief.export.markdown_json",
            "research.packet.v2.canonical",
            "research.request.v1.canonical",
            "research.request.v1.verify.cli",
            "research.request.v1.fulfill.cli",
            "research.result.v1.canonical",
            "web.review",
            "assist.finding_candidates.preview.cli",
            "assist.finding_candidates.invoke.cli.byok.optional",
        ],
        "unavailable": [
            "network.fetch",
            "model.invoke.api",
            "model.invoke.web",
            "model.output.auto_adopt",
            "provider.credential.persist",
            "mcp",
            "multi_user_auth",
            "publish",
            "remote_actor_headers",
            "sibling_artifact_exchange",
            "shared_run_envelope",
            "orchestration",
            "experiment_execution",
            "approval_authority",
        ],
        "limits": {
            "source_bytes": 1_048_576,
            "request_body_bytes": 5_242_880,
            "research_request_bytes": 65_536,
            "mission_page_size": 200,
            "assistant_context_bytes": 65_536,
            "assistant_evidence_cards": 50,
            "assistant_candidates": 3,
        },
    }


def test_strict_dto_rejects_unknown_fields_and_never_reflects_input(client: TestClient) -> None:
    private_value = "/home/operator/private/research.txt"
    private_field = "/home/operator/private/source.txt"
    response = client.post(
        "/api/v1/missions",
        json={
            "title": "Bounded title",
            "objective": "Bounded objective",
            private_field: private_value,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"
    assert response.json()["violations"] == [{"field": "unknown_field", "type": "extra_forbidden"}]
    assert private_field not in response.text
    assert private_value not in response.text


def test_text_bounds_fail_without_reflecting_oversized_value(client: TestClient) -> None:
    oversized = "sensitive-" + ("x" * 210)
    response = client.post(
        "/api/v1/missions",
        json={"title": oversized, "objective": "Objective"},
    )

    assert response.status_code == 422
    assert oversized not in response.text


def test_pagination_is_bounded(client: TestClient) -> None:
    too_small = client.get("/api/v1/missions?limit=0")
    too_large = client.get("/api/v1/missions?limit=201")

    assert too_small.status_code == 422
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "request_validation_failed"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("start_byte", True),
        ("end_byte", True),
        ("start_byte", "0"),
        ("end_byte", "1"),
    ],
)
def test_evidence_offsets_reject_coercive_json_types(
    client: TestClient,
    field: str,
    invalid_value: object,
) -> None:
    created = _create_vertical_slice(client)
    evidence = created["supporting"]
    payload = {
        "claim_id": created["claim"]["id"],
        "snapshot_id": created["source"]["snapshot_id"],
        "start_byte": evidence["start_byte"],
        "end_byte": evidence["end_byte"],
        "quote": evidence["quote"],
        "stance": "supports",
    }
    payload[field] = invalid_value

    response = client.post(
        f"/api/v1/missions/{created['mission']['id']}/evidence",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"


@pytest.mark.parametrize("header_name", ["X-Minerva-Actor", "X-Actor-ID", "Authorization"])
def test_external_actor_or_auth_headers_are_rejected(client: TestClient, header_name: str) -> None:
    actor_value = "remote-user-private-value"
    response = client.post(
        "/api/v1/missions",
        headers={header_name: actor_value},
        json={"title": "Mission", "objective": "Objective"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "external_identity_rejected"
    assert actor_value not in response.text


def test_api_vertical_slice_ledger_and_brief(client: TestClient) -> None:
    created = _create_vertical_slice(client)
    claim_id = created["claim"]["id"]
    mission_id = created["mission"]["id"]

    ledger_response = client.get(f"/api/v1/claims/{claim_id}/evidence")
    assert ledger_response.status_code == 200
    ledger = ledger_response.json()
    assert [item["evidence"]["stance"] for item in ledger["entries"]] == [
        "supports",
        "opposes",
    ]
    assert all(item["snapshot_sha256"] == created["source"]["sha256"] for item in ledger["entries"])
    assert ledger["entries"][0]["evidence"]["quote"] == created["supporting"]["quote"]

    brief_response = client.get(f"/api/v1/missions/{mission_id}/brief-preview")
    assert brief_response.status_code == 200
    brief = brief_response.json()
    assert len(brief["export_digest"]) == 64
    assert "SUPPORTS" in brief["markdown"]
    assert "OPPOSES" in brief["markdown"]
    assert created["finding"]["statement"] in brief["markdown"]
    assert brief["json_document"]["export_digest"] == brief["export_digest"]
    assert brief["markdown"].endswith("\n")
    assert sha256(brief["markdown"].encode()).hexdigest() == brief["markdown_sha256"]
    assert (
        brief["json_document"]["brief"]["citations"][0]["snapshot_sha256"]
        == created["source"]["sha256"]
    )


def test_source_endpoint_accepts_content_not_paths_and_metadata_omits_content(
    client: TestClient,
) -> None:
    mission = client.post(
        "/api/v1/missions",
        json={"title": "Source boundary", "objective": "Prove API byte import."},
    ).json()
    source_text = "Synthetic UTF-8 source."
    imported = client.post(
        f"/api/v1/missions/{mission['id']}/sources",
        json={
            "content": source_text,
            "original_label": "synthetic.txt",
            "media_type": "text/plain",
        },
    )
    assert imported.status_code == 201
    metadata = imported.json()

    fetched = client.get(f"/api/v1/snapshots/{metadata['snapshot_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == metadata
    assert "content" not in metadata
    assert "path" not in metadata
    assert source_text not in fetched.text

    private_path = "/home/operator/private.txt"
    rejected = client.post(
        f"/api/v1/missions/{mission['id']}/sources",
        json={
            "server_path": private_path,
            "original_label": "synthetic.txt",
            "media_type": "text/plain",
        },
    )
    assert rejected.status_code == 422
    assert private_path not in rejected.text


def test_source_and_evidence_errors_do_not_echo_submitted_content(client: TestClient) -> None:
    created = _create_vertical_slice(client)
    secret_source = "ghp_" + ("A" * 40)
    source_response = client.post(
        f"/api/v1/missions/{created['mission']['id']}/sources",
        json={
            "content": secret_source,
            "original_label": "blocked.txt",
            "media_type": "text/plain",
        },
    )
    assert source_response.status_code == 422
    assert secret_source not in source_response.text

    wrong_quote = "private mismatched quote"
    evidence_response = client.post(
        f"/api/v1/missions/{created['mission']['id']}/evidence",
        json={
            "claim_id": created["claim"]["id"],
            "snapshot_id": created["source"]["snapshot_id"],
            "start_byte": 0,
            "end_byte": 5,
            "quote": wrong_quote,
            "stance": "supports",
        },
    )
    assert evidence_response.status_code == 422
    assert wrong_quote not in evidence_response.text


def test_withdrawn_finding_provenance_is_explicit_in_api(client: TestClient) -> None:
    created = _create_vertical_slice(client)
    identity = local_identity(purpose="api provenance regression")
    EvidenceService(client.app.state.database).withdraw_evidence(
        evidence_id=created["supporting"]["id"],
        reason="Synthetic review invalidated this citation.",
        identity=identity,
    )

    response = client.get(f"/api/v1/missions/{created['mission']['id']}/findings")
    ledger_response = client.get(f"/api/v1/claims/{created['claim']['id']}/evidence")

    assert response.status_code == 200
    finding = response.json()["items"][0]
    assert finding["status"] == "contested"
    assert finding["citation_status"] == "withdrawn"
    assert ledger_response.status_code == 200
    withdrawn = next(item for item in ledger_response.json()["entries"] if item["withdrawn"])
    assert withdrawn["withdrawn_by"] == identity.actor_id


def test_claim_etag_and_if_match_enforce_optimistic_concurrency(client: TestClient) -> None:
    created = _create_vertical_slice(client)
    claim_id = created["claim"]["id"]
    current = client.get(f"/api/v1/claims/{claim_id}")
    etag = current.headers["etag"]

    missing = client.patch(
        f"/api/v1/claims/{claim_id}/status",
        json={"status": "contested", "reason": "Both stances are present."},
    )
    assert missing.status_code == 428

    invalid = client.patch(
        f"/api/v1/claims/{claim_id}/status",
        headers={"If-Match": '"claim-other-v1"'},
        json={"status": "contested", "reason": "Both stances are present."},
    )
    assert invalid.status_code == 412

    updated = client.patch(
        f"/api/v1/claims/{claim_id}/status",
        headers={"If-Match": etag},
        json={"status": "contested", "reason": "Both stances are present."},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.headers["etag"] == updated.json()["etag"]
    assert updated.headers["etag"] != etag

    stale = client.patch(
        f"/api/v1/claims/{claim_id}/status",
        headers={"If-Match": etag},
        json={"status": "unsupported", "reason": "Stale writer."},
    )
    assert stale.status_code == 412
    assert client.get(f"/api/v1/claims/{claim_id}").json()["status"] == "contested"


def test_api_responses_receive_security_headers_and_no_cors(client: TestClient) -> None:
    response = client.get(
        "/api/v1/capabilities",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert not any(name.lower().startswith("access-control-") for name in response.headers)


def test_all_rest_collections_use_deterministic_scoped_continuation_cursors(
    client: TestClient,
) -> None:
    created = _create_vertical_slice(client)
    mission_id = created["mission"]["id"]
    question_id = created["question"]["id"]

    second_mission = client.post(
        "/api/v1/missions",
        json={"title": "Second mission", "objective": "Cursor scope regression."},
    ).json()
    second_question = client.post(
        f"/api/v1/missions/{mission_id}/questions",
        json={"text": "What happens on the next page?"},
    )
    assert second_question.status_code == 201
    second_claim = client.post(
        f"/api/v1/missions/{mission_id}/claims",
        json={
            "question_id": question_id,
            "statement": "A second claim belongs on the next page.",
            "falsification_criteria": "The claim is absent from the continuation page.",
        },
    )
    assert second_claim.status_code == 201
    second_source = client.post(
        f"/api/v1/missions/{mission_id}/sources",
        json={
            "content": "Second deterministic source.",
            "original_label": "second-source.txt",
            "media_type": "text/plain",
        },
    )
    assert second_source.status_code == 201
    second_finding = client.post(
        f"/api/v1/missions/{mission_id}/findings",
        json={
            "statement": "The continuation contract is an explicit assumption.",
            "statement_kind": "assumption",
            "status": "inconclusive",
            "uncertainty": "This finding exists to exercise pagination.",
        },
    )
    assert second_finding.status_code == 201

    collections = (
        ("/api/v1/missions", "items", lambda item: item["id"]),
        (
            f"/api/v1/missions/{mission_id}/questions",
            "items",
            lambda item: item["id"],
        ),
        (
            f"/api/v1/missions/{mission_id}/claims",
            "items",
            lambda item: item["id"],
        ),
        (
            f"/api/v1/missions/{mission_id}/sources",
            "items",
            lambda item: item["snapshot_id"],
        ),
        (
            f"/api/v1/missions/{mission_id}/findings",
            "items",
            lambda item: item["id"],
        ),
        (
            f"/api/v1/claims/{created['claim']['id']}/evidence",
            "entries",
            lambda item: item["evidence"]["id"],
        ),
    )
    cursors: dict[str, str] = {}
    for url, item_key, identity in collections:
        first_response = client.get(url, params={"limit": 1})
        repeated_response = client.get(url, params={"limit": 1})
        assert first_response.status_code == 200
        assert repeated_response.status_code == 200
        first = first_response.json()
        repeated = repeated_response.json()
        assert first["next_cursor"] == repeated["next_cursor"]
        assert isinstance(first["next_cursor"], str)
        assert len(first[item_key]) == 1

        second_response = client.get(
            url,
            params={"limit": 1, "cursor": first["next_cursor"]},
        )
        assert second_response.status_code == 200
        second = second_response.json()
        assert len(second[item_key]) == 1
        assert identity(first[item_key][0]) != identity(second[item_key][0])
        assert second["next_cursor"] is None
        cursors[url] = first["next_cursor"]

    question_url = f"/api/v1/missions/{mission_id}/questions"
    wrong_scope = client.get(
        f"/api/v1/missions/{second_mission['id']}/questions",
        params={"limit": 1, "cursor": cursors[question_url]},
    )
    assert wrong_scope.status_code == 422
    assert wrong_scope.json()["error"]["code"] == "pagination_cursor_invalid"

    wrong_type = client.get(
        f"/api/v1/missions/{mission_id}/sources",
        params={"limit": 1, "cursor": cursors[question_url]},
    )
    assert wrong_type.status_code == 422
    assert wrong_type.json()["error"]["code"] == "pagination_cursor_invalid"

    private_cursor = "cHJpdmF0ZS1jdXJzb3ItdmFsdWU"
    malformed = client.get(
        "/api/v1/missions",
        params={"limit": 1, "cursor": private_cursor},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "pagination_cursor_invalid"
    assert private_cursor not in malformed.text


def test_api_claim_and_ledger_each_use_one_read_transaction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _create_vertical_slice(client)
    database = client.app.state.database
    original_read = database.read
    read_count = 0

    @contextmanager
    def counted_read() -> Iterator[sqlite3.Connection]:
        nonlocal read_count
        read_count += 1
        with original_read() as connection:
            yield connection

    monkeypatch.setattr(database, "read", counted_read)
    claim_id = created["claim"]["id"]

    claim_response = client.get(f"/api/v1/claims/{claim_id}")
    assert claim_response.status_code == 200
    assert read_count == 1

    read_count = 0
    ledger_response = client.get(f"/api/v1/claims/{claim_id}/evidence")
    assert ledger_response.status_code == 200
    assert read_count == 1
