"""
NOOB settings shared by the NOOB App and the NOOB server.
Saved in noob_settings.json next to this file (on your PC only - never upload it).
"""

import json
import os
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "noob_settings.json")
DEFAULTS = {
    "gemini_api_key": "",
    "secret_key": "",        # signs login cookies (created automatically)
    "invite_code": "",       # new accounts need this code (shown to the owner in Settings)
    "open_to_noob_users": True,   # people who sign in with a NOOB social account don't need the invite code
    "devices": [],           # paired NOOB devices: [{"name", "mac", "ip", "key", "user_id", "paired_at"}]
}


def new_invite_code():
    return "-".join(secrets.token_hex(2).upper() for _ in range(2))      # e.g. "3F9A-C21B"


def load():
    settings = json.loads(json.dumps(DEFAULTS))       # deep copy
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            settings.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (FileNotFoundError, ValueError):
        pass
    changed = False
    if not settings["secret_key"]:                    # first run: create the secrets
        settings["secret_key"] = secrets.token_hex(32)
        changed = True
    if not settings["invite_code"]:
        settings["invite_code"] = new_invite_code()
        changed = True
    if changed:
        save(settings)
    return settings


def save(settings):
    data = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)       # write safely: never leaves a half-written file
