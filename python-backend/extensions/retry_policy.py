"""Request-wide inference budgets, retry hints, and coordinated auth recovery.

All physical sends consume the same budget when called from the API middleware.
This module has no network side effects on import and never stores bearer tokens.
"""

import asyncio
import json
import math
import os
import time
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Mapping, Optional, TypeVar

from fastapi import HTTPException
from loguru import logger

T = TypeVar("T")
MAX_RETRY_HINT_SECONDS = 300.0
_REFRESH_TASKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _positive_env(name: str, default: float) -> float:
    """Read a finite positive numeric setting, falling back on invalid input."""
    try:
        value = float(os.getenv(name, str(default)))
        if math.isfinite(value) and value > 0:
            return value
    except ValueError:
        pass
    logger.warning(f"Invalid {name}; using {default}")
    return default


@dataclass
class RetryBudget:
    """Budget shared by transport, first-token recovery, and account failover.

    Attributes:
        max_attempts: Total permitted physical inference sends.
        deadline: Absolute monotonic deadline, including backoff and authentication.
        invocation_id: Correlation ID stable for the whole logical client request.
        attempts: Number of sends already reserved.
        refreshed_accounts: Auth managers refreshed by this logical request.
        output_started: Whether application content has been delivered downstream.
    """

    max_attempts: int
    deadline: float
    invocation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attempts: int = 0
    refreshed_accounts: set[int] = field(default_factory=set)
    output_started: bool = False
    last_http_error: Optional[tuple[int, dict[str, str], bytes]] = None
    _output_buffer: bytes = field(default=b"", repr=False)

    def observe_output(self, chunk: bytes) -> None:
        """Latch once semantic SSE output is sent; heartbeats/role headers are not output.

        Arbitrary network splits are buffered. Oversized or unrecognized data is
        treated conservatively as output rather than permitting a duplicate replay.
        """
        if self.output_started or not chunk:
            return
        self._output_buffer += chunk
        if len(self._output_buffer) > 65536:
            self.output_started = True
            self._output_buffer = b""
            return
        self._output_buffer = self._output_buffer.replace(b"\r\n", b"\n")
        while b"\n\n" in self._output_buffer:
            event, self._output_buffer = self._output_buffer.split(b"\n\n", 1)
            lines = [line[5:].lstrip() for line in event.split(b"\n") if line.startswith(b"data:")]
            if not lines:
                continue
            raw = b"\n".join(lines)
            if raw == b"[DONE]":
                self.output_started = True
                break
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                self.output_started = True
                break
            if not isinstance(data, dict):
                self.output_started = True
                break
            event_type = data.get("type")
            if event_type == "content_block_start":
                block = data.get("content_block", {})
                if isinstance(block, dict) and (block.get("type") in ("tool_use", "redacted_thinking") or block.get("text") or block.get("thinking")):
                    self.output_started = True
            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                if isinstance(delta, dict) and any(delta.get(k) for k in ("text", "thinking", "signature", "partial_json")):
                    self.output_started = True
            elif event_type == "message_stop":
                self.output_started = True
            for choice in data.get("choices", []) if isinstance(data.get("choices"), list) else []:
                delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                if isinstance(delta, dict) and any(delta.get(k) for k in ("content", "reasoning_content", "tool_calls", "reasoning_details")):
                    self.output_started = True

    @classmethod
    def from_environment(cls, attempts: Optional[int] = None) -> "RetryBudget":
        """Create a budget; middleware callers use the configured global limit."""
        limit = attempts if attempts is not None else int(_positive_env("KIRO_MAX_UPSTREAM_ATTEMPTS", 6))
        return cls(max(1, limit), time.monotonic() + _positive_env("KIRO_UPSTREAM_REQUEST_DEADLINE", 300))

    @property
    def remaining_seconds(self) -> float:
        """Remaining elapsed-time allowance, never negative."""
        return max(0.0, self.deadline - time.monotonic())

    def can_retry(self, delay: float = 0.0) -> bool:
        """Whether another send fits without replaying delivered content."""
        return (
            not self.output_started
            and self.attempts < self.max_attempts
            and self.remaining_seconds > max(0.0, delay)
        )

    def reserve_attempt(self) -> int:
        """Reserve one physical send or raise an actionable exhaustion error."""
        if not self.can_retry():
            reason = "response content has already been delivered" if self.output_started else "attempt or elapsed-time budget exhausted"
            raise HTTPException(status_code=504, detail=f"Kiro request cannot be replayed: {reason}.")
        self.attempts += 1
        return self.attempts

    async def wait(self, awaitable: Awaitable[T]) -> T:
        """Run an operation within the shared deadline; cancellation propagates."""
        return await asyncio.wait_for(awaitable, timeout=self.remaining_seconds)


