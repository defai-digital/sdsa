// SDSA minimal frontend.
// Three steps: upload → configure per-column policy → download.

const API = "/api";

const ACTIONS_BY_KIND = {
  numeric: ["retain", "dp_laplace", "numeric_bin", "drop"],
  datetime: ["retain", "date_truncate", "drop"],
  categorical: ["retain", "redact", "drop"],
  boolean: ["retain", "redact", "drop"],
  string: ["retain", "mask", "hash", "tokenize", "redact", "string_truncate", "drop"],
};

let state = {
  sessionId: null,
  schema: [],
  pii: {},
  policySuggestions: {},
  preflight: null,
  uploadData: null,
};
let preflightTimer = null;
let preflightSeq = 0;
let sessionInterval = null;
let errorTimer = null;

const $ = (id) => document.getElementById(id);

const STEP_ORDER = ["step-upload", "step-configure", "step-review"];
const STEP_NAMES = { "step-upload": "upload", "step-configure": "configure", "step-review": "review" };
const show = (id) => {
  document.querySelectorAll(".step").forEach(s => s.classList.remove("active"));
  $(id).classList.add("active");
  // Update stepper indicator
  const activeIdx = STEP_ORDER.indexOf(id);
  document.querySelectorAll(".step-item").forEach((el, i) => {
    el.classList.remove("active", "done");
    if (i < activeIdx) el.classList.add("done");
    else if (i === activeIdx) el.classList.add("active");
  });
  // Session indicator visible only when there's a live session
  const sess = $("session-indicator");
  if (state.sessionId && id !== "step-upload") {
    sess?.classList.remove("hidden");
  } else {
    sess?.classList.add("hidden");
  }
  try { window.scrollTo({ top: 0, behavior: "smooth" }); } catch {}
};

function startSessionTimer() {
  if (sessionInterval) clearInterval(sessionInterval);
  const tick = () => {
    const expiresAt = state.uploadData?.session_expires_at;
    if (!expiresAt) return;
    const remaining = Math.max(0, expiresAt - Date.now() / 1000);
    const m = Math.floor(remaining / 60);
    const s = Math.floor(remaining % 60);
    const el = $("session-timer");
    if (el) el.textContent = `${m}:${String(s).padStart(2, "0")}`;
    if (remaining <= 0) {
      clearInterval(sessionInterval);
      sessionInterval = null;
      showError("Session expired — please re-upload.");
    }
  };
  tick();
  sessionInterval = setInterval(tick, 1000);
}
function stopSessionTimer() {
  if (sessionInterval) { clearInterval(sessionInterval); sessionInterval = null; }
}
const showError = (msg) => {
  const el = $("error");
  if (errorTimer) { clearTimeout(errorTimer); errorTimer = null; }
  el.textContent = msg;
  el.classList.remove("hidden");
  errorTimer = setTimeout(() => { el.classList.add("hidden"); errorTimer = null; }, 8000);
};

function formatProcessError(message) {
  const text = String(message || "").trim();

  // Backend text is "(soft cap: N%)" since v1.0.2. Accept the bare "(cap:"
  // form too for forward/back compat.
  const softCap = text.match(/requires suppressing ([\d.]+%) of rows \((?:soft )?cap: (\d+%)\)/i);
  if (softCap) {
    return `Processing blocked: estimated suppression is ${softCap[1]}, above the ${softCap[2]} cap.\nReview the preflight suggestions below.`;
  }

  const hardCap = text.match(/would suppress ([\d.]+%) of rows, exceeding the hard utility cap of (\d+%)/i);
  if (hardCap) {
    return `Processing blocked: estimated suppression is ${hardCap[1]}, above the hard ${hardCap[2]} cap.\nReview the preflight suggestions below.`;
  }

  if (text.startsWith("All ") && text.includes("rows were suppressed")) {
    return "Processing blocked: no rows would remain after k-anonymity.\nReview the preflight suggestions below.";
  }

  const capPct = state.preflight?.suppression_cap != null
    ? `${(state.preflight.suppression_cap * 100).toFixed(0)}%`
    : "10%";
  return text.replaceAll(
    "accept_weaker_guarantee=true",
    `Allow >${capPct} row suppression`
  );
}

async function readErrorMessage(res) {
  const raw = await res.text();
  if (!raw) return `${res.status} ${res.statusText}`.trim();
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
    if (parsed && Array.isArray(parsed.detail))
      return parsed.detail.map(e => e.msg || String(e)).join("; ");
  } catch {}
  return raw;
}

// --- Upload (drag & drop + click to browse) --------------------------------

const MAX_UPLOAD_BYTES = 300 * 1024 * 1024;
const dropzone = $("dropzone");
const fileInput = $("file-input");

const SUPPORTED_EXTENSIONS = [".csv", ".txt", ".sql"];

