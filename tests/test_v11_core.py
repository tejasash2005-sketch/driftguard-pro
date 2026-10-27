"""Tests for 1.1 features: new assertions, diff, report formats, store, performance."""

from __future__ import annotations

import json
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from driftguard.assertions import evaluate_assertion
from driftguard.diff import diff_reports
from driftguard.engine import run_suite
from driftguard.errors import DriftGuardError, NotFoundError
from driftguard.loader import load_report, load_suite
from driftguard.models import AssertionSpec, Case, Report, Response, RunConfig, Status, Suite
from driftguard.reports import (
    render,
    render_diff_markdown,
    render_diff_text,
    render_junit,
    render_markdown,
    write_report,
)
from driftguard.similarity import MAX_SEQUENCE_TOKENS, lexical_similarity
from driftguard.stats import cap_resamples
from driftguard.store import RunStore, SqliteRunStore

from .conftest import EXAMPLES, make_case, make_suite

DATA = Path(__file__).parent / "data"
ADAPTER: TypeAdapter[AssertionSpec] = TypeAdapter(AssertionSpec)


def check(spec: dict, text: str):
    return evaluate_assertion(ADAPTER.validate_python(spec), Response(text=text))


# ------------------------------------------------------------------ new assertions


def test_contains_and_not_contains() -> None:
    assert check({"type": "contains", "value": "Refund"}, "A Refund is due").passed
    assert not check({"type": "contains", "value": "refund"}, "A Refund is due").passed
    assert check(
        {"type": "contains", "value": "refund", "case_sensitive": False}, "A Refund"
    ).passed
    missing = check({"type": "contains", "value": "xyz"}, "abc")
    assert not missing.passed and "xyz" in missing.message
    assert check({"type": "not_contains", "value": "sorry"}, "all good").passed
    bad = check({"type": "not_contains", "value": "SORRY", "case_sensitive": False}, "I am sorry")
    assert not bad.passed and "forbidden" in bad.message


def test_length_assertion() -> None:
    spec = {"type": "length", "min": 3, "max": 5}
    assert check(spec, "abcd").passed and check(spec, "  abcd  ").passed
    assert "below minimum" in check(spec, "ab").message
    assert "exceeds maximum" in check(spec, "abcdef").message
    assert check({"type": "length", "max": 0}, "   ").passed
    for bad in (
        {"type": "length"},
        {"type": "length", "min": 5, "max": 1},
        {"type": "length", "min": -1},
        {"type": "contains", "value": ""},
    ):
        with pytest.raises(ValidationError):
            ADAPTER.validate_python(bad)


# ------------------------------------------------------------------ diff


def reports_pair() -> tuple[Report, Report]:
    ok = lambda i: make_case(i, assertions=[{"type": "non_empty"}])  # noqa: E731
    bad = lambda i: make_case(i, candidate="", assertions=[{"type": "non_empty"}])  # noqa: E731
    old = run_suite(
        make_suite(ok("stays"), ok("breaks"), bad("heals"), bad("still"), ok("gone"), name="s")
    )
    new = run_suite(
        make_suite(
            ok("stays"),
            bad("breaks"),
            ok("heals"),
            bad("still"),
            ok("fresh"),
            bad("fresh_bad"),
            name="s",
        )
    )
    return old, new


def test_diff_classifies_cases() -> None:
    old, new = reports_pair()
    d = diff_reports(old, new)
    assert [c.id for c in d.regressions] == ["breaks"]
    assert [c.id for c in d.fixed] == ["heals"]
    assert sorted(c.id for c in d.added) == ["fresh", "fresh_bad"]
    assert [c.id for c in d.removed] == ["gone"]
    assert d.unchanged == 2 and d.changed == []
    assert d.has_regressions
    assert d.regressions[0].old_status is Status.PASS and d.regressions[0].new_status is Status.FAIL
    assert d.pass_rate_delta is not None


