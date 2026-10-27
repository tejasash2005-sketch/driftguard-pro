from __future__ import annotations

import json
from pathlib import Path

import pytest

from driftguard.api import EXAMPLES_DIR
from driftguard.cli import main
from driftguard.engine import run_suite
from driftguard.loader import load_suite
from driftguard.models import Status

from .conftest import EXAMPLES


def test_packaged_examples_match_root_examples() -> None:
    root_files = sorted(p.name for p in EXAMPLES.glob("*.json"))
    assert root_files == sorted(p.name for p in EXAMPLES_DIR.glob("*.json"))
    for name in root_files:
        assert (EXAMPLES / name).read_bytes() == (EXAMPLES_DIR / name).read_bytes(), name


@pytest.mark.parametrize(("name", "status"), [("demo", Status.PASS), ("regression", Status.FAIL)])
def test_example_suites(name: str, status: Status) -> None:
    report = run_suite(load_suite(EXAMPLES / f"{name}.json"))
    assert report.status is status
    assert report.summary.total >= 5


def test_regression_example_shows_variety_of_failures() -> None:
    report = run_suite(load_suite(EXAMPLES / "regression.json"))
    assert 0 < report.summary.passed < report.summary.total
    assert {c.split(":")[0] for c in report.summary.failure_reasons} >= {"assertion", "drift"}


def test_run_all_examples_via_cli_directory_is_handled(tmp_path: Path) -> None:
    # A directory mixing suites with fixtures/configs reports ERROR for the non-suite files.
    assert main(["run", str(EXAMPLES)]) == 2
    assert main(["run", str(EXAMPLES / "demo.json"), str(EXAMPLES / "regression.json")]) == 1


def test_example_files_are_valid_json() -> None:
    for path in EXAMPLES.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
