# Migrating from 1.0 to 1.1

**Short version:** upgrade in place (`python -m pip install -U .`). Existing suites, fixtures,
simulator configs, saved reports, CLI invocations and API clients keep working unchanged.

## What is guaranteed to be the same
* All 1.0 CLI commands, flags and exit codes (PASS 0, FAIL 1, ERROR 2, INCONCLUSIVE 3).
* All 1.0 API routes and response shapes (new fields are additive).
* Suite / fixtures / simulator-config JSON formats. New assertion types are additions.
* Run ids (hash of suite + config) and case statuses: tests compare 1.1 output with reports
  produced by real 1.0 code (`tests/data/report_v1_0_*.json`).
* `driftguard.api.RunStore` still exists (it now lives in `driftguard.store` and is
  re-exported from `driftguard.api`).

## Things that can differ
| Area | Change | Who is affected |
|------|--------|-----------------|
| Similarity for texts over 2,000 tokens | Linear bigram measure replaces `SequenceMatcher` | Only suites with very long outputs; scores can shift slightly, so re-baseline thresholds if they sit near the limit |
| Bootstrap/permutation on large suites | Resamples are capped (`n * resamples <= 4M`); numbers in the last digits can differ because sums no longer use `math.fsum` | Suites with more than ~2,000 cases (a note appears in the report); small suites agree to ~1e-9 relative |
| Report JSON | New `metadata.report_schema_version` field (1.0 reports lack it and load as version 1) | A 1.0 install cannot load 1.1 reports (`extra="forbid"`); use 1.1 everywhere you read them |
| `RunConfig`, `Suite`, ... | Unchanged. `AssertionSpec` is a wider union | Code that `match`es on assertion classes should handle `Contains`, `NotContains`, `Length` |
| Dev tooling | `pytest>=8.4,<10`, `hypothesis` added to the `dev` extra | Contributors: re-run `pip install -e ".[dev]"` |

## Opting in to new features
* **Persistence:** `export DRIFTGUARD_DB=./runs.db` (or `driftguard serve --db runs.db`).
  Without it the API keeps the last 200 runs in memory, as in 1.0.
* **Auth:** `export DRIFTGUARD_API_TOKEN=<16+ random characters>`. Clients send
  `Authorization: Bearer <token>`. `/api/health`, `/api/config` and the dashboard shell stay
  public; everything else under `/api/` requires the token. Without it nothing changes.
* **Body limit:** now always on (10 MiB). Raise with `DRIFTGUARD_MAX_BODY_BYTES` if you post
  larger suites. 1.0 had no limit.
* **CI gating:** save the previous run's JSON report as a CI artifact and run
  `driftguard diff previous.json current.json` to fail only on *new* regressions.

## Rolling back
Delete `DRIFTGUARD_DB` (it is a plain SQLite file) and reinstall 1.0. Reports written by 1.1
need 1.1 to be read back.
