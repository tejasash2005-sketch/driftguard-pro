from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from driftguard.engine import run_suite
from driftguard.logging_utils import configure_logging, get_logger, redact
from driftguard.models import Case, Report, Response, Suite
from driftguard.reports import render_html, render_text, report_to_json, slugify, write_report

from .conftest import make_case, make_suite


def sample_report() -> Report:
    ok = make_case(
        "ok", assertions=[{"type": "non_empty"}], b={"latency_ms": 10}, c={"latency_ms": 11}
    )
    bad = make_case("bad", candidate="", assertions=[{"type": "non_empty"}])
    return run_suite(make_suite(ok, bad, name="Report Suite"))


def test_json_report_round_trip_and_metadata() -> None:
    report = sample_report()
    data = json.loads(report_to_json(report))
    assert Report.model_validate(data) == report
    meta = data["metadata"]
    assert meta["suite_name"] == "Report Suite" and len(meta["run_id"]) == 12
    assert meta["config"]["seed"] == 0 and meta["generated_at"].endswith("Z")
    assert data["summary"]["total"] == 2 and data["results"][1]["failure_reasons"]


def test_json_report_is_byte_reproducible() -> None:
    assert report_to_json(sample_report()) == report_to_json(sample_report())


def test_html_report_content_and_escaping() -> None:
    evil = Case(
        id="<script>alert(1)</script>",
        assertions=[{"type": "exact_match", "expected": "<img src=x onerror=alert(1)>"}],
        candidate=Response(text="nope"),
    )
    page = render_html(run_suite(Suite(name="<b>x</b>", cases=[evil])))
    assert "<script>alert(1)</script>" not in page and "<img src=x" not in page
    assert "&lt;script&gt;" in page and "&lt;b&gt;x&lt;/b&gt;" in page
    html = render_html(sample_report())
    assert (
        "FAIL" in html
        and "Drift summary" in html
        and "Report Suite" in html
        and "prefers-color-scheme" in html
    )


def test_text_report() -> None:
    text = render_text(sample_report())
    assert "Status: FAIL" in text and "[FAIL" in text and "assertion:non_empty" in text


def test_write_report_files(tmp_path: Path) -> None:
    paths = write_report(sample_report(), tmp_path / "out")
    assert sorted(p.name for p in paths) == ["report-suite.report.html", "report-suite.report.json"]
    assert all(p.read_text(encoding="utf-8") for p in paths)
    with pytest.raises(ValueError):
        write_report(sample_report(), tmp_path, ("pdf",))


def test_slugify() -> None:
    assert slugify("../../etc/passwd") == "etc-passwd"
    assert slugify("???") == "report"
    assert slugify("Demo Bot v1.2") == "demo-bot-v1.2"


def test_redaction_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SERVICE_API_KEY", "supersecretvalue123")
    assert "supersecretvalue123" not in redact("token is supersecretvalue123 ok")
    assert "sk-abcdefghijklmnop" not in redact("key sk-abcdefghijklmnop leaked")
    assert "abcdefgh12345678" not in redact("Authorization: Bearer abcdefgh12345678")
    assert "hunter2hunter2" not in redact('{"api_key": "hunter2hunter2"}')
    assert redact("nothing secret here") == "nothing secret here"


def test_logger_never_emits_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890abcdef")
    stream = io.StringIO()
    configure_logging(2, stream)
    log = get_logger("test")
    log.info("using key %s", "sk-test-1234567890abcdef")
    try:
        raise RuntimeError("boom sk-test-1234567890abcdef")
    except RuntimeError:
        log.exception("failed")
    out = stream.getvalue()
    assert "sk-test-1234567890abcdef" not in out and "[REDACTED]" in out
    configure_logging(0, io.StringIO())
    assert logging.getLogger("driftguard").level == logging.WARNING
