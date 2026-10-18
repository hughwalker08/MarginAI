"""Thin LLM interface so providers/models can be swapped and compared by the eval suite."""
from __future__ import annotations

import os
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass
class Message:
    role: str  # "user" | "model"
    text: str


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""  # the model that actually answered (may be a fallback)


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, messages: list[Message], json_mode: bool = False) -> LLMResponse: ...

    def stream(self, system: str, messages: list[Message]) -> Iterator[LLMResponse]:
        """Yield text deltas as they arrive; the last item carries the token counts and model."""
        ...

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float: ...


# USD per 1M tokens (input, output) at paid-tier list prices; the free tier is $0 but this
# shows what the same usage would cost. Verify against ai.google.dev/pricing.
GEMINI_PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
}


class LLMUnavailable(RuntimeError):
    """The provider could not answer at all (outage, rate limit, quota). Not a model mistake:
    the eval suite records these as infra errors and leaves them out of accuracy."""


class RateLimiter:
    """Spaces calls at least 60/rpm seconds apart across all threads. rpm <= 0 disables it."""

    def __init__(self, rpm: float = 0):
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            time.sleep(slot - now)


def retry_info(e: Exception) -> tuple[float | None, bool]:
    """(server-suggested retry delay in seconds, whether a per-day quota is exhausted) from a
    Gemini APIError. Daily quotas don't reset by waiting, so there's no point retrying those."""
    text = f"{getattr(e, 'details', '')} {e}"
    daily = bool(re.search(r"PerDay", text))
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", text) or \
        re.search(r"retry in (\d+(?:\.\d+)?)\s*s", text, re.I)
    return (float(m.group(1)) if m else None), daily


RETRYABLE = (429, 500, 502, 503, 504)


class GeminiClient:
    """Gemini via google-genai. The free tier returns frequent transient 503/429s: each model is
    retried with backoff (honouring the server's retryDelay), then GEMINI_FALLBACK_MODELS
    (comma-separated) are tried in turn. Pass fallbacks=[] to pin one model, as the evals do."""

    thinking_level: str | None = None

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 fallbacks: list[str] | None = None, rpm: float | None = None,
                 max_retries: int | None = None, max_wait_s: float = 60.0):
        from google import genai
        from google.genai import types

        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        if fallbacks is None:
            raw = os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3-flash-preview")
            fallbacks = [m.strip() for m in raw.split(",") if m.strip()]
        self.fallbacks = [m for m in fallbacks if m != self.model]
        self.limiter = RateLimiter(rpm if rpm is not None else float(os.environ.get("GEMINI_RPM", 0)))
        self.max_retries = max_retries if max_retries is not None else int(os.environ.get("GEMINI_MAX_RETRIES", 3))
        self.max_wait_s = max_wait_s
        # "minimal" | "low" | ... turns down a thinking model's reasoning, which is most of its latency.
        self.thinking_level = os.environ.get("GEMINI_THINKING_LEVEL") or None
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set (see .env.example)")
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=45_000))

    def _build(self, system: str, messages: list[Message], json_mode: bool):
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json" if json_mode else None,
            thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level)
            if self.thinking_level else None,
        )
        contents = [types.Content(role=m.role, parts=[types.Part(text=m.text)]) for m in messages]
        return config, contents

    def complete(self, system: str, messages: list[Message], json_mode: bool = False) -> LLMResponse:
        from google.genai import errors

        config, contents = self._build(system, messages, json_mode)
        last_error: Exception | None = None
        for model in [self.model, *self.fallbacks]:
            for attempt in range(self.max_retries + 1):
                self.limiter.wait()
                try:
                    resp = self._client.models.generate_content(model=model, contents=contents, config=config)
                except errors.APIError as e:
                    if e.code not in RETRYABLE:
                        raise
                    last_error = e
                    delay, daily = retry_info(e)
                    if daily or attempt == self.max_retries:
                        break  # this model is done for now; try the next one
                    backoff = delay if delay is not None else 2 ** (attempt + 1)
                    time.sleep(min(backoff, self.max_wait_s) + random.uniform(0, 1))
                    continue
                except Exception as e:  # network timeout
                    last_error = e
                    break
                usage = resp.usage_metadata
                return LLMResponse(
                    text=resp.text or "",
                    input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                    output_tokens=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
                    if usage else 0,
                    model=model,
                )
        raise LLMUnavailable(f"All Gemini models failed; last error: {last_error}")

    def stream(self, system: str, messages: list[Message]) -> Iterator[LLMResponse]:
        from google.genai import errors

        config, contents = self._build(system, messages, False)
        last_error: Exception | None = None
        for model in [self.model, *self.fallbacks]:
            for attempt in range(self.max_retries + 1):
                self.limiter.wait()
                started = False  # once text has reached the caller we can no longer retry or fall back
                try:
                    usage = None
                    for chunk in self._client.models.generate_content_stream(
                            model=model, contents=contents, config=config):
                        usage = chunk.usage_metadata or usage
                        if chunk.text:
                            started = True
                            yield LLMResponse(text=chunk.text, model=model)
                    yield LLMResponse(
                        text="",
                        input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                        output_tokens=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
                        if usage else 0,
                        model=model,
                    )
                    return
                except errors.APIError as e:
                    if started or e.code not in RETRYABLE:
                        raise
                    last_error = e
                    delay, daily = retry_info(e)
                    if daily or attempt == self.max_retries:
                        break
                    backoff = delay if delay is not None else 2 ** (attempt + 1)
                    time.sleep(min(backoff, self.max_wait_s) + random.uniform(0, 1))
                except Exception as e:  # network timeout
                    if started:
                        raise
                    last_error = e
                    break
        raise LLMUnavailable(f"All Gemini models failed; last error: {last_error}")

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        p_in, p_out = GEMINI_PRICES.get(self.model, (0.0, 0.0))
        return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


class FakeLLM:
    """Scripted responses for tests: returns the queued replies in order."""

    model = "fake"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, system: str, messages: list[Message], json_mode: bool = False) -> LLMResponse:
        self.calls.append((system, list(messages)))
        return LLMResponse(self.replies.pop(0), input_tokens=100, output_tokens=20)

    def stream(self, system: str, messages: list[Message]) -> Iterator[LLMResponse]:
        self.calls.append((system, list(messages)))
        text = self.replies.pop(0)
        for i in range(0, len(text), 12):
            yield LLMResponse(text[i:i + 12])
        yield LLMResponse("", input_tokens=100, output_tokens=20, model=self.model)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0
