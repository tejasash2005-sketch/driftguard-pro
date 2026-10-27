"""Repeatable local timing probes for representative DriftGuard workloads.

Run with ``python benchmarks/benchmark_core.py`` from the repository root. Results are
measurements for the current machine, not portable performance guarantees.
"""

from __future__ import annotations

import json
import platform
import sys
import time
import tracemalloc

from driftguard.engine import run_suite
from driftguard.models import Case, Response, RunConfig, Suite
from driftguard.similarity import lexical_similarity


def benchmark_suites() -> list[dict[str, int | float]]:
    measurements = []
    for count in (100, 1_000, 5_000):
        cases = [
            Case(
                id=f"case-{index}",
                assertions=[{"type": "non_empty"}],
                baseline=Response(text=f"expected answer {index}", latency_ms=100),
                candidate=Response(text=f"expected answer {index}", latency_ms=101),
            )
            for index in range(count)
        ]
        suite = Suite(name=f"benchmark-{count}", cases=cases)
        tracemalloc.start()
        try:
            started = time.perf_counter()
            report = run_suite(suite, RunConfig())
            elapsed = time.perf_counter() - started
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        measurements.append(
            {
                "cases": count,
                "seconds": round(elapsed, 6),
                "peak_traced_bytes": peak_bytes,
                "status": report.status.value,
            }
        )
    return measurements


def benchmark_text() -> list[dict[str, int | float]]:
    measurements = []
    for token_count in (500, 2_000, 20_000):
        left = " ".join(f"word-{index % 997}" for index in range(token_count))
        right = left[:-1] + "x"
        tracemalloc.start()
        try:
            started = time.perf_counter()
            score = lexical_similarity(left, right)
            elapsed = time.perf_counter() - started
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        measurements.append(
            {
                "tokens_per_input": token_count,
                "characters_per_input": len(left),
                "seconds": round(elapsed, 6),
                "peak_traced_bytes": peak_bytes,
                "similarity": score,
            }
        )
    return measurements


def main() -> None:
    result = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "suite_runs": benchmark_suites(),
        "lexical_similarity": benchmark_text(),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
