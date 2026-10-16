"""
Binary AWS eventstream decoding and upstream exception surfacing for Kiro streams.

Port of kiro-gateway fork commits 61d9b68 ("stream parsing") and dc0fe43
("surface refusals"), as a runtime patch so kiro/ stays zero-diff.

What upstream does: AwsEventStreamParser decodes each network chunk with
``chunk.decode("utf-8", errors="ignore")`` and scans the text for JSON objects.
A multi-byte character (CJK, emoji) split across two chunks is silently
dropped, and exception frames (throttling, ContentLengthExceeded, refusals)
carry no JSON key it looks for, so they vanish and the stream ends as a normal
``end_turn`` with partial or empty content.

What this extension does:
- DecodingEventStreamParser: a subclass that decodes real eventstream frames
  (prelude + message CRC32, resync on corruption, 16MB frame cap), routes them
  by ``:message-type`` / ``:event-type``, keeps the full metering payload, and
  emits ``{"type": "exception"}`` events for exception/error frames and for
  metadataEvent refusals (stopReason CONTENT_FILTERED). Falls back to the old
  text scan (with an incremental UTF-8 decoder) when the stream is not binary.
- streaming_core._process_chunk is wrapped to pass exception events on (upstream
  drops event types it does not know)
- streaming_core.parse_kiro_stream is wrapped to consume exception events:
  ContentLengthExceeded* sets RequestState.length_exceeded (the compat layer
  rewrites stop_reason to max_tokens / finish_reason to length); any other
  exception raises KiroStreamError so it is never disguised as a clean end.
- metering events are merged across the stream instead of last-one-wins.

Upstream's stream formatters (streaming_anthropic / streaming_openai) never see
an "exception" event, so no upstream code has to understand the new type.
"""

import codecs
import httpx
import dataclasses
import asyncio
import json
import struct
import zlib
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

from loguru import logger

from kiro.parsers import AwsEventStreamParser, find_matching_brace
from extensions.request_context import ensure_request_state
from kiro.native_reasoning import NativeMessageLedger, NativeReasoningError, normalize_delta, reasoning_store
from kiro.native_replay_storage import ReplayStorageError




# ==================================================================================================
# AWS binary eventstream (application/vnd.amazon.eventstream) frame decoding
# ==================================================================================================
#
# Frame layout (all integers big-endian):
#   [total_len u32][headers_len u32][prelude_crc u32][headers ...][payload ...][message_crc u32]
# prelude_crc = CRC32 of the first 8 bytes, message_crc = CRC32 of everything before it.

EVENTSTREAM_PRELUDE_SIZE = 12
EVENTSTREAM_MESSAGE_CRC_SIZE = 4
EVENTSTREAM_MIN_FRAME_SIZE = EVENTSTREAM_PRELUDE_SIZE + EVENTSTREAM_MESSAGE_CRC_SIZE
EVENTSTREAM_MAX_FRAME_SIZE = 16 * 1024 * 1024
# Consecutive decode errors (corrupt frames / resync episodes) before the decoder gives up
EVENTSTREAM_MAX_CONSECUTIVE_ERRORS = 5
# Max bytes skipped in a single resync episode before the decoder gives up
EVENTSTREAM_MAX_RESYNC_BYTES = 1024 * 1024

# Header value types per the AWS eventstream spec
_HEADER_TYPE_BOOL_TRUE = 0
_HEADER_TYPE_BOOL_FALSE = 1
_HEADER_TYPE_BYTE = 2
_HEADER_TYPE_SHORT = 3
_HEADER_TYPE_INTEGER = 4
_HEADER_TYPE_LONG = 5
_HEADER_TYPE_BYTE_ARRAY = 6
_HEADER_TYPE_STRING = 7
_HEADER_TYPE_TIMESTAMP = 8
_HEADER_TYPE_UUID = 9

# Fixed-size header value types: type -> (size, struct format or None for raw bytes)
_FIXED_HEADER_TYPES: Dict[int, Tuple[int, Optional[str]]] = {
    _HEADER_TYPE_BYTE: (1, ">b"),
    _HEADER_TYPE_SHORT: (2, ">h"),
    _HEADER_TYPE_INTEGER: (4, ">i"),
    _HEADER_TYPE_LONG: (8, ">q"),
    _HEADER_TYPE_TIMESTAMP: (8, ">q"),
    _HEADER_TYPE_UUID: (16, None),
}

HeaderValue = Union[bool, int, bytes, str]


class EventStreamDecodeError(ValueError):
    """Raised when an eventstream frame (or its headers) cannot be decoded."""


