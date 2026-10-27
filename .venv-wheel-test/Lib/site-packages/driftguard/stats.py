"""Seeded statistics: bootstrap confidence intervals and a paired randomization test.

Nothing here declares "significance" on its own. ``paired_permutation_test`` returns a
p-value for a clearly defined test; callers compare it to a pre-chosen alpha.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from .errors import StatsError


@dataclass(frozen=True)
class BootstrapResult:
    n: int
    mean: float
    ci_low: float
    ci_high: float
    confidence: float
    n_resamples: int
    seed: int


@dataclass(frozen=True)
class PermutationResult:
    n: int
    observed_mean_diff: float
    p_value: float
    method: str  # "exact" or "monte_carlo"
    n_permutations: int
    seed: int


def _validate(values: Sequence[float], weights: Sequence[float] | None, label: str) -> list[float]:
    if isinstance(values, str | bytes):
        raise StatsError(f"{label} must be a sequence of numbers")
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise StatsError(f"{label} contains a non-numeric value: {value!r}")
        if not math.isfinite(value):
            raise StatsError(f"{label} contains a non-finite value")
        out.append(float(value))
    if weights is not None:
        if len(weights) != len(out):
            raise StatsError("weights must have the same length as the data")
        for weight in weights:
            if not math.isfinite(weight) or weight <= 0:
                raise StatsError("weights must be finite and strictly positive")
    return out


def _weights(weights: Sequence[float] | None, n: int) -> list[float]:
    return [1.0] * n if weights is None else [float(w) for w in weights]


def cap_resamples(n: int, requested: int, *, budget: int = 4_000_000, floor: int = 200) -> int:
    """Limit ``n * resamples`` to ``budget`` so huge suites stay fast (never below ``floor``).

    Deterministic: depends only on ``n`` and ``requested``.
    """
    if n <= 0:
        return requested
    return max(min(requested, floor), min(requested, budget // n))


def weighted_mean(values: Sequence[float], weights: Sequence[float] | None = None) -> float:
    data = _validate(values, weights, "values")
    if not data:
        raise StatsError("cannot compute the mean of an empty sequence")
    w = _weights(weights, len(data))
    return math.fsum(x * y for x, y in zip(data, w, strict=True)) / math.fsum(w)


def _check_params(confidence: float, n_resamples: int) -> None:
    if not 0 < confidence < 1:
        raise StatsError("confidence must be strictly between 0 and 1")
    if n_resamples < 1:
        raise StatsError("n_resamples must be at least 1")


def bootstrap_ci(
    values: Sequence[float],
    weights: Sequence[float] | None = None,
    *,
    confidence: float = 0.95,
    n_resamples: int = 2000,
    seed: int = 0,
) -> BootstrapResult:
    """Percentile bootstrap CI for the (weighted) mean. Deterministic for a given seed."""
    _check_params(confidence, n_resamples)
    data = _validate(values, weights, "values")
    n = len(data)
    if n < 2:
        raise StatsError("bootstrap requires at least 2 observations")
    w = _weights(weights, n)
    rng = random.Random(seed)
    indices = range(n)
    weighted_data = [wi * x for wi, x in zip(w, data, strict=True)]
    stats: list[float] = []
    for _ in range(n_resamples):
        sample = rng.choices(indices, k=n)
        stats.append(sum([weighted_data[i] for i in sample]) / sum([w[i] for i in sample]))
    stats.sort()
    tail = (1 - confidence) / 2
    low = stats[int(math.floor(tail * n_resamples))]
    high = stats[min(n_resamples - 1, int(math.ceil((1 - tail) * n_resamples)) - 1)]
    mean = math.fsum(w[i] * data[i] for i in indices) / math.fsum(w)
    return BootstrapResult(n, mean, low, high, confidence, n_resamples, seed)


def paired_bootstrap_ci(
    baseline: Sequence[float],
    candidate: Sequence[float],
    weights: Sequence[float] | None = None,
    *,
    confidence: float = 0.95,
    n_resamples: int = 2000,
    seed: int = 0,
) -> BootstrapResult:
    """Paired percentile bootstrap CI for mean(candidate - baseline)."""
    base = _validate(baseline, None, "baseline")
    cand = _validate(candidate, None, "candidate")
    if len(base) != len(cand):
        raise StatsError("baseline and candidate must have the same length (paired data)")
    diffs = [c - b for b, c in zip(base, cand, strict=True)]
    return bootstrap_ci(diffs, weights, confidence=confidence, n_resamples=n_resamples, seed=seed)


def paired_permutation_test(
    baseline: Sequence[float],
    candidate: Sequence[float],
    weights: Sequence[float] | None = None,
    *,
    n_resamples: int = 10_000,
    seed: int = 0,
    exact_max_n: int = 12,
) -> PermutationResult:
    """Two-sided paired sign-flip randomization test on the weighted mean difference.

    H0: the distribution of paired differences is symmetric about zero. With
    ``n <= exact_max_n`` all ``2**n`` sign assignments are enumerated (exact p-value);
    otherwise ``n_resamples`` random assignments are drawn with a fixed seed and the
    p-value is ``(count + 1) / (n_resamples + 1)``.
    """
    base = _validate(baseline, None, "baseline")
    cand = _validate(candidate, None, "candidate")
    if len(base) != len(cand):
        raise StatsError("baseline and candidate must have the same length (paired data)")
    n = len(base)
    if n < 1:
        raise StatsError("permutation test requires at least 1 pair")
    _validate(base, weights, "baseline")
    w = _weights(weights, n)
    diffs = [c - b for b, c in zip(base, cand, strict=True)]
    total_w = math.fsum(w)
    weighted = [wi * d for wi, d in zip(w, diffs, strict=True)]
    observed = math.fsum(weighted) / total_w
    tolerance = 1e-12 * max(1.0, abs(observed))
    cutoff = abs(observed) - tolerance

    if n <= exact_max_n:
        count = 0
        total = 1 << n
        for mask in range(total):
            stat = math.fsum(-x if (mask >> i) & 1 else x for i, x in enumerate(weighted)) / total_w
            if abs(stat) >= cutoff:
                count += 1
        return PermutationResult(n, observed, count / total, "exact", total, seed)

    if n_resamples < 1:
        raise StatsError("n_resamples must be at least 1")
    rng = random.Random(seed)
    count = 0
    for _ in range(n_resamples):
        stat = sum([x if rng.random() < 0.5 else -x for x in weighted]) / total_w
        if abs(stat) >= cutoff:
            count += 1
    return PermutationResult(
        n, observed, (count + 1) / (n_resamples + 1), "monte_carlo", n_resamples, seed
    )
