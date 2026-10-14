"""Finite, fail-closed redaction for diagnostic copies, never protocol payloads.

Opaque native reasoning and credentials are removed before any debug retention.
Binary upstream chunks and incomplete documents are represented only by byte count
and SHA-256. This is deliberately not a general-purpose PII classifier.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REDACTED = "[REDACTED]"
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_NESTING = 64

# Compare case-insensitively, ignoring separators used by the supported APIs.
_SENSITIVE_KEYS = frozenset({
    "signature", "signatures", "thinkingsignature", "reasoningsignature",
    "redactedcontent", "encryptedcontent", "encryptedreasoning", "opaquecontent",
    "accesstoken", "refreshtoken", "idtoken", "authtoken", "bearertoken", "token",
    "authorization", "proxyauthorization", "bearer", "credentials", "apikey",
    "xapikey", "proxyapikey", "password", "clientsecret", "secretaccesskey",
    "awsaccesskeyid", "awssecretaccesskey", "awssessiontoken", "sessiontoken", "cookie", "setcookie",
    "xcloudkey", "xkiroauthorization", "kiroaascloudapikey",
})
_OPAQUE_TYPES = {
    "redactedthinking": "redacted_thinking",
    "redactedthinkingdelta": "redacted_thinking_delta",
    "signaturedelta": "signature_delta",
    "reasoningencrypted": "reasoning.encrypted",
    "reasoningsignature": "reasoning.signature",
    "responsereasoningencryptedcontentdelta": "response.reasoning.encrypted_content.delta",
    "responsereasoningencryptedcontentdone": "response.reasoning.encrypted_content.done",
}
_OPAQUE_MARKERS = ("signature", "redacted", "encrypted", "opaque")
_SENSITIVE_TEXT = re.compile(
    r"bearer|\bbasic\s|signature|redacted[\s_.-]*content|encrypted[\s_.-]*content|"
    r"opaque[\s_.-]*content|(?:access|refresh|id|auth|session)[\s_.-]*token|"
    r"authorization|credentials|(?:api|client)[\s_.-]*(?:key|secret)|"
    r"password|secret[\s_.-]*access[\s_.-]*key|cookie",
    re.IGNORECASE,
)
# SSE metadata is untrusted too. Retain only recognized event names, never IDs,
# comments, retry values, or arbitrary event labels containing payload fragments.
_SSE_EVENTS = frozenset({
    "message", "error", "ping", "message_start", "message_delta", "message_stop",
    "content_block_start", "content_block_delta", "content_block_stop",
    "response.created", "response.in_progress", "response.completed", "response.failed",
    "response.incomplete", "response.output_item.added", "response.output_item.done",
    "response.content_part.added", "response.content_part.done",
    "response.output_text.delta", "response.output_text.done",
    "response.reasoning_summary_part.added", "response.reasoning_summary_part.done",
    "response.reasoning_summary_text.delta", "response.reasoning_summary_text.done",
    "response.reasoning_text.delta", "response.reasoning_text.done",
    "response.reasoning.encrypted_content.delta", "response.reasoning.encrypted_content.done",
    "response.function_call_arguments.delta", "response.function_call_arguments.done",
})


def summarize_payload(payload: bytes) -> bytes:
    """Return a newline-delimited JSON summary without retaining payload bytes.

    Args:
        payload: Original diagnostic bytes, including arbitrary binary data.

    Returns:
        UTF-8 JSON containing only a fixed marker, byte count, and SHA-256 digest.
    """
    summary = {
        "diagnostic": "payload_omitted",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return (json.dumps(summary, sort_keys=True) + "\n").encode("ascii")


def _normalize(value: str) -> str:
    """Return an ASCII alphanumeric field/type identifier for matching."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _reject_constant(value: str) -> Any:
    """Reject non-JSON numeric constants without including their input in errors."""
    raise ValueError("Non-finite JSON constants cannot be retained")


def _load_document(text: str) -> dict[str, Any] | list[Any]:
    """Parse one complete JSON container, rejecting scalar stream fragments.

    Raises:
        ValueError: The input is malformed, non-finite, or not a JSON container.
        RecursionError: The JSON parser's nesting limit is exceeded.
    """
    value = json.loads(text, parse_constant=_reject_constant)
    if not isinstance(value, (dict, list)):
        raise ValueError("Diagnostics require a complete JSON container")
    return value


