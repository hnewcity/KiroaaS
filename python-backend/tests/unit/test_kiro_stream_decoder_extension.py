"""
Tests for the binary eventstream decoder in extensions.kiro_stream_decoder.

Ported from the kiro-gateway fork's tests/unit/test_parsers.py (61d9b68), which
tested the same code inside kiro/parsers.py. Upstream's own parser tests
(test_parsers.py) are untouched and still run against kiro.parsers.
"""

import pytest


@pytest.fixture
def aws_event_parser():
    """The decoding parser under test (shadows the conftest fixture)."""
    from extensions.kiro_stream_decoder import DecodingEventStreamParser
    return DecodingEventStreamParser()


import json as _json
import struct as _struct
import zlib as _zlib
from unittest.mock import patch as _patch

from extensions.kiro_stream_decoder import (
    DecodingEventStreamParser,
    EVENTSTREAM_MAX_CONSECUTIVE_ERRORS,
    EVENTSTREAM_MAX_FRAME_SIZE,
    EventStreamDecodeError,
    encode_eventstream_frame,
    parse_eventstream_headers,
)


def _header(name: str, type_byte: int, value: bytes = b"") -> bytes:
    """Builds one raw eventstream header."""
    raw_name = name.encode("utf-8")
    return bytes([len(raw_name)]) + raw_name + bytes([type_byte]) + value


def _string_header(name: str, value: str) -> bytes:
    """Builds a string (type 7) header."""
    raw_value = value.encode("utf-8")
    return _header(name, 7, _struct.pack(">H", len(raw_value)) + raw_value)


def build_frame(headers, payload: bytes) -> bytes:
    """
    Builds an eventstream frame independently of kiro.parsers (so the decoder is
    not only tested against its own encoder).

    Args:
        headers: dict of string headers, or pre-encoded header bytes
        payload: payload bytes
    """
    if isinstance(headers, dict):
        header_bytes = b"".join(_string_header(k, v) for k, v in headers.items())
    else:
        header_bytes = headers
    total_len = 12 + len(header_bytes) + len(payload) + 4
    prelude = _struct.pack(">II", total_len, len(header_bytes))
    prelude += _struct.pack(">I", _zlib.crc32(prelude))
    message = prelude + header_bytes + payload
    return message + _struct.pack(">I", _zlib.crc32(message))


def event_frame(event_type, payload) -> bytes:
    """Builds an event frame with a JSON (or raw bytes) payload."""
    headers = {":message-type": "event", ":content-type": "application/json"}
    if event_type is not None:
        headers[":event-type"] = event_type
    body = payload if isinstance(payload, bytes) else _json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return build_frame(headers, body)


def exception_frame(exception_type: str, payload: bytes) -> bytes:
    """Builds an exception frame."""
    return build_frame(
        {":message-type": "exception", ":exception-type": exception_type, ":content-type": "application/json"},
        payload,
    )


def content_frame(text: str) -> bytes:
    """Builds an assistantResponseEvent frame."""
    return event_frame("assistantResponseEvent", {"content": text})


def feed_all(parser: DecodingEventStreamParser, chunks) -> list:
    """Feeds all chunks and returns every emitted event."""
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    return events


def contents(events) -> str:
    """Joins content event data."""
    return "".join(e["data"] for e in events if e["type"] == "content")


