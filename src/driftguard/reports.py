"""JSON, HTML and text report rendering."""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import Report, ReportDiff, Status

_STATUS_CLASS = {
    Status.PASS: "pass",
    Status.FAIL: "fail",
    Status.ERROR: "error",
    Status.INCONCLUSIVE: "inconclusive",
}


def report_to_json(report: Report) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}g}"


def render_text(report: Report) -> str:
    meta, summary = report.metadata, report.summary
    lines = [
        f"DriftGuard report: {meta.suite_name}  (run {meta.run_id})",
        f"Status: {report.status.value}   exit code {report.status.exit_code}",
        f"Cases: {summary.total}  pass={summary.passed} fail={summary.failed} "
        f"error={summary.errors} inconclusive={summary.inconclusive}",
        f"Pass rate: {_pct(summary.pass_rate)}   Weighted pass rate: "
        f"{_pct(summary.weighted_pass_rate)}",
        "",
    ]
    for result in report.results:
        lines.append(f"[{result.status.value:<12}] {result.id}")
        for reason in result.failure_reasons:
            lines.append(f"    - {reason}")
    if summary.drift:
        lines += ["", "Drift summary (candidate vs baseline):"]
        for m in summary.drift:
            ci = (
                f"CI[{_num(m.ci_low)}, {_num(m.ci_high)}]"
                if m.ci_low is not None and m.ci_high is not None
                else "CI n/a"
            )
            if m.metric == "similarity":
                lines.append(f"  similarity: mean={_num(m.mean_candidate)} {ci} (n={m.n_pairs})")
            else:
                sig = {True: "yes", False: "no", None: "not tested"}[m.significant]
                lines.append(
                    f"  {m.metric}: mean diff={_num(m.mean_diff)} {ci} "
                    f"p={_num(m.p_value)} significant={sig} (n={m.n_pairs})"
                )
    if summary.failure_reasons:
        lines += ["", "Failure summary:"]
        lines += [f"  {code}: {count}" for code, count in summary.failure_reasons.items()]
    return "\n".join(lines) + "\n"


_CSS = """
:root{color-scheme:light dark;--bg:#f6f7f9;--fg:#15181d;--card:#fff;--muted:#5f6b7a;
--line:#e1e5ea;--pass:#1a7f4b;--fail:#c62828;--error:#b45309;--inc:#5b6475}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--fg:#e8ebef;--card:#171c23;
--muted:#97a3b3;--line:#2a323d;--pass:#4cc38a;--fail:#ff6b6b;--error:#f5a524;--inc:#9aa5b8}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px}
h1{margin:0 0 4px}h2{margin:28px 0 10px;font-size:1.1rem}
.meta{color:var(--muted);font-size:.9rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:1.5rem}.card span{color:var(--muted);font-size:.8rem}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:.8rem;
border:1px solid currentColor}
.pass{color:var(--pass)}.fail{color:var(--fail)}.error{color:var(--error)}
.inconclusive{color:var(--inc)}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line)}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;
font-size:.9rem}
th{color:var(--muted);font-weight:600}
ul{margin:4px 0;padding-left:18px}
"""


