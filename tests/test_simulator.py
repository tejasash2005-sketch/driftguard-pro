from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from driftguard.engine import run_suite
from driftguard.models import Status
from driftguard.simulator import SimulatorConfig, derive_seed, simulate

from .conftest import EXAMPLES


def cfg(**kw) -> SimulatorConfig:
    base = {
        "seed": 1,
        "cases": [
            {
                "id": "a",
                "base_text": "one two three four five six seven eight",
                "weight": 2,
                "assertions": [{"type": "non_empty"}],
            },
            {"id": "j", "base_text": '{"k": "some words here", "n": 1}'},
        ],
        "regressions": [],
    }
    base.update(kw)
    return SimulatorConfig.model_validate(base)


def test_same_seed_same_output() -> None:
    config = cfg(
        regressions=[
            {"kind": "text_drift", "probability": 0.5},
            {"kind": "latency", "probability": 0.5},
        ]
    )
    assert simulate(config).model_dump_json() == simulate(config).model_dump_json()
    a = run_suite(simulate(config)).model_dump_json()
    assert a == run_suite(simulate(config)).model_dump_json()


def test_different_seed_differs() -> None:
    a = simulate(cfg(seed=1)).cases[0].baseline
    b = simulate(cfg(seed=2)).cases[0].baseline
    assert a is not None and b is not None and a.latency_ms != b.latency_ms


def test_case_order_does_not_change_individual_results() -> None:
    forward = {c.id: c.candidate for c in simulate(cfg()).cases}
    config = cfg()
    config.cases.reverse()
    backward = {c.id: c.candidate for c in simulate(config).cases}
    assert forward == backward


def test_derive_seed_is_stable() -> None:
    assert derive_seed(1, "a", "baseline") == derive_seed(1, "a", "baseline")
    assert derive_seed(1, "a", "baseline") != derive_seed(1, "a", "candidate")


def test_no_regressions_means_no_failures() -> None:
    report = run_suite(simulate(cfg(noise=0.05)))
    assert report.status is Status.PASS


def test_each_regression_kind_is_applied_and_detected() -> None:
    expectations = {
        "latency": "drift:latency",
        "tokens": "drift:tokens",
        "cost": "drift:cost",
        "empty": "assertion:non_empty",
        "text_drift": "drift:similarity",
        "json_break": "drift:json_structure",
    }
    for kind, code in expectations.items():
        config = cfg(
            noise=0.0,
            regressions=[
                {
                    "kind": kind,
                    "probability": 1.0,
                    "magnitude": 1.5 if kind != "text_drift" else 1.0,
                }
            ],
        )
        report = run_suite(simulate(config))
        codes = {c for r in report.results for c in r.failure_codes}
        assert code in codes, (kind, codes)
        for case in simulate(config).cases:
            assert case.candidate and kind in case.candidate.metadata["simulated_regressions"]


def test_probability_zero_and_case_targeting() -> None:
    never = simulate(cfg(regressions=[{"kind": "empty", "probability": 0.0}]))
    assert all(c.candidate and c.candidate.text for c in never.cases)
    targeted = simulate(cfg(regressions=[{"kind": "empty", "probability": 1.0, "case_ids": ["a"]}]))
    by_id = {c.id: c for c in targeted.cases}
    assert by_id["a"].candidate and by_id["a"].candidate.text == ""
    assert by_id["j"].candidate and by_id["j"].candidate.text != ""


def test_weights_are_carried_into_the_suite_and_pass_rate() -> None:
    config = cfg(noise=0.0, regressions=[{"kind": "empty", "probability": 1.0, "case_ids": ["a"]}])
    suite = simulate(config)
    assert {c.id: c.weight for c in suite.cases} == {"a": 2.0, "j": 1.0}
    summary = run_suite(suite).summary
    assert summary.weighted_pass_rate == pytest.approx(1 / 3)
    assert summary.pass_rate == 0.5


def test_json_text_drift_keeps_json_valid() -> None:
    suite = simulate(
        cfg(noise=0.0, regressions=[{"kind": "text_drift", "probability": 1.0, "magnitude": 1.0}])
    )
    candidate = {c.id: c for c in suite.cases}["j"].candidate
    assert candidate is not None
    assert set(json.loads(candidate.text)) == {"k", "n"}


def test_config_validation() -> None:
    for bad in (
        {"cases": []},
        {"cases": [{"id": "a"}]},
        {"cases": [{"id": "a", "base_text": "x"}], "noise": 2},
        {"cases": [{"id": "a", "base_text": "x"}], "regressions": [{"kind": "bogus"}]},
        {
            "cases": [{"id": "a", "base_text": "x"}],
            "regressions": [{"kind": "empty", "probability": 2}],
        },
    ):
        with pytest.raises(ValidationError):
            SimulatorConfig.model_validate(bad)


def test_example_simulator_config_is_deterministic() -> None:
    config = SimulatorConfig.model_validate(json.loads((EXAMPLES / "simulator.json").read_text()))
    generated = simulate(config).model_dump(mode="json", by_alias=True)
    stored = json.loads((EXAMPLES / "regression.json").read_text())
    assert generated == stored  # the shipped regression.json is exactly the seeded output
