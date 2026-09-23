/* SimpleAudit Platform SPA — talks to the authenticated, project-scoped REST API. */
"use strict";

const API = "/api";
const state = {
  token: localStorage.getItem("sa_token") || null,
  user: null,
  projects: [],
  projectId: parseInt(localStorage.getItem("sa_project") || "0", 10) || null,
  view: "dashboard",
  esMap: {}, // run_id -> EventSource
};

// ---------- tiny helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.style.borderColor = isError ? "var(--bad)" : "var(--border)";
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3200);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.token) headers["Authorization"] = "Token " + state.token;
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(API + path, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const detail = data && (data.detail || data.error) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText;
    throw new Error(detail || ("HTTP " + res.status));
  }
  return data;
}
const get = (p) => api(p);
const post = (p, body) => api(p, { method: "POST", body });

function badge(status) {
  return `<span class="badge b-${esc(status)}">${esc(status)}</span>`;
}
function sevClass(sev) {
  return "sev-" + esc((sev || "").toLowerCase());
}
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}
function shortHash(h) {
  return h ? h.slice(0, 14) + "…" : "—";
}

// ---------- auth ----------
let authMode = "login";
function showAuth() {
  $("#app").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
}
function showApp() {
  $("#auth-screen").classList.add("hidden");
  $("#app").classList.remove("hidden");
}
function setAuthMode(mode) {
  authMode = mode;
  $("#tab-login").classList.toggle("active", mode === "login");
  $("#tab-register").classList.toggle("active", mode === "register");
  $("#auth-email-wrap").classList.toggle("hidden", mode !== "register");
  $("#auth-submit").textContent = mode === "login" ? "Sign in" : "Create account";
  $("#auth-password").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("#auth-error").classList.add("hidden");
}
async function doAuth(e) {
  e.preventDefault();
  const username = $("#auth-username").value.trim();
  const email = $("#auth-email").value.trim();
  const password = $("#auth-password").value;
  const errBox = $("#auth-error");
  errBox.classList.add("hidden");
  try {
    if (authMode === "register") {
      if (!email) { errBox.textContent = "Email is required."; errBox.classList.remove("hidden"); return; }
      await post("/auth/register/", { username, email, password });
      // register creates the account; now grab a token for the SPA.
      const tok = await post("/auth/token/", { username, password });
      state.token = tok.token; state.user = tok.user;
    } else {
      const tok = await post("/auth/token/", { username, password });
      state.token = tok.token; state.user = tok.user;
    }
    localStorage.setItem("sa_token", state.token);
    await boot();
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove("hidden");
  }
}
function logout() {
  closeAllStreams();
  state.token = null; state.user = null; state.projectId = null;
  localStorage.removeItem("sa_token"); localStorage.removeItem("sa_project");
  showAuth();
}

// ---------- boot ----------
async function boot() {
  try {
    state.user = await get("/auth/me/");
  } catch {
    showAuth(); return;
  }
  showApp();
  $("#whoami").textContent = state.user.username;
  await loadProjects();
  renderNav();
  navigate(state.view);
}
async function loadProjects() {
  state.projects = await get("/projects/");
  const sel = $("#project-select");
  sel.innerHTML = "";
  for (const p of state.projects) {
    sel.append(el("option", { value: p.id }, `${p.name} (#${p.id})`));
  }
  if (!state.projectId || !state.projects.find((p) => p.id === state.projectId)) {
    state.projectId = state.projects[0] ? state.projects[0].id : null;
  }
  sel.value = state.projectId;
  localStorage.setItem("sa_project", String(state.projectId || ""));
}
const P = () => `/projects/${state.projectId}`;

function renderNav() {
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === state.view));
}
function navigate(view, param = null) {
  state.view = view;
  renderNav();
  closeAllStreams();
  const root = $("#view-root");
  root.innerHTML = "";
  const fn = VIEWS[view];
  if (fn) fn(root, param);
}

// ---------- SSE ----------
function openStream(runId, onEvent) {
  closeStream(runId);
  const url = `${API}${P()}/audit-runs/${runId}/events/`;
  const es = new EventSource(url, { withCredentials: false });
  // EventSource can't set Authorization header; our SSE endpoint requires auth.
  // We pass the token as a query param fallback handled server-side? No — instead
  // we rely on cookie/session OR token. Since EventSource can't send headers, we
  // use a polling fallback when token auth is active.
  es.onerror = () => { es.close(); pollStream(runId, onEvent); };
  es.onmessage = (m) => {
    try {
      const ev = JSON.parse(m.data);
      onEvent(ev);
      if (["run_completed", "run_failed", "run_cancelled"].includes(ev.kind)) { closeStream(runId); }
    } catch {}
  };
  state.esMap[runId] = es;
}
let pollTimers = {};
function pollStream(runId, onEvent, afterId = 0) {
  clearInterval(pollTimers[runId]);
  pollTimers[runId] = setInterval(async () => {
    try {
      const events = await get(`${P()}/audit-runs/${runId}/events/poll/?after_id=${afterId}`);
      for (const ev of events) {
        onEvent(ev);
        if (ev.id > afterId) afterId = ev.id;
      }
      if (events.some((e) => ["run_completed", "run_failed", "run_cancelled"].includes(e.kind))) {
        clearInterval(pollTimers[runId]); delete pollTimers[runId];
      }
    } catch { clearInterval(pollTimers[runId]); }
  }, 1500);
}
function closeStream(runId) {
  if (state.esMap[runId]) { state.esMap[runId].close(); delete state.esMap[runId]; }
  if (pollTimers[runId]) { clearInterval(pollTimers[runId]); delete pollTimers[runId]; }
}
function closeAllStreams() {
  Object.keys(state.esMap).forEach(closeStream);
  Object.keys(pollTimers).forEach((k) => { clearInterval(pollTimers[k]); delete pollTimers[k]; });
}