def test_diff_identical_and_improvement_only() -> None:
    old, new = reports_pair()
    assert not diff_reports(old, old).has_regressions
    assert diff_reports(old, old).unchanged == len(old.results)
    reverse = diff_reports(new, old)
    assert [c.id for c in reverse.regressions] == ["heals"]
    assert [c.id for c in reverse.fixed] == ["breaks"]
    only_fix = diff_reports(
        run_suite(make_suite(make_case("a", candidate="", assertions=[{"type": "non_empty"}]))),
        run_suite(make_suite(make_case("a", assertions=[{"type": "non_empty"}]))),
    )
    assert not only_fix.has_regressions and [c.id for c in only_fix.fixed] == ["a"]


def test_diff_added_failing_case_counts_as_regression() -> None:
    base = run_suite(make_suite(make_case("a", assertions=[{"type": "non_empty"}])))
    plus = run_suite(
        make_suite(
            make_case("a", assertions=[{"type": "non_empty"}]),
            make_case("b", candidate="", assertions=[{"type": "non_empty"}]),
        )
    )
    d = diff_reports(base, plus)
    assert d.regressions == [] and d.has_regressions


def test_diff_removed_case_is_a_regression() -> None:
    old = run_suite(make_suite(make_case("kept"), make_case("removed")))
    new = run_suite(make_suite(make_case("kept")))
    diff = diff_reports(old, new)
    assert [case.id for case in diff.removed] == ["removed"]
    assert diff.has_regressions


def test_diff_rejects_incompatible_reports() -> None:
    report = run_suite(make_suite(make_case("a"), name="suite"))
    with pytest.raises(DriftGuardError, match="different suites"):
        diff_reports(report, run_suite(make_suite(make_case("a"), name="other")))
    version_two = report.metadata.model_copy(update={"suite_version": "2"})
    with pytest.raises(DriftGuardError, match="different suite versions"):
        diff_reports(report, report.model_copy(update={"metadata": version_two}))
    unknown_schema = report.metadata.model_copy(update={"report_schema_version": 99})
    with pytest.raises(DriftGuardError, match="unsupported report schema"):
        diff_reports(report, report.model_copy(update={"metadata": unknown_schema}))


def test_diff_rejects_duplicate_case_ids() -> None:
    report = run_suite(make_suite(make_case("a")))
    malformed = report.model_copy(
        update={
            "results": [*report.results, report.results[0]],
            "summary": report.summary.model_copy(update={"total": 2}),
        }
    )
    with pytest.raises(DriftGuardError, match="duplicate case IDs"):
        diff_reports(report, malformed)


def test_diff_changed_failure_codes_and_similarity_delta() -> None:
    a = make_case("x", baseline="the cat sat", candidate="", assertions=[{"type": "non_empty"}])
    b = make_case(
        "x",
        baseline="the cat sat",
        candidate="zzz qqq",
        assertions=[{"type": "exact_match", "expected": "never"}],
    )
    d = diff_reports(run_suite(make_suite(a)), run_suite(make_suite(b)))
    assert [c.id for c in d.changed] == ["x"] and d.changed[0].new_failure_codes


def test_diff_renderers() -> None:
    d = diff_reports(*reports_pair())
    text = render_diff_text(d)
    assert "[REGRESSED] breaks: PASS -> FAIL" in text and "REGRESSIONS FOUND" in text
    md = render_diff_markdown(d)
    assert "| regressed | `breaks` | PASS -> FAIL |" in md


# ------------------------------------------------------------------ report formats


def test_junit_structure_and_counts() -> None:
    cases = [
        make_case("p", assertions=[{"type": "non_empty"}]),
        make_case("f", candidate="", assertions=[{"type": "non_empty"}]),
        make_case("e", candidate=None),
        make_case("i", baseline=None),
    ]
    xml = render_junit(run_suite(make_suite(*cases, name="J & <suite>")))
    root = ET.fromstring(xml)
    assert root.tag == "testsuite" and root.get("name") == "J & <suite>"
    assert (root.get("tests"), root.get("failures"), root.get("errors"), root.get("skipped")) == (
        "4",
        "1",
        "1",
        "1",
    )
    by_name = {tc.get("name"): tc for tc in root.findall("testcase")}
    assert by_name["p"].find("failure") is None
    assert by_name["f"].find("failure") is not None and by_name["e"].find("error") is not None
    assert by_name["i"].find("skipped") is not None
    assert render_junit(run_suite(make_suite(*cases, name="J"))) == render_junit(
        run_suite(make_suite(*cases, name="J"))
    )