function looksLikeSupported(file) {
  if (!file) return false;
  const name = (file.name || "").toLowerCase();
  return SUPPORTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function setUploadProgress(loaded, total, indeterminate = false) {
  const wrap = $("dropzone-progress");
  const fill = $("dropzone-progress-fill");
  const meta = $("dropzone-progress-meta");
  if (!wrap) return;
  wrap.classList.remove("hidden");
  wrap.classList.toggle("indeterminate", !!indeterminate);
  if (indeterminate) {
    if (fill) fill.style.width = "";
    if (meta) meta.textContent = "Parsing…";
  } else {
    const pct = total > 0 ? Math.min(100, (loaded / total) * 100) : 0;
    if (fill) fill.style.width = `${pct}%`;
    if (meta) meta.textContent = `${fmtBytes(loaded)} / ${fmtBytes(total)} · ${pct.toFixed(0)}%`;
  }
}
function clearUploadProgress() {
  const wrap = $("dropzone-progress");
  const fill = $("dropzone-progress-fill");
  if (!wrap) return;
  wrap.classList.add("hidden");
  wrap.classList.remove("indeterminate");
  if (fill) fill.style.width = "0%";
}

function uploadXHR(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/upload`);
    xhr.responseType = "text";
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) setUploadProgress(e.loaded, e.total);
    });
    xhr.upload.addEventListener("load", () => {
      // Bytes are uploaded; backend is now parsing/detecting. Show indeterminate
      // bar so the user knows we haven't stalled.
      setUploadProgress(file.size, file.size, true);
    });
    xhr.addEventListener("load", () => {
      const status = xhr.status;
      const text = xhr.responseText || "";
      if (status >= 200 && status < 300) {
        try { resolve(JSON.parse(text)); }
        catch (e) { reject(new Error("Malformed response from server")); }
      } else {
        let msg = `${status} ${xhr.statusText}`.trim();
        if (text) {
          try {
            const parsed = JSON.parse(text);
            if (parsed && typeof parsed.detail === "string") msg = parsed.detail;
          } catch { msg = text; }
        }
        reject(new Error(msg));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Network error")));
    xhr.addEventListener("abort", () => reject(new Error("Upload aborted")));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

async function uploadFile(file) {
  if (!file) return;
  if (!looksLikeSupported(file)) {
    flashDropzoneError(`Unsupported file: ${file.name} (expected .csv, .txt, or .sql)`);
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    flashDropzoneError(`File exceeds 300 MB limit (${(file.size / 1e6).toFixed(1)} MB)`);
    return;
  }

  // Clean up previous session before uploading to prevent server-side memory leak.
  if (state.sessionId) {
    const oldId = state.sessionId;
    state.sessionId = null;  // prevent double-delete from resetToUpload
    try { await fetch(`${API}/session/${oldId}`, { method: "DELETE" }); } catch (e) { /* ignore */ }
  }

  $("dropzone-file").textContent = `${file.name} — ${fmtBytes(file.size)}`;
  dropzone.classList.add("uploading");
  dropzone.classList.remove("error");
  setUploadProgress(0, file.size);

  try {
    const data = await uploadXHR(file);
    state.sessionId = data.session_id;
    state.schema = data.schema;
    state.pii = data.pii_suggestions;
    state.policySuggestions = data.policy_suggestions || {};
    state.uploadData = data;
    startSessionTimer();
    renderConfigure(data);
    resetPreviewPanel();
    renderPreviewOriginal();
    schedulePreflight();
    show("step-configure");
  } catch (e) {
    flashDropzoneError(`Upload failed: ${e.message}`);
    showError(`Upload failed: ${e.message}`);
  } finally {
    dropzone.classList.remove("uploading");
    clearUploadProgress();
  }
}

function renderPreflightError(message) {
  state.preflight = null;
  $("process-btn").disabled = false;
  const el = $("preflight");
  el.className = "preflight warn";
  el.innerHTML = `
    <div class="preflight-title">Preflight unavailable</div>
    <ul class="preflight-list"><li>${esc(message)}</li></ul>`;
}

let dropzoneErrorTimer = null;

function flashDropzoneError(msg) {
  if (dropzoneErrorTimer) { clearTimeout(dropzoneErrorTimer); dropzoneErrorTimer = null; }
  dropzone.classList.add("error");
  $("dropzone-file").textContent = msg;
  dropzoneErrorTimer = setTimeout(() => { dropzone.classList.remove("error"); dropzoneErrorTimer = null; }, 2000);
}

// Click to browse
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});

fileInput.addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) uploadFile(f);
  e.target.value = "";  // allow re-selecting the same file
});

// Drag & drop
["dragenter", "dragover"].forEach((ev) => {
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.add("drag-over");
  });
});
["dragleave", "dragend"].forEach((ev) => {
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("drag-over");
  });
});
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  e.stopPropagation();
  dropzone.classList.remove("drag-over");
  const file = e.dataTransfer.files && e.dataTransfer.files[0];
  if (file) uploadFile(file);
});

// Prevent the browser from navigating away if the user misses the dropzone.
["dragover", "drop"].forEach((ev) => {
  window.addEventListener(ev, (e) => {
    if (!dropzone.contains(e.target)) e.preventDefault();
  });
});

// --- Configure -------------------------------------------------------------

const PII_SEVERITY = {
  credit_card: "high", government_id: "high", email: "high", phone: "high",
  date_of_birth: "mid", name: "mid", address: "mid",
  identifier: "low", none: "low",
};

function piiBadge(pii) {
  const sev = PII_SEVERITY[pii.kind] || "low";
  const pct = Math.round((pii.confidence || 0) * 100);
  return `<span class="pii-badge ${sev}">${esc(pii.kind)}</span>
          <div class="sub">${pct}% · ${esc(pii.reason || "")}</div>`;
}

function renderConfigure(data) {
  $("summary").textContent =
    `${data.row_count.toLocaleString()} rows × ${data.column_count} columns. ` +
    `Review per-column policy below.`;
  const tbody = $("columns-table").querySelector("tbody");
  tbody.innerHTML = "";
  for (const col of data.schema) {
    const pii = data.pii_suggestions[col.name] || { kind: "none", confidence: 1 };
    const policy = data.policy_suggestions?.[col.name] || {};
    const allowed = ACTIONS_BY_KIND[col.kind] || ACTIONS_BY_KIND.string;
    const suggested = policy.action || "retain";
    const defaultAction = allowed.includes(suggested) ? suggested : "retain";
    const suggestedParams = policy.params || {};
    const suggestedDp = policy.dp_params || {};
    const defaultEpsilon = Number.isFinite(suggestedDp.epsilon) ? suggestedDp.epsilon : 1.0;
    const defaultLower = suggestedDp.lower ?? col.min ?? "";
    const defaultUpper = suggestedDp.upper ?? col.max ?? "";
    const defaultQI = typeof policy.is_quasi_identifier === "boolean"
      ? policy.is_quasi_identifier
      : isDefaultQI(col, pii);

    const tr = document.createElement("tr");
    tr.dataset.column = col.name;
    tr.dataset.kind = col.kind;
    tr.dataset.suggestedParams = JSON.stringify(suggestedParams);
    if (defaultAction === "dp_laplace") tr.classList.add("dp-on");
    tr.innerHTML = `
      <td class="select-col">
        <input type="checkbox" class="col-include" checked
               aria-label="Include ${esc(col.name)} in output"
               title="Include in output — uncheck to drop this column" />
      </td>
      <td><code>${esc(col.name)}</code></td>
      <td>${esc(col.kind)}<div class="sub">${col.n_unique.toLocaleString()} unique</div></td>
      <td>${piiBadge(pii)}</td>
      <td>
        <select class="action" aria-label="Action for ${esc(col.name)}">
          ${allowed.map(a => `<option value="${a}"${a === defaultAction ? " selected" : ""}>${a}</option>`).join("")}
        </select>
      </td>
      <td class="center">
        <input type="checkbox" class="qi"
               aria-label="Quasi-identifier for ${esc(col.name)}"
               ${defaultQI ? "checked" : ""} />
      </td>
      <td class="dp-cell">
        <input type="number" class="eps small" step="0.1" min="0.1" max="10" value="${defaultEpsilon}" />
      </td>
      <td class="dp-cell">
        <input type="number" class="bound lower" placeholder="lo" value="${esc(String(defaultLower))}" />
        <input type="number" class="bound upper" placeholder="hi" value="${esc(String(defaultUpper))}" />
      </td>`;
    tbody.appendChild(tr);
  }
  // After re-render, search is reset.
  const search = $("col-search");
  if (search) { search.value = ""; applyColumnSearch(""); }
  const selectAll = $("select-all");
  if (selectAll) { selectAll.checked = true; selectAll.indeterminate = false; }
}

// Keep row's dp-on class in sync with its action dropdown.
document.addEventListener("change", (e) => {
  const tr = e.target.closest("#columns-table tbody tr");
  if (!tr || !e.target.classList.contains("action")) return;
  tr.classList.toggle("dp-on", e.target.value === "dp_laplace");
});

function collectProcessPayload() {
  const policies = [];
  const dp_params = {};
  const rows = $("columns-table").querySelectorAll("tbody tr");
  for (const tr of rows) {
    const col = tr.dataset.column;
    const included = tr.querySelector(".col-include")?.checked !== false;
    // Excluded columns are sent as action=drop. QI and DP params are
    // meaningless for a dropped column, so we zero them out.
    if (!included) {
      policies.push({ column: col, action: "drop", params: {}, is_quasi_identifier: false });
      continue;
    }
    const action = tr.querySelector(".action").value;
    const qi = tr.querySelector(".qi").checked;
    policies.push({ column: col, action, params: buildParams(tr, action), is_quasi_identifier: qi });
    if (action === "dp_laplace") {
      const eps = parseFloat(tr.querySelector(".eps").value);
      const lo = parseFloat(tr.querySelector(".lower").value);
      const hi = parseFloat(tr.querySelector(".upper").value);
      if (!Number.isNaN(eps) && !Number.isNaN(lo) && !Number.isNaN(hi)) {
        dp_params[col] = { epsilon: eps, lower: lo, upper: hi };
      }
    }
  }
  const kRaw = parseInt($("k-input").value, 10);
  const k = Number.isNaN(kRaw) ? 5 : Math.max(2, Math.min(1000, kRaw));
  return {
    policies,
    k,
    dp_params,
    deterministic_key_name: $("det-key").value.trim() || null,
    accept_weaker_guarantee: $("accept-weaker").checked,
  };
}

function renderPreflight(preflight) {
  const el = $("preflight");
  if (!preflight) {
    state.preflight = null;
    $("process-btn").disabled = false;
    el.className = "preflight hidden";
    el.innerHTML = "";
    return;
  }
  state.preflight = preflight;
  // Don't disable Process based on preflight — the panel already explains the
  // problem. Disabling creates a "stuck" feeling; let the user click through
  // and receive the identical error as a toast if they want to confirm.
  $("process-btn").disabled = false;
  const hardBlocked = preflight.within_hard_suppression_cap === false;
  const level = hardBlocked
    ? "bad"
    : (preflight.within_suppression_cap ? (preflight.suppression_ratio > 0 ? "warn" : "good") : "warn");
  const summary = preflight.qi_columns.length
    ? `Estimated suppression: ${(preflight.suppression_ratio * 100).toFixed(1)}% (${preflight.rows_suppressed}/${preflight.rows_total} rows)`
    : "No QI columns selected; k-anonymity will not suppress rows.";
  const bullets = [];
  if (preflight.worst_qi_by_cardinality?.length) {
    const worst = preflight.worst_qi_by_cardinality[0];
    bullets.push(`Worst QI by cardinality: ${worst.column} (${worst.n_unique}/${worst.row_count} unique).`);
  }
  if (preflight.drop_one_qi_impacts?.length) {
    const best = preflight.drop_one_qi_impacts[0];
    if (best.improvement > 0) {
      bullets.push(`Best single-column relief: remove or generalize ${best.column} to reach ${(best.suppression_ratio * 100).toFixed(1)}% suppression.`);
    }
  }
  if (preflight.greedy_drop_plan?.steps?.length) {
    const plan = preflight.greedy_drop_plan;
    const cols = plan.steps.map((step) => step.column);
    const verb = plan.reaches_target ? "reach" : "reduce to";
    bullets.push(`Suggested QI plan: uncheck ${cols.join(" -> ")} to ${verb} ${(plan.final_suppression_ratio * 100).toFixed(1)}% suppression.`);
  }
  for (const msg of (preflight.suggestions || [])) bullets.push(msg);
  // One-click remediation. When the hard cap is blown, these become primary —
  // the user needs to fix something before Process will succeed.
  const bestFix = preflight.drop_one_qi_impacts?.find((item) => item.improvement > 0);
  const greedyPlan = preflight.greedy_drop_plan?.steps?.map((step) => step.column) || [];
  const btnClass = hardBlocked ? "btn-primary" : "btn-ghost";
  const actions = [];
  if (bestFix) {
    actions.push(`<button type="button" class="btn ${btnClass} quick-fix"
                    data-col="${esc(bestFix.column)}">
      Uncheck "${esc(bestFix.column)}" as QI
    </button>`);
  }
  if (greedyPlan.length > 1) {
    actions.push(`<button type="button" class="btn ${btnClass}" id="apply-greedy-plan">
      Apply suggested QI plan (${greedyPlan.length})
    </button>`);
  }
  if (hardBlocked && preflight.qi_columns?.length > 1) {
    actions.push(`<button type="button" class="btn btn-ghost" id="uncheck-all-qi">
      Uncheck all QIs (${preflight.qi_columns.length})
    </button>`);
  }

  const supPct = Math.max(0, Math.min(100, preflight.suppression_ratio * 100));
  el.className = `preflight ${level}`;
  el.innerHTML = `
    <div class="preflight-title">${esc(summary)}</div>
    <div class="meta">k=${esc(preflight.k)} · below-k ${esc(preflight.classes_below_k)}/${esc(preflight.classes_total)} · soft cap ${esc((preflight.suppression_cap * 100).toFixed(0))}% · hard cap ${esc((preflight.hard_suppression_cap * 100).toFixed(0))}%</div>
    <div class="sup-bar" aria-hidden="true"><span style="width:${supPct}%"></span></div>
    ${bullets.length ? `<ul class="preflight-list">${bullets.map((msg) => `<li>${esc(msg)}</li>`).join("")}</ul>` : ""}
    ${actions.length ? `<div class="preflight-actions">${actions.join("")}</div>` : ""}`;
}

// Wire up the dynamically-rendered remediation buttons.
document.addEventListener("click", (e) => {
  const one = e.target.closest(".quick-fix");
  if (one) {
    const col = one.dataset.col;
    const row = document.querySelector(`#columns-table tbody tr[data-column="${CSS.escape(col)}"]`);
    if (row) {
      const qi = row.querySelector(".qi");
      if (qi) { qi.checked = false; schedulePreflight(); schedulePreview(); }
    }
    return;
  }
  if (e.target.closest("#uncheck-all-qi")) {
    document.querySelectorAll("#columns-table tbody .qi").forEach((cb) => { cb.checked = false; });
    schedulePreflight();
    schedulePreview();
    return;
  }
  if (e.target.closest("#apply-greedy-plan")) {
    const cols = state.preflight?.greedy_drop_plan?.steps?.map((step) => step.column) || [];
    for (const col of cols) {
      const row = document.querySelector(`#columns-table tbody tr[data-column="${CSS.escape(col)}"]`);
      const qi = row?.querySelector(".qi");
      if (qi) qi.checked = false;
    }
    schedulePreflight();
    schedulePreview();
  }
});