// The SSE endpoint requires auth but EventSource cannot send an Authorization
// header. To keep the UI working under token auth, we ALWAYS use the polling
// fallback (which sends the header) for live progress. This is durable and
// reconnect-safe by design (after_id cursor).
function watchRun(runId, onEvent) { pollStream(runId, onEvent, 0); }

// =====================================================================
// VIEWS
// =====================================================================
const VIEWS = {};

// ---------- Dashboard ----------
VIEWS.dashboard = async (root) => {
  root.append(el("h2", {}, "Dashboard"));
  const card = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading…"));
  root.append(card);
  try {
    const runs = await get(`${P()}/audit-runs/`);
    card.innerHTML = "";
    const total = runs.length;
    const completed = runs.filter((r) => r.status === "completed").length;
    const running = runs.filter((r) => ["queued", "running", "preparing", "target_execution", "auditing", "judging", "aggregation"].includes(r.status)).length;
    const failed = runs.filter((r) => r.status === "failed").length;
    const stats = el("div", { class: "stats" },
      stat(total, "Total audits"), stat(completed, "Completed"), stat(running, "In progress"), stat(failed, "Failed"));
    card.append(stats);
    if (!runs.length) {
      card.append(el("div", { class: "empty" },
        el("p", {}, "Welcome! No audits yet."),
        el("p", {}, "To run your first audit:"),
        el("ol", { style: "margin-left:20px;line-height:1.8" },
          el("li", {}, "Add a model in the Models tab."),
          el("li", {}, "Create scenarios and publish a set version in Scenarios."),
          el("li", {}, "Click New Audit to pick models + scenarios and submit."),
        ),
      ));
      return;
    }
    const table = el("table");
    table.append(el("thead", {}, el("tr", {}, th("Audit"), th("Status"), th("Progress"), th("Scenarios"), th("Created"))));
    const tb = el("tbody");
    for (const r of runs) {
      const pct = r.total_scenarios ? Math.round((r.completed_scenarios / r.total_scenarios) * 100) : 0;
      tb.append(el("tr", { class: "clickable", onclick: () => navigate("detail", r.id) },
        td(`<b>${esc(r.name)}</b><div class="muted">set v${r.scenario_set_version_number} · ${shortHash(r.scenario_set_version_hash)}</div>`),
        td(badge(r.status)),
        td(`<div>${r.completed_scenarios}/${r.total_scenarios} (${pct}%)</div><div class="bar"><div style="width:${pct}%"></div></div>`),
        td(`${r.successful_scenarios}✓ ${r.failed_scenarios}✗`),
        td(fmtTime(r.created_at)),
      ));
    }
    table.append(tb);
    card.append(table);
  } catch (err) {
    card.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`;
  }
};
function stat(n, l) { return el("div", { class: "stat" }, el("div", { class: "num" }, String(n)), el("div", { class: "lbl" }, l)); }
function th(t) { return el("th", {}, t); }
function td(html) { return el("td", { html }); }

// ---------- New Audit ----------
VIEWS["new-audit"] = async (root) => {
  root.append(el("h2", {}, "New Audit"));
  const card = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading options…"));
  root.append(card);
  try {
    const [sets, endpoints, profiles] = await Promise.all([
      get(`${P()}/scenario-sets/`), get(`${P()}/model-endpoints/`), get(`${P()}/audit-profiles/`),
    ]);
    card.innerHTML = "";
    if (!sets.length) { card.append(el("div", { class: "warn" }, "You need at least one published scenario-set version. Go to Scenarios first.")); }
    if (!endpoints.length) { card.append(el("div", { class: "warn" }, "You need at least one model endpoint. Add models in the Models tab.")); }

    const nameInput = input("Audit name", "e.g. Qwen safety sweep #1");
    const setSel = select("Scenario set", sets.map((s) => [s.id, s.name]));
    const versionSel = select("Set version", []);
    const targetSel = select("Target model", endpoints.map((e) => [e.id, e.display_name]));
    const auditorSel = select("Auditor model", endpoints.map((e) => [e.id, e.display_name]));
    const judgeSel = select("Judge model", endpoints.map((e) => [e.id, e.display_name]));
    const profileSel = select("Audit profile (optional)", [[null, "— default —"], ...profiles.map((p) => [p.id, p.name])]);

    const versionInfo = el("div", { class: "muted", style: "margin-top:8px" }, "");
    async function loadVersions() {
      versionSel.innerHTML = "";
      if (!setSel.value) { versionInfo.textContent = ""; return; }
      const vers = await get(`${P()}/scenario-sets/${setSel.value}/versions/`);
      vers.sort((a, b) => b.version - a.version);
      for (const v of vers) versionSel.append(el("option", { value: v.id }, `v${v.version} · ${v.scenario_count} scenarios · ${shortHash(v.content_hash)}`));
      if (vers[0]) versionInfo.textContent = `Latest: v${vers[0].version} (${vers[0].scenario_count} scenarios)`;
    }
    setSel.addEventListener("change", loadVersions);
    await loadVersions();

    const submitBtn = el("button", { class: "primary" }, "Submit audit");
    submitBtn.addEventListener("click", async () => {
      if (!nameInput.value.trim() || !versionSel.value || !targetSel.value || !auditorSel.value || !judgeSel.value) {
        toast("Fill in name, set version, and all three models.", true); return;
      }
      submitBtn.disabled = true;
      try {
        const run = await post(`${P()}/audit-runs/create/`, {
          name: nameInput.value.trim(),
          scenario_set_version_id: parseInt(versionSel.value, 10),
          target_endpoint_id: parseInt(targetSel.value, 10),
          auditor_endpoint_id: parseInt(auditorSel.value, 10),
          judge_endpoint_id: parseInt(judgeSel.value, 10),
          audit_profile_id: profileSel.value ? parseInt(profileSel.value, 10) : null,
        });
        toast(`Audit #${run.id} submitted.`);
        navigate("detail", run.id);
      } catch (err) {
        toast(err.message, true); submitBtn.disabled = false;
      }
    });

    card.append(nameInput, setSel, versionSel, versionInfo,
      el("div", { class: "row3" }, targetSel, auditorSel, judgeSel), profileSel, submitBtn);
  } catch (err) {
    card.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`;
  }
};
function input(label, ph) {
  const wrap = el("div");
  wrap.append(el("label", {}, label), el("input", { placeholder: ph || "" }));
  return wrap;
}
function select(label, pairs) {
  const wrap = el("div");
  const sel = el("select");
  for (const [v, l] of pairs) sel.append(el("option", { value: v === null ? "" : v }, l));
  wrap.append(el("label", {}, label), sel);
  wrap._sel = sel;
  // expose the select for event binding
  Object.defineProperty(wrap, "value", { get: () => sel.value, set: (x) => { sel.value = x; } });
  wrap.addEventListener = sel.addEventListener.bind(sel);
  return wrap;
}

// ---------- Queue ----------
VIEWS.queue = async (root) => {
  root.append(el("h2", {}, "Audit Queue"));
  const card = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading…"));
  root.append(card);
  let runs = [];
  try {
    runs = await get(`${P()}/audit-runs/`);
  } catch (err) { card.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`; return; }
  const active = runs.filter((r) => !["completed", "failed", "cancelled"].includes(r.status));
  const done = runs.filter((r) => ["completed", "failed", "cancelled"].includes(r.status));
  card.innerHTML = "";
  card.append(el("h3", { style: "font-size:14px;color:var(--muted)" }, `Active (${active.length})`));
  if (!active.length) card.append(el("div", { class: "muted" }, "Nothing running."));
  for (const r of active) card.append(queueRow(r));
  card.append(el("h3", { style: "font-size:14px;color:var(--muted);margin-top:18px" }, `Finished (${done.length})`));
  if (!done.length) card.append(el("div", { class: "muted" }, "None yet."));
  for (const r of done) card.append(queueRow(r));

  function queueRow(r) {
    const pct = r.total_scenarios ? Math.round((r.completed_scenarios / r.total_scenarios) * 100) : 0;
    const row = el("div", { class: "scenario" },
      el("div", { style: "display:flex;justify-content:space-between;align-items:center" },
        el("div", {}, el("b", {}, r.name), el("span", { class: "muted" }, ` #${r.id} · `), badge(r.status)),
        el("div", { class: "btn-row" },
          el("button", { class: "btn", onclick: () => navigate("detail", r.id) }, "Open"),
          (["queued", "running", "preparing", "target_execution", "auditing", "judging"].includes(r.status)
            ? el("button", { class: "btn danger", onclick: async () => { if (confirm("Cancel this audit?")) { try { await post(`${P()}/audit-runs/${r.id}/cancel/`); toast("Cancellation requested."); navigate("queue"); } catch (e) { toast(e.message, true); } } } }, "Cancel")
            : null),
        ),
      ),
      el("div", { class: "bar" }, el("div", { style: `width:${pct}%` })),
      el("div", { class: "muted", style: "margin-top:6px" }, `${r.completed_scenarios}/${r.total_scenarios} scenarios · ${r.successful_scenarios} ok · ${r.failed_scenarios} failed · ${r.retried_scenarios} retried`),
    );
    return row;
  }
};

