"""Property-based tests (Hypothesis) for invariants that example tests can miss."""

from __future__ import annotations

import math

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from driftguard.diff import diff_reports
from driftguard.engine import run_suite
from driftguard.jsonutil import diff_json, try_parse_json
from driftguard.models import Case, Response, Suite
from driftguard.reports import render_html, render_junit, render_markdown
from driftguard.similarity import lexical_similarity
from driftguard.stats import paired_bootstrap_ci, paired_permutation_test

SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
texts = st.text(max_size=300)
finite = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-1000, 1000) | st.text(max_size=10),
    lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=5), c, max_size=4),
    max_leaves=12,
)


@SETTINGS
@given(texts)
def test_identical_text_is_always_exactly_one(text: str) -> None:
    assert lexical_similarity(text, text) == 1.0


@SETTINGS
@given(texts, texts)
def test_similarity_is_symmetric_and_bounded(a: str, b: str) -> None:
    s = lexical_similarity(a, b)
    assert 0.0 <= s <= 1.0
    assert s == lexical_similarity(b, a)


@SETTINGS
@given(json_values)
def test_json_self_diff_is_empty(value) -> None:
    d = diff_json(value, value)
    assert not (d.added or d.removed or d.type_changed or d.value_changed)


@SETTINGS
@given(json_values, json_values)
def test_json_diff_never_raises_and_is_symmetric_on_add_remove(a, b) -> None:
    forward, backward = diff_json(a, b), diff_json(b, a)
    assert sorted(forward.added) == sorted(backward.removed)
    assert sorted(forward.type_changed) == sorted(backward.type_changed)


@SETTINGS
@given(texts)
def test_try_parse_json_never_raises(text: str) -> None:
    ok, _ = try_parse_json(text)
    assert isinstance(ok, bool)


@SETTINGS
@given(st.lists(st.tuples(finite, finite), min_size=2, max_size=25), st.integers(0, 2**31))
def test_bootstrap_ci_is_ordered_deterministic_and_brackets(pairs, seed) -> None:
    base, cand = [p[0] for p in pairs], [p[1] for p in pairs]
    a = paired_bootstrap_ci(base, cand, seed=seed, n_resamples=200)
    assert a == paired_bootstrap_ci(base, cand, seed=seed, n_resamples=200)
    assert a.ci_low <= a.ci_high
    diffs = [c - b for b, c in zip(base, cand, strict=True)]
    assert min(diffs) - 1e-6 <= a.ci_low and a.ci_high <= max(diffs) + 1e-6


@SETTINGS
@given(st.lists(st.tuples(finite, finite), min_size=1, max_size=10), st.integers(0, 1000))
def test_permutation_p_value_is_a_valid_probability(pairs, seed) -> None:
    base, cand = [p[0] for p in pairs], [p[1] for p in pairs]
    r = paired_permutation_test(base, cand, seed=seed, n_resamples=200)
    assert 0.0 < r.p_value <= 1.0 and math.isfinite(r.observed_mean_diff)
    swapped = paired_permutation_test(cand, base, seed=seed, n_resamples=200)
    assert math.isclose(r.p_value, swapped.p_value, rel_tol=1e-9)  # sign symmetry (exact path)


responses = st.builds(
    Response,
    text=texts,
    latency_ms=st.none() | st.floats(0, 1e5),
    completion_tokens=st.none() | st.integers(0, 10**5),
)
cases = st.lists(
    st.builds(
        Case,
        id=st.text(min_size=1, max_size=20),
        baseline=st.none() | responses,
        candidate=st.none() | responses,
        weight=st.floats(0.1, 10),
        assertions=st.just([{"type": "non_empty"}]) | st.just([]),
    ),
    max_size=8,
    unique_by=lambda c: c.id,
)


@SETTINGS
@given(cases)
def test_engine_and_renderers_never_crash_on_arbitrary_input(case_list) -> None:
    report = run_suite(Suite(name="prop", cases=case_list))
    assert report.summary.total == len(case_list)
    assert (
        report.summary.passed
        + report.summary.failed
        + report.summary.errors
        + report.summary.inconclusive
        == len(case_list)
    )
    for render in (render_html, render_junit, render_markdown):
        assert render(report)
    assert not diff_reports(report, report).has_regressions
    assert (
        run_suite(Suite(name="prop", cases=case_list)).model_dump_json() == report.model_dump_json()
    )
