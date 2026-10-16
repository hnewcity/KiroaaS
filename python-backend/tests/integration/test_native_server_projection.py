"""Fake MCP and byte-stream integration; no live upstream or credential access."""

from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import AsyncMock

import httpx
import pytest

from extensions import kiro_payload_builder as builder
from extensions.kiro_stream_decoder import install_kiro_stream_decoder, uninstall_kiro_stream_decoder
from extensions.request_context import current_state, reset_request_state, start_request_state
from extensions.server_tool_blocks import install_server_tool_blocks, uninstall_server_tool_blocks
from kiro.cache import ModelInfoCache
from kiro.native_reasoning import NativeReasoningError, reasoning_store, restore_native_projections
from tests.unit.test_kiro_stream_decoder_extension import event_frame

MODEL = "fixture-native-model"
SCOPE = ("client", "account", MODEL)


class ByteStream(httpx.AsyncByteStream):
    """Split binary frames independently of transport event boundaries."""

    def __init__(self, data: bytes) -> None:
        self.data, self.closed = data, False

    async def __aiter__(self) -> Any:
        for start in range(0, len(self.data), 7):
            yield self.data[start:start + 7]

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use the actual installed decoder/converters and production projection hook."""
    reasoning_store.clear()
    uninstall_kiro_stream_decoder()
    builder.uninstall_kiro_payload_builder()
    install_server_tool_blocks()
    builder.install_kiro_payload_builder()
    install_kiro_stream_decoder()
    import kiro.streaming_anthropic as anthropic
    import kiro.streaming_openai as openai
    monkeypatch.setattr(anthropic, "count_tokens", lambda text: len(text))
    monkeypatch.setattr(openai, "count_tokens", lambda text: len(text))
    yield
    uninstall_kiro_stream_decoder()
    builder.uninstall_kiro_payload_builder()
    uninstall_server_tool_blocks()
    reasoning_store.clear()


@contextmanager
def context(*, scope: tuple[str, str, str] = SCOPE) -> Iterator[Any]:
    state, token = start_request_state()
    state.client_scope, state.account_scope = scope[:2]
    cache = ModelInfoCache()
    cache._cache = {scope[2]: {"modelId": scope[2], "additionalModelRequestFieldsSchema": {
        "type": "object", "properties": {"max_tokens": {"type": "integer", "minimum": 1, "maximum": 10000}},
    }}}
    state.model_cache = cache
    try:
        yield state
    finally:
        reset_request_state(token)


def build(api: str, messages: list[dict[str, Any]], *, model: str = MODEL) -> dict[str, Any]:
    """Exercise real request validation and parent normal native conversion."""
    from kiro.models_anthropic import AnthropicMessagesRequest
    from kiro.models_openai import ChatCompletionRequest
    import kiro.routes_anthropic as anthropic
    import kiro.routes_openai as openai

    definitions = [{"name": name, "description": name, "input_schema": {"type": "object"}}
                   for name in ("web_search", "read_file")]
    if api == "anthropic":
        request = AnthropicMessagesRequest(model=model, max_tokens=4096, messages=messages, tools=definitions)
        return anthropic.anthropic_to_kiro(request, "unused-route-fallback", "")
    request = ChatCompletionRequest(model=model, max_tokens=4096, messages=messages, tools=[
        {"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}}
        for item in definitions
    ])
    return openai.build_kiro_payload(request, "unused-route-fallback", "")


def frames(*, mixed: bool = True, error: bool = False) -> bytes:
    """Native content interleaves with two projected and one ordinary tool."""
    events = [
        ("reasoningContentEvent", {"text": "thought A", "signature": "signature-A"}),
        ("assistantResponseEvent", {"content": "before"}),
        ("toolUseEvent", {"toolUseId": "search-1", "name": "web_search", "input": '{"query":"one","limit":2}', "stop": True}),
        ("reasoningContentEvent", {"redactedContent": "AP8B"}),
        ("assistantResponseEvent", {"content": "between"}),
    ]
    if mixed:
        events.append(("toolUseEvent", {"toolUseId": "client-tool", "name": "read_file", "input": '{"path":"caller"}', "stop": True}))
    events.extend([
        ("reasoningContentEvent", {"text": "thought B", "signature": "signature-B"}),
        ("toolUseEvent", {"toolUseId": "search-2", "name": "web_search", "input": '{"query":"two"}', "stop": True}),
        ("assistantResponseEvent", {"content": "after"}),
        ("reasoningContentEvent", {"signature": 5}) if error else ("contextUsageEvent", {"contextUsagePercentage": 1}),
    ])
    return b"".join(event_frame(name, event) for name, event in events)


def parse_sse(chunks: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line[5:]) for chunk in chunks for line in chunk.splitlines()
            if line.startswith("data:") and line[5:].strip() != "[DONE]"]


def assemble(api: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Independent client-side assembly of exactly the emitted protocol blocks."""
    if api == "openai":
        message = {"role": "assistant", "content": "", "reasoning_content": "", "reasoning_details": [], "tool_calls": []}
        for event in events:
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                for key in ("content", "reasoning_content"):
                    message[key] += delta.get(key) or ""
                for key in ("tool_calls", "reasoning_details"):
                    message[key].extend(delta.get(key) or [])
        return message
    blocks, inputs = {}, {}
    for event in events:
        index = event.get("index")
        if event["type"] == "content_block_start":
            blocks[index] = deepcopy(event["content_block"])
        elif event["type"] == "content_block_delta":
            delta = event["delta"]
            for key in ("text", "thinking", "signature"):
                if key in delta:
                    blocks[index][key] = blocks[index].get(key, "") + delta[key]
            if "partial_json" in delta:
                inputs[index] = inputs.get(index, "") + delta["partial_json"]
    for index, value in inputs.items():
        blocks[index]["input"] = json.loads(value)
    return {"role": "assistant", "content": [blocks[index] for index in sorted(blocks)]}


