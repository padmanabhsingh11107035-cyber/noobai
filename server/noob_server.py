"""
NOOB - AI voice assistant server (runs on your PC / laptop)   *** 100% free ***

How NOOB answers (for the NOOB device and for the NOOB App):
  1. Speech -> text   Whisper (99 languages, auto-detected, runs on this PC, free)
  2. Text -> answer   Google Gemini (free tier) - or a local AI with Ollama (free, offline) as backup
                      + today's date and time + free web search (DuckDuckGo) for live information
  3. Answer -> voice  Microsoft Edge neural voices (free, female voice, 70+ languages)

It also serves the NOOB App (http://localhost:5000). Everyone signs in with their own account
and gets their own "About Me", memory and conversations; they can talk to NOOB, manage what it
remembers, and connect their own NOOB devices. Everything is saved in noob_memory.db, so NOOB
remembers after switch-off.

Start: double-click "NOOB App.bat"   (or run:  python noob_server.py)
"""

import asyncio
import collections
import io
import logging
import os
import re
import secrets
import threading
import time
import wave
from datetime import datetime, timedelta
from functools import wraps

import av
import edge_tts
import numpy as np
import requests
from ddgs import DDGS
from faster_whisper import WhisperModel
from flask import Flask, Response, abort, g, jsonify, redirect, request, send_from_directory, session

import noob_devices
import noob_settings
import noob_social
import noob_tunnel
from noob_memory import NoobMemory

# ------------------------------ settings ------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_SIZE = os.environ.get("NOOB_WHISPER_MODEL", "small")     # tiny/base/small/medium/large-v3
# AI brain 1: Google Gemini free tier (needs internet). If one model is busy, the next one is tried.
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest", "gemini-3.7-flash",
                 "gemini-3.5-flash", "gemini-3.1-flash-lite"]
GEMINI_TIME_LIMIT = 40           # seconds to keep trying Gemini models (the NOOB device waits up to 60 s)
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
whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8",
                       download_root=os.path.join(HERE, "models"))      # kept inside the NOOB folder
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
log(f"{len(VOICES)} speech languages ready. Accounts: {memory.user_count()}.")


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
last_good_model = GEMINI_MODELS[0]


def ask_gemini_model(model, key, system, contents, timeout):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"system_instruction": {"parts": [{"text": system}]}, "contents": contents},
        timeout=timeout,
    )
    if r.status_code != 200:
        try:
            message = r.json()["error"]["message"]
        except Exception:
            message = r.text[:200]
        raise RuntimeError(f"{model}: error {r.status_code}: {message[:200]}")
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"{model}: no answer ({data.get('promptFeedback')})")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise RuntimeError(f"{model}: empty answer ({candidates[0].get('finishReason')})")
    return text


def ask_gemini(system, messages):
    """Tries the free Gemini models one by one (starting with the last one that worked)."""
    global last_good_model
    key = settings()["gemini_api_key"] or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("no Gemini API key set (NOOB App > Settings)")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages]
    deadline = time.time() + GEMINI_TIME_LIMIT
    models = [last_good_model] + [m for m in GEMINI_MODELS if m != last_good_model]
    for model in models:
        remaining = deadline - time.time()
        if remaining < 3:
            break
        try:
            text = ask_gemini_model(model, key, system, contents, timeout=min(20, remaining))
            last_good_model = model
            return text
        except requests.RequestException as e:
            log(f"   [gemini] {model}: no reply in time ({type(e).__name__}), trying another model")
        except RuntimeError as e:
            if any(code in str(e) for code in ("error 400", "error 401", "error 403")):
                raise RuntimeError(f"Gemini key problem - check it in Settings ({e})")
            log(f"   [gemini] {e} - trying another model")
    raise RuntimeError("all Gemini models are busy right now")


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


def memory_prompt(user_id):
    text = ""
    user = memory.get_user(user_id) or {}
    if user.get("name"):
        text += f"\n\nThe user's account name is {user['name']}."
    profile = memory.get_profile(user_id)
    if profile:
        lines = "\n".join(f"{field}: {value}" for field, value in profile.items())
        text += f"\n\nThe user's profile (typed by the user in the NOOB App; always true, use it):\n{lines}"
    facts = memory.all_facts(user_id)
    if facts:
        lines = "\n".join(f"#{fid} (saved {saved_at}): {fact}" for fid, saved_at, fact in facts)
        text += f"\n\nYour memory list (things the user told you earlier; #number = id):\n{lines}"
    return text or "\n\nYou do not know anything about the user yet."


