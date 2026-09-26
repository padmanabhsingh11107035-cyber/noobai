/* NOOB App - talks to the NOOB server on this PC (same address this page came from). */
"use strict";

const $ = (id) => document.getElementById(id);
const PROFILE_FIELDS = [
  ["Name", 1], ["Age", 1], ["Gender", 1], ["Pronouns", 1], ["Birthday", 1], ["City", 1],
  ["Phone", 1], ["Email", 1], ["Preferred language", 1], ["Blood group", 1], ["Height and weight", 1], ["Allergies", 1],
  ["Medical conditions", 2], ["Current medicines", 2],
  ["Doctor name and phone", 1], ["Emergency contact", 1], ["Hobbies and interests", 1], ["Website", 1],
  ["NOOB username", 1], ["Business", 1], ["About me", 3],
];

// ---------------------------------------------------------------- helpers
async function api(path, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers["Content-Type"] = "application/json";
    delete opts.json;
  }
  let timer = 0;
  if (opts.timeout) {
    const controller = new AbortController();
    opts.signal = controller.signal;
    timer = setTimeout(() => controller.abort(), opts.timeout);
    delete opts.timeout;
  }
  let res;
  try { res = await fetch(path, opts); } finally { clearTimeout(timer); }
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
  let valid = document.getElementById("page-" + page) ? page : "talk";
  if (valid === "settings" && !(serverStatus && serverStatus.user.is_owner)) valid = "talk";   // owner only
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
    showFreeNote(serverStatus.questions_left);
    $("maintenance").hidden = !serverStatus.maintenance;                      // locked by the NOOB admin
    $("lockNote").hidden = !(serverStatus.locked_for_others && !serverStatus.maintenance);
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

// People without a NOOB account get a few free questions; this shows how many are left.
function showFreeNote(left) {
  const note = $("freeNote");
  if (left === null || left === undefined) { note.hidden = true; return; }
  note.hidden = false;
  note.className = "free-note" + (left === 0 ? " out" : "");
  note.replaceChildren(el("span", "", left === 0 ? "You've used your free questions. "
    : `Free trial: ${left} question${left === 1 ? "" : "s"} left. `));
  const link = el("a", "", "Link your NOOB account for unlimited");
  link.href = "#about";
  note.append(link);
}

// ---------------------------------------------------------------- SURVEY
let surveyStars = 0;
function showSurvey() {
  surveyStars = 0;
  $("surveyComment").value = "";
  $("surveySend").disabled = true;
  paintStars(0);
  $("survey").hidden = false;
}
function paintStars(n) {
  $("stars").querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number(b.dataset.star) <= n));
}
$("stars").querySelectorAll("button").forEach((b) => {
  b.onclick = () => { surveyStars = Number(b.dataset.star); paintStars(surveyStars); $("surveySend").disabled = false; };
  b.onmouseenter = () => paintStars(Number(b.dataset.star));
  b.onmouseleave = () => paintStars(surveyStars);
});
$("surveyLater").onclick = () => { $("survey").hidden = true; };
$("surveySend").onclick = async () => {
  try {
    await api("/api/review", { method: "POST", json: { stars: surveyStars, comment: $("surveyComment").value.trim() } });
    $("survey").hidden = true;
    toast(surveyStars >= 4 ? "Thank you! 💜" : "Thank you — we'll make NOOB better");
  } catch (e) { toast(e.message, true); }
};

// ---------------------------------------------------------------- MUSIC
// Songs play in YouTube's own player (youtube-nocookie.com), shown on the Talk page. NOOB finds them on the PC
// ("PLAY: ..." in its answer) and sends a few matches; if one can't be played outside YouTube, the next one is tried.
const ICON_PAUSE = '<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6V5Zm8 0h4v14h-4V5Z"/></svg>';
const ICON_PLAY = '<svg viewBox="0 0 24 24"><path d="M7 5v14l12-7L7 5Z"/></svg>';
const music = { player: null, api: null, results: [], index: 0, playing: false, resumeAfterTalk: false, timer: 0 };

function youtubeApi() {
  if (!music.api) {
    music.api = new Promise((resolve, reject) => {
      window.onYouTubeIframeAPIReady = resolve;
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.onerror = () => { music.api = null; reject(new Error("YouTube could not be reached")); };
      document.head.append(script);
    });
  }
  return music.api;
}

