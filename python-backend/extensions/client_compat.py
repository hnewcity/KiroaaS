"""
Client-facing error mapping and stream fixes, ported from the kiro-gateway fork
(4ddea22, 61d9b68, dc0fe43). kiro/ stays zero-diff.

Upstream builds its error responses inline in the route handlers (always
``api_error``, the upstream status code), so this extension works at two layers:

1. Module globals the routes look up on every request are wrapped:
   - stream_with_first_token_retry_anthropic: SSE ``ping`` events while
     upstream is silent (SSE_PING_INTERVAL, default 25s, 0 = off), and stream
     failures become one Anthropic error event with a type clients act on
     (rate_limit_error / overloaded_error / invalid_request_error for refusals)
   - stream_kiro_to_anthropic / collect_anthropic_response: stop_reason
     ``max_tokens`` when Kiro reported ContentLengthExceeded
   - stream_kiro_to_openai_internal: finish_reason ``length`` for the same case,
     an OpenAI error chunk for stream exceptions, numeric ``credits_used``
   - kiro.kiro_errors.enhance_kiro_error: records the Kiro error reason
2. A pure ASGI middleware on /v1/messages and /v1/chat/completions rewrites the
   JSON error responses using what the hooks recorded (extensions.request_context):

   Anthropic (/v1/messages):
   - context overflow -> 400 invalid_request_error "prompt is too long: N tokens
     > M maximum" (the wording Claude Code recognises and auto-compacts on)
   - monthly quota    -> 402 billing_error
   - 429              -> rate_limit_error + Retry-After
   - 5xx / 408        -> overloaded_error (retryable)
   - refusal / other stream exception in non-streaming mode -> 400
     invalid_request_error / 529 overloaded_error (instead of a 500)
   OpenAI (/v1/chat/completions):
   - context overflow -> error type context_length_exceeded

   For streams it only drops the duplicate error event upstream's route adds
   after the mapped one.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from loguru import logger

from extensions.kiro_stream_decoder import KiroStreamError
from extensions.request_context import (
    current_state,
    ensure_request_state,
    reset_request_state,
    start_request_state,
)


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


# Interval for SSE ping events sent to Anthropic clients while waiting on upstream (seconds, 0 = off)
SSE_PING_INTERVAL: float = _env_float("SSE_PING_INTERVAL", "25")

ANTHROPIC_PATH = "/v1/messages"
OPENAI_PATH = "/v1/chat/completions"


# ==================================================================================================
# Anthropic error mapping (kiro/kiro_errors.py in the fork)
# ==================================================================================================

@dataclass
class AnthropicErrorMapping:
    """How an upstream Kiro error is presented to an Anthropic client."""
    status_code: int
    error_type: str
    message: str
    headers: Dict[str, str]


def format_prompt_too_long(estimated_tokens: int, max_tokens: int) -> str:
    """
    Context overflow message in Anthropic's official wording.

    Claude Code recognises "prompt is too long: N tokens > M maximum" and can
    compact + retry; custom wording is treated as a hard failure. N is forced
    above M so the message is never self-contradictory.
    """
    n = max(int(estimated_tokens or 0), int(max_tokens) + 1)
    return f"prompt is too long: {n} tokens > {int(max_tokens)} maximum"


def map_upstream_error_for_anthropic(
    status_code: int,
    reason: str,
    message: str,
    estimated_tokens: int = 0,
    max_input_tokens: int = 200000,
) -> AnthropicErrorMapping:
    """
    Maps a Kiro HTTP error to an Anthropic error response.

    - Context overflow -> 400 invalid_request_error with official wording
    - Monthly quota    -> 402 billing_error (not retryable)
    - 429              -> 429 rate_limit_error + Retry-After so clients back off
    - 5xx / 408        -> original status, overloaded_error (retryable)
    - Everything else  -> original status, api_error / invalid_request_error for 400
    """
    if reason == "CONTENT_LENGTH_EXCEEDS_THRESHOLD":
        return AnthropicErrorMapping(
            400, "invalid_request_error",
            format_prompt_too_long(estimated_tokens, max_input_tokens), {},
        )
    if reason == "MONTHLY_REQUEST_COUNT":
        return AnthropicErrorMapping(402, "billing_error", message, {})
    if status_code == 429:
        return AnthropicErrorMapping(429, "rate_limit_error", message, {"Retry-After": "5"})
    if status_code == 408 or status_code >= 500:
        return AnthropicErrorMapping(status_code, "overloaded_error", message, {})
    if status_code == 400:
        return AnthropicErrorMapping(400, "invalid_request_error", message, {})
    return AnthropicErrorMapping(status_code, "api_error", message, {})


def stream_exception_status(error: KiroStreamError) -> Tuple[int, str]:
    """(status, Anthropic error type) for an upstream exception in a non-streaming response.

    Refusals are not retryable -> 400 invalid_request_error; other upstream
    exceptions are transient -> 529 overloaded_error.
    """
    if error.exception_type == "ContentFilteredException":
        return 400, "invalid_request_error"
    if error.exception_type == "RequestTimeoutException":
        return 504, "api_error"
    if error.exception_type in ("InvalidNativeStreamException", "InvalidReasoningEvent"):
        return 502, "api_error"
    return 529, "overloaded_error"


# ==================================================================================================
# Anthropic SSE helpers (kiro/streaming_anthropic.py in the fork)
# ==================================================================================================

PING_SSE_EVENT = 'event: ping\ndata: {"type": "ping"}\n\n'


def format_sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """Same format as upstream streaming_anthropic.format_sse_event."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def with_sse_pings(
    source: AsyncGenerator[str, None],
    interval: float,
) -> AsyncGenerator[str, None]:
    """
    Interleaves Anthropic `ping` events into an SSE stream while upstream is silent.

    Long first-token waits or long thinking can leave the connection idle long
    enough for reverse proxies / clients to drop it. A ping is emitted whenever
    no chunk arrived for `interval` seconds; busy streams are never delayed.
    """
    if interval <= 0:
        async for chunk in source:
            yield chunk
        return

    iterator = source.__aiter__()
    pending: Optional[asyncio.Task] = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield PING_SSE_EVENT
                continue
            task, pending = pending, None
            try:
                chunk = task.result()
            except StopAsyncIteration:
                return
            yield chunk
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            except Exception as e:  # source already failing; we're cleaning up
                logger.debug(f"Source stream error during ping cleanup: {e}")
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except RuntimeError as e:
                logger.debug(f"Could not close source stream: {e}")