def _redact_string(value: str, depth: int) -> str:
    """Redact credential markers and nested or malformed structured strings."""
    if value == REDACTED:
        return value
    if _SENSITIVE_TEXT.search(value):
        return REDACTED
    if value.lstrip().startswith(("{", "[")):
        try:
            return json.dumps(_redact(_load_document(value), depth + 1), ensure_ascii=True, allow_nan=False)
        except (ValueError, RecursionError):
            return REDACTED
    # Embedded JSON, escaped JSON keys and partial serialized containers cannot
    # safely be matched by replacing just the apparent sensitive substring.
    if any(marker in value for marker in ("{", "}", "\\u", '\\"')):
        return REDACTED
    return value


def _redact(value: Any, depth: int = 0) -> Any:
    """Return a detached JSON tree with finite credential/native redactions.

    Raises:
        ValueError: The diagnostic nesting budget is exceeded.
    """
    if depth > MAX_NESTING:
        raise ValueError("Diagnostic nesting limit exceeded")
    if isinstance(value, dict):
        block_type = value.get("type")
        normalized_type = _normalize(block_type) if isinstance(block_type, str) else ""
        if any(marker in normalized_type for marker in _OPAQUE_MARKERS):
            # Entire opaque blocks are secret, including unexpected/malformed
            # payload fields, not merely the conventional data/signature field.
            return {
                (key if _normalize(key) in _SENSITIVE_KEYS else _redact_string(key, depth)): (
                    _OPAQUE_TYPES.get(normalized_type, REDACTED) if key == "type"
                    else item if key == "index" and type(item) is int
                    else REDACTED
                )
                for key, item in value.items()
            }
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _normalize(key)
            if normalized_key in _SENSITIVE_KEYS or _SENSITIVE_TEXT.search(key):
                safe_key = key if normalized_key in _SENSITIVE_KEYS else REDACTED
                result[safe_key] = REDACTED
            elif normalized_key == "data" and not isinstance(item, dict):
                # A missing/malformed native block type must not expose a bare
                # opaque data string or a JSON array of byte values.
                result[key] = REDACTED
            else:
                result[_redact_string(key, depth)] = _redact(item, depth + 1)
        return result
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_string(value, depth)
    return value


def sanitize_json_bytes(payload: bytes) -> bytes:
    """Sanitize complete UTF-8 request/response JSON, or summarize it fail-closed.

    Args:
        payload: A diagnostic copy of client or upstream JSON bytes.

    Returns:
        Pretty-printed sanitized JSON, or a size/hash summary for invalid,
        scalar, over-sized, non-finite, or over-nested input. No input is mutated.
    """
    if len(payload) > MAX_DOCUMENT_BYTES:
        return summarize_payload(payload)
    try:
        sanitized = _redact(_load_document(payload.decode("utf-8")))
        return (json.dumps(sanitized, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    except (UnicodeDecodeError, ValueError, RecursionError):
        return summarize_payload(payload)


def _sanitize_sse(text: str) -> bytes:
    """Sanitize complete JSON SSE frames without retaining transport metadata.

    Raises:
        ValueError: Any frame is incomplete, unsupported, or contains invalid JSON.
        RecursionError: A frame exceeds the parser's nesting limit.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n\n"):
        raise ValueError("Incomplete SSE frame")
    frames: list[str] = []
    for frame in text.split("\n\n"):
        if not frame:
            continue
        event: str | None = None
        data: list[str] = []
        for line in frame.split("\n"):
            field, separator, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data" and separator:
                data.append(value)
            elif field == "event" and separator and value in _SSE_EVENTS and event is None:
                event = value
            else:
                raise ValueError("Unsupported SSE field or event")
        if not data:
            raise ValueError("SSE frame has no JSON data")
        content = "\n".join(data)
        if content != "[DONE]":
            content = json.dumps(_redact(_load_document(content)), ensure_ascii=True, allow_nan=False)
        frames.append((f"event: {event}\n" if event else "") + f"data: {content}\n\n")
    if not frames:
        raise ValueError("SSE chunk has no complete frames")
    return "".join(frames).encode("utf-8")


def sanitize_modified_chunk(payload: bytes) -> bytes:
    """Sanitize complete modified JSON/SSE, otherwise return a size/hash summary.

    No raw fragment is buffered for reassembly. A chunk with even one incomplete
    or malformed frame is summarized in its entirety, including any valid prefix.

    Args:
        payload: Bytes emitted by a protocol adapter to the client.

    Returns:
        Sanitized complete JSON/SSE or a newline-delimited JSON summary.
    """
    if len(payload) > MAX_DOCUMENT_BYTES:
        return summarize_payload(payload)
    try:
        text = payload.decode("utf-8")
        if text.lstrip().startswith(("{", "[")):
            return sanitize_json_bytes(payload)
        return _sanitize_sse(text)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return summarize_payload(payload)
