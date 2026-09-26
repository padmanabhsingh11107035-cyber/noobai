/* NOOB App - talks to the NOOB server on this PC (same address this page came from). */
"use strict";

const $ = (id) => document.getElementById(id);
const PROFILE_FIELDS = [
  ["Name", 1], ["Age", 1], ["Gender", 1], ["City", 1], ["Preferred language", 1], ["Blood group", 1],
  ["Height and weight", 1], ["Allergies", 1], ["Medical conditions", 2], ["Current medicines", 2],
  ["Doctor name and phone", 1], ["Emergency contact", 1], ["Hobbies and interests", 1], ["Birthday", 1],
  ["About me", 3],
];

// ---------------------------------------------------------------- helpers
async function api(path, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers["Content-Type"] = "application/json";
    delete opts.json;
  }
  const res = await fetch(path, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error("Please sign in"); }
  if (!res.ok) {
    let message = `Server error ${res.status}`;
    try { message = (await res.json()).error || message; } catch { /* not JSON */ }
    throw new Error(message);
  }
  const type = res.headers.get("Content-Type") || "";
  return type.includes("application/json") ? res.json() : res.blob();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;       // textContent: never runs HTML from data
  return node;
}

function toast(message, bad = false) {
  const t = el("div", "toast" + (bad ? " bad" : ""), message);
  $("toasts").append(t);
  setTimeout(() => { t.style.transition = "opacity .4s"; t.style.opacity = "0"; }, 2600);
  setTimeout(() => t.remove(), 3100);
}

function modal({ title, text = "", body = null, ok = "OK", cancel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    $("modalTitle").textContent = title;
    $("modalText").textContent = text;
    $("modalBody").replaceChildren(...(body ? [body] : []));
    $("modalOk").textContent = ok;
    $("modalOk").className = "btn " + (danger ? "danger ghost" : "primary");
    $("modalCancel").textContent = cancel;
    $("modalCancel").hidden = !cancel;
    $("modal").hidden = false;
    const done = (value) => { $("modal").hidden = true; $("modalOk").onclick = $("modalCancel").onclick = null; resolve(value); };
    $("modalOk").onclick = () => done(true);
    $("modalCancel").onclick = () => done(false);
    const first = $("modalBody").querySelector("input");
    (first || $("modalOk")).focus();
  });
}

const ICONS = {
  edit: '<svg viewBox="0 0 24 24"><path d="M3 17.3V21h3.7L17.8 9.9l-3.7-3.7L3 17.3ZM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.7 3.7L20.7 7Z"/></svg>',
  del: '<svg viewBox="0 0 24 24"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12ZM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4Z"/></svg>',
  device: '<svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5v10a5 5 0 0 0 10 0V7a5 5 0 0 0-5-5Zm0 4a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3Zm0 7a3 3 0 1 1 0 6 3 3 0 0 1 0-6Z"/></svg>',
  brain: '<svg viewBox="0 0 24 24"><path d="M9 21h6v-1H9v1Zm3-19a7 7 0 0 0-4 12.7V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.3A7 7 0 0 0 12 2Z"/></svg>',
};
function iconButton(icon, title, onClick, extra = "") {
  const b = el("button", "icon-btn " + extra);
  b.innerHTML = ICONS[icon];          // fixed, trusted SVG only
  b.title = title;
  b.onclick = onClick;
  return b;
}

// ---------------------------------------------------------------- navigation
const loaders = {};
function showPage() {
  const page = (location.hash || "#talk").slice(1);
  const valid = document.getElementById("page-" + page) ? page : "talk";
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("show", p.id === "page-" + valid));
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === valid));
  if (loaders[valid]) loaders[valid]();
}
window.addEventListener("hashchange", showPage);

