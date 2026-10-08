// Bright Smile Dental front desk: live call, patient intake, operatory schedule, Riley's actions.
const $ = (id) => document.getElementById(id);
const TZ = "America/Chicago";
const DAY_START = 8 * 60, DAY_END = 17 * 60, SPAN = DAY_END - DAY_START;

const ui = {
  seenEvents: null, seenTools: null, selectedDay: null,
  conversation: null, conversationId: null, callStart: null, timerId: null,
  lastKpis: {}, intake: {}, state: null, freshUntil: new Map(), gridSig: "",
  live: { id: null, on: false, count: 0, mode: "" },
};

// ---------- helpers ----------
const fmt = (d, o) => new Intl.DateTimeFormat("en-US", { timeZone: TZ, ...o }).format(new Date(d));
const dayKey = (d) => fmt(d, { year: "numeric", month: "2-digit", day: "2-digit" }).replace(/(\d+)\/(\d+)\/(\d+)/, "$3-$1-$2");
const minutesOf = (d) => { const [h, m] = fmt(d, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).split(":"); return (+h % 24) * 60 + +m; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (n) => "$" + Math.round(n).toLocaleString("en-US");
const hhmm = (m) => `${((Math.floor(m / 60) + 11) % 12) + 1}${m % 60 ? ":" + String(m % 60).padStart(2, "0") : ""} ${m < 720 ? "AM" : "PM"}`;
const icon = (id) => `<svg><use href="#i-${id}"/></svg>`;
const pyWeekday = (iso) => (new Date(iso + "T12:00:00").getDay() + 6) % 7;

function toast(title, body) {
  $("toast-title").textContent = title;
  $("toast-body").textContent = body;
  $("toast").classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => $("toast").classList.remove("show"), 5200);
}

// ---------- KPIs ----------
function setKpi(key, text) {
  const el = document.querySelector(`[data-k="${key}"]`);
  if (!el || el.textContent === text) return;
  const changed = ui.lastKpis[key] !== undefined;
  el.textContent = text;
  ui.lastKpis[key] = text;
  if (changed && el.classList.contains("kpi-val")) { el.classList.add("bump"); setTimeout(() => el.classList.remove("bump"), 1500); }
}

function renderKpis(k, log, today) {
  setKpi("calls", String(k.calls_today));
  setKpi("calls-sub", k.calls_today ? `avg ${Math.floor(k.avg_call_secs / 60)}m ${k.avg_call_secs % 60}s per call` : "no calls yet today");
  setKpi("booked", String(k.booked_today));
  setKpi("booked-sub", `${k.new_patients_today} new patient${k.new_patients_today === 1 ? "" : "s"}`);
  setKpi("prod", money(k.production_today));
  const ins = log.filter((t) => t.tool === "verify_insurance" && dayKey(t.at) === today);
  const inNet = ins.filter((t) => t.detail?.status === "in_network").length;
  setKpi("ins", String(ins.length));
  setKpi("ins-sub", ins.length ? `${inNet} in network` : "verified live on calls");
  setKpi("util", `${k.utilization}%`);
  setKpi("util-sub", `${k.open_chair_hours} open chair-hours`);
  document.querySelector('[data-k="util-bar"]').style.width = `${k.utilization}%`;
}

// ---------- schedule ----------
function renderDays(all, today) {
  if (!ui.selectedDay || !all.some((d) => d.date === ui.selectedDay)) ui.selectedDay = all[0].date;
  const idx = all.findIndex((d) => d.date === ui.selectedDay);
  const start = idx < 5 ? 0 : Math.min(idx - 2, all.length - 5);
  const days = all.slice(start, start + 5);
  const html = days.map((d) => {
    const label = fmt(d.date + "T12:00:00", { weekday: "short", month: "short", day: "numeric" });
    return `<button class="day ${d.date === ui.selectedDay ? "sel" : ""}" data-day="${d.date}">
      <div class="day-top"><b>${label}</b>${d.date === today ? '<span class="today-tag">Today</span>' : ""}</div>
      <div class="meter"><i style="width:${d.fill}%"></i></div>
      <div class="day-meta"><span>${d.fill}% booked</span><span>${money(d.production)}</span></div>
    </button>`;
  }).join("");
  if ($("days").dataset.html !== html) { $("days").innerHTML = html; $("days").dataset.html = html; }
}

const SHORT = {
  "Cleaning and checkup": "Cleaning", "New patient exam and cleaning": "New patient exam",
  "Children's cleaning": "Kids cleaning", "Emergency visit": "Emergency", "Whitening consultation": "Whitening consult",
  "Crown or implant consultation": "Crown consult", "Filling": "Filling",
};

