"""Offline native-reasoning flow through installed decoder and both API adapters."""

from contextlib import contextmanager
import json
from types import SimpleNamespace

import httpx
import pytest

from extensions.kiro_payload_builder import install_kiro_payload_builder, uninstall_kiro_payload_builder
from extensions.kiro_stream_decoder import install_kiro_stream_decoder, uninstall_kiro_stream_decoder
from extensions.request_context import reset_request_state, start_request_state
from kiro.cache import ModelInfoCache
from kiro.native_reasoning import NativeReasoningError, reasoning_store
from tests.unit.test_kiro_stream_decoder_extension import event_frame

MODEL = "fixture-native-model"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data, split=7):
        self.data, self.split, self.closed = data, split, False

    async def __aiter__(self):
        for start in range(0, len(self.data), self.split):
            yield self.data[start:start + self.split]

    async def aclose(self):
        self.closed = True


def response():
    frames = [
        ("reasoningContentEvent", {"text": "思考😀A"}),
        ("reasoningContentEvent", {"signature": "upstream-signature-A"}),
        ("assistantResponseEvent", {"content": "answer-1"}),
        ("reasoningContentEvent", {"redactedContent": "b3BhcXVl"}),
        ("toolUseEvent", {"toolUseId": "call-1", "name": "read_file", "input": '{"path":"x"}', "stop": True}),
        ("reasoningContentEvent", {"text": "思考B"}),
        ("reasoningContentEvent", {"signature": "upstream-signature-B"}),
        ("assistantResponseEvent", {"content": "answer-2"}),
        ("contextUsageEvent", {"contextUsagePercentage": 1}),
    ]
    stream = Chunks(b"".join(event_frame(name, data) for name, data in frames))
    return httpx.Response(200, stream=stream), stream


@pytest.fixture(autouse=True)
def installed():
    reasoning_store.clear()
    uninstall_kiro_stream_decoder()
    uninstall_kiro_payload_builder()
    install_kiro_payload_builder()
    install_kiro_stream_decoder()
    yield
    uninstall_kiro_stream_decoder()
    uninstall_kiro_payload_builder()
    reasoning_store.clear()


@contextmanager
def context(account="account-A", model=MODEL):
    state, token = start_request_state()
    state.client_scope, state.account_scope = "client-A", account
    cache = ModelInfoCache()
    cache._cache = {model: {"modelId": model, "additionalModelRequestFieldsSchema": {
        "type": "object", "properties": {"max_tokens": {"type": "integer", "minimum": 1, "maximum": 10000}},
    }}}
    state.model_cache = cache
    try:
        yield state
    finally:
        reset_request_state(token)


