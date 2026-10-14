"""Thin LLM interface so providers/models can be swapped and compared by the eval suite."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol


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

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float: ...


# USD per 1M tokens (input, output) at paid-tier list prices; the free tier is $0 but this
# shows what the same usage would cost. Verify against ai.google.dev/pricing.
GEMINI_PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
}


class GeminiClient:
    """Gemini via google-genai. The free tier returns frequent transient 503/429s, so if the
    primary model keeps failing we fall through GEMINI_FALLBACK_MODELS (comma-separated)."""

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 fallbacks: list[str] | None = None):
        from google import genai
        from google.genai import types

        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
        if fallbacks is None:
            raw = os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3-flash-preview")
            fallbacks = [m.strip() for m in raw.split(",") if m.strip()]
        self.fallbacks = [m for m in fallbacks if m != self.model]
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set (see .env.example)")
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=45_000))

    def complete(self, system: str, messages: list[Message], json_mode: bool = False) -> LLMResponse:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json" if json_mode else None,
        )
        contents = [types.Content(role=m.role, parts=[types.Part(text=m.text)]) for m in messages]
        last_error: Exception | None = None
        for model in [self.model, *self.fallbacks]:
            for attempt in range(2):
                try:
                    resp = self._client.models.generate_content(model=model, contents=contents, config=config)
                except errors.APIError as e:
                    if e.code not in (429, 500, 503, 504):
                        raise
                    last_error = e
                    time.sleep(2 * (attempt + 1))
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
        raise RuntimeError(f"All Gemini models failed; last error: {last_error}")

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

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0
