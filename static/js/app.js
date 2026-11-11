import { AudioEngine } from "./audio.js";
import { Orb } from "./orb.js";
import {
  h,
  renderActions,
  renderActivity,
  renderDiagnosis,
  renderInsights,
  renderMetrics,
  renderPlan,
  renderProgress,
  renderSummary,
  summaryMarkdown,
} from "./render.js";

const $ = (id) => document.getElementById(id);

const ui = {
  stage: $("stage"),
  statusLabel: $("status-label"),
  statusSub: $("status-sub"),
  timer: $("call-timer"),
  options: $("call-options"),
  callBtn: $("call-btn"),
  callBtnLabel: $("call-btn-label"),
  muteBtn: $("mute-btn"),
  endBtn: $("end-btn"),
  hint: $("hint"),
  tryHints: $("try-hints"),
  tryList: $("try-list"),
  followupBtn: $("followup-btn"),
  transcript: $("transcript-list"),
  caseId: $("case-id"),
  metrics: document.querySelector("#metrics-table tbody"),
  diagnosis: $("diagnosis-body"),
  progress: $("progress-body"),
  insights: $("insights-body"),
  plan: $("plan-body"),
  actions: $("actions-body"),
  summaryCard: $("card-summary"),
  summary: $("summary-body"),
  activityList: $("activity-list"),
  activityCount: $("activity-count"),
  assumptions: $("assumptions-list"),
  modelNote: $("model-note"),
  downloadBtn: $("download-btn"),
  toast: $("toast"),
};

const orb = new Orb($("orb"));

const state = {
  phase: "idle", // idle | connecting | live | ending
  stage: "idle", // idle | connecting | listening | speaking | thinking
  config: null,
  ws: null,
  audio: null,
  muted: false,
  caseFile: null,
  startedAt: 0,
  timerId: null,
  bubbles: { seller: null, kam: null },
  pendingHangup: false,
  hangupTimer: null,
  drainTimer: null,
  streaming: false, // mic audio flows only after the call is configured
  modelTurn: false, // Disha's turn is in progress until the server says turn_complete
  lastCompletedCase: null, // the case a "7-day follow-up" call builds on
};

const TRY_HINTS = {
  inbound: [
    "“My sales have dropped this month. Can you help?”",
    "“Which products are out of stock?”",
    "“Should I just cut my prices?”",
    "“मेरी सेल्स इतनी कम क्यों हो गई?”",
  ],
  outbound: ["“Yes, I have two minutes.”", "“Why is this happening?”", "“I only have ₹25,000 to restock.”"],
  followup: ["“How am I doing against the targets?”", "“The spice rack supplier is still delayed.”", "“What should I do next?”"],
};

/* ------------------------------------------------------------------ stage & status */

const STAGE_TEXT = {
  idle: ["Ready when you are", "Press call and speak naturally, in English or Hindi."],
  connecting: ["Connecting…", "Setting up a secure voice line to Disha."],
  listening: ["Listening…", "Go ahead, Disha is listening. You can interrupt her any time."],
  speaking: ["Disha is speaking", "Jump in whenever you like."],
  thinking: ["Working on it…", "Disha is checking your account."],
  muted: ["You're muted", "Unmute to keep talking to Disha."],
};

function setStage(stage, label) {
  state.stage = stage;
  const key = stage === "listening" && state.muted ? "muted" : stage;
  const [title, sub] = STAGE_TEXT[key];
  ui.stage.dataset.state = stage;
  ui.statusLabel.textContent = label || title;
  ui.statusSub.textContent = sub;
  orb.setState(stage === "connecting" ? "connecting" : stage);
}

orb.getLevel = () => {
  if (!state.audio) return 0;
  if (state.stage === "speaking") return state.audio.outLevel;
  if (state.stage === "listening" && !state.muted) return state.audio.micLevel;
  return 0;
};

function toast(message, ms = 4200) {
  ui.toast.textContent = message;
  ui.toast.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (ui.toast.hidden = true), ms);
}

/* ------------------------------------------------------------------ transcript */

function clearTranscript() {
  ui.transcript.replaceChildren();
  state.bubbles = { seller: null, kam: null };
}

function scrollTranscript() {
  ui.transcript.scrollTop = ui.transcript.scrollHeight;
}

function appendTranscript(role, text) {
  let bubble = state.bubbles[role];
  if (!bubble) {
    const body = h("span", { class: "text" });
    bubble = h(
      "li",
      { class: `bubble bubble-${role === "kam" ? "kam" : "seller"}` },
      h("span", { class: "who", text: role === "kam" ? "Disha" : state.config?.seller?.seller_name?.split(" ")[0] || "Seller" }),
      body,
    );
    bubble.body = body;
    ui.transcript.append(bubble);
    state.bubbles[role] = bubble;
  }
  bubble.body.textContent += text;
  scrollTranscript();
}

