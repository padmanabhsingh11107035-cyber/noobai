"""
"Continue with NOOB": sign in to the NOOB AI Assistant with a NOOB social media account (nooob.xyz).

It checks the username/email and password with NOOB's own login service (the same one the
nooob.xyz website uses), reads the account's signup details (name, birthday, phone, email, city...), and ends that login
straight away. The NOOB password is never saved or logged by the assistant.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NOOB_SOCIAL_URL = "https://abffssydapumuhwgzeck.supabase.co"
# The website's public "publishable" key: safe to share, it can only do what NOOB's security rules allow.
NOOB_SOCIAL_KEY = "sb_publishable_g20GG46EXeMr1jcNwVJtmw_rAZKsuA3"
TIMEOUT = (6, 15)          # seconds to connect, seconds to wait for the answer

# One shared connection to NOOB that stays open between sign-ins (no new DNS lookup and secure handshake
# every time, which is slow on a phone hotspot). A connection that fails to open is retried twice.
_http = requests.Session()
_http.mount("https://", HTTPAdapter(pool_maxsize=8, max_retries=Retry(
    total=2, connect=2, read=0, status=0, backoff_factor=0.4, allowed_methods=None)))
_pool = ThreadPoolExecutor(max_workers=4)


def warm_up():
    """Opens the connection to NOOB early (called when the sign-in page loads), so signing in is quick."""
    try:
        _http.get(f"{NOOB_SOCIAL_URL}/auth/v1/health", headers=_headers(), timeout=(5, 5))
    except Exception:                                   # only a head start; signing in still works without it
        pass


def details_from(me):
    """The person's NOOB signup and profile details, as "About Me" fields for NOOB AI."""
    def text(key):
        value = me.get(key)
        return str(value).strip() if value not in (None, "") else ""

    details = {}
    name = " ".join(part for part in (text("firstName"), text("lastName")) if part) or text("displayName")
    if name:
        details["Name"] = name
    birthday = text("dateOfBirth")[:10]
    if birthday:
        try:
            details["Birthday"] = date.fromisoformat(birthday).strftime("%d %B %Y").lstrip("0")
        except ValueError:
            details["Birthday"] = birthday
    for key, field in (("gender", "Gender"), ("pronouns", "Pronouns"), ("city", "City"), ("email", "Email"),
                       ("website", "Website"), ("bio", "About me")):
        if text(key):
            details[field] = text(key)
    phone = re.sub(r"[^\d]", "", text("mobileNumber"))
    if phone:
        code = re.search(r"\+?(\d{1,4})\)?\s*$", text("countryCode")) if text("countryCode") else None
        details["Phone"] = f"+{code.group(1)} {phone}" if code else phone
    interests = me.get("interests")
    if isinstance(interests, list) and interests:
        details["Hobbies and interests"] = ", ".join(str(i) for i in interests if i)
    if text("username"):
        details["NOOB username"] = "@" + text("username")
    business = [part for part in (text("businessCategory"),
                                  text("businessEmail") and "email " + text("businessEmail"),
                                  text("businessPhone") and "phone " + text("businessPhone"),
                                  text("businessAddress") and "address " + text("businessAddress")) if part]
    if business:
        details["Business"] = "; ".join(business)
    return {k: v[:1000] for k, v in details.items()}


class NoobSocialError(Exception):
    """A message that can be shown to the person signing in."""


# ---------------- NOOB AI maintenance lock ----------------
# The NOOB admin can lock NOOB AI for maintenance (NOOB app → Admin Control Panel → Platform). NOOB AI reads that
# switch from NOOB every 15 seconds in the background, so answering a question never waits for it.
_platform = {"noob_ai_maintenance": False}


def noob_ai_locked():
    return bool(_platform["noob_ai_maintenance"])


def check_platform():
    """Reads the switch once. If NOOB can't be reached, the last known value is kept."""
    try:
        r = _http.post(f"{NOOB_SOCIAL_URL}/rest/v1/rpc/public_platform_settings", headers=_headers(), json={},
                       timeout=(5, 10))
        if r.status_code == 200 and isinstance(r.json(), dict):
            _platform["noob_ai_maintenance"] = bool(r.json().get("noobAiMaintenance"))
    except Exception:
        pass
    return noob_ai_locked()


