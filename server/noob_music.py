"""
Songs from YouTube for NOOB ("play Kesariya", "gaana chalao", "play some lofi music").

- search(): finds songs on YouTube, free and without an API key (yt-dlp; DuckDuckGo as a backup).
- The NOOB App plays them with YouTube's own player (see web/app.js), so nothing is downloaded for the app.
- pcm(): for the NOOB device, which has only a speaker: the song's sound is fetched from YouTube while it plays
  and turned into the same 16 kHz audio NOOB speaks with. Press NOOB's button to stop it.
"""

import requests

try:
    import yt_dlp
except ImportError:                                    # not installed yet: run "Setup NOOB.bat" again
    yt_dlp = None

MAX_DEVICE_SECONDS = 15 * 60          # the device plays at most 15 minutes of one video
YDL_OPTIONS = {"quiet": True, "no_warnings": True, "noplaylist": True,
               "js_runtimes": {"node": {}}}   # Node.js (if installed) helps yt-dlp read YouTube's pages


def search(query, limit=6):
    """Returns up to `limit` YouTube videos: [{"id", "title", "channel", "duration"}] (duration in seconds, 0 = live)."""
    query = (query or "").strip()[:200]
    if not query:
        return []
    results = []
    if yt_dlp:
        try:
            with yt_dlp.YoutubeDL({**YDL_OPTIONS, "extract_flat": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            for e in info.get("entries") or []:
                if e.get("id") and len(e["id"]) == 11:
                    results.append({"id": e["id"], "title": str(e.get("title") or "")[:200],
                                    "channel": str(e.get("channel") or e.get("uploader") or "")[:100],
                                    "duration": int(e.get("duration") or 0)})
        except Exception:
            results = []
    if not results:                                   # backup: DuckDuckGo's video search
        try:
            from ddgs import DDGS
            for r in DDGS().videos(query, max_results=limit * 2):
                url = str(r.get("content") or "")
                video_id = url.split("v=")[-1][:11] if "youtube.com/watch?v=" in url else ""
                if len(video_id) == 11:
                    results.append({"id": video_id, "title": str(r.get("title") or "")[:200],
                                    "channel": str(r.get("publisher") or r.get("uploader") or "")[:100], "duration": 0})
        except Exception:
            pass
    return results[:limit]


def best_for_device(results):
    """A normal-length song for the speaker: skips live streams and very long videos when there is a choice."""
    for r in results:
        if 0 < r["duration"] <= MAX_DEVICE_SECONDS:
            return r
    return results[0] if results else None


class _YouTubeFile:
    """The song's file, read in 1 MB pieces as it plays (YouTube slows down one long download)."""
    PIECE = 1 << 20

    def __init__(self, url, headers, size):
        self.url, self.headers, self.size = url, headers, size
        self.pos, self.buffer = 0, b""
        self.http = requests.Session()

    def read(self, n=-1):
        want = n if n and n > 0 else self.PIECE
        while len(self.buffer) < want and (not self.size or self.pos < self.size):
            end = self.pos + self.PIECE - 1
            r = self.http.get(self.url, headers={**self.headers, "Range": f"bytes={self.pos}-{end}"}, timeout=(8, 30))
            if r.status_code not in (200, 206) or not r.content:
                break
            self.buffer += r.content
            self.pos += len(r.content)
        out, self.buffer = self.buffer[:want], self.buffer[want:]
        return out


def pcm(video_id, rate=16000):
    """Yields the video's sound as 16-bit mono PCM pieces while it downloads (first sound after ~2-3 s)."""
    import av
    with yt_dlp.YoutubeDL({**YDL_OPTIONS, "format": "bestaudio[ext=webm]/bestaudio/best"}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    source = _YouTubeFile(info["url"], info.get("http_headers") or {}, info.get("filesize") or info.get("filesize_approx"))
    container = av.open(source, mode="r")
    try:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        sent, limit = 0, MAX_DEVICE_SECONDS * rate * 2
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                data = out.to_ndarray().tobytes()
                sent += len(data)
                yield data
            if sent >= limit:
                break
    finally:
        container.close()
