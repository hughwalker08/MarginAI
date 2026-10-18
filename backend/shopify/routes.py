"""Shopify connection endpoints: install, OAuth callback."""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..stores import create_store
from . import oauth, vault

router = APIRouter(prefix="/api/shopify")
COOKIE = "shopify_oauth_state"


def _cfg():
    try:
        return os.environ["SHOPIFY_CLIENT_ID"], os.environ["SHOPIFY_CLIENT_SECRET"]
    except KeyError as e:
        raise oauth.OAuthError(f"{e.args[0]} is not set in .env") from e


def _allowed_shops() -> set[str]:
    return {s.strip().lower() for s in os.environ.get("SHOPIFY_ALLOWED_SHOPS", "").split(",") if s.strip()}


def _page(title: str, message: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{title}</title>"
                        f"<body style='font:16px system-ui;max-width:560px;margin:15vh auto;padding:0 20px'>"
                        f"<h2>{title}</h2><p>{message}</p>", status_code=status)


def _base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


@router.get("/install")
def install(request: Request, shop: str | None = None):
    """App URL: Shopify (or an install link) sends the merchant here; we send them on to Shopify's permission screen."""
    try:
        client_id, secret = _cfg()
        shop = oauth.valid_shop(shop)
        if shop not in _allowed_shops():
            raise oauth.OAuthError("This store is not on the allowed list (SHOPIFY_ALLOWED_SHOPS)")
        params = dict(request.query_params)
        if "hmac" in params and not oauth.verify_hmac(params, secret):
            raise oauth.OAuthError("Invalid request signature")
    except oauth.OAuthError as e:
        return _page("Can't start the install", str(e))
    nonce, state = oauth.make_state(secret)
    scopes = os.environ.get("SHOPIFY_SCOPES", oauth.DEFAULT_SCOPES)
    resp = RedirectResponse(oauth.authorize_url(shop, client_id, scopes, f"{_base_url()}/api/shopify/callback", state))
    resp.set_cookie(COOKIE, nonce, max_age=oauth.STATE_MAX_AGE_S, httponly=True, samesite="lax",
                    secure=_base_url().startswith("https://"))
    return resp


@router.get("/callback")
def callback(request: Request):
    from ..api import DATABASE_URL  # late import: api.py includes this router

    params = dict(request.query_params)
    try:
        client_id, secret = _cfg()
        if not oauth.verify_hmac(params, secret):
            raise oauth.OAuthError("Invalid request signature")
        shop = oauth.valid_shop(params.get("shop"))
        if shop not in _allowed_shops():
            raise oauth.OAuthError("This store is not on the allowed list (SHOPIFY_ALLOWED_SHOPS)")
        oauth.check_state(params.get("state", ""), request.cookies.get(COOKIE), secret)
        if not params.get("code"):
            raise oauth.OAuthError("Missing authorization code")
        tokens = oauth.exchange_code(shop, client_id, secret, params["code"])
        wanted = os.environ.get("SHOPIFY_SCOPES", oauth.DEFAULT_SCOPES)
        missing = oauth.missing_scopes(wanted, tokens.scope)
        if missing:
            raise oauth.OAuthError("The install did not grant: " + ", ".join(missing))
        info = oauth.graphql(shop, tokens.access_token,
                             "{ shop { name currencyCode ianaTimezone } }")["shop"]
        slug = re.sub(r"[^a-z0-9]+", "_", shop.removesuffix(".myshopify.com")).strip("_")[:29] or "store"
        if not slug[0].isalpha():
            slug = "s" + slug
        store = create_store(DATABASE_URL, slug.ljust(3, "_"), info["name"], shop, info["ianaTimezone"],
                             info["currencyCode"])
        vault.save_tokens(DATABASE_URL, store.slug, tokens)
    except oauth.OAuthError as e:
        return _page("Connection failed", str(e))
    except Exception:  # never show internals to whoever completed the install
        return _page("Connection failed", "Something went wrong on our side. Nothing was connected.", 500)
    resp = _page("Connected", f"{store.name} is connected. You can close this tab.", 200)
    resp.delete_cookie(COOKIE)
    return resp