function appendToolNote(label) {
  state.bubbles.kam = null; // speech after a tool call starts a fresh bubble
  ui.transcript.append(h("li", { class: "bubble bubble-tool", text: label }));
  scrollTranscript();
}

/* ------------------------------------------------------------------ case file */

function flash(cardId) {
  const card = $(cardId);
  card.classList.remove("flash");
  void card.offsetWidth; // restart the animation
  card.classList.add("flash");
}

function renderCase(caseFile, { animate = true } = {}) {
  const prev = state.caseFile;
  state.caseFile = caseFile;
  ui.caseId.hidden = false;
  ui.caseId.textContent = `Case ${caseFile.case_id}`;

  const sections = [
    ["card-progress", () => renderProgress(ui.progress, caseFile.progress), (c) => c?.progress],
    ["card-diagnosis", () => renderDiagnosis(ui.diagnosis, caseFile.diagnosis), (c) => c?.diagnosis],
    ["card-insights", () => renderInsights(ui.insights, caseFile.insights), (c) => c?.insights],
    [
      "card-plan",
      () => renderPlan(ui.plan, caseFile.action_plan, caseFile.kpi_targets, caseFile.restock_plan),
      (c) => [c?.action_plan, c?.kpi_targets, c?.restock_plan],
    ],
    ["card-actions", () => renderActions(ui.actions, caseFile.actions_taken, caseFile.follow_up), (c) => [c?.actions_taken, c?.follow_up]],
  ];
  for (const [cardId, render, pick] of sections) {
    const changed = JSON.stringify(pick(prev)) !== JSON.stringify(pick(caseFile));
    if (!changed) continue;
    if (render()) {
      $(cardId).classList.add("filled");
      if (animate) flash(cardId);
    }
  }
  if (caseFile.summary && JSON.stringify(prev?.summary) !== JSON.stringify(caseFile.summary)) {
    renderSummary(ui.summary, caseFile.summary);
    ui.summaryCard.hidden = false;
    if (animate) flash("card-summary");
    ui.summaryCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  renderActivity(ui.activityList, ui.activityCount, caseFile.activity);
}

function resetCaseFile(mode = selected("mode")) {
  state.caseFile = null;
  ui.caseId.hidden = true;
  const followUp = mode === "followup";
  $("card-progress").hidden = !followUp;
  $("card-diagnosis").hidden = followUp;
  ui.progress.replaceChildren(h("p", { class: "empty", text: "Disha reviews last week's targets first." }));
  ui.diagnosis.replaceChildren(h("p", { class: "empty", text: "Disha runs the diagnosis as soon as the seller describes the problem." }));
  ui.insights.replaceChildren(h("p", { class: "empty", text: "Answers to Disha's follow-up questions land here." }));
  ui.plan.replaceChildren(h("p", { class: "empty", text: "2–3 prioritised actions with expected impact, owner and timeline." }));
  ui.actions.replaceChildren(h("p", { class: "empty", text: "Actions Disha executes with permission, and the follow-up she books." }));
  ui.summaryCard.hidden = true;
  document.querySelectorAll(".card.filled").forEach((c) => c.classList.remove("filled"));
  renderActivity(ui.activityList, ui.activityCount, []);
}

/* ------------------------------------------------------------------ call lifecycle */

function selected(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value;
}

function setControls(phase) {
  const inCall = phase === "connecting" || phase === "live";
  ui.callBtn.hidden = inCall;
  ui.callBtn.disabled = false;
  ui.options.hidden = inCall;
  ui.muteBtn.hidden = !inCall;
  ui.endBtn.hidden = !inCall;
  ui.timer.hidden = !inCall;
  ui.tryHints.hidden = inCall;
  if (inCall) ui.followupBtn.hidden = true;
}

function startTimer() {
  state.startedAt = Date.now();
  const tick = () => {
    const s = Math.floor((Date.now() - state.startedAt) / 1000);
    ui.timer.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };
  tick();
  state.timerId = setInterval(tick, 1000);
}

async function startCall({ previousCase = null } = {}) {
  if (state.phase !== "idle") return;
  const mode = selected("mode") || "inbound";
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
    toast("This browser can't capture audio. Please use a recent Chrome, Edge, Safari or Firefox.");
    return;
  }
  state.phase = "connecting";
  state.streaming = false;
  ui.callBtn.disabled = true;
  resetCaseFile(mode);
  clearTranscript();
  setStage("connecting");

  const audio = new AudioEngine({
    onMicChunk: (pcm) => {
      if (!state.streaming || state.muted || state.ws?.readyState !== WebSocket.OPEN) return;
      state.ws.send(echoGuard(pcm));
    },
    onPlaybackChange: onPlaybackChange,
  });
  state.audio = audio;
  try {
    await audio.start();
  } catch (err) {
    console.error(err);
    await audio.stop();
    state.audio = null;
    state.phase = "idle";
    ui.callBtn.disabled = false;
    setStage("idle");
    toast(err?.name === "NotAllowedError" ? "Microphone access is needed for a voice call. Please allow it and try again." : "Couldn't start audio on this device.");
    return;
  }
  setControls("connecting");

  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ mode, lang: selected("lang") || "en" });
  const ws = new WebSocket(`${scheme}://${location.host}/ws/call?${params}`);
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  ws.onopen = () => {
    if (mode === "followup") {
      ws.send(JSON.stringify({ type: "start", previous_case: compactCase(previousCase || state.lastCompletedCase) }));
    }
    state.streaming = true;
  };
  ws.onmessage = onSocketMessage;
  ws.onclose = () => {
    if (state.ws === ws && state.phase !== "idle") endCall(state.pendingHangup ? "completed" : "disconnected");
  };
  ws.onerror = () => toast("Connection problem. Please check your network and try again.");
}

