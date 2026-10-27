"""Anthropic adapter (requires ``pip install "driftguard-pro[anthropic]"``)."""

from __future__ import annotations

import time
from typing import Any

from ..errors import ProviderError
from ..models import Response
from .base import Pricing, provider_timeout, require_api_key

ENV_VAR = "ANTHROPIC_API_KEY"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, pricing: Pricing | None = None) -> None:
        if not model:
            raise ProviderError("a model name is required")
        self.model = model
        self.pricing = pricing

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> Response:
        api_key = require_api_key(ENV_VAR)
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(
                "the anthropic package is not installed: "
                'python -m pip install "driftguard-pro[anthropic]"'
            ) from exc
        client: Any = anthropic.Anthropic(
            api_key=api_key, timeout=provider_timeout(), max_retries=0
        )
        started = time.perf_counter()
        try:
            result = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise ProviderError(f"Anthropic request failed: {type(exc).__name__}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        text = "".join(
            block.text for block in result.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(result, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None)
        completion_tokens = getattr(usage, "output_tokens", None)
        cost = None
        if self.pricing and prompt_tokens is not None and completion_tokens is not None:
            cost = self.pricing.cost(prompt_tokens, completion_tokens)
        return Response(
            text=text,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            metadata={"provider": self.name, "model": self.model},
        )