function card(e, heightPx, fresh) {
  const riley = e.source === "voice-agent";
  const first = e.patient.split(" ")[0];
  const name = e.patient;
  const badges = (e.new_patient ? '<span class="np">NEW</span>' : "") + (riley ? `<span class="ai">${icon("spark")}RILEY</span>` : "");
  const codes = e.cdt.length ? ` · <code>${e.cdt.join(" ")}</code>` : "";
  if (heightPx < 50) {
    const short = SHORT[e.service] || e.service;
    return `<div class="appt ${e.category === "block" ? "block-ev" : e.category} ${riley ? "by-riley" : ""} ${fresh ? "fresh" : ""} slim"
      style="top:var(--t);height:var(--h)" title="${esc(name)} · ${esc(e.service)}">
      <div class="appt-l1"><span class="nm">${esc(name)}</span><span class="svc">${esc(short)}${e.cdt.length ? ` <code>${e.cdt[0]}</code>` : ""}</span>${badges}</div></div>`;
  }
  const l3 = heightPx >= 62 && e.insurance ? `<div class="appt-l3">${esc(e.insurance)}${e.confirmation ? " · #" + esc(e.confirmation) : ""}</div>` : "";
  const l2 = heightPx >= 36 ? `<div class="appt-l2">${esc(e.service)}${codes}</div>` : "";
  return `<div class="appt ${e.category === "block" ? "block-ev" : e.category} ${riley ? "by-riley" : ""} ${fresh ? "fresh" : ""}"
    style="top:var(--t);height:var(--h)" title="${esc(name)} · ${esc(e.service)}" data-first="${esc(first)}">
    <div class="appt-l1"><span class="nm">${esc(name)}</span>${badges}</div>${l2}${l3}</div>`;
}

function renderGrid(state, freshIds) {
  const grid = $("grid");
  const H = grid.clientHeight || 600;
  const pct = (m) => ((m - DAY_START) / SPAN) * 100;
  const day = ui.selectedDay;
  const open = (state.hours[String(pyWeekday(day))] || []).map(([a, b]) => {
    const [ah, am] = a.split(":"), [bh, bm] = b.split(":");
    return [+ah * 60 + +am, +bh * 60 + +bm];
  });

  let axis = "";
  for (let m = DAY_START; m <= DAY_END; m += 30) {
    axis += `<div class="hr ${m % 60 ? "half" : ""}" style="top:${pct(m)}%"></div>`;
    if (m % 60 === 0 && m < DAY_END) axis += `<div class="tick" style="top:${pct(m)}%">${hhmm(m).replace(" ", "")}</div>`;
  }

  const blocks = [];
  let cursor = DAY_START;
  for (const [a, b] of open) { if (a > cursor) blocks.push([cursor, a]); cursor = b; }
  if (cursor < DAY_END) blocks.push([cursor, DAY_END]);

  const cols = ["hygiene", "doctor"].map((lane) => {
    let html = "";
    for (let m = DAY_START; m <= DAY_END; m += 30) html += `<div class="hr ${m % 60 ? "half" : ""}" style="top:${pct(m)}%"></div>`;
    for (const [a, b] of blocks) {
      const label = a === 720 ? "Lunch" : "Closed";
      html += `<div class="block" style="top:${pct(a)}%;height:${pct(b) - pct(a)}%">${b - a >= 45 ? label : ""}</div>`;
    }
    for (const e of state.events) {
      if (dayKey(e.start) !== day || (e.provider !== lane && e.provider !== "all")) continue;
      const s = Math.max(minutesOf(e.start), DAY_START), en = Math.min(minutesOf(e.end) || DAY_END, DAY_END);
      const top = pct(s), h = pct(en) - pct(s);
      html += card(e, (h / 100) * H, freshIds.has(e.id) || ui.freshUntil.has(e.id)).replace("var(--t)", `${top}%`).replace("var(--h)", `calc(${h}% - 3px)`);
    }
    return `<div class="col">${html}</div>`;
  });

  let now = "";
  if (dayKey(state.now) === day) {
    const m = minutesOf(state.now);
    if (m > DAY_START && m < DAY_END) now = `<div class="now" style="top:${pct(m)}%" data-t="${fmt(state.now, { hour: "numeric", minute: "2-digit" }).replace(" ", "")}"></div>`;
  }
  const html = `<div class="axis">${axis}</div>${cols[0].replace('<div class="col">', `<div class="col">${now}`)}${cols[1]}`;
  if (html !== ui.gridSig) { grid.innerHTML = html; ui.gridSig = html; }
}