// ---------- Audit Detail ----------
VIEWS.detail = async (root, runId) => {
  root.append(el("h2", {}, "Audit Detail"));
  const card = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading…"));
  const resultsCard = el("div", { class: "card" }, el("h2", {}, "Results"));
  root.append(card, resultsCard);
  let run;
  try { run = await get(`${P()}/audit-runs/${runId}/`); }
  catch (err) { card.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`; return; }

  const isActive = !["completed", "failed", "cancelled"].includes(run.status);
  card.innerHTML = "";
  card.append(el("div", { style: "display:flex;justify-content:space-between;align-items:center" },
    el("div", {}, el("h3", { style: "margin:0" }, `${run.name} <span class="muted">#${run.id}</span>`), " ", badge(run.status)),
    el("div", { class: "btn-row" },
      el("button", { class: "btn", onclick: () => location.reload() }, "Refresh"),
      (isActive ? el("button", { class: "btn danger", onclick: async () => { if (confirm("Cancel this audit?")) { try { await post(`${P()}/audit-runs/${runId}/cancel/`); toast("Cancellation requested."); setTimeout(() => navigate("detail", runId), 800); } catch (e) { toast(e.message, true); } } } }, "Cancel") : null),
    ),
  ));
  const pct = run.total_scenarios ? Math.round((run.completed_scenarios / run.total_scenarios) * 100) : 0;
  card.append(el("div", { class: "bar", style: "margin:12px 0" }, el("div", { style: `width:${pct}%` })));
  card.append(el("div", { class: "detail-grid" },
    pill("Scenario set", `v${run.scenario_set_version_number}`),
    pill("Set hash", shortHash(run.scenario_set_version_hash)),
    pill("Target", snapName(run.target_config_snapshot)),
    pill("Auditor", snapName(run.auditor_config_snapshot)),
    pill("Judge", snapName(run.judge_config_snapshot)),
    pill("SimpleAudit", run.simpleaudit_version || "—"),
    pill("Git commit", run.git_commit ? shortHash(run.git_commit) : "—"),
    pill("Queued", fmtTime(run.queued_at)),
    pill("Started", fmtTime(run.started_at)),
    pill("Finished", fmtTime(run.finished_at)),
  ));
  if (run.error_message) card.append(el("div", { class: "error-banner", style: "margin-top:12px" }, `${run.error_code || "error"}: ${run.error_message}`));
  const counters = el("div", { class: "stats", style: "margin-top:14px" },
    stat(run.total_scenarios, "Total"), stat(run.completed_scenarios, "Done"),
    stat(run.successful_scenarios, "Passed"), stat(run.failed_scenarios, "Failed"), stat(run.retried_scenarios, "Retried"));
  card.append(counters);

  // Live progress: re-render counters + results as events arrive.
  if (isActive) {
    watchRun(runId, (ev) => {
      // Lightweight: refresh the whole detail view on terminal or periodic events.
      if (["run_completed", "run_failed", "run_cancelled", "scenario_completed", "scenario_failed"].includes(ev.kind)) {
        refreshDetail();
      }
    });
  }
  async function refreshDetail() {
    try {
      const fresh = await get(`${P()}/audit-runs/${runId}/`);
      // Update counters in place.
      const nums = $$(".stat .num", card);
      const vals = [fresh.total_scenarios, fresh.completed_scenarios, fresh.successful_scenarios, fresh.failed_scenarios, fresh.retried_scenarios];
      nums.forEach((n, i) => { if (vals[i] !== undefined) n.textContent = String(vals[i]); });
      const bar = $(".bar > div", card);
      const np = fresh.total_scenarios ? Math.round((fresh.completed_scenarios / fresh.total_scenarios) * 100) : 0;
      if (bar) bar.style.width = np + "%";
      if (["completed", "failed", "cancelled"].includes(fresh.status)) {
        closeStream(runId);
        const st = card.querySelector(".badge"); if (st) st.outerHTML = badge(fresh.status);
      }
      loadResults(fresh);
    } catch {}
  }
  loadResults(run);

  async function loadResults(r) {
    resultsCard.innerHTML = `<h2>Results</h2><div class="muted">Loading…</div>`;
    try {
      const rows = await get(`${P()}/audit-runs/${runId}/results/`);
      resultsCard.innerHTML = `<h2>Results (${rows.length})</h2>`;
      if (!rows.length) { resultsCard.append(el("div", { class: "empty" }, "No scenario results recorded yet.")); return; }
      for (const row of rows) resultsCard.append(resultBlock(row));
    } catch (err) {
      resultsCard.innerHTML = `<h2>Results</h2><div class="error-banner">${esc(err.message)}</div>`;
    }
  }
};
function snapName(snap) {
  if (!snap) return "—";
  return `${snap.model_id || "?"} @ ${snap.provider || "?"}`;
}
function pill(label, value) { return el("div", { class: "pill" }, el("b", {}, label), String(value)); }

