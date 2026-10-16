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


def test_real_auth_binding_resumes_after_restart_but_not_replacement(tmp_path, monkeypatch) -> None:
    """Real account selection uses durable replay scope and an independent send guard."""
    import json
    import kiro.native_replay_storage as persistence
    from kiro.auth import KiroAuthManager
    from extensions.upstream_account import bind_account
    from kiro.native_reasoning import ReasoningStore, reasoning_blocks, NativeReasoningError
    from tests.unit.test_native_reasoning import ledger, identity

    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path / "replay"))
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"refreshToken": "fake-A", "accessToken": "fake-access",
                                        "expiresAt": "2099-01-01T00:00:00Z"}), encoding="utf-8")

    def scope():
        manager = KiroAuthManager(creds_file=str(credentials))
        state, token = start_request_state()
        try:
            bind_account(SimpleNamespace(id="same-source", auth_manager=manager, model_cache=None))
            return manager, state.account_scope, state.auth_generation
        finally:
            reset_request_state(token)

    first, before, generation = scope()
    store = ReasoningStore(storage=persistence.current_storage())
    generated = ledger()
    store.record(("client", before, "model"), identity(), "anchor", generated)
    # A normal locally performed credential refresh preserves restart continuity.
    first._refresh_token = "fake-refreshed"
    first._access_token = "fake-new-access"
    first._save_credentials_to_file()
    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path / "replay"))
    second, after, new_generation = scope()
    assert before == after and generation != new_generation
    restarted = ReasoningStore(storage=persistence.current_storage())
    assert restarted.find(("client", after, "model"), "answer", [], reasoning_blocks(generated.blocks))
    data = json.loads(credentials.read_text(encoding="utf-8"))
    data["refreshToken"] = "different-account"
    credentials.write_text(json.dumps(data), encoding="utf-8")
    _, changed, _ = scope()
    assert changed != before
    with pytest.raises(NativeReasoningError):
        restarted.find(("client", changed, "model"), "answer", [], reasoning_blocks(generated.blocks))


def test_durable_binding_includes_constructor_credential_fallbacks(tmp_path, monkeypatch) -> None:
    """Identical partial source files do not prove different fallback tokens equal."""
    import json
    import kiro.native_replay_storage as persistence
    from kiro.auth import KiroAuthManager

    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path / "replay"))
    credentials = tmp_path / "partial.json"
    credentials.write_text(json.dumps({"accessToken": "fixture-access"}), encoding="utf-8")
    first = KiroAuthManager(creds_file=str(credentials), refresh_token="fixture-principal-A")
    original = first.replay_binding("same-path")
    second = KiroAuthManager(creds_file=str(credentials), refresh_token="fixture-principal-B")
    assert second.replay_binding("same-path") != original
    empty = KiroAuthManager()
    assert empty.replay_binding("same-path") == empty.credential_generation