// ---------------------------------------------------------------- server status
let serverStatus = null;
async function refreshStatus() {
  try {
    serverStatus = await api("/api/status");
    $("offline").hidden = true;
    $("serverPill").className = "server-pill ok";
    $("serverText").textContent = serverStatus.gemini ? "NOOB is online" : "Online · offline brain";
    const hour = new Date().getHours();
    const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    $("greeting").textContent = serverStatus.profile_name ? `${part}, ${serverStatus.profile_name}!` : `${part}!`;
    const user = serverStatus.user;
    $("userName").textContent = user.name;
    $("userRole").textContent = user.is_owner ? "Owner" : "Member";
    $("avatar").textContent = (user.name.trim()[0] || "?").toUpperCase();
    document.querySelectorAll(".owner-only").forEach((e) => (e.hidden = !user.is_owner));
    const on = serverStatus.devices_online;
    $("deviceStatus").className = "device-status" + (on ? " on" : "");
    $("deviceStatusText").textContent = !serverStatus.devices ? "No NOOB device connected yet"
      : on ? `Your NOOB device is online` : "Your NOOB device is offline";
  } catch (e) {
    if (e.message === "Please sign in") return;
    $("offline").hidden = false;
    $("serverPill").className = "server-pill bad";
    $("serverText").textContent = "Server stopped";
  }
}
setInterval(refreshStatus, 5000);

// ---------------------------------------------------------------- TALK
const orb = $("orb");
let state = "idle";                 // idle / listening / thinking / speaking
let audioCtx = null, recorder = null, micStream = null, currentAudio = null, rafId = 0;

function setState(next, text) {
  state = next;
  orb.className = "orb " + next;
  orb.style.setProperty("--level", 0);
  $("statusLine").textContent = text || { idle: "Tap to talk", listening: "Listening… (tap to stop)",
    thinking: "Thinking…", speaking: "Speaking… (tap to stop)" }[next];
}

function addBubble(who, text, extraClass = "") {
  $("chatEmpty")?.remove();
  const b = el("div", `bubble ${who} ${extraClass}`, text);
  $("chat").append(b);
  $("chat").scrollTop = $("chat").scrollHeight;
  return b;
}
function typingBubble() {
  $("chatEmpty")?.remove();
  const b = el("div", "bubble noob typing");
  b.append(el("span"), el("span"), el("span"));
  $("chat").append(b);
  $("chat").scrollTop = $("chat").scrollHeight;
  return b;
}

function ensureAudio() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

async function startListening() {
  if (state !== "idle") return;
  if (!window.isSecureContext || !navigator.mediaDevices) {
    toast("Voice works on the NOOB PC or on an https:// address. Here you can type your message.", true);
    return;
  }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch {
    toast("Microphone blocked. Allow the microphone for this app and try again.", true);
    return;
  }
  const ctx = ensureAudio();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(micStream).connect(analyser);
  const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find((t) => MediaRecorder.isTypeSupported(t));
  const rec = new MediaRecorder(micStream, type ? { mimeType: type } : undefined);
  const stream = micStream;
  recorder = rec;
  const chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.onstop = () => {
    cancelAnimationFrame(rafId);
    stream.getTracks().forEach((t) => t.stop());
    if (rec.cancelled) { setState("idle"); return; }
    sendVoice(new Blob(chunks, { type: rec.mimeType }));
  };
  rec.start();
  setState("listening");

  // Stop automatically when you stop talking (like a smart speaker).
  const samples = new Float32Array(analyser.fftSize);
  const started = performance.now();
  let noise = 0.01, heardSpeech = false, lastLoud = started;
  const tick = () => {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const s of samples) sum += s * s;
    const level = Math.sqrt(sum / samples.length);
    const now = performance.now();
    if (now - started < 350) noise = Math.max(noise, level);           // measure room noise first
    const threshold = Math.max(0.02, noise * 2.2);
    if (level > threshold) { heardSpeech = true; lastLoud = now; }
    orb.style.setProperty("--level", Math.min(1, level * 6).toFixed(3));
    const silentFor = now - lastLoud, total = now - started;
    if ((heardSpeech && silentFor > 1300) || total > 15000) return stopListening();
    if (!heardSpeech && total > 7000) { recorder.cancelled = true; toast("I didn't hear anything."); return stopListening(); }
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}

function stopListening() {
  if (recorder && recorder.state === "recording") recorder.stop();
}

async function sendVoice(blob) {
  setState("thinking");
  const typing = typingBubble();
  try {
    const r = await api("/api/voice", { method: "POST", body: blob, headers: { "Content-Type": blob.type } });
    typing.remove();
    if (r.you) addBubble("you", r.you);
    await showAnswer(r);
  } catch (e) {
    typing.remove();
    addBubble("noob", "Could not reach the NOOB server.", "error");
    setState("idle");
  }
}

