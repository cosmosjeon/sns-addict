"use strict";

const API_BASE   = "";
const WS_URL     = "ws://localhost:8765/ws/events";
const POLL_MS    = 5000;
const MAX_EVENTS = 100;

const state = {
  ws: null,
  wsRetry: 0,
  pollTimer: null,
  events: 0,
  startedAt: null,
};

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function fmtTime(tsSec) {
  if (!tsSec) return "—";
  const d = (typeof tsSec === "number") ? new Date(tsSec * 1000) : new Date(tsSec);
  if (isNaN(d.getTime())) return String(tsSec);
  return d.toTimeString().slice(0, 8);
}

function fmtDuration(sinceSec) {
  if (!sinceSec) return "—";
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - sinceSec));
  if (seconds < 60)    return `${seconds}s`;
  if (seconds < 3600)  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function initTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const target = btn.dataset.tab;
      $$(".tab").forEach((t) => {
        const active = t === btn;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
      });
      $$(".tab-content").forEach((c) => {
        c.classList.toggle("active", c.id === `tab-${target}`);
        c.classList.toggle("hidden",  c.id !== `tab-${target}`);
      });
      if (target === "allowlist") loadAllowlist();
      if (target === "live")      ensureWebSocket();
    });
  });
}

async function loadStatus() {
  try {
    const res  = await fetch(`${API_BASE}/api/control/status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderStatus(data);
    hideGatewayBanner();
    return data;
  } catch (err) {
    showGatewayBanner();
    renderStatus(null);
    console.warn("status fetch failed:", err);
    return null;
  }
}

function renderStatus(data) {
  const pill  = $("#session-pill");
  const stateEl = $("#kv-state");
  const modeEl = $("#kv-mode");
  const mood  = $("#kv-mood");
  const since = $("#kv-since");
  const f3    = $("#kv-f3");

  if (!data) {
    pill.textContent = "offline";
    pill.className = "pill pill-idle";
    stateEl.textContent = "—";
    modeEl.textContent  = "—";
    mood.textContent   = "—";
    since.textContent  = "—";
    f3.textContent     = "—";
    return;
  }

  const s = data.session_state || "unknown";
  const mode = data.runtime_mode || "stopped";
  pill.textContent = s;
  pill.className   = "pill " + (s === "active" ? "pill-active" : (s === "stopped" ? "pill-stopped" : "pill-idle"));

  stateEl.textContent = s;
  modeEl.textContent  = mode;
  mood.textContent   = data.current_mood || "—";
  since.textContent  = fmtTime(data.since);
  f3.textContent     = data.f3_mode ? "ON" : "off";

  const toggle = $("#f3-toggle");
  if (toggle && toggle.checked !== !!data.f3_mode) toggle.checked = !!data.f3_mode;
  const modeSelect = $("#runtime-mode");
  if (modeSelect && modeSelect.value !== mode) modeSelect.value = mode;
  $("#f3-banner").classList.toggle("hidden", !data.f3_mode);

  if (data.since && !state.startedAt) state.startedAt = data.since;
  $("#stat-uptime").textContent = (s === "active") ? fmtDuration(state.startedAt || data.since) : "—";
  $("#stats-stamp").textContent = fmtTime(Date.now() / 1000);
}

async function setRuntimeMode(mode) {
  try {
    const res = await fetch(`${API_BASE}/api/control/mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    await loadStatus();
    await loadApprovalQueue();
  } catch (err) {
    flashError(`Mode 변경 실패: ${err.message}`);
    await loadStatus();
  }
}

async function startSession() {
  const btn = $("#btn-start");
  btn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/control/start`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.startedAt = Math.floor(Date.now() / 1000);
    await loadStatus();
    schedulePolling();
  } catch (err) {
    flashError(`Start 실패: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

async function stopSession() {
  const btn = $("#btn-stop");
  btn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/control/stop`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.startedAt = null;
    await loadStatus();
    schedulePolling();
  } catch (err) {
    flashError(`Stop 실패: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

function schedulePolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => {
    loadStatus();
    loadApprovalQueue();
  }, POLL_MS);
}

function showGatewayBanner() {
  const b = $("#status-banner");
  b.innerHTML = "Hermes gateway 안 돔 — <code>hermes start</code> 먼저 실행";
  b.classList.remove("hidden");
}

function hideGatewayBanner() {
  $("#status-banner").classList.add("hidden");
}

function flashError(msg) {
  const b = $("#status-banner");
  b.textContent = msg;
  b.classList.remove("hidden");
  b.classList.remove("banner-warn");
  b.classList.add("banner-danger");
  setTimeout(() => {
    b.classList.add("hidden");
    b.classList.remove("banner-danger");
    b.classList.add("banner-warn");
  }, 4000);
}

async function loadAllowlist() {
  try {
    const res  = await fetch(`${API_BASE}/api/allowlist/list`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const list = await res.json();
    renderAllowlist(list);
    $("#stat-friends").textContent = String(list.length);
  } catch (err) {
    showAllowlistError(`Allowlist load 실패: ${err.message}`);
  }
}

async function loadApprovalQueue() {
  try {
    const res = await fetch(`${API_BASE}/api/control/approval_queue`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderApprovalQueue(data.items || []);
  } catch (err) {
    console.warn("approval queue fetch failed:", err);
  }
}

function renderApprovalQueue(items) {
  const ul = $("#approval-list");
  if (!ul) return;
  const visible = items.filter((item) => ["proposed", "approved", "sending", "failed"].includes(item.status));
  ul.innerHTML = "";
  if (!visible.length) {
    ul.appendChild(el("li", { class: "empty muted small" }, "No proposed replies."));
    return;
  }
  for (const item of visible) {
    const approveDisabled = item.status !== "proposed";
    const rejectDisabled = !["proposed", "approved", "failed"].includes(item.status);
    ul.appendChild(el("li", { class: "approval-item" }, [
      el("div", { class: "approval-main" }, [
        el("div", { class: "approval-meta" }, [
          el("span", { class: "chip" }, item.status || "proposed"),
          el("span", { class: "muted small" }, item.thread_id || item.thread_id_hash || "unknown"),
          el("span", { class: "muted small" }, fmtTime(item.queued_at)),
        ]),
        el("div", { class: "approval-reply" }, item.proposed_reply || ""),
      ]),
      el("div", { class: "approval-actions" }, [
        el("button", {
          class: "btn btn-primary",
          disabled: approveDisabled ? "disabled" : null,
          onclick: () => approveProposal(item.id),
        }, "approve"),
        el("button", {
          class: "btn btn-ghost",
          disabled: rejectDisabled ? "disabled" : null,
          onclick: () => rejectProposal(item.id),
        }, "reject"),
      ]),
    ]));
  }
}

async function approveProposal(id) {
  await updateProposal(id, "approve");
}

async function rejectProposal(id) {
  await updateProposal(id, "reject");
}

async function updateProposal(id, action) {
  try {
    const res = await fetch(`${API_BASE}/api/control/approval_queue/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    await loadApprovalQueue();
    await loadStatus();
  } catch (err) {
    flashError(`Queue ${action} 실패: ${err.message}`);
  }
}

function renderAllowlist(list) {
  const ul = $("#friend-list");
  ul.innerHTML = "";
  $("#allowlist-count").textContent = `${list.length} friend${list.length === 1 ? "" : "s"}`;

  if (list.length === 0) {
    ul.appendChild(el("li", { class: "empty muted small" }, "아직 추가된 친구가 없습니다."));
    return;
  }

  for (const f of list) {
    const meta = el("div", { class: "friend-meta" }, [
      el("span", { class: "chip" }, f.friendliness || "medium"),
      ...(f.topics && f.topics.length
          ? [el("span", { class: "chip" }, f.topics.join(", "))]
          : []),
    ]);
    const removeBtn = el("button", {
      class: "btn-remove",
      title: `Remove ${f.username}`,
      onclick: () => removeFriend(f.username),
    }, "✕ remove");

    ul.appendChild(el("li", { class: "friend-item" }, [
      el("span", { class: "friend-username" }, "@" + f.username),
      meta,
      removeBtn,
    ]));
  }
}

async function addFriend(event) {
  event.preventDefault();
  const usernameInput     = $("#input-username");
  const friendlinessInput = $("#input-friendliness");
  const topicsInput       = $("#input-topics");

  const username = usernameInput.value.trim().replace(/^@/, "");
  if (!username) return;

  const topics = topicsInput.value
    .split(",").map((t) => t.trim()).filter(Boolean);

  const payload = {
    username,
    friendliness: friendlinessInput.value || "medium",
    topics,
  };

  try {
    const res = await fetch(`${API_BASE}/api/allowlist/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    usernameInput.value = "";
    topicsInput.value   = "";
    hideAllowlistError();
    await loadAllowlist();
  } catch (err) {
    showAllowlistError(`Add 실패: ${err.message}`);
  }
}

async function removeFriend(username) {
  if (!confirm(`@${username} 을 allowlist에서 제거할까요?`)) return;
  try {
    const res = await fetch(`${API_BASE}/api/allowlist/${encodeURIComponent(username)}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await loadAllowlist();
  } catch (err) {
    showAllowlistError(`Remove 실패: ${err.message}`);
  }
}

function showAllowlistError(msg) {
  const b = $("#allowlist-error");
  b.textContent = msg;
  b.classList.remove("hidden");
}
function hideAllowlistError() {
  $("#allowlist-error").classList.add("hidden");
}

function ensureWebSocket() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) return;
  if (state.ws && state.ws.readyState === WebSocket.CONNECTING) return;
  connectWebSocket();
}

function connectWebSocket() {
  setConnState("idle");
  let ws;
  try {
    ws = new WebSocket(WS_URL);
  } catch (err) {
    setConnState("error");
    scheduleReconnect();
    return;
  }
  state.ws = ws;

  ws.addEventListener("open", () => {
    setConnState("live");
    state.wsRetry = 0;
  });

  ws.addEventListener("message", (msg) => {
    appendEvent(msg.data);
  });

  ws.addEventListener("error", () => {
    setConnState("error");
  });

  ws.addEventListener("close", () => {
    setConnState("idle");
    state.ws = null;
    scheduleReconnect();
  });
}

function scheduleReconnect() {
  state.wsRetry = Math.min(state.wsRetry + 1, 6);
  const delay = Math.min(1000 * (2 ** state.wsRetry), 15000);
  setTimeout(connectWebSocket, delay);
}

function setConnState(kind) {
  const dot   = $("#conn-indicator");
  const label = $("#conn-label");
  dot.className = "conn-dot conn-" + kind;
  label.textContent = kind === "live" ? "live" : (kind === "error" ? "error" : "offline");
}

function appendEvent(raw) {
  const log = $("#event-log");

  const empty = log.querySelector(".empty");
  if (empty) empty.remove();

  let parsed;
  try { parsed = JSON.parse(raw); } catch { parsed = null; }

  const ts   = parsed?.ts ?? parsed?.timestamp ?? null;
  const type = parsed?.event_type ?? parsed?.type ?? "event";
  const body = parsed
    ? formatEventBody(parsed)
    : String(raw);

  const entry = el("div", {
    class: "event-entry " + classifyEvent(type),
  }, [
    el("span", { class: "event-time" }, fmtTime(ts) || "—"),
    el("span", { class: "event-type" }, String(type)),
    el("span", { class: "event-body" }, body),
  ]);

  log.insertBefore(entry, log.firstChild);

  while (log.childElementCount > MAX_EVENTS) {
    log.removeChild(log.lastChild);
  }

  state.events += 1;
  $("#event-count").textContent = `${state.events} event${state.events === 1 ? "" : "s"}`;
  $("#stat-events").textContent = String(state.events);

  log.scrollTop = 0;

  if (type === "reply_sent") {
    const cur = parseInt($("#stat-replies").textContent, 10) || 0;
    $("#stat-replies").textContent = String(cur + 1);
  }
}

function formatEventBody(obj) {
  const omit = new Set(["ts", "timestamp", "event_type", "type"]);
  const pairs = Object.entries(obj)
    .filter(([k]) => !omit.has(k))
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return pairs.length ? pairs.join("  ") : JSON.stringify(obj);
}

function classifyEvent(type) {
  const t = String(type).toLowerCase();
  if (t.includes("error") || t.includes("fail"))    return "evt-error";
  if (t.includes("warn")  || t.includes("rollback")) return "evt-warn";
  if (t.includes("sent")  || t.includes("success") || t.includes("enabled")) return "evt-success";
  return "";
}

function clearEvents() {
  const log = $("#event-log");
  log.innerHTML = "";
  log.appendChild(el("div", { class: "empty muted small" }, "Cleared. 새 event 대기 중…"));
  state.events = 0;
  $("#event-count").textContent = "0 events";
  $("#stat-events").textContent = "0";
}

function initF3Controls() {
  const consent = $("#f3-consent");
  const toggle  = $("#f3-toggle");
  const hint    = $("#f3-hint");

  consent.addEventListener("change", () => {
    toggle.disabled = !consent.checked;
    if (!consent.checked && toggle.checked) {
      toggle.checked = false;
      sendF3Mode(false, false);
    }
    hint.textContent = consent.checked
      ? "이제 F3 toggle을 활성화할 수 있습니다."
      : "consent 체크박스를 먼저 활성화하세요.";
  });
}

async function toggleF3Mode() {
  const consent = $("#f3-consent");
  const toggle  = $("#f3-toggle");

  if (toggle.checked && !consent.checked) {
    alert("협력자 동의(consent) 체크박스를 먼저 확인해야 합니다.");
    toggle.checked = false;
    return;
  }
  await sendF3Mode(toggle.checked, consent.checked);
}

async function sendF3Mode(enabled, collaboratorConsent) {
  try {
    const res = await fetch(`${API_BASE}/api/control/f3_mode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, collaborator_consent: collaboratorConsent }),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    $("#f3-banner").classList.toggle("hidden", !enabled);
    $("#kv-f3").textContent = enabled ? "ON" : "off";
  } catch (err) {
    flashError(`F3 mode 변경 실패: ${err.message}`);
    $("#f3-toggle").checked = !enabled;
  }
}

async function init() {
  initTabs();
  initF3Controls();
  await loadStatus();
  await loadAllowlist();
  await loadApprovalQueue();
  ensureWebSocket();
  schedulePolling();

  setInterval(() => {
    if (state.startedAt) {
      $("#stat-uptime").textContent = fmtDuration(state.startedAt);
    }
  }, 1000);
}

document.addEventListener("DOMContentLoaded", init);

window.startSession  = startSession;
window.stopSession   = stopSession;
window.loadStatus    = loadStatus;
window.setRuntimeMode = setRuntimeMode;
window.addFriend     = addFriend;
window.removeFriend  = removeFriend;
window.loadApprovalQueue = loadApprovalQueue;
window.approveProposal = approveProposal;
window.rejectProposal = rejectProposal;
window.toggleF3Mode  = toggleF3Mode;
window.clearEvents   = clearEvents;
