# DriftGuard Pro 1.1.2 — final verification sprint

Date: 2026-10-27. This report records the latest verification attempt and supersedes older
environment notes in `FINAL_QUALITY_AUDIT.md` where they differ.

## Environment and CI availability

- Supported runtime found: Python 3.12.15 at `C:\Users\Shridevi S Madiwalar\.local\bin\python3.12.exe`.
- A clean `.venv-verify` was created with Python 3.12. It initially had no project/runtime/dev
  dependencies. `pydantic`, `jsonschema`, `fastapi`, `pytest`, `pytest-cov`, `hypothesis`, `ruff`,
  and `mypy` are absent from that environment.
- In the command table, `python3.12` means the full executable path listed above.
- `python -m pip install -e '.[dev]'` was attempted twice and remained at isolated build dependency
  installation without returning. Both processes were manually interrupted; **no exit code was
  returned**. Previous package-index attempts in this environment reported blocked network access.
- GitHub Actions could not be dispatched: `gh auth status` exited 1 because the saved GitHub token
  is invalid. The supplied project has no Git repository/remote. There is no available free remote
  CI route from this checkout.

## Root-cause diagnosis

The dependency groups are not missing declarations. `pyproject.toml` declares Pydantic, jsonschema,
FastAPI, and Uvicorn as required runtime dependencies and pytest, pytest-cov, Hypothesis, HTTPX,
Ruff, mypy, and types-jsonschema in the `dev` extra. The documented command requests that extra.
The clean venv remained empty because pip did not finish isolated build-dependency installation
(`setuptools>=77` and `wheel`); consequently pip never got to install the project or its runtime/dev
dependencies. The Python 3.12 pip cache reports no locally built wheels. The earlier environment
also reported network denial when accessing the package index. This is an installation environment
blocker, not evidence that the source imports are undeclared. No dependency-group change can make a
fresh online install succeed while the package index is inaccessible; no local wheelhouse was
available to use legitimately.

## Commands and results

| Command/check | Result |
|---|---|
| Python 3.12.15 interpreter startup | **PASS**, version reported |
| `python3.12 -m compileall -q src tests benchmarks scripts` | **PASS**, exit 0; syntax check only |
| Source/ZIP byte comparison before this report/workflow edit | **PASS**, 71 source files, 0 missing and 0 mismatched entries; ZIP rebuilt and rechecked after edits |
| `python3.12 scripts/regression_gate_demo.py` | **BLOCKED**, exit 1 before evaluation: missing `pydantic` |
| `python3.12 -m pytest -q --cov` in clean venv | **BLOCKED**, exit 1: `pytest` is not installed; 0 tests collected |
| `python3.12 -m ruff check .` | **BLOCKED**, exit 1: `ruff` is not installed |
| `python3.12 -m ruff format --check .` | **BLOCKED**, exit 1: `ruff` is not installed |
| `python3.12 -m mypy` | **BLOCKED**, exit 1: `mypy` is not installed |
| `python3.12 benchmarks/benchmark_core.py` | **BLOCKED**, exit 1: package is not installed/importable |
| Benchmark with `PYTHONPATH=src` | **BLOCKED**, exit 1: missing `jsonschema` |
| CLI help and example smoke outside the repository from installed wheel | **BLOCKED**, both exit 1: missing runtime dependency `pydantic` |
| Offline gate positive/negative verdicts and report assertions | **NOT VERIFIED**; demo stopped before generating reports |
| API/auth/SQLite/dashboard tests | **NOT RUN**; required runtime/dev dependencies are missing |
| `docker info` | **BLOCKED**, exit 1: Docker daemon pipe is unavailable |
| `gh auth status` | **BLOCKED**, exit 1: saved token is invalid; no remote workflow was run |
| `pip-audit` against project dependencies | **NOT RUN**: the project declares open version ranges rather than a pinned lock; the audit service/package index is unavailable. A successful vulnerability/license audit is not claimed. |
| Benchmark timing and memory | **NOT MEASURED**; execution stopped at missing dependencies |

The project wheel was installed into the clean Python 3.12 venv with
`python -m pip install --no-index --no-deps .build-check/driftguard_pro-1.1.2-py3-none-any.whl`:
**PASS, exit 0**. This verifies wheel installation only, without dependencies. `importlib.resources`
checks for version 1.1.2, the bundled dashboard index, and the bundled demo example all **passed**.
The outside-repository CLI checks then failed as above, so this is not a successful application
installation test.

The wheel and sdist were rebuilt using the installed setuptools backend under Python 3.10 after the
verification report and workflow edits; package contents and `Requires-Python: >=3.11` were
inspected. The current project ZIP was rebuilt after the latest source/workflow/report edits and
passed ZIP opening, required-file, no-cache/no-database/no-secret checks.

The provider mock subset had previously reported 11 passing tests under Python 3.10 with an
in-process `StrEnum` shim. That historical result is not a supported-runtime test result and does
not substitute for the full suite.

Static CI review: the PowerShell smoke step checks each command's `$LASTEXITCODE` immediately,
including the expected regression exit 1. The offline demo is a separate CI command whose nonzero
Python process exit fails the step. The CI workflow itself was not executed in this sprint.

## Free-only operation

The core has no credentials or paid-service requirement by design. The checked-in regression demo
uses synthetic JSON cases and the required CLI/assertion/statistics logic, not provider SDKs. Optional
provider recording is the only documented path that sends prompts to an external provider and may
incur cost. Functional execution of local API, SQLite, report generation, and the offline demo was
not verified in this sprint because the required open-source Python packages could not be installed.
Initial installation requires downloading the declared packages from a package index; no paid
service is required, but network access or a pre-populated wheelhouse is required.

## Result and remaining blockers

The latest ZIP is structurally valid and matches the latest included files. Python 3.12 syntax and
wheel metadata/package-data installation are verified. **No supported-runtime test suite, coverage
percentage, Ruff result, mypy result, working CLI/API run, passing/failing gate execution, security
audit, or performance measurement was obtained.** The 95/100 target is not established. The next
verification step requires a pre-provisioned Python 3.12 environment with `.[dev]` installed (or
working package-index access), followed by the exact CI checks and a valid GitHub Actions credential
if remote CI is required.