function paintMusic() {
  $("musicToggle").innerHTML = music.playing ? ICON_PAUSE : ICON_PLAY;            // fixed, trusted SVG only
  $("musicToggle").title = $("musicToggle").ariaLabel = music.playing ? "Pause" : "Play";
  $("musicCard").classList.toggle("playing", music.playing);
}

async function playSongs(results) {
  music.results = results || [];
  music.index = 0;
  await loadSong();
}

async function loadSong() {
  const song = music.results[music.index];
  if (!song) { stopMusic(); toast("Sorry, that song can't be played here. Try asking for another one.", true); return; }
  $("musicCard").hidden = false;
  $("musicTitle").textContent = song.title;
  $("musicSub").textContent = song.channel ? `${song.channel} · YouTube` : "YouTube";
  $("musicHint").hidden = true;
  try { await youtubeApi(); } catch (e) { toast(e.message, true); return; }
  if (!music.player) {
    music.player = new YT.Player("ytPlayer", {
      host: "https://www.youtube-nocookie.com",
      videoId: song.id, width: "100%", height: "100%",
      playerVars: { autoplay: 1, playsinline: 1, rel: 0 },
      events: {
        onReady: (e) => { e.target.setVolume(100); e.target.playVideo(); },
        onStateChange: (e) => {
          music.playing = e.data === YT.PlayerState.PLAYING;
          if (music.playing) $("musicHint").hidden = true;
          paintMusic();
        },
        onError: () => { music.index++; loadSong(); },          // not allowed outside YouTube: try the next match
      },
    });
  } else {
    music.player.setVolume(100);
    music.player.loadVideoById(song.id);
  }
  paintMusic();
  clearTimeout(music.timer);                                   // phones may need one tap on the video to start
  music.timer = setTimeout(() => { if (!music.playing) $("musicHint").hidden = false; }, 4000);
}

function stopMusic() {
  clearTimeout(music.timer);
  if (music.player && music.player.stopVideo) music.player.stopVideo();
  music.playing = music.resumeAfterTalk = false;
  music.results = [];
  $("musicCard").hidden = true;
}

// After NOOB's answer: start, stop, pause or continue the music. Returns true when music is now playing.
function afterAnswer(action) {
  const resume = music.resumeAfterTalk;
  music.resumeAfterTalk = false;
  if (music.player && music.player.setVolume) music.player.setVolume(100);
  if (action && action.action === "play") { playSongs(action.results); return true; }
  if (action && action.action === "stop") { stopMusic(); return false; }
  if (action && action.action === "pause") { if (music.player) music.player.pauseVideo(); return false; }
  if (action && action.action === "next") { music.index++; loadSong(); return true; }
  if (music.player && music.results.length && (resume || (action && action.action === "resume"))) {
    music.player.playVideo();
    return true;
  }
  return music.playing;
}

$("musicToggle").onclick = () => {
  if (!music.player) return;
  if (music.playing) music.player.pauseVideo(); else music.player.playVideo();
};
$("musicNext").onclick = () => { music.index++; loadSong(); };
$("musicStop").onclick = stopMusic;
paintMusic();

// ---------------------------------------------------------------- TALK
const orb = $("orb");
let state = "idle";                 // idle / listening / thinking / speaking
let audioCtx = null, recorder = null, rafId = 0;

// One audio player for NOOB's voice. Phones (iPhone especially) only play sound that starts from a tap,
// so the first tap "unlocks" this player with a moment of silence, and every answer reuses it.
const player = new Audio();
player.setAttribute("playsinline", "");
let playerUnlocked = false;
const SILENCE = (() => {
  const n = 1600, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true); v.setUint32(28, 32000, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
})();

function unlockAudio() {                     // call from every tap
  if (audioCtx && audioCtx.state !== "running") audioCtx.resume().catch(() => {});
  if (playerUnlocked) return;
  playerUnlocked = true;
  player.src = SILENCE;
  player.play().catch(() => { playerUnlocked = false; });
}

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

