"""Offline tests for privacy-safe debug modes, persistence, and cleanup."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from loguru import logger as app_logger

import kiro.debug_logger as debug_module
from kiro.debug_logger import DebugLogger
from kiro.debug_redaction import REDACTED

SECRET = "synthetic-private-native-value-29ae6b"
REQUEST = json.dumps({
    "model": "test-model", "accessToken": SECRET,
    "messages": [{"content": [
        {"type": "thinking", "thinking": "Useful diagnostic text", "signature": SECRET},
        {"type": "redacted_thinking", "data": SECRET},
    ]}],
    "output": [{"type": "reasoning", "encrypted_content": SECRET}],
}).encode()
MODIFIED = b'data: {"delta":{"type":"signature_delta","signature":"' + SECRET.encode() + b'"}}\n\n'


@pytest.fixture
def debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[DebugLogger]:
    """Use an independent logger and temporary directory, never the global sink."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "errors")
    monkeypatch.setattr(debug_module, "DEBUG_DIR", str(tmp_path / "debug_logs"))
    instance = object.__new__(DebugLogger)
    instance._initialized = False
    instance.__init__()
    yield instance
    instance._clear_buffers()


def buffer_bytes(debug: DebugLogger) -> bytes:
    """Snapshot every logger-owned diagnostic buffer before file persistence."""
    return b"\n".join((
        debug._request_body_buffer or b"",
        debug._kiro_request_body_buffer or b"",
        bytes(debug._raw_chunks_buffer),
        bytes(debug._modified_chunks_buffer),
        debug._app_logs_buffer.getvalue().encode(),
    ))


def file_bytes(debug: DebugLogger) -> bytes:
    """Snapshot only the test logger's output files."""
    return b"\n".join(path.read_bytes() for path in debug.debug_dir.glob("*"))


def assert_empty(debug: DebugLogger) -> None:
    """Check all request data and the temporary sink have been discarded."""
    assert debug._request_body_buffer is None
    assert debug._kiro_request_body_buffer is None
    assert not debug._raw_chunks_buffer
    assert not debug._modified_chunks_buffer
    assert not debug._app_logs_buffer.getvalue()
    assert debug._loguru_sink_id is None


def assert_summary(summary: dict[str, Any], original: bytes) -> None:
    """Verify the summary retains diagnostic size/hash but no payload."""
    assert summary == {
        "diagnostic": "payload_omitted", "bytes": len(original),
        "sha256": hashlib.sha256(original).hexdigest(),
    }