## Editable build hang diagnosis (2026-10-27)

No project build configuration change is justified by the evidence. The PEP 660 hook is functional, and the standard isolated-build stall reproduces on an unrelated minimal package. The observed failure is in pip's isolated build-dependency bootstrap in this Windows/Python 3.12 environment, before project metadata or source is processed. Direct PyPI access and installation of the same build requirements into the active venv both succeeded, so this is not evidence of a missing DriftGuard dependency declaration or a package-index outage. Root cause inside pip's isolated bootstrap remains undetermined.

Environment: Python 3.12.15 (`C:\Users\Shridevi S Madiwalar\.local\bin\python3.12.exe`), pip 26.2.2, setuptools 84.2.1, wheel 0.48.0, Windows AMD64. Backend imports normally. The active diagnostic venv is `.venv-deps-check`.

| Exact diagnostic command | Elapsed | Exit | Evidence |
|---|---:|---:|---|
| `.venv-deps-check\\Scripts\\python.exe -c "import sys,pip; print('exe='+sys.executable); print('python='+sys.version); print('pip='+pip.__version__); import setuptools,wheel; print('setuptools='+setuptools.__version__); print('wheel='+wheel.__version__); import setuptools.build_meta as b; print('backend_import=ok')"` | 7.9 s | 0 | Python 3.12.15; pip 26.2.2; setuptools 84.2.1; wheel 0.48.0; `backend_import=ok`. |
| `.venv-deps-check\\Scripts\\python.exe -m pip install setuptools>=77 wheel --index-url https://pypi.org/simple --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 5 --verbose` | completed | 0 | Previously recorded in this diagnostic session: setuptools/wheel and packaging installed successfully. |
| `.venv-deps-check\\Scripts\\python.exe -m pip install pydantic>=2.5,<3 --index-url https://pypi.org/simple --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 5 --verbose` | completed | 0 | Previously recorded in this diagnostic session: Pydantic installed successfully from PyPI. |
| Tiny temporary PEP 517 project: `python -m pip install -e . --no-build-isolation --no-deps --disable-pip-version-check --no-input -vv` | 11.73 s | 0 | `Checking if build backend supports build_editable: finished`; editable wheel built and installed. Temporary directory was removed. |
| DriftGuard: `python -m pip install -e . --no-build-isolation --no-deps --disable-pip-version-check --no-input -vv` | 11.53 s | 0 | Editable hook check and metadata completed; editable wheel built and installed. This isolates backend hook behavior only; `--no-deps` does not verify application runtime dependencies. |
| DriftGuard: `python -m pip install -e . --index-url https://pypi.org/simple --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 8 --verbose` | 60.05 s (bounded) | TIMEOUT (subprocess killed by harness) | Last stdout: `Installing build dependencies: started`; stderr: `Running command installing build dependencies` and pip 26.2.2 banner. No project hook or dependency resolution was reached. |
| Unrelated tiny temporary project, same isolated command and 60 s bound | 60.03 s (bounded) | TIMEOUT (subprocess killed by harness) | Last stdout/stderr likewise `Installing build dependencies: started` / `Running command installing build dependencies`. Temporary directory was removed. |
| `python -m pip install -e . --no-build-isolation --no-deps ... -vv` | 11.53 s | 0 | Confirms DriftGuard's editable hook works when the backend is already provisioned in the environment. |

The two isolated install commands were explicitly time-bounded at 60 seconds and were terminated by the diagnostic harness. Their last captured output was the start of build-dependency installation; there was no pip error explaining the stall. This pattern reproducing in the minimal project rules out DriftGuard's package discovery, metadata, or source as the cause. PyPI reachability was separately confirmed earlier in this session, and active-environment build dependency installation succeeded; those observations do not prove that pip's isolated child process has equivalent network behavior.

**Proposed bounded workaround (not yet used for a full application installation):** in a fresh Python 3.12 venv, install the declared build requirements (`setuptools>=77`, `wheel`) first from the configured package index, then install the project with `pip install --no-build-isolation -e ".[dev]"`. This avoids the failing pip isolated-bootstrap phase while retaining the declared runtime and development dependencies; do not add `--no-deps`. The prior `--no-build-isolation --no-deps` checks above were only backend diagnostics and are not application installation evidence. A full fresh-environment install and test suite are intentionally not started before this diagnosis is reported.

**Configuration decision:** leave `[build-system]` (`setuptools>=77`, `wheel`, `setuptools.build_meta`), package discovery (`where=["src"]`), dependency groups, and project source unchanged. Changing these settings would not address a failure reproduced by an unrelated minimal project. No full tests, CLI/API checks, or regression demo were run as part of this diagnostic step.

## Fresh Python 3.12 installation attempt (2026-10-27)

| Command | Elapsed | Exit | Result |
|---|---:|---:|---|
| `"C:\\Users\\Shridevi S Madiwalar\\.local\\bin\\python3.12.exe" -m venv .venv-verify312` | 25.2 s | 0 | Fresh venv created. |
| `.venv-verify312\\Scripts\\python.exe -m pip install setuptools>=77 wheel --index-url https://pypi.org/simple --disable-pip-version-check --no-input --retries 0 --timeout 10 --verbose` (arguments passed directly to subprocess; 90 s subprocess cap) | 90.05 s | TIMEOUT (harness terminated process) | Captured stdout was only `Using pip 26.2.2 from ...\\.venv-verify312\\Lib\\site-packages\\pip (python 3.12)`; captured stderr was empty. No installation progress or pip error was emitted. |
| `.venv-verify312\\Scripts\\python.exe -m pip list --format=freeze` | 7 s | 0 | Only `pip==26.2.2` is installed; setuptools and wheel were not installed. |
| `.venv-verify312\\Scripts\\python.exe -c "import sys; print(sys.executable); print(sys.version)"` | included in 7 s command call | 0 | Confirmed fresh environment is Python 3.12.15. |