class TestEventStreamHeaders:
    """Tests for parse_eventstream_headers()."""

    def test_parses_string_header(self):
        """
        What it does: Parses a single string header.
        Goal: Ensure type 7 headers decode to str.
        """
        headers = parse_eventstream_headers(_string_header(":event-type", "toolUseEvent"))
        assert headers == {":event-type": "toolUseEvent"}

    def test_parses_all_value_types(self):
        """
        What it does: Parses headers of every spec value type.
        Goal: Ensure non-string headers are decoded and do not break offsets.
        """
        raw = b"".join([
            _header("t", 0),
            _header("f", 1),
            _header("b", 2, _struct.pack(">b", -5)),
            _header("s", 3, _struct.pack(">h", -300)),
            _header("i", 4, _struct.pack(">i", 123456)),
            _header("l", 5, _struct.pack(">q", 2 ** 40)),
            _header("ba", 6, _struct.pack(">H", 3) + b"\x01\x02\x03"),
            _header("ts", 8, _struct.pack(">q", 1700000000000)),
            _header("u", 9, bytes(range(16))),
            _string_header("str", "值"),
        ])
        headers = parse_eventstream_headers(raw)
        assert headers["t"] is True
        assert headers["f"] is False
        assert headers["b"] == -5
        assert headers["s"] == -300
        assert headers["i"] == 123456
        assert headers["l"] == 2 ** 40
        assert headers["ba"] == b"\x01\x02\x03"
        assert headers["ts"] == 1700000000000
        assert headers["u"] == bytes(range(16))
        assert headers["str"] == "值"

    def test_rejects_invalid_value_type(self):
        """
        What it does: Uses an undefined header value type.
        Goal: Ensure EventStreamDecodeError is raised.
        """
        with pytest.raises(EventStreamDecodeError):
            parse_eventstream_headers(_header("x", 10))

    def test_rejects_zero_name_length(self):
        """
        What it does: Uses a zero-length header name.
        Goal: Ensure EventStreamDecodeError is raised.
        """
        with pytest.raises(EventStreamDecodeError):
            parse_eventstream_headers(b"\x00\x07\x00\x00")

    def test_rejects_truncated_value(self):
        """
        What it does: Declares a string longer than the available bytes.
        Goal: Ensure EventStreamDecodeError is raised.
        """
        with pytest.raises(EventStreamDecodeError):
            parse_eventstream_headers(_header("x", 7, _struct.pack(">H", 10) + b"abc"))