async def formatted(api: str, streaming: bool, state: Any, data: bytes) -> tuple[dict[str, Any], Any]:
    import kiro.streaming_anthropic as anthropic
    import kiro.streaming_openai as openai

    stream = ByteStream(data)
    response = httpx.Response(200, stream=stream)
    if api == "anthropic":
        if streaming:
            events = parse_sse([chunk async for chunk in anthropic.stream_kiro_to_anthropic(response, MODEL, state.model_cache, SimpleNamespace())])
            result = assemble(api, events)
        else:
            output = await anthropic.collect_anthropic_response(response, MODEL, state.model_cache, SimpleNamespace())
            result = {"role": "assistant", "content": output["content"]}
    elif streaming:
        events = parse_sse([chunk async for chunk in openai.stream_kiro_to_openai(None, response, MODEL, state.model_cache, SimpleNamespace())])
        result = assemble(api, events)
    else:
        output = await openai.collect_stream_response(None, response, MODEL, state.model_cache, SimpleNamespace())
        result = output["choices"][0]["message"]
    assert stream.closed
    return result, response


@pytest.fixture
def fake_mcp(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    async def search(query: str, auth: Any) -> tuple[str, dict[str, Any]]:
        return f"mcp-{query}", {"results": [{"title": query, "url": "https://example.invalid/" + query, "snippet": "snippet " + query}]}

    fake = AsyncMock(side_effect=search)
    monkeypatch.setattr("kiro.mcp_tools.call_kiro_mcp_api", fake)
    monkeypatch.setattr("kiro.mcp_tools.generate_search_summary", lambda query, results: f"summary({query})")
    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize("api,streaming", [("anthropic", True), ("openai", True), ("openai", False)])
@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("restart", [False, True])
async def test_actual_projection_replays_through_normal_conversion(api: str, streaming: bool, mixed: bool,
                                                                  fake_mcp: AsyncMock, restart: bool,
                                                                  tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    if restart:
        from kiro.native_replay_storage import ReplayStorage
        monkeypatch.setattr(reasoning_store, "storage", ReplayStorage(tmp_path))
    with context() as state:
        initial = build(api, [{"role": "user", "content": "go"}])
        message, _ = await formatted(api, streaming, state, frames(mixed=mixed))
        original = deepcopy(state.native_ledger.blocks)
        record = next(iter(reasoning_store._records.values()))
        assert record.projections
        assert fake_mcp.await_count == 2
    if restart:
        from extensions.session_identity import session_registry
        reasoning_store.clear()
        session_registry.clear()
        monkeypatch.setattr(reasoning_store, "storage", ReplayStorage(tmp_path))
    caller = []
    if mixed:
        caller.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "client-tool", "content": "caller tool result"}]}
                      if api == "anthropic" else {"role": "tool", "tool_call_id": "client-tool", "content": "caller tool result"})
    caller.append({"role": "user", "content": "caller follow-up"})
    with context() as replay_state:
        replay = build(api, [{"role": "user", "content": "go"}, message, *caller])
        assert replay_state.recovered_reasoning_record.root_conversation_id == record.root_conversation_id
    conversation = replay["conversationState"]
    assert conversation["conversationId"] == initial["conversationState"]["conversationId"]
    assistants = [entry["assistantResponseMessage"] for entry in conversation["history"] if "assistantResponseMessage" in entry]
    native = [entry["reasoningContent"] for entry in assistants if "reasoningContent" in entry]
    assert native == [{"reasoningText": {"text": "thought A", "signature": "signature-A"}},
                      {"redactedContent": "AP8B"}, {"reasoningText": {"text": "thought B", "signature": "signature-B"}}]
    tools = [tool for entry in assistants for tool in entry.get("toolUses", [])]
    assert [tool["toolUseId"] for tool in tools] == [block["id"] for block in original if block["type"] == "tool_use"]
    assert tools[0]["input"] == {"query": "one", "limit": 2}
    assert "summary(" not in "".join(entry["content"] for entry in assistants)
    users = [entry["userInputMessage"] for entry in conversation["history"] if "userInputMessage" in entry]
    users.append(conversation["currentMessage"]["userInputMessage"])
    results = [result for entry in users for result in entry.get("userInputMessageContext", {}).get("toolResults", [])]
    assert {result["toolUseId"] for result in results} == {tool["toolUseId"] for tool in tools}
    assert "caller follow-up" in json.dumps(users)
    assert "summary(one)" in json.dumps(results) and "summary(two)" in json.dumps(results)
    if mixed:
        assert "caller tool result" in json.dumps(results)


