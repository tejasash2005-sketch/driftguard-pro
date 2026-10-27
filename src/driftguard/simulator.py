"""Seeded, deterministic response simulator.

Every random decision is drawn from a ``random.Random`` seeded from
``sha256(seed:case_id:role)``, so results are identical across runs, platforms and
case orderings.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Literal

from pydantic import Field

from .jsonutil import try_parse_json
from .models import (
    AssertionSpec,
    Case,
    Response,
    StrictModel,
    Suite,
    Thresholds,
)

_FILLER = ["perhaps", "generally", "kindly", "unfortunately", "approximately", "typically"]


class SimCase(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    prompt: str = ""
    weight: float = Field(default=1.0, gt=0, le=1_000_000, allow_inf_nan=False)
    base_text: str
    base_latency_ms: float = Field(default=400.0, ge=0, allow_inf_nan=False)
    prompt_tokens: int = Field(default=20, ge=0)
    completion_tokens: int = Field(default=50, ge=0)
    cost_per_1k_tokens: float = Field(default=0.002, ge=0, allow_inf_nan=False)
    assertions: list[AssertionSpec] = Field(default_factory=list)


class Regression(StrictModel):
    kind: Literal["text_drift", "latency", "tokens", "cost", "json_break", "empty"]
    probability: float = Field(default=0.5, ge=0, le=1)
    magnitude: float = Field(default=0.5, ge=0, le=10, allow_inf_nan=False)
    case_ids: list[str] | None = None


class SimulatorConfig(StrictModel):
    name: str = Field(default="simulated-suite", min_length=1, max_length=200)
    seed: int = 0
    noise: float = Field(default=0.05, ge=0, le=1)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    cases: list[SimCase] = Field(min_length=1, max_length=10_000)
    regressions: list[Regression] = Field(default_factory=list)


def derive_seed(seed: int, case_id: str, role: str) -> int:
    digest = hashlib.sha256(f"{seed}:{case_id}:{role}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _jitter(rng: random.Random, value: float, noise: float) -> float:
    return value * (1 + rng.uniform(-noise, noise))


def _make_response(case: SimCase, rng: random.Random, noise: float) -> Response:
    prompt_tokens = max(0, round(_jitter(rng, case.prompt_tokens, noise)))
    completion_tokens = max(0, round(_jitter(rng, case.completion_tokens, noise)))
    latency = round(_jitter(rng, case.base_latency_ms, noise), 3)
    cost = round((prompt_tokens + completion_tokens) / 1000 * case.cost_per_1k_tokens, 8)
    return Response(
        text=case.base_text,
        latency_ms=latency,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
    )


def _mutate_words(text: str, fraction: float, rng: random.Random) -> str:
    words = text.split(" ")
    if not words:
        return text
    count = max(1, round(len(words) * min(1.0, fraction))) if fraction > 0 else 0
    for index in rng.sample(range(len(words)), k=min(count, len(words))):
        words[index] = rng.choice(_FILLER)
    return " ".join(words)


def _mutate_json_strings(value: Any, fraction: float, rng: random.Random) -> Any:
    if isinstance(value, str):
        return _mutate_words(value, fraction, rng)
    if isinstance(value, list):
        return [_mutate_json_strings(v, fraction, rng) for v in value]
    if isinstance(value, dict):
        return {k: _mutate_json_strings(value[k], fraction, rng) for k in sorted(value)}
    return value


def _apply(regression: Regression, response: Response, rng: random.Random) -> None:
    kind, magnitude = regression.kind, regression.magnitude
    if kind == "latency" and response.latency_ms is not None:
        response.latency_ms = round(response.latency_ms * (1 + magnitude), 3)
    elif kind == "tokens" and response.completion_tokens is not None:
        response.completion_tokens = round(response.completion_tokens * (1 + magnitude))
    elif kind == "cost" and response.cost_usd is not None:
        response.cost_usd = round(response.cost_usd * (1 + magnitude), 8)
    elif kind == "empty":
        response.text = ""
    elif kind == "text_drift":
        ok, value = try_parse_json(response.text)
        if ok and isinstance(value, dict | list):
            mutated = _mutate_json_strings(value, magnitude, rng)
            response.text = json.dumps(mutated, sort_keys=True)
        elif not ok:
            response.text = _mutate_words(response.text, magnitude, rng)
    elif kind == "json_break":
        ok, value = try_parse_json(response.text)
        if ok and isinstance(value, dict) and value:
            del value[rng.choice(sorted(value))]
            response.text = json.dumps(value, sort_keys=True)
        else:
            response.text = response.text[: len(response.text) // 2]


def simulate(config: SimulatorConfig) -> Suite:
    """Generate a suite with simulated baseline and candidate responses."""
    cases: list[Case] = []
    for sim in config.cases:
        baseline = _make_response(
            sim, random.Random(derive_seed(config.seed, sim.id, "baseline")), config.noise
        )
        rng = random.Random(derive_seed(config.seed, sim.id, "candidate"))
        candidate = _make_response(sim, rng, config.noise)
        applied: list[str] = []
        for regression in config.regressions:
            if regression.case_ids is not None and sim.id not in regression.case_ids:
                continue
            if rng.random() < regression.probability:
                _apply(regression, candidate, rng)
                applied.append(regression.kind)
        candidate.metadata["simulated_regressions"] = applied
        cases.append(
            Case(
                id=sim.id,
                prompt=sim.prompt,
                weight=sim.weight,
                assertions=sim.assertions,
                baseline=baseline,
                candidate=candidate,
            )
        )
    return Suite(
        name=config.name,
        description=f"Simulated with seed {config.seed} (DriftGuard simulator)",
        thresholds=config.thresholds,
        cases=cases,
    )
