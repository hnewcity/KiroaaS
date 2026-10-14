"""Offline synthetic contract tests; no shipped program, credentials or network.

This file intentionally lives at the task's literal tests/unit path and also
supports the parent's planned move under python-backend/tests/unit. It imports
only the new adapter by path, without loading the app or installing any hooks.
Run from the repository root with:
    python -B -m pytest -p no:cacheprovider tests/unit/test_responses_adapter.py
"""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import socket
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

_TEST_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _TEST_ROOT if _TEST_ROOT.name == "python-backend" else _TEST_ROOT / "python-backend"
_PATH = _BACKEND / "extensions" / "responses_adapter.py"
_SPEC = importlib.util.spec_from_file_location("_responses_adapter_contract", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
adapter = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = adapter
_SPEC.loader.exec_module(adapter)
Decoder = adapter.ResponsesSSEDecoder
StreamError = adapter.ResponsesStreamError
build = adapter.build_responses_payload
encode_reasoning = adapter.encode_reasoning_envelope
decode_reasoning = adapter.decode_reasoning_envelope


@pytest.fixture(autouse=True)
def isolate_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on socket creation/DNS and suppress only this module's debug logger."""
    deny = Mock(side_effect=AssertionError("network forbidden in adapter fixtures"))
    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(adapter, "logger", Mock())


def command(**extra: Any) -> dict:
    """Return a minimal, entirely synthetic upstream command."""
    return {"modelId": "synthetic-model", "conversationState": {"currentMessage": {
        "userInputMessage": {"content": "hello"}}}, **extra}


def record(kind: str, **fields: Any) -> bytes:
    """Encode one LF-delimited synthetic SSE application event."""
    return ("data: " + json.dumps({"type": kind, **fields}, ensure_ascii=False) + "\n\n").encode("utf-8")


def terminal(status: str = "completed", **response: Any) -> bytes:
    """Encode a terminal response without requiring a trailing DONE marker."""
    return record("response." + status, response={"status": status, **response})


def tool_item(index: int = 0, arguments: str = "", **extra: Any) -> dict:
    """Generate stable, distinct synthetic item/call IDs."""
    return {"type": "function_call", "id": f"item-{index}", "call_id": f"call-{index}",
            "name": f"tool_{index}", "arguments": arguments, **extra}


def tool_start(index: int = 0, arguments: str = "") -> bytes:
    """Encode a declaration; the empty argument prefix is deliberate."""
    return record("response.output_item.added", output_index=index, item=tool_item(index, arguments))


def decoded(wire: bytes, *, step: int | None = None, **limits: Any) -> tuple[list[dict], Any]:
    """Collect a completed synthetic stream at arbitrary chunk size."""
    decoder = Decoder(**limits)
    events = []
    step = len(wire) if step is None else step
    for offset in range(0, len(wire), step):
        events.extend(decoder.feed(wire[offset:offset + step]))
    events.extend(decoder.finalize())
    return events, decoder


def select(events: list[dict], key: str) -> list[dict]:
    """Extract a particular Kiro envelope without imposing incidental metadata."""
    return [event[key] for event in events if key in event]


def test_minimal_payload_is_pure_and_has_no_invented_defaults() -> None:
    """No environment/profile/auth default or source command mutation is allowed."""
    value = command()
    before = copy.deepcopy(value)
    assert build(value) == {"model": "synthetic-model", "stream": True,
                            "input": [{"role": "user", "content": "hello"}]}
    assert value == before


def test_full_observed_payload_order_and_detachment() -> None:
    """Golden payload covers routing, metadata, schemas, reasoning, tools and media."""
    value = command(systemPrompt="  exact instructions\n", origin="SYNTHETIC", profileArn="fixture-profile",
                    agentMode="agent", additionalModelRequestFields={"output_config": {"effort": "high"}})
    schema = {"type": "object", "properties": {"x": {"enum": [1, 2]}}, "additionalProperties": False}
    value["conversationState"] = {
        "conversationId": "conversation", "rootConversationId": "root", "agentContinuationId": "turn",
        "history": [{"userInputMessage": {"content": "previous"}}, {"assistantResponseMessage": {
            "content": "calling", "reasoningContent": {"reasoningText": {"text": "reason", "signature": " sig== "}},
            "toolUses": [{"toolUseId": "call", "name": "fixture", "input": {"x": "\u4e2d"}}]}}],
        "currentMessage": {"userInputMessage": {"content": "next", "images": [{"format": "PNG", "source": {"bytes": b"\x00\xff"}}],
            "documents": [{"format": "PDF", "name": "file", "source": {"bytes": [1, 2]}}],
            "userInputMessageContext": {
                "toolResults": [{"toolUseId": "call", "content": [{"text": "line1"}, {"text": "line2"}]}],
                "tools": [{"toolSpecification": {"name": "fixture", "description": " exact ", "inputSchema": {"json": schema}}}]}}},
    }
    before = copy.deepcopy(value)
    payload = build(value)
    assert payload["metadata"] == {"kiro:agent_mode": "agent", "kiro:conversation_id": "conversation",
                                   "kiro:root_conversation_id": "root", "kiro:agent_continuation_id": "turn"}
    assert payload["instructions"] == "  exact instructions\n"
    assert payload["origin"] == "SYNTHETIC" and payload["profileArn"] == "fixture-profile"
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["input"] == [
        {"role": "user", "content": "previous"},
        {"type": "reasoning", "summary": [], "encrypted_content": '{"reasoningText":{"text":"reason","signature":" sig== "}}'},
        {"role": "assistant", "content": "calling"},
        {"type": "function_call", "call_id": "call", "name": "fixture", "arguments": '{"x":"\u4e2d"}'},
        {"type": "function_call_output", "call_id": "call", "output": "line1\nline2"},
        {"role": "user", "content": [{"type": "input_text", "text": "next"},
            {"type": "input_image", "image_url": "data:image/png;base64,AP8="},
            {"type": "input_file", "filename": "file.pdf", "file_data": "data:application/pdf;base64,AQI="}]},
    ]
    assert payload["tools"] == [{"type": "function", "name": "fixture", "description": " exact ", "parameters": schema}]
    payload["tools"][0]["parameters"]["properties"]["x"]["enum"].append(3)
    assert value == before


@pytest.mark.parametrize("data", [b"\x00\xff", bytearray(b"\x00\xff"), [0, 255], "AP8="])
def test_media_binary_forms_and_unknown_document_format(data: Any) -> None:
    """JSON base64 is not accidentally base64-encoded a second time."""
    value = command()
    value["conversationState"]["currentMessage"]["userInputMessage"] = {
        "images": [{"format": "JPEG", "source": {"bytes": data}}],
        "documents": [{"format": "CUSTOM", "name": "literal.name", "source": {"bytes": data}}],
    }
    parts = build(value)["input"][0]["content"]
    assert parts == [{"type": "input_image", "image_url": "data:image/jpeg;base64,AP8="},
                     {"type": "input_file", "filename": "literal.name.custom", "file_data": "data:application/octet-stream;base64,AP8="}]


@pytest.mark.parametrize("reasoning,expected", [
    ({"reasoningText": {"text": "", "signature": "opaque\\sig"}}, '{"reasoningText":{"text":"","signature":"opaque\\\\sig"}}'),
    ({"redactedContent": b"\x00\xfe"}, '{"redactedContent":"AP4="}'),
    ({"redactedContent": "AP4="}, '{"redactedContent":"AP4="}'),
])
def test_signed_and_opaque_reasoning_request(reasoning: dict, expected: str) -> None:
    """Opaque/signed content is preserved byte-for-byte rather than summarized."""
    value = command()
    value["conversationState"]["history"] = [{"assistantResponseMessage": {"reasoningContent": reasoning}}]
    assert build(value)["input"][0] == {"type": "reasoning", "summary": [], "encrypted_content": expected}


@pytest.mark.parametrize("fields,expected", [({}, None), ({"reasoning": {"effort": "low"}}, "low"),
    ({"output_config": {"effort": "high"}}, "high"), ({"thinking": {"type": "disabled"}}, "none"),
    ({"reasoning": {"effort": "none"}, "thinking": {"type": "disabled"}}, "none"),
    ({"reasoning": {"effort": "high"}, "output_config": {"effort": "high"}}, "high")])
def test_observed_effort_mapping(fields: dict, expected: str | None) -> None:
    """Only nonconflicting observed controls map to reasoning.effort."""
    payload = build(command(additionalModelRequestFields=fields))
    assert payload.get("reasoning") == ({"effort": expected} if expected is not None else None)


@pytest.mark.parametrize("fields", [{"thinking": {"type": "adaptive"}},
    {"thinking": {"type": "disabled", "budget_tokens": 4}}, {"reasoning": {}}, {"reasoning": None},
    {"reasoning": {"effort": ""}}, {"reasoning": {"effort": "high", "summary": "auto"}},
    {"reasoning": {"effort": "high"}, "output_config": {"effort": "low"}},
    {"reasoning": {"effort": "high"}, "thinking": {"type": "disabled"}}])
def test_unsupported_or_conflicting_effort_is_not_silently_lost(fields: dict) -> None:
    """Source-dropped provider fields require an explicit caller decision."""
    with pytest.raises(ValueError, match="additionalModelRequestFields"):
        build(command(additionalModelRequestFields=fields))


def test_routing_aliases_and_current_user_defaults_are_explicit_extensions() -> None:
    """Current routing supplies defaults; historical routing labels are consumed."""
    value = command(model="synthetic-model")
    user = value["conversationState"]["currentMessage"]["userInputMessage"]
    user.update(modelId="synthetic-model", origin="SYNTHETIC")
    del value["modelId"]
    assert build(value)["origin"] == "SYNTHETIC"
    del value["model"]
    assert build(value)["model"] == "synthetic-model"
    value["conversationState"]["history"] = [{"userInputMessage": {"content": "old", "modelId": "other"}}]
    assert build(value)["model"] == "synthetic-model"
    assert build(value)["input"][0] == {"role": "user", "content": "old"}


@pytest.mark.parametrize("path,field,value", [
    ((), "temperature", 0.5), (("conversationState",), "futureGenerationControl", {}),
    ((), "inferenceConfig", {"maxTokens": 42}),
    (("conversationState", "currentMessage", "userInputMessage"), "video", []),
    (("conversationState", "currentMessage", "userInputMessage", "userInputMessageContext"), "environmentState", {}),
])
def test_unknown_explicit_request_fields_fail_at_their_path(path: tuple, field: str, value: Any) -> None:
    """Unknown empty fields are rejected too; explicit does not mean truthy."""
    request = command()
    node = request
    for key in path:
        node = node.setdefault(key, {})
    node[field] = value
    with pytest.raises(ValueError, match=field):
        build(request)


@pytest.mark.parametrize("user", [
    {"content": None}, {"content": ["not text"]}, {"images": None},
    {"images": [{"format": "png", "source": {}}]},
    {"images": [{"format": "png", "source": {"bytes": "not base64"}}]},
    {"images": [{"format": "png", "source": {"bytes": [True]}}]},
    {"images": [{"format": "png", "source": {"bytes": [256]}}]},
    {"images": [{"format": "image/png", "source": {"bytes": b"ok"}}]},
    {"images": [{"format": "png", "source": {"url": "fixture"}}]},
    {"documents": [{"format": "pdf", "name": "x", "source": {"bytes": 1}}]},
    {"userInputMessageContext": {"toolResults": [{"toolUseId": "c", "status": "unknown", "content": [{"text": "ok"}]}]}},
    {"userInputMessageContext": {"toolResults": [{"toolUseId": "c", "content": [{"json": {"x": 1}}]}]}},
    {"userInputMessageContext": {"tools": [{}]}},
    {"userInputMessageContext": {"tools": [{"toolSpecification": {"name": "x", "inputSchema": {}}}]}},
])
def test_nested_request_invalid_or_unsupported_content_fails(user: dict) -> None:
    """Malformed inputs never degrade to a valid-looking empty request."""
    request = command()
    request["conversationState"]["currentMessage"] = {"userInputMessage": user}
    with pytest.raises(ValueError):
        build(request)


@pytest.mark.parametrize("bad", [None, [], {}, {"model": "x"}, command(model="other"), command(origin=None),
    command(conversationState={"history": None}), command(conversationState={"currentMessage": {}}),
    command(conversationState={"currentMessage": {"userInputMessage": {}, "assistantResponseMessage": {}}})])
def test_invalid_envelopes_raise_value_error(bad: Any) -> None:
    """Strict shape/routing failures use the public ValueError contract."""
    with pytest.raises(ValueError):
        build(bad)


def test_empty_content_and_string_arguments_preserved() -> None:
    """No truthiness filtering or JSON whitespace normalization changes intent."""
    value = command(systemPrompt="", agentMode="")
    value["conversationState"]["history"] = [{"assistantResponseMessage": {"content": "", "toolUses": [
        {"toolUseId": "a", "name": "a", "input": '{ "x": 1 }'}, {"toolUseId": "b", "name": "b"}]}}]
    value["conversationState"]["currentMessage"]["userInputMessage"]["content"] = ""
    payload = build(value)
    assert payload["instructions"] == ""
    assert payload["metadata"]["kiro:agent_mode"] == ""
    assert [i.get("content", i.get("arguments")) for i in payload["input"]] == ["", '{ "x": 1 }', "{}", ""]


def test_request_cycle_non_json_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Traversal, output expansion, depth and invalid scalars are bounded."""
    cyc: dict = {}
    cyc["self"] = cyc
    with pytest.raises(ValueError, match="depth"):
        build(cyc)
    for value in (float("nan"), float("inf"), object(), (1, 2), "\ud800"):
        with pytest.raises(ValueError):
            build(command(systemPrompt=value))
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "MAX_REQUEST_NODES", 3)
        with pytest.raises(ValueError, match="node"):
            build(command())
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "MAX_REQUEST_BYTES", 4)
        with pytest.raises(ValueError, match="budget"):
            build(command())


def test_every_utf8_and_crlf_split_matches_whole_stream() -> None:
    """Every two-chunk split, and bytewise feeds, must produce identical output."""
    wire = (record("response.created", response={"id": "r", "status": "in_progress"}) +
            record("response.output_text.delta", item_id="m", output_index=0, delta="\u4f60\u597d\U0001f600\u2028") +
            record("response.output_text.done", item_id="m", output_index=0, text="\u4f60\u597d\U0001f600\u2028") +
            terminal(id="r") + b"data: [DONE]\n\n").replace(b"\n", b"\r\n")
    whole, _ = decoded(wire)
    for split in range(len(wire) + 1):
        decoder = Decoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) + decoder.finalize() == whole
        assert decoder.completed
    bytewise, decoder = decoded(wire, step=1)
    assert bytewise == whole
    assert select(whole, "assistantResponseEvent") == [{"content": "\u4f60\u597d\U0001f600\u2028"}]
    assert decoder.terminal_status == "completed"


def test_sse_multiline_comments_bom_transport_fields_and_cr_only() -> None:
    """SSE data joins with LF; event headers can supply a missing JSON type."""
    wire = (b"\xef\xbb\xbf: comment\r\nid: marker\r\nretry: 0010\r\nignore: transport\r\n"
            b"event: response.output_text.delta\r\ndata: {\r\ndata: \"delta\": \"one\"}\r\n\r\n" +
            b": heartbeat\r\r" + terminal().replace(b"\n", b"\r"))
    events, _ = decoded(wire, step=1)
    assert events[0] == {"metadataEvent": {"sse": {"id": "marker", "retry": "0010"}}}
    assert events[1] == {"assistantResponseEvent": {"content": "one"}}


def test_text_done_item_done_and_completed_snapshots_never_duplicate() -> None:
    """Missing snapshot suffixes are emitted once, not the already-streamed text."""
    item = {"id": "m", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hello!"}]}
    wire = (record("response.output_text.delta", output_index=0, item_id="m", delta="hel") +
            record("response.output_text.done", output_index=0, item_id="m", text="hello!") +
            record("response.content_part.done", output_index=0, item_id="m", content_index=0, part=item["content"][0]) +
            record("response.output_item.done", output_index=0, item=item) + terminal(output=[item]))
    events, _ = decoded(wire)
    assert select(events, "assistantResponseEvent") == [{"content": "hel"}, {"content": "lo!"}]


def test_completed_only_output_supports_text_reasoning_and_tools() -> None:
    """A final response snapshot can fill content omitted from streaming deltas."""
    output = [
        {"type": "reasoning", "id": "r", "encrypted_content": '{"reasoningText":{"text":"think","signature":"signed"}}'},
        {"type": "message", "id": "m", "role": "assistant", "content": [{"type": "output_text", "text": "answer"}]},
        tool_item(2, '{"x":1}'),
    ]
    events, decoder = decoded(terminal(output=output))
    assert [next(iter(e)) for e in events] == ["reasoningContentEvent", "reasoningContentEvent", "assistantResponseEvent",
                                              "toolUseEvent", "toolUseEvent", "metadataEvent"]
    assert select(events, "toolUseEvent")[-1] == {"toolUseId": "call-2", "stop": True}
    assert decoder.completed


def test_refusal_and_text_parts_are_independent_not_globally_suppressed() -> None:
    """One refusal's delta cannot suppress another item's complete refusal."""
    wire = (record("response.refusal.delta", output_index=0, item_id="a", delta="no") +
            record("response.refusal.done", output_index=0, item_id="a", refusal="no") +
            record("response.refusal.done", output_index=1, item_id="b", refusal="other") +
            record("response.output_text.delta", output_index=1, item_id="b", content_index=1, delta="text") + terminal())
    events, _ = decoded(wire)
    assert select(events, "assistantResponseEvent") == [{"content": "no"}, {"content": "other"}, {"content": "text"}]


def test_interleaved_tools_preserve_identity_and_immediate_done_order() -> None:
    """Each done signal stops its own tool before intervening text/other tool events."""
    decoder = Decoder()
    events = decoder.feed(tool_start(0) + tool_start(1))
    events += decoder.feed(record("response.function_call_arguments.delta", item_id="item-0", delta='{"x":') +
                           record("response.function_call_arguments.delta", output_index=1, delta='{"y":2}') +
                           record("response.function_call_arguments.delta", item_id="item-0", output_index=0, delta="1}"))
    assert not any(e.get("toolUseEvent", {}).get("stop") for e in events)
    done_events = decoder.feed(
        record("response.function_call_arguments.done", item_id="item-1", arguments='{"y":2}') +
        record("response.output_text.delta", item_id="m", output_index=2, delta="between stops") +
        record("response.output_item.done", output_index=1, item=tool_item(1, '{"y":2}')) +
        record("response.output_item.done", output_index=0, item=tool_item(0, '{"x":1}')))
    assert done_events == [
        {"toolUseEvent": {"toolUseId": "call-1", "stop": True}},
        {"assistantResponseEvent": {"content": "between stops"}},
        {"toolUseEvent": {"toolUseId": "call-0", "stop": True}},
    ]
    assert not decoder.completed and decoder.terminal_status is None
    events += done_events
    final = decoder.feed(terminal(output=[tool_item(0, '{"x":1}'), tool_item(1, '{"y":2}')]))
    assert select(final, "toolUseEvent") == []
    assert select(events, "toolUseEvent") == [
        {"toolUseId": "call-0", "name": "tool_0", "input": "", "stop": False},
        {"toolUseId": "call-1", "name": "tool_1", "input": "", "stop": False},
        {"toolUseId": "call-0", "input": '{"x":', "stop": False},
        {"toolUseId": "call-1", "input": '{"y":2}', "stop": False},
        {"toolUseId": "call-0", "input": "1}", "stop": False},
        {"toolUseId": "call-1", "stop": True},
        {"toolUseId": "call-0", "stop": True},
    ]
    assert decoder.completed and decoder.finalize() == []


@pytest.mark.parametrize("initial", ["", "{", '{"a":1}'])
def test_partial_tool_declaration_and_done_snapshot_only_emit_suffix(initial: str) -> None:
    """The initial argument prefix is not replayed by an item.done snapshot."""
    wire = (tool_start(arguments=initial) + record("response.output_item.done", output_index=0, item=tool_item(arguments='{"a":1}')) + terminal())
    events, _ = decoded(wire)
    tool_events = select(events, "toolUseEvent")
    assert "".join(e.get("input", "") for e in tool_events) == '{"a":1}'
    assert sum(e.get("stop", False) for e in tool_events) == 1


@pytest.mark.parametrize("reason,stop", [("max_output_tokens", "MAX_TOKENS"), ("content_filter", "CONTENT_FILTERED"),
    ("compaction_required_for_model_handoff", "COMPACTION_REQUIRED_FOR_MODEL_HANDOFF"), ("new-reason", "INCOMPLETE"), (None, "INCOMPLETE")])
def test_incomplete_keeps_early_tool_stop_but_does_not_claim_response_success(reason: str | None, stop: str) -> None:
    """A completed tool is observable even when the whole response later ends incomplete."""
    wire = (tool_start(arguments="{}") + record("response.function_call_arguments.done", item_id="item-0", arguments="{}") +
            terminal("incomplete", incomplete_details={"reason": reason, "opaque": "preserved"}) + b"data: [DONE]\n\n")
    events, decoder = decoded(wire)
    assert not decoder.completed
    assert decoder.terminal_status == "incomplete"
    assert [e for e in select(events, "toolUseEvent") if e.get("stop")] == [{"toolUseId": "call-0", "stop": True}]
    meta = select(events, "metadataEvent")[-1]
    assert meta["stopReason"] == stop
    assert meta["incompleteDetails"] == {"reason": reason, "opaque": "preserved"}
    assert decoder.finalize() == []


def test_incomplete_partial_arguments_remain_unstopped() -> None:
    """Truncated JSON is acceptable evidence of an incomplete call, not runnable input."""
    events, _ = decoded(tool_start(arguments='{"partial":') + terminal("incomplete", incomplete_details={"reason": "max_output_tokens"}))
    assert select(events, "toolUseEvent") == [{"toolUseId": "call-0", "name": "tool_0", "input": '{"partial":', "stop": False}]


@pytest.mark.parametrize("arguments", ["", "{", '{"a":', "[]", "null", '{"x":NaN}', '{"x":1,"x":2}'])
def test_complete_invalid_tool_arguments_never_emit_stop(arguments: str) -> None:
    """A terminal success with malformed tool arguments fails closed."""
    decoder = Decoder()
    decoder.feed(tool_start(arguments=arguments))
    with pytest.raises(StreamError) as error:
        decoder.feed(terminal())
    assert error.value.exception_type == "ResponsesProtocolError"
    assert not any(e.get("toolUseEvent", {}).get("stop") for e in error.value.events)
    assert not decoder.completed


def test_terminal_validation_does_not_fabricate_stops_for_unfinished_calls() -> None:
    """Without independent done signals, a malformed terminal cannot create new stops."""
    decoder = Decoder()
    decoder.feed(tool_start(0, "{}") + tool_start(1, "{"))
    with pytest.raises(StreamError) as error:
        decoder.feed(terminal())
    assert select(error.value.events, "toolUseEvent") == []


def test_signed_reasoning_projects_only_canonical_signature_without_duplicate_text() -> None:
    """Wire JSON whitespace is codec syntax; the actual signature/text stay exact."""
    opaque = '{ "reasoningText": { "text": "thinking", "signature": "opaque-sig==" } }'
    item = {"type": "reasoning", "id": "r", "encrypted_content": opaque, "summary": []}
    wire = (record("response.reasoning.delta", item_id="r", output_index=0, delta="think") +
            record("response.reasoning_text.delta", item_id="r", output_index=0, delta="ing") +
            record("response.output_item.done", output_index=0, item=item) + terminal(output=[item]))
    events, _ = decoded(wire)
    assert select(events, "reasoningContentEvent") == [{"text": "think"}, {"text": "ing"},
        {"signature": "opaque-sig=="}]
    json.dumps(events, allow_nan=False)


def test_redacted_reasoning_is_parent_canonical_and_lossless() -> None:
    """Only the canonical base64 field is emitted, and repeat snapshots deduplicate."""
    item = {"type": "reasoning", "id": "r", "encrypted_content": ' {"redactedContent":"AP8="} '}
    events, _ = decoded(record("response.output_item.done", item=item) + terminal(output=[item]))
    assert select(events, "reasoningContentEvent") == [{"redactedContent": "AP8="}]
    assert json.loads(json.dumps(events)) == events


@pytest.mark.parametrize("opaque", ['{"redactedContent":"not-base64?"}',
    '{"future":{"blob":"/+=opaque"}}', "not json\nopaque==", "", '{"redactedContent":""}'])
def test_unknown_cloud_reasoning_cannot_emit_parent_discarded_fields(opaque: str) -> None:
    """Unrepresentable envelopes fail explicitly rather than inventing opaque replay."""
    item = {"type": "reasoning", "id": "r", "encrypted_content": opaque}
    with pytest.raises(StreamError) as error:
        Decoder().feed(record("response.output_item.done", item=item))
    assert error.value.exception_type == "ResponsesProtocolError"
    assert not select(error.value.events, "reasoningContentEvent")


def test_reasoning_summary_parts_stay_out_of_signed_canonical_text() -> None:
    """Source-unmapped summaries remain metadata, not text later paired with a signature."""
    part0, part1 = {"type": "summary_text", "text": "first"}, {"type": "summary_text", "text": "second"}
    item = {"type": "reasoning", "id": "r", "summary": [part0, part1]}
    wire = (record("response.reasoning_summary_part.added", item_id="r", summary_index=0, part={"type": "summary_text", "text": ""}) +
            record("response.reasoning_summary_text.delta", item_id="r", summary_index=0, delta="first") +
            record("response.reasoning_summary_text.done", item_id="r", summary_index=0, text="first") +
            record("response.reasoning_summary_part.done", item_id="r", summary_index=0, part=part0) +
            record("response.output_item.done", item=item) + terminal(output=[item]))
    events, _ = decoded(wire)
    assert select(events, "reasoningContentEvent") == []
    raws = [event["upstreamEvent"] for event in select(events, "metadataEvent")]
    assert any(event.get("delta") == "first" for event in raws)
    assert any(event.get("item", {}).get("summary") == [part0, part1] for event in raws)


def test_usage_lifecycle_unknown_events_and_code_references_preserve_data() -> None:
    """Raw usage and future metadata survive alongside the observed Kiro projections."""
    unknown = {"type": "kiro:future", "opaque": {"blob": "secret-free fixture", "number": 17}}
    usage = {"input_tokens": 3, "output_tokens": 4, "output_tokens_details": {"reasoning_tokens": 2},
             "kiro:context_usage_percentage": 12.5, "kiro:credits": {"value": 0, "unit": "credit", "unit_plural": "credits"}}
    wire = (record("response.queued", response={"id": "r", "status": "queued"}) +
            record("response.in_progress", response={"id": "r", "status": "in_progress"}) +
            record(unknown["type"], opaque=unknown["opaque"]) +
            record("kiro:code_reference.added", annotations=[{"type": "kiro:code_reference", "license_name": "fixture-license",
                   "repository": "repo", "url": "fixture-url", "recommendation_content_span": {"start": 0, "end": 5}},
                   {"type": "future", "opaque": "keep"}]) + terminal(id="r", usage=usage))
    events, _ = decoded(wire)
    assert {"metadataEvent": {"upstreamEvent": unknown}} in events
    assert select(events, "codeReferenceEvent") == [{"references": [{"licenseName": "fixture-license", "repository": "repo",
        "url": "fixture-url", "recommendationContentSpan": {"start": 0, "end": 5}}]}]
    assert select(events, "metadataEvent")[-1]["usage"] == usage
    assert select(events, "contextUsageEvent") == [{"contextUsagePercentage": 12.5}]
    assert select(events, "meteringEvent") == [{"usage": 0, "unit": "credit", "unitPlural": "credits"}]
    assert [next(iter(e)) for e in events[-3:]] == ["metadataEvent", "contextUsageEvent", "meteringEvent"]


@pytest.mark.parametrize("code,category,expected", [
    ("rate_limit_exceeded", "", "ThrottlingException"), ("", "too_many_requests", "ThrottlingException"),
    ("credit_balance_exhausted", "", "ServiceQuotaExceededException"), ("", "insufficient_quota", "ServiceQuotaExceededException"),
    ("access_denied", "", "AccessDeniedException"), ("kiro:model_requires_user_opt_in", "", "ValidationException"),
    ("context_length_exceeded", "", "ValidationException"), ("model_not_found", "", "ValidationException"),
    ("invalid_function_parameters", "", "ValidationException"), ("", "not_found", "ValidationException"),
    ("server_is_overloaded", "", "ServiceUnavailableException"), ("", "model_error", "InternalServerException"),
    ("future", "future", "InternalServerException")])
@pytest.mark.parametrize("kind", ["error", "response.failed"])
def test_upstream_errors_are_typed_and_do_not_stop_open_tools(code: str, category: str, expected: str, kind: str) -> None:
    """Upstream failure is observable, includes exact details, and is sticky."""
    error_data = {"code": code, "type": category, "message": "synthetic upstream failure", "opaque": [1, 2]}
    wire = record(kind, **({"error": error_data} if kind == "error" else {"response": {"status": "failed", "error": error_data}}))
    decoder = Decoder()
    decoder.feed(tool_start(arguments="{}"))
    with pytest.raises(StreamError) as error:
        decoder.feed(record("response.output_text.delta", delta="before error") + wire)
    exc = error.value
    assert isinstance(exc, ValueError)
    assert exc.exception_type == expected
    assert exc.message == str(exc) == "synthetic upstream failure"
    assert exc.events == [{"assistantResponseEvent": {"content": "before error"}}]
    assert exc.details["type"] == kind
    assert not decoder.completed and decoder.terminal_status == "failed"
    with pytest.raises(StreamError) as later:
        decoder.finalize()
    assert later.value is exc
    with pytest.raises(StreamError) as later:
        decoder.feed(b"")
    assert later.value is exc


@pytest.mark.parametrize("wire", [b"", b":heartbeat\n\n", record("response.created", response={"id": "r"}),
    record("response.output_text.delta", delta="partial"), b'data: {"type":"response.completed","response":{}}',
    terminal()[:-1], terminal() + b'data: {', b'data: {"delta":"\xf0\x9f'])
def test_eof_without_complete_framing_and_terminal_is_explicit_error(wire: bytes) -> None:
    """EOF is not completion, even after content or a partial completion record."""
    decoder = Decoder()
    decoder.feed(wire)
    with pytest.raises(StreamError) as error:
        decoder.finalize()
    assert error.value.exception_type == "ResponsesTruncatedStream"
    assert not decoder.completed


@pytest.mark.parametrize("wire", [
    b"data: [DONE]\n\n", b"data: not-json\n\n", b"data: []\n\n", b"data: null\n\n",
    b'data: {"type":"x","type":"y"}\n\n', b'data: {"type":"x","v":NaN}\n\n',
    b'data: {"type":"x","v":Infinity}\n\n', b'data: {"type":3}\n\n', b'data: {}\n\n',
    b'data: {"type":"response.output_text.delta","delta":1}\n\n',
    b'event: mismatch\ndata: {"type":"response.output_text.delta","delta":"x"}\n\n',
    b'data: {"type":"response.output_text.delta","delta":"\xff"}\n\n',
    record("response.output_text.delta", delta="x", output_index=-1),
    record("response.output_text.delta", delta="x", content_index=True),
    record("response.completed", response=[]), record("response.completed", response={"status": "incomplete"}),
    record("response.function_call_arguments.delta", item_id="missing", delta="{}"),
    record("response.output_item.added", item={"type": "function_call", "id": "t"}),
])
def test_malformed_records_raise_specific_stream_error(wire: bytes) -> None:
    """No malformed event is silently swallowed by broad parse fallbacks."""
    decoder = Decoder()
    with pytest.raises(StreamError) as error:
        decoder.feed(wire)
    assert error.value.exception_type in {"ResponsesProtocolError", "ResponsesTruncatedStream"}
    assert error.value.message
    assert not decoder.completed


def test_error_call_exposes_prior_outputs_but_not_previous_calls() -> None:
    """Chunk grouping must not make already valid outputs inaccessible on failure."""
    decoder = Decoder()
    assert decoder.feed(record("response.output_text.delta", delta="previous")) == [
        {"assistantResponseEvent": {"content": "previous"}}]
    with pytest.raises(StreamError) as error:
        decoder.feed(record("response.output_text.delta", delta="this call") + b"data: broken\n\n")
    assert error.value.events == [{"assistantResponseEvent": {"content": "this call"}}]


def test_conflicting_snapshots_fail_instead_of_dropping_changes() -> None:
    """Prefix reconciliation cannot hide contradictory completed text."""
    decoder = Decoder()
    decoder.feed(record("response.output_text.delta", item_id="m", delta="one"))
    with pytest.raises(StreamError, match="conflicts"):
        decoder.feed(record("response.output_text.done", item_id="m", text="two"))


def test_item_alias_collisions_and_ambiguous_tool_delta_fail() -> None:
    """Tool arguments must never be assigned to whichever tool was last seen."""
    for data in (record("response.function_call_arguments.delta", delta="{}"),
                 record("response.function_call_arguments.delta", output_index=0, item_id="item-1", delta="{}")):
        decoder = Decoder()
        decoder.feed(tool_start(0) + tool_start(1))
        with pytest.raises(StreamError):
            decoder.feed(data)


@pytest.mark.parametrize("tail", [terminal(), record("response.output_text.delta", delta="late"),
    b"data: [DONE]\n\ndata: [DONE]\n\n"])
def test_data_after_terminal_or_duplicate_done_is_error(tail: bytes) -> None:
    """Terminal responses cannot restart or silently consume a second response."""
    decoder = Decoder()
    decoder.feed(terminal())
    with pytest.raises(StreamError):
        decoder.feed(tail)
    assert not decoder.completed


def test_finalize_is_idempotent_feed_after_finalize_is_error() -> None:
    """A successful EOF check is repeatable, but the stream cannot be reopened."""
    decoder = Decoder()
    decoder.feed(terminal())
    assert decoder.completed and decoder.finalize() == decoder.finalize() == []
    with pytest.raises(StreamError, match="after finalize"):
        decoder.feed(b"")


@pytest.mark.parametrize("limits,wire", [
    ({"max_buffer_bytes": 32}, b"data: " + b"x" * 33),
    ({"max_buffer_bytes": 32}, b":comment\n" * 10),
    ({"max_buffer_bytes": 32}, b"data: {\ndata: " + b" " * 40),
    ({"max_state_bytes": 3}, record("response.output_text.delta", delta="abcd")),
    ({"max_stream_bytes": 8}, b":comment\n\n"),
    ({"max_items": 1}, tool_start(0) + tool_start(1)),
    ({"max_parts": 1}, record("response.output_text.delta", item_id="m", content_index=0, delta="a") +
                         record("response.output_text.delta", item_id="m", content_index=1, delta="b")),
    ({"max_events": 1}, record("response.output_text.delta", delta="a") + terminal()),
    ({"max_state_bytes": 4}, record("response.output_text.delta", item_id="oversize-identity", delta="")),
])
def test_each_stream_budget_is_enforced(limits: dict, wire: bytes) -> None:
    """Line, multiline, comments, state, identity, wire and collection counts are bounded."""
    decoder = Decoder(**limits)
    with pytest.raises(StreamError) as error:
        for byte in wire:
            decoder.feed(bytes([byte]))
    assert error.value.exception_type == "ResponsesBufferLimitExceeded"


@pytest.mark.parametrize("name", ["max_buffer_bytes", "max_state_bytes", "max_stream_bytes", "max_items", "max_parts", "max_events"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, None])
def test_invalid_limits_rejected(name: str, value: Any) -> None:
    """Invalid budgets are not coerced into surprising parser behavior."""
    with pytest.raises(ValueError, match="positive integers"):
        Decoder(**{name: value})


def test_large_feed_with_small_individual_records_is_not_a_buffer_overflow() -> None:
    """The buffer limit applies to records, not the size of a caller's chunk."""
    wire = record("response.output_text.delta", delta="a") * 100 + terminal()
    events, decoder = decoded(wire, max_buffer_bytes=100)
    assert len(select(events, "assistantResponseEvent")) == 100
    assert decoder.completed


@pytest.mark.parametrize("usage", [{"kiro:credits": {"value": True}}, {"kiro:credits": {"value": "1"}},
    {"kiro:context_usage_percentage": "10"}, {"kiro:credits": None}, []])
def test_usage_validation_does_not_synthesize_missing_stops_on_bad_terminal(usage: Any) -> None:
    """Validate terminal metadata before synthesizing missing stops for still-open calls."""
    decoder = Decoder()
    decoder.feed(tool_start(arguments="{}"))
    if usage == {"kiro:credits": None}:
        assert decoder.feed(terminal(usage=usage))
        assert decoder.completed
    else:
        with pytest.raises(StreamError) as error:
            decoder.feed(terminal(usage=usage))
        assert not select(error.value.events, "toolUseEvent")
        assert not decoder.completed


def test_response_identity_change_and_completed_incomplete_tool_fail() -> None:
    """Contradictory lifecycle/identity claims must remain explicit failures."""
    decoder = Decoder()
    decoder.feed(record("response.created", response={"id": "one"}))
    with pytest.raises(StreamError, match="response.id changed"):
        decoder.feed(terminal(id="two"))
    decoder = Decoder()
    decoder.feed(record("response.output_item.done", item=tool_item(arguments="{}", status="incomplete")))
    with pytest.raises(StreamError, match="incomplete tool"):
        decoder.feed(terminal())


def test_known_text_cannot_change_after_done() -> None:
    """Closed content parts reject further deltas, even if the delta is empty."""
    decoder = Decoder()
    decoder.feed(record("response.output_text.done", item_id="m", text="finished"))
    with pytest.raises(StreamError, match="after part completion"):
        decoder.feed(record("response.output_text.delta", item_id="m", delta=""))


def test_historical_tools_are_consumed_but_mixed_reasoning_is_an_error() -> None:
    """GHc declares only current tools; genuinely ambiguous reasoning remains invalid."""
    request = command()
    request["conversationState"]["history"] = [{"userInputMessage": {"content": "old", "userInputMessageContext": {
        "tools": [{"toolSpecification": {"name": "x", "inputSchema": {"json": {}}}}]}}}]
    assert "tools" not in build(request)
    assert build(request)["input"][0] == {"role": "user", "content": "old"}
    request["conversationState"]["history"] = [{"assistantResponseMessage": {"reasoningContent": {
        "reasoningText": {"text": "a"}, "redactedContent": "AA=="}}}]
    with pytest.raises(ValueError, match="exactly one"):
        build(request)


def test_added_reasoning_null_is_not_mistaken_for_completed_opaque_content() -> None:
    """Reasoning payloads may be absent while their item is still in progress."""
    wire = (record("response.output_item.added", output_index=0, item={"type": "reasoning", "id": "r",
            "status": "in_progress", "encrypted_content": None, "summary": []}) +
            record("response.reasoning_text.delta", item_id="r", delta="thought") +
            record("response.output_item.done", output_index=0, item={"type": "reasoning", "id": "r",
            "status": "completed", "encrypted_content": '{"reasoningText":{"text":"thought","signature":"sig"}}'}) + terminal())
    events, _ = decoded(wire)
    assert select(events, "reasoningContentEvent") == [{"text": "thought"},
        {"signature": "sig"}]
    assert select(events, "metadataEvent")[0]["upstreamEvent"]["item"]["encrypted_content"] is None


def test_unknown_fields_on_known_events_and_parts_are_not_lost() -> None:
    """Future opaque data is preserved even on otherwise familiar event types."""
    wire = (record("response.output_text.delta", item_id="m", delta="a", opaque={"signed": "raw"}) +
            record("response.content_part.done", item_id="m", part={"type": "output_text", "text": "a", "opaque": "raw"}) + terminal())
    events, _ = decoded(wire)
    assert select(events, "assistantResponseEvent") == [{"content": "a"}]
    raws = [e["upstreamEvent"] for e in select(events, "metadataEvent")]
    assert raws[0]["opaque"] == {"signed": "raw"}
    assert raws[1]["part"]["opaque"] == "raw"


def test_unknown_parts_preserve_one_raw_item_not_one_duplicate_per_part() -> None:
    """Raw fallback must not amplify a large unknown item into repeated payloads."""
    item = {"type": "message", "id": "m", "content": [{"type": "future", "opaque": str(i)} for i in range(10)]}
    decoder = Decoder()
    events = decoder.feed(record("response.output_item.done", item=item))
    assert len(events) == 1 and events[0]["metadataEvent"]["upstreamEvent"]["item"] == item
    decoder.feed(terminal())
    assert decoder.finalize() == []


@pytest.mark.parametrize("wire", [
    b'data: {"type":"future","value":1e9999}\n\n',
    b'data: {"type":"future","value":"\\ud800"}\n\n',
    record("response.content_part.done", part={"type": []}),
    record("response.output_item.done", item={"type": "function_call", "id": "t", "name": "t", "arguments": "{}", "content": None}),
    record("response.output_item.done", item={"type": "message", "content": [], "status": "future"}),
    record("response.output_item.done", item={"type": "message", "content": [], "role": "user"}),
    record("response.output_text.delta", delta="a", sequence_number=True),
])
def test_bad_future_shapes_never_leak_untyped_exceptions(wire: bytes) -> None:
    """Overflow, Unicode and malformed union discriminators use the same error API."""
    with pytest.raises(StreamError) as error:
        Decoder().feed(wire)
    assert error.value.exception_type == "ResponsesProtocolError"


def test_null_error_code_and_flat_error_record_use_typed_error_api() -> None:
    """Nullable upstream error codes do not hide the original error message."""
    for wire in (record("error", error={"code": None, "type": None, "message": "original"}),
                 record("error", code="rate_limit_exceeded", message="original")):
        with pytest.raises(StreamError, match="original") as error:
            Decoder().feed(wire)
        assert error.value.exception_type in {"InternalServerException", "ThrottlingException"}


@pytest.mark.parametrize("last", [3, 2])
def test_repeated_or_backwards_sequence_numbers_fail_without_reordering(last: int) -> None:
    """Replays are not a license to silently duplicate text or tool arguments."""
    decoder = Decoder()
    decoder.feed(record("response.output_text.delta", delta="a", sequence_number=3))
    with pytest.raises(StreamError, match="sequence_number"):
        decoder.feed(record("response.output_text.delta", delta="b", sequence_number=last))


def test_anonymous_text_item_completion_is_not_duplicated_in_final_output() -> None:
    """A sole unkeyed stream is correlated when the terminal snapshot adds an index."""
    item = {"type": "message", "content": [{"type": "output_text", "text": "same"}]}
    events, _ = decoded(record("response.output_text.delta", delta="same") +
                        record("response.output_item.done", item=item) + terminal(output=[item]))
    assert select(events, "assistantResponseEvent") == [{"content": "same"}]


def test_id_only_tool_fallback_and_partial_done_identity() -> None:
    """The observed id fallback is stable even when done omits call_id/name."""
    start = {"type": "function_call", "id": "only-id", "name": "t", "arguments": ""}
    end = {"type": "function_call", "id": "only-id", "arguments": "{}"}
    events, _ = decoded(record("response.output_item.added", item=start) +
                        record("response.function_call_arguments.done", item_id="only-id", arguments="{}") +
                        record("response.output_item.done", item=end) + terminal())
    assert select(events, "toolUseEvent") == [{"toolUseId": "only-id", "name": "t", "input": "", "stop": False},
        {"toolUseId": "only-id", "input": "{}", "stop": False}, {"toolUseId": "only-id", "stop": True}]


def test_completed_with_error_field_never_releases_tool_stop() -> None:
    """A contradictory error object takes precedence over claimed completion."""
    decoder = Decoder()
    decoder.feed(tool_start(arguments="{}"))
    with pytest.raises(StreamError, match="bad") as error:
        decoder.feed(terminal(error={"type": "server_error", "message": "bad"}))
    assert error.value.exception_type == "InternalServerException"
    assert not select(error.value.events, "toolUseEvent")


def test_state_budget_is_cumulative_and_request_expansion_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Many small deltas and repeated JSON escaping cannot bypass size budgets."""
    decoder = Decoder(max_state_bytes=4)
    decoder.feed(record("response.output_text.delta", delta="ab"))
    decoder.feed(record("response.output_text.delta", delta="cd"))
    with pytest.raises(StreamError) as error:
        decoder.feed(record("response.output_text.delta", delta="e"))
    assert error.value.exception_type == "ResponsesBufferLimitExceeded"
    monkeypatch.setattr(adapter, "MAX_REQUEST_BYTES", 800)
    with pytest.raises(ValueError, match="encoded request"):
        build(command(systemPrompt="\x00" * 150))


def test_deep_stream_json_is_an_explicit_failure() -> None:
    """Parser nesting cannot consume the host recursion limit unnoticed."""
    wire = b'data: {"type":"future","data":' + b"[" * 70 + b"0" + b"]" * 70 + b"}\n\n"
    with pytest.raises(StreamError):
        Decoder().feed(wire)


def test_signed_reasoning_multiple_parts_and_summary_only_do_not_duplicate() -> None:
    """Only exact full text, not summary text, can be paired with its signature."""
    plain = (record("response.reasoning_text.delta", item_id="r", content_index=0, delta="one") +
             record("response.reasoning_text.delta", item_id="r", content_index=1, delta="two"))
    summary = record("response.reasoning_summary_text.delta", item_id="r", summary_index=0, delta="summary")
    item = {"type": "reasoning", "id": "r", "encrypted_content": '{"reasoningText":{"text":"onetwo","signature":"sig"}}'}
    for prefix, expected in ((plain, ["one", "two"]), (summary, ["onetwo"])):
        events, _ = decoded(prefix + record("response.output_item.done", item=item) + terminal(output=[item]))
        assert [e["text"] for e in select(events, "reasoningContentEvent") if "text" in e] == expected
        assert select(events, "reasoningContentEvent")[-1] == {"signature": "sig"}


def test_signed_reasoning_missing_suffix_is_emitted_once() -> None:
    """The aggregate reconciliation preserves a nonstreamed terminal suffix."""
    item = {"type": "reasoning", "id": "r", "encrypted_content": '{"reasoningText":{"text":"thinking","signature":"sig"}}'}
    events, _ = decoded(record("response.reasoning_text.delta", item_id="r", delta="think") +
                        record("response.output_item.done", item=item) + terminal(output=[item]))
    assert [e["text"] for e in select(events, "reasoningContentEvent") if "text" in e] == ["think", "ing"]


@pytest.mark.parametrize("wire", [
    record("response.output_item.done", item={"type": "future_item", "opaque": "keep"}),
    record("response.content_part.done", part={"type": "future_part", "opaque": "keep"}),
    record("response.content_part.done", part={"type": "summary_text", "text": "wrong-family"}),
])
def test_future_items_and_wrong_family_parts_are_preserved_not_reinterpreted(wire: bytes) -> None:
    """Unknown content produces raw metadata, not fabricated assistant text."""
    decoder = Decoder()
    events = decoder.feed(wire)
    assert len(events) == 1 and "upstreamEvent" in events[0]["metadataEvent"]
    decoder.feed(terminal())
    assert decoder.finalize() == []


def test_terminal_id_null_optional_details_and_increasing_sequence() -> None:
    """A terminal-only lifecycle may introduce its response ID and null details."""
    decoder = Decoder()
    decoder.feed(record("response.output_text.delta", delta="x", sequence_number=0))
    events = decoder.feed(record("response.completed", sequence_number=2,
                                 response={"id": "r", "status": "completed", "incomplete_details": None}))
    assert select(events, "metadataEvent")[-1]["responseId"] == "r"
    assert decoder.finalize() == []


@pytest.mark.parametrize("first,second", [
    (record("response.output_text.delta", item_id="m", delta="x"),
     record("response.reasoning_text.delta", item_id="m", delta="x")),
    (tool_start(0), record("response.output_item.done", output_index=0, item={**tool_item(0, "{}"), "id": "changed"})),
    (tool_start(0), record("response.output_item.done", output_index=0, item={**tool_item(0, "{}"), "name": "changed"})),
    (record("response.output_item.done", item={"type": "message", "id": "m", "content": [{"type": "output_text", "text": "x"}]}),
     record("response.output_text.delta", item_id="m", delta="x")),
    (record("response.output_item.done", item={"type": "reasoning", "id": "r", "encrypted_content": '{"redactedContent":"AA=="}'}),
     record("response.output_item.done", item={"type": "reasoning", "id": "r", "encrypted_content": '{"redactedContent":"AQ=="}'})),
    (record("response.created", response={"id": "one"}), record("response.in_progress", response={"id": "two"})),
    (record("response.output_item.added", item={"type": "function_call", "id": "one", "call_id": "clash", "name": "t"}),
     record("response.output_item.added", item={"type": "function_call", "id": "clash", "name": "t"})),
])
def test_identity_kind_name_and_opaque_mutations_fail(first: bytes, second: bytes) -> None:
    """Completed snapshots cannot silently change identity, item kind or opaque data."""
    decoder = Decoder()
    decoder.feed(first)
    with pytest.raises(StreamError):
        decoder.feed(second)


def test_raw_bytes_in_tool_json_are_not_implicitly_serialized() -> None:
    """Binary support is explicitly scoped to media/redacted reasoning, not JSON."""
    value = command()
    value["conversationState"]["history"] = [{"assistantResponseMessage": {"toolUses": [
        {"toolUseId": "c", "name": "t", "input": {"binary": b"raw"}}]}}]
    with pytest.raises(ValueError, match="JSON data"):
        build(value)


def test_feed_type_and_exact_record_byte_boundary() -> None:
    """Nonbytes and one-byte-over-budget delimiters fail through the stream API."""
    with pytest.raises(StreamError, match="requires bytes"):
        Decoder().feed("not bytes")
    wire = record("response.output_text.delta", delta="x")
    assert Decoder(max_buffer_bytes=len(wire)).feed(wire) == [{"assistantResponseEvent": {"content": "x"}}]
    with pytest.raises(StreamError) as error:
        Decoder(max_buffer_bytes=len(wire) - 1).feed(wire)
    assert error.value.exception_type == "ResponsesBufferLimitExceeded"


@pytest.mark.parametrize("bad", [None, [], {}, 0, True, "", "x"])
def test_finite_wrong_type_matrix_has_only_typed_protocol_errors(bad: Any) -> None:
    """Probe malformed event leaves without relying on network or a schema engine."""
    candidates = [
        record("response.output_item.done", item=bad),
        record("response.content_part.done", part=bad),
        record("response.completed", response=bad),
        record("error", error=bad),
        record("response.output_text.delta", delta=bad),
        record("response.output_item.done", item={"type": "reasoning", "content": bad}),
        record("response.output_item.done", item={"type": "message", "content": bad}),
    ]
    for wire in candidates:
        decoder = Decoder()
        try:
            decoder.feed(wire)
            if decoder.terminal_status is None:
                decoder.feed(terminal())
            decoder.finalize()
        except StreamError:
            pass  # Any noncontract exception escapes and fails the test.


@pytest.mark.parametrize("task", ["vibe", "spectask"])
@pytest.mark.parametrize("trigger", ["MANUAL", "DIAGNOSTIC", "INLINE_CHAT"])
@pytest.mark.parametrize("status", ["success", "error"])
def test_normal_generate_command_consumes_local_fields_without_cloud_additions(task: str, trigger: str, status: str) -> None:
    """luo/WHc/uuo omit these SDK-local fields; output/status text stays literal."""
    request = command(agentMode="independent-mode", origin="CLI")
    state = request["conversationState"]
    state.update(agentTaskType=task, chatTriggerType=trigger)
    state["history"] = [
        {"assistantResponseMessage": {"toolUses": [{"toolUseId": "old-call", "name": "fixture", "input": {}}]}},
        {"userInputMessage": {"content": "history", "userInputMessageContext": {"toolResults": [
            {"toolUseId": "old-call", "status": status, "content": [{"text": "literal historical output"}]}]}}},
        {"assistantResponseMessage": {"toolUses": [{"toolUseId": "new-call", "name": "fixture", "input": {}}]}},
    ]
    user = state["currentMessage"]["userInputMessage"]
    user["userInputMessageContext"] = {"toolResults": [
        {"toolUseId": "new-call", "status": status, "content": [{"text": "error text is already here"}, {"text": ""}, {"text": "last line"}]}]}
    before = copy.deepcopy(request)
    expected = copy.deepcopy(request)
    del expected["conversationState"]["agentTaskType"]
    del expected["conversationState"]["chatTriggerType"]
    del expected["conversationState"]["history"][1]["userInputMessage"]["userInputMessageContext"]["toolResults"][0]["status"]
    del expected["conversationState"]["currentMessage"]["userInputMessage"]["userInputMessageContext"]["toolResults"][0]["status"]
    payload = build(request)
    assert payload == build(expected)
    assert payload["metadata"] == {"kiro:agent_mode": "independent-mode"}
    results = [item for item in payload["input"] if item.get("type") == "function_call_output"]
    assert results == [
        {"type": "function_call_output", "call_id": "old-call", "output": "literal historical output"},
        {"type": "function_call_output", "call_id": "new-call", "output": "error text is already here\n\nlast line"},
    ]
    assert request == before


def test_generate_routing_and_tool_history_follow_luo_uuo_ghc() -> None:
    """Top command routing wins; only current tools, never historical ones, are sent."""
    request = command(origin="CLI")
    old_tool = {"toolSpecification": {"name": "old", "description": "old declaration", "inputSchema": {"json": {"type": "object"}}}}
    new_tool = {"toolSpecification": {"name": "new", "inputSchema": {"json": {"type": "object"}}}}
    request["conversationState"]["history"] = [{"userInputMessage": {
        "content": "old model turn", "modelId": "old-model", "origin": "AI_EDITOR",
        "userInputMessageContext": {"tools": [old_tool]}}}]
    request["conversationState"]["currentMessage"]["userInputMessage"].update(
        modelId="stale-routing-label", origin="CHATBOT", userInputMessageContext={"tools": [new_tool]})
    result = build(request)
    assert result["model"] == "synthetic-model" and result["origin"] == "CLI"
    assert result["tools"] == [{"type": "function", "name": "new", "parameters": {"type": "object"}}]
    assert result["input"] == [{"role": "user", "content": "old model turn"}, {"role": "user", "content": "hello"}]
    assert "metadata" not in result  # Task type or routing labels must not invent mode metadata.


@pytest.mark.parametrize("key,value", [("agentTaskType", "future"), ("agentTaskType", None),
    ("agentTaskType", []), ("chatTriggerType", "manual"), ("chatTriggerType", True), ("chatTriggerType", "FUTURE")])
def test_unrecognized_local_enum_values_remain_actionable(key: str, value: Any) -> None:
    """Known omissions are scoped to the shipped enums, not a blanket ignore list."""
    request = command()
    request["conversationState"][key] = value
    with pytest.raises(ValueError, match=key):
        build(request)


@pytest.mark.parametrize("status", [None, "failed", True, "", {}])
def test_unrecognized_tool_result_status_is_not_silently_consumed(status: Any) -> None:
    """Only the source enum success/error receives the explicit consume semantics."""
    request = command()
    request["conversationState"]["currentMessage"]["userInputMessage"]["userInputMessageContext"] = {"toolResults": [
        {"toolUseId": "c", "status": status, "content": [{"text": "preserved"}]}]}
    with pytest.raises(ValueError, match="status"):
        build(request)


@pytest.mark.parametrize("field,value", [("temperature", 0.7), ("stop", ["END"]),
    ("max_output_tokens", 256), ("inferenceConfig", {"maxTokens": 256})])
def test_generation_parameters_still_require_an_explicit_responses_mapping(field: str, value: Any) -> None:
    """Consuming SDK-local fields must not make generation controls disappear."""
    request = command(additionalModelRequestFields={field: value})
    request["conversationState"].update(agentTaskType="vibe", chatTriggerType="MANUAL")
    with pytest.raises(ValueError) as error:
        build(request)
    assert field in str(error.value) and "no source-supported mapping" in str(error.value)


@pytest.mark.parametrize("canonical", [
    {"text": "exact \u4e2d\n\x00 text", "signature": "\n exact-signature/+= \n"},
    {"text": "", "signature": "sig"}, {"text": "unsigned"}, {"text": "", "signature": ""},
    {"redactedContent": "AP8="},
])
def test_public_reasoning_codec_semantic_round_trip(canonical: dict) -> None:
    """The exported pair uses ONLY parent fields and the source JSON union."""
    before = copy.deepcopy(canonical)
    wire = encode_reasoning(canonical)
    assert decode_reasoning(wire) == canonical
    assert canonical == before
    assert set(decode_reasoning(wire)) <= {"text", "signature", "redactedContent"}
    expected = canonical if "redactedContent" in canonical else {"reasoningText": canonical}
    assert json.loads(wire) == expected
    # Codec JSON whitespace does not alter opaque content or canonical replay.
    assert encode_reasoning(decode_reasoning(json.dumps(expected, indent=2))) == wire
    decoded_value = decode_reasoning(wire)
    decoded_value[next(iter(decoded_value))] = "changed"
    assert canonical == before


@pytest.mark.parametrize("data", [b"\x00\xff", bytearray(b"\x00\xff"), [0, 255], "AP8="])
def test_public_reasoning_codec_binary_forms_use_canonical_base64(data: Any) -> None:
    """SDK bytes and the parent's JSON base64 produce the same L3r envelope."""
    assert encode_reasoning({"redactedContent": data}) == '{"redactedContent":"AP8="}'
    assert decode_reasoning(encode_reasoning({"redactedContent": data})) == {"redactedContent": "AP8="}


@pytest.mark.parametrize("opaque_bytes", [b"\x00\xff\x80opaque provider bytes\x00", b'{"id":"r-fixture","encrypted_content":"opaque/+=not-interpreted"}'])
def test_opaque_reasoning_cloud_to_canonical_to_generate_round_trip(opaque_bytes: bytes) -> None:
    """Provider ciphertext/L6e-style payload bytes survive without invented cloud fields."""
    opaque_base64 = base64.b64encode(opaque_bytes).decode("ascii")
    original_wire = encode_reasoning({"redactedContent": opaque_base64})
    item = {"type": "reasoning", "id": "transport-item", "encrypted_content": original_wire}
    events, _ = decoded(record("response.output_item.done", output_index=0, item=item) + terminal(output=[item]), step=1)
    canonical = select(events, "reasoningContentEvent")
    assert canonical == [{"redactedContent": opaque_base64}]
    assert base64.b64decode(canonical[0]["redactedContent"]) == opaque_bytes
    request = command()
    request["conversationState"].update(agentTaskType="vibe", chatTriggerType="MANUAL", history=[
        {"assistantResponseMessage": {"reasoningContent": canonical[0]}}])
    replay = build(request)["input"][0]
    assert replay == {"type": "reasoning", "summary": [], "encrypted_content": original_wire}
    assert "id" not in replay and json.loads(replay["encrypted_content"]) == {"redactedContent": opaque_base64}


def test_signed_reasoning_canonical_accumulation_replays_exact_text_and_signature() -> None:
    """No dropped encryptedContent field is needed by the parent's signed-block ledger."""
    canonical = {"text": "prefix and final suffix", "signature": "exact sig/+=="}
    item = {"id": "r", "type": "reasoning", "encrypted_content": encode_reasoning(canonical)}
    events, _ = decoded(record("response.reasoning_text.delta", item_id="r", delta="prefix") +
                        record("response.output_item.done", item=item) + terminal(output=[item]))
    reconstructed = {"text": "", "signature": ""}
    for event in select(events, "reasoningContentEvent"):
        assert event.keys() <= {"text", "signature"}
        reconstructed["text"] += event.get("text", "")
        reconstructed["signature"] += event.get("signature", "")
    assert reconstructed == canonical
    assert encode_reasoning(reconstructed) == item["encrypted_content"]
    request = command()
    request["conversationState"]["history"] = [{"assistantResponseMessage": {
        "reasoningContent": {"reasoningText": reconstructed}}}]
    assert build(request)["input"][0]["encrypted_content"] == item["encrypted_content"]


@pytest.mark.parametrize("canonical", [
    {}, {"signature": "signature-without-text"}, {"text": None}, {"text": "x", "signature": 7},
    {"text": "x", "redactedContent": "AA=="}, {"signature": "s", "redactedContent": "AA=="},
    {"redactedContent": "not base64"}, {"redactedContent": ""}, {"redactedContent": b""},
    {"encryptedContent": "unmapped"}, {"text": "x", "future": "unknown"},
])
def test_codec_rejects_unsupported_canonical_shapes(canonical: dict) -> None:
    """The helper cannot synthesize text, signatures, or unestablished opaque wrappers."""
    with pytest.raises(ValueError):
        encode_reasoning(canonical)


@pytest.mark.parametrize("wire", [
    "not-json", "", "null", "[]", "{}", '{"reasoningText":{"signature":"s"}}',
    '{"reasoningText":{"text":"t","signature":null}}', '{"reasoningText":{"text":"t","future":1}}',
    '{"redactedContent":[]}', '{"redactedContent":""}', '{"redactedContent":"?"}',
    '{"reasoningText":{"text":"t"},"redactedContent":"AA=="}',
    '{"reasoningText":{"text":"t"},"future":1}', '{"encryptedContent":"opaque"}',
])
def test_codec_rejects_unrepresentable_cloud_envelopes(wire: str) -> None:
    """No unknown ciphertext is silently converted to a new cloud schema."""
    with pytest.raises(ValueError, match="encrypted_content"):
        decode_reasoning(wire)


def test_standalone_encrypted_content_request_has_no_unverified_passthrough() -> None:
    """The source-aligned SDK union, not an extra cloud alias, is the replay API."""
    request = command()
    request["conversationState"]["history"] = [{"assistantResponseMessage": {
        "reasoningContent": {"encryptedContent": "opaque"}}}]
    with pytest.raises(ValueError, match="encryptedContent"):
        build(request)


def test_codec_budgets_are_enforced_before_decode_and_after_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exported helpers retain finite limits independently of payload/SSE entrypoints."""
    monkeypatch.setattr(adapter, "MAX_REQUEST_BYTES", 100)
    with pytest.raises(ValueError, match="budget"):
        encode_reasoning({"text": "x" * 100})
    with pytest.raises(ValueError, match="budget"):
        decode_reasoning('{"reasoningText":{"text":"' + "x" * 100 + '"}}')
    monkeypatch.setattr(adapter, "MAX_REQUEST_BYTES", 150)
    with pytest.raises(ValueError, match="encoded reasoning"):
        encode_reasoning({"text": "\x00" * 25})


def test_codec_helpers_are_explicitly_exported() -> None:
    """The parent can integrate the stable codec without relying on private helpers."""
    assert set(adapter.__all__) == {"build_responses_payload", "ResponsesSSEDecoder", "ResponsesStreamError",
                                   "encode_reasoning_envelope", "decode_reasoning_envelope"}


@pytest.mark.parametrize("canonical", [{"text": "exact", "signature": "sig"}, {"redactedContent": "AP8="}])
def test_semantically_identical_envelope_snapshots_do_not_duplicate_events(canonical: dict) -> None:
    """Envelope JSON whitespace differs from the opaque content inside the codec."""
    encoded = encode_reasoning(canonical)
    initial = {"type": "reasoning", "id": "r", "encrypted_content": encoded}
    repeated = {**initial, "encrypted_content": json.dumps(json.loads(encoded), indent=2)}
    events, _ = decoded(record("response.output_item.done", item=initial) + terminal(output=[repeated]))
    expected = [{"redactedContent": "AP8="}] if "redactedContent" in canonical else [{"text": "exact"}, {"signature": "sig"}]
    assert select(events, "reasoningContentEvent") == expected


def test_task_type_does_not_become_an_invented_agent_mode() -> None:
    """Task kind is local; absent agentMode remains absent from Responses metadata."""
    request = command()
    request["conversationState"].update(agentTaskType="spectask", chatTriggerType="MANUAL")
    assert "metadata" not in build(request)


@pytest.mark.parametrize("limit", [1, 2, 256, 1024, 8192, 200_001, 2**31, 2**53 + 1, 2**160 + 7])
def test_schema_backed_max_tokens_mapping_preserves_exact_positive_integer(limit: int) -> None:
    """CreateResponseRequest$ models max_output_tokens; no model cap is inferred."""
    request = command(additionalModelRequestFields={"max_tokens": limit})
    request["conversationState"].update(agentTaskType="vibe", chatTriggerType="MANUAL")
    before = copy.deepcopy(request)
    actual = build(request)
    expected = build(command())
    expected["max_output_tokens"] = limit
    assert actual == expected
    assert type(actual["max_output_tokens"]) is int
    assert json.loads(json.dumps(actual))["max_output_tokens"] == limit
    assert "max_tokens" not in actual and "additionalModelRequestFields" not in actual
    assert request == before


@pytest.mark.parametrize("limit", [0, -1, -1024, True, False, 1.0, 1.5, "1024", "", None, [], {}])
def test_max_tokens_requires_positive_integer_without_coercion(limit: Any) -> None:
    """Required facade output limits must not become absent, rounded or coerced."""
    with pytest.raises(ValueError) as error:
        build(command(additionalModelRequestFields={"max_tokens": limit}))
    assert "additionalModelRequestFields.max_tokens" in str(error.value)
    assert "positive integer" in str(error.value)


@pytest.mark.parametrize("fields,reasoning", [
    ({"reasoning": {"effort": "high"}}, {"effort": "high"}),
    ({"output_config": {"effort": "low"}}, {"effort": "low"}),
    ({"thinking": {"type": "disabled"}}, {"effort": "none"}),
    ({"output_config": {"effort": "high"}, "reasoning": {"effort": "high"}}, {"effort": "high"}),
    ({"thinking": {"type": "disabled"}, "reasoning": {"effort": "none"}}, {"effort": "none"}),
])
def test_max_tokens_mapping_composes_with_existing_effort_controls(fields: dict, reasoning: dict) -> None:
    """An output-token limit coexists with effort without masking either control."""
    payload = build(command(additionalModelRequestFields={"max_tokens": 4097, **fields}))
    assert payload["max_output_tokens"] == 4097
    assert payload["reasoning"] == reasoning


@pytest.mark.parametrize("extra", [
    {"thinking": {"type": "adaptive", "budget_tokens": 1024}},
    {"thinking": {"type": "disabled", "budget_tokens": 1024}},
    {"reasoning": {"effort": "high", "budget_tokens": 1024}},
    {"output_config": {"effort": "high", "budget_tokens": 1024}},
    {"budget_tokens": 1024},
])
def test_output_limit_support_does_not_silently_accept_thinking_budgets(extra: dict) -> None:
    """The verified output limit is not evidence for any thinking-budget alias."""
    with pytest.raises(ValueError) as error:
        build(command(additionalModelRequestFields={"max_tokens": 4096, **extra}))
    assert "budget_tokens" in str(error.value)
    assert "no source-supported mapping" in str(error.value)


def test_max_tokens_does_not_mask_conflicting_effort() -> None:
    """Supporting one mapped parameter does not discard incompatible reasoning settings."""
    with pytest.raises(ValueError, match="conflicting reasoning effort"):
        build(command(additionalModelRequestFields={"max_tokens": 4096,
            "output_config": {"effort": "low"}, "reasoning": {"effort": "high"}}))


@pytest.mark.parametrize("input_command", [command(), command(additionalModelRequestFields={})])
def test_missing_max_tokens_does_not_invent_an_output_limit(input_command: dict) -> None:
    """There is no adapter default, minimum insertion, or automatic limit inference."""
    assert "max_output_tokens" not in build(input_command)


def test_output_limit_alias_is_scoped_to_additional_model_request_fields() -> None:
    """No unrelated top-level or neighboring cloud-schema controls become accepted."""
    for field in ("max_tokens", "max_output_tokens", "maxOutputTokens"):
        with pytest.raises(ValueError, match=field):
            build(command(**{field: 256}))
    with pytest.raises(ValueError, match="max_tokens"):
        build(command(additionalModelRequestFields={"output_config": {"effort": "high", "max_tokens": 256}}))


def tool_done_signal(kind: str, arguments: str = "{}", index: int = 0) -> bytes:
    """Encode either independently completed tool signal for focused order tests."""
    if kind == "arguments":
        return record("response.function_call_arguments.done", item_id=f"item-{index}", arguments=arguments)
    assert kind == "item"
    return record("response.output_item.done", output_index=index, item=tool_item(index, arguments, status="completed"))


@pytest.mark.parametrize("kind", ["arguments", "item"])
def test_valid_done_signal_emits_suffix_then_stop_before_following_text(kind: str) -> None:
    """A stop belongs to the done record, not to a later global completion record."""
    decoder = Decoder()
    initial = decoder.feed(tool_start(arguments='{"x":'))
    assert not any(e.get("stop") for e in select(initial, "toolUseEvent"))
    done = decoder.feed(tool_done_signal(kind, '{"x":1}') +
                        record("response.output_text.delta", item_id="message", output_index=1, delta="after tool"))
    assert done == [
        {"toolUseEvent": {"toolUseId": "call-0", "input": "1}", "stop": False}},
        {"toolUseEvent": {"toolUseId": "call-0", "stop": True}},
        {"assistantResponseEvent": {"content": "after tool"}},
    ]
    assert not decoder.completed and decoder.terminal_status is None
    message = {"type": "message", "id": "message", "role": "assistant", "content": [{"type": "output_text", "text": "after tool"}]}
    final = decoder.feed(terminal(output=[tool_item(arguments='{"x":1}'), message]))
    assert not select(final, "toolUseEvent") and not select(final, "assistantResponseEvent")
    assert decoder.completed and decoder.finalize() == []


@pytest.mark.parametrize("first,second", [("arguments", "item"), ("item", "arguments")])
def test_first_done_signal_wins_repeated_done_and_completion_do_not_repeat_stop(first: str, second: str) -> None:
    """Deduplication is per tool even when both forms of done are repeated."""
    decoder = Decoder()
    decoder.feed(tool_start(arguments="{}"))
    assert decoder.feed(tool_done_signal(first)) == [{"toolUseEvent": {"toolUseId": "call-0", "stop": True}}]
    assert decoder.feed(tool_done_signal(first) + tool_done_signal(second) + tool_done_signal(second)) == []
    assert not decoder.completed
    assert not select(decoder.feed(terminal(output=[tool_item(arguments="{}")])), "toolUseEvent")
    assert decoder.finalize() == []


@pytest.mark.parametrize("kind", ["arguments", "item"])
@pytest.mark.parametrize("failure_kind", ["error", "response.failed"])
@pytest.mark.parametrize("same_feed", [False, True])
def test_early_tool_stop_does_not_hide_subsequent_upstream_failure(kind: str, failure_kind: str, same_feed: bool) -> None:
    """Earlier tool completion remains ordered output, never whole-response success."""
    error_data = {"type": "server_error", "message": "synthetic failure after completed tool"}
    failure = record(failure_kind, **({"error": error_data} if failure_kind == "error" else
                                    {"response": {"status": "failed", "error": error_data}}))
    prefix = tool_start(arguments="{}") + tool_done_signal(kind) + record("response.output_text.delta", delta="between tool and failure")
    decoder = Decoder()
    earlier = [] if same_feed else decoder.feed(prefix)
    assert not decoder.completed
    with pytest.raises(StreamError) as error:
        decoder.feed(prefix + failure if same_feed else failure)
    outputs = earlier + error.value.events
    assert outputs == [
        {"toolUseEvent": {"toolUseId": "call-0", "name": "tool_0", "input": "{}", "stop": False}},
        {"toolUseEvent": {"toolUseId": "call-0", "stop": True}},
        {"assistantResponseEvent": {"content": "between tool and failure"}},
    ]
    assert error.value.exception_type == "InternalServerException"
    assert decoder.terminal_status == "failed" and not decoder.completed
    assert not select(outputs, "metadataEvent")
    with pytest.raises(StreamError) as finalized:
        decoder.finalize()
    assert finalized.value is error.value


@pytest.mark.parametrize("kind", ["arguments", "item"])
def test_incomplete_keeps_completed_tool_without_stopping_partial_tool(kind: str) -> None:
    """Terminal incomplete snapshots may fill output but never close unfinished calls."""
    decoder = Decoder()
    earlier = decoder.feed(tool_start(0, "{}") + tool_start(1, '{"partial":') + tool_done_signal(kind, index=0))
    assert [e for e in select(earlier, "toolUseEvent") if e.get("stop")] == [{"toolUseId": "call-0", "stop": True}]
    final = decoder.feed(terminal("incomplete", output=[tool_item(0, "{}", status="completed"),
                                tool_item(1, '{"partial":', status="incomplete")],
                                 incomplete_details={"reason": "max_output_tokens"}))
    assert not select(final, "toolUseEvent")
    assert select(final, "metadataEvent")[-1]["stopReason"] == "MAX_TOKENS"
    assert decoder.terminal_status == "incomplete" and not decoder.completed
    assert decoder.finalize() == []


@pytest.mark.parametrize("kind", ["arguments", "item"])
@pytest.mark.parametrize("arguments", ["", "{", '{"x":', "[]", "null", '"scalar"', '{"x":NaN}', '{"x":1,"x":2}'])
def test_invalid_arguments_declared_done_fail_without_any_stop(kind: str, arguments: str) -> None:
    """A malformed declared completion must not authorize partial tool execution."""
    decoder = Decoder()
    decoder.feed(tool_start())
    with pytest.raises(StreamError) as error:
        decoder.feed(tool_done_signal(kind, arguments))
    assert error.value.exception_type == "ResponsesProtocolError"
    assert not any(e.get("stop") for e in select(error.value.events, "toolUseEvent"))
    assert not decoder.completed
    with pytest.raises(StreamError) as later:
        decoder.feed(terminal())
    assert later.value is error.value


@pytest.mark.parametrize("arguments", ["", '{"partial":', "{}"])
def test_explicit_incomplete_item_done_is_not_a_tool_stop(arguments: str) -> None:
    """An incomplete item status overrides syntactic completeness of its argument text."""
    decoder = Decoder()
    decoder.feed(tool_start())
    pending = decoder.feed(record("response.output_item.done", output_index=0, item=tool_item(arguments=arguments, status="incomplete")))
    assert not any(e.get("stop") for e in select(pending, "toolUseEvent"))
    final = decoder.feed(terminal("incomplete", incomplete_details={"reason": "max_output_tokens"}))
    assert not select(final, "toolUseEvent")
    assert not decoder.completed and decoder.finalize() == []


@pytest.mark.parametrize("kind", ["arguments", "item"])
def test_early_tool_stop_does_not_turn_truncated_eof_into_completion(kind: str) -> None:
    """A valid completed tool does not satisfy the required response terminal event."""
    decoder = Decoder()
    decoder.feed(tool_start(arguments="{}"))
    assert decoder.feed(tool_done_signal(kind)) == [{"toolUseEvent": {"toolUseId": "call-0", "stop": True}}]
    with pytest.raises(StreamError) as error:
        decoder.finalize()
    assert error.value.exception_type == "ResponsesTruncatedStream"
    assert error.value.events == [] and not decoder.completed


@pytest.mark.parametrize("kind", ["arguments", "item"])
def test_bad_terminal_metadata_does_not_erase_or_repeat_early_tool_stop(kind: str) -> None:
    """A subsequent protocol failure cannot retroactively replace earlier ordered events."""
    decoder = Decoder()
    prefix = tool_start(arguments="{}") + tool_done_signal(kind)
    with pytest.raises(StreamError) as error:
        decoder.feed(prefix + terminal(output=[tool_item(arguments="{}")], usage={"kiro:credits": {"value": "bad"}}))
    assert [e for e in select(error.value.events, "toolUseEvent") if e.get("stop")] == [{"toolUseId": "call-0", "stop": True}]
    assert not select(error.value.events, "metadataEvent") and not decoder.completed


def test_complete_arguments_without_done_signal_do_not_stop_early() -> None:
    """A valid JSON prefix alone is not a protocol-level completion signal."""
    decoder = Decoder()
    initial = decoder.feed(tool_start(arguments="{}") + b": heartbeat\n\n")
    assert not any(e.get("stop") for e in select(initial, "toolUseEvent"))
    assert not decoder.completed
    final = decoder.feed(terminal(output=[tool_item(arguments="{}")]))
    assert select(final, "toolUseEvent") == [{"toolUseId": "call-0", "stop": True}]
    assert decoder.completed and decoder.finalize() == []


def test_terminal_snapshots_fill_missing_calls_without_repeating_stopped_calls() -> None:
    """Final output fallback remains available only for genuinely missing events."""
    decoder = Decoder()
    earlier = decoder.feed(tool_start(arguments="{}") + tool_done_signal("arguments"))
    assert select(earlier, "toolUseEvent")[-1] == {"toolUseId": "call-0", "stop": True}
    final = decoder.feed(terminal(output=[tool_item(0, "{}"), tool_item(1, '{"new":1}')]))
    assert select(final, "toolUseEvent") == [
        {"toolUseId": "call-1", "name": "tool_1", "input": '{"new":1}', "stop": False},
        {"toolUseId": "call-1", "stop": True},
    ]
    assert decoder.finalize() == []


def test_tool_done_order_is_independent_of_sse_byte_chunking() -> None:
    """Coalesced and bytewise SSE feeds retain the same interleaved stop positions."""
    wire = (tool_start(0) + tool_start(1) + tool_done_signal("arguments", '{"x":1}', 1) +
            record("response.output_text.delta", item_id="m", output_index=2, delta="between") +
            tool_done_signal("item", '{"x":0}', 0) +
            terminal(output=[tool_item(0, '{"x":0}'), tool_item(1, '{"x":1}')]))
    expected, _ = decoded(wire)
    bytewise, _ = decoded(wire, step=1)
    assert bytewise == expected
    for split in range(len(wire) + 1):
        decoder = Decoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) + decoder.finalize() == expected