def parse_eventstream_headers(data: bytes) -> Dict[str, HeaderValue]:
    """
    Parses the headers section of an AWS eventstream frame.

    Each header is: name_len (u8), name (utf-8), value_type (u8), value.
    String (7) and byte array (6) values are prefixed with a u16 length.

    Args:
        data: Raw header bytes (exactly headers_len bytes of the frame)

    Returns:
        Mapping of header name to decoded value (str for string headers)

    Raises:
        EventStreamDecodeError: If the headers are malformed or truncated
    """
    headers: Dict[str, HeaderValue] = {}
    offset = 0
    end = len(data)

    def _require(count: int) -> None:
        if offset + count > end:
            raise EventStreamDecodeError(
                f"header truncated: need {count} bytes at offset {offset}, have {end - offset}"
            )

    while offset < end:
        _require(1)
        name_len = data[offset]
        offset += 1
        if name_len == 0:
            raise EventStreamDecodeError("header name length must not be 0")
        _require(name_len)
        name = data[offset:offset + name_len].decode("utf-8", errors="replace")
        offset += name_len

        _require(1)
        value_type = data[offset]
        offset += 1

        value: HeaderValue
        if value_type == _HEADER_TYPE_BOOL_TRUE:
            value = True
        elif value_type == _HEADER_TYPE_BOOL_FALSE:
            value = False
        elif value_type in (_HEADER_TYPE_STRING, _HEADER_TYPE_BYTE_ARRAY):
            _require(2)
            (value_len,) = struct.unpack_from(">H", data, offset)
            offset += 2
            _require(value_len)
            raw_value = bytes(data[offset:offset + value_len])
            offset += value_len
            value = raw_value.decode("utf-8", errors="replace") if value_type == _HEADER_TYPE_STRING else raw_value
        elif value_type in _FIXED_HEADER_TYPES:
            size, fmt = _FIXED_HEADER_TYPES[value_type]
            _require(size)
            if fmt is None:
                value = bytes(data[offset:offset + size])
            else:
                (value,) = struct.unpack_from(fmt, data, offset)
            offset += size
        else:
            raise EventStreamDecodeError(f"invalid header value type {value_type} for header '{name}'")

        headers[name] = value

    return headers


def encode_eventstream_frame(headers: Dict[str, str], payload: bytes) -> bytes:
    """
    Encodes a single AWS eventstream frame with string headers.

    Used by tests and debugging tools to build realistic Kiro stream data.

    Args:
        headers: Header name -> string value
        payload: Frame payload bytes

    Returns:
        Complete frame bytes including prelude and both CRCs
    """
    header_bytes = bytearray()
    for name, value in headers.items():
        name_raw = name.encode("utf-8")
        value_raw = value.encode("utf-8")
        header_bytes += struct.pack(">B", len(name_raw)) + name_raw
        header_bytes += struct.pack(">BH", _HEADER_TYPE_STRING, len(value_raw)) + value_raw

    total_len = EVENTSTREAM_MIN_FRAME_SIZE + len(header_bytes) + len(payload)
    prelude = struct.pack(">II", total_len, len(header_bytes))
    prelude += struct.pack(">I", zlib.crc32(prelude))
    message = prelude + bytes(header_bytes) + payload
    return message + struct.pack(">I", zlib.crc32(message))


