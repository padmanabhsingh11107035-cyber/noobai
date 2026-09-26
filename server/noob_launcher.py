"""
Opens the NOOB App.
  - starts the NOOB server in the background (if it is not already running)
  - opens the app in its own window (Microsoft Edge "app mode", or your normal browser)

The server keeps running after you close the window, so your NOOB device keeps working.
Stop it from the app: Settings > Stop NOOB server.
"""

import os
import subprocess
import sys
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
APP_URL = "http://localhost:5000/app"
LOADING_PAGE = os.path.join(HERE, "web", "loading.html")
LOG_FILE = os.path.join(HERE, "noob_server.log")


def server_running():
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 5_000_000:
        os.remove(LOG_FILE)                                   # keep the log file small
    log = open(LOG_FILE, "a", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
    subprocess.Popen([sys.executable, os.path.join(HERE, "noob_server.py")], cwd=HERE, env=env,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def open_window(url):
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            edge = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if base and os.path.exists(edge):
                subprocess.Popen([edge, f"--app={url}", "--window-size=1280,860"])
                return
    webbrowser.open(url)


if __name__ == "__main__":
    if server_running():
        open_window(APP_URL)
    else:
        start_server()
        # The start-up screen waits until NOOB is ready, then opens the app by itself.
        open_window("file:///" + LOADING_PAGE.replace("\\", "/"))
