"""Retry, rate-limit and quota handling in the Gemini client, without touching the network."""
import time

import pytest
from google.genai import errors

from backend.engine import llm
from backend.engine.llm import GeminiClient, LLMUnavailable, Message, RateLimiter, retry_info
from evals.run import summarise


def api_error(code, quota_id="GenerateRequestsPerMinutePerProjectPerModel-FreeTier", delay="7s"):
    return errors.APIError(code, {"error": {"code": code, "status": "RESOURCE_EXHAUSTED", "message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


def test_retry_info_reads_delay_and_daily_quota():
    assert retry_info(api_error(429)) == (7.0, False)
    assert retry_info(api_error(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier"))[1]
    assert retry_info(RuntimeError("503 UNAVAILABLE")) == (None, False)


def test_rate_limiter_spaces_calls():
    rl = RateLimiter(rpm=600)  # 0.1 s apart
    t0 = time.monotonic()
    for _ in range(3):
        rl.wait()
    assert time.monotonic() - t0 >= 0.19
    RateLimiter(0).wait()  # disabled: returns immediately


class FakeModels:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return type("R", (), {"text": item, "usage_metadata": None})()

    def generate_content_stream(self, model, contents, config):
        """Script items: an exception (raised on first read), or a list of chunk texts / exceptions."""
        self.calls.append(model)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        for part in item:
            if isinstance(part, Exception):
                raise part
            yield type("Ch", (), {"text": part, "usage_metadata": None})()


def client(script, fallbacks=(), max_retries=3):
    c = GeminiClient.__new__(GeminiClient)
    c.model, c.fallbacks, c.max_retries, c.max_wait_s = "main", list(fallbacks), max_retries, 60.0
    c.limiter = RateLimiter(0)
    c._client = type("C", (), {"models": FakeModels(script)})()
    return c


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(llm.time, "sleep", waited.append)
    monkeypatch.setattr(llm.random, "uniform", lambda a, b: 0)
    return waited


def test_rate_limit_retries_after_server_delay(sleeps):
    c = client([api_error(429), "ok"])
    assert c.complete("s", [Message("user", "q")]).text == "ok"
    assert sleeps == [7.0]


def test_daily_quota_skips_retries_and_moves_to_fallback(sleeps):
    c = client([api_error(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier"), "ok"], fallbacks=["backup"])
    r = c.complete("s", [Message("user", "q")])
    assert (r.text, r.model, sleeps) == ("ok", "backup", [])


def test_exhausted_retries_raise_llm_unavailable(sleeps):
    c = client([api_error(503, delay="1s")] * 3, max_retries=2)
    with pytest.raises(LLMUnavailable):
        c.complete("s", [Message("user", "q")])
    assert len(sleeps) == 2


def test_non_retryable_error_propagates(sleeps):
    c = client([errors.APIError(400, {"error": {"message": "bad request"}})])
    with pytest.raises(errors.APIError):
        c.complete("s", [Message("user", "q")])


def row(i, passed, failure=None, error=None):
    return {"id": f"q{i}", "difficulty": "easy", "category": "count", "passed": passed, "failure": failure,
            "first_attempt": passed, "error": error, "latency_ms": 10, "input_tokens": 1, "output_tokens": 1,
            "cost_usd": 0.0}


def test_summary_excludes_infra_errors_from_accuracy():
    s = summarise([row(1, True), row(2, False, "wrong_result"), row(3, False, "infra_error"),
                   row(4, False, "llm_error", "RuntimeError: All Gemini models failed; 429")])  # legacy outage
    assert (s["scored"], s["infra_errors"], s["accuracy"]) == (2, 2, 0.5)
    assert s["failures"]["wrong_result"] == 1


def test_stream_yields_chunks_then_final_usage_chunk():
    c = client([["Hel", "lo"]])
    out = list(c.stream("sys", [Message("user", "hi")]))
    assert [x.text for x in out] == ["Hel", "lo", ""] and out[-1].model == "main"


def test_stream_falls_back_if_failure_happens_before_any_text():
    c = client([api_error(503), ["ok"]], fallbacks=["backup"], max_retries=0)
    out = list(c.stream("sys", [Message("user", "hi")]))
    assert "".join(x.text for x in out) == "ok" and out[-1].model == "backup"


def test_stream_does_not_retry_after_text_was_sent():
    c = client([["partial", api_error(503)], ["never used"]], fallbacks=["backup"])
    with pytest.raises(errors.APIError):
        list(c.stream("sys", [Message("user", "hi")]))