def retry_after_seconds(
    headers: Mapping[str, str], body: bytes = b"", *, now: Optional[datetime] = None
) -> Optional[float]:
    """Read Kiro milliseconds or HTTP seconds/date without accepting NaN/infinity.

    Args:
        headers: Upstream response headers, case insensitive.
        body: Buffered JSON error body, optionally with retryAfterMilliseconds.
        now: UTC wall clock override for deterministic HTTP-date tests.

    Returns:
        A nonnegative delay capped at five minutes, or None for an invalid hint.
    """
    normalized = {str(k).lower(): str(v) for k, v in headers.items()}
    millis: Any = normalized.get("x-amzn-kiro-ratelimit-retry-after")
    if millis is None and body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                millis = parsed.get("retryAfterMilliseconds")
        except (ValueError, UnicodeDecodeError):
            pass
    if millis is not None and not isinstance(millis, bool):
        try:
            value = float(millis) / 1000
            if math.isfinite(value) and value >= 0:
                return min(value, MAX_RETRY_HINT_SECONDS)
        except (ValueError, TypeError):
            pass
    for key in ("retry-after", "x-amz-retry-after"):
        raw = normalized.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            try:
                date = parsedate_to_datetime(raw)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                value = (date - (now or datetime.now(timezone.utc))).total_seconds()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(value):
            return min(max(value, 0.0), MAX_RETRY_HINT_SECONDS)
    return None


def is_expired_auth(status: int, body: bytes) -> bool:
    """Refresh only explicit token expiry/invalid-token errors, not generic 403.

    A bare 401 is authentication failure and permits one recovery attempt. A 403
    requires a positive expiry indicator; quota, access and policy denials do not.
    """
    if status not in (401, 403):
        return False
    lowered = body.lower()
    denied = (b"accessdenied", b"insufficient", b"monthly_request", b"quota", b"suspended", b"revoked")
    if any(marker in lowered for marker in denied):
        return False
    return status == 401 or any(marker in lowered for marker in (
        b"expiredtoken", b"tokenexpired", b"token has expired", b"token is expired",
        b"invalidtoken", b"invalid_token", b"invalid bearer token", b"invalid access token",
    ))


async def refresh_if_current(auth: Any, failed_token: str) -> None:
    """Single-flight refresh, skipping a token another request already replaced.

    Args:
        auth: Authentication manager with get_access_token and force_refresh.
        failed_token: Token rejected by the server, used only for equality checks.
    """
    task = _REFRESH_TASKS.get(auth)
    if task is None or task.done():
        current = await auth.get_access_token()
        if current != failed_token:
            return
        # Recheck after awaiting: another request may have started a refresh.
        task = _REFRESH_TASKS.get(auth)
        if task is None or task.done():
            task = asyncio.create_task(auth.force_refresh())
            _REFRESH_TASKS[auth] = task
            reference = weakref.ref(auth)

            def discard(finished: asyncio.Task) -> None:
                """Release completed refresh tasks and consume orphaned errors."""
                manager = reference()
                if manager is not None and _REFRESH_TASKS.get(manager) is finished:
                    _REFRESH_TASKS.pop(manager, None)
                if not finished.cancelled():
                    finished.exception()

            task.add_done_callback(discard)
    # One cancelled inference request must not cancel auth recovery for its peers.
    await asyncio.shield(task)
