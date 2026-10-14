"""Cloud mode must forward approved operations or fail, never silently go direct."""

import hashlib
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

import extensions.cloud_connector as cloud


@pytest.fixture(autouse=True)
def reset_cloud(monkeypatch):
    cloud.uninstall_cloud_connector()
    monkeypatch.setenv("KIROAAS_CLOUD_ENABLED", "true")
    yield
    cloud.uninstall_cloud_connector()


@pytest.mark.parametrize("host,allowed", [
    ("runtime.us-east-1.kiro.dev", True), ("management.eu-central-1.kiro.dev", True),
    ("q.us-east-1.amazonaws.com", True), ("oidc.eu-west-1.amazonaws.com", True),
    ("prod.us-east-1.auth.desktop.kiro.dev", True),
    ("runtime.us-east-1.kiro.dev.attacker.invalid", False),
    ("runtime.extra.us-east-1.kiro.dev", False), ("s3.us-east-1.amazonaws.com", False),
    ("management.kiro.dev", False), ("example.com", False),
])
def test_service_allowlist_is_not_a_suffix_wildcard(host, allowed):
    assert cloud._is_target_host(host) is allowed


@pytest.mark.parametrize("url,key", [(None, "key"), ("https://relay.invalid/forward", None), ("http://relay.invalid/forward", "key"), ("https://user:pass@relay.invalid/forward", "key")])
def test_invalid_enabled_cloud_configuration_never_installs_direct_fallback(monkeypatch, url, key):
    if url is None:
        monkeypatch.delenv("KIROAAS_CLOUD_FORWARD_URL", raising=False)
    else:
        monkeypatch.setenv("KIROAAS_CLOUD_FORWARD_URL", url)
    if key is None:
        monkeypatch.delenv("KIROAAS_CLOUD_API_KEY", raising=False)
    else:
        monkeypatch.setenv("KIROAAS_CLOUD_API_KEY", key)
    with pytest.raises(ValueError):
        cloud.install_cloud_connector()
    assert not cloud._installed


@pytest.mark.asyncio
async def test_management_rpc_is_forwarded_with_original_target_and_exact_hash(monkeypatch):
    monkeypatch.setattr(cloud, "_installed", True)
    inner = Mock(handle_async_request=AsyncMock(return_value=httpx.Response(200, json={"models": []})), aclose=AsyncMock())
    transport = cloud._CloudTransport(inner, "https://relay.invalid:8443/forward", "relay-key")
    payload = json.dumps({"origin": "KIRO_CLI", "nextToken": "page2"}).encode()
    original = "https://management.us-east-1.kiro.dev/"
    req = httpx.Request("POST", original, content=payload,
        headers={"Authorization": "Bearer upstream-token", "x-amz-target": "KiroControlPlaneBearerService.ListAvailableModels"},
        extensions={"kiro_upstream": True})
    await transport.handle_async_request(req)
    forwarded = inner.handle_async_request.call_args.args[0]
    assert str(forwarded.url) == "https://relay.invalid:8443/forward"
    assert forwarded.headers["host"] == "relay.invalid:8443"
    assert forwarded.headers["x-kiro-target-url"] == original
    assert forwarded.headers["x-kiro-authorization"] == "Bearer upstream-token"
    assert "authorization" not in forwarded.headers
    assert forwarded.headers["x-cloud-key"] == "relay-key"
    assert forwarded.headers["x-amz-content-sha256"] == hashlib.sha256(payload).hexdigest()
    assert forwarded.headers["x-amz-target"].endswith("ListAvailableModels")
    assert forwarded.content == payload


@pytest.mark.asyncio
async def test_unapproved_explicit_upstream_request_is_not_sent_direct(monkeypatch):
    monkeypatch.setattr(cloud, "_installed", True)
    inner = Mock(handle_async_request=AsyncMock(), aclose=AsyncMock())
    transport = cloud._CloudTransport(inner, "https://relay.invalid/forward", "key")
    request = httpx.Request("POST", "https://custom.invalid/", headers={"authorization": "Bearer token"}, extensions={"kiro_upstream": True})
    with pytest.raises(ValueError, match="cannot forward"):
        await transport.handle_async_request(request)
    inner.handle_async_request.assert_not_awaited()


def test_even_supported_host_requires_an_installed_cloud_transport():
    with pytest.raises(ValueError, match="not installed"):
        cloud.require_cloud_route("https://runtime.us-east-1.kiro.dev/")
