"""Conversation memory: turn the last few exchanges into messages the model can read.

The browser holds the conversation and sends a compact record of each finished turn; the server
keeps no session state (so any instance can answer any request). Each remembered turn costs roughly
300-500 prompt tokens, so MEMORY_TURNS (see below) is a cost/accuracy dial.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .llm import Message

# How many previous question/answer pairs the model sees. Chosen with `python -m evals.run_followups`;
# override with the MEMORY_TURNS environment variable.
MEMORY_TURNS = int(os.environ.get("MEMORY_TURNS", 6))
PREVIEW_ROWS = 5
MAX_CELL = 60
MAX_TEXT = 600
MAX_SQL = 3000


@dataclass
class HistoryTurn:
    question: str
    answer: str = ""
    sql: str | None = None
    assumptions: str = ""
    clarification: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)  # a preview only


def _clip(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _preview(turn: HistoryTurn) -> str:
    if not turn.rows:
        return "(no rows)"
    def cell(v):
        return "" if v is None else _clip(str(v), MAX_CELL)
    lines = [" | ".join(_clip(c, MAX_CELL) for c in turn.columns)]
    lines += [" | ".join(cell(v) for v in r) for r in turn.rows[:PREVIEW_ROWS]]
    return "\n".join(lines)


def build_messages(question: str, history: list[HistoryTurn] | None, turns: int | None = None) -> list[Message]:
    """Messages for the SQL-writing call: earlier exchanges replayed as the user's question and the
    model's own JSON reply (so the SQL it wrote is in view), then the new question. The previous
    turn's answer and a preview of its rows ride along with the new question, because follow-ups
    ("and just online?", "which of those...") usually refer to that result."""
    n = MEMORY_TURNS if turns is None else turns
    recent = (history or [])[-n:] if n > 0 else []
    messages: list[Message] = []
    for t in recent:
        messages.append(Message("user", _clip(t.question, MAX_TEXT)))
        messages.append(Message("model", json.dumps({
            "sql": _clip(t.sql, MAX_SQL) or None,
            "assumptions": _clip(t.assumptions, MAX_TEXT),
            "clarification": _clip(t.clarification, MAX_TEXT) or None,
        })))
    if not recent:
        return [Message("user", question)]
    last = recent[-1]
    context = (f"[Previous answer shown to the user: {_clip(last.answer, MAX_TEXT)}]\n"
               f"[First rows of that result]\n{_preview(last)}\n\n") if last.sql else ""
    messages.append(Message("user", f"{context}New question: {question}"))
    return messages