async function sendText(text) {
  if (!text.trim() || state === "thinking") return;
  stopSpeaking();
  addBubble("you", text);
  setState("thinking");
  const typing = typingBubble();
  try {
    const r = await api("/api/chat", { method: "POST", json: { text } });
    typing.remove();
    await showAnswer(r, false);
  } catch {
    typing.remove();
    addBubble("noob", "Could not reach the NOOB server.", "error");
    setState("idle");
  }
}

async function showAnswer(r, fromVoice = true) {
  addBubble("noob", r.answer, r.ok ? "" : "error");
  try {
    const wav = await api("/api/speak", { method: "POST", json: { text: r.answer, lang: r.lang } });
    await playVoice(wav);
  } catch {
    toast("Could not play NOOB's voice (internet needed for the voice).", true);
  }
  setState("idle");
  if (fromVoice && r.ok && $("convMode").checked) setTimeout(startListening, 350);   // keep talking
}

function playVoice(blob) {
  return new Promise((resolve) => {
    const ctx = ensureAudio();
    const audio = new Audio(URL.createObjectURL(blob));
    currentAudio = audio;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaElementSource(audio).connect(analyser);
    analyser.connect(ctx.destination);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length / 255;
      orb.style.setProperty("--level", Math.min(1, avg * 2.2).toFixed(3));
      rafId = requestAnimationFrame(tick);
    };
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      cancelAnimationFrame(rafId);
      URL.revokeObjectURL(audio.src);
      currentAudio = null;
      resolve();
    };
    audio.onended = finish;
    audio.onerror = finish;
    audio.onpause = finish;
    setState("speaking");
    audio.play().then(() => { rafId = requestAnimationFrame(tick); }).catch(finish);
  });
}

function stopSpeaking() {
  if (currentAudio) currentAudio.pause();
}

