"""Shopify OAuth (authorization code grant) helpers. Pure functions where possible so they are easy to test.

Flow: Shopify sends the merchant to our App URL (/api/shopify/install?shop=...), we redirect them to
Shopify's authorize page, Shopify redirects back to /api/shopify/callback?code&hmac&shop&state&timestamp,
we verify everything and exchange the code for an expiring offline token (+ refresh token).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

# Anchored on both ends: an unanchored pattern would let "evil.com/x.myshopify.com" receive the auth code.
SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$")
STATE_MAX_AGE_S = 600
DEFAULT_SCOPES = ("read_orders,read_all_orders,read_products,read_customers,read_inventory,"
                  "read_locations,read_discounts")
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-07")


class OAuthError(ValueError):
    pass


@dataclass
class TokenSet:
    access_token: str
    scope: str
    expires_at: datetime | None
    refresh_token: str | None
    refresh_expires_at: datetime | None


def valid_shop(shop: str | None) -> str:
    shop = (shop or "").strip().lower()
    if not SHOP_RE.match(shop):
        raise OAuthError("Invalid shop domain (expected something.myshopify.com)")
    return shop


def verify_hmac(params: dict[str, str], secret: str) -> bool:
    """Shopify signs the query string: drop `hmac`, sort the rest, HMAC-SHA256 with the client secret."""
    given = params.get("hmac", "")
    message = "&".join(f"{k}={v}" for k, v in sorted((k, v) for k, v in params.items() if k != "hmac"))
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, given)


def make_state(secret: str, nonce: str | None = None, now: float | None = None) -> tuple[str, str]:
    """Return (nonce, state). `state` carries the nonce, a timestamp and a signature; the nonce is also set
    in a cookie, so the callback only accepts a state that this browser started."""
    nonce = nonce or secrets.token_urlsafe(16)
    ts = str(int(now if now is not None else time.time()))
    sig = hmac.new(secret.encode(), f"{nonce}.{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    return nonce, f"{nonce}.{ts}.{sig}"


def check_state(state: str, cookie_nonce: str | None, secret: str, now: float | None = None) -> None:
    try:
        nonce, ts, sig = state.split(".")
    except ValueError as e:
        raise OAuthError("Malformed state") from e
    expected = hmac.new(secret.encode(), f"{nonce}.{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expected, sig):
        raise OAuthError("State signature mismatch")
    if not cookie_nonce or not hmac.compare_digest(cookie_nonce, nonce):
        raise OAuthError("State does not match this browser session")
    if (now if now is not None else time.time()) - int(ts) > STATE_MAX_AGE_S:
        raise OAuthError("State expired; start the install again")


def authorize_url(shop: str, client_id: str, scopes: str, redirect_uri: str, state: str) -> str:
    q = urlencode({"client_id": client_id, "scope": scopes, "redirect_uri": redirect_uri, "state": state})
    return f"https://{shop}/admin/oauth/authorize?{q}"


def _token_set(body: dict, now: datetime | None = None) -> TokenSet:
    now = now or datetime.now(timezone.utc)
    exp = body.get("expires_in")
    rexp = body.get("refresh_token_expires_in")
    return TokenSet(
        access_token=body["access_token"], scope=body.get("scope", ""),
        expires_at=now + timedelta(seconds=int(exp)) if exp else None,
        refresh_token=body.get("refresh_token"),
        refresh_expires_at=now + timedelta(seconds=int(rexp)) if rexp else None)


def exchange_code(shop: str, client_id: str, client_secret: str, code: str) -> TokenSet:
    r = httpx.post(f"https://{shop}/admin/oauth/access_token", timeout=20, data={
        "client_id": client_id, "client_secret": client_secret, "code": code, "expiring": "1"})
    if r.status_code != 200:
        raise OAuthError(f"Token exchange failed ({r.status_code})")
    return _token_set(r.json())


def refresh_tokens(shop: str, client_id: str, client_secret: str, refresh_token: str) -> TokenSet:
    r = httpx.post(f"https://{shop}/admin/oauth/access_token", timeout=20, data={
        "client_id": client_id, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": refresh_token})
    if r.status_code == 401:
        raise OAuthError("Refresh token rejected: the store must be reconnected")
    if r.status_code != 200:
        raise OAuthError(f"Token refresh failed ({r.status_code})")
    return _token_set(r.json())


def missing_scopes(requested: str, granted: str) -> list[str]:
    """A write_* scope also grants the matching read_*; merchants can also strip scopes at install."""
    have = set(granted.replace(" ", "").split(","))
    have |= {s.replace("write_", "read_", 1) for s in have if s.startswith("write_")}
    return [s for s in requested.replace(" ", "").split(",") if s and s not in have]


def graphql(shop: str, access_token: str, query: str, variables: dict | None = None) -> dict:
    r = httpx.post(f"https://{shop}/admin/api/{API_VERSION}/graphql.json", timeout=60,
                   headers={"X-Shopify-Access-Token": access_token},
                   json={"query": query, "variables": variables or {}})
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise OAuthError(f"GraphQL error: {str(body['errors'])[:300]}")
    return body["data"]
