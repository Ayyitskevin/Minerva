from __future__ import annotations

import copy
import json
import pickle
from collections.abc import Callable
from dataclasses import replace

import pytest

from conftest import ClaimSeed, Lab, fixed_clock
from minerva.assist.models import (
    CandidateDraft,
    CandidatePreview,
    ModelProvider,
    ProviderCredential,
    ProviderOutcome,
    ProviderRequest,
    ProviderResponse,
    ProviderSelection,
    ProviderUsage,
    validate_model_id,
)
from minerva.assist.service import SYSTEM_PROMPT, AssistanceService
from minerva.cli.credentials import load_provider_credential, resolve_provider_selection
from minerva.cli.main import main
from minerva.core.audit import list_audit_events
from minerva.core.errors import ConflictError, IntegrityError, MinervaError, SecurityBoundaryError
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.research.models import StatementKind


class FakeProvider:
    def __init__(
        self,
        response: ProviderResponse | None = None,
        *,
        provider: ModelProvider = ModelProvider.OPENAI,
        failure: Exception | None = None,
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.provider = provider
        self.response = response
        self.failure = failure
        self.callback = callback
        self.calls = 0
        self.last_request: ProviderRequest | None = None

    def generate(
        self,
        request: ProviderRequest,
        _credential: ProviderCredential,
    ) -> ProviderResponse:
        self.calls += 1
        self.last_request = request
        if self.callback is not None:
            self.callback()
        if self.failure is not None:
            raise self.failure
        if self.response is None:
            raise AssertionError("fake provider needs a response")
        return self.response


def _selection(
    provider: ModelProvider = ModelProvider.OPENAI,
    model: str = "test-model-1",
) -> ProviderSelection:
    return ProviderSelection(provider, model, "cli")


def _response(
    evidence_ids: list[str],
    *,
    outcome: ProviderOutcome = ProviderOutcome.SUCCEEDED,
    candidates: tuple[CandidateDraft, ...] | None = None,
    returned_model: str = "test-model-1",
    response_id: str | None = "response_test_123",
    usage: ProviderUsage | None = None,
) -> ProviderResponse:
    if candidates is None:
        candidates = (
            CandidateDraft(
                statement="The bounded evidence supports a cautious candidate.",
                uncertainty="The evidence does not establish generality.",
                evidence_ids=evidence_ids,
            ),
        )
    if usage is None:
        usage = ProviderUsage(120, 40)
    return ProviderResponse(
        outcome=outcome,
        returned_model=returned_model,
        response_id=response_id,
        candidates=candidates,
        usage=usage,
    )


def _seed_preview(
    lab: Lab,
) -> tuple[AssistanceService, CandidatePreview, ClaimSeed, EvidenceCard, EvidenceCard]:
    seed = lab.seed_claim()
    supporting = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    opposing = lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    service = AssistanceService(
        lab.database,
        clock=fixed_clock,
        id_factory=lab.ids,
    )
    preview = service.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=_selection(),
        max_candidates=2,
        max_output_tokens=512,
    )
    return service, preview, seed, supporting, opposing


def _assistance_events(lab: Lab) -> list[dict[str, object]]:
    with lab.database.read() as connection:
        events = list_audit_events(connection, limit=500)
    return [
        event for event in events if str(event["event_type"]).startswith("assistance.invocation.")
    ]


def _research_counts(lab: Lab) -> dict[str, int]:
    tables = (
        "claims",
        "claim_status_events",
        "evidence_cards",
        "evidence_withdrawals",
        "findings",
        "finding_citations",
        "source_snapshots",
    )
    with lab.database.read() as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            )
            for table in tables
        }


