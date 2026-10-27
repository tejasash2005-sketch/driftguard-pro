# DriftGuard Pro 1.1.2 — final quality audit

The latest supported-runtime and packaging attempts are documented in
[`FINAL_VERIFICATION_REPORT.md`](FINAL_VERIFICATION_REPORT.md); that report supersedes the earlier
runtime-availability statements below.

## Scope and evidence

Reviewed package metadata, CLI, loaders/models, engine, similarity/statistics, report renderers,
provider adapters, FastAPI routes/middleware, SQLite and in-memory stores, dashboard assets, tests,
examples, Dockerfile, workflows, README, changelog, and release archive. Findings below distinguish
static review from commands actually run. The supplied project has no `.git` directory.

## Implemented in this continuation

- Added a self-contained offline regression-gate demo using synthetic suite files. It runs baseline,
  acceptable and degraded evaluations, generates JSON/JUnit/Markdown for each, checks run exit codes,
  diffs baseline against both candidates, and asserts that the degraded run records assertion,
  similarity and latency failures. No credentials, API calls, or network access are used.
- CI now runs that demo and the existing CLI gate tests on Python 3.11/3.12, Ubuntu/Windows.
- Added a bounded `DRIFTGUARD_PROVIDER_TIMEOUT` (0.1–300 seconds, default 30 seconds) and disabled
  SDK retries for optional OpenAI and Anthropic calls. Added mocked tests for the setting and invalid
  values. Core workflows remain local and provider-free.
- Fixed the README CI snippet, documented the offline demo, optional provider timeout, architecture,
  outbound-data behavior and a repeatable benchmark command. Updated package metadata to version
  1.1.2 and SPDX MIT metadata; the build-system minimum is 77 for SPDX license support.
- Added CLI coverage for malformed and incompatible diff inputs. Earlier changes include strict
  suite/schema/case-ID compatibility checks, removed-case regression handling, and non-overwriting
  same-suite report output.

## Signature regression demo

`examples/regression-gate/` contains a healthy baseline, a candidate that stays above the similarity
and latency thresholds, and a candidate that fails the required-content assertion, similarity floor,
and latency budget. `scripts/regression_gate_demo.py` asserts the expected `run` exit codes (0, 0, 1),
then asserts `diff` returns 0 for the acceptable report and 1 for the degraded report. It validates
all three output formats and prints the failure codes. The script is wired into CI and pytest. In
the final sprint it was attempted under Python 3.12, but stopped before evaluating data because the
clean environment could not install Pydantic.

## Production-oriented review

- **Inputs and resource bounds:** Pydantic limits suites, case counts, and text lengths; file loading
  caps JSON files at 25 MiB; API requests are capped at 10 MiB by default. JSON Schema remote `$ref`
  resolution is not enabled. Pathological local regular expressions can still consume CPU.
- **Regression meaning:** verdicts use configured assertions and deterministic thresholds. Lexical
  similarity is a surface-text measure, not semantic understanding. Statistical intervals/tests
  quantify uncertainty and do not determine case pass/fail; p-values are not multiple-test corrected.
- **API security:** optional single shared bearer token protects API routes other than health/config;
  comparison and deletion require that token when configured. This is not user-level IAM. There is no
  built-in rate limiting; use a trusted reverse proxy and TLS before exposing it remotely.
- **Persistence:** SQLite uses parameterized statements, WAL and per-instance locks, with a bounded
  run count. Local file permissions, backups and multi-process deployment remain operator concerns.
- **Providers and data egress:** provider integrations are optional. Core evaluation does not transmit
  inputs. Explicit `record` use sends prompts to the configured paid/credentialed provider; provider
  outputs can contain sensitive data and should be treated accordingly. No live integration was run.
- **Dashboard:** local assets, CSP and text-safe DOM usage are present; API/dashboard integration
  tests exist. No real browser automation test or browser run is available in this environment.
- **Dependencies and licenses:** required dependencies and optional SDKs are declared in
  `pyproject.toml`; project license is MIT. A vulnerability/license audit could not contact its
  service, so no clean audit result is claimed. Dependencies are range-constrained, not hash-locked.
- **CI:** workflows cover Ubuntu/Windows and Python 3.11/3.12; the Docker job builds on Ubuntu. The
  local Docker daemon is unavailable, so workflow execution is not established by this audit.

## Quality rubric and current evidence rating

This is an evidence-readiness rubric, not a claim of production certification. Full points require
both source inspection and successful supported-runtime checks.