// ---------- Riley's actions ----------
const ACT = {
  verify_insurance: (t) => ["shield", "Verified insurance",
    `${t.detail?.carrier || t.args.carrier} · ${(t.detail?.status || "").replace(/_/g, " ")}`],
  check_availability: (t) => ["search", "Searched the schedule",
    t.detail?.slots?.length ? `${t.detail.service_label}: ${t.detail.slots.slice(0, 2).map((s) => s.replace(/^(today|tomorrow), /, "")).join(" · ")}` : (t.detail?.note || t.summary)],
  book_appointment: (t) => t.ok
    ? ["check", "Booked appointment", `${t.detail?.patient_name || t.args.patient_name} · ${t.detail?.spoken || ""} · #${t.detail?.confirmation_code || ""}`]
    : ["check", "Booking declined by clinic rules", t.detail?.message || t.summary],
  request_callback: (t) => ["back", t.args.urgency === "urgent" ? "Urgent callback requested" : "Callback requested", t.args.reason],
};

function renderFeed(log) {
  const first = ui.seenTools === null;
  ui.seenTools = ui.seenTools || new Set();
  const today = log.filter((t) => dayKey(t.at) === dayKey(ui.state.now));
  $("act-count").textContent = today.length ? `${today.length} today` : "";
  const sig = log.slice(0, 7).map((t) => t.id).join();
  if (log.length && $("feed").dataset.sig !== sig) {
    $("feed").dataset.sig = sig;
    $("feed").innerHTML = log.slice(0, 7).map((t) => {
      const [ic, title, detail] = (ACT[t.tool] || (() => ["spark", t.tool, t.summary]))(t);
      const isNew = !first && !ui.seenTools.has(t.id);
      return `<div class="act ${t.ok ? "" : "fail"} ${isNew ? "new" : ""}">
        <div class="act-ic">${icon(ic)}</div>
        <div><div class="act-t">${esc(title)}</div><div class="act-d">${esc(detail)}</div></div>
        <div class="act-ms">${fmt(t.at, { hour: "numeric", minute: "2-digit" }).replace(" ", "").toLowerCase()}<br>${t.ms} ms</div>
      </div>`;
    }).join("");
  }
  log.forEach((t) => ui.seenTools.add(t.id));
}

function renderCallbacks(cbs) {
  const sig = cbs.map((c) => c.id).join();
  if (!cbs.length || $("callbacks").dataset.sig === sig) return;
  $("callbacks").dataset.sig = sig;
  $("callbacks").innerHTML = cbs.slice(0, 3).map((c) =>
    `<div class="cb"><div><b>${esc(c.patient_name)}</b><span>${esc(c.reason)} · ${esc(c.phone)}</span></div>${c.urgency === "urgent" ? '<span class="urg">Urgent</span>' : ""}</div>`).join("");
}

// ---------- patient intake (built from Riley's tool calls during the live call) ----------
function setField(f, html) {
  const dd = document.querySelector(`[data-f="${f}"] dd`);
  if (ui.intake[f] === html) return;
  ui.intake[f] = html;
  dd.innerHTML = html;
  dd.classList.remove("filled"); void dd.offsetWidth; dd.classList.add("filled");
}

function renderIntake(log) {
  if (!ui.callStart) return;
  const calls = log.filter((t) => new Date(t.at) >= ui.callStart).reverse();
  for (const t of calls) {
    if (t.tool === "verify_insurance") {
      const st = t.detail?.status;
      const pill = st === "in_network" ? '<span class="ok-pill">In network</span>' : st ? `<span class="ok-pill no-pill">${esc(st.replace(/_/g, " "))}</span>` : "";
      setField("insurance", `${esc(t.detail?.carrier || t.args.carrier)}${pill}`);
    }
    if (t.tool === "check_availability" && t.detail?.service_label) setField("visit", esc(t.detail.service_label));
    if (t.tool === "book_appointment" && t.ok) {
      setField("patient", esc(t.detail?.patient_name || t.args.patient_name));
      setField("phone", `•••• ${esc(String(t.args.phone).slice(-4))}`);
      setField("visit", esc(t.detail?.service || ""));
      setField("appt", esc((t.detail?.spoken || "").replace(/^(today|tomorrow), /, "")));
      setField("conf", `#${esc(t.detail?.confirmation_code || "")} <span class="ok-pill">Booked</span>`);
      $("intake-state").textContent = "Booked";
      $("intake-state").className = "intake-state done";
    }
    if (t.tool === "request_callback") {
      setField("patient", esc(t.args.patient_name));
      setField("phone", `•••• ${esc(String(t.args.phone).slice(-4))}`);
    }
  }
}