def _anthropic_type_for_status(status_code: Optional[int]) -> Optional[str]:
    if status_code == 429:
        return "rate_limit_error"
    if status_code is not None and (status_code == 408 or status_code >= 500):
        return "overloaded_error"
    return None


def stream_error_event(error: BaseException) -> str:
    """
    Builds an Anthropic SSE `error` event from a streaming exception.

    Exceptions raised by upstream's retry wrapper carry a JSON Anthropic error
    body; it is forwarded, with its generic api_error type replaced by
    rate_limit_error / overloaded_error when the upstream status says so.
    Refusals are invalid_request_error (retrying will not help). Anything else
    is overloaded_error, which clients treat as retryable.
    """
    if isinstance(error, KiroStreamError) and error.exception_type == "ContentFilteredException":
        return format_sse_event("error", {
            "type": "error",
            "error": {"type": "invalid_request_error", "message": error.exception_message},
        })
    body: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(str(error))
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            body = parsed
    except (json.JSONDecodeError, TypeError):
        body = None
    if body is not None:
        if body["error"].get("type") == "api_error":
            state = current_state()
            mapped = _anthropic_type_for_status(state.upstream_status if state else None)
            if mapped:
                body["error"]["type"] = mapped
    else:
        body = {
            "type": "error",
            "error": {
                "type": "overloaded_error",
                "message": str(error) or "Upstream stream was interrupted. Please retry.",
            },
        }
    return format_sse_event("error", body)


def _force_stop_reason(chunk: str, stop_reason: str) -> str:
    """Rewrites stop_reason in an Anthropic message_delta event."""
    if not chunk.startswith("event: message_delta"):
        return chunk
    try:
        _, data_line = chunk.split("\ndata: ", 1)
        data = json.loads(data_line)
        data.setdefault("delta", {})["stop_reason"] = stop_reason
        return format_sse_event("message_delta", data)
    except (ValueError, AttributeError):
        return chunk


