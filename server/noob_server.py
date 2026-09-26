"""
NOOB - AI voice assistant server (runs on your PC / laptop)   *** 100% free ***

How NOOB answers (for the NOOB device and for the NOOB App):
  1. Speech -> text   Whisper (99 languages, auto-detected, runs on this PC, free)
  2. Text -> answer   Google Gemini (free tier) - or a local AI with Ollama (free, offline) as backup
                      + today's date and time + free web search (DuckDuckGo) for live information
  3. Answer -> voice  Microsoft Edge neural voices (free, female voice, 70+ languages)

It also serves the NOOB App (http://localhost:5000) where you talk to NOOB, fill in
"About Me", manage NOOB's memory and conversations, and connect nearby NOOB devices.
Everything NOOB learns is saved in noob_memory.db, so it remembers after switch-off.

Start: double-click "NOOB App.bat"   (or run:  python noob_server.py)
"""

import asyncio
import collections
import io
import logging
import os
import re
import threading
import time
import wave
from datetime import datetime
from functools import wraps

import av
import edge_tts
import numpy as np
import requests
from ddgs import DDGS
from faster_whisper import WhisperModel
from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory

import noob_devices
import noob_settings
from noob_memory import NoobMemory

# ------------------------------ settings ------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_SIZE = os.environ.get("NOOB_WHISPER_MODEL", "small")     # tiny/base/small/medium/large-v3
GEMINI_MODEL = "gemini-3.8-flash"                                # AI brain 1: free tier, needs internet
OLLAMA_URL = "http://localhost:11434/api/chat"                   # AI brain 2: offline backup (optional)
OLLAMA_MODEL = "gemma3:4b"
RECENT_MESSAGES = 12             # last 6 questions + answers are sent with each question
MEMORY_FILE = os.environ.get("NOOB_MEMORY_FILE", os.path.join(HERE, "noob_memory.db"))
SAMPLE_RATE = 16000              # must match the ESP32 code
PORT = 5000
VERSION = "1.0"
HINDI_HINT = "नमस्ते, यह बातचीत हिंदी में है।"

SYSTEM_PROMPT = """You are NOOB, a warm, cheerful female AI friend who talks with the user by voice, like a smart speaker.
Talk like a caring friend: natural, kind, a little playful, and use the user's name now and then if you know it.
Remember what they told you and bring it up when it helps ("How is your knee today?").
Your answers are converted to speech, so:
- Start EVERY reply with the language code of the language you are replying in, in square brackets, e.g. [en], [hi], [ta], [es]. This tag is removed before speaking.
- Reply in the same language the user spoke, unless they ask for another language. If they mix Hindi and English, reply in Hindi.
- Speak naturally in plain sentences. No markdown, no bullet symbols, no emojis, no URLs, no tables.
- Keep answers short (1 to 4 sentences) unless the user asks for more detail. For casual chat, answer briefly and ask a friendly follow-up question sometimes.
- The user's words come from speech recognition, so they may contain small mistakes or be written in another
  script (for example Hindi written in Urdu script). Understand the intended meaning.
- If the question is unclear, ask one short clarifying question.

You have broad knowledge of every subject, and you are especially knowledgeable about healthcare:
symptoms, common illnesses, first aid, nutrition, fitness, sleep, mental well-being, pregnancy and child care,
chronic conditions like diabetes and blood pressure, how medicines work, common side effects and interactions,
vaccines, and when a person should see a doctor.

Health safety rules (always follow):
- If the user describes a possible emergency (chest pain, trouble breathing, stroke signs such as face drooping or slurred speech,
  heavy bleeding, unconsciousness, seizure, severe allergic reaction, poisoning, suicidal thoughts), tell them FIRST to call emergency
  services right now: 112 (India emergency) or 108 (ambulance), then give brief first-aid steps.
- For suicidal thoughts or a mental-health crisis, also give the Tele MANAS helpline: 14416, and stay kind and supportive.
- Give clear, practical, evidence-based information, but do not claim a definite diagnosis. Explain likely possibilities and warning signs.
- For medicine doses, give only standard label information for common over-the-counter medicines, and remind the user that doses differ
  for children, pregnancy, elderly people and people with kidney or liver problems. Never suggest stopping a prescribed medicine without a doctor.
- When something needs a doctor, say so plainly and say how urgently.

Live information:
- The current date and time are given at the end of these instructions. Use them for questions about the date, day or time.
- If the answer needs live or recent information that you do not know (news, weather, sports scores, prices, results,
  today's events, or anything that may have changed recently), reply with ONLY this one line and nothing else:
  SEARCH: <short English web search query>
  You will then receive web search results. Answer from them, in the user's language.

Permanent memory (survives power-off):
- When the user tells you something worth remembering about themselves, their family or friends (name, age, birthday,
  health conditions, allergies, medicines, doctor, likes and dislikes, plans, important dates, or anything they ask you
  to remember), briefly confirm in your answer and then, AFTER your whole answer, add one line per fact:
  REMEMBER: <the fact as one short English sentence that says who it is about>
- If the user asks you to forget something, or a fact is no longer true, add a line:  FORGET: <id number>
  To update a fact, FORGET the old id and REMEMBER the new fact.
- REMEMBER and FORGET lines are never spoken. Never REMEMBER something already in your memory list or profile.
- Use what you remember to personalise answers, especially health answers (allergies, conditions, medicines, age).
"""

