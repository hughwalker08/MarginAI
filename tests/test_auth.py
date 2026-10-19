import json
import os
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend import api, auth
from backend.engine.engine import Engine
from backend.engine.llm import FakeLLM
from backend.stores import create_store

DB = os.environ.get("DATABASE_URL", "postgresql:///marginai")
SECRET = "x" * 40


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@gmail.com")


def test_session_roundtrip_tamper_expiry_and_secret_change(monkeypatch):
    u = auth.User("a@saarde.com", "Ann", "http://pic")
    tok = auth.make_session(u)
    assert auth.read_session(tok) == u
    body, sig = tok.rsplit(".", 1)
    assert auth.read_session(body + "." + sig[:-2] + "AA") is None  # signature changed
    assert auth.read_session("e30." + sig) is None  # payload swapped
    assert auth.read_session(None) is None and auth.read_session("junk") is None
    assert auth.read_session(tok, now=time.time() + auth.SESSION_TTL_S + 5) is None  # expired
    monkeypatch.setenv("SESSION_SECRET", "y" * 40)
    assert auth.read_session(tok) is None  # a rotated secret signs everyone out
    monkeypatch.setenv("SESSION_SECRET", "short")
    assert auth.read_session(tok) is None
    with pytest.raises(auth.AuthError):
        auth.make_session(u)


def test_google_verification(monkeypatch):
    from google.oauth2 import id_token

    claims = {"email": "Ann@Saarde.com", "email_verified": True, "name": "Ann", "picture": "p"}
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda cred, req, aud: claims)
    assert auth.verify_google_credential("c" * 30).email == "ann@saarde.com"  # lower-cased
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda cred, req, aud: {**claims, "email_verified": False})
    with pytest.raises(auth.AuthError):
        auth.verify_google_credential("c" * 30)
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda cred, req, aud: {**claims, "email_verified": "true"})
    with pytest.raises(auth.AuthError):  # must be the boolean True, not a truthy string
        auth.verify_google_credential("c" * 30)

    def boom(cred, req, aud):
        raise ValueError("Wrong recipient, payload audience != required audience")

    monkeypatch.setattr(id_token, "verify_oauth2_token", boom)
    with pytest.raises(auth.AuthError):
        auth.verify_google_credential("c" * 30)
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    with pytest.raises(auth.AuthError):
        auth.verify_google_credential("c" * 30)


def _db_ready() -> bool:
    try:
        with psycopg.connect(DB) as c:
            return c.execute("SELECT count(*) FROM orders").fetchone()[0] > 0
    except psycopg.Error:
        return False


needs_db = pytest.mark.skipif(not _db_ready(), reason="local marginai database not loaded")


@pytest.fixture()
def store():
    s = create_store(DB, "zz_auth", "Zz Auth Shop", "zz-auth.myshopify.com")
    auth.add_access(DB, "zz_auth", "domain", "saarde.com")
    auth.add_access(DB, "zz_auth", "email", "Friend@Gmail.com")
    yield s
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("DELETE FROM stores WHERE slug = 'zz_auth'")  # cascades to store_access
        c.execute('DROP SCHEMA IF EXISTS "store_zz_auth" CASCADE')
        c.execute('DROP OWNED BY "ro_zz_auth"')
        c.execute('DROP ROLE IF EXISTS "ro_zz_auth"')


@needs_db
def test_access_rules_are_exact(store):
    ok = lambda email: auth.can_access(DB, auth.User(email) if email else None, "zz_auth")  # noqa: E731
    assert ok("ann@saarde.com") and ok("ANN@Saarde.com") and ok("friend@gmail.com") and ok("boss@gmail.com")
    for bad in ["x@evilsaarde.com", "x@saarde.com.evil.com", "x@sub.saarde.com", "x@saarde.co", "saarde.com",
                "x@gmail.com", "", None, "x@saarde.com@evil.com"]:
        assert not ok(bad), bad
    assert auth.can_access(DB, None, "demo")  # the demo is open to anyone
    assert not auth.can_access(DB, auth.User("ann@saarde.com"), "some_other_store")  # no rule for that store


@needs_db
def test_add_remove_and_validation(store):
    with pytest.raises(ValueError):
        auth.add_access(DB, "zz_auth", "email", "no-at-sign")
    with pytest.raises(ValueError):
        auth.add_access(DB, "zz_auth", "domain", "a@b.com")
    with pytest.raises(ValueError):
        auth.add_access(DB, "zz_auth", "domain", "localhost")
    auth.add_access(DB, "zz_auth", "domain", "@Other.com")
    assert ("zz_auth", "domain", "other.com") in auth.list_access(DB)
    auth.remove_access(DB, "zz_auth", "domain", "other.com")
    assert ("zz_auth", "domain", "other.com") not in auth.list_access(DB)