def render_html(report: Report) -> str:
    e = html.escape
    meta, summary = report.metadata, report.summary
    cls = _STATUS_CLASS[report.status]
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>DriftGuard report: {e(meta.suite_name)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>{e(meta.suite_name)}</h1>",
        f"<p class='meta'>Run <code>{e(meta.run_id)}</code> &middot; "
        f"generated {e(meta.generated_at)}"
        f" &middot; DriftGuard {e(meta.driftguard_version)} &middot; suite sha256 "
        f"<code>{e(meta.suite_sha256[:12])}</code> &middot; seed {meta.config.seed} &middot; "
        f"similarity: {e(meta.config.similarity)}</p>",
        f"<p><span class='badge {cls}'>{e(report.status.value)}</span> "
        f"exit code {report.status.exit_code}</p>",
        "<div class='cards'>",
    ]
    cards = [
        ("Cases", str(summary.total)),
        ("Passed", str(summary.passed)),
        ("Failed", str(summary.failed)),
        ("Errors", str(summary.errors)),
        ("Inconclusive", str(summary.inconclusive)),
        ("Pass rate", _pct(summary.pass_rate)),
        ("Weighted pass rate", _pct(summary.weighted_pass_rate)),
    ]
    parts += [f"<div class='card'><b>{e(v)}</b><span>{e(k)}</span></div>" for k, v in cards]
    parts.append("</div>")

    parts.append(
        "<h2>Drift summary</h2><div class='wrap'><table><tr><th>Metric</th><th>n</th>"
        "<th>Mean baseline</th><th>Mean candidate</th><th>Mean diff</th>"
        "<th>CI</th><th>p-value</th><th>Significant?</th></tr>"
    )
    for m in summary.drift:
        ci = "n/a" if m.ci_low is None else f"[{_num(m.ci_low)}, {_num(m.ci_high)}]"
        sig = {True: "yes", False: "no", None: "not tested"}[m.significant]
        parts.append(
            f"<tr title='{e(m.note)}'><td>{e(m.metric)}</td><td>{m.n_pairs}</td>"
            f"<td>{_num(m.mean_baseline)}</td><td>{_num(m.mean_candidate)}</td>"
            f"<td>{_num(m.mean_diff)}</td><td>{ci}</td><td>{_num(m.p_value)}</td><td>{sig}</td></tr>"
        )
    parts.append("</table></div>")
    parts.append(
        "<p class='meta'>CIs: percentile bootstrap, fixed seed. Significance is only "
        "reported when a paired randomization test was run with enough pairs; p-values "
        "are not corrected for multiple metrics.</p>"
    )

    if summary.failure_reasons:
        parts.append("<h2>Failure summary</h2><ul>")
        parts += [f"<li><code>{e(c)}</code>: {n}</li>" for c, n in summary.failure_reasons.items()]
        parts.append("</ul>")

    parts.append(
        "<h2>Test results</h2><div class='wrap'><table><tr><th>ID</th><th>Status</th>"
        "<th>Weight</th><th>Similarity</th><th>Details</th></tr>"
    )
    for r in report.results:
        sim = "n/a" if r.drift is None else f"{r.drift.similarity:.3f}"
        details = "".join(f"<li>{e(x)}</li>" for x in r.failure_reasons)
        details = f"<ul>{details}</ul>" if details else ""
        parts.append(
            f"<tr><td>{e(r.id)}</td><td><span class='badge {_STATUS_CLASS[r.status]}'>"
            f"{e(r.status.value)}</span></td><td>{r.weight:g}</td><td>{sim}</td>"
            f"<td>{details}</td></tr>"
        )
    parts.append("</table></div></main></body></html>\n")
    return "".join(parts)


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.").lower()
    return slug[:80] or "report"


REPORT_FORMATS = ("json", "html", "junit", "md")
_EXTENSIONS = {
    "json": "report.json",
    "html": "report.html",
    "junit": "junit.xml",
    "md": "report.md",
}


def render(report: Report, fmt: str) -> str:
    renderers = {
        "json": report_to_json,
        "html": render_html,
        "junit": render_junit,
        "md": render_markdown,
        "text": render_text,
    }
    if fmt not in renderers:
        raise ValueError(f"unsupported report format: {fmt}")
    return renderers[fmt](report)


def write_report(
    report: Report, directory: str | Path, formats: tuple[str, ...] = ("json", "html")
) -> list[Path]:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    base = slugify(report.metadata.suite_name)
    written: list[Path] = []
    for fmt in formats:
        if fmt not in _EXTENSIONS:
            raise ValueError(f"unsupported report format: {fmt}")
        content = render(report, fmt)
        target = out / f"{base}.{_EXTENSIONS[fmt]}"
        if target.exists() and target.read_text(encoding="utf-8") != content:
            target = out / f"{base}.{report.metadata.run_id}.{_EXTENSIONS[fmt]}"
        target.write_text(content, encoding="utf-8", newline="\n")
        written.append(target)
    return written


_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml_safe(text: str) -> str:
    return _XML_ILLEGAL.sub("?", text)


def render_junit(report: Report) -> str:
    """JUnit XML understood by GitHub, GitLab, Jenkins and most CI dashboards.

    FAIL -> <failure>, ERROR -> <error>, INCONCLUSIVE -> <skipped>. No wall-clock times are
    written so the output is reproducible.
    """
    s = report.summary
    suite = ET.Element(
        "testsuite",
        name=_xml_safe(report.metadata.suite_name),
        tests=str(s.total),
        failures=str(s.failed),
        errors=str(s.errors),
        skipped=str(s.inconclusive),
        time="0",
        timestamp=report.metadata.generated_at,
    )
    props = ET.SubElement(suite, "properties")
    for key, value in (
        ("run_id", report.metadata.run_id),
        ("driftguard_version", report.metadata.driftguard_version),
        ("suite_sha256", report.metadata.suite_sha256),
        ("seed", str(report.metadata.config.seed)),
    ):
        ET.SubElement(props, "property", name=key, value=value)
    for result in report.results:
        case = ET.SubElement(
            suite,
            "testcase",
            classname=_xml_safe(report.metadata.suite_name),
            name=_xml_safe(result.id),
            time="0",
        )
        message = _xml_safe("; ".join(result.failure_reasons))
        if result.status is Status.FAIL:
            ET.SubElement(
                case, "failure", message=message[:500], type=result.failure_codes[0]
            ).text = message
        elif result.status is Status.ERROR:
            ET.SubElement(case, "error", message=message[:500], type="error").text = message
        elif result.status is Status.INCONCLUSIVE:
            ET.SubElement(case, "skipped", message=message[:500])
    ET.indent(suite)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(suite, encoding="unicode") + "\n"
    )