def request(api, messages, model=MODEL):
    from kiro.models_anthropic import AnthropicMessagesRequest
    from kiro.models_openai import ChatCompletionRequest
    if api == "anthropic":
        return AnthropicMessagesRequest(model=model, max_tokens=4096, messages=messages,
            tools=[{"name": "read_file", "description": "read", "input_schema": {"type": "object"}}])
    return ChatCompletionRequest(model=model, max_tokens=4096, messages=messages,
        tools=[{"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {"type": "object"}}}])


def build(api, req):
    import kiro.routes_anthropic as anthropic
    import kiro.routes_openai as openai
    function = anthropic.anthropic_to_kiro if api == "anthropic" else openai.build_kiro_payload
    return function(req, "route-random-fallback", "")


def parse_sse(chunks):
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    events.append(json.loads(data))
    return events


def assemble_anthropic(events):
    blocks = {}
    partial = {}
    for event in events:
        index = event.get("index")
        if event["type"] == "content_block_start":
            blocks[index] = event["content_block"]
        elif event["type"] == "content_block_delta":
            delta = event["delta"]
            for field in ("text", "thinking", "signature"):
                if field in delta:
                    blocks[index][field] = blocks[index].get(field, "") + delta[field]
            if "partial_json" in delta:
                partial[index] = partial.get(index, "") + delta["partial_json"]
    for index, value in partial.items():
        blocks[index]["input"] = json.loads(value)
    return {"role": "assistant", "content": [blocks[index] for index in sorted(blocks)]}


def assemble_openai(events):
    message = {"role": "assistant", "content": "", "reasoning_content": "", "reasoning_details": [], "tool_calls": []}
    for event in events:
        for choice in event.get("choices", []):
            delta = choice.get("delta", {})
            message["content"] += delta.get("content", "") or ""
            message["reasoning_content"] += delta.get("reasoning_content", "") or ""
            message["reasoning_details"].extend(delta.get("reasoning_details", []))
            message["tool_calls"].extend(delta.get("tool_calls", []))
    return message


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["anthropic", "openai"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_native_output_and_verified_tool_continuation_round_trip(api, streaming):
    import kiro.streaming_anthropic as anthropic
    import kiro.streaming_openai as openai

    first_messages = [{"role": "user", "content": "go"}]
    with context() as state:
        first_payload = build(api, request(api, first_messages))
        upstream, stream = response()
        if api == "anthropic":
            if streaming:
                chunks = [chunk async for chunk in anthropic.stream_kiro_to_anthropic(upstream, MODEL, state.model_cache, SimpleNamespace())]
                message = assemble_anthropic(parse_sse(chunks))
            else:
                result = await anthropic.collect_anthropic_response(upstream, MODEL, state.model_cache, SimpleNamespace())
                message = {"role": "assistant", "content": result["content"]}
        elif streaming:
            chunks = [chunk async for chunk in openai.stream_kiro_to_openai(None, upstream, MODEL, state.model_cache, SimpleNamespace())]
            message = assemble_openai(parse_sse(chunks))
        else:
            result = await openai.collect_stream_response(None, upstream, MODEL, state.model_cache, SimpleNamespace())
            message = result["choices"][0]["message"]
        assert stream.closed
        if api == "anthropic":
            assert [block["type"] for block in message["content"]] == ["thinking", "text", "redacted_thinking", "tool_use", "thinking", "text"]
            assert message["content"][0]["signature"] == "upstream-signature-A"
            assert message["content"][2]["data"] == "b3BhcXVl"
            tool_result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "done"}]}
        else:
            assert message["content"] == "answer-1answer-2"
            assert message["reasoning_content"] == "思考😀A思考B"
            assert any(block.get("data") == "b3BhcXVl" for block in message["reasoning_details"])
            tool_result = {"role": "tool", "tool_call_id": "call-1", "content": "done"}
    # A new ASGI request without an explicit session can recover it only from
    # exact, verified native output. Identical prompt text alone never does this.
    with context() as state:
        replay = build(api, request(api, first_messages + [message, tool_result]))
        before, after = first_payload["conversationState"], replay["conversationState"]
        assert after["conversationId"] == before["conversationId"]
        assert after["agentContinuationId"] == before["agentContinuationId"]
        native = [entry["assistantResponseMessage"]["reasoningContent"] for entry in after["history"]
                  if "reasoningContent" in entry.get("assistantResponseMessage", {})]
        assert native == [
            {"reasoningText": {"text": "思考😀A", "signature": "upstream-signature-A"}},
            {"redactedContent": "b3BhcXVl"},
            {"reasoningText": {"text": "思考B", "signature": "upstream-signature-B"}},
        ]
        assert "_native_history" not in json.dumps(replay)
    with context(account="account-B"):
        with pytest.raises(NativeReasoningError, match="cannot be verified"):
            build(api, request(api, first_messages + [message, tool_result]))

@pytest.mark.asyncio
async def test_explicit_stream_deadline_bounds_silent_body_and_closes_stream():
    import asyncio
    import time
    import kiro.streaming_core as core
    from extensions.kiro_stream_decoder import KiroStreamError

    class Stalled(Chunks):
        async def __aiter__(self):
            yield event_frame("reasoningContentEvent", {"text": "progress"})
            await asyncio.Event().wait()

    stream = Stalled(b"")
    upstream = httpx.Response(200, stream=stream, extensions={"kiro_stream_deadline": time.monotonic() + 0.05})
    with context():
        seen = []
        with pytest.raises(KiroStreamError) as error:
            async for event in core.parse_kiro_stream(upstream):
                seen.append(event.type)
        assert error.value.exception_type == "RequestTimeoutException"
        assert seen == ["native_reasoning"]
        assert stream.closed
        assert not reasoning_store._records


@pytest.mark.asyncio
async def test_cancellation_after_native_progress_closes_stream_without_recording_partial_output():
    import asyncio
    import kiro.streaming_core as core

    waiting = asyncio.Event()

    class Stalled(Chunks):
        async def __aiter__(self):
            yield event_frame("reasoningContentEvent", {"text": "progress"})
            waiting.set()
            await asyncio.Event().wait()

    stream = Stalled(b"")
    with context():
        iterator = core.parse_kiro_stream(httpx.Response(200, stream=stream))
        first = await iterator.__anext__()
        assert first.type == "native_reasoning"
        pending = asyncio.create_task(iterator.__anext__())
        await waiting.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await iterator.aclose()
        assert stream.closed
        assert not reasoning_store._records


@pytest.mark.asyncio
async def test_truncated_frame_is_not_a_successful_native_response():
    import kiro.streaming_core as core
    from extensions.kiro_stream_decoder import KiroStreamError

    frame = event_frame("reasoningContentEvent", {"signature": "upstream"})
    for tail in (frame[:5], frame[:-1]):
        stream = Chunks(tail)
        with context():
            with pytest.raises(KiroStreamError, match="ended inside a frame"):
                _ = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=stream))]
            assert stream.closed