function resetIntake() {
  ui.intake = {};
  document.querySelectorAll("#intake dd").forEach((dd) => { dd.textContent = "—"; dd.classList.remove("filled"); });
  $("intake-state").textContent = "Listening";
  $("intake-state").className = "intake-state on";
}

// ---------- calls that come in from the phone line (not this browser) ----------
function renderLive(live) {
  if (!live || ui.conversation) return;
  const L = ui.live;
  if (live.active && live.conversation_id !== L.id) {
    Object.assign(L, { id: live.conversation_id, on: true, count: 0, mode: "" });
    ui.conversationId = live.conversation_id;
    ui.callStart = new Date(new Date(live.started).getTime() - 2000);
    $("transcript").innerHTML = "";
    resetIntake();
    $("avatar").classList.add("live");
    $("timer").classList.add("on");
    clearInterval(ui.timerId);
    ui.timerId = setInterval(tickTimer, 500);
    $("call-btn").disabled = true;
    $("call-label").textContent = "Riley is on a call";
    $("review").innerHTML = '<div class="placeholder">When a call ends, ElevenLabs scores it against the clinic\'s rules and the review lands here.</div>';
    $("review-state").textContent = "";
  }
  if (!L.on || live.conversation_id !== L.id) return;
  for (const m of live.messages.slice(L.count)) addMsg(m.role, m.text);
  L.count = live.messages.length;
  if (live.mode !== L.mode) {
    L.mode = live.mode;
    $("status").textContent = live.mode === "speaking" ? "Riley is speaking · incoming call" : "Listening · incoming call";
  }
  if (!live.active) {
    L.on = false;
    $("call-btn").disabled = false;
    endUi(true);
  }
}