async function runPreflight() {
  if (!state.sessionId) return;
  const seq = ++preflightSeq;
  const body = collectProcessPayload();
  try {
    const res = await fetch(`${API}/preflight/${state.sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        policies: body.policies,
        k: body.k,
        dp_params: body.dp_params,
        deterministic_key_name: body.deterministic_key_name,
      }),
    });
    if (res.status === 404) {
      // Session expired while configuring — don't spam the warn panel; reset.
      if (seq === preflightSeq) {
        showError("Session expired — please re-upload.");
        await resetToUpload();
      }
      return;
    }
    if (!res.ok) throw new Error(await readErrorMessage(res));
    const data = await res.json();
    if (seq !== preflightSeq) return;
    renderPreflight(data.preflight);
  } catch (e) {
    if (seq !== preflightSeq) return;
    renderPreflightError(e.message || "Unable to estimate suppression");
  }
}

function schedulePreflight() {
  if (preflightTimer) window.clearTimeout(preflightTimer);
  preflightTimer = window.setTimeout(() => {
    preflightTimer = null;
    runPreflight();
  }, 250);
}

function isDefaultQI(col, pii) {
  // Only default to QI when average equivalence class size could plausibly
  // meet the default k. A high-cardinality column (e.g. raw salary) as a QI
  // with action=retain would force k-anonymity to suppress every row.
  if (pii.kind !== "none") return false;
  if (!["numeric", "datetime", "categorical"].includes(col.kind)) return false;
  const n = col.row_count || 0;
  const u = col.n_unique || 0;
  if (u === 0 || n === 0) return false;
  const defaultK = state.uploadData?.default_k ?? 5;
  return u * defaultK <= n;
}

function esc(s) {
  return String(s).replace(/[&<>"'`]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;",
  })[c]);
}