@pytest.mark.asyncio
async def test_identical_binary_text_deltas_are_not_deduplicated():
    import kiro.streaming_core as core

    data = event_frame("assistantResponseEvent", {"content": "ha"}) * 2
    with context():
        events = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=Chunks(data)))]
        assert "".join(event.content or "" for event in events) == "haha"

@pytest.mark.asyncio
async def test_metadata_does_not_disable_body_idle_timeout():
    import asyncio
    import kiro.streaming_core as core

    class MetadataOnly(Chunks):
        async def __aiter__(self):
            yield event_frame("meteringEvent", {"usage": 0})
            await asyncio.Event().wait()

    stream = MetadataOnly(b"")
    with context():
        from extensions.kiro_stream_decoder import KiroStreamError
        with pytest.raises(KiroStreamError, match="idle"):
            _ = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=stream, extensions={"kiro_stream_idle_timeout": 0.02}), first_token_timeout=0.1)]
        assert stream.closed


@pytest.mark.asyncio
async def test_native_text_counts_as_progress_while_waiting_for_signature():
    import asyncio
    import kiro.streaming_core as core

    class Thinking(Chunks):
        async def __aiter__(self):
            yield event_frame("reasoningContentEvent", {"text": "thought"})
            await asyncio.sleep(0.03)
            yield event_frame("reasoningContentEvent", {"signature": "real-upstream"})

    with context():
        events = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=Thinking(b"")), first_token_timeout=0.01)]
        assert [event.type for event in events] == ["native_reasoning", "native_reasoning"]


@pytest.mark.asyncio
async def test_length_exception_ends_stream_without_reading_post_terminal_content():
    import kiro.streaming_core as core
    from tests.unit.test_kiro_stream_decoder_extension import exception_frame

    data = event_frame("reasoningContentEvent", {"text": "prefix"}) + exception_frame("ContentLengthExceededException", b'{"message":"limit"}') + event_frame("assistantResponseEvent", {"content": "must-not-emit"})
    with context() as state:
        events = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=Chunks(data, split=len(data))))]
        assert state.length_exceeded
        assert [event.type for event in events] == ["native_reasoning"]

@pytest.mark.asyncio
async def test_corrupt_frame_recovery_cannot_be_reported_as_clean_completion():
    import kiro.streaming_core as core
    from extensions.kiro_stream_decoder import KiroStreamError

    broken = bytearray(event_frame("reasoningContentEvent", {"text": "lost"}))
    broken[-1] ^= 1
    data = bytes(broken) + event_frame("assistantResponseEvent", {"content": "recovered"})
    stream = Chunks(data)
    with context():
        with pytest.raises(KiroStreamError, match="corrupt frames"):
            _ = [event async for event in core.parse_kiro_stream(httpx.Response(200, headers={"content-type": "application/vnd.amazon.eventstream"}, stream=stream))]
        assert stream.closed
        assert not reasoning_store._records


@pytest.mark.asyncio
async def test_empty_reasoning_markers_do_not_create_fabricated_thinking_blocks():
    import kiro.streaming_core as core

    data = b"".join(event_frame("reasoningContentEvent", value) for value in ({}, {"text": ""}, {"text": None}, {"redactedContent": []}))
    data += event_frame("assistantResponseEvent", {"content": "ok"})
    with context():
        events = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=Chunks(data)))]
        assert [event.type for event in events] == ["content"]