$("orbBtn").onclick = () => {
  if (state === "idle") startListening();
  else if (state === "listening") stopListening();
  else if (state === "speaking") { $("convMode").checked = false; stopSpeaking(); }
};
$("composer").onsubmit = (e) => { e.preventDefault(); const t = $("typeBox").value; $("typeBox").value = ""; sendText(t); };
document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => sendText(c.textContent)));
document.addEventListener("keydown", (e) => {        // Space bar = talk (when not typing)
  if (e.code === "Space" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName) && location.hash.match(/^(#talk)?$/)) {
    e.preventDefault();
    $("orbBtn").click();
  }
});
loaders.talk = async () => {
  if ($("chat").querySelector(".bubble")) return;
  try {                                               // show the last few messages
    const log = await api("/api/conversation");
    log.slice(-6).forEach((m) => addBubble(m.role === "user" ? "you" : "noob", m.text.replace(/^\[[a-z-]+\]\s*/i, "")));
  } catch { /* offline overlay handles it */ }
};

// ---------------------------------------------------------------- ABOUT ME
function buildProfileForm() {
  const form = $("profileForm");
  PROFILE_FIELDS.forEach(([name, lines]) => {
    const label = el("label", "field" + (lines > 1 ? " wide" : ""));
    label.append(el("span", "", name));
    const input = lines > 1 ? el("textarea") : el("input");
    if (lines > 1) input.rows = lines;
    input.dataset.field = name;
    input.maxLength = 1000;
    label.append(input);
    form.append(label);
  });
}
loaders.about = async () => {
  const profile = await api("/api/profile");
  document.querySelectorAll("#profileForm [data-field]").forEach((i) => (i.value = profile[i.dataset.field] || ""));
};
$("saveProfile").onclick = async () => {
  const data = {};
  document.querySelectorAll("#profileForm [data-field]").forEach((i) => (data[i.dataset.field] = i.value));
  await api("/api/profile", { method: "PUT", json: data });
  toast("Saved! NOOB will use your details from now on.");
  refreshStatus();
};

// ---------------------------------------------------------------- MEMORY
let facts = [];
function renderFacts() {
  const q = $("factSearch").value.toLowerCase();
  const list = $("factList");
  const shown = facts.filter((f) => f.fact.toLowerCase().includes(q));
  list.replaceChildren();
  if (!shown.length) list.append(el("div", "empty", facts.length ? "Nothing matches your search." :
    "NOOB doesn't remember anything yet. Tell it about yourself, or add something above."));
  shown.slice().reverse().forEach((f) => {
    const item = el("div", "item");
    const icon = el("div", "icon-circle");
    icon.innerHTML = ICONS.brain;
    const grow = el("div", "grow");
    grow.append(el("div", "title", f.fact), el("div", "meta", `Saved ${f.saved_at}`));
    item.append(icon, grow,
      iconButton("edit", "Edit", async () => {
        const input = el("input");
        input.value = f.fact;
        input.maxLength = 500;
        if (await modal({ title: "Edit memory", body: input, ok: "Save" }) && input.value.trim()) {
          await api(`/api/facts/${f.id}`, { method: "PUT", json: { fact: input.value } });
          toast("Memory updated");
          loaders.memory();
        }
      }),
      iconButton("del", "Delete", async () => {
        if (await modal({ title: "Forget this?", text: f.fact, ok: "Forget", danger: true })) {
          await api(`/api/facts/${f.id}`, { method: "DELETE" });
          toast("NOOB forgot it");
          loaders.memory();
        }
      }, "del"));
    list.append(item);
  });
}
loaders.memory = async () => { facts = await api("/api/facts"); renderFacts(); };
$("factSearch").oninput = renderFacts;
$("addFact").onsubmit = async (e) => {
  e.preventDefault();
  const fact = $("newFact").value.trim();
  if (!fact) return;
  await api("/api/facts", { method: "POST", json: { fact } });
  $("newFact").value = "";
  toast("NOOB will remember that");
  loaders.memory();
};

// ---------------------------------------------------------------- CONVERSATIONS
let chatLog = [];
function renderHistory() {
  const q = $("historySearch").value.toLowerCase();
  const box = $("historyList");
  box.replaceChildren();
  const shown = chatLog.filter((m) => m.text.toLowerCase().includes(q));
  if (!shown.length) { box.append(el("div", "empty", chatLog.length ? "Nothing matches your search." : "No conversations yet.")); return; }
  let day = "";
  shown.forEach((m) => {
    const d = m.time.slice(0, 10);
    if (d !== day) { day = d; box.append(el("div", "day", new Date(d + "T00:00").toDateString())); }
    const b = el("div", "bubble " + (m.role === "user" ? "you" : "noob"), m.text.replace(/^\[[a-z-]+\]\s*/i, ""));
    b.append(el("small", "", m.time.slice(11)));
    box.append(b);
  });
  box.scrollTop = box.scrollHeight;
}
loaders.history = async () => { chatLog = await api("/api/conversation"); renderHistory(); };
$("historySearch").oninput = renderHistory;
$("clearHistory").onclick = async () => {
  if (await modal({ title: "Clear all conversations?", text: "Your About Me details and NOOB's memory are kept.", ok: "Clear", danger: true })) {
    await api("/api/conversation", { method: "DELETE" });
    toast("Conversations cleared");
    loaders.history();
  }
};

// ---------------------------------------------------------------- DEVICES
function deviceItem(d, actionText, action, badge) {
  const item = el("div", "item");
  const icon = el("div", "icon-circle");
  icon.innerHTML = ICONS.device;
  const grow = el("div", "grow");
  grow.append(el("div", "title", d.name || "NOOB device"),
              el("div", "meta", [d.ip, d.paired_at ? `paired ${d.paired_at}` : d.version ? `firmware ${d.version}` : ""].filter(Boolean).join(" · ")));
  item.append(icon, grow);
  if (badge) item.append(el("span", "badge" + (badge.ok ? " ok" : badge.off ? " off" : ""), badge.text));
  if (actionText) {
    const b = el("button", "btn " + (actionText === "Forget" ? "ghost danger" : "primary"), actionText);
    b.onclick = () => action(b);
    item.append(b);
  }
  return item;
}

loaders.devices = async () => {
  const mine = await api("/api/devices");
  const list = $("myDevices");
  list.replaceChildren();
  if (!mine.length) list.append(el("div", "empty", "No devices yet. Press “Scan now” to find your NOOB."));
  mine.forEach((d) => list.append(deviceItem(d, "Forget", async () => {
    if (await modal({ title: `Forget ${d.name}?`, text: "The device will need to be connected again.", ok: "Forget", danger: true })) {
      await api(`/api/devices/${encodeURIComponent(d.mac)}`, { method: "DELETE" });
      toast("Device removed");
      loaders.devices();
    }
  }, d.online ? { text: "● Online", ok: true } : { text: "● Offline", off: true })));
  clearTimeout(devicesTimer);
  if (location.hash === "#devices") devicesTimer = setTimeout(loaders.devices, 5000);   // live status
};
let devicesTimer = 0;

$("scanBtn").onclick = async () => {
  $("scanBtn").disabled = true;
  $("radar").classList.add("scanning");
  $("scanTitle").textContent = "Scanning…";
  const list = $("foundList");
  try {
    const found = await api("/api/devices/scan", { method: "POST" });
    list.replaceChildren();
    $("foundTitle").hidden = false;
    $("scanTitle").textContent = found.length ? `Found ${found.length} NOOB device${found.length > 1 ? "s" : ""}` : "No NOOB devices found";
    if (!found.length) list.append(el("div", "empty", "Nothing found. Check that NOOB is switched on, shows “Ready” or “Not paired”, and uses the same Wi-Fi."));
    found.forEach((d) => list.append(deviceItem(d, d.mine ? "" : "Connect", (btn) => pairDevice(d, btn),
      d.mine ? { text: "Yours", ok: true } : { text: d.other_account ? "Another account" : d.paired ? "Paired to another PC" : "New" })));
  } catch {
    toast("Scan failed", true);
  }
  $("radar").classList.remove("scanning");
  $("scanBtn").disabled = false;
};

async function pairDevice(d, btn) {
  btn.disabled = true;
  const started = await api("/api/devices/pair/start", { method: "POST", json: { ip: d.ip } }).catch(() => ({ ok: false }));
  btn.disabled = false;
  if (!started.ok) { toast("The device did not answer. Try scanning again.", true); return; }
  const box = el("div", "code-inputs");
  const inputs = [0, 1, 2, 3].map(() => {
    const i = el("input");
    i.inputMode = "numeric";
    i.maxLength = 1;
    i.oninput = () => { i.value = i.value.replace(/\D/g, ""); if (i.value && i.nextSibling) i.nextSibling.focus(); };
    i.onkeydown = (e) => { if (e.key === "Backspace" && !i.value && i.previousSibling) i.previousSibling.focus(); };
    return i;
  });
  box.append(...inputs);
  if (!(await modal({ title: `Connect ${d.name}`, text: "Look at NOOB's screen and enter the 4-digit code it shows.", body: box, ok: "Connect" }))) return;
  const code = inputs.map((i) => i.value).join("");
  const r = await api("/api/devices/pair", { method: "POST", json: { ip: d.ip, code } });
  if (r.ok) { toast(`Connected to ${r.name}! 🎉`); $("scanBtn").click(); loaders.devices(); }
  else toast(r.error, true);
}

// ---------------------------------------------------------------- SETTINGS
let logTimer = 0;
loaders.settings = async () => {
  await refreshStatus();
  const status = serverStatus;
  if (!status) return;
  $("accountInfo").replaceChildren(...[["Name", status.user.name], ["Username", status.user.username],
    ["Role", status.user.is_owner ? "Owner" : "Member"]].flatMap(([k, v]) => [el("dt", "", k), el("dd", "", v)]));
  const linked = status.user.noob_username;
  $("noobLinkText").textContent = linked ? `NOOB account: @${linked} — you can use “Continue with NOOB”` : "NOOB account: not linked";
  $("linkNoob").hidden = Boolean(linked);
  if (!status.user.is_owner) return;
  const s = await api("/api/settings");
  $("geminiKey").value = "";
  $("geminiKey").placeholder = s.gemini_key_set ? `Saved (${s.gemini_key_hint}) — paste a new key to replace` : "Paste your key";
  $("inviteCode").textContent = s.invite_code;
  renderUsers(s.users);
  if (status) {
    $("brainStatus").textContent = status.gemini ? `Using Google Gemini (${status.gemini_model}) — free tier.`
      : "No Gemini key yet — NOOB uses the offline brain (Ollama) if it is installed.";
    const info = [["Status", "Running"], ["Address for devices", status.server_url], ["Speech model", `Whisper ${status.whisper}`],
      ["Voice languages", status.languages], ["Memories", status.facts], ["Messages", status.messages], ["Version", status.version]];
    $("serverInfo").replaceChildren(...info.flatMap(([k, v]) => [el("dt", "", k), el("dd", "", String(v))]));
  }
  const refreshLog = async () => {
    if (location.hash !== "#settings") { clearInterval(logTimer); return; }
    try {
      const lines = await api("/api/log");
      const box = $("log");
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      box.textContent = lines.join("\n");
      if (atBottom) box.scrollTop = box.scrollHeight;
    } catch { /* offline */ }
  };
  clearInterval(logTimer);
  refreshLog();
  logTimer = setInterval(refreshLog, 2000);
};
function renderUsers(users) {
  $("userList").replaceChildren(...users.map((u) => {
    const item = el("div", "item");
    const avatar = el("div", "icon-circle", (u.name.trim()[0] || "?").toUpperCase());
    const grow = el("div", "grow");
    grow.append(el("div", "title", u.name), el("div", "meta", `@${u.username} · joined ${u.created_at}`));
    item.append(avatar, grow);
    if (u.is_owner) item.append(el("span", "badge ok", "Owner"));
    else item.append(iconButton("del", "Remove account", async () => {
      if (await modal({ title: `Remove ${u.name}?`, text: "Their account, memory and conversations will be deleted.", ok: "Remove", danger: true })) {
        await api(`/api/users/${u.id}`, { method: "DELETE" });
        toast("Account removed");
        loaders.settings();
      }
    }, "del"));
    return item;
  }));
}
$("copyInvite").onclick = () => navigator.clipboard.writeText($("inviteCode").textContent).then(() => toast("Invite code copied"));
$("newInvite").onclick = async () => {
  if (await modal({ title: "Make a new invite code?", text: "The old code stops working. People who already have accounts are not affected.", ok: "New code" })) {
    $("inviteCode").textContent = (await api("/api/settings/invite", { method: "POST" })).invite_code;
    toast("New invite code ready");
  }
};
$("changePw").onclick = async () => {
  try {
    await api("/api/auth/password", { method: "POST", json: { old: $("oldPw").value, new: $("newPw").value } });
    $("oldPw").value = $("newPw").value = "";
    toast("Password changed");
  } catch (e) { toast(e.message, true); }
};
$("linkNoob").onclick = async () => {
  const box = el("div");
  const id = el("input"); id.placeholder = "NOOB username or email"; id.autocomplete = "username";
  const pw = el("input"); pw.type = "password"; pw.placeholder = "NOOB password"; pw.autocomplete = "current-password";
  pw.style.marginTop = "10px";
  box.append(id, pw, el("p", "muted small", "🔒 Your NOOB password is only checked with NOOB and is never saved here."));
  if (!(await modal({ title: "Link your NOOB account", text: "Then you can sign in here with “Continue with NOOB”.", body: box, ok: "Link" }))) return;
  try {
    const r = await api("/api/auth/noob/link", { method: "POST", json: { identifier: id.value.trim(), password: pw.value } });
    toast(`Linked to @${r.noob_username}`);
    loaders.settings();
  } catch (e) { toast(e.message, true); }
};
async function signOut() {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  location.href = "/login";
}
$("signOut").onclick = signOut;
$("signOut2").onclick = signOut;

$("saveKey").onclick = async () => {
  const key = $("geminiKey").value.trim();
  if (!key) { toast("Paste your key first", true); return; }
  await api("/api/settings", { method: "PUT", json: { gemini_api_key: key } });
  toast("Key saved — NOOB now uses Gemini");
  loaders.settings();
};
$("stopServer").onclick = async () => {
  if (await modal({ title: "Stop NOOB?", text: "NOOB will stop answering until you open NOOB App.bat again.", ok: "Stop", danger: true })) {
    await api("/api/shutdown", { method: "POST" }).catch(() => {});
    setTimeout(refreshStatus, 1200);
  }
};

// ---------------------------------------------------------------- start
buildProfileForm();
refreshStatus().then(showPage);
