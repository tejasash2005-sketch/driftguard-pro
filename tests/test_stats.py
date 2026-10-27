from __future__ import annotations

import math

import pytest

from driftguard.errors import StatsError
from driftguard.stats import (
    bootstrap_ci,
    paired_bootstrap_ci,
    paired_permutation_test,
    weighted_mean,
)

BASE = [10.0, 12.0, 9.5, 11.0, 10.5, 12.5, 9.0, 10.0]
CAND = [11.0, 12.5, 10.5, 12.5, 11.0, 13.0, 10.5, 11.5]


def test_bootstrap_is_deterministic_for_fixed_seed() -> None:
    a = paired_bootstrap_ci(BASE, CAND, seed=7, n_resamples=500)
    b = paired_bootstrap_ci(BASE, CAND, seed=7, n_resamples=500)
    c = paired_bootstrap_ci(BASE, CAND, seed=8, n_resamples=500)
    assert a == b
    assert (a.ci_low, a.ci_high) != (c.ci_low, c.ci_high)


def test_bootstrap_ci_brackets_mean_and_is_ordered() -> None:
    r = paired_bootstrap_ci(BASE, CAND, seed=1)
    assert r.ci_low <= r.mean <= r.ci_high
    assert r.mean == pytest.approx(sum(c - b for b, c in zip(BASE, CAND, strict=True)) / len(BASE))
    assert r.ci_low > 0  # every pair increased


def test_bootstrap_degenerate_constant_diff() -> None:
    r = paired_bootstrap_ci([1, 2, 3, 4], [2, 3, 4, 5], seed=0)
    assert r.ci_low == r.ci_high == r.mean == 1.0


def test_bootstrap_weighted() -> None:
    unweighted = bootstrap_ci([0.0, 10.0], seed=0, n_resamples=200)
    weighted = bootstrap_ci([0.0, 10.0], [9.0, 1.0], seed=0, n_resamples=200)
    assert unweighted.mean == 5.0
    assert weighted.mean == 1.0


@pytest.mark.parametrize(
    "call",
    [
        lambda: paired_bootstrap_ci([1.0], [2.0]),  # n < 2
        lambda: paired_bootstrap_ci([1.0, 2.0], [1.0]),  # length mismatch
        lambda: paired_bootstrap_ci([1.0, float("nan")], [1.0, 2.0]),
        lambda: paired_bootstrap_ci([1.0, 2.0], [1.0, float("inf")]),
        lambda: paired_bootstrap_ci([1.0, "x"], [1.0, 2.0]),  # type: ignore[list-item]
        lambda: paired_bootstrap_ci([True, False], [1.0, 2.0]),
        lambda: paired_bootstrap_ci([1.0, 2.0], [1.0, 2.0], confidence=1.0),
        lambda: paired_bootstrap_ci([1.0, 2.0], [1.0, 2.0], n_resamples=0),
        lambda: bootstrap_ci([1.0, 2.0], [1.0, 0.0]),  # non-positive weight
        lambda: bootstrap_ci([1.0, 2.0], [1.0]),  # weight length
        lambda: weighted_mean([]),
    ],
)
def test_invalid_statistics_inputs(call) -> None:
    with pytest.raises(StatsError):
        call()


def test_permutation_exact_p_value() -> None:
    # Six positive, equal differences: only the all-plus and all-minus sign
    # assignments reach |mean| = 1, so p = 2 / 2**6 exactly.
    r = paired_permutation_test([0.0] * 6, [1.0] * 6)
    assert r.method == "exact"
    assert r.p_value == 2 / 64
    assert r.n_permutations == 64


def test_permutation_no_difference_gives_p_one() -> None:
    r = paired_permutation_test([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6])
    assert r.p_value == 1.0
    assert r.observed_mean_diff == 0.0


def test_permutation_symmetric_mixed_signs() -> None:
    r = paired_permutation_test([0, 0, 0, 0, 0, 0], [1, -1, 1, -1, 1, -1])
    assert r.observed_mean_diff == 0.0 and r.p_value == 1.0


def test_permutation_monte_carlo_is_seeded_and_valid() -> None:
    base = list(range(30))
    cand = [x + 1.0 + (i % 3) * 0.1 for i, x in enumerate(base)]
    a = paired_permutation_test(base, cand, seed=3, n_resamples=2000)
    b = paired_permutation_test(base, cand, seed=3, n_resamples=2000)
    assert a == b and a.method == "monte_carlo"
    assert 0 < a.p_value < 0.01
    assert a.p_value >= 1 / 2001  # never exactly zero


def test_permutation_weights_change_result() -> None:
    base = [0.0] * 6
    cand = [1.0, 1.0, 1.0, 1.0, 1.0, -5.0]
    unweighted = paired_permutation_test(base, cand)
    heavy_outlier = paired_permutation_test(base, cand, [1, 1, 1, 1, 1, 10])
    assert unweighted.observed_mean_diff != heavy_outlier.observed_mean_diff
    assert math.isfinite(heavy_outlier.p_value)


def test_permutation_invalid() -> None:
    with pytest.raises(StatsError):
        paired_permutation_test([], [])
    with pytest.raises(StatsError):
        paired_permutation_test([1.0], [1.0, 2.0])