/** Only what the follow-up call needs from the previous case (the server re-validates it). */
function compactCase(c) {
  if (!c) return null;
  return {
    case_id: c.case_id,
    action_plan: c.action_plan,
    kpi_targets: c.kpi_targets,
    actions_taken: c.actions_taken,
    summary: c.summary,
    insights: c.insights,
    restock_plan: c.restock_plan ? { items: (c.restock_plan.within_budget || c.restock_plan.items).map((i) => ({ product: i.product })) } : null,
  };
}

/**
 * Speaker-safe barge-in: while Disha is talking, only pass mic audio that is clearly louder than her echo would
 * be. Browser echo cancellation removes most of it; this guard stops any leftover from making her interrupt herself.
 * Silence is sent instead so the audio stream stays continuous.
 */
function echoGuard(pcm) {
  if (!state.audio?.playing) return pcm;
  const samples = new Int16Array(pcm);
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  const micRms = Math.sqrt(sum / samples.length) / 32768;
  const threshold = Math.max(0.012, state.audio.outLevel * 0.3);
  return micRms >= threshold ? pcm : new ArrayBuffer(pcm.byteLength);
}

function onSocketMessage(event) {
  if (event.data instanceof ArrayBuffer) {
    state.modelTurn = true;
    state.audio?.play(event.data);
    clearTimeout(state.hangupTimer);
    return;
  }
  let msg;
  try {
    msg = JSON.parse(event.data);
  } catch {
    return;
  }
  switch (msg.type) {
    case "ready":
      state.phase = "live";
      setControls("live");
      startTimer();
      setStage("thinking", "Disha is joining…");
      renderCase(msg.case, { animate: false });
      break;
    case "transcript":
      appendTranscript(msg.role, msg.text);
      if (msg.role === "seller") {
        if (state.pendingHangup) cancelHangup(); // the seller is still talking: keep the line open
        if (state.stage !== "speaking") setStage("listening");
      }
      break;
    case "interrupted":
      state.modelTurn = false;
      state.audio?.clear();
      if (state.bubbles.kam) state.bubbles.kam.classList.add("interrupted");
      state.bubbles = { seller: null, kam: null };
      setStage("listening");
      break;
    case "turn_complete":
      state.modelTurn = false;
      state.audio?.flush();
      state.bubbles = { seller: null, kam: null };
      if (!state.audio?.playing && state.phase === "live") setStage("listening");
      break;
    case "tool_started":
      state.modelTurn = true;
      setStage("thinking", `${msg.label}…`);
      appendToolNote(msg.label);
      break;
    case "case":
      renderCase(msg.case);
      break;
    case "hangup":
      state.pendingHangup = true;
      maybeHangup();
      break;
    case "notice":
      toast(msg.message);
      break;
    case "call_ended":
      toast(msg.reason === "time_limit" ? "This demo call reached its time limit." : "The call has ended.");
      endCall(msg.reason);
      break;
    case "error":
      toast(msg.message || "Something went wrong.");
      break;
  }
}

function onPlaybackChange(playing) {
  clearTimeout(state.drainTimer);
  if (playing) {
    if (state.phase === "live") setStage("speaking");
    return;
  }
  // Debounce: tiny gaps between audio chunks shouldn't flicker the status. Disha streams in real time, so a
  // pause mid-turn (e.g. while a tool runs) drains the buffer; it's only the seller's turn after turn_complete.
  state.drainTimer = setTimeout(() => {
    if (state.phase === "live" && state.stage === "speaking") setStage(state.modelTurn ? "thinking" : "listening");
    maybeHangup();
  }, 250);
}

