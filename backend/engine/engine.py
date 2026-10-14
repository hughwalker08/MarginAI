"""question -> SQL -> validate -> run -> fix (max 2 retries) -> plain-English answer -> log."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field

import psycopg

from . import prompts
from .charts import suggest_chart
from .context import build_store_context, schema_text
from .executor import QueryResult, run_readonly
from .llm import LLMClient, Message
from .validator import ValidationError, validate_sql

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
    error: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_reply(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _table_text(res: QueryResult, limit: int = ANSWER_ROWS) -> str:
    lines = [" | ".join(res.columns)] + [" | ".join("" if v is None else str(v) for v in r)
                                         for r in res.rows[:limit]]
    if len(res.rows) > limit:
        lines.append(f"... ({len(res.rows) - limit} more rows not shown)")
    return "\n".join(lines)


class Engine:
    def __init__(self, llm: LLMClient, database_url: str, log: bool = True):
        self.llm = llm
        self.database_url = database_url
        self.log = log
        store_context, self.as_of = build_store_context(database_url)
        self.system = prompts.SQL_SYSTEM.format(schema=schema_text(), store_context=store_context)

    def ask(self, question: str) -> EngineResult:
        t0 = time.perf_counter()
        out = EngineResult(question=question, answer="", model=self.llm.model)

        def call(system, messages, json_mode):
            r = self.llm.complete(system, messages, json_mode=json_mode)
            out.input_tokens += r.input_tokens
            out.output_tokens += r.output_tokens
            out.model = r.model or out.model
            return r.text

        try:
            self._run(question, out, call)
        except Exception as e:  # LLM/API/DB failure: report, never crash the caller
            out.error = f"{type(e).__name__}: {e}"
            out.answer = out.answer or "Sorry, I couldn't answer that."
        out.latency_ms = int((time.perf_counter() - t0) * 1000)
        out.cost_usd = self.llm.cost_usd(out.input_tokens, out.output_tokens)
        if self.log:
            self._log(out)
        return out

    def _run(self, question: str, out: EngineResult, call) -> None:
        messages = [Message("user", question)]
        result: QueryResult | None = None
        empty_retried = False
        for attempt in range(MAX_RETRIES + 1):
            out.attempts = attempt + 1
            reply = call(self.system, messages, True)
            messages.append(Message("model", reply))
            try:
                data = _parse_reply(reply)
            except (ValueError, json.JSONDecodeError) as e:
                out.error = f"Model reply was not valid JSON: {e}"
                messages.append(Message("user", prompts.FIX_PROMPT.format(error=out.error)))
                continue
            out.assumptions = data.get("assumptions") or ""
            if not data.get("sql"):
                out.clarification = data.get("clarification") or "Could you tell me more about what you mean?"
                out.answer = out.clarification
                out.error = None
                return
            sql = data["sql"]
            out.sql = sql
            try:
                sql = validate_sql(sql)
                result = run_readonly(self.database_url, sql)
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
            return

        out.columns, out.rows, out.truncated = result.columns, result.rows, result.truncated
        out.chart = suggest_chart(result.columns, result.rows)
        out.answer = call(prompts.ANSWER_SYSTEM, [Message("user", prompts.ANSWER_USER.format(
            question=question, assumptions=out.assumptions or "none", row_count=len(result.rows),
            trunc=", truncated" if result.truncated else "", table=_table_text(result)))], False).strip()

    def _log(self, o: EngineResult) -> None:
        try:
            with psycopg.connect(self.database_url, autocommit=True) as conn:
                conn.execute(
                    "INSERT INTO query_log (question, sql, answer, error, attempts, row_count, latency_ms, "
                    "input_tokens, output_tokens, cost_usd, model) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (o.question, o.sql, o.answer, o.error, o.attempts, len(o.rows), o.latency_ms,
                     o.input_tokens, o.output_tokens, o.cost_usd, o.model))
        except psycopg.Error:
            pass  # logging must never break answering