| Area | Weight | Evidence now | Gap to full credit |
|---|---:|---|---|
| Core evaluation and bounded inputs | 20 | 16 | Main suite could not execute here |
| Regression gate and report behavior | 20 | 15 | New end-to-end script is present but unexecuted |
| Tests, coverage, lint and typing | 20 | 5 | Full pytest, coverage, Ruff and mypy unavailable |
| API, security and persistence | 15 | 10 | Static review and prior tests only; no supported runtime/browser run |
| Packaging and installation | 10 | 7 | wheel/sdist contents verified; supported-runtime install unavailable |
| Documentation and usability | 10 | 8 | Commands mostly map to implementation; not all can be run here |
| Performance evidence | 5 | 2 | Benchmark script exists; no measurements available |
| **Evidence readiness** | **100** | **63** | **95 target is not justified by available verification** |

## Commands actually run

- `python -m compileall -q src tests benchmarks scripts` — **PASS** on Python 3.10.11; syntax only.
- `pytest tests/test_providers.py` with an in-process `StrEnum` compatibility shim — **11 passed**.
  This provider-mock subset does not exercise live services and is not a supported-runtime run.
- Provider mock tests via `pytest` with an in-process `StrEnum` compatibility shim — **11 passed**.
  This is a Python 3.10 diagnostic, not a supported Python test run.
- Full `pytest -q` with the same shim — **NOT COLLECTED**: collection encountered missing
  `datetime.UTC`, missing `jsonschema`, and missing `hypothesis`. Full `pytest -q --cov` is also
  unavailable because pytest-cov is not installed.
- `python -m pip install -e '.[dev]'` — **BLOCKED**: final sprint found Python 3.12.15, but the
  isolated build-dependency install stalled and was interrupted; package-index access is restricted.
- `uv python install 3.11` — **BLOCKED** by denied network access; no usable Python 3.11 executable
  was found.
- `python -m pip wheel --no-build-isolation --no-deps` — **BLOCKED** because Python 3.10 does not
  meet package metadata. Direct `setuptools.build_meta.build_wheel('.build-check')` — **PASS** for a
  pure wheel using setuptools 82.0.1; wheel contents and `Requires-Python: >=3.11` were verified.
- Direct `setuptools.build_meta.build_sdist('.build-check')` — **PASS**; tar contents include CI,
  synthetic gate fixtures, scripts, tests, docs, and package. `MANIFEST.in` now specifies these files.
  These backend builds do not validate installation or execution on a supported Python runtime.
- Clean wheel install with dependencies — **NOT COMPLETED**. The wheel installed with `--no-deps` into
  a clean Python 3.12 venv, and package assets were present; outside-repository CLI runs then failed
  because Pydantic was absent.
- `python scripts/regression_gate_demo.py` — **BLOCKED** before evaluation; Python 3.12 child process
  failed while importing the package because Pydantic was absent.
- Ruff, mypy, pytest-cov, `python -m build`, clean wheel install, offline gate demo, benchmark, browser automation,
  live provider, and Docker smoke tests — **NOT RUN** (tools/runtime/daemon/credentials unavailable).
- `pip-audit` — **NOT RUN to completion**; its PyPI vulnerability query was denied by network policy.
- ZIP inspection — **PASS**: archive opens, includes source/tests/docs/workflows/demo, excludes caches,
  virtual environments, generated databases and secrets.

No supported-runtime test count, coverage percentage, Ruff result, mypy result, functional wheel
install result, dependency audit result, or benchmark timing/memory result is available. See the
final verification report for the Python 3.12 executable and exact blockers. Complete these checks
with dependencies available before treating the 95/100 target as verified.

## Prioritized remaining work

1. **P0 — verification:** run full CI-equivalent checks under Python 3.11 and 3.12; fix any failures;
   capture actual test count and coverage without lowering the 90% threshold.
2. **P1 — release:** build wheel and sdist with `python -m build`, install the wheel into a clean
   supported environment, and test CLI/API outside the repository.
3. **P1 — supply chain:** run `pip-audit` and a dependency license inventory with network access;
   consider a reviewed lock file for repeatable deployments.
4. **P2 — browser assurance:** add and run a browser-level dashboard flow for auth, selection,
   comparisons, trends, and downloads when a browser runner is available.
5. **P2 — operational controls:** if deployed beyond a trusted local/reverse-proxy boundary, add
   tested rate limiting and operational guidance for SQLite backup, retention, and file access.