def watch_platform(log, every=15):
    """Keeps checking the switch in the background and logs when it changes."""
    def loop():
        before = None
        while True:
            now = check_platform()
            if now != before and before is not None:
                log("NOOB AI locked for maintenance by the NOOB admin" if now else "NOOB AI maintenance lock removed")
            before = now
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()


def _headers(token=None):
    headers = {"apikey": NOOB_SOCIAL_KEY, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def verify_login(identifier, password):
    """Returns {"id", "username", "name"} for a correct NOOB login, otherwise raises NoobSocialError."""
    identifier = (identifier or "").strip()
    if not identifier or not password:
        raise NoobSocialError("Enter your NOOB username (or email) and password.")
    try:
        # 1. NOOB accounts log in with a private address; find it from the username or email.
        r = _http.post(f"{NOOB_SOCIAL_URL}/rest/v1/rpc/resolve_login_email", headers=_headers(),
                          json={"identifier": identifier}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
        login_email = r.json()

        # 2. Check the password.
        r = _http.post(f"{NOOB_SOCIAL_URL}/auth/v1/token?grant_type=password", headers=_headers(),
                          json={"email": login_email, "password": password}, timeout=TIMEOUT)
        if r.status_code == 429:
            raise NoobSocialError("Too many attempts. Please wait a moment and try again.")
        if r.status_code != 200:
            details = str(r.json()) if r.headers.get("Content-Type", "").startswith("application/json") else r.text
            if "banned" in details.lower():
                raise NoobSocialError("This NOOB account has been suspended.")
            raise NoobSocialError("Wrong NOOB username/email or password.")
        session = r.json()
        token, user_id = session["access_token"], session["user"]["id"]

        # 3. Read the account's name, then end this one login (other devices stay signed in).
        try:
            r = _http.post(f"{NOOB_SOCIAL_URL}/rest/v1/rpc/get_my_user", headers=_headers(token), json={},
                              timeout=TIMEOUT)
            me = r.json() if r.status_code == 200 and isinstance(r.json(), dict) else {}
        finally:
            try:
                _http.post(f"{NOOB_SOCIAL_URL}/auth/v1/logout?scope=local", headers=_headers(token), timeout=TIMEOUT)
            except requests.RequestException:
                pass
    except (requests.RequestException, ValueError, KeyError, TypeError):      # no internet or an unexpected reply
        raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")

    if me.get("isSuspended"):
        raise NoobSocialError("This NOOB account has been suspended.")
    username = str(me.get("username") or "")
    return {"id": user_id, "username": username, "name": str(me.get("displayName") or username or "NOOB user"),
            "details": details_from(me)}


def verify_token(token):
    """For the "NOOB AI" button inside the NOOB social media app: checks the login token the app handed over.
    Returns {"id", "username", "name"}, otherwise raises NoobSocialError. The token is used once and never saved.
    (No logout here: this token is the person's own NOOB app login.)"""
    token = (token or "").strip()
    if not token or len(token) > 4000:
        raise NoobSocialError("Please sign in.")
    try:
        # Both questions go to NOOB at the same time (half the waiting): is this login real and still
        # signed in, and whose account is it.
        check = _pool.submit(_http.get, f"{NOOB_SOCIAL_URL}/auth/v1/user", headers=_headers(token), timeout=TIMEOUT)
        details = _pool.submit(_http.post, f"{NOOB_SOCIAL_URL}/rest/v1/rpc/get_my_user", headers=_headers(token),
                               json={}, timeout=TIMEOUT)
        r = check.result()
        if r.status_code in (401, 403):
            raise NoobSocialError("Your NOOB login has expired. Please sign in.")
        if r.status_code != 200:
            raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
        user_id = r.json()["id"]
        r = details.result()
        me = r.json() if r.status_code == 200 and isinstance(r.json(), dict) else {}
        if me.get("id") not in (None, user_id):          # never mix up two accounts
            raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
    if me.get("isSuspended"):
        raise NoobSocialError("This NOOB account has been suspended.")
    username = str(me.get("username") or "")
    return {"id": user_id, "username": username, "name": str(me.get("displayName") or username or "NOOB user"),
            "details": details_from(me)}