def apply_memory_commands(reply, user_id):
    """Saves REMEMBER facts, deletes FORGET ids, and returns the answer without those commands."""
    match = re.search(r"\b(?:REMEMBER|FORGET)\s*:", reply)
    if not match:
        return reply.strip()
    answer, commands = reply[:match.start()], reply[match.start():]
    for kind, value in re.findall(r"\b(REMEMBER|FORGET)\s*:\s*(.+?)\s*(?=\b(?:REMEMBER|FORGET)\s*:|$)",
                                  commands, flags=re.DOTALL):
        if kind == "REMEMBER" and value:
            log(f"   [memory] saved #{memory.add_fact(user_id, value)}: {value}")
        elif kind == "FORGET":
            number = re.search(r"\d+", value)
            if number and memory.delete_fact(user_id, int(number.group())):
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


def ask_ai(user_id, user_text):
    """The whole 'thinking' step. Returns the answer with its language tag, or None if no AI is reachable."""
    system = SYSTEM_PROMPT + memory_prompt(user_id) + f"\n\nCurrent date and time (India): {now_text()}"
    messages = memory.recent_messages(user_id, RECENT_MESSAGES) + [{"role": "user", "content": user_text}]

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

    answer = apply_memory_commands(reply, user_id) or "Sorry, I have no answer for that."
    memory.add_exchange(user_id, user_text, answer)
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


# ------------------------------ accounts and sign-in ------------------------------
app.secret_key = settings()["secret_key"]
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30), MAX_CONTENT_LENGTH=20 * 1024 * 1024)
failed_logins = collections.defaultdict(list)          # IP address -> times of wrong passwords
DEVICE_SEEN = {}                                        # device MAC -> last time it said hello
ONLINE_SECONDS = 70


@app.after_request
def no_caching_of_personal_data(response):
    if request.path.startswith(("/api/", "/app", "/login", "/noob-signin", "/ask", "/device/")):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Vary"] = "Cookie"
    return response


def current_user():
    uid = session.get("uid")
    return memory.get_user(uid) if uid else None


