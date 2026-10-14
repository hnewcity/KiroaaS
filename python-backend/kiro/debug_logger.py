# -*- coding: utf-8 -*-

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Privacy-safe request diagnostics with off, errors-only, and immediate modes.

Only sanitized JSON or payload size/hash summaries enter this logger's buffers
and files. This module does not change protocol payloads or other loguru sinks.
Free-form application/error messages are summaries, not substring redactions.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from loguru import logger

from kiro.config import DEBUG_DIR, DEBUG_MODE
from kiro.debug_redaction import sanitize_json_bytes, sanitize_modified_chunk, summarize_payload

if TYPE_CHECKING:
    from loguru import Message


class DebugLogger:
    """Manage sanitized diagnostics without retaining raw data between calls."""

    _instance: ClassVar[DebugLogger | None] = None

    def __new__(cls) -> DebugLogger:
        """Return the process-wide debug logger instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize sanitized buffers once; do not create files until enabled."""
        if self._initialized:
            return
        self.debug_dir = Path(DEBUG_DIR)
        self._initialized = True
        self._request_body_buffer: bytes | None = None
        self._kiro_request_body_buffer: bytes | None = None
        self._raw_chunks_buffer = bytearray()
        self._modified_chunks_buffer = bytearray()
        self._app_logs_buffer = io.StringIO()
        self._loguru_sink_id: int | None = None

    def _is_enabled(self) -> bool:
        """Return whether errors-only or immediate diagnostics are enabled."""
        return DEBUG_MODE in ("errors", "all")

    def _is_immediate_write(self) -> bool:
        """Return whether sanitized diagnostics should be written immediately."""
        return DEBUG_MODE == "all"

    def _clear_buffers(self) -> None:
        """Clear every diagnostic buffer and remove the temporary log sink."""
        self._request_body_buffer = None
        self._kiro_request_body_buffer = None
        self._raw_chunks_buffer.clear()
        self._modified_chunks_buffer.clear()
        self._clear_app_logs_buffer()

    def _clear_app_logs_buffer(self) -> None:
        """Remove the log sink, tolerating an already-removed sink, and clear it."""
        if self._loguru_sink_id is not None:
            try:
                logger.remove(self._loguru_sink_id)
            except ValueError:
                pass
            self._loguru_sink_id = None
        self._app_logs_buffer = io.StringIO()

    def _capture_app_log(self, message: Message) -> None:
        """Retain log timing/severity and a digest, never formatted log content.

        Args:
            message: Loguru's transient formatted message, possibly a traceback.
        """
        record = message.record
        # Hash the whole rendered message, including any exception text. Never
        # retain record/exception objects or queue raw messages asynchronously.
        summary = summarize_payload(str(message).encode("utf-8", errors="surrogatepass"))
        entry = {
            "time": record["time"].isoformat(),
            "level": record["level"].no,
            "line": record["line"],
            "message": json.loads(summary),
        }
        self._app_logs_buffer.write(json.dumps(entry) + "\n")

    def _setup_app_logs_capture(self) -> None:
        """Install a synchronous, summary-only sink without local-variable dumps."""
        self._clear_app_logs_buffer()
        self._loguru_sink_id = logger.add(
            self._capture_app_log,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} | {message}",
            level="DEBUG",
            colorize=False,
            backtrace=False,
            diagnose=False,
            enqueue=False,
        )

    def prepare_new_request(self) -> None:
        """Reset buffers/sinks and, in all mode, replace the previous log files."""
        self._clear_buffers()
        if not self._is_enabled():
            return
        self._setup_app_logs_capture()
        if self._is_immediate_write():
            try:
                self._reset_directory()
            except OSError:
                # Exception text and paths may themselves contain credentials.
                logger.error("[DebugLogger] Cannot prepare debug directory; check permissions.")

    def _reset_directory(self) -> None:
        """Replace only owned diagnostic files, never recursively delete a directory.

        DEBUG_DIR is operator-controlled and may point at a shared directory.
        Unrelated files and subdirectories must survive a new request or flush.
        """
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "request_body.json", "kiro_request_body.json", "response_stream_raw.txt",
            "response_stream_modified.txt", "error_info.json", "app_logs.txt",
        ):
            target = self.debug_dir / name
            if target.is_file() or target.is_symlink():
                target.unlink()

    def log_request_body(self, body: bytes) -> None:
        """Record sanitized client JSON or an invalid-body size/hash summary.

        Args:
            body: Original request bytes; never stored directly.
        """
        if not self._is_enabled():
            return
        if self._is_immediate_write():
            self._write_request_body_to_file(body)
        else:
            self._request_body_buffer = sanitize_json_bytes(body)

    def log_kiro_request_body(self, body: bytes) -> None:
        """Record sanitized upstream JSON without changing the sent request.

        Args:
            body: Upstream request bytes; never stored directly.
        """
        if not self._is_enabled():
            return
        if self._is_immediate_write():
            self._write_kiro_request_body_to_file(body)
        else:
            self._kiro_request_body_buffer = sanitize_json_bytes(body)

    def log_raw_chunk(self, chunk: bytes) -> None:
        """Record only size/hash for each binary or fragmented upstream chunk.

        Args:
            chunk: Untrusted upstream bytes, never decoded or reassembled here.
        """
        if not self._is_enabled():
            return
        if self._is_immediate_write():
            self._append_raw_chunk_to_file(chunk)
        else:
            self._raw_chunks_buffer.extend(summarize_payload(chunk))

    def log_modified_chunk(self, chunk: bytes) -> None:
        """Record sanitized complete JSON/SSE or summarize the entire fragment.

        Args:
            chunk: Client-facing bytes; incomplete frames are never buffered raw.
        """
        if not self._is_enabled():
            return
        if self._is_immediate_write():
            self._append_modified_chunk_to_file(chunk)
        else:
            self._modified_chunks_buffer.extend(sanitize_modified_chunk(chunk))

    def log_error_info(self, status_code: int, error_message: str = "") -> None:
        """Write an HTTP status and size/hash summary of unstructured error text.

        Args:
            status_code: HTTP error status.
            error_message: Potentially sensitive exception or upstream error text.
        """
        if not self._is_enabled():
            return
        error_info = {
            "status_code": status_code,
            "error_message": json.loads(summarize_payload(
                error_message.encode("utf-8", errors="surrogatepass")
            )),
        }
        self._write_diagnostic("error_info.json", json.dumps(error_info, indent=2).encode("utf-8"))

    def flush_on_error(self, status_code: int, error_message: str = "") -> None:
        """Flush already-safe buffers and save diagnostics even for bodyless errors.

        Args:
            status_code: HTTP error status.
            error_message: Free-form error text, retained only as a size/hash summary.
        """
        if not self._is_enabled():
            self._clear_buffers()
            return
        try:
            if not self._is_immediate_write():
                self._reset_directory()
                for name, content in (
                    ("request_body.json", self._request_body_buffer),
                    ("kiro_request_body.json", self._kiro_request_body_buffer),
                    ("response_stream_raw.txt", self._raw_chunks_buffer),
                    ("response_stream_modified.txt", self._modified_chunks_buffer),
                ):
                    if content:
                        self._write_diagnostic(name, bytes(content))
            self.log_error_info(status_code, error_message)
            self._write_app_logs_to_file()
        except OSError:
            logger.error("[DebugLogger] Cannot flush debug files; check directory permissions.")
        finally:
            self._clear_buffers()

    def discard_buffers(self) -> None:
        """Save app-log summaries only in all mode, then remove every buffer/sink."""
        try:
            if self._is_immediate_write():
                self._write_app_logs_to_file()
        finally:
            self._clear_buffers()

    def _write_diagnostic(self, name: str, content: bytes, *, append: bool = False) -> None:
        """Write bytes that have already crossed a sanitization boundary.

        Args:
            name: Internal fixed diagnostic filename, never an upstream filename.
            content: Sanitized bytes, not original payloads.
            append: Whether to append an independently safe stream record.
        """
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            with (self.debug_dir / name).open("ab" if append else "wb") as output:
                output.write(content)
        except OSError:
            # Do not log exception strings, filenames, or payloads on failure.
            logger.error("[DebugLogger] Cannot write debug file; check directory permissions.")

    def _write_request_body_to_file(self, body: bytes) -> None:
        """Sanitize client JSON before writing the request diagnostic file."""
        self._write_diagnostic("request_body.json", sanitize_json_bytes(body))

    def _write_kiro_request_body_to_file(self, body: bytes) -> None:
        """Sanitize upstream JSON before writing the request diagnostic file."""
        self._write_diagnostic("kiro_request_body.json", sanitize_json_bytes(body))

    def _append_raw_chunk_to_file(self, chunk: bytes) -> None:
        """Append only a size/hash summary, including for directly called helpers."""
        self._write_diagnostic("response_stream_raw.txt", summarize_payload(chunk), append=True)

    def _append_modified_chunk_to_file(self, chunk: bytes) -> None:
        """Append independently sanitized JSON/SSE, never raw stream fragments."""
        self._write_diagnostic("response_stream_modified.txt", sanitize_modified_chunk(chunk), append=True)

    def _write_app_logs_to_file(self) -> None:
        """Write existing summary-only application log entries when nonempty."""
        content = self._app_logs_buffer.getvalue()
        if content.strip():
            self._write_diagnostic("app_logs.txt", content.encode("utf-8"))


# Global instance; construction alone does not start capture or create files.
debug_logger = DebugLogger()
