"""
Online access for NOOB AI (optional, free): a Cloudflare Tunnel gives the NOOB App a secure web address such
as https://ai.nooob.xyz, so it opens from phones anywhere and from the "NOOB AI" button in the NOOB social app.

One-time setup: double-click "Setup online access.bat" (or run:  python noob_tunnel.py setup).
After that the NOOB server starts the tunnel by itself every time it starts.

Everything stays inside this folder: tools/cloudflared.exe and tunnel.yml (both kept out of GitHub).
The Cloudflare login and tunnel keys are saved by cloudflared in your user folder (.cloudflared).
"""

import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED = os.path.join(HERE, "tools", "cloudflared.exe")
CONFIG = os.path.join(HERE, "tunnel.yml")
LOG_FILE = os.path.join(HERE, "noob_tunnel.log")
DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
TUNNEL_NAME = "noob-ai"
HIDDEN = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def configured():
    return os.path.exists(CONFIG) and os.path.exists(CLOUDFLARED)


def public_url():
    """The https address from tunnel.yml, or '' when online access is not set up."""
    if not os.path.exists(CONFIG):
        return ""
    match = re.search(r"hostname:\s*(\S+)", open(CONFIG, encoding="utf-8").read())
    return f"https://{match.group(1)}" if match else ""


def start(log):
    """Starts the tunnel in the background (called by the NOOB server). Returns the process or None."""
    if not configured():
        return None
    out = open(LOG_FILE, "a", encoding="utf-8")
    process = subprocess.Popen([CLOUDFLARED, "tunnel", "--no-autoupdate", "--config", CONFIG, "run"],
                               stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, creationflags=HIDDEN)
    log(f"Online access on: {public_url()}")
    return process


# ------------------------------ one-time setup ------------------------------
def run(*args):
    result = subprocess.run([CLOUDFLARED, *args], capture_output=True, text=True)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def setup(hostname):
    if not os.path.exists(CLOUDFLARED):
        print("Downloading cloudflared from Cloudflare (about 60 MB)...")
        os.makedirs(os.path.dirname(CLOUDFLARED), exist_ok=True)
        urllib.request.urlretrieve(DOWNLOAD_URL, CLOUDFLARED + ".part")
        os.replace(CLOUDFLARED + ".part", CLOUDFLARED)

    cert = os.path.join(os.path.expanduser("~"), ".cloudflared", "cert.pem")
    if not os.path.exists(cert):
        print("\nA browser window opens: log in to Cloudflare, click your domain, then click Authorize.")
        subprocess.run([CLOUDFLARED, "tunnel", "login"])
        if not os.path.exists(cert):
            sys.exit("Cloudflare login was not finished. Run this setup again.")

    code, text = run("tunnel", "create", TUNNEL_NAME)
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", text)
    if code != 0:
        if "already exists" not in text:
            sys.exit("Could not create the tunnel:\n" + text)
        code, text = run("tunnel", "info", TUNNEL_NAME)
        match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", text)
    if not match:
        sys.exit("Could not find the tunnel id:\n" + text)
    tunnel_id = match.group(1)
    credentials = os.path.join(os.path.expanduser("~"), ".cloudflared", f"{tunnel_id}.json")
    if not os.path.exists(credentials):
        sys.exit(f"The tunnel '{TUNNEL_NAME}' was made on another PC. Delete it in the Cloudflare dashboard "
                 f"(Zero Trust > Networks > Tunnels) and run this setup again.")

    code, text = run("tunnel", "route", "dns", TUNNEL_NAME, hostname)
    if code != 0 and "already exists" not in text:
        sys.exit("Could not create the web address:\n" + text)

    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write(f"tunnel: {tunnel_id}\n"
                f"credentials-file: {credentials}\n"
                f"ingress:\n"
                f"  - hostname: {hostname}\n"
                f"    service: http://localhost:5000\n"
                f"  - service: http_status:404\n")
    print(f"\nDone! NOOB AI will be online at https://{hostname} whenever the NOOB server is running.")
    print("Restart NOOB (Settings > Stop NOOB server, then open NOOB App.bat) to switch it on now.")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "setup":
    name = sys.argv[2] if len(sys.argv) > 2 else input("Web address for NOOB AI (e.g. ai.yourdomain.com): ").strip()
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", name.lower()):
        sys.exit("That does not look like a web address.")
    setup(name.lower())