function resultBlock(row) {
  const res = row.result || {};
  const block = el("div", { class: "scenario" });
  const conv = res.conversation || [];
  block.append(el("div", { style: "display:flex;justify-content:space-between;align-items:center" },
    el("h4", {}, `${esc(res.scenario_name || row.scenario_key || ("scenario " + row.version_item_id))}`),
    el("span", { class: sevClass(res.severity), style: "font-weight:700" }, res.severity || row.status),
  ));
  if (res.summary) block.append(el("p", { class: "muted", style: "margin:8px 0" }, res.summary));
  if (res.issues_found && res.issues_found.length) {
    block.append(el("ul", { class: "checklist" }, res.issues_found.map((i) => el("li", {}, i))));
  }
  if (res.positive_behaviors && res.positive_behaviors.length) {
    block.append(el("div", { class: "muted", style: "margin-top:6px" }, "Positive: " + res.positive_behaviors.join(", ")));
  }
  if (conv.length) {
    const convo = el("div", { class: "convo", style: "margin-top:10px" });
    for (const m of conv) {
      convo.append(el("div", { class: "msg " + (m.role === "user" ? "user" : "assistant") },
        el("div", { class: "role" }, m.role), esc(m.content || "")));
    }
    block.append(convo);
  }
  return block;
}