# ==================================================================================================
# OpenAI stream helpers (kiro/streaming_openai.py in the fork)
# ==================================================================================================

def _extract_credits_used(metering_data: Any) -> Optional[float]:
    """Credit amount from a Kiro metering dict (the "usage" field), or None."""
    if isinstance(metering_data, (int, float)) and not isinstance(metering_data, bool):
        return metering_data
    if not isinstance(metering_data, dict):
        return None
    credits = metering_data.get("usage")
    if isinstance(credits, (int, float)) and not isinstance(credits, bool):
        return credits
    return None


def format_openai_error_chunk(exception_type: str, exception_message: str) -> str:
    """Upstream stream exception as an OpenAI-style SSE error chunk (routes_openai's shape)."""
    error_payload = {
        "error": {
            "message": exception_message or exception_type,
            "type": "kiro_api_error",
            "code": exception_type,
        }
    }
    return f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"


def _fix_openai_chunk(chunk: str, length_exceeded: bool) -> str:
    """finish_reason -> length after ContentLengthExceeded; credits_used -> number."""
    if not chunk.startswith("data: {") or '"finish_reason": null' in chunk:
        return chunk
    try:
        data = json.loads(chunk[len("data: "):])
    except ValueError:
        return chunk
    changed = False
    choices = data.get("choices") or []
    if length_exceeded and choices and choices[0].get("finish_reason") in ("stop", "tool_calls"):
        choices[0]["finish_reason"] = "length"
        changed = True
    usage = data.get("usage")
    if isinstance(usage, dict) and isinstance(usage.get("credits_used"), dict):
        credits = _extract_credits_used(usage["credits_used"])
        if credits:
            usage["credits_used"] = credits
        else:
            del usage["credits_used"]
        changed = True
    if not changed:
        return chunk
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ==================================================================================================
# ASGI middleware: request state + error response rewriting
# ==================================================================================================

def _max_input_tokens(app: Any, model: Optional[str]) -> int:
    """Best-effort max input tokens for the requested model (200000 fallback)."""
    from kiro.config import DEFAULT_MAX_INPUT_TOKENS

    try:
        account = app.state.account_manager.get_first_account()
        return int(account.model_cache.get_max_input_tokens(model))
    except Exception:
        return DEFAULT_MAX_INPUT_TOKENS


def rewrite_error_response(
    path: str, status: int, body: bytes, state: Any, app: Any
) -> Optional[Tuple[int, bytes, Dict[str, str]]]:
    """
    Maps an upstream-derived JSON error response for the client, or returns None.

    Only responses that echo the recorded upstream status are touched, so the
    gateway's own errors (validation, "All accounts failed", etc.) pass through.
    """
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return None
    error = payload["error"]
    message = error.get("message") or ""

    if path == ANTHROPIC_PATH:
        stream_error = state.stream_error
        if isinstance(stream_error, KiroStreamError) and status == 500:
            new_status, error_type = stream_exception_status(stream_error)
            new_body = {"type": "error", "error": {
                "type": error_type,
                "message": stream_error.exception_message or stream_error.exception_type,
            }}
            return new_status, json.dumps(new_body).encode(), {}
        if state.upstream_status is not None and status == state.upstream_status:
            mapping = map_upstream_error_for_anthropic(
                status, state.upstream_reason or "UNKNOWN", message or "Upstream error",
                max_input_tokens=_max_input_tokens(app, state.model),
            )
            new_body = {"type": "error", "error": {"type": mapping.error_type, "message": mapping.message}}
            return mapping.status_code, json.dumps(new_body).encode(), mapping.headers
        return None

    if path == OPENAI_PATH:
        if (
            state.upstream_reason == "CONTENT_LENGTH_EXCEEDS_THRESHOLD"
            and status == state.upstream_status
            and error.get("type") == "kiro_api_error"
        ):
            error["type"] = "context_length_exceeded"
            return status, json.dumps(payload).encode(), {}
    return None


