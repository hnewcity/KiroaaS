"""Offline proof boundaries and lifetime of gateway-native projection receipts."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
import json

import pytest

from kiro.native_reasoning import (
    NativeMessageLedger, NativeReasoningError, ReasoningStore,
    reasoning_blocks, restore_native_projections,
)
from kiro.streaming_core import KiroEvent

SCOPE = ("client", "account", "model")


def fixture_projection(anthropic: bool = True, *, store: ReasoningStore | None = None,
                       record: bool = True) -> tuple[Any, ...]:
    """Build independent original/visible fixtures, not a client receipt API."""
    store = store if store is not None else ReasoningStore()
    ledger = NativeMessageLedger()
    for event in [
        KiroEvent(type="native_reasoning", reasoning={"text": "thought", "signature": "signature"}),
        KiroEvent(type="content", content="before"),
        KiroEvent(type="tool_use", tool_use={"id": "original-id", "function": {
            "name": "web_search", "arguments": '{"query":"query","limit":1}'}}),
        KiroEvent(type="native_reasoning", reasoning={"redactedContent": "AP8B"}),
        KiroEvent(type="content", content="after"),
    ]:
        ledger.feed(event)
    visible_search = [
        {"type": "server_tool_use", "id": "mcp-id", "name": "web_search", "input": {"query": "query"}},
        {"type": "web_search_tool_result", "tool_use_id": "mcp-id", "content": [
            {"type": "web_search_result", "title": "title", "url": "https://example.invalid", "encrypted_content": "snippet", "page_age": None, "score": 1}]},
        {"type": "text", "text": "summary"},
    ]
    visible = deepcopy(ledger.blocks[:2] + visible_search + ledger.blocks[3:])
    exchanges = {2: {"original": ledger.blocks[2], "visible": visible_search,
                     "result": '{"result":{"results":[]},"summary":"summary"}'}}
    identity = SimpleNamespace(conversation_id="conversation", root_conversation_id="root", continuation_id="turn")
    if record:
        store.record(SCOPE, identity, "anchor", ledger)
    canonical = visible if anthropic else {"content": "beforesummaryafter", "tool_calls": [],
                                           "reasoning_details": reasoning_blocks(ledger.blocks)}
    store.record_projection(SCOPE, identity, "anchor", ledger, exchanges, anthropic=anthropic, emitted=canonical)
    message = {"role": "assistant", "content": visible} if anthropic else {"role": "assistant", **canonical}
    return store, ledger, identity, exchanges, canonical, message


@pytest.mark.parametrize("anthropic", [True, False])
def test_exact_replay_restores_original_state_and_keeps_caller_content(anthropic: bool) -> None:
    store, ledger, _, _, _, message = fixture_projection(anthropic)
    caller = {"role": "user", "content": [{"type": "text", "text": "caller summary text must stay"},
                                          {"type": "image", "source": {"data": "caller-image"}}]}
    before = deepcopy([message, caller])
    restored = restore_native_projections([message, caller], scope=SCOPE, anthropic=anthropic, store=store)
    assert [message, caller] == before
    assert restored[-1] is caller
    original = restored[0]
    if anthropic:
        assert original["content"] == ledger.blocks
        result = restored[1]["content"][0]
        assert result["tool_use_id"] == "original-id"
        assert json.loads(result["content"])["summary"] == "summary"
    else:
        assert original["content"] == "beforeafter"
        assert original["tool_calls"][0]["id"] == "original-id"
        assert original["reasoning_details"] == reasoning_blocks(ledger.blocks)
        assert restored[1]["tool_call_id"] == "original-id"
    # Restoring twice is safe; no duplicate generated tool results.
    assert restore_native_projections(restored, scope=SCOPE, anthropic=anthropic, store=store) == restored
    original = deepcopy(original)
    restored[0]["content"] = "caller mutation"
    assert restore_native_projections([message], scope=SCOPE, anthropic=anthropic, store=store)[0] == original
    assert next(iter(store._records.values())).blocks == ledger.blocks


@pytest.mark.parametrize("location,value", [
    ((0, "thinking"), "changed"), ((0, "signature"), "forged"),
    ((1, "text"), "changed"), ((2, "id"), "forged-id"),
    ((2, "name"), "web_fetch"), ((2, "input"), {"query": "other"}),
    ((3, "tool_use_id"), "original-id"), ((3, "content"), []),
    ((4, "text"), "changed summary"), ((5, "data"), "Yg=="),
    ((6, "text"), "changed after"),
])
def test_each_projected_component_is_proven(location: tuple[int, str], value: Any) -> None:
    store, _, _, _, _, message = fixture_projection()
    message["content"][location[0]][location[1]] = value
    with pytest.raises(NativeReasoningError, match="cannot be verified"):
        restore_native_projections([message], scope=SCOPE, anthropic=True, store=store)


@pytest.mark.parametrize("mutation", ["reorder", "duplicate", "extra", "boolean"])
def test_full_structure_and_json_types_are_proven(mutation: str) -> None:
    store, _, _, _, _, message = fixture_projection()
    blocks = message["content"]
    if mutation == "reorder":
        blocks[0], blocks[5] = blocks[5], blocks[0]
    elif mutation == "duplicate":
        blocks.insert(3, deepcopy(blocks[2]))
    elif mutation == "extra":
        blocks[2]["unproven"] = "caller-added"
    else:
        blocks[3]["content"][0]["score"] = True
    with pytest.raises(NativeReasoningError):
        restore_native_projections([message], scope=SCOPE, anthropic=True, store=store)


@pytest.mark.parametrize("anthropic", [True, False])
@pytest.mark.parametrize("part", [0, 1, 2])
def test_client_account_and_model_scope_must_all_match(anthropic: bool, part: int) -> None:
    store, _, _, _, _, message = fixture_projection(anthropic)
    scope = list(SCOPE)
    scope[part] = "changed"
    with pytest.raises(NativeReasoningError):
        restore_native_projections([message], scope=tuple(scope), anthropic=anthropic, store=store)


@pytest.mark.parametrize("anthropic", [True, False])
@pytest.mark.parametrize("cause", ["ttl", "clear", "lru"])
def test_receipts_expire_and_evict_with_original_proof(anthropic: bool, cause: str) -> None:
    store = ReasoningStore(max_records=1, ttl=10)
    with patch("kiro.native_reasoning.time.monotonic", return_value=1):
        _, _, identity, _, _, message = fixture_projection(anthropic, store=store)
    if cause == "clear":
        store.clear()
    elif cause == "lru":
        other = NativeMessageLedger()
        other.feed(KiroEvent(type="native_reasoning", reasoning={"text": "new", "signature": "new"}))
        with patch("kiro.native_reasoning.time.monotonic", return_value=2):
            store.record(SCOPE, identity, "new", other)
    with patch("kiro.native_reasoning.time.monotonic", return_value=12 if cause == "ttl" else 3):
        with pytest.raises(NativeReasoningError):
            restore_native_projections([message], scope=SCOPE, anthropic=anthropic, store=store)
    if cause != "lru":
        assert store._bytes == 0


def test_only_completed_decoder_records_can_receive_receipts() -> None:
    store, ledger, identity, exchanges, visible, _ = fixture_projection(record=False)
    assert not store._records
    store.record(SCOPE, identity, "anchor", ledger)
    for scope, anchor, identity_value in [
        (("client", "other", "model"), "anchor", identity),
        (SCOPE, "other", identity),
        (SCOPE, "anchor", SimpleNamespace(conversation_id="other", root_conversation_id="root", continuation_id="turn")),
    ]:
        store.record_projection(scope, identity_value, anchor, ledger, exchanges, anthropic=True, emitted=visible)
        assert not next(iter(store._records.values())).projections
    store.record_projection(SCOPE, identity, "anchor", ledger, exchanges, anthropic=True, emitted=[])
    assert not next(iter(store._records.values())).projections


def test_receipt_bytes_are_bounded_and_ttl_is_not_extended() -> None:
    store = ReasoningStore(ttl=10)
    with patch("kiro.native_reasoning.time.monotonic", return_value=1):
        _, ledger, identity, exchanges, visible, _ = fixture_projection(store=store)
    record = next(iter(store._records.values()))
    assert record.size == store._bytes
    base = record.size - record.projections[True].size
    with patch("kiro.native_reasoning.time.monotonic", return_value=9):
        store.record_projection(SCOPE, identity, "anchor", ledger, exchanges, anthropic=True, emitted=visible)
        assert store._bytes == record.size  # Replacement is not counted twice.
        assert next(iter(store._records.values())).expires_at == 11
        store.max_bytes = base + 1
        with pytest.raises(NativeReasoningError, match="bounded"):
            store.record_projection(SCOPE, identity, "anchor", ledger, exchanges, anthropic=True, emitted=visible)


def test_ordinary_messages_and_unprojected_native_output_are_unchanged() -> None:
    store, ledger, _, _, _, _ = fixture_projection()
    messages = [{"role": "user", "content": "caller"}, {"role": "assistant", "content": "ordinary"},
                {"role": "assistant", "content": deepcopy(ledger.blocks)},
                {"role": "assistant", "content": [{"type": "server_tool_use", "id": "legacy"}]}]
    assert restore_native_projections(messages, scope=SCOPE, anthropic=True, store=store) == messages


@pytest.mark.parametrize("field,value", [("content", "tampered"), ("reasoning_content", "tampered")])
def test_openai_flattened_fields_cannot_be_tampered(field: str, value: str) -> None:
    store, _, _, _, _, message = fixture_projection(False)
    message[field] = value
    with pytest.raises(NativeReasoningError):
        restore_native_projections([message], scope=SCOPE, anthropic=False, store=store)


def test_receipt_attachment_evicts_by_shared_byte_budget() -> None:
    store, ledger, identity, exchanges, visible, _ = fixture_projection()
    first_key = next(iter(store._records))
    store.record(SCOPE, identity, "anchor", ledger)
    store.max_bytes = store._bytes  # Room for originals, not a second receipt.
    store.record_projection(SCOPE, identity, "anchor", ledger, exchanges, anthropic=True, emitted=visible)
    assert first_key not in store._records
    assert len(store._records) == 1
    assert next(iter(store._records.values())).size == store._bytes <= store.max_bytes


def test_observer_budget_cannot_break_ordinary_unprojected_output(monkeypatch: pytest.MonkeyPatch) -> None:
    import kiro.native_reasoning as native
    from extensions.request_context import start_request_state, reset_request_state

    monkeypatch.setattr(native, "reasoning_store", ReasoningStore(max_bytes=32))
    state, token = start_request_state()
    state.account_scope = "account"
    state.wire_identity = object()
    try:
        recorder = native.NativeProjectionRecorder(anthropic=True)
        recorder.observe_anthropic({"type": "content_block_start", "index": 0,
                                   "content_block": {"type": "text", "text": "ordinary"}})
        # Overflow withdraws optional proof, not text or original replay state.
        assert not recorder._observation_available and not recorder._blocks
        recorder.web_search("tool", "mcp", "query", {"results": []}, "summary")
        recorder.finish()
        assert not native.reasoning_store._records
    finally:
        reset_request_state(token)


def test_coalescing_tool_results_preserves_caller_text_and_does_not_mutate_input() -> None:
    store, _, _, _, _, message = fixture_projection()
    caller = {"role": "user", "content": [{"type": "text", "text": "caller before"},
              {"type": "tool_result", "tool_use_id": "caller-tool", "content": "caller result"},
              {"type": "text", "text": "caller after"}]}
    saved = deepcopy(caller)
    restored = restore_native_projections([message, caller], scope=SCOPE, anthropic=True, store=store)
    assert caller == saved
    assert restored[1]["content"][1:] == caller["content"]
    assert restored[1]["content"][0]["tool_use_id"] == "original-id"
