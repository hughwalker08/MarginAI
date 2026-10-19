"""Sign in with Google, a signed session cookie, and per-store access rules.

Flow: the browser gets a Google ID token (the "Sign in with Google" button), posts it to /api/auth/google, we verify it
with Google's public keys (signature, expiry, audience = our client id) and require a verified email. We then set our
own signed, HttpOnly session cookie. Access to a store is decided from the verified email alone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

import psycopg

SESSION_COOKIE = "marginai_session"
SESSION_TTL_S = 7 * 24 * 3600
DEMO_SLUG = "demo"


class AuthError(ValueError):
    pass


@dataclass(frozen=True)
class User:
    email: str
    name: str = ""
    picture: str = ""


def google_client_id() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_ID") or None


def auth_enabled() -> bool:
    return google_client_id() is not None


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def _secret() -> bytes:
    s = os.environ.get("SESSION_SECRET")
    if not s or len(s) < 32:
        raise AuthError("SESSION_SECRET is missing or too short (use at least 32 random characters)")
    return s.encode()


# ---------------------------------------------------------------- Google

def verify_google_credential(credential: str) -> User:
    """Check a Google ID token and return who it belongs to. Raises AuthError if it can't be trusted."""
    client_id = google_client_id()
    if not client_id:
        raise AuthError("Google sign-in is not configured")
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(credential, g_requests.Request(), client_id)
    except Exception as e:  # bad signature, expired, wrong audience, wrong issuer...
        raise AuthError("Google sign-in could not be verified") from e
    email = (claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is not True:
        raise AuthError("Your Google email is not verified")
    return User(email=email, name=claims.get("name") or "", picture=claims.get("picture") or "")


# --------------------------------------------------------------- sessions

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(user: User, now: float | None = None) -> str:
    payload = {"e": user.email, "n": user.name, "p": user.picture,
               "x": int((now if now is not None else time.time()) + SESSION_TTL_S)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_session(token: str | None, now: float | None = None) -> User | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(_b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest()), sig):
            return None
        payload = json.loads(_unb64(body))
        if payload["x"] < (now if now is not None else time.time()):
            return None
        return User(email=payload["e"], name=payload.get("n", ""), picture=payload.get("p", ""))
    except (AuthError, ValueError, KeyError, TypeError):
        return None


# ----------------------------------------------------------------- access

def can_access(database_url: str, user: User | None, store_slug: str) -> bool:
    """The demo is open to all. A real store needs a signed-in user who is an admin or is listed for that store."""
    if store_slug == DEMO_SLUG:
        return True
    if user is None:
        return False
    email = user.email.lower()
    if email in admin_emails():
        return True
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1]  # exact match: "saarde.com" does not admit "x.saarde.com" or "evilsaarde.com"
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM store_access WHERE store_slug = %s AND "
            "((kind = 'email' AND value = %s) OR (kind = 'domain' AND value = %s)) LIMIT 1",
            (store_slug, email, domain)).fetchone()
    return row is not None


def add_access(database_url: str, store_slug: str, kind: str, value: str) -> None:
    value = value.strip().lower().lstrip("@")
    if kind == "email" and "@" not in value:
        raise ValueError("an email address needs an @")
    if kind == "domain" and ("@" in value or "." not in value):
        raise ValueError("a domain looks like saarde.com")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("INSERT INTO store_access (store_slug, kind, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                     (store_slug, kind, value))


def remove_access(database_url: str, store_slug: str, kind: str, value: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM store_access WHERE store_slug = %s AND kind = %s AND value = %s",
                     (store_slug, kind, value.strip().lower().lstrip("@")))


def list_access(database_url: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(database_url) as conn:
        return conn.execute("SELECT store_slug, kind, value FROM store_access ORDER BY 1, 2, 3").fetchall()