The requested editable project installation (`pip install --no-build-isolation -e ".[dev]"`) was **NOT RUN** because its prerequisite build-requirement installation did not complete. No retry was made. Runtime/development dependencies, pytest/coverage, Ruff, mypy, CLI, API/dashboard, regression scenarios, and packaging checks were **NOT RUN** in this fresh environment. The source and build configuration were not changed, and the release ZIP was not rebuilt.

The failure provides no pip exception or network error text to diagnose further: pip emitted only its startup banner before the 90-second harness timeout. This is a fresh-environment package installation blocker; it does not establish a project dependency declaration defect. The previous environment's successful build-requirement installation does not count as success in this new venv.

## Package installation stall diagnostics (2026-10-27, follow-up)

No DriftGuard install or functional tests were run, and no source files or ZIP were changed.

| Check / exact command | Elapsed | Exit/result | Evidence |
|---|---:|---:|---|
| `Resolve-Path .venv-verify312\\Scripts\\python.exe`; `& $py -c "import sys,pip; ..."`; `& $py -m pip --version` | 7.4 s | 0 | Python is `.venv-verify312\\Scripts\\python.exe`, Python 3.12.15; pip is from this venv, version 26.2.2. |
| `& $py -m pip config debug` with output redaction | 8.9 s | 0 | No relevant pip/proxy/cert environment variables were set. Global/user/site config files: only `C:\\Users\\Shridevi S Madiwalar\\pip\\pip.ini` exists, setting `global.cache-dir: D:\\pip-cache`; no configured index/proxy/certificate value was shown. Credential-like output was redacted. |
| Python `urllib` GET `https://pypi.org/simple/setuptools/` with 8 s timeout | 0.62 s | HTTP 200 | TLS and endpoint access worked. |
| Python `urllib` GET `https://files.pythonhosted.org/` with 8 s timeout | 0.24 s | HTTP 404 | TLS/host connection worked; root path is not a valid resource. |
| `.venv-verify312\\Scripts\\python.exe -m pip -vvv index versions setuptools --index-url https://pypi.org/simple --disable-pip-version-check --no-input --retries 0 --timeout 5` (20 s subprocess cap) | 20.03 s | TIMEOUT; harness terminated command | Last output: pip looked up the setuptools simple page, opened HTTPS, received `304`, then emitted no more output. Stderr was empty. |
| `.venv-verify312\\Scripts\\python.exe -m pip cache info` | 7.4 s call with process/disk inspection | 0 | Cache is `D:\\pip-cache\\http-v2`, 104.8 MB, 710 HTTP files; wheel cache is empty. |
| PowerShell process listing (`Get-Process -Name python,python3,pip`) | same inspection | completed | Found Python PIDs 13156 and 21660 (started 19:01:34 local) and 14540 and 26608 (started 19:02:49 local). CPU time was respectively 373.61, 0.02, 0.02, and 302.33 seconds. At 19:10 local these had existed about 9 and 7 minutes. `Get-CimInstance Win32_Process` was denied (0x80041003), so command lines/parentage could not be inspected. They were not terminated because their purpose could not be established safely. |
| .NET drive free-space check for C: and D: | same inspection | completed | C: had 4,469,379,072 bytes free; D: had 75,751,854,080 bytes free. Disk exhaustion is not indicated. |

### Comparison to earlier successful downloads

Earlier evidence in this report came from the different `.venv-deps-check` environment, also Python 3.12.15/pip 26.2.2. There, explicitly installing setuptools/wheel and Pydantic with `--index-url https://pypi.org/simple --no-cache-dir --retries 0 --timeout 5` completed. Those commands used a different venv and explicitly bypassed the configured cache; they do not prove that the current `.venv-verify312` or its cache behaves identically. The current verbose index query did use the configured cache and logged a 304 response immediately before hanging. However, earlier isolated project installs also stalled when `--no-cache-dir` was specified, so cache behavior alone is not established as the root cause.

### Finding

Direct HTTPS connectivity succeeds and disk space is ample. Pip can reach the index but the bounded pip index query stalled after a cached 304 response; four Python processes remain, and OS permissions prevented inspecting their command lines. These are concrete environment anomalies, but the evidence does not isolate whether the hang is due to pip/cache processing, lingering processes, or another local runtime condition. No machine-wide setting was changed. Do not start another installation attempt until the lingering processes/cache situation can be safely inspected or an administrator/environment owner can identify those processes. No one-off cache bypass was attempted in this follow-up.

## Controlled Python 3.12 install attempt (2026-10-27)

The downloaded build wheels were used once in the fresh `.venv-verify312`; then the requested editable install with the full dev extra was attempted once. The second command timed out, so no dependency or application tests were started.

| Exact command | Elapsed | Exit | stdout / stderr |
|---|---:|---:|---|
| `.venv-verify312\\Scripts\\python.exe -m pip install --no-index --find-links C:\\Users\\SHRIDE~1\\AppData\\Local\\Temp setuptools>=77 wheel --disable-pip-version-check --no-input --verbose` | 10.94 s | 0 | stdout: `Successfully installed packaging-26.3 setuptools-84.2.1 wheel-0.48.0`; stderr empty. It used the three wheels downloaded in the immediately preceding probe. |
| `.venv-verify312\\Scripts\\python.exe -m pip install --no-build-isolation -e .[dev] --verbose` (the pip process was given a 90-second timeout; `.[dev]` was passed as one argument) | 90.03 s | 124 (timeout wrapper; pip process terminated) | stdout empty; stderr empty. No pip progress or error was captured. No retry was made. |

**Status:** build tools install **PASS**. Editable project plus declared development dependencies **BLOCKED** by the 90-second pip stall. Runtime/dev dependency import checks, pytest with coverage, Ruff lint/format, mypy, CLI, regression gate, reports, API/dashboard, packaging, and ZIP verification are **NOT RUN** after this attempt. No source files or ZIP were changed.

