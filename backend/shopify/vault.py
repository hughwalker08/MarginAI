"""Store and retrieve a store's Shopify tokens (encrypted), refreshing the access token when it is close to expiry."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg

from . import crypto, oauth


def save_tokens(database_url: str, slug: str, t: oauth.TokenSet) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO shopify_tokens (store_slug, access_token_enc, refresh_token_enc, expires_at, "
            "refresh_expires_at, scope, updated_at) VALUES (%s,%s,%s,%s,%s,%s, now()) "
            "ON CONFLICT (store_slug) DO UPDATE SET access_token_enc = EXCLUDED.access_token_enc, "
            "refresh_token_enc = EXCLUDED.refresh_token_enc, expires_at = EXCLUDED.expires_at, "
            "refresh_expires_at = EXCLUDED.refresh_expires_at, scope = EXCLUDED.scope, updated_at = now()",
            (slug, crypto.encrypt(t.access_token), crypto.encrypt(t.refresh_token) if t.refresh_token else None,
             t.expires_at, t.refresh_expires_at, t.scope))


def get_access_token(database_url: str, slug: str, shop_domain: str) -> str:
    """A valid access token for the store, refreshed first if it expires within a minute."""
    with psycopg.connect(database_url) as conn:
        row = conn.execute("SELECT access_token_enc, refresh_token_enc, expires_at FROM shopify_tokens "
                           "WHERE store_slug = %s", (slug,)).fetchone()
    if not row:
        raise oauth.OAuthError(f"Store {slug!r} is not connected")
    access, refresh, expires_at = crypto.decrypt(row[0]), row[1] and crypto.decrypt(row[1]), row[2]
    if expires_at and expires_at - datetime.now(timezone.utc) < timedelta(seconds=60):
        if not refresh:
            raise oauth.OAuthError("Access token expired and no refresh token is stored: reconnect the store")
        fresh = oauth.refresh_tokens(shop_domain, os.environ["SHOPIFY_CLIENT_ID"],
                                     os.environ["SHOPIFY_CLIENT_SECRET"], refresh)
        save_tokens(database_url, slug, fresh)
        return fresh.access_token
    return access