class TestBinaryEventStreamDecoding:
    """Tests for binary frame decoding in DecodingEventStreamParser.feed()."""

    def test_decodes_single_content_frame(self, aws_event_parser):
        """
        What it does: Feeds one assistantResponseEvent frame.
        Goal: Ensure binary frames are decoded to content events.
        """
        events = aws_event_parser.feed(content_frame("Hello"))
        assert events == [{"type": "content", "data": "Hello"}]
        assert aws_event_parser.frames_decoded == 1

    def test_encoder_roundtrip(self, aws_event_parser):
        """
        What it does: Decodes a frame built by encode_eventstream_frame().
        Goal: Ensure the helper encoder matches the decoder and the spec builder.
        """
        payload = b'{"content":"roundtrip"}'
        headers = {":message-type": "event", ":event-type": "assistantResponseEvent"}
        assert encode_eventstream_frame(headers, payload) == build_frame(headers, payload)
        assert contents(aws_event_parser.feed(encode_eventstream_frame(headers, payload))) == "roundtrip"

    def test_multiple_frames_in_one_chunk(self, aws_event_parser):
        """
        What it does: Feeds several frames concatenated in a single chunk.
        Goal: Ensure all frames are decoded in order.
        """
        stream = content_frame("A") + content_frame("B") + event_frame("contextUsageEvent", {"contextUsagePercentage": 12.5})
        events = aws_event_parser.feed(stream)
        assert [e["type"] for e in events] == ["content", "content", "context_usage"]
        assert contents(events) == "AB"
        assert events[2]["data"] == 12.5

    def test_every_split_point_preserves_content(self):
        """
        What it does: Splits a multi-frame stream (with Chinese text) at every byte offset.
        Goal: Ensure frames and multi-byte UTF-8 survive any chunk boundary.
        """
        pieces = ["你好，", "世界！", "emoji 🚀 ", "结束"]
        stream = b"".join(content_frame(p) for p in pieces)
        stream += event_frame("meteringEvent", {"unit": "credit", "usage": 0.25})
        expected = "".join(pieces)

        for split in range(1, len(stream)):
            parser = DecodingEventStreamParser()
            events = feed_all(parser, [stream[:split], stream[split:]])
            assert contents(events) == expected, f"split at {split}"
            assert [e["data"] for e in events if e["type"] == "usage"] == [{"unit": "credit", "usage": 0.25}]

    def test_one_byte_chunks(self):
        """
        What it does: Feeds a stream one byte at a time.
        Goal: Ensure the decoder buffers bytes until each frame completes.
        """
        pieces = ["多字节", "字符", "测试"]
        stream = b"".join(content_frame(p) for p in pieces)
        parser = DecodingEventStreamParser()
        events = feed_all(parser, [stream[i:i + 1] for i in range(len(stream))])
        assert contents(events) == "多字节字符测试"

    def test_split_inside_multibyte_char_in_payload(self):
        """
        What it does: Splits exactly inside the 3-byte UTF-8 encoding of a Chinese char.
        Goal: Ensure the character is not dropped (old per-chunk decode bug).
        """
        frame = content_frame("中文")
        char_offset = frame.index("中".encode("utf-8"))
        parser = DecodingEventStreamParser()
        events = feed_all(parser, [frame[:char_offset + 1], frame[char_offset + 1:char_offset + 2], frame[char_offset + 2:]])
        assert contents(events) == "中文"

    def test_preserves_identical_binary_deltas(self, aws_event_parser):
        """
        What it does: Sends the same content in two consecutive frames.
        Goal: Ensure existing dedup behavior applies to binary frames.
        """
        events = aws_event_parser.feed(content_frame("same") + content_frame("same") + content_frame("next"))
        assert contents(events) == "samesamenext"

    def test_retains_model_metadata_without_empty_content(self, aws_event_parser):
        """
        What it does: Sends an assistantResponseEvent carrying only metadata.
        Goal: Ensure no empty content event is emitted.
        """
        events = aws_event_parser.feed(event_frame("assistantResponseEvent", {"modelId": "claude"}))
        assert events == [{"type": "model_metadata", "data": "claude"}]

    def test_unknown_event_type_falls_back_to_key_detection(self, aws_event_parser):
        """
        What it does: Uses an unknown :event-type and a missing :event-type.
        Goal: Ensure JSON key-pattern detection still routes the payload.
        """
        events = aws_event_parser.feed(
            event_frame("brandNewEvent", {"content": "x"}) + event_frame(None, {"contextUsagePercentage": 7})
        )
        assert events == [{"type": "content", "data": "x"}, {"type": "context_usage", "data": 7}]

    def test_ignores_unknown_event_without_known_keys(self, aws_event_parser):
        """
        What it does: Sends an unknown event with unknown keys, then content.
        Goal: Ensure it is skipped without breaking later frames.
        """
        events = aws_event_parser.feed(event_frame("codeReferenceEvent", {"references": []}) + content_frame("ok"))
        assert events == [{"type": "content", "data": "ok"}]

    def test_invalid_json_payload_is_skipped(self, aws_event_parser):
        """
        What it does: Sends an event frame whose payload is not JSON.
        Goal: Ensure it is skipped and decoding continues.
        """
        events = aws_event_parser.feed(event_frame("assistantResponseEvent", b"not json") + content_frame("ok"))
        assert contents(events) == "ok"

    def test_frame_with_non_string_headers(self, aws_event_parser):
        """
        What it does: Decodes a frame mixing string and non-string headers.
        Goal: Ensure routing still works when extra header types are present.
        """
        header_bytes = (
            _header(":flag", 0)
            + _header(":seq", 4, _struct.pack(">i", 3))
            + _string_header(":message-type", "event")
            + _header(":ts", 8, _struct.pack(">q", 1))
            + _string_header(":event-type", "assistantResponseEvent")
        )
        events = aws_event_parser.feed(build_frame(header_bytes, b'{"content":"typed"}'))
        assert contents(events) == "typed"