function flashPreflight() {
  const el = $("preflight");
  if (!el || el.classList.contains("hidden")) return;
  try { el.scrollIntoView({ behavior: "smooth", block: "center" }); } catch {}
  el.classList.remove("flash");
  // Force reflow so the animation restarts if it was already applied.
  void el.offsetWidth;
  el.classList.add("flash");
}

function flashAcceptWeaker() {
  const toggle = $("accept-weaker")?.closest(".toggle");
  if (!toggle) return;
  try { toggle.scrollIntoView({ behavior: "smooth", block: "center" }); } catch {}
  toggle.classList.remove("flash");
  void toggle.offsetWidth;
  toggle.classList.add("flash");
}

function guardProcessFromPreflight() {
  const preflight = state.preflight;
  if (!preflight) return false;

  if (preflight.within_hard_suppression_cap === false) {
    showError("Processing blocked: estimated suppression is above the hard cap.\nReview the preflight suggestions below.");
    flashPreflight();
    return true;
  }

  if (preflight.within_suppression_cap === false && !$("accept-weaker").checked) {
    const capPct = preflight.suppression_cap != null
      ? `${(preflight.suppression_cap * 100).toFixed(0)}%`
      : "10%";
    showError(`Processing blocked: estimated suppression is above the ${capPct} cap.\nUse the preflight suggestions or allow >${capPct} row suppression.`);
    flashPreflight();
    flashAcceptWeaker();
    return true;
  }

  return false;
}