function lastDishaLine() {
  const bubbles = ui.transcript.querySelectorAll(".bubble-kam");
  return bubbles.length ? bubbles[bubbles.length - 1].textContent.trim() : "";
}

function maybeHangup() {
  if (!state.pendingHangup || state.audio?.playing) return;
  // Never drop the line right after Disha asked something: let the seller answer.
  if (lastDishaLine().endsWith("?")) return;
  clearTimeout(state.hangupTimer);
  state.hangupTimer = setTimeout(() => {
    if (state.pendingHangup && !state.audio?.playing) endCall("completed");
  }, 2000);
}

function cancelHangup() {
  state.pendingHangup = false;
  clearTimeout(state.hangupTimer);
}

async function endCall(reason = "ended") {
  if (state.phase === "idle") return;
  state.phase = "idle";
  state.streaming = false;
  clearInterval(state.timerId);
  clearTimeout(state.hangupTimer);
  clearTimeout(state.drainTimer);
  const ws = state.ws;
  state.ws = null;
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ type: "end" }));
    } catch {
      /* socket already closing */
    }
    ws.close(1000, "call ended");
  }
  await state.audio?.stop();
  state.audio = null;
  state.pendingHangup = false;
  state.muted = false;
  ui.muteBtn.setAttribute("aria-pressed", "false");
  ui.muteBtn.setAttribute("aria-label", "Mute microphone");
  setControls("idle");
  ui.callBtnLabel.textContent = "Call again";
  if (state.caseFile?.summary) state.lastCompletedCase = state.caseFile;
  const canFollowUp = Boolean(state.caseFile?.follow_up) && state.caseFile.mode !== "followup";
  ui.followupBtn.hidden = !canFollowUp;
  setStage("idle", reason === "completed" ? "Call completed" : "Call ended");
  ui.statusSub.textContent = state.caseFile?.summary ? "The summary has been sent to the seller. Download it from the case file." : "Press call to talk to Disha again.";
}

function toggleMute() {
  state.muted = !state.muted;
  state.audio?.setMicEnabled(!state.muted);
  ui.muteBtn.setAttribute("aria-pressed", String(state.muted));
  ui.muteBtn.setAttribute("aria-label", state.muted ? "Unmute microphone" : "Mute microphone");
  if (state.ws?.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({ type: "mute", muted: state.muted }));
  if (state.stage === "listening") setStage("listening");
}

function downloadSummary() {
  if (!state.caseFile) return;
  const blob = new Blob([summaryMarkdown(state.caseFile, state.config?.seller)], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: `disha-call-summary-${state.caseFile.case_id}.md` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ------------------------------------------------------------------ init */

function updateCallLabel() {
  const mode = selected("mode") || "inbound";
  ui.callBtnLabel.textContent = { inbound: "Call Disha", outbound: "Let Disha call me", followup: "Take Disha's follow-up call" }[mode];
  ui.tryList.replaceChildren(...TRY_HINTS[mode].map((t) => h("li", { text: t })));
}

function startFollowUp() {
  const radio = document.querySelector('input[name="mode"][value="followup"]');
  radio.checked = true;
  updateCallLabel();
  startCall({ previousCase: state.lastCompletedCase });
}

async function init() {
  ui.callBtn.addEventListener("click", () => startCall());
  ui.followupBtn.addEventListener("click", startFollowUp);
  ui.endBtn.addEventListener("click", () => endCall("seller_hung_up"));
  ui.muteBtn.addEventListener("click", toggleMute);
  ui.downloadBtn.addEventListener("click", downloadSummary);
  document.querySelectorAll('input[name="mode"]').forEach((el) => el.addEventListener("change", updateCallLabel));
  window.addEventListener("beforeunload", () => state.ws?.close());
  setStage("idle");

  try {
    const res = await fetch("/api/config", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const config = await res.json();
    state.config = config;
    const s = config.seller;
    $("seller-name").textContent = s.seller_name;
    $("seller-meta").textContent = `${s.business_name} · ${s.city.split(",")[0]} · ${s.category}`;
    $("seller-avatar").textContent = s.seller_name
      .split(" ")
      .map((p) => p[0])
      .join("")
      .slice(0, 2);
    renderMetrics(ui.metrics, config.metrics);
    ui.assumptions.replaceChildren(...config.assumptions.map((a) => h("li", { text: a })));
    ui.modelNote.textContent = `Voice model: ${config.model} (speech-to-speech, voice “${config.voice}”) via the Gemini Live API. Demo calls are capped at ${Math.round(config.max_call_seconds / 60)} minutes.`;
  } catch (err) {
    console.error(err);
    toast("Couldn't load the seller account. Please refresh the page.");
  }
}

init();
