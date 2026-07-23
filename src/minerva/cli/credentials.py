"""Resolve non-secret provider preferences and just-in-time environment credentials."""

from __future__ import annotations

import os
from collections.abc import Mapping

from minerva.assist.models import (
    ModelProvider,
    ProviderCredential,
    ProviderSelection,
    validate_model_id,
)
from minerva.core.errors import IntegrityError, SecurityBoundaryError


def resolve_provider_selection(
    *,
    provider: str | None,
    model: str | None,
    environment: Mapping[str, str] | None = None,
) -> ProviderSelection:
    values = os.environ if environment is None else environment
    raw_provider: str | None
    raw_model: str | None
    if (provider is None) is not (model is None):
        raise IntegrityError(
            "assistant_selection_incomplete",
            "CLI provider and model overrides must be supplied together.",
        )
    if provider is not None and model is not None:
        raw_provider = provider
        raw_model = model
        source = "cli"
    else:
        raw_provider = values.get("MINERVA_AI_PROVIDER")
        raw_model = values.get("MINERVA_AI_MODEL")
        source = "environment"
    if raw_provider is None or raw_model is None:
        raise IntegrityError(
            "assistant_selection_required",
            "Select a provider and model by CLI option or Minerva preference "
            "environment variables.",
        )
    try:
        selected_provider = ModelProvider(raw_provider)
    except ValueError:
        raise IntegrityError(
            "assistant_provider_invalid",
            "The selected model provider is not supported.",
        ) from None
    return ProviderSelection(selected_provider, validate_model_id(raw_model), source)


def load_provider_credential(
    provider: ModelProvider,
    *,
    environment: Mapping[str, str] | None = None,
) -> ProviderCredential:
    values = os.environ if environment is None else environment
    variable = provider.credential_environment_variable
    value = values.get(variable)
    if value is None:
        raise SecurityBoundaryError(
            "provider_credential_missing",
            f"Set {variable} in the current OS-user environment before authorizing egress.",
        )
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        encoded = b""
    if (
        not 8 <= len(encoded) <= 4_096
        or "\x00" in value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise SecurityBoundaryError(
            "provider_credential_invalid",
            "The selected provider credential is invalid.",
        )
    return ProviderCredential(value)