## Runtime dependency resolution isolation (2026-10-27)

Per the bounded investigation, the runtime requirements were attempted separately from editable installation and the dev extra. The command exited with a package-index connection timeout; the investigation stopped as requested. No import, dev dependency, editable, CLI, or test checks followed.

| Stage | Exact command | Elapsed | Exit | Result |
|---|---|---:|---:|---|
| Project/interpreter/process inspection | PowerShell `Resolve-Path .`, `Resolve-Path .venv-verify312\\Scripts\\python.exe`, and `Get-Process -Name python,python3,pip` | 4.8 s | completed | Project root was `C:\\Users\\Shridevi S Madiwalar\\Downloads\\driftguard-pro-1.1.0 (1)\\driftguard-pro`; venv executable is under `.venv-verify312`. No process named pip was listed; four previously observed python processes remained (command lines unavailable). |
| Pip version | `.venv-verify312\\Scripts\\python.exe -m pip --version` | 1.61 s | 0 | pip 26.2.2 from the target venv. |
| Installed packages | `.venv-verify312\\Scripts\\python.exe -m pip list` | 1.67 s | 0 | Only packaging 26.3, pip 26.2.2, setuptools 84.2.1, wheel 0.48.0. |
| Runtime requirements from `pyproject.toml` | Pydantic `>=2.5,<3`; jsonschema `>=4.18,<5`; FastAPI `>=0.110,<1`; Uvicorn `>=0.27,<1` | n/a | n/a | Build backend is `setuptools.build_meta`, build requirements `setuptools>=77` and `wheel`, Python `>=3.11`, package discovery `src`, no explicit editable-specific configuration. Dev extra contains pytest, pytest-cov, Hypothesis, HTTPX, Ruff, mypy, and types-jsonschema. |
| Runtime install | `.venv-verify312\\Scripts\\python.exe -m pip install --index-url https://pypi.org/simple --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 8 --verbose 'pydantic>=2.5,<3' 'jsonschema>=4.18,<5' 'fastapi>=0.110,<1' 'uvicorn>=0.27,<1'` | 24.84 s | 1 | **FAIL/BLOCKED:** resolver reached package metadata downloads, then stderr reported `error: connection-timeout` fetching `pydantic-core==2.50.0` metadata from `files.pythonhosted.org`: `files.pythonhosted.org didn't respond within 8.0 seconds`. Last stdout operation was obtaining metadata for `pydantic-core==2.50.0` after pip examined Pydantic 2.14.1 and 2.14.0. No retry followed. |

Dependency imports, development dependency installation, editable installation without dependency resolution, pytest/coverage, Ruff, mypy, CLI/regression, and API/dashboard are **NOT RUN**. Application functionality is not claimed. No source, machine-wide configuration, or ZIP was changed.

## pydantic-core wheel compatibility and runtime retry (2026-10-27)

| Check | Exact command / evidence | Elapsed | Exit/result |
|---|---|---:|---|
| Python platform/ABI | `.venv-verify312\\Scripts\\python.exe -m pip debug --verbose`; Python reported 3.12.15, AMD64, 64-bit, `sysconfig.get_platform()=win-amd64` | 7.4 s | **PASS**, compatible tags include `cp312-cp312-win_amd64`. |
| Pydantic/core compatibility | PyPI JSON queried for Pydantic 2.14.1 and pydantic-core 2.50.1/2.50.0 | under 2 s total | **PASS**, Pydantic 2.14.1 requires exactly pydantic-core 2.50.1. Both core versions publish cp312 Windows AMD64 wheels; 2.50.1 is the matching version. |
| Core wheel download | `.venv-verify312\\Scripts\\python.exe -m pip download --no-deps --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 5 --verbose --dest %TEMP%\\driftguard-pydantic-core-probe https://files.pythonhosted.org/packages/c5/17/8bbd530b8659e9d963f5b16f6cb8e159f4cd174b4d6304e48969ab12dba8/pydantic_core-2.50.1-cp312-cp312-win_amd64.whl` | 5.91 s | **PASS**, exit 0; downloaded `pydantic_core-2.50.1-cp312-cp312-win_amd64.whl`, 2,172,522 bytes. |
| Wheel verification | SHA-256, ZIP test, and WHEEL tag inspected locally | 5.1 s | **PASS**; SHA-256 `132529c83901437ff642f585216831bf5fd7a91df66829907e155192ead62498` matches PyPI metadata; ZIP test passes; tag is `cp312-cp312-win_amd64`. |
| Runtime dependency install using verified local core wheel | `.venv-verify312\\Scripts\\python.exe -m pip install --index-url https://pypi.org/simple --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 10 --verbose %TEMP%\\driftguard-pydantic-core-probe\\pydantic_core-2.50.1-cp312-cp312-win_amd64.whl 'pydantic>=2.5,<3' 'jsonschema>=4.18,<5' 'fastapi>=0.110,<1' 'uvicorn>=0.27,<1'` | 18.78 s | **FAIL/BLOCKED**, exit 1. The local core wheel was accepted, and Pydantic 2.14.1 plus its exact core requirement were resolved. Pip then failed fetching `h11==0.16.0` metadata from `https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl.metadata`; stderr says it did not respond within 10.0 seconds (`connection-timeout`). No retry followed. |

Runtime dependencies are not verified as installed. Development dependencies, imports, editable installation, pytest/coverage, Ruff, mypy, CLI, regression gate, API/dashboard, and packaging remain **NOT RUN**. No source or ZIP was changed.

## Controlled runtime/dev dependency wheelhouse verification (2026-10-27)

