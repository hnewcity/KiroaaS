"""Adapt upstream Responses SSE into the gateway's common binary event stream."""

import json
from typing import AsyncIterator, Any

import httpx

from extensions.kiro_stream_decoder import encode_eventstream_frame
from extensions.responses_adapter import ResponsesSSEDecoder, ResponsesStreamError
from kiro.usage import validate_responses_usage


def _frame(name: str, payload: dict, *, exception: bool = False) -> bytes:
    headers = {":message-type": "exception" if exception else "event", ":content-type": "application/json"}
    headers[":exception-type" if exception else ":event-type"] = name
    return encode_eventstream_frame(headers, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class ResponsesEventStream(httpx.AsyncByteStream):
    """Own and close the raw HTTP response across completion, error and cancellation."""

    def __init__(self, source: httpx.Response) -> None:
        self.source = source
        self.decoder = ResponsesSSEDecoder()
        self.flags: dict[str, Any] = {}
        self.closed = False
        self._reported_model: str | None = None

    def _encode_events(self, events: list[dict]) -> list[bytes]:
        frames = []
        for envelope in events:
            if len(envelope) != 1:
                raise ValueError("Responses adapter returned an invalid event union")
            name, payload = next(iter(envelope.items()))
            if name == "metadataEvent":
                raw = payload.get("upstreamEvent", {})
                response = raw.get("response", {}) if isinstance(raw, dict) else {}
                model = response.get("model") if isinstance(response, dict) else None
                if isinstance(model, str) and model and model != self._reported_model:
                    frames.append(_frame("assistantResponseEvent", {"modelId": model}))
                    self._reported_model = model
                usage = payload.get("usage")
                if usage is not None:
                    frames.append(_frame("meteringEvent", {"_responses_usage": validate_responses_usage(usage)}))
                # Terminal limitations are surfaced by the shared parser. Place
                # authoritative usage before the terminal event, not after it.
            frames.append(_frame(name, payload))
        return frames

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.source.aiter_bytes():
                try:
                    events = self.decoder.feed(chunk)
                except ResponsesStreamError as error:
                    for frame in self._encode_events(error.events):
                        yield frame
                    yield _frame(error.exception_type, {"message": error.message}, exception=True)
                    return
                for frame in self._encode_events(events):
                    yield frame
            try:
                final = self.decoder.finalize()
            except ResponsesStreamError as error:
                for frame in self._encode_events(error.events):
                    yield frame
                yield _frame(error.exception_type, {"message": error.message}, exception=True)
                return
            for frame in self._encode_events(final):
                yield frame
            self.flags["kiro_stream_completed"] = self.decoder.completed
        except (ValueError, UnicodeError) as error:
            yield _frame("InvalidNativeStreamException", {"message": str(error)}, exception=True)
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            await self.source.aclose()


def adapt_responses_stream(source: httpx.Response) -> httpx.Response:
    """Return a stream-compatible response; non-200 statuses remain untouched."""
    if source.status_code != 200:
        return source
    stream = ResponsesEventStream(source)
    headers = {key: value for key, value in source.headers.items()
               if key.lower() not in ("content-length", "content-encoding", "content-type")}
    headers["content-type"] = "application/vnd.amazon.eventstream"
    try:
        request = source.request
    except RuntimeError:
        request = None
    response = httpx.Response(source.status_code, headers=headers, stream=stream,
                              request=request, extensions=dict(source.extensions))
    stream.flags = response.extensions
    return response
