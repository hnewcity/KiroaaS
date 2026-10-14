"""Offline regression coverage for finite native-reasoning diagnostic redaction."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from kiro.debug_redaction import (
    MAX_DOCUMENT_BYTES,
    MAX_NESTING,
    REDACTED,
    sanitize_json_bytes,
    sanitize_modified_chunk,
    summarize_payload,
)

SECRET = "private-value-7da924c1"


def encode(value: Any) -> bytes:
    """Serialize synthetic test data without accessing credentials."""
    return json.dumps(value).encode("utf-8")


def assert_summary(actual: bytes, original: bytes) -> None:
    """Require the exact closed summary schema and original-byte digest."""
    assert json.loads(actual) == {
        "diagnostic": "payload_omitted",
        "bytes": len(original),
        "sha256": hashlib.sha256(original).hexdigest(),
    }
    assert SECRET.encode() not in actual


@pytest.mark.parametrize("key", [
    "signature", "signatures", "thinking_signature", "reasoningSignature",
    "redactedContent", "redacted_content", "encrypted_content", "encryptedContent",
    "encrypted_reasoning", "opaque_content", "accessToken", "access_token",
    "ACCESS-TOKEN", "refreshToken", "refresh_token", "Authorization",
    "Proxy-Authorization", "bearer", "bearer_token", "token", "id_token",
    "authToken", "session_token", "api_key", "x-api-key", "proxy_api_key",
    "credentials", "clientSecret", "password", "secretAccessKey",
    "aws_access_key_id", "aws_session_token", "cookie", "Set-Cookie",
])
@pytest.mark.parametrize("value", [SECRET, {"unexpected": SECRET}, [80, 81, 82, SECRET], None, 123])
def test_sensitive_fields_redacted_recursively(key: str, value: Any) -> None:
    """Redact values regardless of spelling, depth, container, or malformed type."""
    original = {"messages": [{"content": [{"nested": {key: value, "text": "Visible text"}}]}]}
    untouched = encode(original)
    output = sanitize_json_bytes(untouched)
    nested = json.loads(output)["messages"][0]["content"][0]["nested"]
    assert nested == {key: REDACTED, "text": "Visible text"}
    assert SECRET.encode() not in output
    assert encode(original) == untouched


@pytest.mark.parametrize("block_type", [
    "redacted_thinking", "redacted_thinking_delta", "signature_delta",
    "reasoning.encrypted", "reasoning.signature",
    "response.reasoning.encrypted_content.delta",
    "response.reasoning.encrypted_content.done",
])
def test_opaque_blocks_hide_all_payload_fields(block_type: str) -> None:
    """Opaque block payloads cannot hide under nonstandard or malformed fields."""
    output = json.loads(sanitize_json_bytes(encode({
        "type": block_type, "index": 2, "data": SECRET, "signature": SECRET,
        "delta": SECRET, "text": SECRET, "unexpected": {"anything": SECRET},
    })))
    assert output["type"] == block_type
    assert output["index"] == 2
    assert output["signature"] == REDACTED
    assert all(value == REDACTED for key, value in output.items() if key not in ("type", "index"))


def test_unknown_opaque_type_does_not_echo_secret_in_type() -> None:
    """Do not retain malicious payload-bearing type names or malformed indexes."""
    output = sanitize_json_bytes(encode({"type": "encrypted." + SECRET, "index": SECRET, "data": SECRET}))
    assert SECRET.encode() not in output
    assert json.loads(output)["type"] == REDACTED


@pytest.mark.parametrize("data", [SECRET, [80, 81, 82], {"unexpected": SECRET}])
def test_redacted_block_data_containers(data: Any) -> None:
    """Neither base64, byte arrays, nor malformed objects survive opaque blocks."""
    output = json.loads(sanitize_json_bytes(encode({"type": "redacted_thinking", "data": data})))
    assert output["data"] == REDACTED


def test_native_text_remains_useful_but_replay_material_is_removed() -> None:
    """Preserve native text, usage, ordering, model, and tool diagnostics."""
    original = {
        "model": "test-model",
        "reasoningContentEvent": {"text": "Checking the calculation", "signature": SECRET},
        "messages": [{"content": [
            {"type": "thinking", "thinking": "Compare both values", "signature": SECRET},
            {"type": "text", "text": "The result is 42"},
            {"type": "redacted_thinking", "data": SECRET},
            {"type": "tool_use", "name": "calculator", "input": {"expression": "6 * 7"}},
        ]}],
        "reasoning_details": [{"type": "thinking", "index": 1, "thinking": "Confirm", "signature": SECRET}],
        "output": [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "Arithmetic"}], "encrypted_content": SECRET}],
        "usage": {"input_tokens": 12, "output_tokens": 7},
        "finish_reason": "stop",
    }
    output = sanitize_json_bytes(encode(original))
    result = json.loads(output)
    assert SECRET.encode() not in output
    assert result["reasoningContentEvent"]["text"] == "Checking the calculation"
    assert result["messages"][0]["content"][0]["thinking"] == "Compare both values"
    assert result["messages"][0]["content"][1] == original["messages"][0]["content"][1]
    assert result["messages"][0]["content"][3] == original["messages"][0]["content"][3]
    assert result["reasoning_details"][0]["index"] == 1
    assert result["output"][0]["summary"] == original["output"][0]["summary"]
    assert result["usage"] == original["usage"]
    assert result["finish_reason"] == "stop"


@pytest.mark.parametrize("text", [
    "Bearer " + SECRET, "bEaReR\t" + SECRET,
    "Authorization: Basic " + SECRET, "refresh_token=" + SECRET,
    "https://invalid.example/path?access_token=" + SECRET,
    '{"signature":"' + SECRET + '"}',
    '{"sig\\u006eature":"' + SECRET + '"}',
    '{"encrypted_content":"' + SECRET,
    'broken prefix {"sig\\u006eature":"' + SECRET + '"}',
])
def test_credential_and_structured_strings_fail_closed(text: str) -> None:
    """Sensitive strings are omitted in full, not patched around unsafe substrings."""
    assert SECRET.encode() not in sanitize_json_bytes(encode({"content": text}))


def test_nested_json_string_is_sanitized_without_mutating_safe_text() -> None:
    """A serialized object with escaped field names must cross the same boundary."""
    output = json.loads(sanitize_json_bytes(encode({"content": '{"sig\\u006eature":"' + SECRET + '","count":4}'})))
    assert json.loads(output["content"]) == {"signature": REDACTED, "count": 4}
    assert json.loads(sanitize_json_bytes(encode({"content": "Normal plain text"})))["content"] == "Normal plain text"


@pytest.mark.parametrize("payload", [
    b"", b"not JSON", b"\xff\xfe\x00", b'{"signature":"' + SECRET.encode(),
    b'{"encrypted_content":"' + SECRET.encode() + b'"}TRAILER',
    encode(SECRET), b"123", b"null", b'{"usage":NaN}', b'{"usage":Infinity}',
    b'{"usage":1e9999}', b"[" * (MAX_NESTING + 5) + b"0" + b"]" * (MAX_NESTING + 5),
    b"[" * 1500 + b"0" + b"]" * 1500,
])
def test_invalid_json_is_only_a_summary(payload: bytes) -> None:
    """Malformed encodings, partial values, scalars, and resource limits fail closed."""
    assert_summary(sanitize_json_bytes(payload), payload)


def test_oversize_document_and_stream_are_summaries() -> None:
    """Avoid parsing documents above the fixed diagnostic budget."""
    payload = b'{"content":"' + b"x" * MAX_DOCUMENT_BYTES + b'"}'
    assert_summary(sanitize_json_bytes(payload), payload)
    assert_summary(sanitize_modified_chunk(payload), payload)


def test_unicode_and_lone_surrogates_are_safe_json() -> None:
    """Valid diagnostic text can be re-encoded even with escaped lone surrogates."""
    payload = b'{"text":"\\ud800\\u4e2d\\u6587","signature":"' + SECRET.encode() + b'"}'
    output = sanitize_json_bytes(payload)
    assert json.loads(output) == {"text": "\ud800中文", "signature": REDACTED}


@pytest.mark.parametrize("payload", [b"", b"\x00\xff" + SECRET.encode(), SECRET.encode(), b'{"text":"Visible"}'])
def test_raw_summary_contains_only_length_and_hash(payload: bytes) -> None:
    """Even apparently readable upstream bytes are summarized, not inspected."""
    assert_summary(summarize_payload(payload), payload)


def test_complete_sse_with_multiple_frames_is_sanitized() -> None:
    """Anthropic deltas, OpenAI details, and Responses envelopes share redaction."""
    frames = [
        {"type": "content_block_delta", "delta": {"type": "signature_delta", "signature": SECRET}},
        {"choices": [{"delta": {"content": "Visible", "reasoning_details": [{"type": "redacted_thinking", "data": SECRET}]}}]},
        {"type": "response.output_item.done", "item": {"type": "reasoning", "encrypted_content": SECRET}},
    ]
    payload = b"".join(b"data: " + encode(frame) + b"\n\n" for frame in frames) + b"data: [DONE]\n\n"
    output = sanitize_modified_chunk(payload)
    assert SECRET.encode() not in output
    assert output.count(b"data: ") == 4
    assert b"Visible" in output
    assert output.endswith(b"data: [DONE]\n\n")


def test_sse_event_crlf_and_multiline_data() -> None:
    """Parse standard line endings and multi-line JSON without losing diagnostics."""
    payload = b'event: content_block_delta\r\ndata: {"delta":\r\ndata: {"signature":"' + SECRET.encode() + b'","text":"Visible"}}\r\n\r\n'
    output = sanitize_modified_chunk(payload)
    assert output.startswith(b"event: content_block_delta\n")
    assert b"Visible" in output
    assert SECRET.encode() not in output


@pytest.mark.parametrize("payload", [
    b'data: {"signature":"' + SECRET.encode() + b'"}',
    b'data: {"signature":"' + SECRET.encode() + b'"}\n',
    b'data: {"signature":"' + SECRET.encode() + b'\n\n',
    b"data: " + encode(SECRET) + b"\n\n",
    b"data: " + SECRET.encode() + b"\n\n",
    b"event: " + SECRET.encode() + b"\ndata: {}\n\n",
    b"id: " + SECRET.encode() + b"\ndata: {}\n\n",
    b": " + SECRET.encode() + b"\n\ndata: {}\n\n",
    b"retry: " + SECRET.encode() + b"\ndata: {}\n\n",
    b"data: {}\n\ndata: " + SECRET.encode(),
    b"data: {}\n\n" + SECRET.encode(),
    b"event: message\n\n", b"\n\n", b"data: \xff\n\n",
    b"event: message\nevent: message\ndata: {}\n\n",
])
def test_unsafe_sse_summarizes_the_entire_chunk(payload: bytes) -> None:
    """Never retain a valid prefix, unknown metadata, or part of a secret suffix."""
    assert_summary(sanitize_modified_chunk(payload), payload)


def test_every_fragment_boundary_is_safe() -> None:
    """Every split of a native signature SSE frame must omit both fragments."""
    payload = b'data: {"delta":{"type":"signature_delta","signature":"' + SECRET.encode() + b'"}}\n\n'
    for boundary in range(1, len(payload)):
        for fragment in (payload[:boundary], payload[boundary:]):
            if fragment.lstrip().startswith((b"{", b"[")):
                assert sanitize_modified_chunk(fragment) == sanitize_json_bytes(fragment)
            else:
                assert_summary(sanitize_modified_chunk(fragment), fragment)


def test_modified_json_uses_the_request_redactor() -> None:
    """Non-SSE JSON responses receive the identical native-field policy."""
    payload = encode({"output": [{"type": "reasoning", "encrypted_content": SECRET}], "model": "test"})
    assert sanitize_modified_chunk(payload) == sanitize_json_bytes(payload)


def test_redaction_is_idempotent() -> None:
    """Repeated defensive redaction must preserve useful sanitized diagnostics."""
    payload = encode({"type": "thinking", "signature": SECRET, "thinking": "Visible", "auth": {"accessToken": SECRET}})
    once = sanitize_json_bytes(payload)
    assert sanitize_json_bytes(once) == once

@pytest.mark.parametrize("field", ["X-Cloud-Key", "X-Kiro-Authorization", "KIROAAS_CLOUD_API_KEY", "vendor_access_token", "AWS_SECRET_ACCESS_KEY"])
def test_prefixed_credentials_redact_values_not_just_key_labels(field):
    import json
    from kiro.debug_redaction import sanitize_json_bytes
    secret = "synthetic-secret-without-a-marker"
    sanitized = sanitize_json_bytes(json.dumps({field: secret}).encode())
    assert secret.encode() not in sanitized
