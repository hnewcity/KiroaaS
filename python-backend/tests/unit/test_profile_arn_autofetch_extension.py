# -*- coding: utf-8 -*-

"""
Tests for the profileArn autofetch extension.

The extension wraps KiroAuthManager.get_access_token so that, when a manager
has no profileArn, it resolves one via ListAvailableProfiles (on
q.{region}.amazonaws.com) exactly once per instance. Failures are non-fatal:
the manager keeps whatever (possibly empty) profileArn it had.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from kiro.auth import KiroAuthManager
from extensions.profile_arn_autofetch import (
    install_profile_arn_autofetch,
    uninstall_profile_arn_autofetch,
)


@pytest.fixture(autouse=True)
def clean_autofetch():
    uninstall_profile_arn_autofetch()
    install_profile_arn_autofetch()
    yield
    uninstall_profile_arn_autofetch()


def _make_manager(profile_arn=None, sso_region=None, region="us-east-1", creds_file=None):
    """
    Build a manager with a valid in-memory token so the *original*
    get_access_token short-circuits (no token refresh / network).
    """
    manager = KiroAuthManager(refresh_token="rt", profile_arn=profile_arn, region=region)
    manager._access_token = "valid-token"
    manager._expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    manager._sso_region = sso_region
    manager._creds_file = creds_file
    return manager


def _mock_async_client(status_code=200, json_data=None, raises=None):
    """Patch httpx.AsyncClient inside the extension; return (patcher, post_mock)."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json = Mock(return_value=json_data or {})
    mock_response.text = json.dumps(json_data or {})

    mock_client = AsyncMock()
    if raises is not None:
        mock_client.request = AsyncMock(side_effect=raises)
    else:
        mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    patcher = patch(
        "extensions.profile_arn_autofetch.httpx.AsyncClient",
        return_value=mock_client,
    )
    return patcher, mock_client.request


_PROFILES_OK = {"profiles": [{"arn": "arn:aws:codewhisperer:us-east-1:1:profile/p", "profileName": "p"}]}


@pytest.mark.asyncio
async def test_fetches_profile_arn_when_missing():
    manager = _make_manager(profile_arn=None)
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        token = await manager.get_access_token()

    assert token == "valid-token"
    assert manager.profile_arn == "arn:aws:codewhisperer:us-east-1:1:profile/p"
    post.assert_called_once()


@pytest.mark.asyncio
async def test_no_fetch_when_profile_arn_present():
    manager = _make_manager(profile_arn="arn:existing")
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await manager.get_access_token()

    assert manager.profile_arn == "arn:existing"
    post.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_calls_fetch_only_once():
    manager = _make_manager(profile_arn=None)
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await asyncio.gather(*[manager.get_access_token() for _ in range(5)])

    assert post.call_count == 1
    assert manager.profile_arn == "arn:aws:codewhisperer:us-east-1:1:profile/p"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"status_code": 403, "json_data": {}},
        {"status_code": 200, "json_data": {"profiles": []}},
        {"raises": RuntimeError("boom")},
    ],
)
async def test_failure_is_non_fatal_and_not_retried(kwargs):
    manager = _make_manager(profile_arn=None)
    patcher, post = _mock_async_client(**kwargs)

    with patcher:
        token = await manager.get_access_token()
        assert token == "valid-token"
        assert manager.profile_arn is None
        # Flag set on the failed attempt → second call must NOT re-fetch.
        await manager.get_access_token()

    assert post.call_count == 1


@pytest.mark.asyncio
async def test_uses_sso_region_for_endpoint():
    manager = _make_manager(profile_arn=None, sso_region="eu-west-1", region="us-east-1")
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await manager.get_access_token()

    url = post.call_args.args[1]
    assert url == "https://q.eu-west-1.amazonaws.com/"
    assert "kiro.dev" not in url


@pytest.mark.asyncio
async def test_falls_back_to_region_when_no_sso_region():
    manager = _make_manager(profile_arn=None, sso_region=None, region="ap-southeast-2")
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await manager.get_access_token()

    assert post.call_args.args[1] == "https://q.ap-southeast-2.amazonaws.com/"


@pytest.mark.asyncio
async def test_request_headers_and_body():
    manager = _make_manager(profile_arn=None)
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await manager.get_access_token()

    headers = post.call_args.kwargs["headers"]
    body = post.call_args.kwargs["json"]
    assert headers["Authorization"] == "Bearer valid-token"
    assert headers["x-amz-target"] == "AmazonCodeWhispererService.ListAvailableProfiles"
    assert headers["Content-Type"] == "application/x-amz-json-1.0"
    assert headers["User-Agent"].startswith("KiroaaS/")
    assert body == {"nextToken": None}


@pytest.mark.asyncio
async def test_persists_to_file_when_creds_file_present():
    manager = _make_manager(profile_arn=None, creds_file="/tmp/creds.json")
    manager._save_credentials_to_file = Mock()
    patcher, _ = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await manager.get_access_token()

    manager._save_credentials_to_file.assert_called_once()


@pytest.mark.asyncio
async def test_no_file_persist_in_sqlite_mode():
    manager = _make_manager(profile_arn=None, creds_file=None)
    manager._save_credentials_to_file = Mock()
    patcher, _ = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        await manager.get_access_token()

    # ARN is held in memory; sqlite save path does not persist profile_arn.
    assert manager.profile_arn == "arn:aws:codewhisperer:us-east-1:1:profile/p"
    manager._save_credentials_to_file.assert_not_called()


@pytest.mark.asyncio
async def test_uninstall_restores_original_get_access_token():
    uninstall_profile_arn_autofetch()
    manager = _make_manager(profile_arn=None)
    patcher, post = _mock_async_client(json_data=_PROFILES_OK)

    with patcher:
        token = await manager.get_access_token()

    assert token == "valid-token"
    assert manager.profile_arn is None
    post.assert_not_called()