| Stage | Command / evidence | Elapsed | Exit | Status |
|---|---|---:|---:|---|
| Python 3.12 platform | `pip debug --verbose` and `sysconfig.get_platform()` in `.venv-verify312` | 7.4 s | 0 | **PASS**: AMD64, 64-bit, `win-amd64`; supported tag includes `cp312-cp312-win_amd64`. |
| Project runtime constraints | Read `pyproject.toml` via Python `tomllib` | 5.8 s | 0 | **PASS**: Pydantic `>=2.5,<3`, jsonschema `>=4.18,<5`, FastAPI `>=0.110,<1`, Uvicorn `>=0.27,<1`; backend `setuptools.build_meta`, build requirements setuptools>=77 and wheel. |
| h11 download-only test | `.venv-verify312\\Scripts\\python.exe -m pip download --no-deps --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 5 --verbose --dest %TEMP%\\driftguard-h11-probe-yc_c00fg https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl` | 3.28 s | 0 | **PASS**: h11 0.16.0 wheel downloaded. Earlier h11 metadata timeout was transient for this direct wheel request. |
| Complete runtime wheel download | `.venv-verify312\\Scripts\\python.exe -m pip download --only-binary=:all: --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 10 --verbose --index-url https://pypi.org/simple --dest %TEMP%\\driftguard-runtime-wheelhouse-ar4doykt <local pydantic_core-2.50.1-cp312-cp312-win_amd64.whl> <local h11-0.16.0-py3-none-any.whl> 'pydantic>=2.5,<3' 'jsonschema>=4.18,<5' 'fastapi>=0.110,<1' 'uvicorn>=0.27,<1'` | 10.92 s | 0 | **PASS**: 19 wheels resolved/downloaded. Versions: annotated-doc 0.0.5; annotated-types 0.8.0; anyio 4.15.1; attrs 26.1.0; click 8.5.0; fastapi 0.162.0; h11 0.16.0; idna 3.20; jsonschema 4.26.0; jsonschema-specifications 2025.9.1; opentelemetry-api 1.45.1; pydantic 2.14.1; pydantic-core 2.50.1; referencing 0.37.0; rpds-py 2026.9.1; starlette 1.10.0; typing-extensions 4.16.0; typing-inspection 0.4.4; uvicorn 0.54.0. |
| Published wheel hashes | PyPI JSON file SHA-256 compared to each local wheel SHA-256 | 7.8 s | 0 | **PASS**, 19/19 matched. |
| Fresh offline venv | `python3.12.exe -m venv %TEMP%\\driftguard-runtime-offline-env` | 25.5 s | 0 | **PASS**: new Python 3.12 venv outside repository. |
| Offline runtime install | `%TEMP%\\driftguard-runtime-offline-env\\Scripts\\python.exe -m pip install --no-index --find-links %TEMP%\\driftguard-runtime-wheelhouse-ar4doykt --disable-pip-version-check --no-input --verbose 'pydantic>=2.5,<3' 'jsonschema>=4.18,<5' 'fastapi>=0.110,<1' 'uvicorn>=0.27,<1'` | 27.66 s | 0 | **PASS**: 19 runtime packages installed from local wheels, no index access. |
| Runtime imports | `%TEMP%\\driftguard-runtime-offline-env\\Scripts\\python.exe -c "import pydantic, pydantic_core, jsonschema, fastapi, uvicorn; ..."` | 10.6 s | 0 | **PASS**: pydantic 2.14.1, core 2.50.1, jsonschema 4.26.0, FastAPI 0.162.0, Uvicorn 0.54.0 imported. |
| Dev wheel download | `%TEMP%\\driftguard-runtime-offline-env\\Scripts\\python.exe -m pip download --only-binary=:all: --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 10 --verbose --index-url https://pypi.org/simple --dest %TEMP%\\driftguard-dev-wheelhouse-bi8iqyrs 'pytest>=8.4,<10' 'pytest-cov>=5,<8' 'hypothesis>=6.100,<7' 'httpx>=0.27,<1' 'ruff>=0.5,<1' 'mypy>=1.8,<2' 'types-jsonschema>=4.18,<5'` | 15.77 s | 1 | **BLOCKED**: stderr `error: connection-timeout`; exact failed URL `https://files.pythonhosted.org/packages/96/ba/11c464d8aed7777b99eec35d31c474ea64caaa68e4da342609aa1bad2868/hypothesis-6.170.12-cp312-cp312-win_amd64.whl.metadata`; it did not respond within 10 seconds. Last stdout: obtaining Hypothesis 6.170.12 metadata. No retry followed. |

Dev dependencies could not be collected, so they were not installed. Pytest/coverage, Ruff, mypy, project editable install, CLI, regression gate, API/dashboard, and release checks remain **NOT RUN**. Runtime dependency installation and import success do not constitute functional application verification. No source files or release ZIP were modified.

## Development tool download and runtime-only smoke verification (2026-10-27)

The runtime environment `%TEMP%\\driftguard-runtime-offline-env` and its installed 19 runtime packages were preserved. The separate dev wheel download below was attempted once with a 30-second overall cap and binary-only wheels.

Compatible top-level dev wheels identified from PyPI metadata for Python 3.12 Windows were: pytest 9.1.1 (`py3-none-any`), pytest-cov 7.1.0 (`py3-none-any`), Hypothesis 6.170.12 (`cp311-abi3-win_amd64`, compatible with cp312), HTTPX 0.28.1 (`py3-none-any`), Ruff 0.17.3 (`py3-none-win_amd64`), mypy 1.20.2 (`cp312-cp312-win_amd64`), and types-jsonschema 4.26.0.20261006 (`py3-none-any`). These are candidates within the declared ranges, not installed dev tools.

