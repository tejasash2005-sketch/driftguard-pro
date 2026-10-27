# DriftGuard Pro 1.1.0 initial audit

This initial snapshot audit is retained for history. It is superseded by
[`FINAL_QUALITY_AUDIT.md`](FINAL_QUALITY_AUDIT.md), which records the continued 1.1.2 work and
current verification state.

Initial inspection of the supplied source tree, before code changes.

## Verified

- A Python package under `src/driftguard` exposes the `driftguard` CLI, FastAPI app, deterministic simulator, lexical/optional embedding similarity, assertion engine, baseline drift thresholds, statistical summaries, JSON/HTML/JUnit/Markdown rendering, and bounded in-memory/SQLite stores.
- Pydantic models enforce most suite/input bounds; JSON loading caps files at 25 MiB. The API has bearer-token middleware, a request-body cap, CSP headers, and generic handling for unexpected exceptions.
- Tests cover the main engine, report formats, API/auth, providers via mocks, property cases, and compatibility with 1.0 report fixtures.

## Findings to address

- `diff` currently trusts each report independently, silently collapses duplicate case IDs, and does not reject comparisons across different suite identities or unsupported report schema versions. The CI workflow has only an identical-report diff smoke command and no explicit degraded-candidate gate assertion.
- `write_report` names output from suite name alone, so multiple reports for one suite in a batch overwrite each other.
- The README has a CI artifact-download example that permits a missing baseline and then invokes `diff`; the gate should fail closed if the baseline is absent.
- The supplied environment reports Python 3.10.11, while package metadata requires Python >=3.11. Ruff, mypy, build, and pytest-cov are not installed. `py` launcher execution is denied. Docker and `pip-audit` commands are present but their daemon/network availability is unverified.
- There is no `.git` directory in the supplied project, so no branch or Git checkpoint is available.

## Security and reliability notes

- Existing API authentication is one shared bearer token; public health/config endpoints disclose only health/version and auth/persistence booleans. This is not per-user authorization. SQLite uses parameterized queries and WAL, but concurrency and filesystem permissions still depend on the host.
- Optional provider adapters need tests with mocked clients; live services and credentials are not established by this audit.
- Dashboard assets are served locally and browser-side rendering uses DOM text APIs; browser automation availability is unknown.

## Completion plan

Make report comparison fail closed for incompatible/corrupt inputs, add CLI regression-gate tests with a deliberately degraded candidate, ensure batch report output does not overwrite same-name runs, make the CI smoke workflow cross-platform and artifact download mandatory wherever diff is used, then run every check supported by the actual environment and package a clean ZIP.

## Changes made and verification

- Updated `diff_reports` to reject suite name/version mismatches, duplicate case IDs, and unknown report schema versions. Removed cases now make `has_regressions` true.
- Added tests for removed cases, malformed/incompatible comparison data, and same-suite report output collisions. The existing `test_cli_diff` covers identical, degraded, improved, missing-report, JSON, and Markdown CLI outcomes; CI now runs it as an explicit gate step.
- Updated CI smoke steps to PowerShell, made the expected degraded fixture exit code explicit, and corrected README gate instructions.
- Added `benchmarks/benchmark_core.py` for repeatable small/medium/large suite and text probes. It was not run because no supported Python runtime is available.
- `python -m compileall -q src tests benchmarks`: PASS on Python 3.10 (syntax compilation only; not an application test).
- `python -m pip install -e '.[dev]'`: NOT RUN to completion; PyPI access was denied while fetching build dependencies. This machine's default Python is 3.10.11, below `requires-python >=3.11`.
- `uv python install 3.11`: NOT RUN to completion; download access was denied. An apparent Python 3.11 directory has no interpreter executable.
- `python -m pytest -q --cov` with `PYTHONPATH=src`: NOT RUN; collection stops because Python 3.10 does not provide `enum.StrEnum`.
- Ruff, mypy, build, and coverage packages are unavailable in the active interpreter. Docker is installed but its daemon is unavailable. `pip-audit` is installed, but its PyPI vulnerability-service request was denied by network policy.
- No test count or coverage percentage is reported because pytest could not collect the suite. No wheel/sdist, provider live test, Docker run, or benchmark measurement is claimed.
