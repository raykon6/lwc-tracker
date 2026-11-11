/* Verity front end. All untrusted text is written with textContent; no innerHTML anywhere. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const PAGE_SIZE = 50;
  const ATTENTION = new Set(["invalid_url", "not_found", "fetch_error", "parse_error"]);
  const RETRYABLE = new Set(["fetch_error", "parse_error", "cancelled"]);
  const STATUS = {
    completed: { label: "Completed", cls: "completed", order: 0 },
    in_progress: { label: "In progress", cls: "in_progress", order: 1 },
    not_started: { label: "Not started", cls: "not_started", order: 2 },
    not_found: { label: "Profile not found", cls: "attention", order: 3 },
    invalid_url: { label: "Invalid link", cls: "attention", order: 4 },
    fetch_error: { label: "Could not fetch", cls: "attention", order: 5 },
    parse_error: { label: "Unreadable page", cls: "attention", order: 6 },
    cancelled: { label: "Cancelled", cls: "cancelled", order: 7 },
    pending: { label: "Waiting", cls: "pending", order: 8 },
  };
  const FLAGS = {
    shared_profile: { tag: "Shared profile", text: "The same profile link appears in more than one roster row." },
    name_mismatch: { tag: "Name mismatch", text: "The roster name shares no words with the name on the profile. Check that the link belongs to this participant." },
    badges_outside_window: { tag: "Outside window", text: "Some badges were earned outside the campaign window and were not counted." },
  };
  const FILTERS = [
    ["all", "All"], ["completed", "Completed"], ["in_progress", "In progress"],
    ["not_started", "Not started"], ["attention", "Needs attention"], ["flagged", "Flagged"],
  ];

  const state = {
    config: null, token: null, rosterId: null, roster: null, jobId: null, job: null,
    results: new Map(), cursor: 0, pollTimer: null, filter: "all", query: "",
    sortKey: "row", sortDir: 1, page: 0, lastAnnounced: -1,
  };

  // ---------- helpers ------------------------------------------------------------------------
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "style") Object.assign(el.style, v); // CSSOM, allowed by the strict CSP
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? "" : String(v));
      }
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const fmt = (n) => Number(n || 0).toLocaleString();
  const fmtBytes = (b) => (b >= 1048576 ? `${+(b / 1048576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso + "T00:00:00");
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }
  function fmtDuration(s) {
    if (s === null || s === undefined) return "";
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
  }
  const isSafeProfileUrl = (u) => typeof u === "string" && /^https:\/\/www\.skills\.google\/public_profiles\/[0-9a-f-]{36}$/.test(u);

  async function api(path, opts = {}) {
    const headers = { Accept: "application/json", ...(opts.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (opts.method && opts.method !== "GET") headers["X-Verity-Request"] = "1";
    let res;
    try {
      res = await fetch(path, { ...opts, headers, credentials: "same-origin", cache: "no-store" });
    } catch {
      throw new Error("The tracker server is not reachable. Check that it is still running.");
    }
    if (res.status === 401) {
      openAuth();
      throw new Error("Access token required.");
    }
    if (!res.ok) {
      let detail = `Request failed (${res.status}).`;
      try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch { /* keep default */ }
      throw new Error(detail);
    }
    return res;
  }

  function announce(msg) { $("live").textContent = msg; }
  function showError(el, msg) { el.textContent = msg; el.hidden = !msg; }

  // ---------- config & auth ------------------------------------------------------------------
  async function loadConfig() {
    try {
      const res = await api("/api/config");
      state.config = await res.json();
    } catch (e) {
      $("policy-text").textContent = "Server unavailable";
      return;
    }
    const c = state.config;
    $("demo-banner").hidden = !c.demo;
    $("policy-text").textContent = `${c.campaign.required_count} badges required · ${c.http.requests_per_second} request/s`;
    $("dz-hint").textContent = `Up to ${fmtBytes(c.limits.max_upload_bytes)} and ${fmt(c.limits.max_rows)} rows`;
    renderRules();
  }

  function openAuth() {
    const dlg = $("auth");
    if (!dlg.open) dlg.showModal();
  }

  $("auth-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const value = $("auth-token").value.trim();
    if (value.length < 8) { showError($("auth-error"), "Enter the full token."); return; }
    state.token = value;
    try { sessionStorage.setItem("verity-token", value); } catch { /* storage may be blocked */ }
    $("auth").close();
    $("auth-token").value = "";
    await loadConfig();
  });

  // ---------- tabs ---------------------------------------------------------------------------
  const tabs = [$("tab-upload"), $("tab-paste")];
  function selectTab(tab) {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
    }
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => selectTab(t));
    t.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        selectTab(next); next.focus(); e.preventDefault();
      }
    });
  });

  // ---------- roster -------------------------------------------------------------------------
  const dz = $("dropzone");
  ["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("is-over"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) uploadFile(f); });
  $("file-input").addEventListener("change", (e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); e.target.value = ""; });

  async function uploadFile(file) {
    showError($("roster-error"), "");
    const max = state.config?.limits.max_upload_bytes ?? 1048576;
    if (!/\.(csv|txt)$/i.test(file.name)) return showError($("roster-error"), "Choose a .csv file.");
    if (file.size > max) return showError($("roster-error"), `That file is larger than ${fmtBytes(max)}.`);
    if (file.size === 0) return showError($("roster-error"), "That file is empty.");
    const body = new FormData();
    body.append("file", file, file.name);
    try {
      const res = await api("/api/roster", { method: "POST", body });
      acceptRoster(await res.json());
    } catch (e) { showError($("roster-error"), e.message); }
  }

  $("paste-submit").addEventListener("click", async () => {
    showError($("roster-error"), "");
    const text = $("paste-input").value;
    if (!text.trim()) return showError($("roster-error"), "Paste at least one profile link.");
    try {
      const res = await api("/api/roster/text", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
      });
      acceptRoster(await res.json());
    } catch (e) { showError($("roster-error"), e.message); }
  });

  $("load-demo").addEventListener("click", async () => {
    showError($("roster-error"), "");
    try {
      const res = await api("/api/roster/demo", { method: "POST" });
      acceptRoster(await res.json());
    } catch (e) { showError($("roster-error"), e.message); }
  });

  function acceptRoster(data) {
    state.rosterId = data.roster_id;
    state.roster = data;
    const s = data.summary;
    const facts = $("roster-facts");
    facts.replaceChildren(
      ...[["Rows", s.total], ["Valid links", s.valid], ["Invalid links", s.invalid], ["Shared profiles", s.duplicates], ["Unique profiles", s.unique_profiles]]
        .map(([k, v]) => h("div", null, h("dt", { text: k }), h("dd", { text: fmt(v) }))),
    );
    const cols = s.columns;
    const parts = [`Links from “${cols.url}”`];
    parts.push(cols.name ? `names from “${cols.name}”` : "no name column");
    parts.push(cols.email ? `emails from “${cols.email}”` : "no email column");
    $("roster-columns").textContent = parts.join(", ") + "." + (s.warnings.length ? " " + s.warnings.join(" ") : "");

    const issues = data.issues || [];
    $("roster-issues").hidden = issues.length === 0;
    $("roster-issues-summary").textContent = `${issues.length} row${issues.length === 1 ? "" : "s"} need attention`;
    $("roster-issues-list").replaceChildren(...issues.map((r) => h("li", null,
      h("span", { class: "num", text: `Row ${r.row}` }),
      h("span", { text: r.error ? r.error : `Same profile as row ${r.duplicate_of}` }),
    )));

    const unique = s.unique_profiles;
    $("start-run").textContent = unique ? `Verify ${fmt(unique)} profile${unique === 1 ? "" : "s"}` : "Record invalid rows";
    $("start-run").disabled = s.total === 0;
    $("roster-summary").hidden = false;
    $("start-run").focus();
  }

  $("roster-reset").addEventListener("click", () => {
    stopPolling();
    state.rosterId = null; state.roster = null;
    $("roster-summary").hidden = true;
    selectTab($("tab-upload"));
    $("file-input").focus();
  });

  // ---------- runs ---------------------------------------------------------------------------
  $("start-run").addEventListener("click", () => startRun(null));
  $("retry-run").addEventListener("click", () => startRun(state.jobId));

  async function startRun(retryOf) {
    if (!state.rosterId) return;
    showError($("roster-error"), "");
    const payload = { roster_id: state.rosterId, force_refresh: $("force-refresh").checked };
    if (retryOf) payload.retry_of = retryOf;
    try {
      const res = await api("/api/jobs", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const data = await res.json();
      state.jobId = data.job_id;
      state.results = new Map();
      state.cursor = 0;
      state.lastAnnounced = -1;
      state.page = 0;
      ["run-panel", "overview-panel", "results-panel"].forEach((id) => { $(id).hidden = false; });
      document.querySelectorAll(".dock-link").forEach((a) => { a.hidden = false; });
      observeSections();
      $("start-run").disabled = true;
      $("cancel-run").hidden = false;
      $("retry-run").hidden = true;
      $("run-desc").textContent = `Paced at ${state.config?.http.requests_per_second ?? 1} request/s with ${state.config?.http.max_retries ?? 3} retries for transient errors.`;
      announce("Verification started.");
      $("run-panel").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      poll();
    } catch (e) {
      showError($("roster-error"), e.message);
    }
  }

  $("cancel-run").addEventListener("click", async () => {
    if (!state.jobId) return;
    $("cancel-run").disabled = true;
    try { await api(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`, { method: "POST" }); }
    catch (e) { announce(e.message); }
    finally { $("cancel-run").disabled = false; }
  });

  function stopPolling() { if (state.pollTimer) clearTimeout(state.pollTimer); state.pollTimer = null; }

  async function poll() {
    stopPolling();
    if (!state.jobId) return;
    const jobId = state.jobId;
    try {
      const res = await api(`/api/jobs/${encodeURIComponent(jobId)}?since=${state.cursor}`);
      const snap = await res.json();
      if (jobId !== state.jobId) return;
      for (const r of snap.results) state.results.set(r.row, r);
      state.cursor = snap.cursor;
      state.job = snap;
      renderProgress(snap);
      renderOverview();
      renderTable();
      if (snap.state === "running" || snap.state === "queued") {
        state.pollTimer = setTimeout(poll, 1000);
      } else {
        finishRun(snap);
      }
    } catch (e) {
      $("progress-state").textContent = e.message;
      state.pollTimer = setTimeout(poll, 4000);
    }
  }

  function finishRun(snap) {
    $("start-run").disabled = false;
    $("cancel-run").hidden = true;
    const retryable = [...state.results.values()].filter((r) => RETRYABLE.has(r.status)).length;
    $("retry-run").hidden = retryable === 0;
    $("retry-run").textContent = `Retry ${fmt(retryable)} unfinished`;
    const done = snap.counts.completed || 0;
    announce(`Verification ${snap.state === "cancelled" ? "cancelled" : "finished"}. ${done} of ${snap.total} participants completed the campaign.`);
  }

  function renderProgress(snap) {
    const p = pct(snap.done, snap.total);
    $("progress-fill").style.width = `${p}%`;
    $("progress").setAttribute("aria-valuenow", String(p));
    $("progress").setAttribute("aria-valuetext", `${snap.done} of ${snap.total} checked`);
    $("progress-count").textContent = `${fmt(snap.done)} of ${fmt(snap.total)} checked`;
    const bits = [];
    if (snap.rate_per_s) bits.push(`${snap.rate_per_s.toFixed(2)} rows/s`);
    if (snap.eta_s !== null && snap.eta_s !== undefined) bits.push(`about ${fmtDuration(snap.eta_s)} left`);
    else if (snap.elapsed_s) bits.push(`took ${fmtDuration(Math.round(snap.elapsed_s))}`);
    $("progress-rate").textContent = bits.join(" · ");
    const labels = { queued: "Queued", running: "Running", done: "Finished", cancelled: "Cancelled", failed: snap.error || "Stopped" };
    $("progress-state").textContent = labels[snap.state] || "";
    $("progress-state").className = `state-pill${snap.state === "done" ? " is-done" : ["cancelled", "failed"].includes(snap.state) ? " is-stopped" : ""}`;
    const decile = Math.floor(p / 25);
    if (snap.state === "running" && decile !== state.lastAnnounced && p > 0) {
      state.lastAnnounced = decile;
      announce(`${p}% checked.`);
    }
  }

  // ---------- overview -----------------------------------------------------------------------
  function bucketOf(r) {
    if (ATTENTION.has(r.status)) return "attention";
    return r.status;
  }

  function renderOverview() {
    const rows = [...state.results.values()];
    const total = state.job?.total ?? rows.length;
    const count = (fn) => rows.filter(fn).length;
    const completed = count((r) => r.status === "completed");
    const progress = count((r) => r.status === "in_progress");
    const notStarted = count((r) => r.status === "not_started");
    const attention = count((r) => ATTENTION.has(r.status));
    const kpis = [
      ["Completed", completed, "completed", "c-green"],
      ["In progress", progress, "in_progress", "c-blue"],
      ["Not started", notStarted, "not_started", "c-yellow"],
      ["Needs attention", attention, "attention", "c-red"],
    ];
    $("hs-total").textContent = fmt(total);
    $("hs-completed").textContent = fmt(completed);
    $("hs-progress").textContent = fmt(progress);
    $("hs-attention").textContent = fmt(attention);
    $("hs-foot").textContent = state.job && (state.job.state === "running" || state.job.state === "queued") ? "Updating live" : `Last checked ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    $("kpis").replaceChildren(...kpis.map(([label, value, cls, color]) => h("div", { class: "kpi" },
      h("div", { class: "kpi-label" }, h("span", { class: `status bare ${cls}`, "aria-hidden": "true" }), label),
      h("div", { class: `kpi-value ${color}`, text: fmt(value) }),
      h("div", { class: "kpi-sub", text: `${pct(value, total)}% of ${fmt(total)}` }),
    )));

    const verified = rows.filter((r) => ["completed", "in_progress", "not_started"].includes(r.status));
    const req = state.config?.campaign.required_count ?? 10;
    const dist = new Array(req + 1).fill(0);
    for (const r of verified) dist[Math.min(r.badge_count, req)] += 1;
    const maxD = Math.max(1, ...dist);
    const distEl = $("dist-chart");
    if (!verified.length) distEl.replaceChildren(h("p", { class: "chart-empty", text: "Waiting for verified profiles." }));
    else distEl.replaceChildren(...dist.map((n, i) => i).reverse().map((i) => h("div", { class: "hbar compact" },
      h("span", { class: "bar-label num", text: `${i} / ${req}` }),
      h("span", { class: "bar-track", role: "img", "aria-label": `${dist[i]} participants with ${i} badges` },
        h("span", { class: `bar-fill ${i === req ? "f-green" : i === 0 ? "f-red" : "f-muted"}`, style: { width: `${(dist[i] / maxD) * 100}%` } })),
      h("span", { class: "bar-value", text: fmt(dist[i]) }),
    )));

    const required = state.config?.campaign.required_badges ?? [];
    const badgeEl = $("badge-chart");
    if (!verified.length || !required.length) {
      badgeEl.replaceChildren(h("p", { class: "chart-empty", text: required.length ? "Waiting for verified profiles." : "Every badge counts in this campaign, so there is no per-badge breakdown." }));
      return;
    }
    const held = new Map(required.map((t) => [t, 0]));
    for (const r of verified) {
      const missing = new Set(r.missing || []);
      for (const t of required) if (!missing.has(t)) held.set(t, held.get(t) + 1);
    }
    const sorted = [...held.entries()].sort((a, b) => a[1] - b[1]);
    badgeEl.replaceChildren(...sorted.map(([title, n]) => {
      const p = pct(n, verified.length);
      return h("div", { class: "hbar" },
        h("span", { class: "bar-label", title, text: title }),
        h("span", { class: "bar-track", role: "img", "aria-label": `${p}% hold ${title}` },
          h("span", { class: `bar-fill ${p < 50 ? "f-red" : p < 75 ? "f-yellow" : "f-green"}`, style: { width: `${p}%` } })),
        h("span", { class: "bar-value", text: `${p}%` }));
    }));
  }

  // ---------- table --------------------------------------------------------------------------
  function buildFilters() {
    $("filters").replaceChildren(...FILTERS.map(([key, label]) => h("button", {
      type: "button", class: "seg", "data-filter": key, "aria-pressed": String(state.filter === key),
      onclick: () => { state.filter = key; state.page = 0; buildFilters(); renderTable(); },
    }, label, h("span", { class: "count", "data-count": key }))));
  }

  function matchesFilter(r) {
    switch (state.filter) {
      case "all": return true;
      case "attention": return ATTENTION.has(r.status);
      case "flagged": return (r.flags || []).length > 0;
      default: return r.status === state.filter;
    }
  }

  function sortValue(r, key) {
    if (key === "status") return STATUS[r.status]?.order ?? 99;
    if (key === "name") return (r.name || r.display_name || "").toLowerCase();
    if (key === "last_earned") return r.last_earned || "";
    return r[key] ?? 0;
  }

  function visibleRows() {
    const q = state.query.trim().toLowerCase();
    let rows = [...state.results.values()].filter(matchesFilter);
    if (q) rows = rows.filter((r) => [r.name, r.email, r.display_name].some((v) => (v || "").toLowerCase().includes(q)));
    const { sortKey: k, sortDir: d } = state;
    rows.sort((a, b) => {
      const va = sortValue(a, k), vb = sortValue(b, k);
      return (va < vb ? -1 : va > vb ? 1 : 0) * d || a.row - b.row;
    });
    return rows;
  }

  function meter(count, req) {
    const segs = h("span", { class: `segments${count >= req ? " is-complete" : ""}`, "aria-hidden": "true" });
    const n = Math.min(req, 20);
    const on = Math.round((Math.min(count, req) / req) * n);
    for (let i = 0; i < n; i++) segs.append(h("span", { class: i < on ? "on" : "" }));
    return h("div", { class: "meter" }, segs,
      h("span", { class: "meter-text" }, String(count), h("small", { text: ` / ${req}` })));
  }

  function renderTable() {
    const all = [...state.results.values()];
    for (const [key] of FILTERS) {
      const el = document.querySelector(`[data-count="${key}"]`);
      if (!el) continue;
      const saved = state.filter; state.filter = key;
      el.textContent = fmt(all.filter(matchesFilter).length);
      state.filter = saved;
    }

    const rows = visibleRows();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages - 1);
    const start = state.page * PAGE_SIZE;
    const slice = rows.slice(start, start + PAGE_SIZE);
    const req = state.config?.campaign.required_count ?? 10;

    $("tbody").replaceChildren(...slice.map((r) => {
      const st = STATUS[r.status] || STATUS.pending;
      const who = r.name || r.display_name || `Row ${r.row}`;
      const notes = h("div", { class: "tags" }, ...(r.flags || []).map((f) => h("span", { class: "tag", text: FLAGS[f]?.tag || f })));
      const notesCell = r.error ? h("span", { class: "err-text", text: r.error }) : notes;
      return h("tr", null,
        h("td", { class: "col-row num", text: String(r.row) }),
        h("td", null,
          h("div", { class: "who-name", title: who, text: who }),
          h("div", { class: "who-email", title: r.email || "", text: r.email || (r.display_name && r.name ? `Profile: ${r.display_name}` : "") })),
        h("td", null, ATTENTION.has(r.status) || r.status === "cancelled" ? h("span", { class: "muted", text: "—" }) : meter(r.badge_count, req)),
        h("td", null, h("span", { class: `status ${st.cls}`, text: st.label })),
        h("td", { class: "num col-date", text: fmtDate(r.last_earned) }),
        h("td", null, notesCell),
        h("td", null, h("button", { type: "button", class: "btn btn-outline btn-small", "aria-label": `Details for ${who}`, onclick: (e) => openDetail(r, e.currentTarget) }, "Details")),
      );
    }));
    $("empty").hidden = slice.length > 0;
    $("pager-text").textContent = rows.length ? `Showing ${fmt(start + 1)}–${fmt(start + slice.length)} of ${fmt(rows.length)}` : "";
    $("prev-page").disabled = state.page === 0;
    $("next-page").disabled = state.page >= pages - 1;

    document.querySelectorAll("th[aria-sort]").forEach((th) => {
      const key = th.querySelector(".sort")?.dataset.key;
      th.setAttribute("aria-sort", key === state.sortKey ? (state.sortDir === 1 ? "ascending" : "descending") : "none");
    });
  }

  document.querySelectorAll(".sort").forEach((btn) => btn.addEventListener("click", () => {
    const key = btn.dataset.key;
    if (state.sortKey === key) state.sortDir *= -1;
    else { state.sortKey = key; state.sortDir = key === "badge_count" || key === "last_earned" ? -1 : 1; }
    renderTable();
  }));
  let searchTimer;
  $("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.query = e.target.value.slice(0, 120); state.page = 0; renderTable(); }, 120);
  });
  $("prev-page").addEventListener("click", () => { state.page -= 1; renderTable(); });
  $("next-page").addEventListener("click", () => { state.page += 1; renderTable(); });

  // ---------- export -------------------------------------------------------------------------
  async function download(format) {
    if (!state.jobId) return;
    try {
      const res = await api(`/api/jobs/${encodeURIComponent(state.jobId)}/export?format=${format}`);
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const name = (cd.match(/filename="([A-Za-z0-9._-]+)"/) || [])[1] || `lwc-progress.${format}`;
      const url = URL.createObjectURL(blob);
      const a = h("a", { href: url, download: name });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      announce(`Exported ${name}.`);
    } catch (e) { announce(e.message); alert(e.message); }
  }
  $("export-csv").addEventListener("click", () => download("csv"));
  $("export-json").addEventListener("click", () => download("json"));

  // ---------- dialogs ------------------------------------------------------------------------
  let returnFocus = null;
  function openDialog(dlg, opener) {
    returnFocus = opener || document.activeElement;
    dlg.showModal();
  }
  document.querySelectorAll("dialog").forEach((dlg) => {
    dlg.addEventListener("close", () => { if (returnFocus && document.contains(returnFocus)) returnFocus.focus(); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg && dlg.id !== "auth") dlg.close(); });
    dlg.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dlg.close()));
  });

  function openDetail(r, opener) {
    const st = STATUS[r.status] || STATUS.pending;
    const req = state.config?.campaign.required_count ?? 10;
    $("detail-title").textContent = r.name || r.display_name || `Row ${r.row}`;
    const body = [];
    const facts = [
      ["Status", h("span", { class: `status ${st.cls}`, text: st.label })],
      ["Qualifying badges", `${r.badge_count} of ${req}`],
      ["All badges on profile", String(r.total_badges)],
      ["Name on profile", r.display_name || "—"],
      ["Email", r.email || "—"],
      ["Roster row", String(r.row)],
      ["Checked", r.checked_at ? new Date(r.checked_at).toLocaleString() + (r.from_cache ? " (cached)" : "") : "—"],
    ];
    const profile = isSafeProfileUrl(r.profile_url)
      ? h("a", { class: "link", href: r.profile_url, target: "_blank", rel: "noopener noreferrer", text: "Open public profile" })
      : h("span", { text: r.profile_url || "—" });
    facts.push(["Profile", profile]);
    body.push(h("dl", { class: "dl" }, ...facts.flatMap(([k, v]) => [h("dt", { text: k }), h("dd", null, v)])));

    if (r.error) body.push(h("h3", { text: "Problem" }), h("p", { class: "flag-note is-error", text: r.error }));
    if ((r.flags || []).length) {
      body.push(h("h3", { text: "Flags" }), ...r.flags.map((f) => h("p", { class: "flag-note", text: FLAGS[f]?.text || f })));
    }
    if ((r.matched || []).length) {
      body.push(h("h3", { text: `Counted badges (${r.matched.length})` }),
        h("ul", { class: "list" }, ...r.matched.map((b) => h("li", null, h("span", { text: b.title }), h("span", { class: "date", text: fmtDate(b.earned) })))));
    }
    if ((r.missing || []).length && !ATTENTION.has(r.status)) {
      body.push(h("h3", { text: `Still needed (${r.missing.length})` }),
        h("ul", { class: "list missing" }, ...r.missing.map((t) => h("li", null, h("span", { text: t })))));
    }
    if ((r.extra || []).length) {
      body.push(h("h3", { text: `Other badges, not counted (${r.extra.length})` }),
        h("ul", { class: "list" }, ...r.extra.map((b) => h("li", null, h("span", { text: b.title }), h("span", { class: "date", text: fmtDate(b.earned) })))));
    }
    $("detail-body").replaceChildren(...body);
    openDialog($("detail"), opener);
  }

  function renderRules() {
    const c = state.config;
    const body = [
      h("h3", { text: "Completion" }),
      h("p", { text: `A participant completes the campaign with ${c.campaign.required_count} qualifying skill badges.` + (c.campaign.start_date || c.campaign.end_date ? ` Badges count when earned between ${c.campaign.start_date || "the start"} and ${c.campaign.end_date || "today"}.` : "") }),
    ];
    if (c.campaign.required_badges.length) {
      body.push(h("h3", { text: `Qualifying badges (${c.campaign.required_badges.length})` }),
        h("ol", { class: "list" }, ...c.campaign.required_badges.map((t) => h("li", null, h("span", { text: t })))));
    }
    body.push(
      h("h3", { text: "How profiles are read" }),
      h("dl", { class: "dl" },
        h("dt", { text: "Pacing" }), h("dd", { text: `${c.http.requests_per_second} request/s, ${c.http.concurrency} parallel` }),
        h("dt", { text: "Retries" }), h("dd", { text: `${c.http.max_retries}, with backoff and Retry-After` }),
        h("dt", { text: "Cache" }), h("dd", { text: c.http.cache_ttl_seconds ? `${Math.round(c.http.cache_ttl_seconds / 60)} minutes` : "Off" }),
        h("dt", { text: "Accepted links" }), h("dd", { text: "skills.google and cloudskillsboost.google public profiles only" })),
      h("p", { class: "note", text: "Rules are set in campaign.toml on the server, so a browser cannot change them." }),
    );
    $("rules-body").replaceChildren(...body);
  }
  $("open-rules").addEventListener("click", (e) => { if (state.config) openDialog($("rules"), e.currentTarget); });

  // ---------- dock & back to top -----------------------------------------------------------
  const dockLinks = [...document.querySelectorAll(".dock-link")];
  function setCurrent(id) {
    dockLinks.forEach((a) => a.setAttribute("aria-current", String(a.dataset.section === id)));
  }
  // Scroll spy: the current section is the last one whose top has passed 35% of the viewport.
  let spyQueued = false;
  function observeSections() {
    if (spyQueued) return;
    spyQueued = true;
    requestAnimationFrame(() => {
      spyQueued = false;
      const line = window.innerHeight * 0.35;
      let current = "roster";
      for (const a of dockLinks) {
        const el = $(a.dataset.section);
        if (el && !el.hidden && el.getBoundingClientRect().top <= line) current = a.dataset.section;
      }
      setCurrent(current);
    });
  }
  window.addEventListener("scroll", observeSections, { passive: true });
  window.addEventListener("resize", observeSections, { passive: true });
  setCurrent("roster");
  observeSections();
  const toTop = $("to-top");
  window.addEventListener("scroll", () => { toTop.hidden = window.scrollY < 600; }, { passive: true });
  toTop.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    $("main").focus({ preventScroll: true });
  });

  // ---------- boot ---------------------------------------------------------------------------
  try { state.token = sessionStorage.getItem("verity-token"); } catch { state.token = null; }
  buildFilters();
  loadConfig().then(() => { if (state.config?.auth_required && !state.token) openAuth(); });
})();