class DecodingEventStreamParser(AwsEventStreamParser):
    """
    AwsEventStreamParser that decodes binary eventstream frames.

    Kiro returns application/vnd.amazon.eventstream binary frames. The parser decodes
    frames (validating prelude and message CRC32), routes them by the ``:message-type``
    and ``:event-type`` / ``:exception-type`` headers, and converts payloads into the
    same events the upstream parser emits. Data is buffered as bytes, so multi-byte
    UTF-8 characters split across network chunks are never lost.

    If the stream is clearly not binary eventstream (e.g. plain JSON text), the parser
    falls back to scanning the text for known JSON event patterns.

    Additional emitted event types (compared to upstream):
    - usage: full metering dict, e.g. {"usage": 0.12, "unit": "credit", ...}
    - exception: upstream exception/error frame or refusal
      (data: {"exception_type": str, "message": str, "raw": dict})

    Tool calls, content dedup and JSON-truncation diagnostics are inherited unchanged.
    """
    
    # Maps the :event-type header to the internal event type used by _process_event
    EVENT_TYPE_MAP: Dict[str, str] = {
        "assistantResponseEvent": "content",
        "meteringEvent": "usage",
        "contextUsageEvent": "context_usage",
        "followupPromptEvent": "followup",
    }
    
    # Stream modes
    _MODE_UNKNOWN = "unknown"
    _MODE_BINARY = "binary"
    _MODE_TEXT = "text"
    
    
    def __init__(self) -> None:
        """Initializes the parser."""
        super().__init__()
        self._init_decoder_state()
    
    def _init_decoder_state(self) -> None:
        """Initializes (or resets) binary decoder / mode detection state."""
        self._mode = self._MODE_UNKNOWN
        self._byte_buffer = bytearray()
        self._text_decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")
        self._consecutive_errors = 0
        self._ever_corrupt = False
        self._resyncing = False
        self._resync_skipped = 0
        self._decoder_stopped = False
        self._stop_reported = False
        self._stop_reason = ""
        self.frames_decoded = 0
        self.bytes_skipped = 0
    
    def feed(self, chunk: bytes) -> List[Dict[str, Any]]:
        """
        Adds chunk to buffer and returns parsed events.
        
        The first bytes of the stream decide the mode: a valid eventstream prelude
        selects binary frame decoding, anything else selects the plain-text fallback.
        
        Args:
            chunk: Bytes of data from stream
        
        Returns:
            List of events in {"type": str, "data": Any} format
        """
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            logger.warning(f"AwsEventStreamParser.feed expected bytes, got {type(chunk).__name__}")
            return []
        if not chunk:
            return []
        
        if self._mode == self._MODE_BINARY:
            if self._decoder_stopped:
                return []
            self._byte_buffer.extend(chunk)
            return self._decode_frames()
        
        if self._mode == self._MODE_TEXT:
            return self._feed_text(bytes(chunk))
        
        # Mode not decided yet: accumulate until we can tell
        self._byte_buffer.extend(chunk)
        mode = self._detect_mode()
        if mode is None:
            return []
        self._mode = mode
        if mode == self._MODE_BINARY:
            logger.debug("AWS eventstream: binary frame mode")
            return self._decode_frames()
        
        logger.debug("AWS eventstream: stream is not binary eventstream, using text fallback")
        pending = bytes(self._byte_buffer)
        self._byte_buffer.clear()
        return self._feed_text(pending)
    
    def expect_binary(self) -> None:
        """Honor an explicit eventstream content type instead of sniffing corrupted bytes."""
        self._mode = self._MODE_BINARY

    def _detect_mode(self) -> Optional[str]:
        """
        Decides whether the stream is binary eventstream or plain text.
        
        A frame is at most 16MB, so its big-endian total length always starts with
        0x00 (or 0x01 for exactly 16MB). Text never starts with those bytes, so the
        first byte is enough. A corrupt first frame is then handled by binary resync
        instead of silently switching to text scanning.
        
        Returns:
            Binary or text mode, or None if no data is buffered yet
        """
        if not self._byte_buffer:
            return None
        return self._MODE_BINARY if self._byte_buffer[0] <= 0x01 else self._MODE_TEXT
    
    # ------------------------------------------------------------------------------------------
    # Binary eventstream path
    # ------------------------------------------------------------------------------------------
    
    def _decode_frames(self) -> List[Dict[str, Any]]:
        """
        Decodes all complete frames currently in the byte buffer.
        
        Recovery follows the reference implementation: a bad prelude (CRC mismatch or
        impossible lengths) means frame boundaries are lost, so bytes are skipped until
        the next plausible prelude; a bad message CRC or malformed headers means the
        boundary is right but the data is corrupt, so the whole frame is skipped.
        
        Returns:
            Parsed events from all decoded frames
        """
        events: List[Dict[str, Any]] = []
        buf = self._byte_buffer
        
        while not self._decoder_stopped and len(buf) >= EVENTSTREAM_PRELUDE_SIZE:
            total_len, headers_len, prelude_crc = struct.unpack_from(">III", buf, 0)
            
            # The prelude CRC covers both lengths, so validate it before trusting them
            actual_prelude_crc = zlib.crc32(buf[:8])
            if actual_prelude_crc != prelude_crc:
                self._resync(f"prelude CRC mismatch (expected 0x{prelude_crc:08x}, got 0x{actual_prelude_crc:08x})")
                continue
            if total_len < EVENTSTREAM_MIN_FRAME_SIZE or total_len > EVENTSTREAM_MAX_FRAME_SIZE:
                self._resync(f"invalid frame length {total_len} (allowed {EVENTSTREAM_MIN_FRAME_SIZE}..{EVENTSTREAM_MAX_FRAME_SIZE})")
                continue
            if headers_len > total_len - EVENTSTREAM_MIN_FRAME_SIZE:
                self._resync(f"headers length {headers_len} exceeds frame length {total_len}")
                continue
            
            if len(buf) < total_len:
                break  # Wait for the rest of the frame
            
            frame = bytes(buf[:total_len])
            del buf[:total_len]
            
            (message_crc,) = struct.unpack_from(">I", frame, total_len - EVENTSTREAM_MESSAGE_CRC_SIZE)
            actual_message_crc = zlib.crc32(frame[:-EVENTSTREAM_MESSAGE_CRC_SIZE])
            if actual_message_crc != message_crc:
                self.bytes_skipped += total_len
                self._register_error(
                    f"message CRC mismatch (expected 0x{message_crc:08x}, got 0x{actual_message_crc:08x}), "
                    f"skipped corrupt frame of {total_len} bytes"
                )
                continue
            
            headers_end = EVENTSTREAM_PRELUDE_SIZE + headers_len
            try:
                headers = parse_eventstream_headers(frame[EVENTSTREAM_PRELUDE_SIZE:headers_end])
            except EventStreamDecodeError as e:
                self.bytes_skipped += total_len
                self._register_error(f"header parse failed ({e}), skipped frame of {total_len} bytes")
                continue
            
            payload = frame[headers_end:-EVENTSTREAM_MESSAGE_CRC_SIZE]
            self._consecutive_errors = 0
            self._resyncing = False
            self._resync_skipped = 0
            self.frames_decoded += 1
            
            event = self._handle_frame(headers, payload)
            if event:
                events.append(event)
        
        if self._decoder_stopped and not self._stop_reported:
            self._stop_reported = True
            events.append({
                "type": "exception",
                "data": {
                    "exception_type": "EventStreamDecodeError",
                    "message": self._stop_reason,
                    "raw": {},
                },
            })
        
        return events
    
    def _resync(self, reason: str) -> None:
        """
        Skips bytes after a prelude error until the next plausible frame start.
        
        A whole resync episode counts as one error; it ends at the next valid frame.
        
        Args:
            reason: Why the current position is not a valid prelude
        """
        buf = self._byte_buffer
        if not self._resyncing:
            self._resyncing = True
            self._register_error(f"{reason}; resyncing to next frame boundary")
            if self._decoder_stopped:
                return
        
        # A valid prelude can only start with 0x00 (or 0x01 for exactly 16MB frames)
        candidates = [pos for pos in (buf.find(b"\x00", 1), buf.find(b"\x01", 1)) if pos != -1]
        skip = min(candidates) if candidates else len(buf)
        del buf[:skip]
        self._resync_skipped += skip
        self.bytes_skipped += skip
        logger.debug(f"AWS eventstream resync: skipped {skip} bytes ({self._resync_skipped} in this episode)")
        
        if self._resync_skipped > EVENTSTREAM_MAX_RESYNC_BYTES:
            self._stop_decoder(
                f"no valid frame found after skipping {self._resync_skipped} bytes (last error: {reason})"
            )
    
    def _register_error(self, message: str) -> None:
        """
        Records a decode error and stops the decoder after too many in a row.
        
        Args:
            message: Error description
        """
        self._ever_corrupt = True
        self._consecutive_errors += 1
        logger.warning(
            f"AWS eventstream decode error {self._consecutive_errors}/{EVENTSTREAM_MAX_CONSECUTIVE_ERRORS}: {message}"
        )
        if self._consecutive_errors >= EVENTSTREAM_MAX_CONSECUTIVE_ERRORS:
            self._stop_decoder(f"{self._consecutive_errors} consecutive errors, last: {message}")
    
    def _stop_decoder(self, reason: str) -> None:
        """
        Stops the decoder; remaining and future data is discarded.
        
        Args:
            reason: Why decoding was abandoned
        """
        self._decoder_stopped = True
        self._stop_reason = f"AWS eventstream decoder stopped: {reason}"
        self._byte_buffer.clear()
        logger.error(self._stop_reason)
    
    def _handle_frame(self, headers: Dict[str, HeaderValue], payload: bytes) -> Optional[Dict[str, Any]]:
        """
        Routes a decoded frame by its :message-type header.
        
        Args:
            headers: Decoded frame headers
            payload: Frame payload bytes
        
        Returns:
            Parsed event or None
        """
        message_type = self._header_str(headers, ":message-type") or "event"
        
        if message_type == "event":
            return self._handle_event_frame(self._header_str(headers, ":event-type"), payload)
        if message_type == "exception":
            exception_type = self._header_str(headers, ":exception-type") or "UnknownException"
            return self._build_exception_event(exception_type, payload)
        if message_type == "error":
            error_code = self._header_str(headers, ":error-code") or "UnknownError"
            return self._build_exception_event(error_code, payload)
        
        logger.warning(f"AWS eventstream: ignoring frame with unknown :message-type '{message_type}'")
        return None
    
    @staticmethod
    def _header_str(headers: Dict[str, HeaderValue], name: str) -> Optional[str]:
        """
        Returns a header value if it is a string header.
        
        Args:
            headers: Decoded frame headers
            name: Header name
        
        Returns:
            String value or None
        """
        value = headers.get(name)
        return value if isinstance(value, str) else None
    
    def _handle_event_frame(self, event_type: Optional[str], payload: bytes) -> Optional[Dict[str, Any]]:
        """
        Decodes an event frame payload and dispatches it to the event processors.
        
        The :event-type header decides the event type; unknown or missing types fall back
        to the same JSON key detection used by the text path.
        
        Args:
            event_type: Value of the :event-type header, if any
            payload: Frame payload bytes (JSON)
        
        Returns:
            Parsed event or None
        """
        if not payload:
            return None
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._register_error(f"Invalid JSON/UTF-8 in '{event_type}' event ({len(payload)} bytes)")
            return None
        
        if event_type == "reasoningContentEvent":
            if isinstance(data, dict):
                data = {key: data[key] for key in ("text", "signature", "redactedContent") if data.get(key) is not None}
                if not data:
                    return None
            try:
                normalized = normalize_delta(data)
                return {"type": "native_reasoning", "data": normalized} if any(normalized.values()) else None
            except NativeReasoningError as error:
                return {"type": "exception", "data": {"exception_type": "InvalidReasoningEvent", "message": str(error)}}
        if event_type == "metadataEvent":
            return self._process_metadata_event(data)
        
        if event_type == "toolUseEvent":
            if not isinstance(data, dict):
                logger.warning(f"Unexpected toolUseEvent payload type: {type(data).__name__}")
                return None
            return self._process_tool_use_event(data)
        
        internal_type = self.EVENT_TYPE_MAP.get(event_type) if event_type else None
        
        if internal_type == "usage":
            # Metering payloads are normalized in _process_event (numbers are wrapped)
            return self._process_event(data, internal_type)
        
        if not isinstance(data, dict):
            logger.warning(f"Unexpected '{event_type}' payload type: {type(data).__name__}")
            return None
        
        if internal_type == "content" and isinstance(data.get("modelId"), str) and not data.get("content"):
            return {"type": "model_metadata", "data": data["modelId"]}
        if internal_type == "content" and "content" not in data:
            # e.g. an assistantResponseEvent carrying only metadata such as modelId
            logger.debug(f"Ignoring assistantResponseEvent without content, keys {list(data.keys())[:5]}")
            return None
        
        if internal_type is None:
            internal_type = self._detect_event_type_from_keys(data)
            if internal_type is None:
                logger.debug(f"Ignoring AWS event '{event_type}' with keys {list(data.keys())[:5]}")
                return None
        
        event = self._process_event(data, internal_type)
        if event is not None and internal_type == "content" and isinstance(data.get("modelId"), str):
            event["model_id"] = data["modelId"]
        return event
    
    def _detect_event_type_from_keys(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Detects the event type from JSON keys (fallback when :event-type is unknown).
        
        Mirrors EVENT_PATTERNS: the first key of the object decides the type.
        
        Args:
            data: Decoded payload
        
        Returns:
            Internal event type or None
        """
        key_map = {pattern[2:-2]: event_type for pattern, event_type in self.EVENT_PATTERNS}
        for key in data:
            if key in key_map:
                return key_map[key]
        return None
    
    def _process_content_event(self, data: dict) -> Optional[Dict[str, Any]]:
        """Binary assistant events are deltas: identical consecutive text is valid."""
        if self._mode == self._MODE_BINARY:
            content = data.get("content", "")
            if not isinstance(content, str):
                raise EventStreamDecodeError("assistantResponseEvent content must be text")
            self.last_content = content
            return {"type": "content", "data": content} if content else None
        return super()._process_content_event(data)

    def _process_tool_use_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processes a binary toolUseEvent payload.
        
        Kiro repeats name/toolUseId on every fragment, so fragments are grouped by
        toolUseId instead of by the first JSON key.
        
        Args:
            data: Decoded toolUseEvent payload
        
        Returns:
            Always None (tool calls are collected via get_tool_calls())
        """
        tool_use_id = data.get("toolUseId")
        current_id = self.current_tool_call.get("id") if self.current_tool_call else None
        is_new_call = "name" in data and (
            self.current_tool_call is None or (tool_use_id is not None and tool_use_id != current_id)
        )
        
        before = len(self.tool_calls)
        if is_new_call:
            self._process_tool_start_event(data)
        else:
            if "input" in data:
                self._process_tool_input_event(data)
            if data.get("stop"):
                self._process_tool_stop_event(data)
        completed = self.tool_calls[before:]
        return {"type": "tool_batch", "data": completed} if completed else None
    
    def finish(self) -> None:
        """Reject an incomplete binary frame at EOF instead of silently losing it."""
        if self._ever_corrupt:
            raise EventStreamDecodeError("Kiro stream contained corrupt frames; recovered bytes cannot be reported as a complete response")
        if self.current_tool_call and getattr(self, "_native_reasoning_seen", False):
            raise EventStreamDecodeError("Native stream ended before a tool-use stop event")
        if self._byte_buffer and (self._mode == self._MODE_BINARY or (
            self._mode == self._MODE_UNKNOWN and self._byte_buffer[0] < 32
        )):
            raise EventStreamDecodeError("Kiro eventstream ended inside a frame")

    def _process_metadata_event(self, data: Any) -> Optional[Dict[str, Any]]:
        """
        Handles metadataEvent frames.
        
        A refusal arrives as {"stopReason": "CONTENT_FILTERED", "stopDetails":
        {"refusal": {"category", "explanation"}}} with no content at all. It is
        surfaced as an exception event so it is never returned as an empty end_turn.
        
        Args:
            data: Decoded metadataEvent payload
        
        Returns:
            Exception event for refusals, otherwise None
        """
        if not isinstance(data, dict):
            return None
        stop_reason = data.get("stopReason")
        if stop_reason in ("MAX_TOKENS", "MAX_OUTPUT_TOKENS"):
            return {"type": "exception", "data": {"exception_type": "ContentLengthExceededException", "message": "Upstream reached its output limit"}}
        if data.get("responseStatus") == "incomplete" and stop_reason != "CONTENT_FILTERED":
            return {"type": "exception", "data": {"exception_type": "IncompleteResponseException", "message": "Upstream response is incomplete"}}
        details = data.get("stopDetails") if isinstance(data.get("stopDetails"), dict) else {}
        refusal = details.get("refusal") if isinstance(details.get("refusal"), dict) else None
        if stop_reason != "CONTENT_FILTERED" and refusal is None:
            logger.debug("metadataEvent fields: {}", list(data) if isinstance(data, dict) else type(data).__name__)
            return None
        category = (refusal or {}).get("category") or stop_reason or "CONTENT_FILTERED"
        explanation = (refusal or {}).get("explanation") or "The model refused to continue."
        message = f"{explanation} (reason: {category})"
        logger.warning(f"Kiro refused the request: {message}")
        return {
            "type": "exception",
            "data": {"exception_type": "ContentFilteredException", "message": message, "raw": data},
        }
    
    def _build_exception_event(self, exception_type: str, payload: bytes) -> Dict[str, Any]:
        """
        Builds an exception event from an exception/error frame.
        
        Args:
            exception_type: Value of :exception-type (or :error-code)
            payload: Frame payload (usually JSON like {"message": "..."})
        
        Returns:
            {"type": "exception", "data": {"exception_type", "message", "raw"}}
        """
        text = payload.decode("utf-8", errors="replace")
        raw: Dict[str, Any] = {}
        parsed: Any = None
        if text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, dict):
            raw = parsed
        elif text:
            raw = {"payload": text}
        
        message = raw.get("message") or raw.get("Message")
        if not isinstance(message, str):
            message = text
        
        logger.warning(f"Kiro stream exception: {exception_type} - {message[:500]}")
        return {
            "type": "exception",
            "data": {"exception_type": exception_type, "message": message, "raw": raw},
        }
    
    # ------------------------------------------------------------------------------------------
    # Plain-text fallback path
    # ------------------------------------------------------------------------------------------
    
    def _feed_text(self, data: bytes) -> List[Dict[str, Any]]:
        """
        Scans decoded text for known JSON event patterns (non-binary fallback).
        
        Uses an incremental UTF-8 decoder so characters split across chunks are kept.
        
        Args:
            data: Raw bytes
        
        Returns:
            Parsed events
        """
        self.buffer += self._text_decoder.decode(data)
        
        events = []
        
        while True:
            # Find nearest pattern
            earliest_pos = -1
            earliest_type = None
            
            for pattern, event_type in self.EVENT_PATTERNS:
                pos = self.buffer.find(pattern)
                if pos != -1 and (earliest_pos == -1 or pos < earliest_pos):
                    earliest_pos = pos
                    earliest_type = event_type
            
            if earliest_pos == -1:
                break
            
            # Find JSON end
            json_end = find_matching_brace(self.buffer, earliest_pos)
            if json_end == -1:
                # JSON not complete, wait for more data
                break
            
            json_str = self.buffer[earliest_pos:json_end + 1]
            self.buffer = self.buffer[json_end + 1:]
            
            try:
                data_obj = json.loads(json_str)
                event = self._process_event(data_obj, earliest_type)
                if event:
                    events.append(event)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON: {json_str[:100]}")
        
        return events
    
    def _process_event(self, data: Any, event_type: str) -> Optional[Dict[str, Any]]:
        """
        Processes a parsed event.
        
        Args:
            data: Parsed JSON (a dict, except metering payloads which may be a bare number)
            event_type: Event type
        
        Returns:
            Processed event or None
        """
        if event_type == 'content':
            return self._process_content_event(data)
        elif event_type == 'tool_start':
            return self._process_tool_start_event(data)
        elif event_type == 'tool_input':
            return self._process_tool_input_event(data)
        elif event_type == 'tool_stop':
            return self._process_tool_stop_event(data)
        elif event_type == 'usage':
            logger.debug("Metering fields: {}", list(data) if isinstance(data, dict) else type(data).__name__)
            return {"type": "usage", "data": self._normalize_metering(data)}
        elif event_type == 'context_usage':
            return {"type": "context_usage", "data": data.get('contextUsagePercentage', 0)}
        
        return None
    
    @staticmethod
    def _normalize_metering(data: Any) -> Dict[str, Any]:
        """
        Normalizes a metering payload into a dict, keeping every field.
        
        Args:
            data: Metering payload, e.g. {"usage": 0.12, "unit": "credit",
                "cacheReadInputTokens": 100} or a bare number
        
        Returns:
            Metering dict; a bare number becomes {"usage": number}
        """
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return {"usage": data}
        logger.warning(f"Unexpected metering payload type: {type(data).__name__}")
        return {}
    
    def reset(self) -> None:
        """Resets parser state, including the binary decoder."""
        super().reset()
        self._init_decoder_state()


