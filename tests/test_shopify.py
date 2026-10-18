import hashlib
import hmac as hmaclib
import os
import time
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import api
from backend.engine.executor import run_readonly
from backend.shopify import crypto, oauth, vault
from backend.stores import DEMO, create_store, get_store

DB = os.environ.get("DATABASE_URL", "postgresql:///marginai")
SECRET = "shh-its-a-secret"


def signed(params: dict) -> dict:
    msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return {**params, "hmac": hmaclib.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()}


def test_shop_domain_validation_is_anchored():
    assert oauth.valid_shop("Saarde.myshopify.com") == "saarde.myshopify.com"
    for bad in ["evil.com/x.myshopify.com", "saarde.myshopify.com.evil.com", "saarde.com", "", None,
                "a b.myshopify.com", "http://saarde.myshopify.com", "-x.myshopify.com"]:
        with pytest.raises(oauth.OAuthError):
            oauth.valid_shop(bad)


def test_hmac_verification():
    p = signed({"shop": "saarde.myshopify.com", "code": "abc", "timestamp": "1", "state": "s"})
    assert oauth.verify_hmac(p, SECRET)
    assert not oauth.verify_hmac({**p, "code": "tampered"}, SECRET)
    assert not oauth.verify_hmac(p, "wrong-secret")
    assert not oauth.verify_hmac({k: v for k, v in p.items() if k != "hmac"}, SECRET)


def test_state_roundtrip_expiry_and_cookie_binding():
    nonce, state = oauth.make_state(SECRET)
    oauth.check_state(state, nonce, SECRET)
    with pytest.raises(oauth.OAuthError):
        oauth.check_state(state, "other-browser", SECRET)
    with pytest.raises(oauth.OAuthError):
        oauth.check_state(state, None, SECRET)
    with pytest.raises(oauth.OAuthError):
        oauth.check_state(state[:-1] + "0", nonce, SECRET)
    old_nonce, old_state = oauth.make_state(SECRET, now=time.time() - 3600)
    with pytest.raises(oauth.OAuthError):
        oauth.check_state(old_state, old_nonce, SECRET)


def test_missing_scopes():
    assert oauth.missing_scopes("read_orders,read_products", "read_orders,read_products") == []
    assert oauth.missing_scopes("read_orders,read_products", "read_orders") == ["read_products"]
    assert oauth.missing_scopes("read_orders", "write_orders") == []  # write implies read


