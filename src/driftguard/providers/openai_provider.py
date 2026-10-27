"""OpenAI adapter (requires ``pip install "driftguard-pro[openai]"``)."""

from __future__ import annotations

import time
from typing import Any

from ..errors import ProviderError
from ..models import Response
from .base import Pricing, provider_timeout, require_api_key

ENV_VAR = "OPENAI_API_KEY"


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, pricing: Pricing | None = None) -> None:
        if not model:
            raise ProviderError("a model name is required")
        self.model = model
        self.pricing = pricing

    def __repr__(self) -> str:
        return f"OpenAIProvider(model={self.model!r})"

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> Response:
        api_key = require_api_key(ENV_VAR)
        try:
            import openai
        except ImportError as exc:
            raise ProviderError(
                "the openai package is not installed: "
                'python -m pip install "driftguard-pro[openai]"'
            ) from exc
        client: Any = openai.OpenAI(api_key=api_key, timeout=provider_timeout(), max_retries=0)
        started = time.perf_counter()
        try:
            result = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
        except Exception as exc:
            # Only the exception type is surfaced; messages can echo request details.
            raise ProviderError(f"OpenAI request failed: {type(exc).__name__}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        text = (result.choices[0].message.content or "") if result.choices else ""
        usage = getattr(result, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
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