def test_preview_is_deterministic_minimal_and_excludes_withdrawn_evidence(lab: Lab) -> None:
    service, first, seed, supporting, opposing = _seed_preview(lab)
    withdrawn = lab.cite(
        seed,
        "Café context remains uncertain.",
        EvidenceStance.INCONCLUSIVE,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=withdrawn.id,
        reason="Keep the provider context limited to active evidence.",
        identity=lab.identity,
    )

    second = service.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=_selection(),
        max_candidates=2,
        max_output_tokens=512,
    )
    third = service.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=_selection(),
        max_candidates=2,
        max_output_tokens=512,
    )

    assert second.request_sha256 == third.request_sha256
    assert second.context_sha256 == third.context_sha256
    assert second.request_sha256 == first.request_sha256
    assert second.evidence_ids == (supporting.id, opposing.id)
    assert second.excluded_withdrawn_evidence_ids == (withdrawn.id,)
    context = json.loads(second.context_json)
    assert set(context) == {"claim", "evidence", "schema_version", "task"}
    assert set(context["claim"]) == {"falsification_criteria", "id", "statement"}
    assert all(set(item) == {"citation_id", "quote", "stance"} for item in context["evidence"])
    assert "citation_id values" in SYSTEM_PROMPT
    assert "output evidence_ids" in SYSTEM_PROMPT
    assert {item["stance"] for item in context["evidence"]} == {"supports", "opposes"}
    assert "source.txt" not in second.context_json
    assert "snapshot_sha256" not in second.context_json
    assert "workflow_status" not in second.context_json
    assert second.context_bytes == len(second.context_json.encode("utf-8"))
    assert second.external_data_notice.endswith("preview.")
    assert _assistance_events(lab) == []


@pytest.mark.security
def test_raw_claim_secret_is_blocked_before_serialization_or_egress(lab: Lab) -> None:
    seed = lab.seed_claim()
    claim = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=seed.question.id,
        statement="api_key = synthetic-credential-value-123",
        falsification_criteria="A benign observation would falsify this synthetic claim.",
        identity=lab.identity,
    )
    quote = "Evidence supports the claim."
    encoded = quote.encode()
    start = seed.content.index(encoded)
    lab.evidence.add_evidence(
        mission_id=seed.mission.id,
        claim_id=claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        start_byte=start,
        end_byte=start + len(encoded),
        quote=quote,
        stance=EvidenceStance.SUPPORTS,
        identity=lab.identity,
    )
    service = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)

    with pytest.raises(SecurityBoundaryError) as raised:
        service.preview_finding_candidates(
            claim_id=claim.id,
            selection=_selection(),
            max_candidates=1,
            max_output_tokens=256,
        )

    assert raised.value.code == "assistant_context_secret_detected"
    assert _assistance_events(lab) == []


