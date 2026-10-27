"""Optional LLM provider adapters. Keys are read only from environment variables."""

from __future__ import annotations

from ..errors import ProviderError
from .anthropic_provider import AnthropicProvider
from .base import Pricing, Provider
from .openai_provider import OpenAIProvider

PROVIDERS = ("openai", "anthropic")


def get_provider(name: str, model: str, pricing: Pricing | None = None) -> Provider:
    if name == "openai":
        return OpenAIProvider(model=model, pricing=pricing)
    if name == "anthropic":
        return AnthropicProvider(model=model, pricing=pricing)
    raise ProviderError(f"unknown provider {name!r}; choose one of: {', '.join(PROVIDERS)}")


__all__ = [
    "PROVIDERS",
    "AnthropicProvider",
    "OpenAIProvider",
    "Pricing",
    "Provider",
    "get_provider",
]
