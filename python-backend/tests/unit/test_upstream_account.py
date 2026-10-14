"""Account selection hooks bind both legacy and pooled routes without network calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from extensions.request_context import reset_request_state, start_request_state
from extensions.upstream_account import install_upstream_account_context, uninstall_upstream_account_context
from kiro.account_manager import AccountManager


@pytest.mark.asyncio
async def test_both_selectors_bind_cache_and_restore(monkeypatch):
    uninstall_upstream_account_context()
    first = SimpleNamespace(id="fixture-A", model_cache=object())
    second = SimpleNamespace(id="fixture-B", model_cache=object())
    first_method = Mock(return_value=first)
    next_method = AsyncMock(return_value=second)
    monkeypatch.setattr(AccountManager, "get_first_account", first_method)
    monkeypatch.setattr(AccountManager, "get_next_account", next_method)
    manager = object.__new__(AccountManager)
    install_upstream_account_context()
    install_upstream_account_context()
    state, token = start_request_state()
    try:
        assert manager.get_first_account() is first
        scope_a = state.account_scope
        assert state.model_cache is first.model_cache
        assert await manager.get_next_account("model", exclude_accounts={"fixture-A"}) is second
        assert state.model_cache is second.model_cache
        assert state.account_scope != scope_a
        assert "fixture-B" not in state.account_scope
        next_method.assert_awaited_once_with(manager, "model", exclude_accounts={"fixture-A"})
    finally:
        reset_request_state(token)
        uninstall_upstream_account_context()
    assert AccountManager.get_first_account is first_method
    assert AccountManager.get_next_account is next_method


@pytest.mark.asyncio
async def test_selection_outside_request_is_safe(monkeypatch):
    uninstall_upstream_account_context()
    monkeypatch.setattr(AccountManager, "get_first_account", Mock(return_value=None))
    monkeypatch.setattr(AccountManager, "get_next_account", AsyncMock(return_value=None))
    install_upstream_account_context()
    try:
        manager = object.__new__(AccountManager)
        assert manager.get_first_account() is None
        assert await manager.get_next_account("model") is None
    finally:
        uninstall_upstream_account_context()
