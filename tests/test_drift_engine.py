from __future__ import annotations

import json

import pytest

from driftguard.drift import compute_case_drift, drift_failures, pct_change
from driftguard.engine import aggregate_status, compare_fixtures, run_batch, run_suite
from driftguard.jsonutil import diff_json, try_parse_json
from driftguard.models import (
    Case,
    Fixtures,
    Response,
    RunConfig,
    Status,
    Suite,
    Thresholds,
)
from driftguard.similarity import lexical_similarity

from .conftest import make_case, make_suite


def drift(b: Response, c: Response, **th):
    return compute_case_drift(
        b, c, thresholds=Thresholds(**th), similarity_fn=lexical_similarity, method="lexical"
    )


def test_diff_json() -> None:
    d = diff_json(
        {"a": 1, "b": {"c": [1, 2]}, "gone": 1}, {"a": 2, "b": {"c": [1, 2, 3]}, "new": 1}
    )
    assert d.value_changed == ["a"]
    assert d.removed == ["gone"] and sorted(d.added) == ["b.c[2]", "new"]
    assert diff_json({"a": 1}, {"a": "1"}).type_changed == ["a"]
    assert diff_json([1], {"a": 1}).type_changed == ["$"]
    assert diff_json(True, 1).type_changed == ["$"]
    assert diff_json(1, 1.0).value_changed == []


def test_try_parse_json() -> None:
    assert try_parse_json('{"a": 1}') == (True, {"a": 1})
    assert try_parse_json("")[0] is False
    assert try_parse_json("[" * 100000)[0] is False


def test_pct_change_zero_baseline() -> None:
    assert pct_change(100, 150) == 50.0
    assert pct_change(0, 5) is None


def test_metric_thresholds_and_missing_data() -> None:
    d = drift(
        Response(text="a", latency_ms=100, prompt_tokens=10, completion_tokens=10, cost_usd=1.0),
        Response(text="a", latency_ms=160, prompt_tokens=10, completion_tokens=10, cost_usd=1.2),
    )
    by_name = {m.name: m for m in d.metrics}
    assert by_name["latency_ms"].exceeded and by_name["latency_ms"].pct_change == 60.0
    assert not by_name["total_tokens"].exceeded and not by_name["cost_usd"].exceeded
    codes = [c for c, _ in drift_failures(d, Thresholds(), 0.8)]
    assert codes == ["drift:latency"]
    # No data on one side -> metric silently absent, never an error.
    assert drift(Response(text="a"), Response(text="a", latency_ms=5)).metrics == []
    # Zero baseline cannot yield a percentage, so no threshold is applied.
    z = drift(Response(text="a", latency_ms=0), Response(text="a", latency_ms=50))
    assert z.metrics[0].pct_change is None and not z.metrics[0].exceeded


def test_disabled_thresholds() -> None:
    d = drift(
        Response(text="a", latency_ms=1),
        Response(text="a", latency_ms=1000),
        max_latency_increase_pct=None,
    )
    assert drift_failures(d, Thresholds(max_latency_increase_pct=None), 0.8) == []


def test_json_drift_flags() -> None:
    b = Response(text=json.dumps({"a": 1, "b": 2}))
    removed = drift(b, Response(text=json.dumps({"a": 1})))
    assert [c for c, _ in drift_failures(removed, Thresholds(min_similarity=0), 0)] == [
        "drift:json_structure"
    ]
    changed = drift(b, Response(text=json.dumps({"a": 1, "b": 3})))
    assert drift_failures(changed, Thresholds(min_similarity=0), 0) == []
    strict = Thresholds(min_similarity=0, fail_on_json_value_change=True)
    assert [c for c, _ in drift_failures(changed, strict, 0)] == ["drift:json_value"]
    broken = drift(b, Response(text="sorry, no json"))
    assert "no longer valid JSON" in drift_failures(broken, Thresholds(min_similarity=0), 0)[0][1]


def run_one(case: Case, **kw):
    return run_suite(make_suite(case, **kw)).results[0]


def test_status_pass() -> None:
    r = run_one(make_case(assertions=[{"type": "non_empty"}]))
    assert r.status is Status.PASS and r.drift and r.drift.similarity == 1.0


def test_status_fail_on_assertion() -> None:
    r = run_one(make_case(candidate="", assertions=[{"type": "non_empty"}]))
    assert r.status is Status.FAIL and "assertion:non_empty" in r.failure_codes


def test_status_fail_on_similarity_and_per_case_override() -> None:
    case = make_case(baseline="the cat sat on the mat", candidate="stock markets rallied today")
    assert run_one(case).status is Status.FAIL
    lenient = case.model_copy(update={"min_similarity": 0.0})
    assert run_one(lenient).status is Status.PASS


def test_status_error_missing_candidate() -> None:
    r = run_one(make_case(candidate=None, assertions=[{"type": "non_empty"}]))
    assert r.status is Status.ERROR and r.error == "missing candidate response"


def test_status_error_bad_schema_does_not_abort_other_cases() -> None:
    bad = make_case("bad", assertions=[{"type": "json_schema", "schema": {"type": "wat"}}])
    good = make_case("good", assertions=[{"type": "non_empty"}])
    report = run_suite(make_suite(bad, good))
    assert [r.status for r in report.results] == [Status.ERROR, Status.PASS]
    assert report.status is Status.ERROR
    assert "invalid JSON Schema" in (report.results[0].error or "")


