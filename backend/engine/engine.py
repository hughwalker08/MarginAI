"""question -> SQL -> validate -> run -> fix (max 2 retries) -> plain-English answer -> log."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

import psycopg

from . import prompts
from .charts import suggest_chart
from . import catalogue
from .context import build_store_context, schema_text
from .executor import QueryResult, run_readonly
from .llm import LLMClient, Message
from .memory import HistoryTurn, build_messages
from ..stores import DEMO, Store
from .validator import ValidationError, semantic_warnings, validate_sql

MAX_RETRIES = 2
ANSWER_ROWS = 50


@dataclass
class EngineResult:
    question: str
    answer: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    truncated: bool = False
    chart: dict | None = None
    assumptions: str = ""
    clarification: str | None = None
    follow_ups: list[str] = field(default_factory=list)  # suggested next questions
    error: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    user_email: str | None = None  # who asked (signed-in users only), for the query log
    timings: dict = field(default_factory=dict)  # ms: sql_llm, db, to_result, to_first_word, answer

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_reply(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def clean_follow_ups(raw, question: str) -> list[str]:
    """Keep up to 3 sensible, distinct suggestions; anything malformed is simply dropped."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen = {question.strip().lower()}
    for item in raw:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        if 8 <= len(text) <= 110 and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out[:3]


def _table_text(res: QueryResult, limit: int = ANSWER_ROWS) -> str:
    lines = [" | ".join(res.columns)] + [" | ".join("" if v is None else str(v) for v in r)
                                         for r in res.rows[:limit]]
    if len(res.rows) > limit:
        lines.append(f"... ({len(res.rows) - limit} more rows not shown)")
    return "\n".join(lines)