def test_write_report_does_not_overwrite_different_run_for_same_suite(tmp_path: Path) -> None:
    suite = make_suite(make_case("a"), name="same-suite")
    first = run_suite(suite)
    second = run_suite(suite, RunConfig(seed=1))
    paths_a = write_report(first, tmp_path, ("json",))
    paths_b = write_report(second, tmp_path, ("json",))
    assert paths_a[0] != paths_b[0]
    assert load_report(paths_a[0]).metadata.run_id == first.metadata.run_id
    assert load_report(paths_b[0]).metadata.run_id == second.metadata.run_id


def test_junit_strips_illegal_xml_characters() -> None:
    case = Case(
        id="c\x00x",
        assertions=[{"type": "exact_match", "expected": "a\x0bb"}],
        candidate=Response(text="zz"),
    )
    ET.fromstring(render_junit(run_suite(Suite(name="s\x01", cases=[case]))))  # must parse


def test_markdown_escapes_table_cells() -> None:
    case = Case(
        id="a|b",
        assertions=[{"type": "exact_match", "expected": "x|y\nz"}],
        candidate=Response(text="q"),
    )
    md = render_markdown(run_suite(Suite(name="m", cases=[case])))
    row = next(line for line in md.splitlines() if line.startswith("| `a"))
    assert "\\|" in row and "\n" not in row[:-1]
    assert md.startswith("## DriftGuard: m - **FAIL**")


def test_render_dispatch_and_write_all_formats(tmp_path: Path) -> None:
    report = run_suite(load_suite(EXAMPLES / "regression.json"))
    for fmt in ("json", "html", "junit", "md", "text"):
        assert render(report, fmt)
    with pytest.raises(ValueError):
        render(report, "pdf")
    names = sorted(p.name for p in write_report(report, tmp_path, ("json", "html", "junit", "md")))
    assert names == [
        "simulated-regression.junit.xml",
        "simulated-regression.report.html",
        "simulated-regression.report.json",
        "simulated-regression.report.md",
    ]


# ------------------------------------------------------------------ compatibility with 1.0


@pytest.mark.parametrize("name", ["demo", "regression"])
def test_v1_0_reports_still_load_and_match(name: str) -> None:
    old = load_report(DATA / f"report_v1_0_{name}.json")
    assert old.metadata.report_schema_version == 1
    new = run_suite(load_suite(EXAMPLES / f"{name}.json"))
    assert new.metadata.report_schema_version == 2
    assert new.metadata.run_id == old.metadata.run_id  # run ids are stable across versions
    assert new.status == old.status
    assert [
        (r.id, r.status, r.failure_codes, r.drift.similarity if r.drift else None)
        for r in new.results
    ] == [
        (r.id, r.status, r.failure_codes, r.drift.similarity if r.drift else None)
        for r in old.results
    ]
    assert new.summary.failure_reasons == old.summary.failure_reasons
    for a, b in zip(new.summary.drift, old.summary.drift, strict=True):
        assert a.metric == b.metric and a.n_pairs == b.n_pairs and a.significant == b.significant
        for fld in ("mean_diff", "ci_low", "ci_high", "p_value"):
            x, y = getattr(a, fld), getattr(b, fld)
            assert (x is None) == (y is None)
            if x is not None:
                assert x == pytest.approx(y, rel=1e-9, abs=1e-12)
    # and 1.0 reports can be diffed against 1.1 reports
    assert not diff_reports(old, new).has_regressions


# ------------------------------------------------------------------ stores