def test_token_encryption_roundtrip(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    enc = crypto.encrypt("shpat_secret")
    assert "shpat_secret" not in enc and crypto.decrypt(enc) == "shpat_secret"
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        crypto.decrypt(enc)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    with pytest.raises(crypto.TokenKeyMissing):
        crypto.encrypt("x")


def _db_ready() -> bool:
    try:
        with psycopg.connect(DB) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


needs_db = pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")


@pytest.fixture()
def test_store():
    store = create_store(DB, "zz_test", "Test Store", "zz-test.myshopify.com")
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute('INSERT INTO "store_zz_test".locations VALUES (1, \'Only Shop\', \'pos\')')
    yield store
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("DELETE FROM stores WHERE slug = 'zz_test'")
        c.execute('DROP SCHEMA IF EXISTS "store_zz_test" CASCADE')
        c.execute('DROP OWNED BY "ro_zz_test"')
        c.execute('DROP ROLE IF EXISTS "ro_zz_test"')


@needs_db
def test_store_role_sees_only_its_own_schema(test_store):
    own = run_readonly(DB, "SELECT name FROM locations", role=test_store.role, schema=test_store.schema)
    assert own.rows == [["Only Shop"]]
    # The same table name resolves to different data per store.
    demo = run_readonly(DB, "SELECT count(*) FROM locations")
    assert demo.rows == [[3]]
    for sql in ["SELECT count(*) FROM public.orders", "SELECT * FROM public.stores",
                "SELECT * FROM public.shopify_tokens", "SELECT * FROM public.query_log"]:
        with pytest.raises(psycopg.Error):
            run_readonly(DB, sql, role=test_store.role, schema=test_store.schema)
    with pytest.raises(psycopg.Error):  # the demo role cannot read another store's schema either
        run_readonly(DB, 'SELECT * FROM "store_zz_test".locations')
    with pytest.raises(psycopg.Error):
        run_readonly(DB, "UPDATE locations SET name = 'x'", role=test_store.role, schema=test_store.schema)


@needs_db
def test_executor_rejects_unsafe_identifiers():
    for kwargs in [{"schema": 'public"; DROP TABLE orders; --'}, {"role": "x; y"}, {"timezone": "UTC'; --"}]:
        with pytest.raises(ValueError):
            run_readonly(DB, "SELECT 1", **kwargs)


@needs_db
def test_create_store_is_idempotent_and_rejects_bad_slugs(test_store):
    again = create_store(DB, "zz_test", "Renamed", "zz-test.myshopify.com")
    assert again.name == "Renamed" and get_store(DB, "zz_test").schema == "store_zz_test"
    for bad in ["demo", "Bad", "a", "x" * 40, "1abc", "a-b-c"]:
        with pytest.raises(ValueError):
            create_store(DB, bad, "n")
    assert get_store(DB, "demo") == DEMO and get_store(DB, "nope_nope") is None


@needs_db
def test_vault_roundtrip_and_refresh(test_store, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret")
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    vault.save_tokens(DB, "zz_test", oauth.TokenSet("access-1", "read_orders", soon, "refresh-1", soon))
    assert vault.get_access_token(DB, "zz_test", "zz-test.myshopify.com") == "access-1"
    with psycopg.connect(DB) as c:  # nothing readable in the table
        raw = c.execute("SELECT access_token_enc FROM shopify_tokens WHERE store_slug = 'zz_test'").fetchone()[0]
    assert "access-1" not in raw
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    vault.save_tokens(DB, "zz_test", oauth.TokenSet("old", "read_orders", expired, "refresh-1", soon))
    monkeypatch.setattr(oauth, "refresh_tokens", lambda shop, cid, sec, rt: oauth.TokenSet(
        "access-2", "read_orders", soon, "refresh-2", soon))
    assert vault.get_access_token(DB, "zz_test", "zz-test.myshopify.com") == "access-2"
    assert vault.get_access_token(DB, "zz_test", "zz-test.myshopify.com") == "access-2"  # persisted


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("SHOPIFY_ALLOWED_SHOPS", "saarde.myshopify.com")
    monkeypatch.setenv("APP_BASE_URL", "https://abc.trycloudflare.com")
    monkeypatch.setattr(api, "GeminiClient", lambda: None)
    monkeypatch.setattr(api, "Engine", lambda llm, url, **kw: object())
    with TestClient(api.app, follow_redirects=False) as c:
        yield c


@needs_db
def test_install_redirects_to_shopify_with_state_cookie(client):
    r = client.get("/api/shopify/install", params={"shop": "saarde.myshopify.com"})
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("https://saarde.myshopify.com/admin/oauth/authorize?")
    assert "client_id=client-id" in loc and "redirect_uri=https%3A%2F%2Fabc.trycloudflare.com%2Fapi%2Fshopify%2Fcallback" in loc
    assert "shopify_oauth_state=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


@needs_db
def test_install_rejects_unlisted_or_malformed_shops_and_bad_signature(client):
    assert client.get("/api/shopify/install", params={"shop": "other.myshopify.com"}).status_code == 400
    assert client.get("/api/shopify/install", params={"shop": "evil.com"}).status_code == 400
    assert client.get("/api/shopify/install", params={"shop": "saarde.myshopify.com", "hmac": "bad"}).status_code == 400
    good = signed({"shop": "saarde.myshopify.com", "timestamp": "1"})
    assert client.get("/api/shopify/install", params=good).status_code in (302, 307)


@needs_db
def test_callback_rejects_bad_hmac_state_and_unlisted_shop(client):
    p = signed({"shop": "saarde.myshopify.com", "code": "c", "state": "bad", "timestamp": "1"})
    assert client.get("/api/shopify/callback", params={**p, "hmac": "0" * 64}).status_code == 400  # bad signature
    assert client.get("/api/shopify/callback", params=p).status_code == 400  # state/cookie mismatch
    other = signed({"shop": "other.myshopify.com", "code": "c", "state": "s", "timestamp": "1"})
    assert client.get("/api/shopify/callback", params=other).status_code == 400


@needs_db
def test_tunnel_requests_only_reach_the_install_endpoints(client):
    tunnel = {"host": "abc.trycloudflare.com"}
    assert client.get("/api/health", headers=tunnel).status_code == 404
    assert client.post("/api/ask", headers=tunnel, json={"question": "revenue?"}).status_code == 404
    assert client.get("/api/stores", headers=tunnel).status_code == 404
    assert client.get("/api/shopify/install", headers=tunnel, params={"shop": "saarde.myshopify.com"}).status_code in (302, 307)
    assert client.get("/api/stores").status_code == 200  # localhost is unaffected


@needs_db
def test_public_demo_mode_hides_real_stores(client, monkeypatch, test_store):
    assert {s["slug"] for s in client.get("/api/stores").json()} >= {"demo", "zz_test"}
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    assert [s["slug"] for s in client.get("/api/stores").json()] == ["demo"]
    r = client.post("/api/ask", json={"question": "revenue?", "store": "zz_test"})
    assert r.status_code == 404


@needs_db
def test_client_credentials_connect_and_automatic_renewal(monkeypatch):
    from backend.shopify import connect as connect_mod

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    issued = []

    def fake_token(shop, cid, secret):
        issued.append((shop, cid, secret))
        life = timedelta(hours=24) if len(issued) == 1 else timedelta(hours=24)
        return oauth.TokenSet(f"tok-{len(issued)}", "read_orders", datetime.now(timezone.utc) + life, None, None)

    def fake_graphql(shop, token, query, variables=None):
        if "currentAppInstallation" in query:
            return {"currentAppInstallation": {"accessScopes": [{"handle": "read_orders"}]}}
        return {"shop": {"name": "Zz Shop", "currencyCode": "AUD", "ianaTimezone": "Australia/Sydney"}}

    monkeypatch.setattr(oauth, "client_credentials_token", fake_token)
    monkeypatch.setattr(oauth, "graphql", fake_graphql)
    try:
        name, scopes = connect_mod.connect(DB, "zz-shop.myshopify.com", "zz_shop", "cid", "csecret")
        assert name == "Zz Shop" and scopes == ["read_orders"]
        assert vault.get_access_token(DB, "zz_shop", "zz-shop.myshopify.com") == "tok-1"
        with psycopg.connect(DB) as c:
            row = c.execute("SELECT grant_type, client_id, client_secret_enc FROM shopify_tokens "
                            "WHERE store_slug = 'zz_shop'").fetchone()
        assert row[0] == "client_credentials" and row[1] == "cid" and "csecret" not in row[2]
        with psycopg.connect(DB, autocommit=True) as c:  # make the stored token look expired
            c.execute("UPDATE shopify_tokens SET expires_at = now() - interval '1 minute' WHERE store_slug = 'zz_shop'")
        assert vault.get_access_token(DB, "zz_shop", "zz-shop.myshopify.com") == "tok-2"
        assert issued[-1] == ("zz-shop.myshopify.com", "cid", "csecret")  # renewed with the stored credentials
    finally:
        with psycopg.connect(DB, autocommit=True) as c:
            c.execute("DELETE FROM stores WHERE slug = 'zz_shop'")
            c.execute('DROP SCHEMA IF EXISTS "store_zz_shop" CASCADE')
            c.execute('DROP OWNED BY "ro_zz_shop"')
            c.execute('DROP ROLE IF EXISTS "ro_zz_shop"')
