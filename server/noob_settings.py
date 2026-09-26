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
    "device_key": "",        # secret shared with paired NOOB devices (created automatically)
    "devices": [],           # paired NOOB devices: [{"name", "mac", "ip", "paired_at"}]
}


def load():
    settings = json.loads(json.dumps(DEFAULTS))       # deep copy
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            settings.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (FileNotFoundError, ValueError):
        pass
    if not settings["device_key"]:                    # first run: create a random secret key
        settings["device_key"] = secrets.token_hex(12)
        save(settings)
    return settings


def save(settings):
    data = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)       # write safely: never leaves a half-written file
