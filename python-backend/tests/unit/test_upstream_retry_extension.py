"""
Tests for the upstream retry extension (port of kiro-gateway fork endpoints.py /
http_client.py hardening): endpoint candidates, 429 rotation, capped backoff,
headers per attempt, additionalModelRequestFields fallback.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

import extensions.upstream_retry as ur
from extensions.request_context import reset_request_state, start_request_state
from extensions.upstream_retry import (
    AMAZONQ_TARGET,
    CODEWHISPERER_TARGET,
    EndpointThrottleRegistry,
    agent_mode_for_payload,
    backoff_delay,
    build_endpoint,
    build_headers,
    endpoint_candidates,
    install_upstream_retry,
    region_from_url,
    throttle_delay,
    uninstall_upstream_retry,
)
from kiro.http_client import KiroHttpClient

RUNTIME_URL = "https://runtime.us-east-1.kiro.dev/generateAssistantResponse"
Q_URL = "https://q.us-east-1.amazonaws.com/generateAssistantResponse"


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    monkeypatch.delenv("KIROAAS_CLOUD_ENABLED", raising=False)
    uninstall_upstream_retry()
    install_upstream_retry()
    yield
    uninstall_upstream_retry()


def _auth(profile_arn="arn:aws:codewhisperer:us-east-1:1:profile/x"):
    auth = Mock()
    auth.fingerprint = "fp"
    auth.get_access_token = AsyncMock(return_value="tok")
    auth.force_refresh = AsyncMock()
    auth._profile_arn = profile_arn
    auth.profile_arn = profile_arn
    return auth


def _mock_client(*responses):
    mock_client = AsyncMock()
    mock_client.is_closed = False
    mock_client.request = AsyncMock(side_effect=list(responses))
    return mock_client


class TestBuildEndpoint:
    def test_runtime_keeps_legacy_target(self):
        ep = build_endpoint("runtime", "US-EAST-1")
        assert ep.url == RUNTIME_URL
        assert ep.amz_target == CODEWHISPERER_TARGET

    def test_ide_has_no_target(self):
        ep = build_endpoint("ide", "eu-central-1")
        assert ep.base_url == "https://q.eu-central-1.amazonaws.com"
        assert ep.amz_target is None

    def test_codewhisperer_host_only_in_us_east_1(self):
        assert build_endpoint("codewhisperer", "us-east-1").base_url == "https://codewhisperer.us-east-1.amazonaws.com"
        assert build_endpoint("codewhisperer", "eu-central-1").base_url == "https://q.eu-central-1.amazonaws.com"

    def test_amazonq_target(self):
        assert build_endpoint("amazonq", "us-east-1").amz_target == AMAZONQ_TARGET

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            build_endpoint("nope", "us-east-1")


class TestCandidates:
    def test_region_from_url(self):
        assert region_from_url("https://runtime.eu-central-1.kiro.dev/generateAssistantResponse") == "eu-central-1"
        assert region_from_url(Q_URL) == "us-east-1"
        assert region_from_url("https://api.example.com/test") is None

    def test_default_is_requested_url_only(self, monkeypatch):
        monkeypatch.setattr(ur, "KIRO_ENDPOINTS", ["runtime"])
        eps = endpoint_candidates(RUNTIME_URL)
        assert [e.name for e in eps] == ["requested"]
        assert eps[0].url == RUNTIME_URL

    def test_configured_order_and_unknown_filtered(self, monkeypatch):
        monkeypatch.setattr(ur, "KIRO_ENDPOINTS", ["runtime", "bogus", "ide", "amazonq"])
        eps = endpoint_candidates(RUNTIME_URL)
        # runtime duplicates the requested URL; ide and amazonq share a host but
        # differ in x-amz-target, so both stay
        assert [e.name for e in eps] == ["requested", "ide", "amazonq"]

    def test_requested_q_host_is_kept_first(self, monkeypatch):
        # chat_host_fallback points profile-less accounts at q.amazonaws.com
        monkeypatch.setattr(ur, "KIRO_ENDPOINTS", ["runtime", "ide"])
        eps = endpoint_candidates(Q_URL, has_profile_arn=False)
        assert eps[0].url == Q_URL
        assert "runtime" not in [e.name for e in eps]

    def test_runtime_skipped_without_profile_arn(self, monkeypatch):
        monkeypatch.setattr(ur, "KIRO_ENDPOINTS", ["ide", "runtime"])
        names = [e.name for e in endpoint_candidates(Q_URL, has_profile_arn=False)]
        assert names == ["requested", "ide"]

    def test_non_kiro_url_passthrough(self):
        eps = endpoint_candidates("https://api.example.com/test")
        assert len(eps) == 1 and eps[0].name == "requested"

    def test_cloud_skips_untunneled_hosts(self, monkeypatch):
        monkeypatch.setenv("KIROAAS_CLOUD_ENABLED", "true")
        monkeypatch.setattr(ur, "KIRO_ENDPOINTS", ["codewhisperer", "ide"])
        names = [e.name for e in endpoint_candidates(RUNTIME_URL)]
        assert names == ["requested", "ide"]


class TestRegistry:
    def test_throttled_moves_to_back(self):
        reg = EndpointThrottleRegistry()
        eps = [build_endpoint("runtime", "us-east-1"), build_endpoint("ide", "us-east-1")]
        reg.throttle(1, "runtime", 30)
        assert [e.name for e in reg.order(1, eps)] == ["ide", "runtime"]
        # other accounts unaffected
        assert [e.name for e in reg.order(2, eps)] == ["runtime", "ide"]

    def test_expiry(self):
        reg = EndpointThrottleRegistry()
        reg.throttle(1, "runtime", -1)
        assert not reg.is_throttled(1, "runtime")


class TestDelays:
    def test_backoff_capped_with_jitter(self):
        for attempt in range(10):
            d = backoff_delay(attempt)
            assert 0 <= d <= 5 * 1.25

    def test_throttle_honours_retry_after(self):
        assert throttle_delay(0, "3") == 3.0
        assert throttle_delay(0, "999") == 8.0

    def test_throttle_bad_retry_after_falls_back(self):
        d = throttle_delay(0, "soon")
        assert 2.0 <= d <= 3.5


class TestHeaders:
    def test_requested_endpoint_matches_upstream_headers(self):
        from kiro.utils import get_kiro_headers

        auth = _auth()
        ep = endpoint_candidates(RUNTIME_URL)[0]
        h = build_headers(auth, "t", ep, 1, "vibe")
        upstream = get_kiro_headers(auth, "t")
        for key in ("x-amz-target", "amz-sdk-request", "x-amzn-kiro-agent-mode", "User-Agent"):
            assert h[key] == upstream[key]

    def test_target_omitted_and_attempt(self):
        h = build_headers(_auth(), "t", build_endpoint("ide", "us-east-1"), 3, "spectask")
        assert "x-amz-target" not in h
        assert h["amz-sdk-request"] == "attempt=3; max=3"
        assert h["x-amzn-kiro-agent-mode"] == "spectask"

    def test_agent_mode_from_payload(self):
        assert agent_mode_for_payload({"conversationState": {"agentTaskType": "spectask"}}) == "spectask"
        assert agent_mode_for_payload({"conversationState": {}}) == "vibe"
        assert agent_mode_for_payload(None) == "vibe"


class TestRotation:
    @pytest.mark.asyncio
    async def test_429_switches_endpoint_without_sleep(self, monkeypatch):
        monkeypatch.setattr(ur, "KIRO_ENDPOINTS", ["runtime", "ide"])
        client = KiroHttpClient(_auth())
        r429 = Mock(status_code=429, headers={})
        r200 = Mock(status_code=200)
        mock_client = _mock_client(r429, r200)

        with patch.object(client, "_get_client", return_value=mock_client):
            with patch.object(ur.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                resp = await client.request_with_retry(
                    "POST", RUNTIME_URL, {"conversationState": {"agentTaskType": "spectask"}},
                )

        assert resp is r200
        sleep.assert_not_called()
        urls = [c.args[1] for c in mock_client.request.call_args_list]
        assert urls == [RUNTIME_URL, Q_URL]
        second_headers = mock_client.request.call_args_list[1].kwargs["headers"]
        assert "x-amz-target" not in second_headers
        assert second_headers["amz-sdk-request"] == "attempt=2; max=3"
        assert second_headers["x-amzn-kiro-agent-mode"] == "spectask"

    @pytest.mark.asyncio
    async def test_408_is_retried(self):
        client = KiroHttpClient(_auth())
        mock_client = _mock_client(Mock(status_code=408), Mock(status_code=200))
        with patch.object(client, "_get_client", return_value=mock_client):
            with patch.object(ur.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                resp = await client.request_with_retry("POST", "https://api.example.com/x", {})
        assert resp.status_code == 200
        sleep.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_sleep_after_last_attempt(self):
        client = KiroHttpClient(_auth())
        r503 = Mock(status_code=503)
        mock_client = _mock_client(r503, r503, r503)
        with patch.object(client, "_get_client", return_value=mock_client):
            with patch.object(ur.asyncio, "sleep", new_callable=AsyncMock) as sleep:
                resp = await client.request_with_retry("POST", "https://api.example.com/x", {})
        assert resp is r503
        assert sleep.call_count == mock_client.request.call_count - 1

    @pytest.mark.asyncio
    async def test_records_upstream_status_for_compat_layer(self):
        state, token = start_request_state()
        try:
            client = KiroHttpClient(_auth())
            r429 = Mock(status_code=429, headers={})
            mock_client = _mock_client(r429, r429, r429)
            with patch.object(client, "_get_client", return_value=mock_client):
                with patch.object(ur.asyncio, "sleep", new_callable=AsyncMock):
                    await client.request_with_retry("POST", RUNTIME_URL, {})
            assert state.upstream_status == 429
        finally:
            reset_request_state(token)

    @pytest.mark.asyncio
    async def test_new_status_clears_reason_from_previous_attempt(self):
        # Account failover: account A's MONTHLY_REQUEST_COUNT reason must not be
        # paired with account B's unrelated (non-JSON) 500.
        state, token = start_request_state()
        try:
            state.upstream_status, state.upstream_reason = 402, "MONTHLY_REQUEST_COUNT"
            client = KiroHttpClient(_auth())
            r500 = Mock(status_code=500)
            mock_client = _mock_client(r500, r500, r500)
            with patch.object(client, "_get_client", return_value=mock_client):
                with patch.object(ur.asyncio, "sleep", new_callable=AsyncMock):
                    await client.request_with_retry("POST", RUNTIME_URL, {})
            assert state.upstream_status == 500
            assert state.upstream_reason is None
        finally:
            reset_request_state(token)


class TestAdditionalFieldsFallback:
    @pytest.mark.asyncio
    async def test_400_on_additional_fields_strips_and_retries(self):
        client = KiroHttpClient(_auth())
        r400 = Mock(status_code=400)
        r400.aread = AsyncMock(return_value=b'{"message":"additionalModelRequestFields is not supported for this model"}')
        r400.aclose = AsyncMock()
        r200 = Mock(status_code=200)
        mock_client = _mock_client(r400, r200)
        payload = {
            "conversationState": {"currentMessage": {"userInputMessage": {"modelId": "claude-x"}}},
            "additionalModelRequestFields": {"output_config": {"effort": "low"}},
        }
        with patch.object(client, "_get_client", return_value=mock_client):
            resp = await client.request_with_retry("POST", "https://api.example.com/x", payload)
        assert resp is r200
        sent = [json.loads(c.kwargs["content"]) for c in mock_client.request.call_args_list]
        assert "additionalModelRequestFields" in sent[0]
        assert "additionalModelRequestFields" not in sent[1]
        # learned: next request for the same model is stripped up front
        assert "additionalModelRequestFields" not in ur.strip_rejected_additional_fields(payload)
        assert "additionalModelRequestFields" in payload  # caller's dict untouched

    @pytest.mark.asyncio
    async def test_rejected_value_is_not_remembered(self):
        client = KiroHttpClient(_auth())
        r400 = Mock(status_code=400)
        r400.aread = AsyncMock(return_value=b'{"message":"Invalid value for additionalModelRequestFields.output_config.effort"}')
        r400.aclose = AsyncMock()
        mock_client = _mock_client(r400, Mock(status_code=200))
        payload = {
            "conversationState": {"currentMessage": {"userInputMessage": {"modelId": "claude-opus-5.5"}}},
            "additionalModelRequestFields": {"output_config": {"effort": "max"}},
        }
        with patch.object(client, "_get_client", return_value=mock_client):
            resp = await client.request_with_retry("POST", "https://api.example.com/x", payload)
        assert resp.status_code == 200
        assert "claude-opus-5.5" not in ur._ADDITIONAL_FIELDS_REJECTED

    @staticmethod
    def _additional_fields_400():
        r400 = Mock(status_code=400)
        r400.aread = AsyncMock(return_value=b'{"message":"additionalModelRequestFields is not supported"}')
        r400.aclose = AsyncMock()
        return r400

    @staticmethod
    def _payload_with_fields():
        return {
            "conversationState": {"currentMessage": {"userInputMessage": {"modelId": "claude-y"}}},
            "additionalModelRequestFields": {"output_config": {"effort": "low"}},
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("first", ["403", "400"])
    async def test_strip_retry_does_not_consume_an_attempt(self, first):
        # Streaming chat gets FIRST_TOKEN_MAX_RETRIES (2) attempts. A 403 refresh
        # plus the strip retry must still reach a third request instead of
        # failing with "Streaming failed after 2 attempts. Unknown error." (504).
        auth = _auth()
        client = KiroHttpClient(auth)
        r403, r200 = Mock(status_code=403), Mock(status_code=200)
        order = (r403, self._additional_fields_400()) if first == "403" else (self._additional_fields_400(), r403)
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.send = AsyncMock(side_effect=[*order, r200])
        mock_client.build_request = Mock(side_effect=lambda method, url, **kw: kw)
        with patch("kiro.config.FIRST_TOKEN_MAX_RETRIES", 2):
            with patch.object(client, "_get_client", return_value=mock_client):
                resp = await client.request_with_retry("POST", RUNTIME_URL, self._payload_with_fields(), stream=True)
        assert resp is r200
        assert mock_client.send.call_count == 3
        auth.force_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_strip_retry_happens_at_most_once(self):
        # After stripping, a second 400 has no field to strip: returned as is.
        client = KiroHttpClient(_auth())
        second = Mock(status_code=400)
        second.aread = AsyncMock(return_value=b'{"message":"Improperly formed request."}')
        mock_client = _mock_client(self._additional_fields_400(), second)
        with patch.object(client, "_get_client", return_value=mock_client):
            resp = await client.request_with_retry("POST", "https://api.example.com/x", self._payload_with_fields())
        assert resp is second
        assert mock_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_other_400_returned_as_is(self):
        client = KiroHttpClient(_auth())
        r400 = Mock(status_code=400)
        r400.aread = AsyncMock(return_value=b'{"message":"Improperly formed request."}')
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(return_value=r400)
        payload = {"additionalModelRequestFields": {}, "conversationState": {}}
        with patch.object(client, "_get_client", return_value=mock_client):
            resp = await client.request_with_retry("POST", "https://api.example.com/x", payload)
        assert resp is r400
        assert mock_client.request.call_count == 1


def test_uninstall_restores_upstream_method():
    uninstall_upstream_retry()
    assert KiroHttpClient.request_with_retry.__module__ == "kiro.http_client"
    install_upstream_retry()
    assert KiroHttpClient.request_with_retry.__module__ == "extensions.upstream_retry"