$("process-btn").addEventListener("click", async () => {
  const body = collectProcessPayload();
  for (const [col, params] of Object.entries(body.dp_params)) {
    if ([params.epsilon, params.lower, params.upper].some((v) => Number.isNaN(v))) {
      showError(`DP column '${col}' needs ε and both bounds`);
      return;
    }
  }
  for (const policy of body.policies) {
    if (policy.action === "dp_laplace" && !body.dp_params[policy.column]) {
      showError(`DP column '${policy.column}' needs ε and both bounds`);
      return;
    }
  }
  if (guardProcessFromPreflight()) return;

  const btn = $("process-btn");
  btn.classList.add("loading");
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/process/${state.sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status === 404) {
      // Session is gone (expired or deleted). Don't leave the user stuck.
      showError("Session expired — please re-upload.");
      await resetToUpload();
      return;
    }
    if (!res.ok) throw new Error(await readErrorMessage(res));
    const data = await res.json();
    renderReview(data.report);
    show("step-review");
  } catch (e) {
    showError(formatProcessError(e.message));
    const msg = (e.message || "").toLowerCase();
    // Soft-cap breach: the toggle on the actions bar is the one-click fix.
    // Flash it so the user sees the control they need to flip.
    if (msg.includes("soft cap") && !$("accept-weaker").checked) {
      flashAcceptWeaker();
    } else if (msg.includes("suppress") || msg.includes("qi") || msg.includes("k-anonymity")) {
      // Hard-cap or other QI issue — the preflight panel has the remediation.
      flashPreflight();
    }
  } finally {
    btn.classList.remove("loading");
    btn.disabled = false;
  }
});

// Reset current config back to auto-detected defaults.
$("reset-config")?.addEventListener("click", () => {
  if (!state.uploadData) return;
  renderConfigure(state.uploadData);
  resetPreviewPanel();
  renderPreviewOriginal();
  schedulePreflight();
});

