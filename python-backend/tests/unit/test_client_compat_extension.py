"""
Tests for the client-compat extension (ports of kiro-gateway fork 4ddea22,
61d9b68 and dc0fe43): Anthropic error mapping, SSE pings, stream error events,
refusal / ContentLengthExceeded handling and the OpenAI equivalents.

Helper-level tests are the fork's own (tests/unit/test_client_compat.py).
Route-level tests run the real upstream routers on a fresh FastAPI app with all
upstream-hardening extensions installed and Kiro replaced by an httpx mock
transport that speaks binary eventstream, so the whole path (payload builder ->
retry -> decoder -> formatters -> compat middleware) is exercised.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import extensions.upstream_retry as upstream_retry
from extensions.client_compat import (
    PING_SSE_EVENT,
    format_prompt_too_long,
    install_client_compat,
    map_upstream_error_for_anthropic,
    stream_error_event,
    uninstall_client_compat,
    with_sse_pings,
)
from extensions.kiro_payload_builder import install_kiro_payload_builder, uninstall_kiro_payload_builder
from extensions.kiro_stream_decoder import (
    KiroStreamError,
    encode_eventstream_frame,
    install_kiro_stream_decoder,
    uninstall_kiro_stream_decoder,
)
from extensions.upstream_retry import install_upstream_retry, uninstall_upstream_retry

# conftest's session-wide network block replaces httpx.AsyncClient with a mock
# (it patches the attribute on the shared httpx module). Keep the real class so
# the fake Kiro transport below is actually used.
from httpx._client import AsyncClient as RealAsyncClient


# ==================================================================================================
# Helpers (fork tests)
# ==================================================================================================

class TestErrorMapping:
    def test_prompt_too_long_official_wording(self):
        assert format_prompt_too_long(250000, 200000) == "prompt is too long: 250000 tokens > 200000 maximum"

    def test_prompt_too_long_never_self_contradictory(self):
        assert format_prompt_too_long(0, 200000) == "prompt is too long: 200001 tokens > 200000 maximum"

    def test_context_overflow(self):
        m = map_upstream_error_for_anthropic(400, "CONTENT_LENGTH_EXCEEDS_THRESHOLD", "x", max_input_tokens=1000)
        assert (m.status_code, m.error_type) == (400, "invalid_request_error")
        assert m.message.startswith("prompt is too long:")

    def test_429_rate_limit_with_retry_after(self):
        m = map_upstream_error_for_anthropic(429, "UNKNOWN", "slow down")
        assert (m.status_code, m.error_type) == (429, "rate_limit_error")
        assert m.headers == {"Retry-After": "5"}

    def test_quota_is_billing_error(self):
        m = map_upstream_error_for_anthropic(402, "MONTHLY_REQUEST_COUNT", "quota")
        assert (m.status_code, m.error_type) == (402, "billing_error")

    @pytest.mark.parametrize("status", [500, 502, 503, 408])
    def test_server_errors_overloaded(self, status):
        m = map_upstream_error_for_anthropic(status, "UNKNOWN", "boom")
        assert (m.status_code, m.error_type) == (status, "overloaded_error")

    def test_plain_400_invalid_request(self):
        assert map_upstream_error_for_anthropic(400, "UNKNOWN", "bad").error_type == "invalid_request_error"

    def test_other_status_api_error(self):
        assert map_upstream_error_for_anthropic(404, "UNKNOWN", "nf").error_type == "api_error"


class TestStreamErrorEvent:
    def test_forwards_structured_error(self):
        err = Exception(json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "m"}}))
        event = stream_error_event(err)
        assert event.startswith("event: error\n")
        assert '"rate_limit_error"' in event

    def test_plain_exception_is_overloaded(self):
        event = stream_error_event(RuntimeError("connection reset"))
        assert '"overloaded_error"' in event
        assert "connection reset" in event

    def test_refusal_is_non_retryable(self):
        event = stream_error_event(KiroStreamError("ContentFilteredException", "cannot continue (reason: X)"))
        assert '"invalid_request_error"' in event
        assert "cannot continue" in event

    def test_other_stream_exception_is_overloaded(self):
        assert '"overloaded_error"' in stream_error_event(KiroStreamError("ThrottlingException", "slow"))


class TestSsePings:
    @pytest.mark.asyncio
    async def test_ping_emitted_while_idle(self):
        async def slow():
            await asyncio.sleep(0.05)
            yield "a"

        out = [c async for c in with_sse_pings(slow(), 0.01)]
        assert out[-1] == "a"
        assert PING_SSE_EVENT in out

    @pytest.mark.asyncio
    async def test_no_ping_when_busy(self):
        async def fast():
            for c in ("a", "b", "c"):
                yield c

        assert [c async for c in with_sse_pings(fast(), 1.0)] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_disabled(self):
        async def fast():
            yield "a"

        assert [c async for c in with_sse_pings(fast(), 0)] == ["a"]

    @pytest.mark.asyncio
    async def test_source_error_propagates(self):
        async def broken():
            yield "a"
            raise ValueError("upstream")

        out = []
        with pytest.raises(ValueError):
            async for c in with_sse_pings(broken(), 1.0):
                out.append(c)
        assert out == ["a"]

    @pytest.mark.asyncio
    async def test_consumer_close_closes_source(self):
        closed = asyncio.Event()

        async def endless():
            try:
                while True:
                    await asyncio.sleep(0.2)
                    yield "x"
            finally:
                closed.set()

        gen = with_sse_pings(endless(), 0.01)
        assert await gen.__anext__() == PING_SSE_EVENT
        await gen.aclose()
        assert closed.is_set()


# ==================================================================================================
# Routes end to end
# ==================================================================================================

def _event(event_type, payload):
    return encode_eventstream_frame(
        {":message-type": "event", ":event-type": event_type}, json.dumps(payload).encode()
    )


def _exception(exception_type, message):
    return encode_eventstream_frame(
        {":message-type": "exception", ":exception-type": exception_type},
        json.dumps({"message": message}).encode(),
    )


def _content(text):
    return _event("assistantResponseEvent", {"content": text})


COMPLETE = _event("meteringEvent", {"usage": 0.5, "unit": "credit"}) + _event(
    "contextUsageEvent", {"contextUsagePercentage": 1.0}
)


class FakeKiro(httpx.AsyncBaseTransport):
    """Replies with a scripted status/body; streams bodies in small chunks."""

    def __init__(self):
        self.status = 200
        self.body = b""
        self.chunk_size = 7
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, content=self.body)
        body, size = self.body, self.chunk_size

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for i in range(0, len(body), size):
                    yield body[i:i + size]

        return httpx.Response(200, stream=Stream())

    @property
    def last_payload(self):
        return json.loads(self.requests[-1].content)


@pytest.fixture
def kiro():
    return FakeKiro()


@pytest.fixture
def client(kiro, monkeypatch):
    import kiro.routes_anthropic as routes_anthropic
    import kiro.routes_openai as routes_openai
    from kiro.http_client import KiroHttpClient
    from kiro.account_manager import AccountManager
    from kiro.cache import ModelInfoCache
    from extensions.upstream_account import install_upstream_account_context, uninstall_upstream_account_context

    uninstall_upstream_account_context()
    monkeypatch.setattr(routes_anthropic, "PROXY_API_KEY", "k")
    monkeypatch.setattr(routes_openai, "PROXY_API_KEY", "k")
    monkeypatch.setattr("kiro.routes_anthropic.WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr("kiro.routes_openai.WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr("extensions.client_compat.SSE_PING_INTERVAL", 0)
    monkeypatch.setattr(upstream_retry.asyncio, "sleep", AsyncMock())

    fake_client = RealAsyncClient(transport=kiro)

    async def get_client(self, stream=False):
        return fake_client

    monkeypatch.setattr(KiroHttpClient, "_get_client", get_client)

    for uninstall in (uninstall_client_compat, uninstall_upstream_retry,
                      uninstall_kiro_payload_builder, uninstall_kiro_stream_decoder):
        uninstall()
    app = FastAPI()
    app.include_router(routes_openai.router)
    app.include_router(routes_anthropic.router)
    install_kiro_stream_decoder()
    install_kiro_payload_builder()
    install_upstream_retry()
    install_client_compat(app)

    auth = MagicMock()
    auth.get_access_token = AsyncMock(return_value="tok")
    auth.fingerprint = "fp"
    auth.api_host = "https://runtime.us-east-1.kiro.dev"
    auth.profile_arn = auth._profile_arn = "arn:aws:codewhisperer:us-east-1:1:profile/x"
    # Synthetic advertised metadata; no live model-name capability assumptions.
    cache = ModelInfoCache()
    cache._cache = {"claude-opus-4.7": {"modelId": "claude-opus-4.7", "tokenLimits": {"maxInputTokens": 200000},
        "additionalModelRequestFieldsSchema": {"type": "object", "properties": {
            "output_config": {"type": "object", "properties": {"effort": {"enum": ["low", "medium", "high", "xhigh"], "default": "low"}}},
            "max_tokens": {"type": "integer", "minimum": 1, "maximum": 128000},
            "thinking": {"type": "object", "properties": {"type": {"enum": ["enabled", "disabled", "adaptive"]}}},
        }}}}
    account = MagicMock(id="a", auth_manager=auth, model_cache=cache, model_resolver=MagicMock())
    monkeypatch.setattr(AccountManager, "get_first_account", lambda self: account)
    install_upstream_account_context()
    app.state.account_manager = object.__new__(AccountManager)
    app.state.account_system = False
    app.state.http_client = fake_client

    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        uninstall_client_compat(app)
        uninstall_upstream_account_context()
        uninstall_upstream_retry()
        uninstall_kiro_payload_builder()
        uninstall_kiro_stream_decoder()


async def _raw_stream(app, path, headers, body):
    """Runs one POST through the ASGI app and returns the body text, even if the app raises."""
    raw = json.dumps(body).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "server": ("test", 80), "client": ("test", 1), "app": app,
        "headers": [(b"content-type", b"application/json")]
        + [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    sent = [{"type": "http.request", "body": raw, "more_body": False}]
    chunks = []

    async def receive():
        return sent.pop(0) if sent else {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    try:
        await app(scope, receive, send)
    except Exception:
        pass
    return b"".join(chunks).decode()


ANTHROPIC_HEADERS = {"x-api-key": "k", "anthropic-version": "2023-06-01"}
OPENAI_HEADERS = {"Authorization": "Bearer k"}


def _anthropic(client, stream=False, **overrides):
    body = {
        "model": "claude-opus-4.7", "max_tokens": 5000, "system": "SYS", "stream": stream,
        "messages": [{"role": "user", "content": "hi"}], **overrides,
    }
    return client.post("/v1/messages", headers=ANTHROPIC_HEADERS, json=body)


def _openai(client, stream=False, **overrides):
    body = {"model": "claude-opus-4.7", "stream": stream,
            "messages": [{"role": "user", "content": "hi"}], **overrides}
    return client.post("/v1/chat/completions", headers=OPENAI_HEADERS, json=body)


def _sse_events(text):
    events = []
    for block in text.split("\n\n"):
        lines = block.split("\n")
        if len(lines) >= 2 and lines[0].startswith("event: "):
            events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


def _streamed_text(text):
    return "".join(
        data["delta"].get("text", "")
        for name, data in _sse_events(text)
        if name == "content_block_delta"
    )


class TestAnthropicStreaming:
    def test_multibyte_text_split_across_chunks_survives(self, client, kiro):
        text = "你好，世界！🙂 naïve"
        kiro.body = _content(text) + COMPLETE
        kiro.chunk_size = 3
        r = _anthropic(client, stream=True)
        assert r.status_code == 200
        assert _streamed_text(r.text) == text
        stop = [d for n, d in _sse_events(r.text) if n == "message_delta"][0]
        assert stop["delta"]["stop_reason"] == "end_turn"

    def test_payload_shape(self, client, kiro):
        kiro.body = _content("ok") + COMPLETE
        _anthropic(client, stream=True, output_config={"effort": "high"},
                   messages=[{"role": "user", "content": "USER-TURN-1"}])
        payload = kiro.last_payload
        history = payload["conversationState"]["history"]
        # system prompt (+ gateway additions such as truncation recovery) as its own pair
        assert history[0]["userInputMessage"]["content"].startswith("SYS")
        assert "USER-TURN-1" not in history[0]["userInputMessage"]["content"]
        assert payload["conversationState"]["currentMessage"]["userInputMessage"]["content"] == "USER-TURN-1"
        assert history[1]["assistantResponseMessage"]["content"] == "I will follow these instructions."
        assert payload["additionalModelRequestFields"]["output_config"] == {"effort": "high"}
        assert "thinking_mode" not in json.dumps(payload)

    def test_refusal_is_single_invalid_request_error(self, client, kiro):
        kiro.body = _content("partial") + _event("metadataEvent", {
            "stopReason": "CONTENT_FILTERED",
            "stopDetails": {"refusal": {"category": "REASONING_EXTRACTION", "explanation": "nope"}},
        })
        r = _anthropic(client, stream=True)
        errors = [d for n, d in _sse_events(r.text) if n == "error"]
        assert len(errors) == 1
        assert errors[0]["error"]["type"] == "invalid_request_error"
        assert "REASONING_EXTRACTION" in errors[0]["error"]["message"]
        assert not any(n == "message_delta" for n, _ in _sse_events(r.text))

    def test_stream_exception_is_overloaded_not_end_turn(self, client, kiro):
        kiro.body = _content("partial") + _exception("ThrottlingException", "slow down")
        r = _anthropic(client, stream=True)
        errors = [d for n, d in _sse_events(r.text) if n == "error"]
        assert [e["error"]["type"] for e in errors] == ["overloaded_error"]
        assert "end_turn" not in r.text

    def test_content_length_exceeded_is_max_tokens(self, client, kiro):
        kiro.body = _content("long answer") + _exception("ContentLengthExceededException", "too long")
        from kiro.truncation_state import get_content_truncation

        r = _anthropic(client, stream=True)
        stop = [d for n, d in _sse_events(r.text) if n == "message_delta"][0]
        assert stop["delta"]["stop_reason"] == "max_tokens"
        assert not any(n == "error" for n, _ in _sse_events(r.text))
        # A reported length stop is not a silent cut: no recovery notice next turn
        assert get_content_truncation("long answer") is None


class TestAnthropicNonStreaming:
    def test_refusal_is_400(self, client, kiro):
        kiro.body = _event("metadataEvent", {"stopReason": "CONTENT_FILTERED"})
        r = _anthropic(client)
        assert r.status_code == 400
        assert r.json()["error"]["type"] == "invalid_request_error"

    def test_other_exception_is_529(self, client, kiro):
        kiro.body = _content("x") + _exception("InternalServerException", "boom")
        r = _anthropic(client)
        assert r.status_code == 529
        assert r.json()["error"] == {"type": "overloaded_error", "message": "boom"}

    def test_content_length_exceeded(self, client, kiro):
        kiro.body = _content("partial") + _exception("ContentLengthExceededException", "x")
        r = _anthropic(client)
        assert r.status_code == 200
        assert r.json()["stop_reason"] == "max_tokens"


class TestAnthropicUpstreamErrors:
    def test_context_overflow(self, client, kiro):
        kiro.status = 400
        kiro.body = json.dumps({"message": "Input is too long.", "reason": "CONTENT_LENGTH_EXCEEDS_THRESHOLD"}).encode()
        r = _anthropic(client, stream=True)
        assert r.status_code == 400
        assert r.json()["error"] == {
            "type": "invalid_request_error",
            "message": "prompt is too long: 200001 tokens > 200000 maximum",
        }

    def test_monthly_quota_is_billing_error(self, client, kiro):
        kiro.status = 402
        kiro.body = json.dumps({"message": "quota", "reason": "MONTHLY_REQUEST_COUNT"}).encode()
        r = _anthropic(client)
        assert (r.status_code, r.json()["error"]["type"]) == (402, "billing_error")

    def test_429_rate_limit_with_retry_after(self, client, kiro):
        kiro.status = 429
        kiro.body = b'{"message":"Too many requests"}'
        r = _anthropic(client)
        assert r.status_code == 429
        assert r.json()["error"]["type"] == "rate_limit_error"
        assert r.headers["retry-after"] == "5"

    def test_503_is_overloaded(self, client, kiro):
        kiro.status = 503
        kiro.body = b'{"message":"boom"}'
        r = _anthropic(client)
        assert (r.status_code, r.json()["error"]["type"]) == (503, "overloaded_error")

    def test_stale_reason_from_earlier_attempt_is_not_reused(self, client, kiro):
        # Failover shape: an earlier account left MONTHLY_REQUEST_COUNT in the
        # request state, then this account returns a non-JSON 500 (proxy page),
        # so the route never re-reads a reason. Must map as overloaded, not 402.
        from extensions import request_context

        original_start = request_context.start_request_state

        def start_with_stale_reason():
            state, token = original_start()
            state.upstream_status, state.upstream_reason = 402, "MONTHLY_REQUEST_COUNT"
            return state, token

        import extensions.client_compat as compat

        kiro.status = 500
        kiro.body = b"<html>502 Bad Gateway</html>"
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(compat, "start_request_state", start_with_stale_reason)
            r = _anthropic(client)
        assert r.status_code == 500
        assert r.json()["error"]["type"] == "overloaded_error"

    def test_gateway_validation_errors_untouched(self, client):
        r = client.post("/v1/messages", headers=ANTHROPIC_HEADERS, json={"model": "x"})
        assert r.status_code == 422


class TestOpenAI:
    def test_context_overflow_type(self, client, kiro):
        kiro.status = 400
        kiro.body = json.dumps({"message": "Input is too long.", "reason": "CONTENT_LENGTH_EXCEEDS_THRESHOLD"}).encode()
        r = _openai(client)
        assert r.status_code == 400
        assert r.json()["error"]["type"] == "context_length_exceeded"

    def test_other_400_keeps_upstream_type(self, client, kiro):
        kiro.status = 400
        kiro.body = json.dumps({"message": "Improperly formed request.", "reason": None}).encode()
        r = _openai(client)
        assert r.json()["error"]["type"] == "kiro_api_error"

    def test_content_length_exceeded_is_length(self, client, kiro):
        kiro.body = _content("long") + _exception("ContentLengthExceededException", "x")
        r = _openai(client)
        assert r.json()["choices"][0]["finish_reason"] == "length"

    def test_stream_exception_emits_error_chunk(self, client, kiro):
        kiro.body = _content("x") + _exception("ThrottlingException", "slow down")
        # Upstream's OpenAI stream wrapper re-raises after sending [DONE], and
        # TestClient drops the body of a response whose app raised; read the
        # ASGI messages directly instead.
        text = asyncio.run(_raw_stream(client.app, "/v1/chat/completions", OPENAI_HEADERS, {
            "model": "claude-opus-4.7", "stream": True, "messages": [{"role": "user", "content": "hi"}],
        }))
        errors = [json.loads(line[6:]) for line in text.splitlines()
                  if line.startswith("data: {") and '"error"' in line]
        assert errors and errors[0]["error"]["code"] == "ThrottlingException"
        assert '"finish_reason": "stop"' not in text

    def test_credits_used_is_a_number(self, client, kiro):
        kiro.body = _content("ok") + COMPLETE
        r = _openai(client, model="claude-sonnet-4.5")
        assert r.json()["usage"]["credits_used"] == 0.5
        # 4.5 generation rejects additionalModelRequestFields: never sent
        assert "additionalModelRequestFields" not in kiro.last_payload


def test_uninstall_removes_middleware_and_hooks():
    import kiro.routes_anthropic as routes_anthropic
    from extensions.client_compat import ClientCompatMiddleware

    app = FastAPI()
    original = routes_anthropic.stream_with_first_token_retry_anthropic
    install_client_compat(app)
    assert any(m.cls is ClientCompatMiddleware for m in app.user_middleware)
    assert routes_anthropic.stream_with_first_token_retry_anthropic is not original
    uninstall_client_compat(app)
    assert not any(m.cls is ClientCompatMiddleware for m in app.user_middleware)
    assert routes_anthropic.stream_with_first_token_retry_anthropic is original