| Check | Command | Elapsed | Exit/status | Evidence |
|---|---|---:|---|---|
| Dev wheel download | Runtime venv `python -m pip download --only-binary=:all: --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 8 --verbose --index-url https://pypi.org/simple --dest %TEMP%\\driftguard-dev-wheelhouse-wn5d1vgp <seven selected top-level wheel URLs>` | 19.89 s | 1 — **BLOCKED** | Top-level wheels began downloading. Resolver then timed out fetching `pluggy==1.7.0` metadata at `https://files.pythonhosted.org/packages/40/9e/2b38731e0fc536806f16490e1a12d7f0dc2a1235aa8cc07bcc75416a7daa/pluggy-1.7.0-py3-none-any.whl.metadata`. Pip stderr: `error: connection-timeout`; host did not respond within 8.0 seconds. No retry was made. |
| CLI help | `%TEMP%\\driftguard-runtime-offline-env\\Scripts\\python.exe -m driftguard.cli --help` with `PYTHONPATH=<project>\\src` | 1.70 s | 0 — **PASS** | Help text and exit-code descriptions printed. |
| Suite validation | `%TEMP%\\driftguard-runtime-offline-env\\Scripts\\python.exe -m driftguard.cli validate examples/demo.json` with `PYTHONPATH=<project>\\src` | 1.70 s | 0 — **PASS** | `OK examples\\demo.json (8 cases)`. |
| Regression gate demo | `%TEMP%\\driftguard-runtime-offline-env\\Scripts\\python.exe scripts/regression_gate_demo.py` | 10.44 s | 0 — **PASS** | Baseline PASS; acceptable candidate PASS; degraded candidate FAIL at expected run exit 1; diff accepted exit 0 and degraded exit 1; required failure reasons `assertion:contains`, `drift:latency`, and `drift:similarity` printed. Demo validated JSON, JUnit XML, and Markdown reports. |
| API/dashboard HTTP smoke | Runtime venv launched `python -m uvicorn driftguard.api:app --host 127.0.0.1 --port 63725` with `PYTHONPATH=<project>\\src` and a temporary SQLite database; stdlib HTTP calls queried `/api/health`, `/`, `/api/config`, `/api/examples`, POST `/api/runs` for synthetic demo, then fetched its Markdown report | 4.28 s | 0 — **PASS** | Health/config/examples and dashboard returned 200; dashboard HTML served; demo run returned 201 PASS; Markdown report returned 200; temporary SQLite database was created. This is HTTP smoke coverage, not browser automation. Server was terminated by the harness after the checks. |

The complete dev set did not download, so it was not installed offline in a separate verification venv. Pytest with coverage, test count/coverage percentage, Ruff lint/format, mypy, browser automation, and full test-backed API/auth/persistence checks are **NOT RUN**. Runtime-only commands above do not substitute for those checks. No source files or ZIP were modified.

## Follow-up development wheelhouse attempt (2026-10-27)

The previously working runtime environment was preserved. Development dependencies were inspected and compatible root wheels identified (pytest 9.1.1, pytest-cov 7.1.0, Hypothesis 6.170.12 cp311-abi3-win_amd64, HTTPX 0.28.1, Ruff 0.17.3 py3-none-win_amd64, mypy 1.20.2 cp312-win_amd64, types-jsonschema 4.26.0.20261006). The failed `pluggy-1.7.0` metadata request was bypassed by downloading its direct wheel once; it succeeded in 3.91 s and its SHA-256 `7dd7b0d8832ba3cb632c306926ded123429211b83641b35dc5c41ad2d34f9bec` matched PyPI JSON.

One complete dev download attempt was then made with direct root wheel URLs, local pluggy, binary-only resolution, `--no-cache-dir`, zero retries, per-request timeout 8 s, and an overall 30 s cap. Exact pip command:

```text
C:\\Users\\Shridevi S Madiwalar\\AppData\\Local\\Temp\\driftguard-runtime-offline-env\\Scripts\\python.exe -m pip download --only-binary=:all: --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 8 --verbose --index-url https://pypi.org/simple --find-links C:\\Users\\Shridevi S Madiwalar\\AppData\\Local\\Temp\\driftguard-dev-wheelhouse-wn5d1vgp --dest C:\\Users\\Shridevi S Madiwalar\\AppData\\Local\\Temp\\driftguard-dev-wheelhouse-wn5d1vgp https://files.pythonhosted.org/packages/24/25/1de2678b631f5a49215c6c96fff41ba892b0a34df68d6d80292b1b48aa7f/pytest-9.1.1-py3-none-any.whl https://files.pythonhosted.org/packages/9d/7a/d968e294073affff457b041c2be9868a40c1c71f4a35fcc1e45e5493067b/pytest_cov-7.1.0-py3-none-any.whl https://files.pythonhosted.org/packages/df/0d/cdf07a645b2fe1224e70a1080670fc793b296333af3f0caf73409729f294/hypothesis-6.170.12-cp311-abi3-win_amd64.whl https://files.pythonhosted.org/packages/2a/39/e50c7c3a983047577ee07d2a9e53faf5a69493943ec3f6a384bdc792deb2/httpx-0.28.1-py3-none-any.whl https://files.pythonhosted.org/packages/d0/a0/f08c1631bfd81faa6a90eaf70c37c786c11bed2046302b56bb506c25e1a0/ruff-0.17.3-py3-none-win_amd64.whl https://files.pythonhosted.org/packages/3e/0d/47e3c3a0ec2a876e35aeac365df3cac7776c36bbd4ed18cc521e1b9d255b/mypy-1.20.2-cp312-cp312-win_amd64.whl https://files.pythonhosted.org/packages/8b/a0/4f2e3c0dc3d5cad958006f2e0307065cc8fe4fbf0393ff0b69d55ee9bbe5/types_jsonschema-4.26.0.20261006-py3-none-any.whl C:\\Users\\Shridevi S Madiwalar\\AppData\\Local\\Temp\\driftguard-dev-wheelhouse-wn5d1vgp\\pluggy-1.7.0-py3-none-any.whl
```

**Result: BLOCKED**, elapsed 30.01 s, exit 124 (overall timeout harness terminated pip). Captured stderr was empty. Last stdout showed the seven root wheels being downloaded/processed, pluggy found locally, and successful metadata retrieval for colorama, iniconfig, packaging, and Pygments 2.21.0. No specific package error or URL failure appeared before the overall timeout. No further attempt was made.

Complete dev wheelhouse and offline dev installation: **BLOCKED / NOT VERIFIED**. Pytest/coverage, Ruff, mypy, and full suite are **NOT RUN**. The separate runtime venv remains unchanged. The earlier runtime-only CLI, regression demo, and API/dashboard smoke results remain recorded above. Source files and release ZIP were not changed.

