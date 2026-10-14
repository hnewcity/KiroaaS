"""Offline tests for logical request budgets and documented retry hint formats."""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from extensions.retry_policy import RetryBudget, is_expired_auth, refresh_if_current, retry_after_seconds


@pytest.mark.parametrize("headers,body,expected", [
    ({"x-amzn-kiro-ratelimit-retry-after": "1500"}, b"", 1.5),
    ({"X-Amzn-Kiro-Ratelimit-Retry-After": "0", "retry-after": "8"}, b"", 0),
    ({}, b'{"retryAfterMilliseconds":2500}', 2.5),
    ({"retry-after": "4.5"}, b"", 4.5),
    ({"x-amz-retry-after": "3"}, b"", 3),
    ({"retry-after": "9999"}, b"", 300),
    ({"retry-after": "-2"}, b"", 0),
    ({"retry-after": "NaN"}, b"", None),
    ({"retry-after": "inf"}, b"", None),
    ({"x-amzn-kiro-ratelimit-retry-after": "garbage", "retry-after": "3"}, b"", 3),
    ({}, b'{"retryAfterMilliseconds":true}', None),
    ({}, b"not json", None),
])
def test_retry_hints(headers, body, expected):
    assert retry_after_seconds(headers, body) == expected


def test_http_date_hint():
    now = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
    assert retry_after_seconds({"Retry-After": "Wed, 14 Oct 2026 00:00:12 GMT"}, now=now) == 12
    assert retry_after_seconds({"Retry-After": "Tue, 13 Oct 2026 00:00:00 GMT"}, now=now) == 0


@pytest.mark.parametrize("status,body,expected", [
    (401, b"", True),
    (403, b"", False),
    (403, b'{"__type":"ExpiredTokenException"}', True),
    (403, b'{"message":"Token has expired"}', True),
    (403, b'{"message":"AccessDeniedException"}', False),
    (403, b'{"reason":"MONTHLY_REQUEST_COUNT"}', False),
    (403, b'{"message":"Account suspended"}', False),
    (401, b'{"message":"Token revoked"}', False),
    (500, b"ExpiredTokenException", False),
])
def test_refresh_classifies_token_errors(status, body, expected):
    assert is_expired_auth(status, body) is expected


def test_budget_counts_every_send_and_latches_output():
    budget = RetryBudget(2, time.monotonic() + 10)
    assert budget.reserve_attempt() == 1
    assert budget.reserve_attempt() == 2
    with pytest.raises(HTTPException):
        budget.reserve_attempt()
    assert budget.attempts == 2
    output_budget = RetryBudget(4, time.monotonic() + 10)
    output_budget.output_started = True
    assert not output_budget.can_retry()


def test_delay_must_fit_deadline():
    budget = RetryBudget(2, time.monotonic() + 1)
    assert not budget.can_retry(2)
    assert budget.can_retry(0)


@pytest.mark.parametrize("variable,value", [
    ("KIRO_MAX_UPSTREAM_ATTEMPTS", "NaN"),
    ("KIRO_MAX_UPSTREAM_ATTEMPTS", "-1"),
    ("KIRO_UPSTREAM_REQUEST_DEADLINE", "inf"),
    ("KIRO_UPSTREAM_REQUEST_DEADLINE", "invalid"),
])
def test_invalid_config_is_finite(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    budget = RetryBudget.from_environment()
    assert budget.max_attempts >= 1
    assert 0 < budget.remaining_seconds <= 300


def sse(data):
    return ("data: " + json.dumps(data) + "\n\n").encode()


@pytest.mark.parametrize("data", [
    {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "test"}},
    {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "read"}},
    {"type": "content_block_start", "content_block": {"type": "redacted_thinking", "data": "opaque"}},
    {"choices": [{"delta": {"content": "hello"}}]},
    {"choices": [{"delta": {"reasoning_content": "test"}}]},
    {"choices": [{"delta": {"tool_calls": [{"id": "tool-1"}]}}]},
])
def test_output_guard_survives_every_byte_split(data):
    budget = RetryBudget(3, time.monotonic() + 10)
    for byte in sse(data):
        budget.observe_output(bytes([byte]))
    assert budget.output_started
    assert not budget.can_retry()


def test_role_headers_and_pings_do_not_prevent_first_token_recovery():
    budget = RetryBudget(3, time.monotonic() + 10)
    budget.observe_output(b": keepalive\n\n")
    budget.observe_output(sse({"type": "ping"}))
    budget.observe_output(sse({"type": "message_start", "message": {}}))
    budget.observe_output(sse({"choices": [{"delta": {"role": "assistant"}}]}))
    assert not budget.output_started


@pytest.mark.asyncio
async def test_concurrent_token_recovery_is_single_flight():
    auth = Mock()
    auth.get_access_token = AsyncMock(return_value="old")
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh():
        entered.set()
        await release.wait()
        auth.get_access_token.return_value = "new"
        return "new"

    auth.force_refresh = AsyncMock(side_effect=refresh)
    first = asyncio.create_task(refresh_if_current(auth, "old"))
    await entered.wait()
    second = asyncio.create_task(refresh_if_current(auth, "old"))
    release.set()
    await asyncio.gather(first, second)
    auth.force_refresh.assert_awaited_once()
    await refresh_if_current(auth, "old")
    auth.force_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_peer_refresh():
    auth = Mock(get_access_token=AsyncMock(return_value="old"))
    entered, release = asyncio.Event(), asyncio.Event()

    async def refresh():
        entered.set()
        await release.wait()
        return "new"

    auth.force_refresh = AsyncMock(side_effect=refresh)
    first = asyncio.create_task(refresh_if_current(auth, "old"))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(refresh_if_current(auth, "old"))
    release.set()
    await second
    auth.force_refresh.assert_awaited_once()
