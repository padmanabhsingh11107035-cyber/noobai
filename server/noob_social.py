"""
"Continue with NOOB": sign in to the NOOB AI Assistant with a NOOB social media account (nooob.xyz).

It checks the username/email and password with NOOB's own login service (the same one the
nooob.xyz website uses), reads the account's signup details (name, birthday, phone, email, city...), and ends that login
straight away. The NOOB password is never saved or logged by the assistant.
"""

import re
from datetime import date

import requests

NOOB_SOCIAL_URL = "https://abffssydapumuhwgzeck.supabase.co"
# The website's public "publishable" key: safe to share, it can only do what NOOB's security rules allow.
NOOB_SOCIAL_KEY = "sb_publishable_g20GG46EXeMr1jcNwVJtmw_rAZKsuA3"
TIMEOUT = 15


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
        r = requests.post(f"{NOOB_SOCIAL_URL}/rest/v1/rpc/resolve_login_email", headers=_headers(),
                          json={"identifier": identifier}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
        login_email = r.json()

        # 2. Check the password.
        r = requests.post(f"{NOOB_SOCIAL_URL}/auth/v1/token?grant_type=password", headers=_headers(),
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
            r = requests.post(f"{NOOB_SOCIAL_URL}/rest/v1/rpc/get_my_user", headers=_headers(token), json={},
                              timeout=TIMEOUT)
            me = r.json() if r.status_code == 200 and isinstance(r.json(), dict) else {}
        finally:
            try:
                requests.post(f"{NOOB_SOCIAL_URL}/auth/v1/logout?scope=local", headers=_headers(token), timeout=TIMEOUT)
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
        r = requests.get(f"{NOOB_SOCIAL_URL}/auth/v1/user", headers=_headers(token), timeout=TIMEOUT)
        if r.status_code in (401, 403):
            raise NoobSocialError("Your NOOB login has expired. Please sign in.")
        if r.status_code != 200:
            raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
        user_id = r.json()["id"]
        r = requests.post(f"{NOOB_SOCIAL_URL}/rest/v1/rpc/get_my_user", headers=_headers(token), json={}, timeout=TIMEOUT)
        me = r.json() if r.status_code == 200 and isinstance(r.json(), dict) else {}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise NoobSocialError("Could not reach NOOB right now. Check the internet and try again.")
    if me.get("isSuspended"):
        raise NoobSocialError("This NOOB account has been suspended.")
    username = str(me.get("username") or "")
    return {"id": user_id, "username": username, "name": str(me.get("displayName") or username or "NOOB user"),
            "details": details_from(me)}
