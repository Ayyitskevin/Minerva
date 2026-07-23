"""Anthropic Messages adapter; the only Minerva module allowed to import this SDK."""

from __future__ import annotations

import os
import re

import httpx
from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError

from minerva.assist.models import (
    CandidateDraftBundle,
    ModelProvider,
    ProviderCredential,
    ProviderOutcome,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    candidate_output_schema,
    validate_model_id,
)
from minerva.core.errors import MinervaError

_BASE_URL = "https://api.anthropic.com"
_SAFE_RESPONSE_ID = re.compile(r"[\x21-\x7e]{1,200}\Z")
_UNSUPPORTED_SDK_ENVIRONMENT = frozenset({"ANTHROPIC_CUSTOM_HEADERS"})


class AnthropicProvider:
    provider = ModelProvider.ANTHROPIC

    def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential,
    ) -> ProviderResponse:
        _reject_ambient_sdk_configuration()
        try:
            with httpx.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=request.timeout_seconds,
            ) as transport:
                client = Anthropic(
                    api_key=credential.reveal(),
                    base_url=_BASE_URL,
                    max_retries=0,
                    timeout=request.timeout_seconds,
                    http_client=transport,
                )
                response = client.messages.create(
                    model=request.model,
                    max_tokens=request.max_output_tokens,
                    system=request.system_prompt,
                    messages=[{"role": "user", "content": request.context_json}],
                    output_config={
                        "format": {
                            "schema": candidate_output_schema(request.max_candidates),
                            "type": "json_schema",
                        }
                    },
                )
        except (APITimeoutError, APIConnectionError):
            raise MinervaError(
                "provider_outcome_unknown",
                "The Anthropic request outcome is unknown; Minerva will not retry automatically.",
                http_status=503,
            ) from None
        except (AuthenticationError, PermissionDeniedError):
            raise MinervaError(
                "provider_auth_failed",
                "Anthropic rejected the configured credential or permission.",
                http_status=502,
            ) from None
        except RateLimitError:
            raise MinervaError(
                "provider_rate_limited",
                "Anthropic rate-limited the request; Minerva did not retry it.",
                http_status=503,
            ) from None
        except APIError:
            raise MinervaError(
                "provider_request_rejected",
                "Anthropic rejected the provider request.",
                http_status=502,
            ) from None
        except (ValidationError, TypeError, ValueError, AttributeError):
            raise MinervaError(
                "provider_response_invalid",
                "Anthropic returned an invalid structured response.",
                http_status=502,
            ) from None

        try:
            returned_model = _required_model_metadata(getattr(response, "model", None))
            response_id = _required_response_id(getattr(response, "id", None))
            normalized_usage = _normalize_usage(getattr(response, "usage", None))
        except (AttributeError, TypeError, ValueError):
            raise MinervaError(
                "provider_response_invalid",
                "Anthropic returned invalid response metadata.",
                http_status=502,
            ) from None
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            return ProviderResponse(
                ProviderOutcome.REFUSED,
                returned_model,
                response_id,
                (),
                normalized_usage,
            )
        if stop_reason in {"max_tokens", "pause_turn"}:
            return ProviderResponse(
                ProviderOutcome.INCOMPLETE,
                returned_model,
                response_id,
                (),
                normalized_usage,
            )
        if stop_reason not in {"end_turn", "stop_sequence"}:
            raise MinervaError(
                "provider_response_invalid",
                "Anthropic returned an invalid terminal response.",
                http_status=502,
            )
        try:
            bundle = CandidateDraftBundle.model_validate_json(_response_text(response))
        except (ValidationError, TypeError, ValueError):
            raise MinervaError(
                "provider_response_invalid",
                "Anthropic returned an invalid candidate payload.",
                http_status=502,
            ) from None
        return ProviderResponse(
            ProviderOutcome.SUCCEEDED,
            returned_model,
            response_id,
            tuple(bundle.candidates),
            normalized_usage,
        )


def _reject_ambient_sdk_configuration() -> None:
    if any(name in os.environ for name in _UNSUPPORTED_SDK_ENVIRONMENT):
        raise MinervaError(
            "provider_environment_unsupported",
            "Remove unsupported Anthropic SDK environment controls before authorizing egress.",
            http_status=403,
        )


def _response_text(response: object) -> str:
    content = getattr(response, "content", None)
    if not isinstance(content, list | tuple):
        raise ValueError("invalid output content")
    texts: list[str] = []
    for item in content:
        if getattr(item, "type", None) != "text":
            raise ValueError("unexpected output content")
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            raise ValueError("invalid output text")
        texts.append(text)
    document = "".join(texts)
    if not document or len(document.encode("utf-8")) > 65_536:
        raise ValueError("invalid output size")
    return document


def _required_model_metadata(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("missing model metadata")
    try:
        return validate_model_id(value)
    except MinervaError:
        raise ValueError("invalid model metadata") from None


def _required_response_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_RESPONSE_ID.fullmatch(value) is None:
        raise ValueError("invalid response identifier")
    return value


def _normalize_usage(value: object) -> ProviderUsage:
    if value is None:
        raise ValueError("missing usage metadata")
    return ProviderUsage(
        input_tokens=_required_token_count(getattr(value, "input_tokens", None)),
        output_tokens=_required_token_count(getattr(value, "output_tokens", None)),
    )


def _required_token_count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid token count")
    return value
