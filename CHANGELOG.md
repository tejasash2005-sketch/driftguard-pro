# Changelog

## 1.1.2

### Added
- Offline CI regression-gate demonstration with baseline, acceptable candidate, degraded
  candidate, and JSON/JUnit/Markdown reports generated from synthetic local data.
- Bounded optional provider request timeouts (`DRIFTGUARD_PROVIDER_TIMEOUT`, default 30 seconds)
  with SDK retries disabled.
- Repeatable local benchmark script and a README architecture diagram.

## 1.1.1

### Fixed
- `driftguard diff` now rejects reports from different suite identities/versions, duplicate case
  IDs, and unsupported report schema versions instead of returning a misleading comparison.
- Removing a case now fails the regression gate. Added passing cases and improvements still pass.
- Distinct reports for the same suite no longer overwrite each other when written to one directory.
- CI runs its CLI smoke commands with PowerShell on both runner operating systems and has an
  explicit positive/negative diff gate test.

## 1.1.0

### Added
- `driftguard diff OLD.json NEW.json`: compares two saved reports and flags regressions,
  fixes, changed failures and added/removed cases (exit 1 when something got worse).
  Also available as `GET /api/diff` and in the dashboard.
- JUnit XML and GitHub-flavoured Markdown report formats (`--formats junit,md`,
  `driftguard report --format junit|md`, `GET /api/runs/{id}/report?format=junit|md`).
- `driftguard validate` (check suite files without running) and `driftguard schema`
  (JSON Schema for suites, fixtures, simulator configs and reports).
- New assertions: `contains`, `not_contains`, `length`.
- Optional durable run storage: `DRIFTGUARD_DB=/path/runs.db` or `driftguard serve --db`.
- Optional bearer-token auth (`DRIFTGUARD_API_TOKEN`, at least 16 characters) and a request
  body limit (`DRIFTGUARD_MAX_BODY_BYTES`, default 10 MiB, answers 413).
- API: `DELETE /api/runs/{id}`, `limit`/`offset`/`suite` on `GET /api/runs`,
  `GET /api/trends`, `GET /api/config`.
- Dashboard: expandable case details, run-to-run comparison, pass-rate trend chart,
  report downloads (also with auth), delete run, token entry.
- Property-based tests (Hypothesis), golden-file compatibility tests against real 1.0
  reports, coverage gate (90 %), dependency audit job in CI.

### Changed
- Bootstrap/permutation resample counts are capped for large suites
  (`n * resamples <= 4,000,000`, minimum 200) and the report notes when this happens.
  5,000 cases now take ~4 s instead of ~20 s.
- Lexical similarity switches to a linear bigram measure for texts above 2,000 tokens
  (previously quadratic: 20k tokens took ~9 s, now ~0.02 s). Results for shorter texts
  are unchanged.
- Reports carry `metadata.report_schema_version` (1 = DriftGuard 1.0, 2 = this release).
- Dev dependency `pytest` constraint widened to `>=8.4,<10` (a 8.4.2 advisory is fixed in 9.x).

### Compatibility
See [MIGRATION.md](MIGRATION.md). No public function, CLI flag, endpoint or file format of
1.0 was removed.

## 1.0.0
Initial release.
