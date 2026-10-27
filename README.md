# DriftGuard Pro

**Deterministic E2E Testing & Drift Detection for LLM Applications**

DriftGuard Pro is a testing and regression-detection platform designed to help developers identify unintended changes in AI application behavior. It evaluates LLM application outputs against configurable expectations, measures similarity and structural changes, checks latency thresholds, and generates reports to support safer releases.

## The Problem

Traditional software tests often rely on exact, deterministic outputs. Large language model (LLM) applications can produce different responses across runs, making conventional snapshot-based testing insufficient for many AI workflows.

A prompt edit, model upgrade, or application change can introduce subtle regressions, including missing fields, invalid output structures, reduced semantic similarity, and increased latency.

## The Solution

DriftGuard Pro provides a configurable testing workflow for detecting these regressions before they reach production.

## Key Features

- **End-to-end evaluation:** Run configurable test suites against expected AI application behavior.
- **Semantic similarity checks:** Detect meaningful differences between expected and actual text outputs.
- **Structured output validation:** Identify missing fields and changes in expected JSON structure.
- **Latency regression detection:** Flag responses that exceed configured latency thresholds.
- **Automated regression gates:** Use process exit codes to distinguish passing suites from failing suites in CI/CD workflows.
- **Multiple report formats:** Export results in JSON, HTML, JUnit XML, and Markdown.
- **Run history:** Review saved test runs and their results.
- **CLI workflow:** Execute test suites from the command line.
- **API and dashboard:** Inspect test results through the project's API and dashboard.
- **Automated quality checks:** The project has been tested with pytest, Ruff, and MyPy.

## Technology Stack

- Python
- pytest and coverage
- Ruff
- MyPy
- FastAPI / Uvicorn
- JSON-based test suite configuration
- HTML, JSON, JUnit XML, and Markdown reporting
- GitHub Actions for CI/CD integration

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/driftguard-pro.git
cd driftguard-pro
```

Create and activate a virtual environment.

Windows:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
```

Linux / macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install the project:

```bash
python -m pip install .
```

For development dependencies, use the project's documented development installation command if available.

## Run a Test Suite

Run the demonstration suite:

```bash
driftguard run examples/demo.json
```

Run the regression demonstration:

```bash
driftguard run examples/regression.json
```

The demo suite is expected to pass. The regression example intentionally contains failing cases and should return a nonzero exit code.

## Expected Regression-Gate Behavior

| Test | Expected result |
|---|---|
| Demonstration suite | PASS; exit code 0 |
| Regression suite | FAIL; exit code 1 |
| Invalid command or usage | Nonzero usage/error exit code |

These examples demonstrate how a CI workflow can detect regressions and fail a job when a test suite does not meet its configured thresholds.

## Run the API

Use the project's documented API startup command. For example, if supported by the installed package:

```bash
uvicorn driftguard.api:app
```

The API and dashboard can be used to inspect runs and results. Refer to the project documentation for the available endpoints and configuration options.

## CI/CD Integration

DriftGuard Pro can be integrated into GitHub Actions so that test suites run on pushes and pull requests.

A passing suite can allow the workflow to continue. A failing suite should return a nonzero exit code and fail the job. To make this a required merge gate, configure the relevant GitHub branch protection rule or repository ruleset.

## Quality Verification

The v1.1.2 verification results recorded for this project include:

- 227 tests passed
- 96.71% test coverage
- Ruff lint checks passed
- Ruff formatting checks passed
- MyPy reported no issues in 21 source files
- Wheel package built successfully
- Fresh wheel installation and CLI demonstration verified
- JSON, HTML, JUnit XML, and Markdown exports checked
- Run history persistence checked

These are recorded verification results, not a claim that every deployment environment, live LLM provider, or production security scenario has been independently audited.

## Project Status

**Version:** 1.1.2

DriftGuard Pro is a developer-tool project focused on making AI application testing and regression detection more reliable. Further work can include broader live-provider integrations, security hardening, deployment automation, and additional CI/CD verification.

## Contributing

Contributions, bug reports, and suggestions are welcome. Please open an issue describing the problem or proposed improvement before submitting major changes.

## License

Add the license selected for this repository. Do not claim an open-source license until its license file has been added.