def test_status_inconclusive_without_checks() -> None:
    r = run_one(make_case(baseline=None))
    assert r.status is Status.INCONCLUSIVE
    assert run_suite(make_suite()).status is Status.INCONCLUSIVE  # empty suite


def test_assertion_only_case_without_baseline_can_pass() -> None:
    assert (
        run_one(make_case(baseline=None, assertions=[{"type": "non_empty"}])).status is Status.PASS
    )


def test_suite_status_priority() -> None:
    p = make_case("p", assertions=[{"type": "non_empty"}])
    i = make_case("i", baseline=None)
    f = make_case("f", candidate="", assertions=[{"type": "non_empty"}])
    e = make_case("e", candidate=None)
    assert run_suite(make_suite(p, i)).status is Status.INCONCLUSIVE
    assert run_suite(make_suite(p, i, f)).status is Status.FAIL
    assert run_suite(make_suite(p, i, f, e)).status is Status.ERROR


def test_summary_counts_and_weighted_pass_rate() -> None:
    ok = make_case("ok", weight=3, assertions=[{"type": "non_empty"}])
    bad = make_case("bad", weight=1, candidate="", assertions=[{"type": "non_empty"}])
    s = run_suite(make_suite(ok, bad)).summary
    assert (s.total, s.passed, s.failed, s.errors, s.inconclusive) == (2, 1, 1, 0, 0)
    assert s.pass_rate == 0.5 and s.weighted_pass_rate == 0.75
    assert s.failure_reasons["assertion:non_empty"] == 1


def latency_suite(n: int, delta: float) -> Suite:
    cases = [
        Case(
            id=f"c{i}",
            baseline=Response(text="same", latency_ms=100 + i),
            candidate=Response(text="same", latency_ms=100 + i + delta),
        )
        for i in range(n)
    ]
    return Suite(
        name="lat",
        cases=cases,
        thresholds=Thresholds(max_latency_increase_pct=None),
    )


def test_significance_requires_enough_pairs_and_a_real_test() -> None:
    few = {m.metric: m for m in run_suite(latency_suite(3, 5)).summary.drift}["latency_ms"]
    assert few.significant is None and few.p_value is None and "no significance claim" in few.note
    assert few.ci_low is not None  # CI is still reported, but no test is claimed
    many = {m.metric: m for m in run_suite(latency_suite(10, 5)).summary.drift}["latency_ms"]
    assert many.significant is True and many.p_value is not None and many.p_value < 0.05
    assert "randomization test" in (many.test or "")
    none = {m.metric: m for m in run_suite(latency_suite(10, 0)).summary.drift}["latency_ms"]
    assert none.significant is False and none.p_value == 1.0


def test_metrics_without_data_report_zero_pairs() -> None:
    drift_summary = {m.metric: m for m in run_suite(make_suite(make_case())).summary.drift}
    assert (
        drift_summary["latency_ms"].n_pairs == 0 and drift_summary["latency_ms"].significant is None
    )
    assert drift_summary["similarity"].n_pairs == 1 and drift_summary["similarity"].ci_low is None


def test_reports_are_reproducible() -> None:
    suite = latency_suite(12, 3)
    a, b = run_suite(suite), run_suite(suite)
    assert a.model_dump_json() == b.model_dump_json()
    changed = run_suite(suite, RunConfig(seed=5))
    assert changed.metadata.run_id != a.metadata.run_id
    assert a.metadata.generated_at == "2023-11-14T22:13:20Z"  # SOURCE_DATE_EPOCH honoured


def test_batch_and_aggregate() -> None:
    good = make_suite(make_case(assertions=[{"type": "non_empty"}]), name="g")
    bad = make_suite(make_case(candidate="", assertions=[{"type": "non_empty"}]), name="b")
    reports = run_batch([good, bad])
    assert [r.status for r in reports] == [Status.PASS, Status.FAIL]
    assert aggregate_status(reports) is Status.FAIL
    assert run_batch([]) == []


def test_compare_fixtures_without_suite() -> None:
    base = Fixtures(name="v1", responses={"a": Response(text="hello"), "b": Response(text="x")})
    cand = Fixtures(name="v2", responses={"a": Response(text="hello"), "c": Response(text="new")})
    suite = compare_fixtures(base, cand)
    assert [c.id for c in suite.cases] == ["a", "b", "c"]
    statuses = {r.id: r.status for r in run_suite(suite).results}
    assert statuses == {"a": Status.PASS, "b": Status.ERROR, "c": Status.PASS}


def test_compare_fixtures_with_suite_keeps_assertions() -> None:
    suite = Suite.model_validate(
        {
            "name": "s",
            "cases": [
                {"id": "a", "assertions": [{"type": "exact_match", "expected": "yes"}], "weight": 2}
            ],
        }
    )
    base = Fixtures(responses={"a": Response(text="yes")})
    cand = Fixtures(responses={"a": Response(text="no")})
    report = run_suite(compare_fixtures(base, cand, suite))
    assert report.results[0].status is Status.FAIL and report.results[0].weight == 2
    assert report.metadata.suite_name == "compare: s"


@pytest.mark.parametrize("n", [0, 1])
def test_tiny_suites_do_not_crash(n: int) -> None:
    cases = [
        make_case(
            f"c{i}", assertions=[{"type": "non_empty"}], b={"latency_ms": 1}, c={"latency_ms": 2}
        )
        for i in range(n)
    ]
    report = run_suite(make_suite(*cases))
    assert report.summary.total == n
