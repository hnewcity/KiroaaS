"""Offline production routing and SSE bridge tests (no service calls)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException

from extensions.protocol_runtime import prepare_operation
from extensions.request_context import start_request_state, reset_request_state
from extensions.upstream_account import bind_account
from extensions.upstream_retry import request_with_retry
from kiro.http_client import KiroHttpClient
from kiro.credential_identity import CredentialIdentity

BASE = "https://runtime.us-east-1.kiro.dev/generateAssistantResponse"


def auth():
    return SimpleNamespace(_region="us-east-1", region="us-east-1", auth_type="aws_sso_oidc",
        profile_arn="arn:fixture:profile", _profile_arn="arn:fixture:profile", fingerprint="fixture",
        q_host="https://q.us-east-1.amazonaws.com", get_access_token=AsyncMock(return_value="fixture-token"),
        force_refresh=AsyncMock())


def command():
    return {"agentMode": "vibe", "profileArn": "arn:fixture:profile", "systemPrompt": "system",
        "additionalModelRequestFields": {"max_tokens": 64},
        "conversationState": {"conversationId": "conversation", "rootConversationId": "root", "agentContinuationId": "turn",
            "agentTaskType": "vibe", "chatTriggerType": "MANUAL",
            "currentMessage": {"userInputMessage": {"content": "hello", "modelId": "fixture-model", "origin": "KIRO_CLI"}}}}


def client_with(*responses):
    owner = KiroHttpClient(auth())
    transport = Mock()
    transport.request = AsyncMock(side_effect=list(responses))
    transport.send = AsyncMock(side_effect=list(responses))
    transport.build_request = Mock(side_effect=lambda method, url, **kwargs: httpx.Request(method, url, **kwargs))
    owner._get_client = AsyncMock(return_value=transport)
    return owner, transport


def sse(event):
    return ("data: " + json.dumps(event) + "\n\n").encode()


def completed(text="ok", status="completed", reason=None):
    response = {"id": "response-1", "status": status, "model": "fixture-model", "output": [
        {"id": "message-1", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
    ], "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
                  "input_tokens_details": {"cached_tokens": 8}, "output_tokens_details": {"reasoning_tokens": 2}}}
    if reason is not None:
        response["incomplete_details"] = {"reason": reason}
    return {"type": "response." + status, "response": response}


@pytest.mark.parametrize("profile,protocol,path,target", [
    ("legacy", "generate", "/generateAssistantResponse", "AmazonCodeWhispererStreamingService.GenerateAssistantResponse"),
    ("cli", "generate", "/", "KiroRuntimeService.GenerateAssistantResponse"),
    ("cli", "responses", "/v1/responses", None),
])
def test_wire_profiles_are_coherent(monkeypatch, profile, protocol, path, target):
    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", profile)
    monkeypatch.setenv("KIRO_GENERATION_PROTOCOL", protocol)
    plan = prepare_operation(auth(), "fixture-token", "POST", BASE, command())
    assert httpx.URL(plan.url).path == path
    assert plan.headers.get("x-amz-target") == target
    assert plan.headers["User-Agent"].startswith("KiroaaS/")
    assert plan.headers["TokenType"] == "SSO_OIDC"
    assert plan.headers["x-amzn-codewhisperer-optout"] == "true"
    if protocol == "responses":
        assert plan.payload["max_output_tokens"] == 64
        assert plan.payload["instructions"] == "system"
        assert plan.headers["x-amzn-kiro-origin"] == "KIRO_CLI"
    elif profile == "cli":
        assert plan.payload["agentMode"] == "vibe"
        assert "x-amzn-kiro-agent-mode" not in plan.headers
    else:
        assert "agentMode" not in plan.payload
        assert plan.headers["x-amzn-kiro-agent-mode"] == "vibe"


@pytest.mark.asyncio
async def test_control_pagination_is_complete_and_does_not_spend_inference_budget(monkeypatch):
    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", "cli")
    monkeypatch.setenv("KIRO_MAX_UPSTREAM_ATTEMPTS", "1")
    owner, transport = client_with(httpx.Response(200, json={"models": [{"modelId": "first"}], "nextToken": "page2"}),
                                   httpx.Response(200, json={"models": [{"modelId": "second"}]}))
    state, token = start_request_state()
    try:
        result = await request_with_retry(owner, "GET", "https://q.us-east-1.amazonaws.com/ListAvailableModels", params={"origin": "AI_EDITOR"})
        assert [item["modelId"] for item in result.json()["models"]] == ["first", "second"]
        assert state.retry_budget.attempts == 0
        calls = transport.request.call_args_list
        assert all(call.args[:2] == ("POST", "https://management.us-east-1.kiro.dev/") for call in calls)
        bodies = [json.loads(call.kwargs["content"]) for call in calls]
        assert bodies[0]["origin"] == "KIRO_CLI"
        assert bodies[1]["nextToken"] == "page2"
        ids = [call.kwargs["headers"]["amz-sdk-invocation-id"] for call in calls]
        assert ids[0] != ids[1]
    finally:
        reset_request_state(token)


@pytest.mark.asyncio
async def test_control_fallback_is_explicit_and_not_used_for_permission_errors(monkeypatch):
    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", "cli")
    monkeypatch.setenv("KIRO_CONTROL_PLANE_FALLBACK", "true")
    owner, transport = client_with(httpx.Response(400, json={"__type": "UnknownOperationException"}),
                                  httpx.Response(200, json={"models": []}))
    result = await request_with_retry(owner, "GET", "https://q.us-east-1.amazonaws.com/ListAvailableModels", params={})
    assert result.status_code == 200
    assert transport.request.call_args_list[0].args[0] == "POST"
    assert transport.request.call_args_list[1].args[:2] == ("GET", "https://q.us-east-1.amazonaws.com/ListAvailableModels")
    assert "x-amz-target" not in transport.request.call_args_list[1].kwargs["headers"]
    owner, transport = client_with(httpx.Response(403, json={"__type": "AccessDeniedException"}))
    result = await request_with_retry(owner, "GET", "https://q.us-east-1.amazonaws.com/ListAvailableModels", params={})
    assert result.status_code == 403
    assert transport.request.call_count == 1


@pytest.mark.asyncio
async def test_repeated_model_cursor_is_not_a_partial_success(monkeypatch):
    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", "cli")
    page = {"models": [], "nextToken": "same"}
    owner, _ = client_with(httpx.Response(200, json=page), httpx.Response(200, json=page))
    with pytest.raises(HTTPException, match="cursor") as error:
        await request_with_retry(owner, "GET", "https://q.us-east-1.amazonaws.com/ListAvailableModels", params={})
    assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_real_retry_entry_returns_common_decodable_responses_stream(monkeypatch):
    import kiro.streaming_core as core
    from extensions.kiro_stream_decoder import install_kiro_stream_decoder, uninstall_kiro_stream_decoder

    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", "cli")
    monkeypatch.setenv("KIRO_GENERATION_PROTOCOL", "responses")
    raw = httpx.Response(200, content=sse(completed()), headers={"content-type": "text/event-stream"})
    owner, transport = client_with(raw)
    uninstall_kiro_stream_decoder()
    install_kiro_stream_decoder()
    try:
        response = await request_with_retry(owner, "POST", BASE, command(), stream=True)
        result = await core.collect_stream_to_result(response)
        assert result.content == "ok" and result.completed
        assert result.usage["_responses_usage"]["input_tokens"] == 20
        assert result.resolved_model_id == "fixture-model"
        sent = transport.build_request.call_args
        assert sent.args[:2] == ("POST", "https://runtime.us-east-1.kiro.dev/v1/responses")
        assert json.loads(sent.kwargs["content"])["max_output_tokens"] == 64
        assert response.is_closed and raw.is_closed
    finally:
        uninstall_kiro_stream_decoder()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason,expect_error", [("incomplete", "max_output_tokens", False), ("incomplete", "unknown_reason", True)])
async def test_incomplete_is_not_disguised_as_end_turn(monkeypatch, status, reason, expect_error):
    import kiro.streaming_core as core
    from extensions.kiro_stream_decoder import install_kiro_stream_decoder, uninstall_kiro_stream_decoder, KiroStreamError
    from extensions.responses_transport import adapt_responses_stream

    state, token = start_request_state()
    uninstall_kiro_stream_decoder()
    install_kiro_stream_decoder()
    try:
        response = adapt_responses_stream(httpx.Response(200, content=sse(completed(status=status, reason=reason))))
        if expect_error:
            with pytest.raises(KiroStreamError):
                _ = [event async for event in core.parse_kiro_stream(response)]
        else:
            result = await core.collect_stream_to_result(response)
            assert state.length_exceeded and not result.completed
            assert result.usage["_responses_usage"]["output_tokens"] == 5
    finally:
        reset_request_state(token)
        uninstall_kiro_stream_decoder()


@pytest.mark.asyncio
async def test_source_change_after_conversion_cannot_send_the_old_payload():
    identity = CredentialIdentity()

    class Auth:
        profile_arn = _profile_arn = "arn:fixture:profile"
        _region = "us-east-1"
        auth_type = "kiro_desktop"

        @property
        def credential_generation(self):
            return identity.binding_key

        async def get_access_token(self):
            identity.observe("replacement", {"accessToken": "new-account-token"})
            return "new-account-token"

    manager = Auth()
    owner = KiroHttpClient(manager)
    transport = Mock(request=AsyncMock())
    owner._get_client = AsyncMock(return_value=transport)
    state, token = start_request_state()
    try:
        bind_account(SimpleNamespace(id="same-file", auth_manager=manager, model_cache=None))
        with pytest.raises(HTTPException) as error:
            await request_with_retry(owner, "POST", BASE, command())
        assert error.value.status_code == 409
        assert state.retry_budget.attempts == 0
        transport.request.assert_not_awaited()
    finally:
        reset_request_state(token)

@pytest.mark.parametrize("operation,legacy_url,target", [
    ("GetUsageLimits", "https://q.us-east-1.amazonaws.com/", "KiroControlPlaneBearerService.GetUsageLimits"),
    ("ListAvailableProfiles", "https://q.us-east-1.amazonaws.com/", "KiroControlPlaneBearerService.ListAvailableProfiles"),
    ("mcp", "https://q.us-east-1.amazonaws.com/mcp", "KiroRuntimeService.InvokeMCP"),
])
def test_cli_control_operations_do_not_inherit_generate_target(monkeypatch, operation, legacy_url, target):
    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", "cli")
    body = {"jsonrpc": "2.0", "id": "tool", "method": "tools/call", "params": {"name": "web_search", "arguments": {"query": "fixture"}}} if operation == "mcp" else {"isEmailRequired": True}
    plan = prepare_operation(auth(), "fixture-token", "POST", legacy_url, body, operation=operation)
    assert plan.method == "POST" and httpx.URL(plan.url).path == "/"
    assert plan.headers["x-amz-target"] == target
    assert "x-amzn-kiro-agent-mode" not in plan.headers
    assert httpx.URL(plan.url).host.startswith("runtime." if operation == "mcp" else "management.")
    if operation == "mcp":
        assert plan.payload["method"] == "tools/call"
        assert plan.payload["params"]["arguments"] == {"query": "fixture"}
        assert plan.payload["profileArn"] == "arn:fixture:profile"
    elif operation == "GetUsageLimits":
        assert plan.payload["origin"] == "KIRO_CLI"


@pytest.mark.asyncio
async def test_explicit_responses_output_limit_does_not_require_generate_additional_schema(monkeypatch):
    from kiro.cache import ModelInfoCache
    from kiro.models_anthropic import AnthropicMessagesRequest
    from extensions.kiro_payload_builder import install_kiro_payload_builder, uninstall_kiro_payload_builder
    import kiro.routes_anthropic as routes

    monkeypatch.setenv("KIRO_GENERATION_PROTOCOL", "responses")
    uninstall_kiro_payload_builder()
    install_kiro_payload_builder()
    state, token = start_request_state()
    try:
        state.model_cache = ModelInfoCache()
        state.model_cache._cache = {"fixture-model": {"modelId": "fixture-model", "additionalModelRequestFieldsSchema": {}}}
        req = AnthropicMessagesRequest(model="fixture-model", max_tokens=64, messages=[{"role": "user", "content": "go"}])
        payload = routes.anthropic_to_kiro(req, "conversation", "")
        assert payload["additionalModelRequestFields"] == {"max_tokens": 64}
        prepared = prepare_operation(auth(), "fixture-token", "POST", BASE, payload)
        assert prepared.payload["max_output_tokens"] == 64
    finally:
        reset_request_state(token)
        uninstall_kiro_payload_builder()
