"""Per-case drift computation: text, JSON structure, latency, tokens and cost."""

from __future__ import annotations

from .jsonutil import diff_json, try_parse_json
from .models import CaseDrift, DriftMetric, JsonDiff, Response, Thresholds
from .similarity import SimilarityFn


def pct_change(baseline: float, candidate: float) -> float | None:
    """Percent change relative to baseline; ``None`` when the baseline is zero."""
    if baseline <= 0:
        return None
    return round((candidate - baseline) / baseline * 100.0, 6)


def _metric(
    name: str, baseline: float | None, candidate: float | None, threshold_pct: float | None
) -> DriftMetric | None:
    if baseline is None or candidate is None:
        return None
    pct = pct_change(baseline, candidate)
    exceeded = pct is not None and threshold_pct is not None and pct > threshold_pct
    return DriftMetric(
        name=name,
        baseline=baseline,
        candidate=candidate,
        change=round(candidate - baseline, 9),
        pct_change=pct,
        threshold_pct=threshold_pct,
        exceeded=exceeded,
    )


def compute_case_drift(
    baseline: Response,
    candidate: Response,
    *,
    thresholds: Thresholds,
    similarity_fn: SimilarityFn,
    method: str,
) -> CaseDrift:
    similarity = similarity_fn(baseline.text, candidate.text)
    ok_b, value_b = try_parse_json(baseline.text)
    ok_c, value_c = try_parse_json(candidate.text)
    json_diff: JsonDiff | None = None
    if ok_b or ok_c:
        json_diff = JsonDiff(baseline_valid=ok_b, candidate_valid=ok_c)
        if ok_b and ok_c:
            result = diff_json(value_b, value_c)
            json_diff.added = result.added
            json_diff.removed = result.removed
            json_diff.type_changed = result.type_changed
            json_diff.value_changed = result.value_changed
    candidates = (
        _metric(
            "latency_ms",
            baseline.latency_ms,
            candidate.latency_ms,
            thresholds.max_latency_increase_pct,
        ),
        _metric(
            "total_tokens",
            baseline.total_tokens,
            candidate.total_tokens,
            thresholds.max_token_increase_pct,
        ),
        _metric(
            "cost_usd", baseline.cost_usd, candidate.cost_usd, thresholds.max_cost_increase_pct
        ),
    )
    return CaseDrift(
        similarity=similarity,
        similarity_method=method,
        text_changed=baseline.text != candidate.text,
        json_diff=json_diff,
        metrics=[m for m in candidates if m is not None],
    )


def drift_failures(
    drift: CaseDrift, thresholds: Thresholds, min_similarity: float
) -> list[tuple[str, str]]:
    """Return ``(code, message)`` pairs for every threshold the drift violates."""
    failures: list[tuple[str, str]] = []
    if drift.similarity < min_similarity:
        failures.append(
            (
                "drift:similarity",
                f"text similarity {drift.similarity:.3f} is below the minimum {min_similarity:.3f}",
            )
        )
    diff = drift.json_diff
    if diff is not None:
        if thresholds.fail_on_json_structure_change and diff.structure_changed:
            if diff.baseline_valid and not diff.candidate_valid:
                detail = "candidate output is no longer valid JSON"
            elif diff.candidate_valid and not diff.baseline_valid:
                detail = "candidate output became JSON but baseline was not"
            else:
                parts = []
                if diff.removed:
                    parts.append("removed " + ", ".join(diff.removed[:5]))
                if diff.added:
                    parts.append("added " + ", ".join(diff.added[:5]))
                if diff.type_changed:
                    parts.append("type changed " + ", ".join(diff.type_changed[:5]))
                detail = "; ".join(parts)
            failures.append(("drift:json_structure", f"JSON structure changed: {detail}"))
        if thresholds.fail_on_json_value_change and diff.value_changed:
            failures.append(
                (
                    "drift:json_value",
                    "JSON values changed at " + ", ".join(diff.value_changed[:5]),
                )
            )
    labels = {"latency_ms": "latency", "total_tokens": "tokens", "cost_usd": "cost"}
    for metric in drift.metrics:
        if metric.exceeded and metric.pct_change is not None:
            failures.append(
                (
                    f"drift:{labels[metric.name]}",
                    f"{labels[metric.name]} increased {metric.pct_change:.1f}% "
                    f"(limit {metric.threshold_pct:.1f}%)",
                )
            )
    return failures
