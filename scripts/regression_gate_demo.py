"""Run an offline end-to-end demonstration of the report regression gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "regression-gate"
FORMATS = "json,junit,md"


def run_cli(*args: str, expected: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    source = str(ROOT / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "driftguard.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != expected:
        raise RuntimeError(
            f"driftguard {' '.join(args)} exited {result.returncode}; expected {expected}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="driftguard-gate-") as temp:
        output = Path(temp)
        reports: dict[str, Path] = {}
        for label, expected_status in (
            ("baseline", 0),
            ("candidate-acceptable", 0),
            ("candidate-degraded", 1),
        ):
            suite = FIXTURES / f"{label}.json"
            folder = output / label
            run_cli(
                "run",
                str(suite),
                "--out-dir",
                str(folder),
                "--formats",
                FORMATS,
                expected=expected_status,
            )
            report_path = folder / "regression-gate-demo.report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            reports[label] = report_path
            junit = ET.parse(folder / "regression-gate-demo.junit.xml").getroot()
            markdown = (folder / "regression-gate-demo.report.md").read_text(encoding="utf-8")
            if report["status"] != ("FAIL" if expected_status else "PASS"):
                raise RuntimeError(f"unexpected {label} report status: {report['status']}")
            if junit.get("tests") != "1" or "DriftGuard" not in markdown:
                raise RuntimeError(f"missing or invalid JSON/JUnit/Markdown outputs for {label}")
            print(f"{label}: {report['status']} (run exit {expected_status})")

        passing = run_cli(
            "diff",
            str(reports["baseline"]),
            str(reports["candidate-acceptable"]),
            expected=0,
        )
        print("baseline -> acceptable candidate: PASS (diff exit 0)")
        degraded = run_cli(
            "diff",
            str(reports["baseline"]),
            str(reports["candidate-degraded"]),
            expected=1,
        )
        failed = json.loads(reports["candidate-degraded"].read_text(encoding="utf-8"))
        causes = failed["results"][0]["failure_codes"]
        required = {"assertion:contains", "drift:similarity", "drift:latency"}
        if not required.issubset(causes):
            raise RuntimeError(f"degraded candidate did not trip expected checks: {causes}")
        for cause in sorted(required):
            print(f"degraded cause: {cause}")
        if "REGRESSIONS FOUND" not in degraded.stdout:
            raise RuntimeError("degraded diff output did not explain the regression verdict")
        if "no regressions" not in passing.stdout:
            raise RuntimeError("acceptable diff output did not report a passing gate")
        print("baseline -> degraded candidate: FAIL as expected (diff exit 1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