def fake_report(name: str, case_text: str = "x") -> Report:
    return run_suite(
        make_suite(
            make_case("a", baseline=case_text, assertions=[{"type": "non_empty"}]), name=name
        )
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    return (
        RunStore(max_runs=5)
        if request.param == "memory"
        else SqliteRunStore(tmp_path / "d" / "r.db", max_runs=5)
    )


def test_store_contract(store) -> None:
    reports = [fake_report(f"s{i % 2}", case_text=f"t{i}") for i in range(4)]
    for r in reports:
        store.add(r)
    listed = store.list()
    assert [r.metadata.run_id for r in listed] == [r.metadata.run_id for r in reversed(reports)]
    assert store.get(reports[0].metadata.run_id) == reports[0]
    assert [r.metadata.suite_name for r in store.list(suite="s1")] == ["s1", "s1"]
    assert len(store.list(limit=2)) == 2 and len(store.list(limit=2, offset=3)) == 1
    assert store.list(suite="nope") == []
    store.delete(reports[0].metadata.run_id)
    with pytest.raises(NotFoundError):
        store.get(reports[0].metadata.run_id)
    with pytest.raises(NotFoundError):
        store.delete("0" * 12)


def test_store_replaces_same_run_and_is_bounded(store) -> None:
    r = fake_report("s")
    store.add(r)
    store.add(r)
    assert len(store.list()) == 1
    for i in range(10):
        store.add(fake_report("s", case_text=f"unique {i}"))
    assert len(store.list()) == 5


def test_sqlite_persists_across_instances_and_resists_injection(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    first = SqliteRunStore(db)
    r = fake_report("persist")
    first.add(r)
    second = SqliteRunStore(db)
    assert second.get(r.metadata.run_id) == r
    assert second.list(suite="x' OR '1'='1") == []
    assert second.list(suite="persist'; DROP TABLE runs; --") == []
    assert len(second.list()) == 1


def test_sqlite_is_thread_safe(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "t.db", max_runs=500)
    errors: list[Exception] = []

    def work(n: int) -> None:
        try:
            for i in range(10):
                store.add(fake_report("t", case_text=f"{n}-{i}"))
                store.list(limit=5)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(store.list()) == 60


# ------------------------------------------------------------------ performance guards


def test_cap_resamples() -> None:
    assert cap_resamples(10, 2000) == 2000
    assert cap_resamples(5000, 2000) == 800
    assert cap_resamples(10_000_000, 2000) == 200  # floor
    assert cap_resamples(5000, 100) == 100  # never above the request
    assert cap_resamples(5000, 2000) == cap_resamples(5000, 2000)


def test_long_text_similarity_is_fast_and_exact_for_identical() -> None:
    a = " ".join(f"w{i % 500}" for i in range(MAX_SEQUENCE_TOKENS * 10))
    b = " ".join(f"w{(i * 7) % 500}" for i in range(MAX_SEQUENCE_TOKENS * 10))
    start = time.perf_counter()
    score = lexical_similarity(a, b)
    assert time.perf_counter() - start < 2.0
    assert 0.0 <= score < 1.0
    assert lexical_similarity(a, a) == 1.0
    assert lexical_similarity(a, a + " extra") < 1.0


def test_large_suite_runs_in_reasonable_time() -> None:
    cases = [
        Case(
            id=f"c{i}",
            assertions=[{"type": "non_empty"}],
            baseline=Response(text=f"answer {i} alpha beta", latency_ms=100 + i % 5),
            candidate=Response(text=f"answer {i} alpha gamma", latency_ms=101 + i % 7),
        )
        for i in range(3000)
    ]
    start = time.perf_counter()
    report = run_suite(Suite(name="big", cases=cases), RunConfig())
    assert time.perf_counter() - start < 15
    assert report.summary.total == 3000
    latency = next(m for m in report.summary.drift if m.metric == "latency_ms")
    assert "reduced" in latency.note


def test_report_json_roundtrip_for_json_file(tmp_path: Path) -> None:
    report = run_suite(load_suite(EXAMPLES / "demo.json"))
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report.model_dump(mode="json")), encoding="utf-8")
    assert load_report(path) == report