def test_singleton_initialization_is_idempotent(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing singleton users keep their logger and buffers on repeated init."""
    monkeypatch.setattr(DebugLogger, "_instance", None)
    first = DebugLogger()
    first.log_request_body(REQUEST)
    second = DebugLogger()
    assert first is second
    assert second._request_body_buffer is not None
    assert SECRET.encode() not in buffer_bytes(second)
    second._clear_buffers()


@pytest.mark.parametrize("mode,enabled,immediate", [("off", False, False), ("errors", True, False), ("all", True, True), ("unknown", False, False)])
def test_mode_helpers(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str, enabled: bool, immediate: bool) -> None:
    """Keep the existing default mode contract, including unknown modes."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    assert debug._is_enabled() is enabled
    assert debug._is_immediate_write() is immediate


def test_off_mode_retains_and_writes_nothing(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every public logging API is disabled when mode is off."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "off")
    debug.prepare_new_request()
    debug.log_request_body(REQUEST)
    debug.log_kiro_request_body(REQUEST)
    debug.log_raw_chunk(SECRET.encode())
    debug.log_modified_chunk(MODIFIED)
    debug.log_error_info(500, SECRET)
    debug.flush_on_error(500, SECRET)
    debug.discard_buffers()
    assert not debug.debug_dir.exists()
    assert_empty(debug)


def test_all_mode_replaces_only_owned_files(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the configured temporary directory is cleared for a new request."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "all")
    debug.debug_dir.mkdir()
    old_file = debug.debug_dir / "request_body.json"
    old_file.write_text("old diagnostic")
    unrelated = debug.debug_dir / "operator-notes.txt"
    unrelated.write_text("keep unrelated data")
    sibling = debug.debug_dir.parent / "untouched.txt"
    sibling.write_text("keep")
    debug.prepare_new_request()
    assert debug.debug_dir.exists()
    assert not old_file.exists()
    assert unrelated.read_text() == "keep unrelated data"
    assert sibling.read_text() == "keep"
    assert debug._loguru_sink_id is not None


@pytest.mark.parametrize("mode", ["all", "errors"])
def test_buffers_and_files_never_contain_native_secrets(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Both modes sanitize client/upstream bodies and streams before retention."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    debug.prepare_new_request()
    debug.log_request_body(REQUEST)
    debug.log_kiro_request_body(REQUEST)
    debug.log_raw_chunk(b"\x00\xff" + SECRET.encode())
    debug.log_modified_chunk(MODIFIED)
    app_logger.warning("Unstructured upstream dump: {}", SECRET)
    assert SECRET.encode() not in buffer_bytes(debug)
    if mode == "errors":
        assert not debug.debug_dir.exists()
        assert json.loads(debug._request_body_buffer)["messages"][0]["content"][0]["signature"] == REDACTED
    else:
        assert (debug.debug_dir / "request_body.json").exists()
        assert SECRET.encode() not in file_bytes(debug)
    debug.flush_on_error(502, "Bearer " + SECRET)
    assert {path.name for path in debug.debug_dir.iterdir()} == {
        "request_body.json", "kiro_request_body.json", "response_stream_raw.txt",
        "response_stream_modified.txt", "error_info.json", "app_logs.txt",
    }
    assert SECRET.encode() not in file_bytes(debug)
    request = json.loads((debug.debug_dir / "request_body.json").read_bytes())
    assert request["model"] == "test-model"
    assert request["messages"][0]["content"][0]["thinking"] == "Useful diagnostic text"
    assert request["messages"][0]["content"][0]["signature"] == REDACTED
    assert b"signature_delta" in (debug.debug_dir / "response_stream_modified.txt").read_bytes()
    error = json.loads((debug.debug_dir / "error_info.json").read_bytes())
    assert error["status_code"] == 502
    assert_summary(error["error_message"], ("Bearer " + SECRET).encode())
    assert_empty(debug)


@pytest.mark.parametrize("mode", ["all", "errors"])
@pytest.mark.parametrize("method,filename,buffer_name", [
    ("log_request_body", "request_body.json", "_request_body_buffer"),
    ("log_kiro_request_body", "kiro_request_body.json", "_kiro_request_body_buffer"),
])
@pytest.mark.parametrize("payload", [b'{"signature":"' + SECRET.encode(), b"\xff" + SECRET.encode(), b"refresh_token=" + SECRET.encode()])
def test_malformed_request_bodies_are_summaries(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str, method: str, filename: str, buffer_name: str, payload: bytes) -> None:
    """Invalid UTF-8 and partial JSON must not fall back to original bytes."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    getattr(debug, method)(payload)
    saved = (debug.debug_dir / filename).read_bytes() if mode == "all" else getattr(debug, buffer_name)
    assert_summary(json.loads(saved), payload)
    assert SECRET.encode() not in saved


@pytest.mark.parametrize("mode", ["all", "errors"])
def test_raw_chunks_are_individual_summaries(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Appending raw chunks cannot reconstruct a signature split across calls."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    chunks = [b'{"sig', b'nature":"' + SECRET[:12].encode(), SECRET[12:].encode() + b'"}', b"\x00\xff", b""]
    for chunk in chunks:
        debug.log_raw_chunk(chunk)
    output = (debug.debug_dir / "response_stream_raw.txt").read_bytes() if mode == "all" else bytes(debug._raw_chunks_buffer)
    records = [json.loads(line) for line in output.splitlines()]
    assert len(records) == len(chunks)
    for record, chunk in zip(records, chunks):
        assert_summary(record, chunk)
    assert SECRET[:12].encode() not in output
    assert SECRET[12:].encode() not in output


@pytest.mark.parametrize("mode", ["all", "errors"])
def test_modified_fragments_fail_closed_independently(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """A split secret and a malformed suffix never enter retained stream data."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    chunks = [b'data: {"signature":"' + SECRET[:12].encode(), SECRET[12:].encode() + b'"}\n\n', b'data: {"text":"Visible"}\n\n' + SECRET.encode()]
    for chunk in chunks:
        debug.log_modified_chunk(chunk)
    output = (debug.debug_dir / "response_stream_modified.txt").read_bytes() if mode == "all" else bytes(debug._modified_chunks_buffer)
    records = [json.loads(line) for line in output.splitlines()]
    for record, chunk in zip(records, chunks):
        assert_summary(record, chunk)
    assert len(records) == len(chunks)
    assert SECRET[:12].encode() not in output
    assert SECRET[12:].encode() not in output
    assert b"Visible" not in output


def test_pretty_json_remains_available(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Readable complete JSON keeps formatting and safe metadata."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "all")
    debug.log_request_body(b'{"model":"test","messages":[]}')
    content = (debug.debug_dir / "request_body.json").read_text()
    assert '\n  "model": "test"' in content
    assert json.loads(content) == {"model": "test", "messages": []}


def test_errors_success_discards_every_buffer_without_files(debug: DebugLogger) -> None:
    """Successful errors-mode requests do not create output directories."""
    debug.prepare_new_request()
    debug.log_request_body(REQUEST)
    debug.log_kiro_request_body(REQUEST)
    debug.log_raw_chunk(SECRET.encode())
    debug.log_modified_chunk(MODIFIED)
    app_logger.info("Request success {}", SECRET)
    debug.discard_buffers()
    assert not debug.debug_dir.exists()
    assert_empty(debug)


def test_all_success_saves_safe_app_logs_and_cleans_sink(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """All mode persists application diagnostics on success without message text."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "all")
    debug.prepare_new_request()
    app_logger.info("Success message {}", SECRET)
    before = debug._app_logs_buffer.getvalue()
    records = [json.loads(line) for line in before.splitlines()]
    assert records[-1]["level"] == 20
    assert "sha256" in records[-1]["message"]
    assert "time" in records[-1] and "line" in records[-1]
    assert SECRET not in before
    assert "Success message" not in before
    debug.discard_buffers()
    assert (debug.debug_dir / "app_logs.txt").read_text() == before
    assert_empty(debug)


def test_exception_tracebacks_are_never_captured_raw(debug: DebugLogger) -> None:
    """Tracebacks and exception locals must not bypass the summary-only sink."""
    debug.prepare_new_request()
    try:
        raise ValueError(SECRET)
    except ValueError:
        app_logger.exception("Failed while decoding {}", SECRET)
    assert SECRET.encode() not in buffer_bytes(debug)
    debug.flush_on_error(500, SECRET)
    assert SECRET.encode() not in file_bytes(debug)
    assert (debug.debug_dir / "app_logs.txt").exists()
    assert_empty(debug)


@pytest.mark.parametrize("mode", ["all", "errors"])
def test_bodyless_error_still_writes_status_and_cleans_up(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Early failures retain status/app summaries even when no body was captured."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    debug.prepare_new_request()
    app_logger.error("Early failure {}", SECRET)
    debug.flush_on_error(401, SECRET)
    info = json.loads((debug.debug_dir / "error_info.json").read_bytes())
    assert info["status_code"] == 401
    assert_summary(info["error_message"], SECRET.encode())
    assert SECRET.encode() not in file_bytes(debug)
    assert_empty(debug)


@pytest.mark.parametrize("mode", ["all", "errors"])
def test_direct_error_info_has_no_raw_error_text(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Direct error-info calls also apply the privacy boundary."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    debug.log_error_info(400, SECRET + "\ud800")
    info = json.loads((debug.debug_dir / "error_info.json").read_bytes())
    assert info["status_code"] == 400
    assert_summary(info["error_message"], (SECRET + "\ud800").encode("utf-8", errors="surrogatepass"))
    assert SECRET.encode() not in file_bytes(debug)


def test_capture_reset_removes_previous_sink(debug: DebugLogger) -> None:
    """Repeated preparation keeps one sink and discards previous request state."""
    debug.prepare_new_request()
    previous = debug._loguru_sink_id
    debug.log_request_body(REQUEST)
    app_logger.info("Previous request")
    debug.prepare_new_request()
    assert debug._loguru_sink_id != previous
    assert debug._request_body_buffer is None
    assert not debug._app_logs_buffer.getvalue()
    with pytest.raises(ValueError):
        app_logger.remove(previous)


def test_cleanup_tolerates_already_removed_sink(debug: DebugLogger) -> None:
    """External sink cleanup must not prevent buffer disposal."""
    debug.prepare_new_request()
    app_logger.remove(debug._loguru_sink_id)
    debug._clear_app_logs_buffer()
    assert_empty(debug)


def test_switching_off_removes_existing_capture(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Disabling diagnostics cannot leave a previously installed sink active."""
    debug.prepare_new_request()
    debug.log_request_body(REQUEST)
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "off")
    debug.prepare_new_request()
    app_logger.info("Not captured {}", SECRET)
    assert_empty(debug)


def test_empty_app_logs_do_not_create_files(debug: DebugLogger) -> None:
    """Do not create empty application log files or their parent directory."""
    debug._write_app_logs_to_file()
    assert not debug.debug_dir.exists()


@pytest.mark.parametrize("helper,filename,payload", [
    ("_write_request_body_to_file", "request_body.json", REQUEST),
    ("_write_kiro_request_body_to_file", "kiro_request_body.json", REQUEST),
    ("_append_raw_chunk_to_file", "response_stream_raw.txt", SECRET.encode()),
    ("_append_modified_chunk_to_file", "response_stream_modified.txt", MODIFIED),
])
def test_private_payload_helpers_cannot_bypass_redaction(debug: DebugLogger, helper: str, filename: str, payload: bytes) -> None:
    """File-writing entry points retain safety even when called directly."""
    getattr(debug, helper)(payload)
    assert (debug.debug_dir / filename).exists()
    assert SECRET.encode() not in file_bytes(debug)


def test_failed_flush_cleans_buffers_and_never_logs_exception_text(debug: DebugLogger) -> None:
    """Filesystem errors cannot retain buffers or leak sensitive exception paths."""
    debug.prepare_new_request()
    debug.log_request_body(REQUEST)
    with patch.object(Path, "mkdir", side_effect=PermissionError(SECRET)), patch.object(debug_module.logger, "error") as error_log:
        debug.flush_on_error(500, SECRET)
    assert SECRET not in str(error_log.call_args_list)
    assert error_log.called
    assert_empty(debug)


def test_failed_file_write_is_nonfatal_and_sanitized(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Immediate-write failures produce fixed actionable messages only."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "all")
    with patch.object(Path, "open", side_effect=OSError(SECRET)), patch.object(debug_module.logger, "error") as error_log:
        debug.log_request_body(REQUEST)
        debug.log_raw_chunk(SECRET.encode())
        debug.log_modified_chunk(MODIFIED)
        debug.log_error_info(500, SECRET)
    assert error_log.call_count == 4
    assert SECRET not in str(error_log.call_args_list)


def test_prepare_directory_failure_is_nonfatal(debug: DebugLogger, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed reset reports only a safe message and remains cleanable."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", "all")
    with patch.object(Path, "mkdir", side_effect=PermissionError(SECRET)):
        debug.prepare_new_request()
    assert SECRET.encode() not in buffer_bytes(debug)
    debug.discard_buffers()
    assert_empty(debug)

@pytest.mark.parametrize("mode", ["all", "errors"])
@pytest.mark.parametrize("messages", [
    ('metadataEvent: {"encrypted_content":"' + SECRET + '","unknown":true}',),
    ('metadataEvent: {"encrypted_content":"' + SECRET,),
    ("metadataEvent: {'signature': '" + SECRET + "', 'redactedContent': '" + SECRET + "'}",),
    ('metadataEvent: {\\"encrypted_content\\":\\"' + SECRET + '\\"}',),
    ('metadataEvent: {"nested":{"refreshToken":"' + SECRET + '"}}',),
    ('metadataEvent: {"Authorization":"Bearer ' + SECRET,),
    ('metadataEvent: {"encrypted_', 'content":"' + SECRET[:12], SECRET[12:] + '"}'),
    (SECRET[:12], SECRET[12:]),
])
def test_metadata_application_messages_are_safe_before_and_after_persistence(
    debug: DebugLogger,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    messages: tuple[str, ...],
) -> None:
    """Unknown, truncated, and split native metadata never enters StringIO raw."""
    monkeypatch.setattr(debug_module, "DEBUG_MODE", mode)
    debug.prepare_new_request()
    for message in messages:
        app_logger.debug("{}", message)
        # Inspect retained memory immediately, not just after flush or cleanup.
        captured = debug._app_logs_buffer.getvalue()
        assert SECRET not in captured
        assert SECRET[:12] not in captured
        assert SECRET[12:] not in captured
        assert "metadataEvent" not in captured
        assert "encrypted_content" not in captured
        assert "refreshToken" not in captured
    entries = [json.loads(line) for line in captured.splitlines()]
    assert len(entries) == len(messages)
    for entry in entries:
        assert entry["level"] == 10
        assert entry["message"]["diagnostic"] == "payload_omitted"
        assert entry["message"]["bytes"] > 0
        assert len(entry["message"]["sha256"]) == 64
    if mode == "errors":
        assert not debug.debug_dir.exists()
        debug.flush_on_error(502, "Metadata decoding failed")
    else:
        debug.discard_buffers()
    saved = (debug.debug_dir / "app_logs.txt").read_text()
    assert saved == captured
    assert SECRET[:12] not in saved
    assert SECRET[12:] not in saved
    assert_empty(debug)
