"""Test engine: evaluates suites, aggregates statistics and builds reports."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from . import __version__
from .assertions import evaluate_assertion
from .drift import compute_case_drift, drift_failures
from .errors import DriftGuardError
from .logging_utils import get_logger
from .models import (
    AssertionResult,
    Case,
    CaseResult,
    Fixtures,
    MetricSummary,
    Report,
    Response,
    RunConfig,
    RunMetadata,
    Status,
    Suite,
    Summary,
    Thresholds,
    worst_status,
)
from .similarity import SimilarityFn, get_similarity_fn
from .stats import bootstrap_ci, cap_resamples, paired_bootstrap_ci, paired_permutation_test

log = get_logger("engine")

PREVIEW_CHARS = 300
BOOTSTRAP_METHOD = "percentile bootstrap (resampling cases with replacement)"
TEST_NAME = "paired sign-flip randomization test on the weighted mean difference (two-sided)"


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "..."


def evaluate_case(
    case: Case, thresholds: Thresholds, similarity_fn: SimilarityFn, method: str
) -> CaseResult:
    """Evaluate one case. Never raises: unexpected problems become ERROR results."""
    base = CaseResult(
        id=case.id,
        name=case.name,
        status=Status.PASS,
        weight=case.weight,
        tags=case.tags,
        baseline_preview=_clip(case.baseline.text) if case.baseline else None,
        candidate_preview=_clip(case.candidate.text) if case.candidate else None,
    )
    if case.candidate is None:
        base.status = Status.ERROR
        base.error = "missing candidate response"
        base.failure_codes = ["error:missing_candidate"]
        base.failure_reasons = [base.error]
        return base
    try:
        assertion_results: list[AssertionResult] = [
            evaluate_assertion(spec, case.candidate) for spec in case.assertions
        ]
        base.assertions = assertion_results
        codes: list[str] = []
        reasons: list[str] = []
        for result in assertion_results:
            if not result.passed:
                codes.append(f"assertion:{result.type}")
                reasons.append(f"{result.type}: {result.message}")
        if case.baseline is not None:
            drift = compute_case_drift(
                case.baseline,
                case.candidate,
                thresholds=thresholds,
                similarity_fn=similarity_fn,
                method=method,
            )
            base.drift = drift
            min_sim = (
                case.min_similarity
                if case.min_similarity is not None
                else thresholds.min_similarity
            )
            for code, message in drift_failures(drift, thresholds, min_sim):
                codes.append(code)
                reasons.append(message)
        base.failure_codes, base.failure_reasons = codes, reasons
        if codes:
            base.status = Status.FAIL
        elif not case.assertions and case.baseline is None:
            base.status = Status.INCONCLUSIVE
            base.failure_codes = ["inconclusive:no_checks"]
            base.failure_reasons = ["no assertions and no baseline: nothing was verified"]
        return base
    except DriftGuardError as exc:
        base.status = Status.ERROR
        base.error = str(exc)
    except Exception as exc:  # defensive: one bad case must not abort a batch
        log.exception("unexpected error while evaluating case %s", case.id)
        base.status = Status.ERROR
        base.error = f"unexpected {type(exc).__name__}"
    base.failure_codes = ["error:evaluation"]
    base.failure_reasons = [base.error or "error"]
    return base


def _summarize_metric(
    name: str,
    baseline: list[float],
    candidate: list[float],
    weights: list[float],
    config: RunConfig,
) -> MetricSummary:
    n = len(baseline)
    if n == 0:
        return MetricSummary(metric=name, n_pairs=0, note="no cases with data for this metric")
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
    total_w = sum(weights)
    summary = MetricSummary(
        metric=name,
        n_pairs=n,
        mean_baseline=sum(w * x for w, x in zip(weights, baseline, strict=True)) / total_w,
        mean_candidate=sum(w * x for w, x in zip(weights, candidate, strict=True)) / total_w,
        mean_diff=sum(w * x for w, x in zip(weights, diffs, strict=True)) / total_w,
    )
    notes: list[str] = []
    boot_n = cap_resamples(n, config.bootstrap_resamples)
    perm_n = cap_resamples(n, config.permutation_resamples)
    if boot_n < config.bootstrap_resamples or perm_n < config.permutation_resamples:
        notes.append(f"resamples reduced to {boot_n}/{perm_n} for performance (n={n})")
    if n >= 2:
        ci = paired_bootstrap_ci(
            baseline,
            candidate,
            weights,
            confidence=config.confidence,
            n_resamples=boot_n,
            seed=config.seed,
        )
        summary.ci_low, summary.ci_high = ci.ci_low, ci.ci_high
        summary.confidence, summary.ci_method = ci.confidence, BOOTSTRAP_METHOD
    else:
        notes.append("fewer than 2 pairs: no confidence interval")
    if n >= config.min_pairs:
        perm = paired_permutation_test(
            baseline,
            candidate,
            weights,
            n_resamples=perm_n,
            seed=config.seed,
        )
        summary.p_value = round(perm.p_value, 6)
        summary.test = f"{TEST_NAME}; {perm.method}"
        summary.significant = perm.p_value < config.alpha
        notes.append(f"alpha={config.alpha}; p-values are not corrected for multiple metrics")
    else:
        notes.append(
            f"only {n} pairs (< min_pairs={config.min_pairs}): no hypothesis test performed, "
            "so no significance claim is made"
        )
    summary.note = "; ".join(notes)
    return summary


def _summarize(cases: Sequence[Case], results: list[CaseResult], config: RunConfig) -> Summary:
    counts = Counter(r.status for r in results)
    total = len(results)
    total_weight = sum(r.weight for r in results)
    passed_weight = sum(r.weight for r in results if r.status is Status.PASS)
    reasons: Counter[str] = Counter()
    for result in results:
        reasons.update(result.failure_codes)
    by_id = {r.id: r for r in results}

    metric_sources: dict[str, Callable[[Response], float | None]] = {
        "latency_ms": lambda r: r.latency_ms,
        "total_tokens": lambda r: None if r.total_tokens is None else float(r.total_tokens),
        "cost_usd": lambda r: r.cost_usd,
    }
    drift_summaries: list[MetricSummary] = []

    sims: list[tuple[float, float]] = []
    for case in cases:
        found = by_id.get(case.id)
        if found is not None and found.drift is not None:
            sims.append((found.drift.similarity, case.weight))
    if sims:
        values = [s for s, _ in sims]
        weights = [w for _, w in sims]
        sim_summary = MetricSummary(
            metric="similarity",
            n_pairs=len(values),
            mean_candidate=sum(w * s for s, w in sims) / sum(weights),
            note="weighted mean text similarity to baseline (1.0 = identical); "
            "no hypothesis test is applied to similarity",
        )
        if len(values) >= 2:
            ci = bootstrap_ci(
                values,
                weights,
                confidence=config.confidence,
                n_resamples=cap_resamples(len(values), config.bootstrap_resamples),
                seed=config.seed,
            )
            sim_summary.ci_low, sim_summary.ci_high = ci.ci_low, ci.ci_high
            sim_summary.confidence = ci.confidence
            sim_summary.ci_method = BOOTSTRAP_METHOD
        drift_summaries.append(sim_summary)

    for name, getter in metric_sources.items():
        base_vals: list[float] = []
        cand_vals: list[float] = []
        weights_: list[float] = []
        for case in cases:
            found_result = by_id.get(case.id)
            if (
                found_result is None
                or found_result.status is Status.ERROR
                or case.baseline is None
                or case.candidate is None
            ):
                continue
            b, c = getter(case.baseline), getter(case.candidate)
            if b is None or c is None:
                continue
            base_vals.append(b)
            cand_vals.append(c)
            weights_.append(case.weight)
        drift_summaries.append(_summarize_metric(name, base_vals, cand_vals, weights_, config))

    return Summary(
        total=total,
        passed=counts[Status.PASS],
        failed=counts[Status.FAIL],
        errors=counts[Status.ERROR],
        inconclusive=counts[Status.INCONCLUSIVE],
        pass_rate=(counts[Status.PASS] / total) if total else None,
        weighted_pass_rate=(passed_weight / total_weight) if total else None,
        failure_reasons=dict(sorted(reasons.items())),
        drift=drift_summaries,
    )


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _timestamp() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        moment = datetime.fromtimestamp(int(epoch), tz=UTC)
    else:
        moment = datetime.now(tz=UTC).replace(microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def run_suite(suite: Suite, config: RunConfig | None = None) -> Report:
    """Run every case in ``suite`` and return a complete :class:`Report`.

    Results are deterministic: the same suite and config always produce the same
    statuses, statistics and run id. ``generated_at`` honours ``SOURCE_DATE_EPOCH``.
    """
    config = config or RunConfig()
    similarity_fn = get_similarity_fn(config.similarity)
    log.info("running suite %r with %d cases", suite.name, len(suite.cases))
    results = [
        evaluate_case(case, suite.thresholds, similarity_fn, config.similarity)
        for case in suite.cases
    ]
    summary = _summarize(suite.cases, results, config)
    status = worst_status(r.status for r in results)
    suite_hash = hashlib.sha256(
        _canonical(suite.model_dump(mode="json", by_alias=True)).encode("utf-8")
    ).hexdigest()
    run_hash = hashlib.sha256(
        (suite_hash + _canonical(config.model_dump(mode="json"))).encode("utf-8")
    ).hexdigest()
    metadata = RunMetadata(
        driftguard_version=__version__,
        run_id=run_hash[:12],
        generated_at=_timestamp(),
        suite_name=suite.name,
        suite_version=suite.version,
        suite_description=suite.description,
        suite_sha256=suite_hash,
        report_schema_version=2,
        config=config,
        thresholds=suite.thresholds,
    )
    return Report(metadata=metadata, status=status, summary=summary, results=results)


def run_batch(suites: Sequence[Suite], config: RunConfig | None = None) -> list[Report]:
    """Run several suites. A failure to run one suite raises; use the CLI for isolation."""
    return [run_suite(suite, config) for suite in suites]


def aggregate_status(reports: Sequence[Report]) -> Status:
    return worst_status(r.status for r in reports)


def compare_fixtures(baseline: Fixtures, candidate: Fixtures, suite: Suite | None = None) -> Suite:
    """Build a runnable suite from two fixture files (optionally using a suite's assertions).

    With a suite: its cases (assertions, weights, thresholds) are kept and responses come
    from the fixtures; ids missing from the candidate fixtures become ERROR cases.
    Without one: every id found in either fixture file becomes a case that must be non-empty.
    """
    if suite is not None:
        cases = [
            case.model_copy(
                update={
                    "baseline": baseline.responses.get(case.id),
                    "candidate": candidate.responses.get(case.id),
                }
            )
            for case in suite.cases
        ]
        return suite.model_copy(update={"name": f"compare: {suite.name}", "cases": cases})
    ids = list(dict.fromkeys([*baseline.responses, *candidate.responses]))
    cases = [
        Case.model_validate(
            {
                "id": case_id,
                "assertions": [{"type": "non_empty"}],
                "baseline": baseline.responses.get(case_id),
                "candidate": candidate.responses.get(case_id),
            }
        )
        for case_id in ids
    ]
    label = f"{baseline.name or 'baseline'} vs {candidate.name or 'candidate'}"
    return Suite(name=f"compare: {label}", cases=cases)


__all__ = [
    "aggregate_status",
    "compare_fixtures",
    "evaluate_case",
    "run_batch",
    "run_suite",
]