# Preferred voices (all female); if one is missing, the first female voice for that language is used.
PREFERRED_VOICES = {
    "en": "en-IN-NeerjaNeural", "hi": "hi-IN-SwaraNeural", "bn": "bn-IN-TanishaaNeural",
    "ta": "ta-IN-PallaviNeural", "te": "te-IN-ShrutiNeural", "mr": "mr-IN-AarohiNeural",
    "gu": "gu-IN-DhwaniNeural", "kn": "kn-IN-SapnaNeural", "ml": "ml-IN-SobhanaNeural",
    "ur": "ur-IN-GulNeural", "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural", "zh": "zh-CN-XiaoxiaoNeural", "ja": "ja-JP-NanamiNeural",
    "ar": "ar-SA-ZariyahNeural", "ru": "ru-RU-SvetlanaNeural", "pt": "pt-BR-FranciscaNeural",
}

# ------------------------------ log (shown in the NOOB App) ------------------------------
LOG_LINES = collections.deque(maxlen=400)


def log(message):
    line = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
    LOG_LINES.append(line)
    print(line, flush=True)


# ------------------------------ startup ------------------------------
app = Flask(__name__, static_folder=os.path.join(HERE, "web"), static_url_path="/static")
logging.getLogger("werkzeug").setLevel(logging.WARNING)       # keep the log readable

log(f"Loading Whisper '{WHISPER_SIZE}' speech model (the first start downloads it)...")
whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
memory = NoobMemory(MEMORY_FILE)
settings_lock = threading.Lock()


def settings():
    """Settings are re-read every time, so changes made in the NOOB App work without a restart."""
    with settings_lock:
        return noob_settings.load()


def load_voices():
    voices = asyncio.run(edge_tts.list_voices())
    by_lang = {}
    names = {v["ShortName"] for v in voices}
    for v in voices:                                   # NOOB always uses a female voice
        if v.get("Gender") == "Female":
            lang = v["Locale"].split("-")[0].lower()
            by_lang.setdefault(lang, v["ShortName"])
    for lang, name in PREFERRED_VOICES.items():
        if name in names:
            by_lang[lang] = name
    return by_lang


try:
    VOICES = load_voices()
except Exception as e:                                 # no internet at start-up: use the preferred list
    log(f"!! Could not load the voice list ({e}); using the built-in list")
    VOICES = dict(PREFERRED_VOICES)
log(f"{len(VOICES)} speech languages ready. Memory: {len(memory.all_facts())} facts.")