// ---------- poll ----------
async function poll() {
  try {
    const state = await (await fetch("/api/state")).json();
    ui.state = state;
    const today = dayKey(state.now);
    $("cal-name").textContent = state.calendar === "google" ? "Google Calendar · synced" : "Clinic calendar · synced";
    $("clock").textContent = fmt(state.now, { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" });

    // New bookings by Riley: jump to that day, animate the card, announce it.
    const firstRender = ui.seenEvents === null;
    ui.seenEvents = ui.seenEvents || new Set();
    const fresh = firstRender ? [] : state.events.filter((e) => e.source === "voice-agent" && !ui.seenEvents.has(e.id));
    state.events.forEach((e) => ui.seenEvents.add(e.id));
    if (fresh.length) ui.selectedDay = dayKey(fresh[0].start);

    renderKpis(state.kpis, state.tool_log, today);
    renderDays(state.kpis.days, today);
    const t0 = Date.now();
    fresh.forEach((e) => ui.freshUntil.set(e.id, t0 + 2500));
    for (const [id, until] of ui.freshUntil) if (until < t0) ui.freshUntil.delete(id);
    renderGrid(state, new Set(fresh.map((e) => e.id)));
    renderFeed(state.tool_log);
    renderCallbacks(state.callbacks);
    renderIntake(state.tool_log);
    renderLive(state.live);

    for (const e of fresh) {
      document.querySelector(`.day[data-day="${dayKey(e.start)}"]`)?.classList.add("flash");
      toast(`Riley booked ${e.patient}`, `${e.service} · ${fmt(e.start, { weekday: "long", hour: "numeric", minute: "2-digit" })} · #${e.confirmation}`);
    }
  } catch (err) { /* server restarting: try again next tick */ }
  setTimeout(poll, 1000);
}

$("days").addEventListener("click", (ev) => {
  const b = ev.target.closest(".day");
  if (!b || !ui.state) return;
  ui.selectedDay = b.dataset.day;
  renderDays(ui.state.kpis.days, dayKey(ui.state.now));
  renderGrid(ui.state, new Set());
});
window.addEventListener("resize", () => ui.state && renderGrid(ui.state, new Set()));

// ---------- call ----------
const bars = $("bars");
bars.innerHTML = "<i></i>".repeat(9);

function animate() {
  const els = bars.children;
  const t = performance.now() / 140;
  const v = ui.conversation ? Math.min(1, ui.conversation.getOutputVolume() * 2.4 + ui.conversation.getInputVolume() * 0.8)
    : ui.live.on && ui.live.mode === "speaking" ? 0.55 + 0.35 * Math.sin(t * 1.7) * Math.sin(t * 0.6) : 0;
  for (let i = 0; i < els.length; i++) {
    const wave = 0.55 + 0.45 * Math.sin(t + i * 0.9);
    els[i].style.height = `${6 + v * 20 * wave * (1 - Math.abs(i - 4) / 6)}px`;
  }
  requestAnimationFrame(animate);
}
animate();

function addMsg(role, text) {
  const box = $("transcript");
  box.querySelector(".placeholder")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text.replace(/\[[a-z ]+\]\s*/g, "");
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

function tickTimer() {
  const s = Math.floor((Date.now() - ui.callStart) / 1000);
  $("timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

async function startCall() {
  const btn = $("call-btn");
  btn.disabled = true;
  $("status").textContent = "Connecting…";
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true });
    const res = await fetch("/api/signed-url");
    const body = await res.json();
    if (!res.ok) throw new Error(body.message || "Could not start the call");
    $("transcript").innerHTML = "";
    resetIntake();
    ui.callStart = new Date(Date.now() - 2000);
    ui.conversation = await ElevenLabsClient.Conversation.startSession({
      signedUrl: body.signed_url,
      onConnect: ({ conversationId }) => {
        ui.conversationId = conversationId;
        $("avatar").classList.add("live");
        $("timer").classList.add("on");
        ui.timerId = setInterval(tickTimer, 500);
      },
      onDisconnect: () => endUi(),
      onMessage: (m) => addMsg(m.role || (m.source === "ai" ? "agent" : "user"), m.message),
      onModeChange: ({ mode }) => { $("status").textContent = mode === "speaking" ? "Riley is speaking" : "Listening…"; },
      onError: (msg) => { $("status").textContent = `Connection issue: ${msg}`; },
    });
    btn.classList.add("end");
    $("call-label").textContent = "End call";
  } catch (e) {
    $("status").textContent = e.message;
    ui.conversation = null;
  } finally {
    btn.disabled = false;
  }
}

function endUi(force = false) {
  if (!force && !ui.conversation && !ui.timerId) return;
  ui.conversation = null;
  clearInterval(ui.timerId); ui.timerId = null;
  $("timer").classList.remove("on");
  $("avatar").classList.remove("live");
  $("call-btn").classList.remove("end");
  $("call-label").textContent = "Start a call with Riley";
  $("status").textContent = "Call ended · scoring the call…";
  if ($("intake-state").textContent === "Listening") { $("intake-state").textContent = "Call ended"; $("intake-state").className = "intake-state"; }
  if (ui.conversationId) loadReview(ui.conversationId);
}

// ---------- post-call review (ElevenLabs analysis) ----------
const CRIT = {
  booking_completed_correctly: "Booking done right",
  no_clinical_advice: "No clinical advice",
  emergency_handled_safely: "Emergency-safe",
  minimum_necessary_data: "Minimum data only",
};
const DATA = { caller_intent: "Intent", appointment_booked: "Booked", service_booked: "Service", insurance_carrier: "Insurance", new_patient: "New patient", emergency_flag: "Emergency" };

async function loadReview(id, tries = 0) {
  $("review-state").textContent = "scoring…";
  try {
    const r = await (await fetch(`/api/calls/${id}`)).json();
    if (!r.ready) {
      if (tries < 40) return setTimeout(() => loadReview(id, tries + 1), 3000);
      $("review-state").textContent = "";
      return;
    }
    const passed = r.criteria.filter((c) => c.result === "success").length;
    $("review-state").textContent = `${passed}/${r.criteria.length} checks passed`;
    $("status").textContent = "Ready for the next caller";
    const val = (v) => v === true ? "Yes" : v === false ? "No" : (v ?? "—");
    $("review").innerHTML = `
      <div class="rv-title">${esc(r.title || "Call summary")} · ${Math.floor(r.duration_secs / 60)}m ${r.duration_secs % 60}s</div>
      <div class="rv-sum">${esc(r.summary)}</div>
      <div class="rv-crit">${r.criteria.map((c) => `<span class="crit ${c.result}" title="${esc(c.rationale)}">${c.result === "success" ? "✓" : c.result === "failure" ? "✕" : "?"} ${esc(CRIT[c.id] || c.id)}</span>`).join("")}</div>
      <dl class="rv-data">${Object.entries(DATA).filter(([k]) => r.data[k] !== undefined && r.data[k] !== null && r.data[k] !== "").map(([k, label]) => `<dt>${label}</dt><dd>${esc(val(r.data[k]))}</dd>`).join("")}</dl>`;
  } catch (e) {
    if (tries < 40) setTimeout(() => loadReview(id, tries + 1), 3000);
  }
}

$("call-btn").addEventListener("click", async () => {
  if (ui.conversation) { await ui.conversation.endSession(); endUi(); } else { startCall(); }
});

poll();