$("columns-table").addEventListener("input", (e) => {
  if (!e.target.closest("tbody")) return;
  if (e.target.classList.contains("col-include")) return;
  schedulePreflight();
  schedulePreview();
});
$("columns-table").addEventListener("change", (e) => {
  if (!e.target.closest("tbody")) return;
  if (e.target.classList.contains("col-include")) return;  // handled above
  schedulePreflight();
  schedulePreview();
});
$("k-input").addEventListener("input", schedulePreflight);
$("det-key")?.addEventListener("input", () => { schedulePreflight(); schedulePreview(); });

function buildParams(tr, action) {
  let suggested = {};
  try { suggested = JSON.parse(tr.dataset.suggestedParams || "{}"); } catch {}
  if (action === "numeric_bin") {
    if (suggested.bin_width != null) return { bin_width: suggested.bin_width };
    // Default bin width: 10% of observed range if available; else 1.
    const lo = parseFloat(tr.querySelector(".lower").value);
    const hi = parseFloat(tr.querySelector(".upper").value);
    const w = (!isNaN(lo) && !isNaN(hi) && hi > lo) ? (hi - lo) / 10 : 1;
    return { bin_width: w };
  }
  if (action === "date_truncate") return { granularity: suggested.granularity || "month" };
  if (action === "string_truncate") return { keep: suggested.keep ?? 3, ...(suggested.pad_char ? { pad_char: suggested.pad_char } : {}) };
  if (action === "mask") {
    return {
      keep_prefix: suggested.keep_prefix ?? 1,
      keep_suffix: suggested.keep_suffix ?? 1,
      ...(suggested.mask_char ? { mask_char: suggested.mask_char } : {}),
    };
  }
  if (action === "redact" && suggested.replacement) return { replacement: suggested.replacement };
  if (action === "tokenize" && suggested.prefix) return { prefix: suggested.prefix };
  return {};
}

// --- Preview panel (sample rows: original + sanitized) ---------------------

let previewMode = "original";   // "original" | "sanitized"
let previewSeq = 0;
let previewTimer = null;
let previewCache = null;        // last sanitized response

function resetPreviewPanel() {
  previewMode = "original";
  previewCache = null;
  previewSeq = 0;
  if (previewTimer) { window.clearTimeout(previewTimer); previewTimer = null; }
  document.querySelectorAll(".preview-tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === "original");
    b.setAttribute("aria-selected", b.dataset.mode === "original" ? "true" : "false");
  });
  const panel = $("preview-panel");
  if (panel) panel.classList.remove("collapsed");
  const meta = $("preview-meta");
  if (meta) meta.textContent = "first 5 rows";
}

function piiClassFor(name) {
  const pii = state.uploadData?.pii_suggestions?.[name];
  if (!pii) return "";
  const sev = PII_SEVERITY[pii.kind] || "low";
  if (sev === "high") return "pii-high";
  if (sev === "mid")  return "pii-mid";
  return "";
}

