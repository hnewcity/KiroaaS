"""
Per-request state shared by the upstream-compat extensions.

Several ports from the kiro-gateway fork need to carry a fact from deep inside
the upstream call chain back out to a layer we can patch. Upstream's route
handlers are compiled at import time and build their error responses inline,
so the only hook points are module globals they call and the ASGI layer around
them. This module is the side channel between those hooks:

- upstream_retry records the last non-200 status Kiro returned
- client_compat records the Kiro error ``reason`` (via enhance_kiro_error)
- kiro_stream_decoder records ContentLengthExceeded / stream exceptions
- client_compat's ASGI middleware and stream wrappers read them to shape the
  response the client sees

The state object is created by the ASGI middleware (one per HTTP request) and
stored in a ContextVar. Child tasks (anyio task groups, the SSE ping wrapper)
copy the context, but they copy a reference to the same mutable object, so
writes made anywhere in the request are visible to the middleware.
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class RequestState:
    """Facts about one client request, written by hooks and read by the compat layer."""

    # Last non-200 HTTP status returned by Kiro (from request_with_retry)
    upstream_status: Optional[int] = None
    # Kiro error reason for that response (e.g. CONTENT_LENGTH_EXCEEDS_THRESHOLD)
    upstream_reason: Optional[str] = None
    # Kiro sent ContentLengthExceeded* mid-stream (output hit its limit)
    length_exceeded: bool = False
    # KiroStreamError raised while parsing the Kiro stream
    stream_error: Optional[BaseException] = None
    # Model the client asked for (for context-overflow wording)
    model: Optional[str] = None


_state: ContextVar[Optional[RequestState]] = ContextVar("kiroaas_request_state", default=None)


def current_state() -> Optional[RequestState]:
    """Returns the state of the current request, or None outside a request."""
    return _state.get()


def start_request_state() -> Tuple[RequestState, Token]:
    """Creates a fresh state for a request. Pair with reset_request_state()."""
    state = RequestState()
    return state, _state.set(state)


def reset_request_state(token: Token) -> None:
    """Restores the context to what it was before start_request_state()."""
    _state.reset(token)


def ensure_request_state() -> RequestState:
    """Returns the current state, creating one when no middleware set it (tests, direct calls)."""
    state = _state.get()
    if state is None:
        state = RequestState()
        _state.set(state)
    return state