def test_preview_requires_active_bounded_evidence(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = lab.seed_claim()
    service = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    with pytest.raises(IntegrityError) as empty:
        service.preview_finding_candidates(
            claim_id=seed.claim.id,
            selection=_selection(),
            max_candidates=1,
            max_output_tokens=256,
        )
    assert empty.value.code == "assistant_evidence_required"

    lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    monkeypatch.setattr("minerva.assist.service.MAX_ASSISTANCE_EVIDENCE_CARDS", 1)
    with pytest.raises(IntegrityError) as too_many:
        service.preview_finding_candidates(
            claim_id=seed.claim.id,
            selection=_selection(),
            max_candidates=1,
            max_output_tokens=256,
        )
    assert too_many.value.code == "assistant_context_too_large"


def test_preview_enforces_context_and_request_limits(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _preview, seed, _supporting, _opposing = _seed_preview(lab)
    monkeypatch.setattr("minerva.assist.service.MAX_ASSISTANCE_CONTEXT_BYTES", 1)
    with pytest.raises(IntegrityError) as too_large:
        service.preview_finding_candidates(
            claim_id=seed.claim.id,
            selection=_selection(),
            max_candidates=1,
            max_output_tokens=256,
        )
    assert too_large.value.code == "assistant_context_too_large"

    for candidates, tokens, expected in (
        (0, 256, "assistant_candidate_limit_invalid"),
        (4, 256, "assistant_candidate_limit_invalid"),
        (1, 127, "assistant_output_limit_invalid"),
        (1, 2049, "assistant_output_limit_invalid"),
    ):
        with pytest.raises(IntegrityError) as invalid:
            service.preview_finding_candidates(
                claim_id=seed.claim.id,
                selection=_selection(),
                max_candidates=candidates,
                max_output_tokens=tokens,
            )
        assert invalid.value.code == expected


def test_authorized_generation_is_one_call_candidate_only_and_metadata_audited(lab: Lab) -> None:
    service, preview, _seed, supporting, opposing = _seed_preview(lab)
    provider = FakeProvider(_response([supporting.id, opposing.id]))
    before = _research_counts(lab)
    secret = "provider-secret-sentinel-123"

    bundle = service.generate_finding_candidates(
        preview=preview,
        expected_request_sha256=preview.request_sha256,
        provider=provider,
        credential=ProviderCredential(secret),
        timeout_seconds=30,
        identity=lab.identity,
    )

    assert provider.calls == 1
    assert provider.last_request is not None
    assert provider.last_request.context_json == preview.context_json
    assert provider.last_request.system_prompt
    assert bundle.candidate_only is True
    assert bundle.candidates[0].statement_kind is StatementKind.AGENT_INFERENCE
    assert bundle.candidates[0].evidence_ids == (supporting.id, opposing.id)
    assert "not evidence or truth" in bundle.disclaimer
    assert _research_counts(lab) == before

    events = _assistance_events(lab)
    assert [event["event_type"] for event in events] == [
        "assistance.invocation.requested",
        "assistance.invocation.succeeded",
    ]
    serialized_events = json.dumps(events, sort_keys=True)
    assert secret not in serialized_events
    assert bundle.candidates[0].statement not in serialized_events
    assert "Evidence supports the claim." not in serialized_events
    assert preview.context_json not in serialized_events
    assert "response_test_123" not in serialized_events


@pytest.mark.security
def test_digest_provider_and_timeout_fail_before_egress(lab: Lab) -> None:
    service, preview, _seed, supporting, _opposing = _seed_preview(lab)
    response = _response([supporting.id])
    cases = (
        (
            FakeProvider(response),
            "0" * 64,
            30,
            "assistant_authorization_mismatch",
        ),
        (
            FakeProvider(response, provider=ModelProvider.ANTHROPIC),
            preview.request_sha256,
            30,
            "assistant_provider_mismatch",
        ),
        (
            FakeProvider(response),
            preview.request_sha256,
            0,
            "assistant_timeout_invalid",
        ),
    )
    for provider, digest, timeout, code in cases:
        with pytest.raises(MinervaError) as raised:
            service.generate_finding_candidates(
                preview=preview,
                expected_request_sha256=digest,
                provider=provider,
                credential=ProviderCredential("synthetic-key-value"),
                timeout_seconds=timeout,
                identity=lab.identity,
            )
        assert raised.value.code == code
        assert provider.calls == 0
    assert _assistance_events(lab) == []


@pytest.mark.security
def test_authorization_rejects_tampered_preview_fields_before_provider_access(lab: Lab) -> None:
    service, preview, _seed, supporting, _opposing = _seed_preview(lab)
    tampered_previews = (
        replace(preview, context_json='{"tampered":true}'),
        replace(preview, evidence_ids=("evd_tampered",)),
        replace(preview, mission_id="mis_tampered"),
        replace(preview, context_sha256="0" * 64),
    )

    for tampered in tampered_previews:
        with pytest.raises(ConflictError) as preflight:
            service.authorize_finding_candidate_request(
                preview=tampered,
                expected_request_sha256=preview.request_sha256,
                timeout_seconds=30.0,
            )
        assert preflight.value.code == "assistant_context_changed"

        provider = FakeProvider(_response([supporting.id]))
        with pytest.raises(ConflictError) as generated:
            service.generate_finding_candidates(
                preview=tampered,
                expected_request_sha256=preview.request_sha256,
                provider=provider,
                credential=ProviderCredential("synthetic-key-value"),
                timeout_seconds=30.0,
                identity=lab.identity,
            )
        assert generated.value.code == "assistant_context_changed"
        assert provider.calls == 0
    assert _assistance_events(lab) == []


def test_replayed_or_changed_context_is_rejected_before_or_after_egress(lab: Lab) -> None:
    service, preview, _seed, supporting, opposing = _seed_preview(lab)
    lab.evidence.withdraw_evidence(
        evidence_id=supporting.id,
        reason="Invalidate the approved preview before dispatch.",
        identity=lab.identity,
    )
    replayed = FakeProvider(_response([opposing.id]))
    with pytest.raises(ConflictError) as before:
        service.generate_finding_candidates(
            preview=preview,
            expected_request_sha256=preview.request_sha256,
            provider=replayed,
            credential=ProviderCredential("synthetic-key-value"),
            timeout_seconds=30,
            identity=lab.identity,
        )
    assert before.value.code == "assistant_context_changed"
    assert replayed.calls == 0
    assert _assistance_events(lab) == []

    current = service.preview_finding_candidates(
        claim_id=preview.claim_id,
        selection=_selection(),
        max_candidates=2,
        max_output_tokens=512,
    )

    def withdraw_last() -> None:
        lab.evidence.withdraw_evidence(
            evidence_id=opposing.id,
            reason="Invalidate all context after external dispatch.",
            identity=lab.identity,
        )

    changed = FakeProvider(_response([opposing.id]), callback=withdraw_last)
    with pytest.raises(ConflictError) as after:
        service.generate_finding_candidates(
            preview=current,
            expected_request_sha256=current.request_sha256,
            provider=changed,
            credential=ProviderCredential("synthetic-key-value"),
            timeout_seconds=30,
            identity=lab.identity,
        )
    assert after.value.code == "assistant_context_changed"
    assert changed.calls == 1
    assert [event["event_type"] for event in _assistance_events(lab)] == [
        "assistance.invocation.requested",
        "assistance.invocation.stale_context",
    ]


def test_second_post_call_freshness_check_discards_late_change(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, preview, _seed, supporting, _opposing = _seed_preview(lab)
    states = iter((True, True, False))
    monkeypatch.setattr(service, "_preview_is_current", lambda _preview: next(states))
    provider = FakeProvider(_response([supporting.id]))

    with pytest.raises(ConflictError):
        service.generate_finding_candidates(
            preview=preview,
            expected_request_sha256=preview.request_sha256,
            provider=provider,
            credential=ProviderCredential("synthetic-key-value"),
            timeout_seconds=30,
            identity=lab.identity,
        )

    assert provider.calls == 1
    assert _assistance_events(lab)[-1]["event_type"] == "assistance.invocation.stale_context"


@pytest.mark.parametrize(
    ("failure", "terminal_event", "public_code"),
    [
        (
            MinervaError(
                "provider_outcome_unknown",
                "The provider outcome is unknown.",
                http_status=503,
            ),
            "assistance.invocation.outcome_unknown",
            "provider_outcome_unknown",
        ),
        (
            MinervaError("provider_rate_limited", "The provider rate limited the request."),
            "assistance.invocation.failed",
            "provider_rate_limited",
        ),
        (
            RuntimeError("private provider body and local path"),
            "assistance.invocation.failed",
            "provider_internal_error",
        ),
    ],
)
def test_provider_failures_are_sanitized_and_terminally_audited(
    lab: Lab,
    failure: Exception,
    terminal_event: str,
    public_code: str,
) -> None:
    service, preview, _seed, _supporting, _opposing = _seed_preview(lab)
    provider = FakeProvider(failure=failure)
    with pytest.raises(MinervaError) as raised:
        service.generate_finding_candidates(
            preview=preview,
            expected_request_sha256=preview.request_sha256,
            provider=provider,
            credential=ProviderCredential("synthetic-key-value"),
            timeout_seconds=30,
            identity=lab.identity,
        )
    assert raised.value.code == public_code
    assert "private provider body" not in raised.value.public_message
    assert provider.calls == 1
    assert _assistance_events(lab)[-1]["event_type"] == terminal_event


@pytest.mark.parametrize("outcome", [ProviderOutcome.REFUSED, ProviderOutcome.INCOMPLETE])
def test_non_success_provider_outcomes_return_no_candidates_and_are_audited(
    lab: Lab,
    outcome: ProviderOutcome,
) -> None:
    service, preview, _seed, _supporting, _opposing = _seed_preview(lab)
    response = _response([], outcome=outcome, candidates=())
    bundle = service.generate_finding_candidates(
        preview=preview,
        expected_request_sha256=preview.request_sha256,
        provider=FakeProvider(response),
        credential=ProviderCredential("synthetic-key-value"),
        timeout_seconds=30,
        identity=lab.identity,
    )
    assert bundle.outcome is outcome
    assert bundle.candidates == ()
    assert _assistance_events(lab)[-1]["event_type"] == f"assistance.invocation.{outcome.value}"


def test_invalid_provider_candidates_fail_closed(lab: Lab) -> None:
    service, preview, _seed, supporting, _opposing = _seed_preview(lab)
    invalid_responses = (
        (
            _response(
                [],
                candidates=(
                    CandidateDraft(
                        statement="Invented citation.",
                        uncertainty="Unknown provenance.",
                        evidence_ids=["evd_ffffffffffffffffffffffffffffffff"],
                    ),
                ),
            ),
            "provider_citation_invalid",
        ),
        (
            _response(
                [],
                candidates=(
                    CandidateDraft(
                        statement="Duplicate citation.",
                        uncertainty="Duplicate identifiers are invalid.",
                        evidence_ids=[supporting.id, supporting.id],
                    ),
                ),
            ),
            "provider_citation_invalid",
        ),
        (
            _response(
                [],
                candidates=(
                    CandidateDraft(
                        statement="api_key = synthetic-credential-value-123",
                        uncertainty="Secret-bearing output is unsafe.",
                        evidence_ids=[supporting.id],
                    ),
                ),
            ),
            "provider_response_secret_detected",
        ),
        (
            _response(
                [supporting.id],
                candidates=tuple(
                    CandidateDraft(
                        statement=f"Candidate {index}",
                        uncertainty="Bounded uncertainty.",
                        evidence_ids=[supporting.id],
                    )
                    for index in range(3)
                ),
            ),
            "provider_response_invalid",
        ),
        (
            _response([supporting.id], usage=ProviderUsage(True, 2)),
            "provider_response_invalid",
        ),
        (
            _response([supporting.id], response_id="sk-proj-" + ("A" * 32)),
            "provider_response_invalid",
        ),
        (
            _response([supporting.id], returned_model="sk-proj-" + ("B" * 32)),
            "assistant_model_secret_detected",
        ),
    )
    for response, expected_code in invalid_responses:
        with pytest.raises(MinervaError) as raised:
            service.generate_finding_candidates(
                preview=preview,
                expected_request_sha256=preview.request_sha256,
                provider=FakeProvider(response),
                credential=ProviderCredential("synthetic-key-value"),
                timeout_seconds=30,
                identity=lab.identity,
            )
        assert raised.value.code == expected_code
        assert _assistance_events(lab)[-1]["event_type"] == "assistance.invocation.failed"


def test_provider_selection_is_explicit_and_never_mixes_cli_with_preferences() -> None:
    environment = {
        "MINERVA_AI_PROVIDER": "anthropic",
        "MINERVA_AI_MODEL": "claude-test-model",
    }
    preferred = resolve_provider_selection(provider=None, model=None, environment=environment)
    assert preferred == ProviderSelection(
        ModelProvider.ANTHROPIC,
        "claude-test-model",
        "environment",
    )
    overridden = resolve_provider_selection(
        provider="openai",
        model="gpt-test-model",
        environment=environment,
    )
    assert overridden == ProviderSelection(ModelProvider.OPENAI, "gpt-test-model", "cli")
    for provider, model in ((None, "gpt-test-model"), ("openai", None)):
        with pytest.raises(IntegrityError) as incomplete:
            resolve_provider_selection(
                provider=provider,
                model=model,
                environment=environment,
            )
        assert incomplete.value.code == "assistant_selection_incomplete"


@pytest.mark.parametrize(
    ("provider", "model", "environment", "code"),
    [
        (None, None, {}, "assistant_selection_required"),
        (
            None,
            None,
            {"MINERVA_AI_PROVIDER": "unknown", "MINERVA_AI_MODEL": "m"},
            "assistant_provider_invalid",
        ),
        ("openai", " invalid ", {}, "assistant_model_invalid"),
        ("openai", "sk-proj-" + ("C" * 32), {}, "assistant_model_secret_detected"),
    ],
)
def test_invalid_provider_preferences_fail_safely(
    provider: str | None,
    model: str | None,
    environment: dict[str, str],
    code: str,
) -> None:
    with pytest.raises(MinervaError) as raised:
        resolve_provider_selection(
            provider=provider,
            model=model,
            environment=environment,
        )
    assert raised.value.code == code


@pytest.mark.security
def test_credentials_are_environment_only_redacted_and_nonserializable() -> None:
    sentinel = "provider-secret-sentinel-123"
    credential = load_provider_credential(
        ModelProvider.OPENAI,
        environment={"OPENAI_API_KEY": sentinel},
    )
    assert credential.reveal() == sentinel
    assert sentinel not in repr(credential)
    assert sentinel not in str(credential)
    for action in (
        lambda: copy.copy(credential),
        lambda: copy.deepcopy(credential),
        lambda: pickle.dumps(credential),
        lambda: json.dumps(credential),
    ):
        with pytest.raises(TypeError) as raised:
            action()
        assert sentinel not in str(raised.value)

    with pytest.raises(SecurityBoundaryError) as missing:
        load_provider_credential(ModelProvider.ANTHROPIC, environment={})
    assert missing.value.code == "provider_credential_missing"
    assert "ANTHROPIC_API_KEY" in missing.value.public_message
    for invalid in ("short", " leading-value", "line\nbreak", "é" * 8):
        with pytest.raises(SecurityBoundaryError) as rejected:
            load_provider_credential(
                ModelProvider.OPENAI,
                environment={"OPENAI_API_KEY": invalid},
            )
        assert rejected.value.code == "provider_credential_invalid"
        assert invalid not in rejected.value.public_message


def test_validate_model_id_rejects_non_strings() -> None:
    with pytest.raises(IntegrityError):
        validate_model_id(123)  # type: ignore[arg-type]


def test_cli_preview_needs_no_key_sdk_or_network(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _service, _preview, seed, _supporting, _opposing = _seed_preview(lab)

    def unexpected_credential(_provider: ModelProvider) -> ProviderCredential:
        raise AssertionError("preview must not load a credential")

    monkeypatch.setattr("minerva.cli.main.load_provider_credential", unexpected_credential)
    code = main(
        (
            "assist",
            "finding-candidates",
            "--db",
            str(lab.database.path),
            "--claim",
            seed.claim.id,
            "--provider",
            "openai",
            "--model",
            "test-model-1",
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document["mode"] == "preview"
    assert document["network_called"] is False
    assert document["preview"]["context_json"]
    assert document["credential_environment_variable"] == "OPENAI_API_KEY"


@pytest.mark.security
def test_cli_confirmation_uses_exact_digest_and_never_outputs_or_persists_key(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _service, _preview, seed, supporting, _opposing = _seed_preview(lab)
    base_arguments = (
        "assist",
        "finding-candidates",
        "--db",
        str(lab.database.path),
        "--claim",
        seed.claim.id,
        "--provider",
        "openai",
        "--model",
        "test-model-1",
    )
    assert main(base_arguments) == 0
    preview_output = json.loads(capsys.readouterr().out)
    digest = preview_output["preview"]["request_sha256"]
    assert isinstance(digest, str)

    sentinel = "provider-secret-sentinel-123"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    provider = FakeProvider(_response([supporting.id]))
    import minerva.integrations.ai as integrations

    monkeypatch.setattr(integrations, "candidate_provider", lambda _provider: provider)
    assert (
        main((*base_arguments, "--confirm-external-send", "--expected-request-sha256", digest)) == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert sentinel not in captured.out
    document = json.loads(captured.out)
    assert document["mode"] == "completed"
    assert document["network_called"] is True
    assert document["result"]["candidate_only"] is True
    assert provider.calls == 1
    assert sentinel.encode() not in lab.database.path.read_bytes()


@pytest.mark.security
def test_cli_rejects_stale_digest_before_adapter_or_credential_access(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _service, preview, seed, _supporting, _opposing = _seed_preview(lab)
    touched: list[str] = []

    def unexpected_provider(_provider: ModelProvider) -> FakeProvider:
        touched.append("provider")
        raise AssertionError("authorization failure must not construct an adapter")

    def unexpected_credential(_provider: ModelProvider) -> ProviderCredential:
        touched.append("credential")
        raise AssertionError("authorization failure must not read a credential")

    import minerva.integrations.ai as integrations

    monkeypatch.setattr(integrations, "candidate_provider", unexpected_provider)
    monkeypatch.setattr("minerva.cli.main.load_provider_credential", unexpected_credential)
    code = main(
        (
            "assist",
            "finding-candidates",
            "--db",
            str(lab.database.path),
            "--claim",
            seed.claim.id,
            "--provider",
            "openai",
            "--model",
            "test-model-1",
            "--confirm-external-send",
            "--expected-request-sha256",
            "0" * 64 if preview.request_sha256 != "0" * 64 else "1" * 64,
        )
    )

    assert code == 3
    assert touched == []
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "assistant_authorization_mismatch"


def test_cli_rejects_ambiguous_confirmation_and_secret_arguments(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _service, preview, seed, _supporting, _opposing = _seed_preview(lab)
    arguments = (
        "assist",
        "finding-candidates",
        "--db",
        str(lab.database.path),
        "--claim",
        seed.claim.id,
        "--provider",
        "openai",
        "--model",
        "test-model-1",
    )
    assert main((*arguments, "--expected-request-sha256", preview.request_sha256)) == 3
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "assistant_confirmation_invalid"

    assert main((*arguments, "--confirm-external-send")) == 3
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "assistant_authorization_required"

    with pytest.raises(SystemExit) as raised:
        main((*arguments, "--api-key", "must-never-be-an-option"))
    assert raised.value.code == 2
    capsys.readouterr()