# ==================================================================================================
# Stream-level hooks (streaming_core)
# ==================================================================================================

class KiroStreamError(Exception):
    """
    Raised when Kiro reports an exception/error frame (or a refusal) mid-stream.

    Attributes:
        exception_type: Upstream exception type (e.g. "ThrottlingException",
            "ContentFilteredException" for refusals)
        exception_message: Upstream exception message
    """

    def __init__(self, exception_type: str, exception_message: str) -> None:
        self.exception_type = exception_type
        self.exception_message = exception_message
        super().__init__(f"Kiro API stream exception [{exception_type}]: {exception_message}")


def is_content_length_exception(exception_type: Optional[str]) -> bool:
    """True for ContentLengthExceeded* exceptions (output hit its length limit)."""
    return bool(exception_type) and "ContentLengthExceeded" in exception_type


@dataclasses.dataclass
class StreamExceptionEvent:
    """Exception event yielded by _process_chunk; consumed before formatters see it."""
    exception_type: str
    exception_message: str
    type: str = "exception"


_installed = False
_originals: Dict[str, Any] = {}


def install_kiro_stream_decoder() -> None:
    """Swap in the binary-frame parser and surface upstream stream exceptions."""
    global _installed
    if _installed:
        return

    import kiro.streaming_core as streaming_core
    import kiro.streaming_anthropic as streaming_anthropic
    import kiro.streaming_openai as streaming_openai

    _originals.update(
        AwsEventStreamParser=streaming_core.AwsEventStreamParser,
        _process_chunk=streaming_core._process_chunk,
        parse_kiro_stream=streaming_core.parse_kiro_stream,
        parse_kiro_stream_anthropic=streaming_anthropic.parse_kiro_stream,
        parse_kiro_stream_openai=streaming_openai.parse_kiro_stream,
    )
    original_process_chunk = streaming_core._process_chunk
    # Whatever is installed now (upstream, or tool_name_alias's restoring wrapper).
    # Wrapping it keeps both patches regardless of install order.
    inner_parse = streaming_core.parse_kiro_stream

    async def process_chunk_with_exceptions(parser, chunk, thinking_parser):
        """Preserve exact event ordering, including a terminal exception position."""
        class _Replay:
            def __init__(self, event):
                self.event = event
            def feed(self, _chunk):
                return [self.event]

        for event in parser.feed(chunk):
            if event.get("type") == "exception":
                data = event.get("data") or {}
                yield StreamExceptionEvent(data.get("exception_type") or "UnknownException", data.get("message") or "")
                return
            if event.get("type") == "native_reasoning":
                parser._native_reasoning_seen = True
            legacy_parser = None if getattr(parser, "_native_reasoning_seen", False) else thinking_parser
            async for parsed in original_process_chunk(_Replay(event), chunk, legacy_parser):
                yield parsed

    async def parse_kiro_stream_surfacing(*args, **kwargs) -> AsyncGenerator[Any, None]:
        """Surface typed errors, merge usage, and bind completed native output."""
        state = ensure_request_state()
        merged_usage: Dict[str, Any] = {}
        ledger = NativeMessageLedger()
        state.native_ledger = ledger
        state.response_model_id = None
        if len(args) >= 3:
            args = (*args[:2], bool(args[2] and state.legacy_thinking), *args[3:])
        else:
            kwargs["enable_thinking_parser"] = bool(kwargs.get("enable_thinking_parser", True) and state.legacy_thinking)
        iterator = inner_parse(*args, **kwargs)
        try:
            async for event in iterator:
                if isinstance(event, StreamExceptionEvent):
                    if is_content_length_exception(event.exception_type):
                        state.length_exceeded = True
                        break
                    error = KiroStreamError(event.exception_type, event.exception_message)
                    state.stream_error = error
                    raise error
                if event.type == "model_metadata" and event.resolved_model_id:
                    if ledger.has_native and state.response_model_id and state.response_model_id != event.resolved_model_id:
                        raise NativeReasoningError("Upstream reported conflicting model IDs; native reasoning cannot be bound safely")
                    state.response_model_id = event.resolved_model_id
                if event.type == "usage" and isinstance(event.usage, dict):
                    merged_usage.update(event.usage)
                    event.usage = dict(merged_usage)
                index = ledger.feed(event)
                if event.type == "native_reasoning":
                    event.native_index = index
                yield event
            if state.wire_identity is not None and state.account_scope and state.upstream_model_id:
                await asyncio.to_thread(reasoning_store.record,
                    (state.client_scope, state.account_scope, state.response_model_id or state.upstream_model_id),
                    state.wire_identity, state.input_turn_anchor, ledger,
                )
        except (NativeReasoningError, ReplayStorageError, EventStreamDecodeError) as error:
            surfaced = KiroStreamError("InvalidNativeStreamException", str(error))
            state.stream_error = surfaced
            raise surfaced from error
        except (streaming_core.StreamDeadlineExceeded, streaming_core.StreamIdleTimeoutError, httpx.TimeoutException) as error:
            surfaced = KiroStreamError("RequestTimeoutException", str(error))
            state.stream_error = surfaced
            raise surfaced from error
        finally:
            await iterator.aclose()

    streaming_core.AwsEventStreamParser = DecodingEventStreamParser
    streaming_core._process_chunk = process_chunk_with_exceptions
    # collect_stream_to_result and both formatters look parse_kiro_stream up as a
    # module global, so all three modules get the surfacing wrapper.
    streaming_core.parse_kiro_stream = parse_kiro_stream_surfacing
    streaming_anthropic.parse_kiro_stream = parse_kiro_stream_surfacing
    streaming_openai.parse_kiro_stream = parse_kiro_stream_surfacing

    _installed = True
    logger.info("Installed Kiro binary eventstream decoder extension")


def uninstall_kiro_stream_decoder() -> None:
    """Restore patched attributes. Intended for unit tests."""
    global _installed
    if _originals:
        import kiro.streaming_core as streaming_core
        import kiro.streaming_anthropic as streaming_anthropic
        import kiro.streaming_openai as streaming_openai

        streaming_core.AwsEventStreamParser = _originals["AwsEventStreamParser"]
        streaming_core._process_chunk = _originals["_process_chunk"]
        streaming_core.parse_kiro_stream = _originals["parse_kiro_stream"]
        streaming_anthropic.parse_kiro_stream = _originals["parse_kiro_stream_anthropic"]
        streaming_openai.parse_kiro_stream = _originals["parse_kiro_stream_openai"]

    _originals.clear()
    _installed = False