class TestBinaryToolUseEvents:
    """Tests for toolUseEvent frames."""

    def _tool_frames(self, tool_id: str, name: str, fragments, stop: bool = True) -> bytes:
        frames = [event_frame("toolUseEvent", {"name": name, "toolUseId": tool_id, "input": f}) for f in fragments]
        if stop:
            frames.append(event_frame("toolUseEvent", {"name": name, "toolUseId": tool_id, "stop": True}))
        return b"".join(frames)

    def test_assembles_fragmented_tool_call(self, aws_event_parser):
        """
        What it does: Streams a tool call as input fragments (name repeated every frame).
        Goal: Ensure fragments are joined into one tool call with valid arguments.
        """
        stream = self._tool_frames("t1", "get_weather", ['{"city":', '"北京"', "}"])
        emitted = aws_event_parser.feed(stream)
        assert emitted[0]["type"] == "tool_batch"
        assert emitted[0]["data"][0]["id"] == "t1"
        calls = aws_event_parser.get_tool_calls()
        assert len(calls) == 1
        assert calls[0]["id"] == "t1"
        assert calls[0]["function"]["name"] == "get_weather"
        assert _json.loads(calls[0]["function"]["arguments"]) == {"city": "北京"}

    def test_tool_call_split_at_every_offset(self):
        """
        What it does: Splits a tool-call stream at every byte offset.
        Goal: Ensure multi-byte arguments survive chunk boundaries.
        """
        stream = self._tool_frames("t1", "search", ['{"q":"', "数据", '库"}'])
        for split in range(1, len(stream)):
            parser = DecodingEventStreamParser()
            feed_all(parser, [stream[:split], stream[split:]])
            calls = parser.get_tool_calls()
            assert len(calls) == 1, f"split at {split}"
            assert _json.loads(calls[0]["function"]["arguments"]) == {"q": "数据库"}

    def test_sequential_tool_calls(self, aws_event_parser):
        """
        What it does: Streams two tool calls with different ids.
        Goal: Ensure both are collected separately.
        """
        stream = self._tool_frames("t1", "a", ['{"x":1}']) + self._tool_frames("t2", "b", ['{"y":', "2}"])
        aws_event_parser.feed(stream)
        calls = aws_event_parser.get_tool_calls()
        assert [c["id"] for c in calls] == ["t1", "t2"]
        assert _json.loads(calls[1]["function"]["arguments"]) == {"y": 2}

    def test_tool_call_without_stop_is_finalized(self, aws_event_parser):
        """
        What it does: Streams a tool call without a stop frame.
        Goal: Ensure get_tool_calls() finalizes it.
        """
        aws_event_parser.feed(self._tool_frames("t1", "a", ['{"k":"v"}'], stop=False))
        calls = aws_event_parser.get_tool_calls()
        assert len(calls) == 1
        assert _json.loads(calls[0]["function"]["arguments"]) == {"k": "v"}


class TestBinaryMeteringEvents:
    """Tests for meteringEvent frames."""

    def test_metering_dict_passthrough(self, aws_event_parser):
        """
        What it does: Sends a metering payload with cache fields.
        Goal: Ensure the full dict (not just the number) reaches consumers.
        """
        payload = {
            "unit": "credit",
            "unitPlural": "credits",
            "usage": 0.12,
            "cacheReadInputTokens": 1500,
            "cacheCreationInputTokens": 20,
        }
        events = aws_event_parser.feed(event_frame("meteringEvent", payload))
        assert events == [{"type": "usage", "data": payload}]

    def test_numeric_metering_is_wrapped(self, aws_event_parser):
        """
        What it does: Sends a bare-number metering payload.
        Goal: Ensure it is normalized to {"usage": number}.
        """
        events = aws_event_parser.feed(event_frame("meteringEvent", 0.5))
        assert events == [{"type": "usage", "data": {"usage": 0.5}}]

    def test_logs_metering_field_names_at_debug(self, aws_event_parser):
        """
        What it does: Checks field-name diagnostics without dumping upstream values.
        Goal: Ensure metering diagnostics are available at DEBUG level.
        """
        with _patch("extensions.kiro_stream_decoder.logger") as mock_logger:
            aws_event_parser.feed(event_frame("meteringEvent", {"usage": 1, "cacheReadInputTokens": 9}))
        logged = " ".join(str(c.args) for c in mock_logger.debug.call_args_list)
        assert "cacheReadInputTokens" in logged


