"""FastAPI app. Run locally:  uvicorn backend.api:app --reload --port 8000"""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import auth
from .engine.engine import Engine
from .engine.llm import GeminiClient
from .engine.memory import MEMORY_TURNS, HistoryTurn
from .shopify.routes import router as shopify_router
from .shopify.scheduler import SyncScheduler
from .stores import DEMO, get_store, list_stores

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///marginai")

EXAMPLES = [
    {"group": "Sales", "question": "What sold best last weekend?"},
    {"group": "Sales", "question": "What was our revenue in each month?"},
    {"group": "Sales", "question": "How did discounts affect revenue in September?"},
    {"group": "Products", "question": "What are our top 5 products by gross profit?"},
    {"group": "Products", "question": "What is the best-selling product in each product type?"},
    {"group": "Customers", "question": "How many customers have placed 3 or more orders?"},
    {"group": "Trends", "question": "How have sales of the cotton blue dress shirt changed over the last 3 months?"},
    {"group": "Operations", "question": "What is the most common reason for refunds?"},
]


class HistoryItem(BaseModel):
    """A finished earlier turn, as recorded by the browser (the server keeps no session state)."""
    question: str = Field(max_length=500)
    answer: str = Field(default="", max_length=2000)
    sql: str | None = Field(default=None, max_length=4000)
    assumptions: str = Field(default="", max_length=1000)
    clarification: str | None = Field(default=None, max_length=1000)
    columns: list[str] = Field(default_factory=list, max_length=30)
    rows: list[list] = Field(default_factory=list, max_length=10)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    store: str = Field(default="demo", pattern=r"^[a-z][a-z0-9_]{2,29}$")
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)

    def turns(self) -> list[HistoryTurn]:
        return [HistoryTurn(**h.model_dump()) for h in self.history]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.llm = GeminiClient()
    app.state.engine = Engine(app.state.llm, DATABASE_URL)  # demo store; builds its context once
    app.state.engines = {DEMO.slug: app.state.engine}
    scheduler = None
    interval = float(os.environ.get("SYNC_INTERVAL_MINUTES") or 0)
    if interval > 0 and os.environ.get("PUBLIC_DEMO") != "1":
        scheduler = SyncScheduler(DATABASE_URL, interval)
        scheduler.start()
    yield
    if scheduler:
        scheduler.stop()


app = FastAPI(title="MarginAI", lifespan=lifespan)
app.include_router(shopify_router)

# Served from a tunnel (so a store owner can finish installing the app) the API is reachable by anyone with the
# link. Requests that don't arrive on localhost may therefore only reach the two Shopify install endpoints.
PUBLIC_PATHS = ("/api/shopify/install", "/api/shopify/callback")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "testserver", "[::1]"}


@app.middleware("http")
async def local_only_except_install(request, call_next):
    if os.environ.get("ALLOW_PUBLIC_HOSTS") == "1":  # a real deployment serves the public; the tunnel guard is for local use
        return await call_next(request)
    host = request.headers.get("host", "").rsplit(":", 1)[0] if not request.headers.get("host", "").startswith("[") \
        else "[::1]"
    if host not in LOCAL_HOSTS and request.url.path not in PUBLIC_PATHS:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)


def viewer(request: Request) -> auth.User | None:
    return auth.read_session(request.cookies.get(auth.SESSION_COOKIE))


def check_store(request: Request, slug: str) -> auth.User | None:
    """Raise 401/403 unless this visitor may query the store. The demo is open; real stores need a listed Google user.
    With sign-in not configured, real stores are open to localhost only (and closed on a public deployment)."""
    user = viewer(request)
    if slug == DEMO.slug:
        return user
    if not auth.auth_enabled():
        if os.environ.get("ALLOW_PUBLIC_HOSTS") == "1":
            raise HTTPException(403, "Real stores need sign-in to be configured")
        return user
    if user is None:
        raise HTTPException(401, "Sign in to use this store")
    if not auth.can_access(DATABASE_URL, user, slug):
        raise HTTPException(403, "Your account doesn't have access to this store")
    return user


CONTEXT_TTL_SECONDS = float(os.environ.get("CONTEXT_TTL_SECONDS", 600))


def engine_for(slug: str) -> Engine:
    """The engine for a store, built on first use. With PUBLIC_DEMO=1 only the synthetic demo store exists."""
    if os.environ.get("PUBLIC_DEMO") == "1" and slug != DEMO.slug:
        raise HTTPException(404, "Unknown store")
    engines = app.state.engines
    if slug not in engines:
        store = get_store(DATABASE_URL, slug)
        if store is None:
            raise HTTPException(404, "Unknown store")
        engines[slug] = Engine(app.state.llm, DATABASE_URL, store=store)
    engine = engines[slug]
    # A live store's prompt holds today's date, its catalogue and its codes, so rebuild it now and then.
    if engine.store.live and time.monotonic() - engine.context_built_at > CONTEXT_TTL_SECONDS:
        engine.refresh_context()
    return engine