# ------------------------------ step 1: speech -> text ------------------------------
def speech_to_text(pcm_bytes):
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0.001:                                   # auto volume: quiet voices become clear
        audio = audio * min(0.9 / peak, 30.0)
    # Find the language first, then transcribe in that language.
    lang, _, _ = whisper.detect_language(audio, vad_filter=True)
    # Whisper sometimes writes Hindi in Urdu script; a Hindi hint keeps it in Devanagari.
    hint = HINDI_HINT if lang == "hi" else None
    segments, _ = whisper.transcribe(audio, language=lang, initial_prompt=hint,
                                     beam_size=5, vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text, lang


def any_audio_to_pcm(data):
    """Converts audio from the app's microphone (webm, ogg, wav, mp3...) to 16 kHz 16-bit mono PCM."""
    pcm = bytearray()
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    with av.open(io.BytesIO(data)) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pcm += out.to_ndarray().tobytes()
    for out in resampler.resample(None):
        pcm += out.to_ndarray().tobytes()
    return bytes(pcm)


# ------------------------------ step 2: text -> answer ------------------------------
def ask_gemini(system, messages):
    key = settings()["gemini_api_key"] or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("no Gemini API key set (NOOB App > Settings)")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"system_instruction": {"parts": [{"text": system}]}, "contents": contents},
        timeout=40,
    )
    if r.status_code == 429:
        raise RuntimeError("Gemini free limit reached for now (429)")
    if r.status_code != 200:
        raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini gave no answer: {data.get('promptFeedback')}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise RuntimeError(f"Gemini gave an empty answer ({candidates[0].get('finishReason')})")
    return text


def ask_ollama(system, messages):
    r = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "stream": False,
              "messages": [{"role": "system", "content": system}] + messages},
        timeout=(3, 50),        # 3 s to connect (fails fast if Ollama is not installed), 50 s to answer
    )
    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
    return r.json()["message"]["content"]


def memory_prompt():
    text = ""
    profile = memory.get_profile()
    if profile:
        lines = "\n".join(f"{field}: {value}" for field, value in profile.items())
        text += f"\n\nThe user's profile (typed by the user in the NOOB App; always true, use it):\n{lines}"
    facts = memory.all_facts()
    if facts:
        lines = "\n".join(f"#{fid} (saved {saved_at}): {fact}" for fid, saved_at, fact in facts)
        text += f"\n\nYour memory list (things the user told you earlier; #number = id):\n{lines}"
    return text or "\n\nYou do not know anything about the user yet."


def apply_memory_commands(reply):
    """Saves REMEMBER facts, deletes FORGET ids, and returns the answer without those commands."""
    match = re.search(r"\b(?:REMEMBER|FORGET)\s*:", reply)
    if not match:
        return reply.strip()
    answer, commands = reply[:match.start()], reply[match.start():]
    for kind, value in re.findall(r"\b(REMEMBER|FORGET)\s*:\s*(.+?)\s*(?=\b(?:REMEMBER|FORGET)\s*:|$)",
                                  commands, flags=re.DOTALL):
        if kind == "REMEMBER" and value:
            log(f"   [memory] saved #{memory.add_fact(value)}: {value}")
        elif kind == "FORGET":
            number = re.search(r"\d+", value)
            if number and memory.delete_fact(int(number.group())):
                log(f"   [memory] forgot #{number.group()}")
    return answer.strip()


def now_text():
    return datetime.now().strftime("%A, %d %B %Y, %I:%M %p")


def think(system, messages):
    """Asks Gemini first, then the offline Ollama brain. Returns the reply, or None if both fail."""
    for name, brain in (("Gemini", ask_gemini), ("Ollama", ask_ollama)):
        try:
            return brain(system, messages)
        except Exception as e:                       # this brain failed: try the next one
            log(f"!! {name}: {e}")
    return None


def search_request(reply):
    match = re.search(r"\bSEARCH\s*:\s*(.+)", reply)
    return match.group(1).strip() if match else None