function renderPreviewOriginal() {
  const body = $("preview-body");
  if (!body) return;
  const data = state.uploadData;
  if (!data || !data.sample_columns || !data.sample_rows?.length) {
    body.className = "preview-body empty";
    body.textContent = "No sample available.";
    return;
  }
  const cols = data.sample_columns;
  const rows = data.sample_rows;
  $("preview-meta").textContent =
    `first ${rows.length} of ${data.row_count.toLocaleString()} rows`;
  body.className = "preview-body";
  body.innerHTML = `
    <table class="preview-table">
      <thead>
        <tr>
          <th class="preview-row-num">#</th>
          ${cols.map((c) => `<th class="${piiClassFor(c)}">${esc(c)}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${rows.map((row, i) => `
          <tr>
            <td class="preview-row-num">${i + 1}</td>
            ${row.map((v) => v === null
              ? `<td class="null">∅</td>`
              : `<td>${esc(v)}</td>`).join("")}
          </tr>`).join("")}
      </tbody>
    </table>`;
}

function renderPreviewSanitized(payload) {
  const body = $("preview-body");
  if (!body) return;
  const cols = payload.columns;
  const orig = payload.original;
  const san = payload.sanitized;
  const dropped = new Set(payload.dropped_columns || []);
  $("preview-meta").textContent =
    `before → after · first ${orig.length} rows` +
    (dropped.size ? ` · ${dropped.size} dropped` : "");
  body.className = "preview-body";
  body.innerHTML = `
    <table class="preview-table">
      <thead>
        <tr>
          <th class="preview-row-num">#</th>
          ${cols.map((c) => `<th class="${piiClassFor(c)}" title="${dropped.has(c) ? "dropped" : esc(c)}">${esc(c)}${dropped.has(c) ? " ⊘" : ""}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${orig.map((row, i) => `
          <tr>
            <td class="preview-row-num">${i + 1}</td>
            ${row.map((v) => v === null
              ? `<td class="null">∅</td>`
              : `<td>${esc(v)}</td>`).join("")}
          </tr>
          <tr>
            <td class="preview-row-num">→</td>
            ${cols.map((c, j) => {
              if (dropped.has(c)) return `<td class="dropped">[dropped]</td>`;
              const sv = (san[i] != null && j < san[i].length) ? san[i][j] : null;
              const ov = orig[i][j];
              const changed = String(sv) !== String(ov);
              if (sv === null) return `<td class="null${changed ? " changed" : ""}">∅</td>`;
              return `<td class="${changed ? "changed" : ""}">${esc(sv)}</td>`;
            }).join("")}
          </tr>`).join("")}
      </tbody>
    </table>`;
}

async function fetchPreview() {
  if (!state.sessionId) return;
  const seq = ++previewSeq;
  const body = $("preview-body");
  if (!body) return;
  body.className = "preview-body loading";
  body.innerHTML = "";
  const payload = collectProcessPayload();
  try {
    const res = await fetch(`${API}/preview/${state.sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (seq !== previewSeq) return;
    if (res.status === 404) {
      body.className = "preview-body error";
      body.textContent = "Session expired — please re-upload.";
      return;
    }
    if (!res.ok) throw new Error(await readErrorMessage(res));
    const data = await res.json();
    if (seq !== previewSeq) return;
    previewCache = data;
    renderPreviewSanitized(data);
  } catch (e) {
    if (seq !== previewSeq) return;
    body.className = "preview-body error";
    body.textContent = `Preview failed: ${e.message}`;
  }
}

function schedulePreview() {
  if (previewMode !== "sanitized") return;
  // Stale; will refetch.
  previewCache = null;
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => {
    previewTimer = null;
    fetchPreview();
  }, 300);
}

document.querySelectorAll(".preview-tab").forEach((tab) => {
  tab.addEventListener("click", (e) => {
    // Don't toggle when the help "?" inside the tab is clicked.
    if (e.target.closest(".help")) return;
    const mode = tab.dataset.mode;
    if (mode === previewMode) return;
    previewMode = mode;
    document.querySelectorAll(".preview-tab").forEach((b) => {
      b.classList.toggle("active", b === tab);
      b.setAttribute("aria-selected", b === tab ? "true" : "false");
    });
    if (mode === "original") {
      renderPreviewOriginal();
    } else if (previewCache) {
      renderPreviewSanitized(previewCache);
    } else {
      fetchPreview();
    }
  });
});

$("preview-collapse")?.addEventListener("click", () => {
  const panel = $("preview-panel");
  if (!panel) return;
  const collapsed = panel.classList.toggle("collapsed");
  $("preview-collapse").textContent = collapsed ? "+" : "−";
  $("preview-collapse").setAttribute("aria-expanded", collapsed ? "false" : "true");
});

// --- Column search ---------------------------------------------------------

function applyColumnSearch(query) {
  const q = (query || "").trim().toLowerCase();
  const rows = document.querySelectorAll("#columns-table tbody tr");
  for (const tr of rows) {
    const name = (tr.dataset.column || "").toLowerCase();
    tr.classList.toggle("row-hidden", q && !name.includes(q));
  }
  syncSelectAllState();
}
$("col-search")?.addEventListener("input", (e) => applyColumnSearch(e.target.value));

// --- Include / exclude columns --------------------------------------------

function visibleRows() {
  return Array.from(document.querySelectorAll("#columns-table tbody tr"))
    .filter((tr) => !tr.classList.contains("row-hidden"));
}

function syncSelectAllState() {
  const all = visibleRows();
  const included = all.filter((tr) => tr.querySelector(".col-include")?.checked);
  const cb = $("select-all");
  if (!cb) return;
  cb.checked = all.length > 0 && included.length === all.length;
  cb.indeterminate = included.length > 0 && included.length < all.length;
}

function applyIncludeStyling(tr) {
  const included = tr.querySelector(".col-include")?.checked !== false;
  tr.classList.toggle("row-excluded", !included);
  // Disable per-row inputs so they can't be tweaked while the column is
  // excluded — makes the "this column will be dropped" contract unambiguous.
  tr.querySelectorAll(".action, .qi, .eps, .bound").forEach((el) => {
    el.disabled = !included;
  });
}

$("columns-table").addEventListener("change", (e) => {
  if (!e.target.classList.contains("col-include")) return;
  const tr = e.target.closest("tbody tr");
  if (tr) applyIncludeStyling(tr);
  syncSelectAllState();
  schedulePreflight();
  schedulePreview();
});

$("select-all")?.addEventListener("change", (e) => {
  const checked = e.target.checked;
  visibleRows().forEach((tr) => {
    const cb = tr.querySelector(".col-include");
    if (cb && cb.checked !== checked) {
      cb.checked = checked;
      applyIncludeStyling(tr);
    }
  });
  e.target.indeterminate = false;
  schedulePreflight();
  schedulePreview();
});

// --- Review ----------------------------------------------------------------

function renderReview(report) {
  const k = report.k_anonymity || {};
  const priv = report.privacy || {};
  const kept = (k.rows_total || 0) - (k.rows_suppressed || 0);
  const prosecutor = 1 / Math.max(k.k_achieved, 1);

  const kClass    = k.k_achieved >= k.k_target ? "ok" : "warn";
  const ratioClass = k.suppression_ratio === 0 ? "ok"
                    : k.suppression_ratio < 0.10 ? "" : "warn";
  const riskClass = prosecutor <= 0.2 ? "ok"
                    : prosecutor <= 0.5 ? "warn" : "bad";

  const stats = [
    { label: "k achieved",
      value: k.k_achieved,
      sub: `target ${k.k_target}`,
      cls: kClass },
    { label: "Rows preserved",
      value: kept.toLocaleString(),
      sub: `of ${k.rows_total.toLocaleString()} (${((kept / Math.max(k.rows_total, 1)) * 100).toFixed(1)}%)`,
      cls: ratioClass || "" },
    { label: "Prosecutor risk",
      value: `≤ ${prosecutor.toFixed(3)}`,
      sub: `upper bound`,
      cls: riskClass },
    { label: "max ε per column",
      value: priv.max_epsilon,
      sub: priv.mechanism_per_column && Object.keys(priv.mechanism_per_column).length
        ? `${Object.keys(priv.mechanism_per_column).length} column(s) with DP` : "no DP applied",
      cls: "" },
  ];
  $("stats").innerHTML = stats.map((s) => `
    <div class="stat ${s.cls}">
      <div class="stat-label">${esc(s.label)}</div>
      <div class="stat-value">${esc(String(s.value))} ${s.sub ? `<small>${esc(s.sub)}</small>` : ""}</div>
    </div>`).join("");

  const warnBox = $("warnings");
  if (warnBox) {
    const warnings = Array.isArray(report.warnings) ? report.warnings : [];
    if (warnings.length) {
      warnBox.innerHTML =
        `<div class="warnings-title">⚠ Privacy warnings</div>` +
        `<ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`;
      warnBox.classList.remove("hidden");
    } else {
      warnBox.innerHTML = "";
      warnBox.classList.add("hidden");
    }
  }

  const claimBox = $("claim-box");
  const claim = claimBox ? claimBox.querySelector(".claim-text") : null;
  if (claim) claim.innerHTML = `<strong>Privacy claim:</strong> ${esc(report.claim || "")}`;
  $("report-raw").textContent = JSON.stringify(report, null, 2);
  $("dl-csv").href = `${API}/download/${state.sessionId}/data.csv`;
  $("dl-json").href = `${API}/download/${state.sessionId}/report.json`;
  $("dl-md").href = `${API}/download/${state.sessionId}/report.md`;
}

async function resetToUpload() {
  if (state.sessionId) {
    try { await fetch(`${API}/session/${state.sessionId}`, { method: "DELETE" }); }
    catch (e) { /* ignore */ }
  }
  stopSessionTimer();
  // Clear pending preflight timer and invalidate sequence so stale
  // responses are discarded.
  if (preflightTimer) { window.clearTimeout(preflightTimer); preflightTimer = null; }
  preflightSeq = 0;
  // Clear error toast timer so a stale auto-hide doesn't clip a new error.
  if (errorTimer) { window.clearTimeout(errorTimer); errorTimer = null; }
  const errorEl = $("error");
  if (errorEl) { errorEl.classList.add("hidden"); errorEl.textContent = ""; }
  state = {
    sessionId: null, schema: [], pii: {}, policySuggestions: {},
    preflight: null, uploadData: null,
  };
  renderPreflight(null);
  resetPreviewPanel();
  const body = $("preview-body");
  if (body) { body.className = "preview-body empty"; body.innerHTML = ""; }
  const search = $("col-search");
  if (search) search.value = "";
  $("file-input").value = "";
  $("dropzone-file").textContent = "";
  clearUploadProgress();
  dropzone.classList.remove("uploading", "error", "drag-over");
  show("step-upload");
}
$("new-session")?.addEventListener("click", resetToUpload);
$("review-restart")?.addEventListener("click", resetToUpload);

// Clicking the "Upload" step in the top bar restarts - behaves like "start over".
// Use event delegation to avoid per-element listeners that could accumulate if
// the step bar is ever re-rendered (BUG-226).
document.querySelectorAll('.step-item[data-step="upload"]').forEach((el) => {
  el.setAttribute("role", "button");
  el.setAttribute("tabindex", "0");
  el.classList.add("step-clickable");
});
document.addEventListener("click", (e) => {
  if (e.target.closest('.step-item[data-step="upload"]')) {
    resetToUpload();
  }
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.closest('.step-item[data-step="upload"]')) {
    e.preventDefault();
    resetToUpload();
  }
});

// ----- Tooltips (for ".help" anchors) --------------------------------------
(() => {
  const tip = $("tooltip");
  if (!tip) return;
  const show = (trigger) => {
    const text = trigger.getAttribute("data-tip");
    if (!text) return;
    tip.textContent = text;
    tip.classList.add("visible");
    tip.setAttribute("aria-hidden", "false");
    const r = trigger.getBoundingClientRect();
    // Default: under the element; flip up if near viewport bottom.
    const tipRect = tip.getBoundingClientRect();
    let top = r.bottom + 6;
    let left = r.left + r.width / 2 - tipRect.width / 2;
    if (top + tipRect.height > window.innerHeight - 8) top = r.top - tipRect.height - 6;
    left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const hide = () => {
    tip.classList.remove("visible");
    tip.setAttribute("aria-hidden", "true");
  };
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest(".help");
    if (t) show(t);
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest(".help")) hide();
  });
  document.addEventListener("focusin", (e) => {
    const t = e.target.closest(".help");
    if (t) show(t);
  });
  document.addEventListener("focusout", (e) => {
    if (e.target.closest(".help")) hide();
  });
  window.addEventListener("scroll", hide, { passive: true });
})();