## Local development-tool availability inventory (2026-10-27)

Read-only inventory only. No packages were installed, no tests were run, and source/runtime/ZIP were left unchanged.

| Check | Command/result | Status |
|---|---|---|
| Project/tool configuration | `Get-Content pyproject.toml`; dev extra declares pytest>=8.4,<10, pytest-cov>=5,<8, hypothesis>=6.100,<7, httpx>=0.27,<1, ruff>=0.5,<1, mypy>=1.8,<2, types-jsonschema>=4.18,<5; project requires Python >=3.11. | **PASS**, constraints confirmed. |
| Existing repo venvs | Python module-presence probe in `.venv-deps-check`, `.venv-verify`, `.venv-verify312` | **PASS**, all were Python 3.12.15; all reported pytest, pytest_cov, coverage, ruff, and mypy absent. |
| Preserved runtime venv | Same module-presence probe in `%TEMP%\\driftguard-runtime-offline-env` | **PASS**, Python 3.12.15; pytest, pytest_cov, coverage, ruff, and mypy absent. Runtime deps remain present. |
| uv-managed base Python | Same module-presence probe in `%USERPROFILE%\\AppData\\Roaming\\uv\\python\\cpython-3.12.15-windows-x86_64-none\\python.exe` | **PASS**, Python 3.12.15; all five test/quality modules absent. |
| Global pytest launcher | `Get-Command pytest`; probe using its adjacent `Python310\\python.exe` | **UNSUITABLE**: pytest exists under Python 3.10.11, below the project’s `Requires-Python >=3.11`; pytest-cov, coverage, Ruff, and mypy are absent there. It was not used. |
| CLI availability | `Get-Command pytest,ruff,mypy` | pytest resolves only to the Python310 launcher; Ruff and mypy are **NOT_FOUND** on PATH. |
| pip wheel cache | `.venv-verify312\\Scripts\\python.exe -m pip cache list` | **PASS**, output `No locally built wheels cached.` |
| pip cache info | `.venv-verify312\\Scripts\\python.exe -m pip cache info` | **PASS**, wheel cache 0 bytes / 0 wheels. HTTP cache contains 104.8 MB but does not contain locally built wheels. |
| Partial development wheelhouses | Enumerated prior temp directories | **PASS**, one contains only the verified pluggy wheel; the other contains 0 wheels. No complete dev tool set is available locally. |
| uv-managed tool inventory | `uv tool list` | **BLOCKED**, exit 2: could not acquire `C:\\Users\\Shridevi S Madiwalar\\AppData\\Local\\uv\\cache\\.lock` (access denied). The expected `%LOCALAPPDATA%\\uv\\tools` directory was not present. No elevation or permission changes were attempted. |

**Verification disposition:** pytest/pytest-cov/coverage, Ruff, and mypy are unavailable in a suitable Python 3.12 environment or local wheel cache. Full pytest/coverage, Ruff lint/format, mypy, test counts, and coverage percentage are **NOT RUN**. The Python 3.10 pytest launcher is not a valid substitute for the supported runtime. The environment/tool cache access blocker prevents proceeding without a new authorized package source or provisioned dev wheelhouse. No source files or ZIP were changed.

## Complete dev wheelhouse attempt (2026-10-27, latest)

Declared Python requirement is `>=3.11`; target is Windows AMD64 / Python 3.12. Dev constraints remain pytest `>=8.4,<10`, pytest-cov `>=5,<8`, Hypothesis `>=6.100,<7`, HTTPX `>=0.27,<1`, Ruff `>=0.5,<1`, mypy `>=1.8,<2`, types-jsonschema `>=4.18,<5`. A separate temp wheelhouse was assembled from verified runtime wheels, build wheels, and the verified pluggy wheel; the existing runtime venv was not changed.

One complete wheelhouse download attempt used direct PyPI file URLs for selected dev wheels plus PyPI Simple API resolution for transitive dependencies, `--only-binary=:all:`, `--no-cache-dir`, zero retries, 15-second per-request timeout, and a 120-second overall timeout. Command began:

```text
.venv-verify312\\Scripts\\python.exe -m pip download --only-binary=:all: --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 15 --verbose --index-url https://pypi.org/simple --find-links %TEMP%\\driftguard-complete-dev-wheelhouse-8nr64e1z --dest %TEMP%\\driftguard-complete-dev-wheelhouse-8nr64e1z <verified direct wheel URLs for pytest 9.1.1, pytest-cov 7.1.0, Hypothesis 6.170.12, HTTPX 0.28.1, Ruff 0.17.3, mypy 1.20.2 and types-jsonschema 4.26.0.20261006>
```

**BLOCKED**, elapsed 33.91 seconds, exit 1. Pip stderr:

```text
error: connection-timeout
Unable to fetch https://files.pythonhosted.org/packages/f0/2c/5193dc81127cd5ddfad031391b046bf32dda219b38463ab872407ca30646/librt-0.16.0-cp312-cp312-win_amd64.whl.metadata
files.pythonhosted.org didn't respond within 15.0 seconds
```

Last stdout operation was fetching metadata for `librt>=0.8.0` required by mypy 1.20.2. Root wheels were processed and several transitive metadata requests completed, but the operation failed before pip reported a complete saved wheelhouse. No further download attempt was made.

A complete dev wheelhouse has **NOT** been verified; offline dependency resolution and installation are **NOT RUN**. Pytest/coverage, Ruff, mypy, and full test suite are **NOT RUN**. No source, runtime environment, or release ZIP was changed. Required next condition: provide reliable access to the relevant `files.pythonhosted.org` package artifacts or a complete trusted Windows x64 / Python 3.12 wheelhouse including `librt` and all remaining transitive wheels.


## Complete development wheelhouse and supported-runtime checks (2026-10-27)

### `librt` dependency chain and package verification

