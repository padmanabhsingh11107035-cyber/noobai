"""
NOOB's AI brain connection: Google Gemini (free tier), streamed so NOOB can start speaking at once.

Speed tricks (measured on a laptop on a phone hotspot):
- The fastest, steadiest free model goes first (gemini-3.5-flash-lite: ~1.5 s typed, ~2.5 s spoken).
- "Thinking" is kept to a minimum: it made spoken answers 4-10x slower.
- Voice is sent to Gemini directly (it understands speech in every language), so the slow speech-to-text
  step on the PC is skipped. The recording is compressed first (about 10 KB instead of 140 KB).
- Google's free service sometimes stalls on one request. If the first model has not started answering
  after a few seconds, a second model is asked at the same time and the first one to answer wins.
- A model that is out of its free daily quota (429), overloaded (503) or unavailable is rested for a while,
  so NOOB never wastes time on it again and again.
"""

import json
import queue
import threading
import time

import requests

GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.8-flash",
                 "gemini-3.6-flash", "gemini-flash-latest", "gemini-3.7-flash", "gemini-3.5-flash"]
REST_SECONDS = {429: 15 * 60, 503: 60, 500: 60, 404: 24 * 3600}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
HEDGE_AFTER = 3.0                 # seconds without an answer before a second model is asked as well
THINKING_LEVELS = ["minimal", "low", None]      # least thinking first; remembered once a model refuses one

_rest_until = {}
_thinking = {}
last_model = GEMINI_MODELS[0]


class BrainUnavailable(Exception):
    pass


def _rest(model, seconds):
    _rest_until[model] = time.time() + seconds


def _ready_models():
    now = time.time()
    ready = [m for m in GEMINI_MODELS if _rest_until.get(m, 0) <= now]
    # if everything is resting, try the one that becomes free soonest
    return ready or sorted(GEMINI_MODELS, key=lambda m: _rest_until.get(m, 0))[:1]


def _sse_events(response):
    """Reads Server-Sent Events safely (split only on real newlines, decode whole lines as UTF-8)."""
    buffer = b""
    for chunk in response.iter_content(chunk_size=None):
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.strip()
            if line.startswith(b"data: "):
                yield json.loads(line[6:].decode("utf-8"))


def _ask_model(model, key, system, contents, out, stop):
    """Runs in a thread: streams one model's answer into `out` as ("text"/"end"/"fail"/"key", model, value)."""
    try:
        while True:                               # find the least thinking this model accepts
            level = _thinking.get(model, THINKING_LEVELS[0])
            body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents}
            if level:
                body["generationConfig"] = {"thinkingConfig": {"thinkingLevel": level}}
            response = requests.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, json=body,
                                     stream=True, timeout=(8, 20))
            if response.status_code == 400 and level and "thinking" in response.text.lower():
                _thinking[model] = THINKING_LEVELS[THINKING_LEVELS.index(level) + 1]
                continue
            break
        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except Exception:
                message = response.text[:200]
            kind = "key" if response.status_code in (401, 403) or "API key" in message else "fail"
            out.put((kind, model, (response.status_code, message)))
            return
        answered = False
        with response:
            for event in _sse_events(response):
                if stop.is_set():
                    return
                candidates = event.get("candidates") or []
                parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
                for part in parts:
                    if part.get("text") and not part.get("thought"):
                        answered = True
                        out.put(("text", model, part["text"]))
        out.put(("end", model, None) if answered else ("fail", model, (0, "empty answer")))
    except (requests.RequestException, ValueError) as e:
        out.put(("fail", model, (0, type(e).__name__)))


def gemini_stream(key, system, contents, log, time_limit=45):
    """Yields the answer text piece by piece from the fastest free Gemini model that answers.
    Raises BrainUnavailable when no model can answer right now."""
    global last_model
    if not key:
        raise BrainUnavailable("no Gemini API key set (NOOB App > Settings)")
    started = time.time()
    waiting = list(_ready_models())
    out = queue.Queue()
    stops = {}
    winner = None

    def launch():
        model = waiting.pop(0)
        stops[model] = threading.Event()
        threading.Thread(target=_ask_model, args=(model, key, system, contents, out, stops[model]), daemon=True).start()
        return time.time()

    last_launch = launch()
    running = 1
    try:
        while True:
            try:
                kind, model, value = out.get(timeout=0.2)
            except queue.Empty:
                now = time.time()
                if winner is None and waiting and running < 2 and now - last_launch > HEDGE_AFTER:
                    last_launch = launch()        # the first model is slow today: ask another one too
                    running += 1
                if winner is None and now - started > time_limit:
                    break
                continue
            if kind == "text":
                if winner is None:
                    winner = model
                    for other, stop in stops.items():
                        if other != model:
                            stop.set()
                if model == winner:
                    yield value
            elif kind == "end" and model == winner:
                last_model = winner
                return
            elif kind == "key":
                raise BrainUnavailable(f"Gemini key problem - check it in Settings ({value[1][:120]})")
            elif kind == "fail":
                running -= 1
                if model == winner:               # cut off part-way: keep what we have
                    log(f"   [gemini] {model}: stream ended early")
                    return
                status, message = value
                log(f"   [gemini] {model}: {status or ''} {message[:80]} - trying another model")
                _rest(model, REST_SECONDS.get(status, 60 if status == 0 else 5 * 60))
                if winner is None and waiting and running < 2:
                    last_launch = launch()
                    running += 1
                if winner is None and running == 0 and not waiting:
                    break
    finally:
        for stop in stops.values():               # stop every model still talking
            stop.set()
    raise BrainUnavailable("all free Gemini models are busy or out of today's free quota")