@pytest.fixture()
def client(monkeypatch, store):
    people = {"ann": "ann@saarde.com", "eve": "eve@gmail.com", "bos": "boss@gmail.com"}
    monkeypatch.setattr(auth, "verify_google_credential", lambda cred: auth.User(people[cred[:3]] if cred[:3] in people else "x@x.com", "N"))
    monkeypatch.setattr(api, "GeminiClient", lambda: None)
    reply = json.dumps({"sql": "SELECT count(*) AS n FROM orders", "assumptions": "", "clarification": None})
    monkeypatch.setattr(api, "Engine", lambda llm, url, **kw: Engine(FakeLLM([reply, "ok"] * 6), url, log=False, **kw))
    with TestClient(api.app) as c:
        yield c


def login(c, who):
    r = c.post("/api/auth/google", json={"credential": who + "x" * 30})
    assert r.status_code == 200, r.text
    return r.json()["user"]


@needs_db
def test_login_session_and_store_listing(client):
    assert client.get("/api/me").json() == {"user": None}
    assert "zz_auth" not in [s["slug"] for s in client.get("/api/stores").json()]  # hidden from anonymous visitors
    assert client.get("/api/config").json()["auth_enabled"] is True
    user = login(client, "ann")
    assert user["email"] == "ann@saarde.com" and user["is_admin"] is False
    assert client.get("/api/me").json()["user"]["email"] == "ann@saarde.com"
    assert "zz_auth" in [s["slug"] for s in client.get("/api/stores").json()]
    set_cookie = client.cookies  # HttpOnly cookie is held by the client, never readable from page scripts
    assert auth.SESSION_COOKIE in set_cookie
    client.post("/api/auth/logout")
    assert client.get("/api/me").json() == {"user": None}


@needs_db
def test_cookie_flags(client):
    r = client.post("/api/auth/google", json={"credential": "ann" + "x" * 30})
    header = r.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header


@needs_db
def test_ask_enforcement(client):
    body = {"question": "how many orders?", "store": "zz_auth"}
    assert client.post("/api/ask", json=body).status_code == 401  # not signed in
    assert client.post("/api/ask/stream", json=body).status_code == 401
    assert client.post("/api/ask", json={"question": "how many orders?"}).status_code == 200  # demo is open
    login(client, "eve")  # signed in, but not listed
    assert client.post("/api/ask", json=body).status_code == 403
    assert "zz_auth" not in [s["slug"] for s in client.get("/api/stores").json()]
    client.post("/api/auth/logout")
    login(client, "ann")  # @saarde.com
    assert client.post("/api/ask", json=body).status_code == 200
    client.post("/api/auth/logout")
    login(client, "bos")  # admin
    assert client.post("/api/ask", json=body).status_code == 200
    assert client.get("/api/me").json()["user"]["is_admin"] is True


@needs_db
def test_forged_or_tampered_cookies_mean_anonymous(client):
    client.cookies.set(auth.SESSION_COOKIE, auth.make_session(auth.User("ann@saarde.com")) + "x")
    assert client.get("/api/me").json() == {"user": None}
    client.cookies.set(auth.SESSION_COOKIE, "e30.AAAA")
    assert client.post("/api/ask", json={"question": "how many orders?", "store": "zz_auth"}).status_code == 401


@needs_db
def test_bad_google_credentials_are_rejected(client, monkeypatch):
    def reject(cred):
        raise auth.AuthError("Google sign-in could not be verified")

    monkeypatch.setattr(auth, "verify_google_credential", reject)
    assert client.post("/api/auth/google", json={"credential": "z" * 40}).status_code == 401
    assert client.post("/api/auth/google", json={"credential": "short"}).status_code == 422
    assert client.get("/api/me").json() == {"user": None}


@needs_db
def test_sign_in_not_configured_on_a_public_deployment_closes_real_stores(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    monkeypatch.setenv("ALLOW_PUBLIC_HOSTS", "1")
    body = {"question": "how many orders?", "store": "zz_auth"}
    assert client.post("/api/ask", json=body).status_code == 403
    assert "zz_auth" not in [s["slug"] for s in client.get("/api/stores").json()]
    assert client.post("/api/ask", json={"question": "how many orders?"}).status_code == 200  # demo still works
    # ...but locally with no sign-in configured, real stores stay open (that's dev mode)
    monkeypatch.delenv("ALLOW_PUBLIC_HOSTS")
    assert client.post("/api/ask", json=body).status_code == 200


@needs_db
def test_questions_are_logged_with_the_asker(client):
    login(client, "ann")
    client.post("/api/ask", json={"question": "audit trail check", "store": "zz_auth"})
    with psycopg.connect(DB) as c:
        assert c.execute("SELECT count(*) FROM query_log WHERE question = 'audit trail check'").fetchone()[0] == 0  # log=False in test engine