class TestBinaryExceptionFrames:
    """Tests for exception / error frames."""

    def test_exception_frame_with_json_payload(self, aws_event_parser):
        """
        What it does: Sends an exception frame after some content.
        Goal: Ensure an exception event with type, message and raw payload is emitted.
        """
        stream = content_frame("partial") + exception_frame(
            "ContentLengthExceededException", b'{"message":"Output too long","reason":"LIMIT"}'
        )
        events = aws_event_parser.feed(stream)
        assert events[0] == {"type": "content", "data": "partial"}
        assert events[1] == {
            "type": "exception",
            "data": {
                "exception_type": "ContentLengthExceededException",
                "message": "Output too long",
                "raw": {"message": "Output too long", "reason": "LIMIT"},
            },
        }

    def test_exception_frame_with_text_payload(self, aws_event_parser):
        """
        What it does: Sends an exception frame with a non-JSON payload.
        Goal: Ensure the raw text becomes the message.
        """
        events = aws_event_parser.feed(exception_frame("ThrottlingException", "请求过多".encode("utf-8")))
        assert events == [{
            "type": "exception",
            "data": {"exception_type": "ThrottlingException", "message": "请求过多", "raw": {"payload": "请求过多"}},
        }]

    def test_exception_frame_without_type_header(self, aws_event_parser):
        """
        What it does: Sends an exception frame without :exception-type.
        Goal: Ensure a default exception type is used.
        """
        events = aws_event_parser.feed(build_frame({":message-type": "exception"}, b'{"message":"boom"}'))
        assert events[0]["data"]["exception_type"] == "UnknownException"
        assert events[0]["data"]["message"] == "boom"

    def test_error_message_type_uses_error_code(self, aws_event_parser):
        """
        What it does: Sends a :message-type=error frame.
        Goal: Ensure it is surfaced as an exception event named by :error-code.
        """
        frame = build_frame({":message-type": "error", ":error-code": "InternalServerError"}, b'{"message":"oops"}')
        events = aws_event_parser.feed(frame)
        assert events[0]["type"] == "exception"
        assert events[0]["data"]["exception_type"] == "InternalServerError"
        assert events[0]["data"]["message"] == "oops"


