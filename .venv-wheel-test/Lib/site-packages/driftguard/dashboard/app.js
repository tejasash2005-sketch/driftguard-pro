"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const TOKEN_KEY = "driftguard.token";
  let currentId = null;
  let currentReport = null;
  let expanded = new Set();

  // DOM is built with textContent only, so report data can never inject markup.
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children || [])) {
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  const svg = (tag, attrs) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
    return n;
  };
  const pct = (v) => (v == null ? "n/a" : (v * 100).toFixed(1) + "%");
  const num = (v) => (v == null ? "n/a" : Number(v).toPrecision(4).replace(/\.?0+(e|$)/, "$1"));
  const badge = (s) => el("span", { class: "badge " + s, text: s });

  function notice(msg, isError) {
    const n = $("notice");
    n.textContent = msg || "";
    n.className = "notice" + (isError ? " err" : "") + (msg ? "" : " hidden");
  }

  class AuthError extends Error {}

  function authHeaders() {
    let token = null;
    try { token = sessionStorage.getItem(TOKEN_KEY); } catch (_) { /* storage blocked */ }
    return token ? { Authorization: "Bearer " + token } : {};
  }

  async function rawFetch(path, options) {
    const opts = Object.assign({}, options);
    opts.headers = Object.assign({}, authHeaders(), opts.headers || {});
    const res = await fetch(path, opts);
    if (res.status === 401) {
      $("token-form").classList.remove("hidden");
      throw new AuthError("Authentication required: enter the API token above.");
    }
    return res;
  }

  async function api(path, options) {
    const res = await rawFetch(path, options);
    if (res.status === 204) return null;
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON body */ }
    if (!res.ok) {
      let msg = "Request failed (" + res.status + ")";
      if (body && body.error) msg = body.error.message;
      else if (body && Array.isArray(body.detail)) msg = body.detail.map((d) => d.msg).join("; ");
      throw new Error(msg);
    }
    return body;
  }
  const postJson = (path, payload) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

  function renderOverview(r) {
    const s = r.summary, m = r.metadata;
    const root = $("overview");
    root.replaceChildren(el("div", { class: "hero" }, [
      el("h2", { text: m.suite_name }), badge(r.status),
      el("span", { class: "muted small mono", text: "run " + m.run_id + " \u00b7 " + m.generated_at + " \u00b7 seed " + m.config.seed }),
    ]));
    const bar = el("i");
    bar.style.width = ((s.pass_rate || 0) * 100).toFixed(1) + "%";
    const card = (label, value, extra) => el("div", { class: "card" }, [el("b", { text: value }), el("span", { text: label }), extra || ""]);
    root.append(el("div", { class: "cards" }, [
      card("Pass rate", pct(s.pass_rate), el("div", { class: "bar" }, [bar])),
      card("Weighted pass rate", pct(s.weighted_pass_rate)),
      card("Total cases", String(s.total)), card("Passed", String(s.passed)), card("Failed", String(s.failed)),
      card("Errors / inconclusive", s.errors + " / " + s.inconclusive),
    ]));
  }

  function renderDrift(r) {
    const head = el("tr", {}, ["Metric", "Pairs", "Mean baseline", "Mean candidate", "Mean diff", "95% CI", "p-value", "Significant?"].map((h) => el("th", { text: h })));
    const rows = r.summary.drift.map((m) => {
      const ci = m.ci_low == null ? "n/a" : "[" + num(m.ci_low) + ", " + num(m.ci_high) + "]";
      const sig = m.significant === true ? "yes" : m.significant === false ? "no" : "not tested";
      return el("tr", { title: m.note || "" }, [m.metric, m.n_pairs, num(m.mean_baseline), num(m.mean_candidate), num(m.mean_diff), ci, num(m.p_value), sig].map((v) => el("td", { text: String(v) })));
    });
    $("drift-table").replaceChildren(el("thead", {}, [head]), el("tbody", {}, rows));
  }

  function renderReasons(r) {
    const entries = Object.entries(r.summary.failure_reasons || {});
    $("reasons").replaceChildren(...(entries.length
      ? entries.map(([code, n]) => el("span", { class: "chip", text: code + " \u00d7 " + n }))
      : [el("span", { class: "empty", text: "No failures \u2014 nothing to report." })]));
  }

  function detailRow(c) {
    const pre = (title, text) => el("div", {}, [el("h4", { text: title }), el("pre", { text: text == null ? "(none)" : text })]);
    const checks = c.assertions.length ? c.assertions.map((a) => (a.passed ? "PASS " : "FAIL ") + a.type + ": " + a.message).join("\n") : "(no assertions)";
    const metrics = c.drift && c.drift.metrics.length
      ? c.drift.metrics.map((m) => m.name + ": " + num(m.baseline) + " \u2192 " + num(m.candidate) + (m.pct_change == null ? "" : " (" + (m.pct_change >= 0 ? "+" : "") + m.pct_change.toFixed(1) + "%)") + (m.exceeded ? "  EXCEEDS LIMIT" : "")).join("\n")
      : "(no operational metrics)";
    const jd = c.drift && c.drift.json_diff;
    const jsonInfo = jd ? ["added: " + (jd.added.join(", ") || "-"), "removed: " + (jd.removed.join(", ") || "-"), "type changed: " + (jd.type_changed.join(", ") || "-"), "values changed: " + (jd.value_changed.join(", ") || "-")].join("\n") : "(not JSON)";
    return el("tr", { class: "detail" }, [el("td", { colspan: "5" }, [el("div", { class: "detail-grid" }, [
      pre("Baseline output", c.baseline_preview), pre("Candidate output", c.candidate_preview),
      pre("Assertions", checks), pre("Operational metrics", metrics), pre("JSON diff", jsonInfo),
    ])])]);
  }

  function renderCases(r) {
    const filter = $("filter").value;
    const rows = r.results.filter((c) => filter === "all" ? true : filter === "failed" ? c.status !== "PASS" : c.status === filter);
    const head = el("tr", {}, ["ID", "Status", "Weight", "Similarity", "Details"].map((h) => el("th", { text: h })));
    const body = [];
    for (const c of rows) {
      const details = c.failure_reasons.length
        ? el("ul", { class: "reasons" }, c.failure_reasons.map((x) => el("li", { text: x })))
        : el("span", { class: "muted", text: "All checks passed" });
      const tr = el("tr", { class: "case-row", tabindex: "0", "aria-expanded": expanded.has(c.id) ? "true" : "false", title: "Click to show details" }, [
        el("td", { class: "mono", text: c.id }), el("td", {}, [badge(c.status)]), el("td", { text: String(c.weight) }),
        el("td", { text: c.drift ? c.drift.similarity.toFixed(3) : "n/a" }), el("td", {}, [details]),
      ]);
      const toggle = () => { expanded.has(c.id) ? expanded.delete(c.id) : expanded.add(c.id); renderCases(r); };
      tr.addEventListener("click", toggle);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      body.push(tr);
      if (expanded.has(c.id)) body.push(detailRow(c));
    }
    if (!body.length) body.push(el("tr", {}, [el("td", { colspan: "5", class: "empty", text: "No cases match this filter." })]));
    $("cases-table").replaceChildren(el("thead", {}, [head]), el("tbody", {}, body));
  }

  async function renderTrend(r) {
    const box = $("trend");
    try {
      const pts = await api("/api/trends?suite=" + encodeURIComponent(r.metadata.suite_name) + "&limit=30");
      if (pts.length < 2) { box.replaceChildren(el("span", { class: "empty", text: "Run this suite more than once to see a trend (" + pts.length + " run so far)." })); return; }
      const W = 640, H = 140, L = 34, R = 10, T = 12, B = 22;
      const x = (i) => L + (i * (W - L - R)) / (pts.length - 1);
      const y = (v) => T + (1 - (v == null ? 0 : v)) * (H - T - B);
      const s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Pass rate over " + pts.length + " runs" });
      for (const g of [0, 0.5, 1]) {
        s.append(svg("line", { class: "axis", x1: L, x2: W - R, y1: y(g), y2: y(g) }));
        const t = svg("text", { x: 2, y: y(g) + 4 }); t.textContent = Math.round(g * 100) + "%"; s.append(t);
      }
      s.append(svg("polyline", { class: "line", points: pts.map((p, i) => x(i) + "," + y(p.pass_rate)).join(" ") }));
      pts.forEach((p, i) => {
        const dot = svg("circle", { class: "dot " + p.status, cx: x(i), cy: y(p.pass_rate), r: p.run_id === r.metadata.run_id ? 6 : 4 });
        const tip = svg("title"); tip.textContent = p.generated_at + " \u2014 " + p.status + " \u2014 " + pct(p.pass_rate); dot.append(tip);
        s.append(dot);
      });
      box.replaceChildren(s);
    } catch (e) { box.replaceChildren(el("span", { class: "empty", text: "Trend unavailable: " + e.message })); }
  }

  function diffGroup(title, items, cls) {
    if (!items.length) return null;
    return el("div", { class: "diff-group" }, [el("h3", { text: title + " (" + items.length + ")" }),
      el("ul", { class: "reasons" }, items.map((c) => el("li", {}, [
        el("span", { class: "mono", text: c.id + " " }),
        c.old_status ? badge(c.old_status) : "new", " \u2192 ", c.new_status ? badge(c.new_status) : "removed",
        cls === "bad" && c.reasons && c.reasons[0] ? el("span", { class: "muted small", text: "  " + c.reasons[0] }) : "",
      ])))]);
  }

  async function renderDiff() {
    const old = $("compare-select").value;
    const out = $("diff-out");
    if (!old || !currentId) { out.textContent = "Select an earlier run to see regressions, fixes and added or removed cases."; return; }
    if (old === currentId) { out.textContent = "Pick a different run to compare against."; return; }
    try {
      const d = await api("/api/diff?old=" + old + "&new=" + currentId);
      const summary = el("div", { class: "diff-summary" }, [
        el("span", { class: "chip" + (d.regressions.length ? "" : " ok"), text: d.regressions.length + " regressed" }),
        el("span", { class: "chip ok", text: d.fixed.length + " fixed" }),
        el("span", { class: "chip neutral", text: d.added.length + " added" }),
        el("span", { class: "chip neutral", text: d.removed.length + " removed" }),
        el("span", { class: "chip neutral", text: d.unchanged + " unchanged" }),
        d.pass_rate_delta == null ? "" : el("span", { class: "muted", text: "pass rate " + (d.pass_rate_delta >= 0 ? "+" : "") + (d.pass_rate_delta * 100).toFixed(1) + " points" }),
      ]);
      out.replaceChildren(summary, ...[diffGroup("Regressed", d.regressions, "bad"), diffGroup("Changed", d.changed, "bad"), diffGroup("Fixed", d.fixed, "ok"), diffGroup("Added", d.added, "bad"), diffGroup("Removed", d.removed, "neutral")].filter(Boolean));
    } catch (e) { out.textContent = e.message; }
  }

  function render(r) {
    currentReport = r;
    renderOverview(r); renderDrift(r); renderReasons(r); renderCases(r);
    renderTrend(r);
    const others = Array.from($("run-select").options).filter((o) => o.value !== r.metadata.run_id);
    $("compare-select").replaceChildren(el("option", { value: "", text: "\u2014 choose a run \u2014" }), ...others.map((o) => el("option", { value: o.value, text: o.textContent })));
    renderDiff();
  }

  async function loadRuns(selectId) {
    const runs = await api("/api/runs?limit=100");
    const sel = $("run-select");
    sel.replaceChildren(...runs.map((x) => el("option", { value: x.run_id, text: x.suite_name + " \u2014 " + x.status + " (" + x.run_id + ")" })));
    $("btn-delete").disabled = !runs.length;
    if (runs.length) {
      currentId = selectId && runs.some((x) => x.run_id === selectId) ? selectId : runs[0].run_id;
      sel.value = currentId;
      expanded = new Set();
      render(await api("/api/runs/" + currentId));
    } else {
      currentId = null; currentReport = null;
      $("overview").replaceChildren(el("div", { class: "empty", text: "No runs yet. Use \u201cRun demo\u201d or upload a suite." }));
    }
    return runs.length;
  }

  async function guarded(fn) {
    try { await fn(); } catch (e) { notice(e.message, !(e instanceof AuthError) || true); }
  }

  async function runExample(name) {
    await guarded(async () => {
      notice("Running " + name + "\u2026");
      const report = await postJson("/api/runs", { example: name });
      await loadRuns(report.metadata.run_id);
      notice("");
    });
  }

  async function uploadSuite(file) {
    await guarded(async () => {
      if (file.size > 5 * 1024 * 1024) throw new Error("File is larger than 5 MB.");
      let suite;
      try { suite = JSON.parse(await file.text()); } catch (_) { throw new Error("That file is not valid JSON."); }
      const report = await postJson("/api/runs", { suite });
      await loadRuns(report.metadata.run_id);
      notice("");
    });
  }

  async function download(format) {
    await guarded(async () => {
      if (!currentId) return;
      const res = await rawFetch("/api/runs/" + currentId + "/report?format=" + format);
      if (!res.ok) throw new Error("Download failed (" + res.status + ")");
      const ext = { json: "json", html: "html", junit: "junit.xml", md: "md" }[format];
      const url = URL.createObjectURL(await res.blob());
      const a = el("a", { href: url, download: "driftguard-" + currentId + "." + ext });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }

  $("btn-demo").addEventListener("click", () => runExample("demo"));
  $("btn-regression").addEventListener("click", () => runExample("regression"));
  $("filter").addEventListener("change", () => currentReport && renderCases(currentReport));
  $("compare-select").addEventListener("change", renderDiff);
  document.querySelectorAll("button[data-format]").forEach((b) => b.addEventListener("click", () => download(b.dataset.format)));
  $("btn-delete").addEventListener("click", () => guarded(async () => {
    if (!currentId || !window.confirm("Delete run " + currentId + "?")) return;
    await api("/api/runs/" + currentId, { method: "DELETE" });
    await loadRuns();
    notice("Run deleted.");
  }));
  $("run-select").addEventListener("change", (e) => guarded(async () => {
    currentId = e.target.value; expanded = new Set(); render(await api("/api/runs/" + currentId));
  }));
  $("file-input").addEventListener("change", (e) => { if (e.target.files[0]) uploadSuite(e.target.files[0]); e.target.value = ""; });
  $("token-form").addEventListener("submit", (e) => {
    e.preventDefault();
    try { sessionStorage.setItem(TOKEN_KEY, $("token-input").value.trim()); } catch (_) { /* ignore */ }
    $("token-input").value = "";
    $("token-form").classList.add("hidden");
    notice("");
    init();
  });

  async function init() {
    try {
      const cfg = await (await fetch("/api/config")).json();
      if (cfg.auth_required && !authHeaders().Authorization) {
        $("token-form").classList.remove("hidden");
        notice("This server requires an API token.");
        return;
      }
      if (!(await loadRuns())) {
        // First visit: seed with the bundled examples so the dashboard shows real data.
        await postJson("/api/runs", { example: "demo" });
        const seeded = await postJson("/api/runs", { example: "regression" });
        await loadRuns(seeded.metadata.run_id);
      }
    } catch (e) {
      if (e instanceof AuthError) {
        try { sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* ignore */ }
        notice("The API token was rejected. Enter a valid token.", true);
      } else notice("Could not load runs: " + e.message, true);
    }
  }
  init();
})();