@pytest.mark.asyncio
async def test_nonstream_anthropic_does_not_start_new_mcp_execution(fake_mcp: AsyncMock) -> None:
    with context() as state:
        build("anthropic", [{"role": "user", "content": "go"}])
        message, _ = await formatted("anthropic", False, state, frames())
        assert message["content"] == state.native_ledger.blocks
        assert not next(iter(reasoning_store._records.values())).projections
    fake_mcp.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["anthropic", "openai"])
async def test_failed_mcp_does_not_authorize_projection(api: str, fake_mcp: AsyncMock) -> None:
    fake_mcp.side_effect = None
    fake_mcp.return_value = ("failed", None)
    with context() as state:
        build(api, [{"role": "user", "content": "go"}])
        message, _ = await formatted(api, True, state, frames())
        assert not next(iter(reasoning_store._records.values())).projections
        assert restore_native_projections([message], scope=SCOPE, anthropic=api == "anthropic") == [message]


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["anthropic", "openai"])
async def test_decode_failure_after_successful_mcp_never_mints_receipt(api: str, fake_mcp: AsyncMock) -> None:
    from extensions.kiro_stream_decoder import KiroStreamError

    with context() as state:
        build(api, [{"role": "user", "content": "go"}])
        with pytest.raises(KiroStreamError):
            await formatted(api, True, state, frames(error=True))
        assert fake_mcp.await_count == 2
        assert not reasoning_store._records


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["anthropic", "openai"])
async def test_projection_uses_resolved_upstream_model_not_display_label(api: str, fake_mcp: AsyncMock) -> None:
    data = event_frame("assistantResponseEvent", {"modelId": "resolved-native-model"}) + frames(mixed=False)
    with context() as state:
        build(api, [{"role": "user", "content": "go"}])
        message, _ = await formatted(api, True, state, data)
        assert state.response_model_id == "resolved-native-model"
    with pytest.raises(NativeReasoningError):
        restore_native_projections([message], scope=SCOPE, anthropic=api == "anthropic")
    restored = restore_native_projections([message], scope=("client", "account", "resolved-native-model"), anthropic=api == "anthropic")
    assert len(restored) > 1