def _md_cell(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def render_markdown(report: Report) -> str:
    """GitHub-flavoured Markdown, suitable for ``$GITHUB_STEP_SUMMARY`` or PR comments."""
    meta, s = report.metadata, report.summary
    icon = {
        Status.PASS: "PASS",
        Status.FAIL: "FAIL",
        Status.ERROR: "ERROR",
        Status.INCONCLUSIVE: "INCONCLUSIVE",
    }[report.status]
    lines = [
        f"## DriftGuard: {_md_cell(meta.suite_name)} - **{icon}**",
        "",
        f"Run `{meta.run_id}` | {s.total} cases | pass rate {_pct(s.pass_rate)} "
        f"(weighted {_pct(s.weighted_pass_rate)}) | {s.failed} failed, {s.errors} errors, "
        f"{s.inconclusive} inconclusive",
        "",
    ]
    bad = [r for r in report.results if r.status is not Status.PASS]
    if bad:
        lines += ["| Case | Status | Reasons |", "|---|---|---|"]
        for r in bad:
            reasons = _md_cell("; ".join(r.failure_reasons))
            lines.append(f"| `{_md_cell(r.id, 60)}` | {r.status.value} | {reasons} |")
        lines.append("")
    if s.drift:
        lines += ["| Metric | n | Mean diff | CI | p | Significant |", "|---|---|---|---|---|---|"]
        for m in s.drift:
            ci = "n/a" if m.ci_low is None else f"[{_num(m.ci_low)}, {_num(m.ci_high)}]"
            sig = {True: "yes", False: "no", None: "not tested"}[m.significant]
            mean = m.mean_candidate if m.metric == "similarity" else m.mean_diff
            lines.append(
                f"| {m.metric} | {m.n_pairs} | {_num(mean)} | {ci} | {_num(m.p_value)} | {sig} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def render_diff_text(diff: ReportDiff) -> str:
    lines = [
        f"DriftGuard diff: {diff.old_suite} ({diff.old_run_id}, {diff.old_status.value}) -> "
        f"{diff.new_suite} ({diff.new_run_id}, {diff.new_status.value})",
        f"regressions={len(diff.regressions)} fixed={len(diff.fixed)} changed={len(diff.changed)} "
        f"added={len(diff.added)} removed={len(diff.removed)} unchanged={diff.unchanged}",
    ]
    if diff.pass_rate_delta is not None:
        lines.append(f"pass rate change: {diff.pass_rate_delta * 100:+.1f} points")
    for title, items in (
        ("REGRESSED", diff.regressions),
        ("FIXED", diff.fixed),
        ("CHANGED", diff.changed),
        ("ADDED", diff.added),
        ("REMOVED", diff.removed),
    ):
        for c in items:
            old = c.old_status.value if c.old_status else "-"
            new = c.new_status.value if c.new_status else "-"
            lines.append(f"  [{title}] {c.id}: {old} -> {new}")
            if title in ("REGRESSED", "CHANGED") and c.reasons:
                lines.append(f"      {c.reasons[0]}")
    verdict = "REGRESSIONS FOUND" if diff.has_regressions else "no regressions"
    return "\n".join(lines + [verdict]) + "\n"


def render_diff_markdown(diff: ReportDiff) -> str:
    verdict = "REGRESSIONS FOUND" if diff.has_regressions else "no regressions"
    lines = [
        f"## DriftGuard diff - **{verdict}**",
        "",
        f"`{diff.old_run_id}` ({diff.old_status.value}) -> `{diff.new_run_id}` "
        f"({diff.new_status.value}); {len(diff.regressions)} regressed, {len(diff.fixed)} fixed, "
        f"{len(diff.added)} added, {len(diff.removed)} removed, {diff.unchanged} unchanged",
        "",
    ]
    rows = [
        (t, c)
        for t, items in (
            ("regressed", diff.regressions),
            ("fixed", diff.fixed),
            ("changed", diff.changed),
            ("added", diff.added),
            ("removed", diff.removed),
        )
        for c in items
    ]
    if rows:
        lines += ["| Kind | Case | Change |", "|---|---|---|"]
        for kind, c in rows:
            old = c.old_status.value if c.old_status else "-"
            new = c.new_status.value if c.new_status else "-"
            lines.append(f"| {kind} | `{_md_cell(c.id, 60)}` | {old} -> {new} |")
        lines.append("")
    return "\n".join(lines) + "\n"