def web_search(query):
    log(f"   [search] {query}")
    try:
        results = DDGS().text(query, region="in-en", max_results=5)
    except Exception as e:
        return (f"The web search for '{query}' failed ({e}). Answer from your own knowledge and say "
                f"that you could not check the latest information.")
    lines = "\n".join(f"{i}. {r.get('title', '')}: {r.get('body', '')}" for i, r in enumerate(results, 1))
    return f"Web search results for '{query}' (today is {now_text()}):\n{lines or 'No results found.'}"


def ask_ai(user_text):
    """The whole 'thinking' step. Returns the answer with its language tag, or None if no AI is reachable."""
    system = SYSTEM_PROMPT + memory_prompt() + f"\n\nCurrent date and time (India): {now_text()}"
    messages = memory.recent_messages(RECENT_MESSAGES) + [{"role": "user", "content": user_text}]

    reply = think(system, messages)
    query = search_request(reply) if reply else None
    if query:                                        # the AI needs live information: search, then ask again
        messages = messages + [
            {"role": "assistant", "content": f"SEARCH: {query}"},
            {"role": "user", "content": web_search(query) +
             "\n\nNow answer my original question using these results. Do not search again."},
        ]
        reply = think(system, messages)
        if reply and search_request(reply):
            reply = "Sorry, I could not find that information right now."
    if reply is None:
        return None

    answer = apply_memory_commands(reply) or "Sorry, I have no answer for that."
    memory.add_exchange(user_text, answer)
    return answer


# ------------------------------ step 3: answer -> speech ------------------------------
def split_language_tag(reply, fallback_lang):
    match = re.match(r"\s*\[([a-zA-Z]{2,3})(?:-[a-zA-Z]+)?\]\s*", reply)
    if match:
        return match.group(1).lower(), reply[match.end():]
    return fallback_lang, reply


def clean_for_speech(text):
    text = re.sub(r"https?://\S+", "", text)                        # drop links
    text = re.sub(r"\[[a-zA-Z]{2,3}(?:-[a-zA-Z]+)?\]", "", text)    # drop stray language tags
    text = re.sub(r"[*#_`>|~\[\]]", "", text)                        # drop markdown symbols
    return re.sub(r"\s+", " ", text).strip()


def text_to_speech(text, lang):
    """Returns NOOB's voice as 16 kHz, 16-bit, mono PCM."""
    voice = VOICES.get(lang) or VOICES.get("en")

    async def synthesize():
        mp3 = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                mp3 += chunk["data"]
        return bytes(mp3)

    return any_audio_to_pcm(asyncio.run(synthesize()))