async function startListening() {
  if (state !== "idle") return;
  if (music.playing) { music.player.pauseVideo(); music.resumeAfterTalk = true; }   // quiet while you talk
  if (!window.isSecureContext || !navigator.mediaDevices || !window.MediaRecorder) {
    toast("Voice needs a secure (https://) page and a modern browser. You can type your message instead.", true);
    return;
  }
  let micStream;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch {
    toast("Microphone blocked. Allow the microphone for this site and try again.", true);
    return;
  }
  // The level meter (for "stop when you stop talking") is a bonus: if the phone does not allow it,
  // recording still works and you tap to stop.
  let analyser = null;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state !== "running") await audioCtx.resume().catch(() => {});
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    audioCtx.createMediaStreamSource(micStream).connect(analyser);
  } catch { analyser = null; }

  const type = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"]
    .find((t) => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t));
  const rec = new MediaRecorder(micStream, type ? { mimeType: type } : undefined);
  recorder = rec;
  const chunks = [];
  rec.ondataavailable = (e) => e.data && e.data.size && chunks.push(e.data);
  rec.onstop = () => {
    cancelAnimationFrame(rafId);
    micStream.getTracks().forEach((t) => t.stop());
    if (rec.cancelled) { setState("idle"); return; }
    sendVoice(new Blob(chunks, { type: rec.mimeType || type || "audio/webm" }));
  };
  rec.start();
  setState("listening");

  const samples = analyser ? new Float32Array(analyser.fftSize) : null;
  const started = performance.now();
  let noise = 0.01, heardSpeech = false, lastLoud = started;
  const tick = () => {
    const now = performance.now(), total = now - started;
    const metering = analyser && audioCtx.state === "running";
    if (metering) {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += s * s;
      const level = Math.sqrt(sum / samples.length);
      if (total < 350) noise = Math.max(noise, level);              // measure room noise first
      if (level > Math.max(0.02, noise * 2.2)) { heardSpeech = true; lastLoud = now; }
      orb.style.setProperty("--level", Math.min(1, level * 6).toFixed(3));
      if (heardSpeech && now - lastLoud > 1300) return stopListening();          // you stopped talking
      if (!heardSpeech && total > 8000) { rec.cancelled = true; toast("I didn't hear anything."); return stopListening(); }
    }
    if (total > 20000) return stopListening();                                    // never record forever
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}

function stopListening() {
  if (recorder && recorder.state === "recording") recorder.stop();
}

async function sendVoice(blob) {
  await streamAnswer("/api/voice", { method: "POST", body: blob, headers: { "Content-Type": blob.type } }, true);
}

async function sendText(text) {
  if (!text.trim() || state === "thinking") return;
  stopSpeaking();
  addBubble("you", text);
  await streamAnswer("/api/chat", { method: "POST", body: JSON.stringify({ text }),
    headers: { "Content-Type": "application/json" } }, false);
}

// Plays one clip on the unlocked player. Resolves true when it played (or was skipped), false if the phone blocked it.
function playClip(url) {
  return new Promise((resolve) => {
    let done = false, guard = 0;
    const finish = (ok) => {
      if (done) return;
      done = true;
      clearTimeout(guard);
      player.onended = player.onerror = null;
      resolve(ok);
    };
    player.onended = () => finish(true);
    player.onerror = () => finish(true);                 // skip a broken clip
    player.src = url;
    player.play().then(() => {
      const seconds = Number.isFinite(player.duration) && player.duration > 0 ? player.duration : 30;
      guard = setTimeout(() => finish(true), seconds * 1000 + 3000);     // never get stuck
    }).catch(() => finish(false));
  });
}

let currentReply = null;                                  // the answer being spoken (so a tap can stop it)
function stopSpeaking() {
  if (currentReply) currentReply.cancel();
}

