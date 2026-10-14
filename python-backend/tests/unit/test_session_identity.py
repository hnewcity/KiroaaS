"""Session contracts: explicit sessions, account isolation, and tool continuations."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from extensions.request_context import reset_request_state, start_request_state
from extensions.session_identity import SessionRegistry, read_identity_headers, request_identity, turn_anchor
from extensions.upstream_account import bind_account


FIRST = [{"role": "user", "content": "hello"}]
TOOLS = FIRST + [
    {"role": "assistant", "content": [{"type": "tool_use", "id": "call-1", "name": "read", "input": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "done"}]},
]


def test_tool_result_continues_turn_but_new_user_message_does_not():
    assert turn_anchor(FIRST) == turn_anchor(TOOLS)
    assert turn_anchor(FIRST) != turn_anchor(TOOLS + [{"role": "user", "content": "hello"}])
    assert turn_anchor(FIRST) == turn_anchor(FIRST + [{"role": "assistant", "tool_calls": [{"id": "call-1"}]}, {"role": "tool", "tool_call_id": "call-1", "content": "done"}])


def test_registry_is_scoped_and_rooted():
    registry = SessionRegistry()
    first = registry.resolve("account-A", "session", None, "turn-1")
    repeat = registry.resolve("account-A", "session", None, "turn-1")
    second = registry.resolve("account-A", "session", None, "turn-2")
    other = registry.resolve("account-B", "session", None, "turn-1")
    child = registry.resolve("account-A", "child", "session", "turn-1")
    assert first == repeat
    assert first.conversation_id == second.conversation_id
    assert first.continuation_id != second.continuation_id
    assert first.conversation_id != other.conversation_id
    assert child.root_conversation_id == first.conversation_id
    assert first.root_conversation_id == first.conversation_id


def test_registry_concurrency_and_capacity():
    registry = SessionRegistry(max_sessions=2, max_turns=2)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: registry.resolve("a", "s", None, "t"), range(32)))
    assert len(set(results)) == 1
    for i in range(8):
        registry.resolve("a", f"s{i}", None, "t")
    assert len(registry._sessions) == 2
    for i in range(8):
        registry.resolve("a", "last", None, f"t{i}")
    assert len(registry._sessions[("a", "last")].turns) == 2


def test_expired_continuation_not_reused():
    registry = SessionRegistry(ttl=10)
    with patch("extensions.session_identity.time.monotonic", return_value=10):
        first = registry.resolve("a", "s", None, "t")
    with patch("extensions.session_identity.time.monotonic", return_value=21):
        later = registry.resolve("a", "s", None, "t")
    assert first.conversation_id == later.conversation_id
    assert first.continuation_id != later.continuation_id


def test_request_context_reuses_retry_identity_and_isolates_account_failover():
    state, token = start_request_state()
    try:
        state.session_id = "explicit-session"
        bind_account(SimpleNamespace(id="account-A", model_cache=None))
        first = request_identity("random-1", None, FIRST)
        assert request_identity("random-2", None, FIRST) == first
        bind_account(SimpleNamespace(id="account-B", model_cache=None))
        other = request_identity("random-3", None, FIRST)
        assert first.conversation_id != other.conversation_id
        assert first.continuation_id != other.continuation_id
    finally:
        reset_request_state(token)


def test_identical_anonymous_requests_do_not_share_identity():
    results = []
    for _ in range(2):
        state, token = start_request_state()
        try:
            results.append(request_identity("same-fallback", None, FIRST))
        finally:
            reset_request_state(token)
    assert results[0].conversation_id != results[1].conversation_id
    assert results[0].continuation_id != results[1].continuation_id


@pytest.mark.parametrize("headers", [
    [(b"x-kiro-session-id", b"")],
    [(b"x-kiro-session-id", b"same"), (b"X-Kiro-Session-Id", b"same")],
    [(b"x-kiro-session-id", b"bad\r\nheader")],
    [(b"x-kiro-turn-id", b"turn-without-session")],
    [(b"x-kiro-root-session-id", b"root-without-session")],
    [(b"x-kiro-agent-mode", b"bad mode")],
    [(b"x-kiro-task-type", b"invented")],
    [(b"x-kiro-session-id", b"x" * 257)],
])
def test_invalid_identity_headers_rejected(headers):
    with pytest.raises(ValueError):
        read_identity_headers(headers)


def test_mode_and_task_are_independent_and_credentials_not_retained():
    value = read_identity_headers([(b"x-kiro-agent-mode", b"spec"), (b"authorization", b"Bearer fixture")])
    assert value["agent_mode"] == "spec"
    assert value["task_type"] == "spectask"
    assert "fixture" not in repr(value)
    overridden = read_identity_headers([(b"x-kiro-agent-mode", b"custom"), (b"x-kiro-task-type", b"vibe")])
    assert overridden["agent_mode"] == "custom" and overridden["task_type"] == "vibe"

@pytest.mark.asyncio
async def test_invalid_session_header_is_rejected_before_application():
    from extensions.client_compat import ClientCompatMiddleware

    calls, sent = [], []

    async def application(scope, receive, send):
        calls.append(scope)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/v1/messages", "headers": [(b"x-kiro-turn-id", b"orphan")]}
    await ClientCompatMiddleware(application)(scope, receive, send)
    assert not calls
    assert sent[0]["status"] == 400
    assert b"requires x-kiro-session-id" in sent[1]["body"]

def test_explicit_turn_identity_survives_registry_restart():
    first = SessionRegistry().resolve("a", "session", None, "client-turn", explicit_turn=True)
    restarted = SessionRegistry().resolve("a", "session", None, "client-turn", explicit_turn=True)
    assert first == restarted
    assert first.continuation_id != SessionRegistry().resolve("b", "session", None, "client-turn", explicit_turn=True).continuation_id


def test_child_root_is_inherited_and_cannot_silently_change():
    registry = SessionRegistry()
    first = registry.resolve("a", "child", "parent", "t1")
    later = registry.resolve("a", "child", None, "t2")
    assert first.root_conversation_id == later.root_conversation_id
    with pytest.raises(ValueError, match="root session cannot change"):
        registry.resolve("a", "child", "unrelated", "t3")

def test_same_gateway_key_has_same_namespace_across_api_auth_headers():
    anthropic = read_identity_headers([(b"x-api-key", b"fixture-key")])
    openai = read_identity_headers([(b"authorization", b"Bearer fixture-key")])
    assert anthropic["client_scope"] == openai["client_scope"]