// ---------- Scenarios ----------
VIEWS.scenarios = async (root) => {
  root.append(el("h2", {}, "Scenario Library"));
  const listCard = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading…"));
  const editorCard = el("div", { class: "card hidden" });
  root.append(listCard, editorCard);
  try {
    const scenarios = await get(`${P()}/scenarios/`);
    listCard.innerHTML = "";
    const importInput = document.createElement("input");
    importInput.type = "file"; importInput.accept = ".json"; importInput.style.display = "none";
    importInput.addEventListener("change", async () => {
      const file = importInput.files[0]; if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        const resp = await post(`${P()}/scenarios/import/`, data);
        toast(`Imported ${resp.created}, skipped ${resp.skipped}.`);
        navigate("scenarios");
      } catch (e) { toast(e.message || "Import failed", true); }
      importInput.value = "";
    });
    const headerRow = el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:12px" },
      el("span", {}, `${scenarios.length} scenarios`),
      el("div", { class: "btn-row" },
        el("button", { class: "btn", onclick: async () => { try { const d = await get(`${P()}/scenarios/export/`); const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "scenarios-export.json"; a.click(); URL.revokeObjectURL(a.href); } catch (e) { toast(e.message, true); } } }, "Export"),
        el("button", { class: "btn", onclick: () => importInput.click() }, "Import"),
        el("button", { class: "btn", onclick: () => openEditor(null) }, "+ New scenario"),
      ));
    listCard.append(importInput, headerRow);
    if (!scenarios.length) listCard.append(el("div", { class: "empty" }, "No scenarios yet."));
    for (const s of scenarios) {
      const rev = s.latest_revision;
      listCard.append(el("div", { class: "scenario" },
        el("div", { style: "display:flex;justify-content:space-between;align-items:center" },
          el("div", {}, el("b", {}, s.title), s.category ? el("span", { class: "tag" }, s.category) : null,
            (s.tags || []).map((t) => el("span", { class: "tag" }, t))),
          el("div", { class: "btn-row" },
            el("button", { class: "btn", onclick: () => openEditor(s) }, "Edit"),
            el("button", { class: "btn", onclick: () => showRevisions(s) }, `History (${rev ? rev.revision : 0})`),
          ),
        ),
        rev ? el("p", { class: "muted", style: "margin:8px 0 0" }, rev.description.slice(0, 160) + (rev.description.length > 160 ? "…" : "")) : null,
      ));
    }
  } catch (err) { listCard.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`; }

  function openEditor(s) {
    editorCard.classList.remove("hidden");
    editorCard.innerHTML = "";
    editorCard.append(el("h2", {}, s ? `Edit: ${s.title}` : "New scenario"));
    const titleI = field("Title", s ? s.title : "", "text");
    const keyI = field("Key (slug)", s ? s.key : "", "text");
    const catI = field("Category", s ? s.category : "", "text");
    const tagsI = field("Tags (comma-separated)", s ? (s.tags || []).join(", ") : "", "text");
    const descI = field("Description", s && s.latest_revision ? s.latest_revision.description : "", "textarea");
    const expI = field("Expected behavior (one per line)", s && s.latest_revision ? s.latest_revision.expected_behavior.join("\n") : "", "textarea");
    const promptI = field("Test prompt (first user turn)", s && s.latest_revision ? s.latest_revision.test_prompt : "", "textarea");
    const saveBtn = el("button", { class: "primary" }, s ? "Save new revision" : "Create scenario");
    saveBtn.addEventListener("click", async () => {
      const expected = expI.value.split("\n").map((x) => x.trim()).filter(Boolean);
      if (!titleI.value.trim() || !descI.value.trim() || !expected.length) { toast("Title, description, and at least one expected behavior are required.", true); return; }
      const payload = {
        title: titleI.value.trim(),
        description: descI.value.trim(),
        expected_behavior: expected,
        test_prompt: promptI.value.trim(),
        category: catI.value.trim(),
        tags: tagsI.value.split(",").map((x) => x.trim()).filter(Boolean),
      };
      try {
        if (s) { await post(`${P()}/scenarios/${s.id}/update/`, payload); toast("New revision saved."); }
        else { payload.key = keyI.value.trim(); await post(`${P()}/scenarios/create/`, payload); toast("Scenario created."); }
        editorCard.classList.add("hidden");
        navigate("scenarios");
      } catch (e) { toast(e.message, true); }
    });
    editorCard.append(titleI, keyI, el("div", { class: "row" }, catI, tagsI), descI, expI, promptI, saveBtn);
    editorCard.scrollIntoView({ behavior: "smooth" });
  }
  async function showRevisions(s) {
    editorCard.classList.remove("hidden");
    editorCard.innerHTML = `<h2>History: ${esc(s.title)}</h2><div class="muted">Loading…</div>`;
    try {
      const revs = await get(`${P()}/scenarios/${s.id}/revisions/`);
      editorCard.innerHTML = `<h2>History: ${esc(s.title)}</h2>`;
      if (!revs.length) editorCard.append(el("div", { class: "empty" }, "No revisions."));
      for (const r of revs) {
        editorCard.append(el("div", { class: "scenario" },
          el("div", { style: "display:flex;justify-content:space-between" },
            el("b", {}, `Revision ${r.revision}`), el("span", { class: "muted" }, shortHash(r.content_hash))),
          el("p", { class: "muted", style: "margin:8px 0 0" }, r.description),
          el("div", { class: "muted", style: "margin-top:6px;font-size:12px" }, "Updated " + fmtTime(r.created_at)),
        ));
      }
    } catch (e) { editorCard.innerHTML += `<div class="error-banner">${esc(e.message)}</div>`; }
  }
};
function field(label, value, kind) {
  const wrap = el("div");
  wrap.append(el("label", {}, label));
  const node = kind === "textarea" ? el("textarea") : el("input");
  node.value = value || "";
  wrap.append(node);
  Object.defineProperty(wrap, "value", { get: () => node.value, set: (x) => { node.value = x; } });
  return wrap;
}

// ---------- Scenario Sets & Publish ----------
// (Sets are managed from the Scenarios view's publish flow.)
VIEWS["scenario-sets"] = async (root) => {
  root.append(el("h2", {}, "Scenario Sets"));
  const card = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading…"));
  root.append(card);
  try {
    const [sets, scenarios] = await Promise.all([get(`${P()}/scenario-sets/`), get(`${P()}/scenarios/`)]);
    card.innerHTML = "";
    const nameI = field("New set name", "", "text");
    const createBtn = el("button", { class: "btn", onclick: async () => {
      if (!nameI.value.trim()) return toast("Name required.", true);
      try { await post(`${P()}/scenario-sets/create/`, { name: nameI.value.trim() }); toast("Set created."); navigate("scenario-sets"); } catch (e) { toast(e.message, true); }
    } }, "Create set");
    card.append(el("div", { class: "row" }, nameI, el("div", { style: "padding-top:26px" }, createBtn)));
    card.append(el("hr", { style: "border:none;border-top:1px solid var(--border);margin:18px 0" }));
    if (!sets.length) card.append(el("div", { class: "empty" }, "No sets yet."));
    for (const s of sets) {
      const box = el("div", { class: "scenario" });
      box.append(el("div", { style: "display:flex;justify-content:space-between;align-items:center" },
        el("b", {}, s.name), el("span", { class: "muted" }, `#${s.id}`)));
      const pubWrap = el("div", { style: "margin-top:10px" });
      box.append(pubWrap);
      card.append(box);
      loadPublishUI(s, scenarios, pubWrap);
    }
  } catch (err) { card.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`; }

  async function loadPublishUI(set, scenarios, wrap) {
    wrap.innerHTML = `<div class="muted">Loading versions…</div>`;
    try {
      const vers = await get(`${P()}/scenario-sets/${set.id}/versions/`);
      wrap.innerHTML = "";
      const checked = new Set();
      const checklist = el("div");
      for (const sc of scenarios) {
        const cb = el("input", { type: "checkbox", style: "width:auto;margin-right:8px" });
        cb.addEventListener("change", () => cb.checked ? checked.add(sc.id) : checked.delete(sc.id));
        const li = el("label", { style: "display:flex;align-items:center;padding:4px 0;cursor:pointer" }, cb, `${sc.title} ${sc.category ? "(" + sc.category + ")" : ""}`);
        checklist.append(li);
      }
      const pubBtn = el("button", { class: "btn", style: "margin-top:8px", onclick: async () => {
        if (!checked.size) return toast("Select at least one scenario.", true);
        try {
          const v = await post(`${P()}/scenario-sets/${set.id}/publish/`, { scenario_ids: Array.from(checked) });
          toast(`Published v${v.version}.`); loadPublishUI(set, scenarios, wrap);
        } catch (e) { toast(e.message, true); }
      } }, `Publish new version (${checked.size})`);
      pubBtn.addEventListener("click", () => { pubBtn.textContent = `Publish new version (${checked.size})`; });
      $$(checklist.children).forEach((li) => { const cb = li.querySelector("input"); cb.addEventListener("change", () => { pubBtn.textContent = `Publish new version (${checked.size})`; }); });
      wrap.append(checklist, pubBtn);
      if (vers.length) {
        const hist = el("div", { class: "muted", style: "margin-top:10px;font-size:12px" },
          "Versions: " + vers.sort((a, b) => b.version - a.version).map((v) => `v${v.version}(${v.scenario_count})`).join(", "));
        wrap.append(hist);
      }
    } catch (e) { wrap.innerHTML = `<div class="error-banner">${esc(e.message)}</div>`; }
  }
};

// ---------- Models ----------
VIEWS.models = async (root) => {
  root.append(el("h2", {}, "Models & Profiles"));
  const epCard = el("div", { class: "card" }, el("h2", {}, "Model Endpoints"), el("div", { class: "empty" }, "Loading…"));
  const profCard = el("div", { class: "card" }, el("h2", {}, "Audit Profiles"), el("div", { class: "empty" }, "Loading…"));
  root.append(epCard, profCard);

  // Endpoints
  try {
    const eps = await get(`${P()}/model-endpoints/`);
    epCard.innerHTML = `<h2>Model Endpoints</h2>`;
    const form = el("div", { class: "card", style: "background:var(--panel2)" });
    const dn = field("Display name", "", "text");
    const prov = field("Provider (e.g. openai, ollama, simulachat)", "", "text");
    const url = field("Base URL", "", "text");
    const mid = field("Model ID", "", "text");
    const sec = field("Secret env-var reference (e.g. OPENAI_API_KEY)", "", "text");
    const addBtn = el("button", { class: "primary", style: "width:auto" }, "Add endpoint");
    addBtn.addEventListener("click", async () => {
      if (!dn.value.trim() || !url.value.trim() || !mid.value.trim()) return toast("Name, URL, and model ID required.", true);
      try {
        await post(`${P()}/model-endpoints/create/`, {
          display_name: dn.value.trim(), provider: prov.value.trim() || "openai",
          base_url: url.value.trim(), model_id: mid.value.trim(), secret_reference: sec.value.trim(),
        });
        toast("Endpoint added."); navigate("models");
      } catch (e) { toast(e.message, true); }
    });
    form.append(el("div", { class: "row" }, dn, prov), el("div", { class: "row" }, url, mid), sec, addBtn);
    epCard.append(form);
    if (!eps.length) epCard.append(el("div", { class: "empty" }, "No endpoints yet."));
    for (const e of eps) {
      epCard.append(el("div", { class: "scenario" },
        el("div", { style: "display:flex;justify-content:space-between" },
          el("b", {}, e.display_name), el("span", { class: "tag" }, e.provider)),
        el("div", { class: "muted", style: "margin-top:6px" }, `${e.model_id} @ ${e.base_url}`),
        el("div", { class: "muted", style: "font-size:12px;margin-top:4px" }, e.secret_reference ? `secret: \`${e.secret_reference}\`` : "no secret ref"),
      ));
    }
  } catch (err) { epCard.innerHTML += `<div class="error-banner">${esc(err.message)}</div>`; }

  // Profiles
  try {
    const profs = await get(`${P()}/audit-profiles/`);
    profCard.innerHTML = `<h2>Audit Profiles</h2>`;
    const form = el("div", { class: "card", style: "background:var(--panel2)" });
    const pn = field("Profile name", "", "text");
    const mt = field("Max turns", "4", "text");
    const tt = field("Target temperature", "0.7", "text");
    const jt = field("Judge temperature", "0.0", "text");
    const lang = field("Language", "en", "text");
    const addBtn = el("button", { class: "primary", style: "width:auto" }, "Add profile");
    addBtn.addEventListener("click", async () => {
      if (!pn.value.trim()) return toast("Name required.", true);
      try {
        await post(`${P()}/audit-profiles/create/`, {
          name: pn.value.trim(), max_turns: parseInt(mt.value, 10) || 4,
          temperature_target: parseFloat(tt.value) || 0.7, temperature_judge: parseFloat(jt.value) || 0.0,
          language: lang.value.trim() || "en",
        });
        toast("Profile added."); navigate("models");
      } catch (e) { toast(e.message, true); }
    });
    form.append(el("div", { class: "row" }, pn, mt), el("div", { class: "row" }, tt, jt), lang, addBtn);
    profCard.append(form);
    if (!profs.length) profCard.append(el("div", { class: "empty" }, "No profiles yet (optional)."));
    for (const p of profs) {
      profCard.append(el("div", { class: "scenario" },
        el("b", {}, p.name),
        el("div", { class: "muted", style: "margin-top:6px" }, `max_turns=${p.max_turns} · T_target=${p.temperature_target} · T_judge=${p.temperature_judge} · ${p.language}`),
      ));
    }
  } catch (err) { profCard.innerHTML += `<div class="error-banner">${esc(err.message)}</div>`; }
};