// Asks NOOB and handles the streamed answer: what NOOB heard, the text as it is written, and each
// sentence's voice as soon as it is ready (so NOOB starts speaking before the whole answer exists).
async function streamAnswer(path, request, fromVoice) {
  setState("thinking");
  const typing = typingBubble();
  let bubble = null, ok = false, blocked = false, streamDone = false, playing = false, cancelled = false, wantSurvey = false;
  let musicAction = null;
  if (music.playing) music.player.setVolume(20);                       // NOOB's voice over the music
  const queue = [], clips = [];
  let allPlayed;
  const finished = new Promise((resolve) => (allPlayed = resolve));
  const reply = {
    cancel() { cancelled = true; queue.length = 0; player.pause(); allPlayed(); },
  };
  currentReply = reply;

  const playNext = () => {
    if (playing || cancelled) return;
    if (!queue.length) { if (streamDone) allPlayed(); return; }
    playing = true;
    setState("speaking");
    playClip(queue.shift()).then((played) => {
      playing = false;
      if (!played) { blocked = true; queue.length = 0; }
      playNext();
    });
  };
  const caption = $("caption"), captionHeard = $("captionHeard"), captionAnswer = $("captionAnswer");
  caption.hidden = true;
  captionHeard.textContent = captionAnswer.textContent = "";
  const noobBubble = () => {
    if (!bubble) { typing.remove(); bubble = addBubble("noob", ""); }
    return bubble;
  };
  const handle = (ev) => {
    if (ev.type === "heard") {
      if (ev.text) {
        $("chat").insertBefore(el("div", "bubble you", ev.text), typing);
        captionHeard.textContent = `“${ev.text}”`;
        caption.hidden = false;
      }
    } else if (ev.type === "text") {
      const b = noobBubble();
      b.textContent += (b.textContent ? " " : "") + ev.text;
      $("chat").scrollTop = $("chat").scrollHeight;
      captionAnswer.textContent = b.textContent;
      caption.hidden = false;
    } else if (ev.type === "audio") {
      const bytes = Uint8Array.from(atob(ev.data), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: ev.mime || "audio/mpeg" }));
      clips.push(url);
      if (!blocked && !cancelled) { queue.push(url); playNext(); }
    } else if (ev.type === "done") {
      ok = ev.ok;
      if ("questions_left" in ev) showFreeNote(ev.questions_left);
      if (ev.maintenance) refreshStatus();
      if (ev.music) musicAction = ev.music;
      if (ev.survey) wantSurvey = true;
      const b = noobBubble();
      if (!b.textContent) b.textContent = ev.answer;
      if (!ev.ok) b.classList.add("error");
      captionAnswer.textContent = b.textContent;
      caption.hidden = false;
    }
  };

  const controller = new AbortController();
  let silence = setTimeout(() => controller.abort(), 60000);            // nothing for 60 s: give up
  try {
    const res = await fetch(path, { ...request, signal: controller.signal });
    if (res.status === 401) { location.href = "/login"; return; }
    if (!res.ok || !res.body) throw new Error(`Server error ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      clearTimeout(silence);
      silence = setTimeout(() => controller.abort(), 60000);
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (line) handle(JSON.parse(line));
      }
    }
  } catch (e) {
    typing.remove();
    const b = noobBubble();
    if (!b.textContent) {
      b.textContent = e.name === "AbortError" ? "NOOB took too long to answer. Please try again." : "Could not reach NOOB AI. Please try again.";
      b.classList.add("error");
    }
  } finally {
    clearTimeout(silence);
    typing.remove();
  }
  streamDone = true;
  if (!playing && !queue.length) allPlayed();
  await finished;
  if (blocked && clips.length && bubble) {                               // the phone blocked sound: offer a button
    const play = el("button", "chip play-voice", "🔊 Play NOOB's voice");
    play.onclick = async () => { for (const url of clips) await playClip(url); };
    bubble.append(el("br"), play);
  }
  if (currentReply === reply) currentReply = null;
  setState("idle");
  const musicOn = afterAnswer(musicAction);
  if (wantSurvey) { $("convMode").checked = false; setTimeout(showSurvey, 600); return; }
  if (fromVoice && ok && !blocked && !cancelled && !musicOn && $("convMode").checked) setTimeout(startListening, 400);  // keep talking
}

$("orbBtn").onclick = () => {
  unlockAudio();
  if (state === "idle") startListening();
  else if (state === "listening") stopListening();
  else if (state === "speaking") { $("convMode").checked = false; stopSpeaking(); }
};
$("composer").onsubmit = (e) => { e.preventDefault(); unlockAudio(); const t = $("typeBox").value; $("typeBox").value = ""; sendText(t); };
document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { unlockAudio(); sendText(c.textContent); }));
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
  loadAccount();
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
loaders.memory = async () => {
  facts = await api("/api/facts");
  renderFacts();
  renderMoods(await api("/api/moods"));
};

const MOOD_FACES = ["", "😢", "🙁", "😐", "🙂", "😄"];
function renderMoods(moods) {
  const strip = $("moodStrip");
  strip.replaceChildren();
  if (!moods.length) {
    strip.append(el("div", "empty", "Nothing yet. Just talk to NOOB — it will notice how you feel."));
    $("moodSummary").textContent = "";
    return;
  }
  moods.slice(-30).forEach((m) => {
    const dot = el("div", `mood m${m.score}`);
    dot.append(el("span", "face", MOOD_FACES[m.score] || "🙂"), el("span", "word", m.mood), el("small", "", m.at.slice(5, 16)));
    dot.title = `${m.at} — ${m.mood} (${m.score}/5)`;
    strip.append(dot);
  });
  strip.scrollLeft = strip.scrollWidth;
  const recent = moods.slice(-7);
  const avg = recent.reduce((t, m) => t + m.score, 0) / recent.length;
  $("moodSummary").textContent = avg >= 3.8 ? "Lately you've mostly seemed happy. Keep it up! 🌟"
    : avg >= 2.8 ? "Lately you've seemed mostly okay."
    : "Lately you've seemed low or stressed. NOOB is here to talk any time — and if it lasts, please talk to someone you trust or call Tele MANAS on 14416 (free).";
}
$("clearMoods").onclick = async () => {
  if (await modal({ title: "Clear your mood history?", text: "NOOB will forget how you've been feeling so far.", ok: "Clear", danger: true })) {
    await api("/api/moods", { method: "DELETE" });
    toast("Mood history cleared");
    loaders.memory();
  }
};
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
async function loadAccount() {                       // "My account" card on the About Me page
  await refreshStatus();
  const status = serverStatus;
  if (!status) return;
  $("accountInfo").replaceChildren(...[["Name", status.user.name], ["Username", status.user.username],
    ["Role", status.user.is_owner ? "Owner" : "Member"]].flatMap(([k, v]) => [el("dt", "", k), el("dd", "", v)]));
  const linked = status.user.noob_username;
  $("noobLinkText").textContent = linked ? `NOOB account: @${linked} — you can use “Continue with NOOB”` : "NOOB account: not linked";
  $("linkNoob").hidden = Boolean(linked);
}

loaders.settings = async () => {
  await refreshStatus();
  const status = serverStatus;
  if (!status || !status.user.is_owner) { location.hash = "#talk"; return; }
  const s = await api("/api/settings");
  $("geminiKey").value = "";
  $("geminiKey").placeholder = s.gemini_key_set ? `Saved (${s.gemini_key_hint}) — paste a new key to replace` : "Paste your key";
  $("inviteCode").textContent = s.invite_code;
  $("openToNoob").checked = s.open_to_noob_users;
  renderUsers(s.users);
  renderRatings(s.reviews);
  if (status) {
    $("brainStatus").textContent = status.gemini ? `Using Google Gemini (${status.gemini_model}) — free tier.`
      : "No Gemini key yet — NOOB uses the offline brain (Ollama) if it is installed.";
    const info = [["Status", "Running"], ["Online address", status.online_url || "not set up (see README)"],
      ["Address for devices", status.server_url], ["Speech model", `Whisper ${status.whisper}`],
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
function renderRatings(r) {
  if (!r || !r.count) { $("ratingSummary").textContent = "No ratings yet."; $("ratingList").replaceChildren(); return; }
  $("ratingSummary").textContent = `★ ${r.average} out of 5 · ${r.count} rating${r.count === 1 ? "" : "s"}`;
  $("ratingList").replaceChildren(...r.latest.map((x) => {
    const item = el("div", "item");
    const grow = el("div", "grow");
    grow.append(el("div", "title", "★".repeat(x.stars) + "☆".repeat(5 - x.stars) + "  " + x.name),
      el("div", "meta", (x.comment ? `“${x.comment}” · ` : "") + x.at));
    item.append(grow);
    return item;
  }));
}
function renderUsers(users) {
  $("userList").replaceChildren(...users.map((u) => {
    const item = el("div", "item");
    const avatar = el("div", "icon-circle", (u.name.trim()[0] || "?").toUpperCase());
    const grow = el("div", "grow");
    grow.append(el("div", "title", u.name), el("div", "meta", `@${u.username} · joined ${u.created_at}` +
      ` · ${u.questions || 0} question${u.questions === 1 ? "" : "s"}` + (u.noob_username ? ` · NOOB @${u.noob_username}` : "")));
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
$("openToNoob").onchange = async () => {
  await api("/api/settings", { method: "PUT", json: { open_to_noob_users: $("openToNoob").checked } });
  toast($("openToNoob").checked ? "Everyone with a NOOB account can use NOOB AI" : "New people now need the invite code");
};
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
    loadAccount();
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