class TestBinaryCorruptionRecovery:
    """Tests for CRC validation and resynchronization."""

    def test_message_crc_corruption_skips_only_that_frame(self, aws_event_parser):
        """
        What it does: Corrupts a payload byte of the middle frame.
        Goal: Ensure the corrupt frame is dropped and following frames still decode.
        """
        bad = bytearray(content_frame("BAD"))
        bad[-6] ^= 0xFF  # inside payload
        events = aws_event_parser.feed(content_frame("one") + bytes(bad) + content_frame("two"))
        assert contents(events) == "onetwo"
        assert aws_event_parser.bytes_skipped == len(bad)

    def test_prelude_crc_corruption_resyncs(self, aws_event_parser):
        """
        What it does: Corrupts the prelude CRC of the middle frame.
        Goal: Ensure the decoder scans forward to the next valid frame.
        """
        bad = bytearray(content_frame("BAD"))
        bad[9] ^= 0xFF  # prelude CRC
        events = aws_event_parser.feed(content_frame("one") + bytes(bad) + content_frame("two"))
        assert contents(events) == "onetwo"

    def test_garbage_between_frames_resyncs(self, aws_event_parser):
        """
        What it does: Inserts garbage bytes (including zero bytes) between frames.
        Goal: Ensure resync finds the next frame boundary.
        """
        garbage = b"\xde\xad\x00\xbe\xef\x00\x00garbage\x01\x02"
        events = feed_all(aws_event_parser, [content_frame("one") + garbage[:5], garbage[5:] + content_frame("two")])
        assert contents(events) == "onetwo"

    def test_oversized_frame_length_resyncs(self, aws_event_parser):
        """
        What it does: Sends a prelude declaring a frame larger than 16MB.
        Goal: Ensure it is rejected without buffering and decoding continues.
        """
        prelude = _struct.pack(">II", EVENTSTREAM_MAX_FRAME_SIZE + 1, 0)
        prelude += _struct.pack(">I", _zlib.crc32(prelude))
        events = aws_event_parser.feed(content_frame("one") + prelude + content_frame("two"))
        assert contents(events) == "onetwo"

    def test_invalid_header_type_skips_frame(self, aws_event_parser):
        """
        What it does: Sends a CRC-valid frame with an invalid header value type.
        Goal: Ensure the frame is skipped and decoding continues.
        """
        bad = build_frame(_header("x", 42), b'{"content":"BAD"}')
        events = aws_event_parser.feed(bad + content_frame("ok"))
        assert contents(events) == "ok"

    def test_gives_up_after_consecutive_errors(self, aws_event_parser):
        """
        What it does: Sends too many corrupt frames in a row.
        Goal: Ensure the decoder stops, logs an error and reports a decode exception once.
        """
        corrupt = []
        for i in range(EVENTSTREAM_MAX_CONSECUTIVE_ERRORS):
            frame = bytearray(content_frame(f"bad{i}"))
            frame[-1] ^= 0xFF
            corrupt.append(bytes(frame))

        with _patch("extensions.kiro_stream_decoder.logger") as mock_logger:
            events = aws_event_parser.feed(content_frame("ok") + b"".join(corrupt) + content_frame("lost"))
            later = aws_event_parser.feed(content_frame("also lost"))

        assert contents(events) == "ok"
        exceptions = [e for e in events if e["type"] == "exception"]
        assert len(exceptions) == 1
        assert exceptions[0]["data"]["exception_type"] == "EventStreamDecodeError"
        assert later == []
        assert mock_logger.error.called

    def test_error_counter_resets_after_valid_frame(self, aws_event_parser):
        """
        What it does: Interleaves corrupt and valid frames.
        Goal: Ensure only consecutive errors count toward the limit.
        """
        stream = b""
        for i in range(EVENTSTREAM_MAX_CONSECUTIVE_ERRORS * 2):
            bad = bytearray(content_frame(f"bad{i}"))
            bad[-1] ^= 0xFF
            stream += bytes(bad) + content_frame(f"ok{i}")
        events = aws_event_parser.feed(stream)
        assert not [e for e in events if e["type"] == "exception"]
        assert contents(events) == "".join(f"ok{i}" for i in range(EVENTSTREAM_MAX_CONSECUTIVE_ERRORS * 2))

    def test_reset_restores_binary_decoder(self, aws_event_parser):
        """
        What it does: Stops the decoder, then resets the parser.
        Goal: Ensure reset() clears decoder state so a new stream can be parsed.
        """
        bad = bytearray(content_frame("bad"))
        bad[-1] ^= 0xFF
        aws_event_parser.feed(bytes(bad) * EVENTSTREAM_MAX_CONSECUTIVE_ERRORS)
        aws_event_parser.reset()
        assert contents(aws_event_parser.feed(content_frame("fresh"))) == "fresh"


class TestPlainTextFallback:
    """Tests for the non-binary (plain JSON text) fallback path."""

    def test_text_split_inside_multibyte_char(self, aws_event_parser):
        """
        What it does: Splits plain JSON text inside a Chinese character.
        Goal: Ensure the incremental decoder keeps the character (old code dropped it).
        """
        raw = '{"content":"你好世界"}'.encode("utf-8")
        split = raw.index("你".encode("utf-8")) + 1
        events = feed_all(aws_event_parser, [raw[:split], raw[split:]])
        assert events == [{"type": "content", "data": "你好世界"}]

    def test_text_every_split_point(self):
        """
        What it does: Splits a plain-text stream at every byte offset.
        Goal: Ensure no characters are lost anywhere.
        """
        raw = '{"content":"中文"}{"content":"测试"}{"usage":0.3}'.encode("utf-8")
        for split in range(1, len(raw)):
            parser = DecodingEventStreamParser()
            events = feed_all(parser, [raw[:split], raw[split:]])
            assert contents(events) == "中文测试", f"split at {split}"
            assert events[-1] == {"type": "usage", "data": {"usage": 0.3}}

    def test_text_metering_dict_passthrough(self, aws_event_parser):
        """
        What it does: Sends a plain-text metering object with cache fields.
        Goal: Ensure every field is kept on the text path too.
        """
        events = aws_event_parser.feed(b'{"usage":0.2,"unit":"credit","cacheReadInputTokens":42}')
        assert events == [{"type": "usage", "data": {"usage": 0.2, "unit": "credit", "cacheReadInputTokens": 42}}]

