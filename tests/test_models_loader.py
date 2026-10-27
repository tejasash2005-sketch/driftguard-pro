from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from driftguard.errors import SuiteLoadError
from driftguard.loader import (
    discover_suites,
    load_fixtures,
    load_report,
    load_simulator_config,
    load_suite,
)
from driftguard.models import Response, Status, Suite, worst_status


def test_status_exit_codes() -> None:
    assert [s.exit_code for s in (Status.PASS, Status.FAIL, Status.ERROR, Status.INCONCLUSIVE)] == [
        0,
        1,
        2,
        3,
    ]


def test_worst_status_priority() -> None:
    assert worst_status([]) is Status.INCONCLUSIVE
    assert worst_status([Status.PASS]) is Status.PASS
    assert worst_status([Status.PASS, Status.INCONCLUSIVE]) is Status.INCONCLUSIVE
    assert worst_status([Status.INCONCLUSIVE, Status.FAIL]) is Status.FAIL
    assert worst_status([Status.FAIL, Status.ERROR, Status.PASS]) is Status.ERROR


def test_response_validation() -> None:
    assert Response(prompt_tokens=3, completion_tokens=4).total_tokens == 7
    assert Response().total_tokens is None
    assert Response(completion_tokens=2).total_tokens == 2
    for bad in (
        {"latency_ms": -1},
        {"latency_ms": float("inf")},
        {"latency_ms": float("nan")},
        {"prompt_tokens": -1},
        {"cost_usd": -0.1},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            Response(**bad)


def test_suite_validation() -> None:
    with pytest.raises(ValidationError, match="duplicate case id"):
        Suite.model_validate({"name": "s", "cases": [{"id": "a"}, {"id": "a"}]})
    with pytest.raises(ValidationError):
        Suite.model_validate({"name": "", "cases": []})
    with pytest.raises(ValidationError):
        Suite.model_validate({"name": "s", "cases": [{"id": "a", "weight": 0}]})
    with pytest.raises(ValidationError):
        Suite.model_validate({"name": "s", "thresholds": {"min_similarity": 1.5}})


def write(tmp: Path, name: str, content: str | bytes) -> Path:
    p = tmp / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return p


def test_load_suite_ok_and_bom(tmp_path: Path) -> None:
    body = json.dumps({"name": "s", "cases": [{"id": "a"}]})
    assert load_suite(write(tmp_path, "s.json", body)).name == "s"
    assert load_suite(write(tmp_path, "bom.json", b"\xef\xbb\xbf" + body.encode())).name == "s"


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError, match="file not found"):
        load_suite(tmp_path / "nope.json")


def test_load_directory_instead_of_file(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError, match="directory"):
        load_suite(tmp_path)


def test_load_malformed_json(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError, match=r"malformed JSON.*line 1"):
        load_suite(write(tmp_path, "bad.json", '{"name": '))


def test_load_invalid_utf8(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError, match="UTF-8"):
        load_suite(write(tmp_path, "bin.json", b"\xff\xfe\x00\x01"))


def test_load_schema_errors_are_readable(tmp_path: Path) -> None:
    p = write(tmp_path, "s.json", json.dumps({"name": "s", "cases": [{"id": "a", "weight": -1}]}))
    with pytest.raises(SuiteLoadError, match=r"invalid suite.*cases\.0\.weight"):
        load_suite(p)
    with pytest.raises(SuiteLoadError, match="invalid suite"):
        load_suite(write(tmp_path, "list.json", "[]"))


def test_load_deeply_nested_json(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError):
        load_suite(write(tmp_path, "deep.json", "[" * 100000 + "]" * 100000))


def test_load_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("driftguard.loader.MAX_FILE_BYTES", 10)
    with pytest.raises(SuiteLoadError, match="too large"):
        load_suite(write(tmp_path, "big.json", json.dumps({"name": "s", "cases": []})))


def test_other_loaders(tmp_path: Path) -> None:
    fx = write(tmp_path, "f.json", json.dumps({"name": "x", "responses": {"a": {"text": "hi"}}}))
    assert load_fixtures(fx).responses["a"].text == "hi"
    with pytest.raises(SuiteLoadError, match="invalid fixtures"):
        load_fixtures(write(tmp_path, "f2.json", "{}"))
    with pytest.raises(SuiteLoadError, match="simulator config"):
        load_simulator_config(write(tmp_path, "s.json", json.dumps({"cases": []})))
    with pytest.raises(SuiteLoadError, match="invalid report"):
        load_report(write(tmp_path, "r.json", "{}"))


def test_discover_suites(tmp_path: Path) -> None:
    (tmp_path / "b.json").write_text("{}")
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "ignore.txt").write_text("x")
    assert [p.name for p in discover_suites([tmp_path])] == ["a.json", "b.json"]
    assert discover_suites(["x.json"]) == [Path("x.json")]
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SuiteLoadError, match="no .json"):
        discover_suites([empty])