@pytest.mark.asyncio
@pytest.mark.parametrize("api,streaming", [("anthropic", True), ("anthropic", False), ("openai", True), ("openai", False)])
async def test_authoritative_responses_usage_overrides_estimates_and_cache_fields(
    api: str, streaming: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kiro.streaming_anthropic as anthropic
    import kiro.streaming_openai as openai
    from kiro.streaming_core import KiroEvent, StreamResult

    raw = {"input_tokens": 101, "output_tokens": 23, "total_tokens": 124,
           "input_tokens_details": {"cached_tokens": 31}, "output_tokens_details": {"reasoning_tokens": 7}}
    first = {"_responses_usage": raw, "cache_read_input_tokens": 999}
    last = {"unit": "credit", "usage": 0.25}

    async def parsed(response: httpx.Response, *args: Any, **kwargs: Any) -> Any:
        yield KiroEvent(type="content", content="answer")
        yield KiroEvent(type="usage", usage=first)
        yield KiroEvent(type="usage", usage=last)
        response.extensions["kiro_stream_completed"] = True

    monkeypatch.setattr(anthropic, "parse_kiro_stream", parsed)
    monkeypatch.setattr(openai, "parse_kiro_stream", parsed)
    monkeypatch.setattr(anthropic, "collect_stream_to_result", AsyncMock(return_value=StreamResult(
        content="answer", usage={**first, **last}, completed=True,
    )))
    response = httpx.Response(200, stream=ByteStream(b""))
    cache = ModelInfoCache()
    if api == "anthropic":
        if streaming:
            events = parse_sse([chunk async for chunk in anthropic.stream_kiro_to_anthropic(response, MODEL, cache, SimpleNamespace())])
            final = next(event for event in events if event["type"] == "message_delta")
            usage = final["usage"]
            assert events[0]["message"]["usage"]["input_tokens"] == 0  # Start remains estimate.
            assert final["delta"]["stop_reason"] == "end_turn"
        else:
            final = await anthropic.collect_anthropic_response(response, MODEL, cache, SimpleNamespace())
            usage = final["usage"]
            assert final["stop_reason"] == "end_turn"
        assert usage == {"input_tokens": 70, "output_tokens": 23, "cache_read_input_tokens": 31}
    else:
        if streaming:
            events = parse_sse([chunk async for chunk in openai.stream_kiro_to_openai(None, response, MODEL, cache, SimpleNamespace())])
            usage = events[-1]["usage"]
            assert events[-1]["choices"][0]["finish_reason"] == "stop"
        else:
            final = await openai.collect_stream_response(None, response, MODEL, cache, SimpleNamespace())
            usage = final["usage"]
            assert final["choices"][0]["finish_reason"] == "stop"
        assert usage["prompt_tokens"] == 101 and usage["completion_tokens"] == 23 and usage["total_tokens"] == 124
        assert usage["prompt_tokens_details"] == {"cached_tokens": 31}
        assert usage["completion_tokens_details"] == {"reasoning_tokens": 7}
        assert usage["credits_used"]["usage"] == 0.25
        assert "_responses_usage" not in json.dumps(usage)


@pytest.mark.asyncio
@pytest.mark.parametrize("api,streaming", [("anthropic", True), ("anthropic", False), ("openai", True), ("openai", False)])
@pytest.mark.parametrize("completed", [True, False])
async def test_successful_eof_without_usage_is_not_truncation(
    api: str, streaming: bool, completed: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kiro.streaming_anthropic as anthropic
    import kiro.streaming_openai as openai
    from kiro.streaming_core import KiroEvent, StreamResult

    async def parsed(response: httpx.Response, *args: Any, **kwargs: Any) -> Any:
        yield KiroEvent(type="content", content="answer")
        response.extensions["kiro_stream_completed"] = completed

    monkeypatch.setattr(anthropic, "parse_kiro_stream", parsed)
    monkeypatch.setattr(openai, "parse_kiro_stream", parsed)
    monkeypatch.setattr(anthropic, "collect_stream_to_result", AsyncMock(return_value=StreamResult(content="answer", completed=completed)))
    response = httpx.Response(200, stream=ByteStream(b""))
    cache = ModelInfoCache()
    if api == "anthropic":
        if streaming:
            events = parse_sse([chunk async for chunk in anthropic.stream_kiro_to_anthropic(response, MODEL, cache, SimpleNamespace())])
            stop = next(event["delta"]["stop_reason"] for event in events if event["type"] == "message_delta")
        else:
            final = await anthropic.collect_anthropic_response(response, MODEL, cache, SimpleNamespace())
            stop = final["stop_reason"]
        assert stop == ("end_turn" if completed else "max_tokens")
    else:
        if streaming:
            events = parse_sse([chunk async for chunk in openai.stream_kiro_to_openai(None, response, MODEL, cache, SimpleNamespace())])
            stop = events[-1]["choices"][0]["finish_reason"]
        else:
            final = await openai.collect_stream_response(None, response, MODEL, cache, SimpleNamespace())
            stop = final["choices"][0]["finish_reason"]
        assert stop == ("stop" if completed else "length")


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["anthropic", "openai"])
async def test_empty_successful_search_results_are_still_proven(api: str, fake_mcp: AsyncMock) -> None:
    fake_mcp.side_effect = None
    fake_mcp.return_value = ("mcp-empty", {"results": []})
    with context() as state:
        build(api, [{"role": "user", "content": "go"}])
        message, _ = await formatted(api, True, state, frames(mixed=False))
        restored = restore_native_projections([message], scope=SCOPE, anthropic=api == "anthropic")
        assert len(restored) > 1
        assert "summary(one)" in json.dumps(restored)