def pcm_to_wav(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buffer.getvalue()


def speak_pcm(text, lang="en"):
    return Response(text_to_speech(clean_for_speech(text), lang), mimetype="application/octet-stream")


NOT_HEARD = "Sorry, I did not hear anything. Please try again."
NO_BRAIN = "Sorry, I cannot reach my brain right now. Please check the internet and try again."


# ------------------------------ NOOB device ------------------------------
@app.post("/ask")
def ask():
    """The NOOB device sends raw 16 kHz PCM audio here and plays the raw PCM answer."""
    if request.headers.get("X-Device-Key") != settings()["device_key"]:
        abort(403)
    pcm = request.get_data()
    if len(pcm) < SAMPLE_RATE // 2:                  # less than 0.25 s of audio
        return speak_pcm(NOT_HEARD)

    started = time.time()
    user_text, heard_lang = speech_to_text(pcm)
    log(f"You (device, {heard_lang}): {user_text}")
    if not user_text:
        return speak_pcm(NOT_HEARD)
    reply = ask_ai(user_text)
    if reply is None:
        return speak_pcm(NO_BRAIN)
    lang, answer = split_language_tag(reply, heard_lang)
    log(f"NOOB ({lang}): {answer}")
    audio = speak_pcm(answer, lang)
    log(f"   answered in {time.time() - started:.1f} s")
    return audio


@app.get("/health")
def health():
    response = jsonify(ok=True, version=VERSION)
    response.headers["Access-Control-Allow-Origin"] = "*"      # lets the start-up screen check if NOOB is ready
    return response


# ------------------------------ NOOB App (this PC only) ------------------------------
def this_pc_only(view):
    """Your data is private: the app and its API only open on this PC."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403)
        return view(*args, **kwargs)
    return wrapper


@app.get("/")
@this_pc_only
def home():
    return redirect("/app")


@app.get("/app")
@this_pc_only
def web_app():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
@this_pc_only
def api_status():
    s = settings()
    ip = noob_devices.local_ip()
    return jsonify(version=VERSION, ip=ip, server_url=f"http://{ip}:{PORT}/ask", whisper=WHISPER_SIZE,
                   gemini=bool(s["gemini_api_key"] or os.environ.get("GEMINI_API_KEY")), gemini_model=GEMINI_MODEL,
                   facts=len(memory.all_facts()), messages=len(memory.recent_log(100000)),
                   profile_name=memory.get_profile().get("Name", ""), devices=len(s["devices"]),
                   languages=len(VOICES), time=now_text())


def answer_json(user_text, heard_lang="en"):
    if not user_text:
        return jsonify(you="", answer=NOT_HEARD, lang="en", ok=False)
    reply = ask_ai(user_text)
    if reply is None:
        return jsonify(you=user_text, answer=NO_BRAIN, lang="en", ok=False)
    lang, answer = split_language_tag(reply, heard_lang)
    log(f"NOOB ({lang}): {answer}")
    return jsonify(you=user_text, answer=answer, lang=lang, ok=True)


@app.post("/api/chat")
@this_pc_only
def api_chat():
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()[:2000]
    log(f"You (typed): {text}")
    return answer_json(text)


@app.post("/api/voice")
@this_pc_only
def api_voice():
    """Voice from the app's microphone (any audio format)."""
    try:
        pcm = any_audio_to_pcm(request.get_data())
    except Exception as e:
        log(f"!! Could not read the recording: {e}")
        return jsonify(you="", answer=NOT_HEARD, lang="en", ok=False)
    if len(pcm) < SAMPLE_RATE // 2:
        return jsonify(you="", answer=NOT_HEARD, lang="en", ok=False)
    text, heard_lang = speech_to_text(pcm)
    log(f"You (app mic, {heard_lang}): {text}")
    return answer_json(text, heard_lang)


@app.post("/api/speak")
@this_pc_only
def api_speak():
    data = request.get_json(silent=True) or {}
    text = clean_for_speech(str(data.get("text", "")))[:3000]
    if not text:
        abort(400)
    return Response(pcm_to_wav(text_to_speech(text, str(data.get("lang", "en")))), mimetype="audio/wav")


@app.get("/api/profile")
@this_pc_only
def api_profile_get():
    return jsonify(memory.get_profile())


@app.put("/api/profile")
@this_pc_only
def api_profile_put():
    data = request.get_json(silent=True) or {}
    memory.set_profile({str(k)[:60]: str(v)[:1000] for k, v in data.items()})
    return jsonify(ok=True)


@app.get("/api/facts")
@this_pc_only
def api_facts():
    return jsonify([{"id": i, "saved_at": t, "fact": f} for i, t, f in memory.all_facts()])


@app.post("/api/facts")
@this_pc_only
def api_fact_add():
    fact = str((request.get_json(silent=True) or {}).get("fact", "")).strip()[:500]
    if not fact:
        abort(400)
    return jsonify(id=memory.add_fact(fact))


@app.put("/api/facts/<int:fact_id>")
@this_pc_only
def api_fact_edit(fact_id):
    fact = str((request.get_json(silent=True) or {}).get("fact", "")).strip()[:500]
    if not fact or not memory.update_fact(fact_id, fact):
        abort(404)
    return jsonify(ok=True)


@app.delete("/api/facts/<int:fact_id>")
@this_pc_only
def api_fact_delete(fact_id):
    return jsonify(ok=memory.delete_fact(fact_id))


@app.get("/api/conversation")
@this_pc_only
def api_conversation():
    return jsonify([{"time": t, "role": r, "text": x} for t, r, x in memory.recent_log(500)])


@app.delete("/api/conversation")
@this_pc_only
def api_conversation_clear():
    memory.clear_conversation()
    return jsonify(ok=True)


@app.get("/api/settings")
@this_pc_only
def api_settings_get():
    key = settings()["gemini_api_key"]
    return jsonify(gemini_key_set=bool(key), gemini_key_hint=("••••" + key[-4:]) if key else "")


@app.put("/api/settings")
@this_pc_only
def api_settings_put():
    data = request.get_json(silent=True) or {}
    with settings_lock:
        s = noob_settings.load()
        if "gemini_api_key" in data:
            s["gemini_api_key"] = str(data["gemini_api_key"]).strip()
        noob_settings.save(s)
    return jsonify(ok=True)


@app.get("/api/log")
@this_pc_only
def api_log():
    return jsonify(list(LOG_LINES))


@app.post("/api/shutdown")
@this_pc_only
def api_shutdown():
    log("NOOB server stopped from the app.")
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify(ok=True)


# ------------------------------ Connect to nearby devices ------------------------------
@app.get("/api/devices")
@this_pc_only
def api_devices():
    return jsonify(settings()["devices"])


@app.post("/api/devices/scan")
@this_pc_only
def api_devices_scan():
    paired = {d["mac"] for d in settings()["devices"]}
    found = noob_devices.scan()
    for d in found:
        d["mine"] = d["mac"] in paired
    log(f"Scan: found {len(found)} NOOB device(s)")
    return jsonify(found)


@app.post("/api/devices/pair/start")
@this_pc_only
def api_pair_start():
    ip = str((request.get_json(silent=True) or {}).get("ip", ""))
    ok = noob_devices.send(ip, "NOOB?PAIRSTART", {"NOOB!CODE"}) is not None
    return jsonify(ok=ok)


@app.post("/api/devices/pair")
@this_pc_only
def api_pair():
    data = request.get_json(silent=True) or {}
    ip, code = str(data.get("ip", "")), str(data.get("code", "")).strip()
    if not re.fullmatch(r"\d{4}", code):
        return jsonify(ok=False, error="The code has 4 digits.")
    with settings_lock:
        s = noob_settings.load()
        url = f"http://{noob_devices.local_ip(ip)}:{PORT}/ask"
        reply = noob_devices.send(ip, f"NOOB?PAIR|{code}|{url}|{s['device_key']}", {"NOOB!PAIRED", "NOOB!BADCODE"})
        if reply is None:
            return jsonify(ok=False, error="The device did not answer. Is it switched on and on the same Wi-Fi?")
        if reply.startswith("NOOB!BADCODE"):
            return jsonify(ok=False, error="Wrong code. Check the code on NOOB's screen and try again.")
        _, name, mac = (reply.split("|") + ["", ""])[:3]
        s["devices"] = [d for d in s["devices"] if d["mac"] != mac] + [
            {"name": name, "mac": mac, "ip": ip, "paired_at": datetime.now().strftime("%Y-%m-%d %H:%M")}]
        noob_settings.save(s)
    log(f"Paired with {name} ({ip})")
    return jsonify(ok=True, name=name)


@app.delete("/api/devices/<mac>")
@this_pc_only
def api_unpair(mac):
    with settings_lock:
        s = noob_settings.load()
        device = next((d for d in s["devices"] if d["mac"] == mac), None)
        if device:
            noob_devices.send(device["ip"], f"NOOB?UNPAIR|{s['device_key']}", {"NOOB!UNPAIRED"}, seconds=1.5)
        s["devices"] = [d for d in s["devices"] if d["mac"] != mac]
        noob_settings.save(s)
    return jsonify(ok=True)


if __name__ == "__main__":
    noob_devices.start_server_responder(PORT, log)
    log(f"NOOB server running. Open the NOOB App: http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