The project declares the dev extra `mypy>=1.8,<2`. PyPI metadata for the selected compatible mypy 1.20.2 wheel declares `librt>=0.8.0; platform_python_implementation != "PyPy"`; CPython 3.12 satisfies that marker. `librt` is the Mypyc runtime library (PyPI metadata summary: "Mypyc runtime library", project source `https://github.com/mypyc/librt`). PyPI publishes `librt-0.16.0-cp312-cp312-win_amd64.whl`, compatible with this CPython 3.12 AMD64 environment. Its published SHA-256 is `25a58a19ea8d83b68209f04912df765e9260635ef77646542ed4b4abe6bc7940` and the downloaded file matched it. The earlier failure was a transient metadata-fetch timeout for this artifact; a direct wheel request to the same approved PyPI file host succeeded.

### Wheelhouse and offline installation

| Check | Exact command/evidence | Exit / result |
|---|---|---|
| Download missing `librt` wheel | `.venv-verify312\\Scripts\\python.exe -m pip download --no-deps --no-cache-dir --disable-pip-version-check --no-input --retries 0 --timeout 10 --verbose --dest %TEMP%\\driftguard-complete-dev-wheelhouse-8nr64e1z https://files.pythonhosted.org/packages/f0/2c/5193dc81127cd5ddfad031391b046bf32dda219b38463ab872407ca30646/librt-0.16.0-cp312-cp312-win_amd64.whl` | **PASS**, exit 0, 9.06 s. |
| Download previously missing top-level dev wheels | `pip download --no-deps --only-binary=:all: --no-cache-dir ...` with the seven compatible PyPI wheel URLs into the existing wheelhouse | **PASS**, exit 0, 13.30 s. |
| Download missing transitive wheels | `pip download --no-deps --only-binary=:all: --no-cache-dir ...` with direct PyPI wheel URLs for colorama 0.4.6, iniconfig 2.3.1, Pygments 2.21.0, coverage 7.17.0, sortedcontainers 2.4.0, certifi 2026.10.23, httpcore 1.0.9, mypy-extensions 1.1.0, and pathspec 1.1.1 into the same wheelhouse | **PASS**, exit 0, 5.73 s. |
| Wheel verification | Python script checked every wheel's supported tag, ZIP integrity, and SHA-256 against matching PyPI JSON file metadata | **PASS**, 40 wheels; 40/40 hash and ZIP checks passed; all tags are compatible with Python 3.12 Windows AMD64. |
| Offline dependency resolution | `.venv-verify312\\Scripts\\python.exe -m pip install --dry-run --ignore-installed --no-index --find-links %TEMP%\\driftguard-complete-dev-wheelhouse-8nr64e1z ...` with all four runtime and seven dev constraints | **PASS**, exit 0, 4.34 s. Pip printed `Would install` with the full resolved set, including `mypy-1.20.2`, `librt-0.16.0`, `pytest-9.1.1`, `pytest-cov-7.1.0`, `coverage-7.17.0`, and Ruff 0.17.3. |
| New verification venv | `python3.12.exe -m venv %TEMP%\\driftguard-dev-verified-env-20261027` | **PASS**, exit 0. This venv is separate from and does not alter the preserved runtime venv. |
| Offline build-tool install | `%TEMP%\\driftguard-dev-verified-env-20261027\\Scripts\\python.exe -m pip install --no-index --find-links %TEMP%\\driftguard-complete-dev-wheelhouse-8nr64e1z --disable-pip-version-check --no-input --verbose setuptools>=77 wheel` | **PASS**, exit 0, 10.23 s. |
| Offline project/dev install | `%TEMP%\\driftguard-dev-verified-env-20261027\\Scripts\\python.exe -m pip install --no-build-isolation --no-index --find-links %TEMP%\\driftguard-complete-dev-wheelhouse-8nr64e1z --disable-pip-version-check --no-input --verbose -e .[dev]` (`.[dev]` passed as one argument) | **PASS**, exit 0, 63.72 s. Editable backend probe, metadata, editable wheel, project, runtime dependencies, and dev dependencies all completed offline. |

### Test and quality checks

| Check | Exact command | Exit | Result |
|---|---|---:|---|
| Full suite + coverage | `%TEMP%\\driftguard-dev-verified-env-20261027\\Scripts\\python.exe -m pytest -q --cov=driftguard --cov-report=term-missing --cov-report=xml:%TEMP%\\driftguard-verification-coverage.xml` with `COVERAGE_FILE=%TEMP%\\driftguard-verification-coverage` | 1 | **FAIL**: 226 passed, 1 failed in 99.47 s (command elapsed 106.25 s). Failure: `tests/test_v11_core.py::test_large_suite_runs_in_reasonable_time`; 3,000-case `run_suite` took 18.70 s against its 15 s limit. Coverage total 96.71%; configured 90.0% threshold was reached. XML report was created in temp. |
| Ruff lint | `%TEMP%\\driftguard-dev-verified-env-20261027\\Scripts\\python.exe -m ruff check .` | 0 | **PASS**, `All checks passed!` |
| Ruff format | `%TEMP%\\driftguard-dev-verified-env-20261027\\Scripts\\python.exe -m ruff format --check .` | 1 (final rerun) | **FAIL**: 4 files would be reformatted: `src/driftguard/diff.py`, `src/driftguard/models.py`, and their generated `build/lib/driftguard` copies. The first run also encountered invalid UTF-8 in this report due to a previous append; the report was re-encoded as UTF-8 and the formatter rerun. The final failure is the four Python formatting findings. Application source was not changed. |
| Mypy | `%TEMP%\\driftguard-dev-verified-env-20261027\\Scripts\\python.exe -m mypy` | 0 | **PASS**, `Success: no issues found in 21 source files`. |

No source change was made, so CLI/regression/API/dashboard smoke checks were not rerun in this verification pass; earlier runtime-only smoke evidence remains recorded above. Since pytest and Ruff format did not both pass, full verification is **BLOCKED**. The test failure and formatting findings were not altered or suppressed. No release ZIP was rebuilt.
