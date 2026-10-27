"""Compare two reports: which cases regressed, were fixed, appeared or disappeared."""

from __future__ import annotations

from .errors import DriftGuardError
from .models import CaseChange, CaseResult, Report, ReportDiff, Status

_SEVERITY = {Status.PASS: 0, Status.INCONCLUSIVE: 1, Status.FAIL: 2, Status.ERROR: 3}


def _delta(old: CaseResult, new: CaseResult) -> float | None:
    if old.drift is None or new.drift is None:
        return None
    return round(new.drift.similarity - old.drift.similarity, 12)


def diff_reports(old: Report, new: Report) -> ReportDiff:
    """Diff ``new`` against ``old`` by case id.

    * ``regressions``: status got more severe (PASS < INCONCLUSIVE < FAIL < ERROR).
    * ``fixed``: status got less severe.
    * ``changed``: same non-PASS status but different failure codes.
    * ``added`` / ``removed``: case ids present on only one side.
    """
    if old.metadata.suite_name != new.metadata.suite_name:
        raise DriftGuardError(
            "reports belong to different suites "
            f"({old.metadata.suite_name!r} and {new.metadata.suite_name!r})"
        )
    if old.metadata.suite_version != new.metadata.suite_version:
        raise DriftGuardError(
            "reports use different suite versions "
            f"({old.metadata.suite_version!r} and {new.metadata.suite_version!r})"
        )
    for report in (old, new):
        if report.metadata.report_schema_version not in (1, 2):
            raise DriftGuardError(
                f"unsupported report schema version: {report.metadata.report_schema_version}"
            )
        ids = [result.id for result in report.results]
        if len(ids) != len(set(ids)):
            raise DriftGuardError("report contains duplicate case IDs")

    old_by_id = {r.id: r for r in old.results}
    new_by_id = {r.id: r for r in new.results}
    diff = ReportDiff(
        old_run_id=old.metadata.run_id,
        new_run_id=new.metadata.run_id,
        old_suite=old.metadata.suite_name,
        new_suite=new.metadata.suite_name,
        old_status=old.status,
        new_status=new.status,
    )
    if old.summary.pass_rate is not None and new.summary.pass_rate is not None:
        diff.pass_rate_delta = round(new.summary.pass_rate - old.summary.pass_rate, 12)
    for case_id, after in new_by_id.items():
        before = old_by_id.get(case_id)
        if before is None:
            diff.added.append(
                CaseChange(
                    id=case_id,
                    new_status=after.status,
                    new_failure_codes=after.failure_codes,
                    reasons=after.failure_reasons,
                )
            )
            continue
        change = CaseChange(
            id=case_id,
            old_status=before.status,
            new_status=after.status,
            similarity_delta=_delta(before, after),
            new_failure_codes=sorted(set(after.failure_codes) - set(before.failure_codes)),
            reasons=after.failure_reasons,
        )
        old_sev, new_sev = _SEVERITY[before.status], _SEVERITY[after.status]
        if new_sev > old_sev:
            diff.regressions.append(change)
        elif new_sev < old_sev:
            diff.fixed.append(change)
        elif after.status is not Status.PASS and set(before.failure_codes) != set(
            after.failure_codes
        ):
            diff.changed.append(change)
        else:
            diff.unchanged += 1
    for case_id, before in old_by_id.items():
        if case_id not in new_by_id:
            diff.removed.append(CaseChange(id=case_id, old_status=before.status))
    return diff