class ClientCompatMiddleware:
    """Pure ASGI middleware (no body buffering for streams)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path") if scope.get("type") == "http" else None
        if scope.get("method") != "POST" or path not in (ANTHROPIC_PATH, OPENAI_PATH):
            await self.app(scope, receive, send)
            return

        state, token = start_request_state()
        from extensions.session_identity import read_identity_headers
        try:
            identity_headers = read_identity_headers(scope.get("headers", []))
        except ValueError as error:
            body = {"type": "error", "error": {"type": "invalid_request_error", "message": str(error)}}
            from starlette.responses import JSONResponse
            try:
                await JSONResponse(body, status_code=400)(scope, receive, send)
            finally:
                reset_request_state(token)
            return
        for name, value in identity_headers.items():
            setattr(state, name, value)
        start_message: Optional[Dict[str, Any]] = None
        buffered: List[bytes] = []
        mode = "passthrough"  # passthrough | buffer-error | sse
        error_event_sent = False

        async def send_wrapper(message):
            nonlocal start_message, mode, error_event_sent
            if message["type"] == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                content_type = headers.get(b"content-type", b"").decode("latin-1")
                if message["status"] >= 400 and "application/json" in content_type:
                    mode, start_message = "buffer-error", message
                    return
                if "text/event-stream" in content_type:
                    mode = "sse"
                await send(message)
                return

            if message["type"] == "http.response.body":
                if mode == "buffer-error":
                    buffered.append(message.get("body", b""))
                    if message.get("more_body", False):
                        return
                    await self._send_error(path, start_message, b"".join(buffered), state, scope, send)
                    return
                if mode == "sse" and state.retry_budget is not None:
                    state.retry_budget.observe_output(message.get("body", b""))
                if mode == "sse" and path == ANTHROPIC_PATH:
                    chunk = message.get("body", b"")
                    if chunk.startswith(b"event: error"):
                        if error_event_sent:
                            # upstream's route adds its own api_error event after ours
                            message = {**message, "body": b""}
                        error_event_sent = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_request_state(token)

    @staticmethod
    async def _send_error(path, start_message, body, state, scope, send):
        status = start_message["status"]
        headers = list(start_message.get("headers", []))
        rewritten = None
        try:
            rewritten = rewrite_error_response(path, status, body, state, scope.get("app"))
        except Exception as e:  # never lose the response over a mapping bug
            logger.warning(f"Error response mapping failed: {e}")
        if rewritten is not None:
            new_status, body, extra = rewritten
            if new_status != status:
                logger.info(f"Mapped upstream error for client: HTTP {status} -> {new_status}")
            status = new_status
            skip = {b"content-length"} | {k.lower().encode("latin-1") for k in extra}
            headers = [(k, v) for k, v in headers if k.lower() not in skip]
            headers += [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in extra.items()]
            headers.append((b"content-length", str(len(body)).encode("latin-1")))
        await send({**start_message, "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})


# ==================================================================================================
# Install
# ==================================================================================================

_installed_apps: List[Any] = []
_originals: Dict[str, Any] = {}


def install_client_compat(app: Any) -> None:
    """Wrap the route-facing globals and add the ASGI middleware to the app.

    Install after kiro_payload_builder (it wraps routes_anthropic.anthropic_to_kiro
    again to record the requested model) and after kiro_stream_decoder.
    """
    if app in _installed_apps:
        return

    if not _originals:
        _install_hooks()

    app.add_middleware(ClientCompatMiddleware)
    _installed_apps.append(app)
    logger.info("Installed client compatibility extension (error mapping, SSE pings)")


def _install_hooks() -> None:
    import kiro.kiro_errors as kiro_errors
    import kiro.routes_anthropic as routes_anthropic
    import kiro.streaming_anthropic as streaming_anthropic
    import kiro.streaming_openai as streaming_openai
    import kiro.truncation_state as truncation_state

    _originals.update(
        enhance_kiro_error=kiro_errors.enhance_kiro_error,
        anthropic_to_kiro=routes_anthropic.anthropic_to_kiro,
        retry_anthropic=routes_anthropic.stream_with_first_token_retry_anthropic,
        collect_anthropic=routes_anthropic.collect_anthropic_response,
        stream_kiro_to_anthropic=streaming_anthropic.stream_kiro_to_anthropic,
        stream_openai_internal=streaming_openai.stream_kiro_to_openai_internal,
        save_content_truncation=truncation_state.save_content_truncation,
    )
    o = _originals

    def enhance_kiro_error(error_json):
        info = o["enhance_kiro_error"](error_json)
        state = current_state()
        if state is not None:
            state.upstream_reason = info.reason
        return info

    def anthropic_to_kiro(request, conversation_id, profile_arn):
        ensure_request_state().model = request.model
        return o["anthropic_to_kiro"](request, conversation_id, profile_arn)

    async def stream_with_first_token_retry_anthropic(*args, **kwargs):
        try:
            async for chunk in with_sse_pings(o["retry_anthropic"](*args, **kwargs), SSE_PING_INTERVAL):
                yield chunk
        except Exception as e:
            # One mapped error event; the route still sees the exception for logging
            yield stream_error_event(e)
            raise

    async def collect_anthropic_response(*args, **kwargs):
        result = await o["collect_anthropic"](*args, **kwargs)
        state = current_state()
        if state is not None and state.length_exceeded and isinstance(result, dict):
            result["stop_reason"] = "max_tokens"
        return result

    async def stream_kiro_to_anthropic(*args, **kwargs):
        state = ensure_request_state()
        async for chunk in o["stream_kiro_to_anthropic"](*args, **kwargs):
            if chunk.startswith("event: error"):
                # Always followed by a raise; stream_with_first_token_retry_anthropic
                # emits the mapped event instead of this generic api_error one.
                continue
            if state.length_exceeded:
                chunk = _force_stop_reason(chunk, "max_tokens")
            yield chunk

    async def stream_kiro_to_openai_internal(*args, **kwargs):
        state = ensure_request_state()
        try:
            async for chunk in o["stream_openai_internal"](*args, **kwargs):
                yield _fix_openai_chunk(chunk, state.length_exceeded)
        except KiroStreamError as e:
            # Surface the upstream failure instead of pretending success
            yield format_openai_error_chunk(e.exception_type, e.exception_message)
            raise

    def save_content_truncation(*args, **kwargs):
        state = current_state()
        if state is not None and state.length_exceeded:
            # Kiro reported the output limit; this is a max_tokens stop, not a
            # silently cut stream, so no truncation notice on the next turn.
            return None
        return o["save_content_truncation"](*args, **kwargs)

    kiro_errors.enhance_kiro_error = enhance_kiro_error
    routes_anthropic.anthropic_to_kiro = anthropic_to_kiro
    routes_anthropic.stream_with_first_token_retry_anthropic = stream_with_first_token_retry_anthropic
    routes_anthropic.collect_anthropic_response = collect_anthropic_response
    streaming_anthropic.stream_kiro_to_anthropic = stream_kiro_to_anthropic
    streaming_openai.stream_kiro_to_openai_internal = stream_kiro_to_openai_internal
    truncation_state.save_content_truncation = save_content_truncation


def uninstall_client_compat(app: Any = None) -> None:
    """Restore patched globals and remove the middleware. Intended for unit tests."""
    if _originals:
        import kiro.kiro_errors as kiro_errors
        import kiro.routes_anthropic as routes_anthropic
        import kiro.streaming_anthropic as streaming_anthropic
        import kiro.streaming_openai as streaming_openai
        import kiro.truncation_state as truncation_state

        kiro_errors.enhance_kiro_error = _originals["enhance_kiro_error"]
        routes_anthropic.anthropic_to_kiro = _originals["anthropic_to_kiro"]
        routes_anthropic.stream_with_first_token_retry_anthropic = _originals["retry_anthropic"]
        routes_anthropic.collect_anthropic_response = _originals["collect_anthropic"]
        streaming_anthropic.stream_kiro_to_anthropic = _originals["stream_kiro_to_anthropic"]
        streaming_openai.stream_kiro_to_openai_internal = _originals["stream_openai_internal"]
        truncation_state.save_content_truncation = _originals["save_content_truncation"]
        _originals.clear()

    for installed in list(_installed_apps):
        if app is not None and installed is not app:
            continue
        installed.user_middleware = [
            m for m in installed.user_middleware if m.cls is not ClientCompatMiddleware
        ]
        installed.middleware_stack = None
        _installed_apps.remove(installed)