@app.get("/api/health")
def health():
    with psycopg.connect(DATABASE_URL) as conn:
        orders = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    return {"status": "ok", "model": app.state.engine.llm.model, "orders": orders,
            "data_as_of": app.state.engine.as_of, "memory_turns": MEMORY_TURNS}


@app.get("/api/config")
def config():
    return {"google_client_id": auth.google_client_id(), "auth_enabled": auth.auth_enabled()}


def _user_json(user: auth.User | None):
    if user is None:
        return {"user": None}
    return {"user": {"email": user.email, "name": user.name, "picture": user.picture,
                     "is_admin": user.email in auth.admin_emails()}}


@app.get("/api/me")
def me(request: Request):
    return _user_json(viewer(request))


class GoogleLogin(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)


@app.post("/api/auth/google")
def login_google(body: GoogleLogin, request: Request, response: Response):
    try:
        user = auth.verify_google_credential(body.credential)
        token = auth.make_session(user)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from e
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_TTL_S, httponly=True, samesite="lax",
                        secure=secure, path="/")
    return _user_json(user)


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"user": None}


@app.get("/api/stores")
def stores(request: Request):
    user = viewer(request)
    out = []
    for st in list_stores(DATABASE_URL, include_real=os.environ.get("PUBLIC_DEMO") != "1"):
        if st.slug != DEMO.slug:
            if auth.auth_enabled():
                if not auth.can_access(DATABASE_URL, user, st.slug):
                    continue  # a store you can't open isn't even listed
            elif os.environ.get("ALLOW_PUBLIC_HOSTS") == "1":
                continue
        out.append({"slug": st.slug, "name": st.name, "currency": st.currency, "demo": st.slug == DEMO.slug,
                    "last_synced_at": st.last_synced_at.isoformat() if st.last_synced_at else None})
    return out


GENERIC_EXAMPLES = [
    {"group": "Sales", "question": "What were our sales last month?"},
    {"group": "Sales", "question": "How are sales trending over the last 3 months?"},
    {"group": "Products", "question": "What are our top 10 products by revenue this year?"},
    {"group": "Channels", "question": "How do online and in-store sales compare?"},
    {"group": "Locations", "question": "Which of our locations sells the most?"},
    {"group": "Timing", "question": "Which day of the week is busiest?"},
    {"group": "Discounts", "question": "How much have discounts cost us this year?"},
    {"group": "Operations", "question": "What is our refund rate by month?"},
]


@app.get("/api/examples")
def examples(store: str = "demo"):
    return EXAMPLES if store == DEMO.slug else GENERIC_EXAMPLES


@app.post("/api/ask")
def ask(req: AskRequest, request: Request):
    """Sync endpoint on purpose: the engine blocks on the LLM, so FastAPI runs it in a worker thread."""
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")
    user = check_store(request, req.store)
    return engine_for(req.store).ask(question, history=req.turns(), user_email=user.email if user else None).to_dict()


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest, request: Request):
    """Newline-delimited JSON events: `result` as soon as the query has run (rows, chart, SQL; the
    answer text may still be empty), `delta` chunks of the written answer, then `done` with metrics."""
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Question is empty")
    user = check_store(request, req.store)
    engine = engine_for(req.store)
    history = req.turns()
    user_email = user.email if user else None

    def events():
        for event, payload in engine.ask_stream(question, history=history, user_email=user_email):
            if event == "delta":
                body = {"type": "delta", "text": payload}
            elif event == "result":
                body = {"type": "result", **payload.to_dict()}
            else:
                d = payload.to_dict()
                body = {"type": "done", **{k: d[k] for k in (
                    "answer", "error", "attempts", "latency_ms", "input_tokens", "output_tokens",
                    "cost_usd", "model", "timings")}}
            yield json.dumps(body, default=str) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history")
def history(limit: int = 20):
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT log_id, created_at, question, answer, error, latency_ms FROM query_log "
            "ORDER BY log_id DESC LIMIT %s", (min(max(limit, 1), 100),)).fetchall()
    return [{"id": r[0], "created_at": r[1].isoformat(), "question": r[2], "answer": r[3],
             "error": r[4], "latency_ms": r[5]} for r in rows]