@pytest.mark.parametrize("api", ["anthropic", "openai"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 64.0, "64"])
def test_api_token_limits_are_not_coerced_before_capability_validation(api, value):
    from kiro.models_anthropic import AnthropicMessagesRequest
    from kiro.models_openai import ChatCompletionRequest
    from pydantic import ValidationError

    model = AnthropicMessagesRequest if api == "anthropic" else ChatCompletionRequest
    with pytest.raises(ValidationError):
        model(model=MODEL, messages=[{"role": "user", "content": "go"}], max_tokens=value)

@pytest.mark.asyncio
async def test_resolved_model_metadata_is_not_mislabeled_as_requested_model():
    import kiro.streaming_core as core

    data = event_frame("assistantResponseEvent", {"modelId": "resolved-provider-model"})
    data += event_frame("reasoningContentEvent", {"text": "thought"})
    data += event_frame("reasoningContentEvent", {"signature": "provider-signature"})
    data += event_frame("assistantResponseEvent", {"content": "answer"})
    with context() as state:
        build("openai", request("openai", [{"role": "user", "content": "go"}]))
        events = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=Chunks(data)))]
        assert events[0].type == "model_metadata"
        assert state.response_model_id == "resolved-provider-model"
        assert {record.scope[2] for record in reasoning_store._records.values()} == {"resolved-provider-model"}
        with pytest.raises(NativeReasoningError):
            reasoning_store.find((state.client_scope, state.account_scope, MODEL), "answer", [],
                [{"type": "thinking", "thinking": "thought", "signature": "provider-signature"}])

@pytest.mark.asyncio
async def test_successful_active_generation_is_not_cut_off_by_retry_budget():
    import asyncio
    import time
    import kiro.streaming_core as core

    class Active(Chunks):
        async def __aiter__(self):
            yield event_frame("reasoningContentEvent", {"text": "working"})
            await asyncio.sleep(0.03)
            yield event_frame("reasoningContentEvent", {"signature": "upstream"})
            yield event_frame("assistantResponseEvent", {"content": "finished"})

    with context():
        upstream = httpx.Response(200, stream=Active(b""), extensions={
            "kiro_request_deadline": time.monotonic() + 0.015,
            "kiro_stream_idle_timeout": 0.2,
        })
        events = [event async for event in core.parse_kiro_stream(upstream)]
        assert events[-1].content == "finished"

@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["anthropic", "openai"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_reported_model_is_exposed_without_overwriting_public_model_alias(api, streaming):
    import kiro.streaming_anthropic as anthropic
    import kiro.streaming_openai as openai

    data = event_frame("assistantResponseEvent", {"modelId": "resolved-model", "content": "ok"})
    data += event_frame("contextUsageEvent", {"contextUsagePercentage": 1})
    with context() as state:
        upstream = httpx.Response(200, stream=Chunks(data))
        if api == "anthropic":
            if streaming:
                events = parse_sse([chunk async for chunk in anthropic.stream_kiro_to_anthropic(upstream, MODEL, state.model_cache, SimpleNamespace())])
                assert events[0]["message"]["model"] == MODEL
                assert next(event for event in events if event["type"] == "message_delta")["kiro_upstream_model"] == "resolved-model"
            else:
                result = await anthropic.collect_anthropic_response(upstream, MODEL, state.model_cache, SimpleNamespace())
                assert result["model"] == MODEL and result["kiro_upstream_model"] == "resolved-model"
        elif streaming:
            events = parse_sse([chunk async for chunk in openai.stream_kiro_to_openai(None, upstream, MODEL, state.model_cache, SimpleNamespace())])
            assert next(event for event in events if event.get("kiro_upstream_model"))["kiro_upstream_model"] == "resolved-model"
        else:
            result = await openai.collect_stream_response(None, upstream, MODEL, state.model_cache, SimpleNamespace())
            assert result["model"] == MODEL and result["kiro_upstream_model"] == "resolved-model"


@pytest.mark.asyncio
async def test_conflicting_model_hints_do_not_create_a_misbound_native_record():
    import kiro.streaming_core as core
    from extensions.kiro_stream_decoder import KiroStreamError

    data = event_frame("assistantResponseEvent", {"modelId": "model-A"})
    data += event_frame("reasoningContentEvent", {"text": "thought", "signature": "signature"})
    data += event_frame("assistantResponseEvent", {"modelId": "model-B", "content": "answer"})
    with context():
        with pytest.raises(KiroStreamError, match="conflicting model IDs"):
            _ = [event async for event in core.parse_kiro_stream(httpx.Response(200, stream=Chunks(data)))]
        assert not reasoning_store._records
