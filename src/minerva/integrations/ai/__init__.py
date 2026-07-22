"""Explicit construction of the two reviewed external model adapters."""

from __future__ import annotations

from minerva.assist.models import ModelProvider
from minerva.assist.service import CandidateProvider
from minerva.core.errors import MinervaError


def candidate_provider(provider: ModelProvider) -> CandidateProvider:
    try:
        if provider is ModelProvider.OPENAI:
            from minerva.integrations.ai.openai import OpenAIProvider

            return OpenAIProvider()
        if provider is ModelProvider.ANTHROPIC:
            from minerva.integrations.ai.anthropic import AnthropicProvider

            return AnthropicProvider()
    except ModuleNotFoundError as error:
        if error.name in {"anthropic", "httpx", "openai"}:
            raise MinervaError(
                "provider_sdk_missing",
                "Install the selected Minerva provider extra before authorizing egress.",
                http_status=503,
            ) from None
        raise
    raise MinervaError(
        "assistant_provider_invalid",
        "The selected model provider is not supported.",
        http_status=400,
    )
