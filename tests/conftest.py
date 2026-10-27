from __future__ import annotations

from pathlib import Path

import pytest

from driftguard.models import Case, Response, Suite

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@pytest.fixture(autouse=True)
def _fixed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")


def make_case(
    case_id: str = "c1",
    baseline: str | None = "hello world",
    candidate: str | None = "hello world",
    **kw,
) -> Case:
    return Case(
        id=case_id,
        baseline=None if baseline is None else Response(text=baseline, **kw.pop("b", {})),
        candidate=None if candidate is None else Response(text=candidate, **kw.pop("c", {})),
        **kw,
    )


def make_suite(*cases: Case, name: str = "t", **kw) -> Suite:
    return Suite(name=name, cases=list(cases), **kw)
