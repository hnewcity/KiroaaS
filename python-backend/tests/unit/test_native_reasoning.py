"""Bounded native state, data integrity, and account/model replay isolation."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kiro.native_reasoning import (
    NativeMessageLedger, NativeReasoningError, ReasoningStore,
    normalize_delta, reasoning_blocks,
)
from kiro.streaming_core import KiroEvent


def ledger(text="thought", signature="signature", content="answer"):
    value = NativeMessageLedger()
    value.feed(KiroEvent(type="native_reasoning", reasoning={"text": text}))
    value.feed(KiroEvent(type="native_reasoning", reasoning={"signature": signature}))
    value.feed(KiroEvent(type="content", content=content))
    return value


def identity():
    return SimpleNamespace(conversation_id="conversation", root_conversation_id="root", continuation_id="turn")


def test_byte_arrays_are_normalized_without_interpreting_opaque_content():
    assert normalize_delta({"redactedContent": [0, 255, 1]}) == {"redactedContent": "AP8B"}
    assert normalize_delta({"redactedContent": "AP8B"}) == {"redactedContent": "AP8B"}


@pytest.mark.parametrize("value", [None, [], {}, {"text": 2}, {"signature": False}, {"redactedContent": "not base64!"}, {"redactedContent": [256]}, {"text": "a", "redactedContent": "Yg=="}])
def test_malformed_native_events_are_errors(value):
    with pytest.raises(NativeReasoningError):
        normalize_delta(value)


def test_openai_delta_indexes_assemble_but_unsigned_text_is_not_replayed():
    details = [
        {"type": "thinking", "index": 0, "thinking": "a"},
        {"type": "thinking", "index": 0, "thinking": "b", "signature": "sig"},
        {"type": "thinking", "index": 3, "thinking": "unsigned"},
    ]
    assert reasoning_blocks(details) == [{"type": "thinking", "thinking": "ab", "signature": "sig"}]
    assert len(reasoning_blocks(details, include_unsigned=True)) == 2


def test_cache_limits_expiry_and_no_mutable_aliases():
    store = ReasoningStore(max_records=1, ttl=10)
    original = ledger()
    scope = ("client", "account", "model")
    with patch("kiro.native_reasoning.time.monotonic", return_value=10):
        store.record(scope, identity(), "anchor", original)
        native = reasoning_blocks(original.blocks)
        found = store.find(scope, "answer", [], native)
        original.blocks[0]["thinking"] = "mutated"
        found.blocks[0]["thinking"] = "also-mutated"
        assert store.find(scope, "answer", [], native).blocks[0]["thinking"] == "thought"
    with patch("kiro.native_reasoning.time.monotonic", return_value=21):
        with pytest.raises(NativeReasoningError):
            store.find(scope, "answer", [], native)
    assert store._bytes == 0
    store.record(scope, identity(), "anchor", ledger("new", "new-sig"))
    store.record(scope, identity(), "anchor", ledger("other", "other-sig"))
    assert len(store._records) == 1
    with pytest.raises(NativeReasoningError):
        store.find(scope, "answer", [], [{"type": "thinking", "thinking": "new", "signature": "new-sig"}])


@pytest.mark.parametrize("scope", [("other-client", "account", "model"), ("client", "other-account", "model"), ("client", "account", "other-model")])
def test_scope_cannot_be_asserted_by_client(scope):
    store = ReasoningStore()
    generated = ledger()
    store.record(("client", "account", "model"), identity(), "anchor", generated)
    with pytest.raises(NativeReasoningError):
        store.find(scope, "answer", [], reasoning_blocks(generated.blocks))


def test_changed_assistant_content_or_tool_set_is_rejected():
    store = ReasoningStore()
    generated = ledger()
    scope = ("client", "account", "model")
    store.record(scope, identity(), "anchor", generated)
    native = reasoning_blocks(generated.blocks)
    with pytest.raises(NativeReasoningError):
        store.find(scope, "changed", [], native)
    with pytest.raises(NativeReasoningError):
        store.find(scope, "answer", [{"id": "invented"}], native)


def test_oversized_record_is_not_retained():
    store = ReasoningStore(max_bytes=10)
    with pytest.raises(NativeReasoningError, match="exceeds"):
        store.record(("client", "account", "model"), identity(), "a", ledger())
    assert store._bytes == 0 and not store._records


def test_default_history_survives_long_conversations_and_overnight_idle() -> None:
    """Native proof is conversation state, not a one-hour authentication token."""
    store = ReasoningStore()
    scope = ("client", "account", "model")
    generated = ledger()
    with patch("kiro.native_reasoning.time.monotonic", return_value=100):
        store.record(scope, identity(), "anchor", generated)
    with patch("kiro.native_reasoning.time.monotonic", return_value=100 + 3 * 86400):
        found = store.find(scope, "answer", [], reasoning_blocks(generated.blocks))
    assert found.root_conversation_id == "root"