// ---------- Compare ----------
VIEWS.compare = async (root) => {
  root.append(el("h2", {}, "Compare Audits"));
  const pickCard = el("div", { class: "card" }, el("div", { class: "empty" }, "Loading…"));
  const outCard = el("div", { class: "card hidden" });
  root.append(pickCard, outCard);
  try {
    const runs = (await get(`${P()}/audit-runs/`)).filter((r) => r.status === "completed");
    pickCard.innerHTML = `<h2>Select completed audits to compare</h2>`;
    if (runs.length < 2) { pickCard.append(el("div", { class: "warn" }, "You need at least two completed audits to compare.")); return; }
    const boxes = [];
    for (const r of runs) {
      const cb = el("input", { type: "checkbox", style: "width:auto;margin-right:8px" });
      boxes.push(cb);
      pickCard.append(el("label", { style: "display:flex;align-items:center;padding:6px 0;cursor:pointer" },
        cb, `${r.name} (#${r.id}) · set v${r.scenario_set_version_number} · ${shortHash(r.scenario_set_version_hash)}`));
    }
    const goBtn = el("button", { class: "primary", style: "width:auto" }, "Compare selected");
    goBtn.addEventListener("click", async () => {
      const ids = boxes.filter((b) => b.checked).map((_, i) => runs.filter((r, j) => boxes[j] === b)[0].id);
      if (ids.length < 2) return toast("Pick at least two audits.", true);
      await runCompare(ids);
    });
    pickCard.append(goBtn);
  } catch (err) { pickCard.innerHTML = `<div class="error-banner">${esc(err.message)}</div>`; }

  async function runCompare(ids) {
    outCard.classList.remove("hidden");
    outCard.innerHTML = `<h2>Comparison</h2><div class="muted">Computing…</div>`;
    try {
      const cmp = await get(`${P()}/audit-runs/compare/?run_ids=${ids.join(",")}`);
      outCard.innerHTML = `<h2>Comparison</h2>`;
      // Run summaries.
      const sumRow = el("div", { class: "stats" });
      for (const r of cmp.runs) {
        sumRow.append(el("div", { class: "stat" },
          el("div", { class: "num" }, `${r.successful_scenarios}/${r.total_scenarios}`),
          el("div", { class: "lbl" }, `${r.name} #${r.id}<br>${r.target || ""} · ${r.judge || ""}`)));
      }
      outCard.append(sumRow);
      // Warnings.
      for (const w of cmp.warnings) outCard.append(el("div", { class: "warn" }, "⚠️ " + w));
      if (!cmp.compatible) outCard.append(el("div", { class: "muted", style: "margin-top:6px" }, "These runs have different inputs. The table below shows only scenarios present in ALL selected runs."));
      // Intersection table.
      if (!cmp.results.length) {
        outCard.append(el("div", { class: "empty" }, "No common scenarios found across the selected runs."));
        return;
      }
      const table = el("table", { class: "compare-table" });
      table.append(el("thead", {}, el("tr", {}, th("Scenario"), ...cmp.runs.map((r) => th(`${r.name} #${r.id}`)))));
      const tb = el("tbody");
      for (const row of cmp.results) {
        const cells = [el("td", {}, esc(row.scenario_key))];
        for (const r of cmp.runs) {
          const d = row.runs[String(r.id)];
          if (d && d.severity) cells.push(el("td", { html: `<span class="${sevClass(d.severity)}" style="font-weight:700">${esc(d.severity)}</span>` }));
          else if (d && d.status === "failed") cells.push(el("td", { class: "muted" }, "failed"));
          else cells.push(el("td", { class: "muted" }, "—"));
        }
        tb.append(el("tr", {}, ...cells));
      }
      table.append(tb);
      outCard.append(table);
      outCard.append(el("div", { class: "muted", style: "margin-top:10px" }, `Showing ${cmp.intersection_count} scenario(s) present in all ${cmp.runs.length} runs.`));
    } catch (err) { outCard.innerHTML = `<h2>Comparison</h2><div class="error-banner">${esc(err.message)}</div>`; }
  }
};

// ---------- wire up static controls ----------
document.addEventListener("DOMContentLoaded", () => {
  $("#tab-login").addEventListener("click", () => setAuthMode("login"));
  $("#tab-register").addEventListener("click", () => setAuthMode("register"));
  $("#auth-submit").addEventListener("click", doAuth);
  $("#auth-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doAuth(e); });
  $("#logout").addEventListener("click", logout);
  $("#project-select").addEventListener("change", async (e) => {
    state.projectId = parseInt(e.target.value, 10);
    localStorage.setItem("sa_project", String(state.projectId));
    navigate(state.view);
  });
  $$("#nav button").forEach((b) => b.addEventListener("click", () => navigate(b.dataset.view)));

  if (state.token) { boot(); } else { showAuth(); }
});