def signed_in(view):
    """Pages and data need a NOOB account."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        g.user = current_user()
        if not g.user:
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in."), 401
            return redirect("/login")
        return view(*args, **kwargs)
    return wrapper


def owner_only(view):
    """Settings that affect everyone (AI key, invite code, accounts, stopping NOOB) are for the owner."""
    @wraps(view)
    @signed_in
    def wrapper(*args, **kwargs):
        if not g.user["is_owner"]:
            return jsonify(error="Only the owner of this NOOB can do that."), 403
        return view(*args, **kwargs)
    return wrapper


def body():
    return request.get_json(silent=True) or {}


def on_this_pc():
    """True only for the NOOB PC itself (not for visitors coming through a tunnel or proxy)."""
    return (request.remote_addr in ("127.0.0.1", "::1")
            and not any(h in request.headers for h in ("Cf-Connecting-Ip", "X-Forwarded-For", "Forwarded")))


def start_session(user_id):
    session.clear()
    session.permanent = True
    session["uid"] = user_id


@app.get("/")
def home():
    return redirect("/app" if current_user() else "/login")


@app.get("/login")
def login_page():
    if current_user():
        return redirect("/app")
    return send_from_directory(app.static_folder, "login.html")


@app.get("/api/auth/state")
def api_auth_state():
    user = current_user()
    return jsonify(signed_in=bool(user), name=user["name"] if user else "",
                   first_account=memory.user_count() == 0)


@app.post("/api/auth/signup")
def api_signup():
    data = body()
    username = str(data.get("username", "")).strip().lower()
    name = " ".join(str(data.get("name", "")).split())[:60]
    password = str(data.get("password", ""))
    if not re.fullmatch(r"[a-z0-9_.-]{3,30}", username):
        return jsonify(ok=False, error="Username: 3-30 letters, numbers, dots, dashes or underscores."), 400
    if not name:
        return jsonify(ok=False, error="Please enter your name."), 400
    if len(password) < 6:
        return jsonify(ok=False, error="Password: at least 6 characters."), 400
    first = memory.user_count() == 0
    if first and not on_this_pc():
        return jsonify(ok=False, error="Create the owner account on the NOOB PC first."), 403
    invite = settings()["invite_code"]
    if not first and str(data.get("invite", "")).strip().upper() != invite.upper():
        return jsonify(ok=False, error="Wrong invite code. Ask the owner of this NOOB for the code."), 403
    user_id = memory.create_user(username, name, password)
    if user_id is None:
        return jsonify(ok=False, error="That username is taken. Try another one."), 409
    profile = memory.get_profile(user_id)
    if not profile.get("Name"):
        memory.set_profile(user_id, {**profile, "Name": name})
    start_session(user_id)
    log(f"New account: {username}" + (" (owner)" if first else ""))
    return jsonify(ok=True)


@app.post("/api/auth/login")
def api_login():
    ip = request.remote_addr or "?"
    now = time.time()
    failed_logins[ip] = [t for t in failed_logins[ip] if now - t < 600]
    if len(failed_logins[ip]) >= 8:
        return jsonify(ok=False, error="Too many wrong tries. Wait 10 minutes and try again."), 429
    data = body()
    user_id = memory.check_login(str(data.get("username", "")).strip(), str(data.get("password", "")))
    if not user_id:
        failed_logins[ip].append(now)
        return jsonify(ok=False, error="Wrong username or password."), 401
    start_session(user_id)
    return jsonify(ok=True)


@app.post("/api/auth/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.post("/api/auth/password")
@signed_in
def api_change_password():
    data = body()
    if not memory.check_login(g.user["username"], str(data.get("old", ""))):
        return jsonify(ok=False, error="Your current password is not correct."), 403
    if len(str(data.get("new", ""))) < 6:
        return jsonify(ok=False, error="New password: at least 6 characters."), 400
    memory.change_password(g.user["id"], str(data["new"]))
    return jsonify(ok=True)


# ------------------------------ "Continue with NOOB" (NOOB social media account) ------------------------------
def too_many_tries():
    ip = request.remote_addr or "?"
    now = time.time()
    failed_logins[ip] = [t for t in failed_logins[ip] if now - t < 600]
    return len(failed_logins[ip]) >= 8


def check_noob_login(data):
    """Returns the NOOB account, or a JSON error response."""
    if too_many_tries():
        return None, (jsonify(ok=False, error="Too many wrong tries. Wait 10 minutes and try again."), 429)
    try:
        return noob_social.verify_login(str(data.get("identifier", "")), str(data.get("password", ""))), None
    except noob_social.NoobSocialError as e:
        if str(e).startswith("Wrong"):
            failed_logins[request.remote_addr or "?"].append(time.time())
        return None, (jsonify(ok=False, error=str(e)), 400)     # 400, not 401: the app session is still fine


def free_username(noob_username):
    base = re.sub(r"[^a-z0-9_.-]", "", noob_username.lower())[:26] or "noob"
    base = base if len(base) >= 3 else base + "user"
    name, n = base, 2
    while not memory.username_free(name):
        name, n = f"{base}-{n}", n + 1
    return name


@app.post("/api/auth/noob")
def api_noob_login():
    data = body()
    noob, error = check_noob_login(data)
    if error:
        return error
    return sign_in_noob_user(noob, data)


@app.get("/noob-signin")
def noob_signin_page():
    """Where the "NOOB AI" button in the NOOB social media app lands (the login token is after '#')."""
    return send_from_directory(app.static_folder, "noob-signin.html")


@app.post("/api/auth/noob-token")
def api_noob_token():
    session.clear()                                   # never continue in someone else's session on a shared device
    if too_many_tries():
        return jsonify(ok=False, error="Too many tries. Wait 10 minutes and try again."), 429
    data = body()
    try:
        noob = noob_social.verify_token(str(data.get("token", "")))
    except noob_social.NoobSocialError as e:
        failed_logins[request.remote_addr or "?"].append(time.time())
        return jsonify(ok=False, error=str(e)), 400
    return sign_in_noob_user(noob, data)


def sign_in_noob_user(noob, data):
    """Signs in the assistant account linked to this NOOB account (making one the first time)."""
    user_id = memory.user_for_noob(noob["id"])
    if not user_id:                                   # first time: make an assistant account for this NOOB user
        first = memory.user_count() == 0
        if first and not on_this_pc():
            return jsonify(ok=False, error="Create the owner account on the NOOB PC first."), 403
        if not first and not settings()["open_to_noob_users"]:
            invite = str(data.get("invite", "")).strip().upper()
            if invite != settings()["invite_code"].upper():
                return jsonify(ok=False, needs_invite=True,
                               error="First time here? Enter the invite code from the owner of this NOOB."
                               if not invite else "Wrong invite code. Ask the owner of this NOOB for the code."), 403
        user_id = memory.create_user(free_username(noob["username"]), noob["name"][:60], secrets.token_urlsafe(24))
        memory.link_noob(user_id, noob["id"], noob["username"])
        profile = memory.get_profile(user_id)
        if not profile.get("Name"):
            memory.set_profile(user_id, {**profile, "Name": noob["name"][:60]})
        log(f"New account from NOOB: @{noob['username']}" + (" (owner)" if first else ""))
    start_session(user_id)
    return jsonify(ok=True)


@app.post("/api/auth/noob/link")
@signed_in
def api_noob_link():
    noob, error = check_noob_login(body())
    if error:
        return error
    if not memory.link_noob(g.user["id"], noob["id"], noob["username"]):
        return jsonify(ok=False, error="That NOOB account is already linked to another account here."), 409
    log(f"{g.user['username']} linked NOOB account @{noob['username']}")
    return jsonify(ok=True, noob_username=noob["username"])


# ------------------------------ NOOB device ------------------------------
def device_for_key(key):
    if not key:
        return None
    return next((d for d in settings()["devices"] if d.get("key") and secrets.compare_digest(d["key"], key)), None)


def ascii_name(name):
    """The OLED font only has English letters."""
    clean = "".join(ch for ch in name if 32 <= ord(ch) < 127).strip()
    return (clean.split() or ["friend"])[0][:12]


@app.post("/ask")
def ask():
    """The NOOB device sends raw 16 kHz PCM audio here and plays the raw PCM answer."""
    device = device_for_key(request.headers.get("X-Device-Key", ""))
    if not device:
        abort(403)
    DEVICE_SEEN[device["mac"]] = time.time()
    user_id = device["user_id"]
    pcm = request.get_data()
    if len(pcm) < SAMPLE_RATE // 2:                  # less than 0.25 s of audio
        return speak_pcm(NOT_HEARD)

    started = time.time()
    user_text, heard_lang = speech_to_text(pcm)
    log(f"You ({device['name']}, {heard_lang}): {user_text}")
    if not user_text:
        return speak_pcm(NOT_HEARD)
    reply = ask_ai(user_id, user_text)
    if reply is None:
        return speak_pcm(NO_BRAIN)
    lang, answer = split_language_tag(reply, heard_lang)
    log(f"NOOB ({lang}): {answer}")
    audio = speak_pcm(answer, lang)
    log(f"   answered in {time.time() - started:.1f} s")
    return audio


@app.get("/device/ping")
def device_ping():
    """Every few seconds the NOOB device says hello, so the app knows it is online (and it knows the PC is)."""
    device = device_for_key(request.headers.get("X-Device-Key", ""))
    if not device:
        abort(403)
    if device["mac"] not in DEVICE_SEEN or time.time() - DEVICE_SEEN[device["mac"]] > ONLINE_SECONDS:
        log(f"{device['name']} is online")
    DEVICE_SEEN[device["mac"]] = time.time()
    user = memory.get_user(device["user_id"]) or {}
    return jsonify(ok=True, name=ascii_name(user.get("name", "")))


@app.get("/health")
def health():
    response = jsonify(ok=True, version=VERSION)
    response.headers["Access-Control-Allow-Origin"] = "*"      # lets the start-up screen check if NOOB is ready
    return response


# ------------------------------ NOOB App ------------------------------
def my_devices():
    now = time.time()
    return [{"name": d["name"], "mac": d["mac"], "ip": d["ip"], "paired_at": d["paired_at"],
             "online": now - DEVICE_SEEN.get(d["mac"], 0) < ONLINE_SECONDS}
            for d in settings()["devices"] if d.get("user_id") == g.user["id"] and d.get("key")]


@app.get("/app")
@signed_in
def web_app():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/status")
@signed_in
def api_status():
    s = settings()
    ip = noob_devices.local_ip()
    devices = my_devices()
    return jsonify(version=VERSION, ip=ip, server_url=f"http://{ip}:{PORT}/ask", whisper=WHISPER_SIZE,
                   gemini=bool(s["gemini_api_key"] or os.environ.get("GEMINI_API_KEY")), gemini_model=last_good_model,
                   facts=len(memory.all_facts(g.user["id"])), messages=len(memory.recent_log(g.user["id"], 100000)),
                   user={"name": g.user["name"], "username": g.user["username"], "is_owner": bool(g.user["is_owner"]),
                         "noob_username": g.user.get("noob_username") or ""},
                   profile_name=memory.get_profile(g.user["id"]).get("Name", "") or g.user["name"],
                   devices=len(devices), devices_online=sum(d["online"] for d in devices),
                   languages=len(VOICES), time=now_text(), online_url=noob_tunnel.public_url())


def answer_json(user_text, heard_lang="en"):
    if not user_text:
        return jsonify(you="", answer=NOT_HEARD, lang="en", ok=False)
    reply = ask_ai(g.user["id"], user_text)
    if reply is None:
        return jsonify(you=user_text, answer=NO_BRAIN, lang="en", ok=False)
    lang, answer = split_language_tag(reply, heard_lang)
    log(f"NOOB ({lang}): {answer}")
    return jsonify(you=user_text, answer=answer, lang=lang, ok=True)


@app.post("/api/chat")
@signed_in
def api_chat():
    text = str(body().get("text", "")).strip()[:2000]
    log(f"You ({g.user['username']}, typed): {text}")
    return answer_json(text)


@app.post("/api/voice")
@signed_in
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
    log(f"You ({g.user['username']}, voice, {heard_lang}): {text}")
    return answer_json(text, heard_lang)


@app.post("/api/speak")
@signed_in
def api_speak():
    data = body()
    text = clean_for_speech(str(data.get("text", "")))[:3000]
    if not text:
        abort(400)
    return Response(pcm_to_wav(text_to_speech(text, str(data.get("lang", "en")))), mimetype="audio/wav")


@app.get("/api/profile")
@signed_in
def api_profile_get():
    return jsonify(memory.get_profile(g.user["id"]))


@app.put("/api/profile")
@signed_in
def api_profile_put():
    memory.set_profile(g.user["id"], {str(k)[:60]: str(v)[:1000] for k, v in body().items()})
    return jsonify(ok=True)


@app.get("/api/facts")
@signed_in
def api_facts():
    return jsonify([{"id": i, "saved_at": t, "fact": f} for i, t, f in memory.all_facts(g.user["id"])])


@app.post("/api/facts")
@signed_in
def api_fact_add():
    fact = str(body().get("fact", "")).strip()[:500]
    if not fact:
        abort(400)
    return jsonify(id=memory.add_fact(g.user["id"], fact))


@app.put("/api/facts/<int:fact_id>")
@signed_in
def api_fact_edit(fact_id):
    fact = str(body().get("fact", "")).strip()[:500]
    if not fact or not memory.update_fact(g.user["id"], fact_id, fact):
        abort(404)
    return jsonify(ok=True)


@app.delete("/api/facts/<int:fact_id>")
@signed_in
def api_fact_delete(fact_id):
    return jsonify(ok=memory.delete_fact(g.user["id"], fact_id))


@app.get("/api/conversation")
@signed_in
def api_conversation():
    return jsonify([{"time": t, "role": r, "text": x} for t, r, x in memory.recent_log(g.user["id"], 500)])


@app.delete("/api/conversation")
@signed_in
def api_conversation_clear():
    memory.clear_conversation(g.user["id"])
    return jsonify(ok=True)


# ------------------------------ owner settings ------------------------------
@app.get("/api/settings")
@owner_only
def api_settings_get():
    s = settings()
    key = s["gemini_api_key"]
    return jsonify(gemini_key_set=bool(key), gemini_key_hint=("••••" + key[-4:]) if key else "",
                   invite_code=s["invite_code"], open_to_noob_users=s["open_to_noob_users"], users=memory.all_users())


@app.put("/api/settings")
@owner_only
def api_settings_put():
    data = body()
    with settings_lock:
        s = noob_settings.load()
        if "gemini_api_key" in data:
            s["gemini_api_key"] = str(data["gemini_api_key"]).strip()
        if "open_to_noob_users" in data:
            s["open_to_noob_users"] = bool(data["open_to_noob_users"])
        noob_settings.save(s)
    return jsonify(ok=True)


@app.post("/api/settings/invite")
@owner_only
def api_new_invite():
    with settings_lock:
        s = noob_settings.load()
        s["invite_code"] = noob_settings.new_invite_code()
        noob_settings.save(s)
    return jsonify(invite_code=s["invite_code"])


@app.delete("/api/users/<int:user_id>")
@owner_only
def api_delete_user(user_id):
    if not memory.delete_user(user_id):
        return jsonify(ok=False, error="The owner account cannot be removed."), 400
    with settings_lock:                              # their devices are unpaired too
        s = noob_settings.load()
        s["devices"] = [d for d in s["devices"] if d.get("user_id") != user_id]
        noob_settings.save(s)
    return jsonify(ok=True)


@app.get("/api/log")
@owner_only
def api_log():
    return jsonify(list(LOG_LINES))


@app.post("/api/shutdown")
@owner_only
def api_shutdown():
    log("NOOB server stopped from the app.")
    threading.Timer(0.5, stop_everything).start()
    return jsonify(ok=True)


# ------------------------------ Connect to nearby devices ------------------------------
@app.get("/api/devices")
@signed_in
def api_devices():
    return jsonify(my_devices())


@app.post("/api/devices/scan")
@signed_in
def api_devices_scan():
    owners = {d["mac"]: d.get("user_id") for d in settings()["devices"] if d.get("key")}
    found = noob_devices.scan()
    for d in found:
        d["mine"] = owners.get(d["mac"]) == g.user["id"]
        d["other_account"] = d["mac"] in owners and not d["mine"]
    log(f"Scan: found {len(found)} NOOB device(s)")
    return jsonify(found)


@app.post("/api/devices/pair/start")
@signed_in
def api_pair_start():
    ip = str(body().get("ip", ""))
    ok = noob_devices.send(ip, "NOOB?PAIRSTART", {"NOOB!CODE"}) is not None
    return jsonify(ok=ok)


@app.post("/api/devices/pair")
@signed_in
def api_pair():
    data = body()
    ip, code = str(data.get("ip", "")), str(data.get("code", "")).strip()
    if not re.fullmatch(r"\d{4}", code):
        return jsonify(ok=False, error="The code has 4 digits.")
    key = secrets.token_hex(12)                      # every device gets its own secret key
    url = f"http://{noob_devices.local_ip(ip)}:{PORT}/ask"
    reply = noob_devices.send(ip, f"NOOB?PAIR|{code}|{url}|{key}", {"NOOB!PAIRED", "NOOB!BADCODE"})
    if reply is None:
        return jsonify(ok=False, error="The device did not answer. Is it switched on and on the same Wi-Fi?")
    if reply.startswith("NOOB!BADCODE"):
        return jsonify(ok=False, error="Wrong code. Check the code on NOOB's screen and try again.")
    _, name, mac = (reply.split("|") + ["", ""])[:3]
    with settings_lock:
        s = noob_settings.load()
        s["devices"] = [d for d in s["devices"] if d.get("mac") != mac] + [
            {"name": name, "mac": mac, "ip": ip, "key": key, "user_id": g.user["id"],
             "paired_at": datetime.now().strftime("%Y-%m-%d %H:%M")}]
        noob_settings.save(s)
    DEVICE_SEEN[mac] = time.time()
    log(f"{g.user['username']} paired {name} ({ip})")
    return jsonify(ok=True, name=name)


@app.delete("/api/devices/<mac>")
@signed_in
def api_unpair(mac):
    with settings_lock:
        s = noob_settings.load()
        device = next((d for d in s["devices"] if d.get("mac") == mac and d.get("user_id") == g.user["id"]), None)
        if not device:
            abort(404)
        noob_devices.send(device["ip"], f"NOOB?UNPAIR|{device['key']}", {"NOOB!UNPAIRED"}, seconds=1.5)
        s["devices"] = [d for d in s["devices"] if d.get("mac") != mac]
        noob_settings.save(s)
    return jsonify(ok=True)


tunnel = None


def stop_everything():
    if tunnel and tunnel.poll() is None:
        tunnel.terminate()                             # online access stops with the server
    os._exit(0)


if __name__ == "__main__":
    noob_devices.start_server_responder(PORT, log)
    tunnel = noob_tunnel.start(log)
    log(f"NOOB server running. Open the NOOB App: http://localhost:{PORT}  "
        f"(other devices on this Wi-Fi: http://{noob_devices.local_ip()}:{PORT})")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
