"""Provider protocol and shared helpers."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Protocol

from ..errors import MissingAPIKeyError, ProviderError
from ..models import Response


@dataclass(frozen=True)
class Pricing:
    """USD per one million tokens. Supplied by the caller; never hardcoded."""

    prompt_per_1m: float
    completion_per_1m: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return round(
            (prompt_tokens * self.prompt_per_1m + completion_tokens * self.completion_per_1m)
            / 1_000_000,
            8,
        )


def provider_timeout() -> float:
    """Return a bounded SDK request timeout, defaulting to 30 seconds."""
    raw = os.environ.get("DRIFTGUARD_PROVIDER_TIMEOUT", "30").strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ProviderError("DRIFTGUARD_PROVIDER_TIMEOUT must be a number from 0.1 to 300") from exc
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 300:
        raise ProviderError("DRIFTGUARD_PROVIDER_TIMEOUT must be a number from 0.1 to 300")
    return timeout


class Provider(Protocol):
    name: str
    model: str

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> Response: ...


def require_api_key(env_var: str) -> str:
    """Read an API key from the environment. The value is never logged or stored."""
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise MissingAPIKeyError(
            f"environment variable {env_var} is not set; export it to use this provider"
        )
    return value