class Engine:
    def __init__(self, llm: LLMClient, database_url: str, log: bool = True, store: Store = DEMO):
        self.llm = llm
        self.database_url = database_url
        self.log = log
        self.store = store
        self.refresh_context()
        self.answer_system = prompts.ANSWER_SYSTEM.format(currency=store.currency)

    def refresh_context(self) -> None:
        """(Re)build the store-specific prompt: today's date, catalogue, locations, codes."""
        store = self.store
        ctx = build_store_context(self.database_url, store)
        self.as_of, self.search_catalogue = ctx.as_of, ctx.search_mode
        self.context_built_at = time.monotonic()
        self.system = prompts.SQL_SYSTEM.format(
            schema=schema_text(store), store_context=ctx.text, timezone=store.timezone,
            tax_name=store.tax_name, tax_divisor=store.tax_divisor)

    def ask(self, question: str, stream_answer: bool = False,
            history: list[HistoryTurn] | None = None, memory_turns: int | None = None,
            user_email: str | None = None) -> EngineResult:
        """Answer a question and return the final result (used by the evals and the plain endpoint)."""
        final = None
        for event, payload in self.ask_stream(question, stream_answer=stream_answer, history=history,
                                              memory_turns=memory_turns, user_email=user_email):
            if event == "done":
                final = payload
        assert final is not None
        return final

    def ask_stream(self, question: str, stream_answer: bool = True,
                   history: list[HistoryTurn] | None = None, memory_turns: int | None = None,
                   user_email: str | None = None):
        """Yield ("result", EngineResult) as soon as the query has run (data and chart, answer still
        empty), then ("delta", text) chunks of the written answer, then ("done", EngineResult)."""
        t0 = time.perf_counter()
        out = EngineResult(question=question, answer="", model=self.llm.model, user_email=user_email)
        ms = lambda: int((time.perf_counter() - t0) * 1000)  # noqa: E731

        try:
            hint = ""
            if self.search_catalogue:
                t_c = time.perf_counter()
                hint = catalogue.hint(self.database_url, self.store, question)
                out.timings["catalogue_ms"] = int((time.perf_counter() - t_c) * 1000)
            result = self._query_phase(question, out, build_messages(question, history, memory_turns, hint))
            out.timings["to_result_ms"] = ms()
            if result is None:  # clarification, decline, or failure: the answer text is already set
                yield "result", out
            else:
                out.columns, out.rows, out.truncated = result.columns, result.rows, result.truncated
                out.chart = suggest_chart(result.columns, result.rows)
                yield "result", out
                t_ans = time.perf_counter()
                parts: list[str] = []
                for delta in self._answer_phase(question, out, result, stream_answer):
                    if not parts:
                        out.timings["to_first_word_ms"] = ms()
                    parts.append(delta)
                    yield "delta", delta
                out.answer = "".join(parts).strip()
                out.timings["answer_ms"] = int((time.perf_counter() - t_ans) * 1000)
        except Exception as e:  # LLM/API/DB failure: report, never crash the caller
            out.error = f"{type(e).__name__}: {e}"
            out.answer = out.answer or "Sorry, I couldn't answer that."
        out.latency_ms = ms()
        out.cost_usd = self.llm.cost_usd(out.input_tokens, out.output_tokens)
        if self.log:
            self._log(out)
        yield "done", out

    def _call(self, out: EngineResult, system: str, messages: list[Message], json_mode: bool) -> str:
        t = time.perf_counter()
        r = self.llm.complete(system, messages, json_mode=json_mode)
        out.timings["sql_llm_ms"] = out.timings.get("sql_llm_ms", 0) + int((time.perf_counter() - t) * 1000)
        out.input_tokens += r.input_tokens
        out.output_tokens += r.output_tokens
        out.model = r.model or out.model
        return r.text

    def _query_phase(self, question: str, out: EngineResult, messages: list[Message]) -> QueryResult | None:
        """question -> SQL -> validate -> run, with up to MAX_RETRIES fixes. None means there is no
        result to summarise (clarification, decline, or failure); out.answer is then already set."""
        result: QueryResult | None = None
        empty_retried = False
        for attempt in range(MAX_RETRIES + 1):
            out.attempts = attempt + 1
            reply = self._call(out, self.system, messages, True)
            messages.append(Message("model", reply))
            try:
                data = _parse_reply(reply)
            except (ValueError, json.JSONDecodeError) as e:
                out.error = f"Model reply was not valid JSON: {e}"
                messages.append(Message("user", prompts.FIX_PROMPT.format(error=out.error)))
                continue
            out.assumptions = data.get("assumptions") or ""
            out.follow_ups = clean_follow_ups(data.get("follow_ups"), question)
            if not data.get("sql"):
                out.clarification = data.get("clarification") or "Could you tell me more about what you mean?"
                out.answer = out.clarification
                out.error = None
                return None
            sql = data["sql"]
            out.sql = sql
            try:
                sql = validate_sql(sql)
                warnings = semantic_warnings(sql, question) if attempt < MAX_RETRIES else []
                if warnings:
                    out.error = None
                    messages.append(Message("user", prompts.FIX_PROMPT.format(error=" ".join(warnings))))
                    continue
                t = time.perf_counter()
                result = run_readonly(self.database_url, sql, role=self.store.role, schema=self.store.schema,
                                      timezone=self.store.timezone)
                out.timings["db_ms"] = out.timings.get("db_ms", 0) + int((time.perf_counter() - t) * 1000)
            except (ValidationError, psycopg.Error) as e:
                out.error = str(e).strip()
                messages.append(Message("user", prompts.FIX_PROMPT.format(error=out.error)))
                result = None
                continue
            out.error = None
            if not result.rows and not empty_retried and attempt < MAX_RETRIES:
                empty_retried = True  # one chance to loosen filters that matched nothing
                messages.append(Message("user", prompts.EMPTY_PROMPT))
                continue
            break
        if result is None:
            out.answer = "Sorry, I wasn't able to produce a working query for that question."
        return result

    def _answer_phase(self, question: str, out: EngineResult, result: QueryResult, stream: bool):
        messages = [Message("user", prompts.ANSWER_USER.format(
            question=question, assumptions=out.assumptions or "none", row_count=len(result.rows),
            trunc=", truncated" if result.truncated else "", table=_table_text(result)))]
        if not stream:
            r = self.llm.complete(self.answer_system, messages, json_mode=False)
            out.input_tokens += r.input_tokens
            out.output_tokens += r.output_tokens
            out.model = r.model or out.model
            yield r.text
            return
        for chunk in self.llm.stream(self.answer_system, messages):
            out.input_tokens += chunk.input_tokens
            out.output_tokens += chunk.output_tokens
            out.model = chunk.model or out.model
            if chunk.text:
                yield chunk.text

    def _log(self, o: EngineResult) -> None:
        try:
            with psycopg.connect(self.database_url, autocommit=True) as conn:
                conn.execute(
                    "INSERT INTO query_log (question, sql, answer, error, attempts, row_count, latency_ms, "
                    "input_tokens, output_tokens, cost_usd, model, store, user_email) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (o.question, o.sql, o.answer, o.error, o.attempts, len(o.rows), o.latency_ms,
                     o.input_tokens, o.output_tokens, o.cost_usd, o.model, self.store.slug, o.user_email))
        except psycopg.Error:
            pass  # logging must never break answering
