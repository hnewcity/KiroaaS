"""Installed route matrix: both APIs/output modes, wire profiles and Cloud relay."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from httpx._client import AsyncClient as RealAsyncClient
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from extensions.client_compat import install_client_compat, uninstall_client_compat
from extensions.kiro_payload_builder import install_kiro_payload_builder, uninstall_kiro_payload_builder
from extensions.kiro_stream_decoder import install_kiro_stream_decoder, uninstall_kiro_stream_decoder
from extensions.upstream_retry import install_upstream_retry, uninstall_upstream_retry
from extensions.upstream_account import install_upstream_account_context, uninstall_upstream_account_context
from extensions.cloud_connector import install_cloud_connector, uninstall_cloud_connector
from kiro.account_manager import AccountManager
from kiro.cache import ModelInfoCache
from kiro.http_client import KiroHttpClient
from tests.unit.test_kiro_stream_decoder_extension import event_frame
from tests.unit.test_protocol_routing import sse, completed

MODEL = "fixture-model"


class FakeRelayAndKiro(httpx.AsyncBaseTransport):
    def __init__(self, protocol, cloud):
        self.protocol, self.cloud, self.calls = protocol, cloud, []
        self.error_response = None

    async def handle_async_request(self, request):
        self.calls.append(request)
        if self.cloud:
            assert request.url.host == "relay.invalid"
            assert request.headers["x-cloud-key"] == "test-relay-key"
            assert "authorization" not in request.headers
            assert request.headers["x-kiro-authorization"] == "Bearer test-upstream-token"
        if self.error_response is not None:
            return httpx.Response(400, json=self.error_response)
        raw = sse(completed()) if self.protocol == "responses" else (
            event_frame("assistantResponseEvent", {"content": "ok"})
            + event_frame("contextUsageEvent", {"contextUsagePercentage": 1})
        )

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                for i in range(0, len(raw), 5):
                    yield raw[i:i + 5]

        return httpx.Response(200, stream=Body(), headers={"content-type": "text/event-stream" if self.protocol == "responses" else "application/vnd.amazon.eventstream"})


@pytest.fixture
def configured_client(monkeypatch, profile, protocol, cloud):
    import kiro.routes_anthropic as anthropic
    import kiro.routes_openai as openai
    monkeypatch.setenv("KIRO_PROTOCOL_PROFILE", profile)
    monkeypatch.setenv("KIRO_GENERATION_PROTOCOL", protocol)
    monkeypatch.setenv("KIRO_NATIVE_SYSTEM_PROMPT", "true")
    monkeypatch.setenv("KIROAAS_CLOUD_ENABLED", "true" if cloud else "false")
    monkeypatch.setenv("KIROAAS_CLOUD_FORWARD_URL", "https://relay.invalid/forward")
    monkeypatch.setenv("KIROAAS_CLOUD_API_KEY", "test-relay-key")
    monkeypatch.setenv("KIROAAS_APP_VERSION", "fixture-1")
    monkeypatch.setattr(anthropic, "PROXY_API_KEY", "gateway-key")
    monkeypatch.setattr(openai, "PROXY_API_KEY", "gateway-key")
    monkeypatch.setattr(anthropic, "WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(openai, "WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr("extensions.client_compat.SSE_PING_INTERVAL", 0)
    monkeypatch.setattr("kiro.config.TRUNCATION_RECOVERY", False)
    for uninstall in (uninstall_client_compat, uninstall_upstream_retry, uninstall_upstream_account_context,
                      uninstall_kiro_payload_builder, uninstall_kiro_stream_decoder, uninstall_cloud_connector):
        uninstall()
    # Only the fake transport can be reached. This restores the actual class for
    # constructor-wrapping coverage, not for any network-capable client.
    monkeypatch.setattr(httpx, "AsyncClient", RealAsyncClient)
    install_cloud_connector()
    fake = FakeRelayAndKiro(protocol, cloud)
    upstream = RealAsyncClient(transport=fake, trust_env=False)
    monkeypatch.setattr(KiroHttpClient, "_get_client", AsyncMock(return_value=upstream))

    auth = SimpleNamespace(_region="us-east-1", profile_arn="arn:fixture", _profile_arn="arn:fixture",
        api_host="https://runtime.us-east-1.kiro.dev", q_host="https://q.us-east-1.amazonaws.com",
        fingerprint="fixture", auth_type="aws_sso_oidc", credential_generation="generation-1",
        get_access_token=AsyncMock(return_value="test-upstream-token"), force_refresh=AsyncMock())
    cache = ModelInfoCache()
    cache._cache = {MODEL: {"modelId": MODEL, "tokenLimits": {"maxInputTokens": 200000, "maxOutputTokens": 128000},
        "additionalModelRequestFieldsSchema": {"type": "object", "properties": {
            "max_tokens": {"type": "integer", "minimum": 1, "maximum": 128000},
            "output_config": {"type": "object", "properties": {"effort": {"enum": ["low", "high"], "default": "low"}}},
        }}}}
    account = SimpleNamespace(id="fixture-account", auth_manager=auth, model_cache=cache, model_resolver=Mock())
    monkeypatch.setattr(AccountManager, "get_first_account", lambda self: account)
    install_upstream_account_context()
    install_kiro_stream_decoder()
    install_kiro_payload_builder()
    install_upstream_retry()
    app = FastAPI()
    app.include_router(anthropic.router)
    app.include_router(openai.router)
    app.state.account_manager = object.__new__(AccountManager)
    app.state.account_system = False
    app.state.http_client = upstream
    install_client_compat(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, fake
    uninstall_client_compat(app)
    uninstall_upstream_retry()
    uninstall_upstream_account_context()
    uninstall_kiro_payload_builder()
    uninstall_kiro_stream_decoder()
    uninstall_cloud_connector()


@pytest.mark.parametrize("profile,protocol", [("legacy", "generate"), ("cli", "generate"), ("cli", "responses")])
@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("api", ["anthropic", "openai"])
@pytest.mark.parametrize("stream", [False, True])
def test_full_generation_route_matrix(configured_client, profile, protocol, cloud, api, stream):
    client, fake = configured_client
    if api == "anthropic":
        payload = {"model": MODEL, "max_tokens": 64, "system": "exact system", "stream": stream,
                   "messages": [{"role": "user", "content": "hello"}]}
        result = client.post("/v1/messages", json=payload, headers={"x-api-key": "gateway-key"})
    else:
        payload = {"model": MODEL, "max_tokens": 64, "stream": stream,
                   "messages": [{"role": "system", "content": "exact system"}, {"role": "user", "content": "hello"}]}
        result = client.post("/v1/chat/completions", json=payload, headers={"authorization": "Bearer gateway-key"})
    assert result.status_code == 200, result.text
    assert len(fake.calls) == 1
    request = fake.calls[0]
    address = request.headers["x-kiro-target-url"] if cloud else str(request.url)
    wire = json.loads(request.content)
    assert request.headers["user-agent"] == "KiroaaS/fixture-1"
    assert request.headers["TokenType"] == "SSO_OIDC"
    if protocol == "responses":
        assert address.endswith("/v1/responses")
        assert "x-amz-target" not in request.headers
        assert wire["instructions"] == "exact system"
        assert wire["max_output_tokens"] == 64
        assert wire["input"] == [{"role": "user", "content": "hello"}]
    else:
        assert address.endswith("/" if profile == "cli" else "/generateAssistantResponse")
        assert request.headers["x-amz-target"] == ("KiroRuntimeService.GenerateAssistantResponse" if profile == "cli" else "AmazonCodeWhispererStreamingService.GenerateAssistantResponse")
        assert wire["systemPrompt"] == "exact system"
        assert "history" not in wire["conversationState"]
        assert wire["conversationState"]["currentMessage"]["userInputMessage"]["origin"] == ("KIRO_CLI" if profile == "cli" else "AI_EDITOR")
        assert ("agentMode" in wire) is (profile == "cli")
    if stream:
        assert '"text": "ok"' in result.text or '"content": "ok"' in result.text
        assert '"finish_reason": "length"' not in result.text
        assert '"stop_reason": "max_tokens"' not in result.text
    else:
        value = result.json()
        text = value["content"][0]["text"] if api == "anthropic" else value["choices"][0]["message"]["content"]
        assert text == "ok"
        if protocol == "responses":
            if api == "anthropic":
                assert value["usage"]["input_tokens"] == 12
                assert value["usage"]["cache_read_input_tokens"] == 8
                assert value["usage"]["output_tokens"] == 5
            else:
                assert value["usage"]["prompt_tokens"] == 20
                assert value["usage"]["total_tokens"] == 25
                assert value["usage"]["completion_tokens_details"]["reasoning_tokens"] == 2


@pytest.mark.parametrize("profile,protocol", [("cli", "responses")])
@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("api", ["anthropic", "openai"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("account_system", [False, True])
def test_responses_http_error_survives_public_routes(configured_client, profile, protocol, cloud, api, stream, account_system):
    """A pre-stream Responses rejection must retain its real message and status."""
    client, fake = configured_client
    client.app.state.account_system = account_system
    if account_system:
        manager = client.app.state.account_manager
        account = manager.get_first_account()
        manager._accounts = {account.id: account}
        manager.get_next_account = AsyncMock(return_value=account)
        manager.report_failure = AsyncMock()
    message = "systemPrompt field is not enabled for this user."
    fake.error_response = {"error": {"message": message, "type": "invalid_request",
                                     "param": "instructions", "code": "unsupported_parameter"}}
    body = {"model": MODEL, "max_tokens": 64, "stream": stream,
            "messages": [{"role": "user", "content": "hello"}]}
    path = "/v1/messages" if api == "anthropic" else "/v1/chat/completions"
    headers = {"x-api-key": "gateway-key"} if api == "anthropic" else {"authorization": "Bearer gateway-key"}
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 400
    assert len(fake.calls) == 1
    error = response.json()["error"]
    assert message in error["message"]
    assert "unsupported_parameter" in error["message"]
    assert "parameter: instructions" in error["message"]
    assert "Unknown error" not in error["message"]
