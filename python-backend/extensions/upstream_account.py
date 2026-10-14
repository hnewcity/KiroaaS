"""Bind selected account capabilities to the request before converter hooks run."""

import hashlib
from typing import Any, Dict

from extensions.request_context import current_state

_originals: Dict[str, Any] = {}


def credential_generation(auth: Any) -> str | None:
    """Read only a real epoch string, never a token or a synthetic mock attribute."""
    generation = getattr(auth, "credential_generation", None)
    return generation if isinstance(generation, str) else None


def bind_account(account: Any) -> None:
    """Attach non-secret account identity and its live metadata cache, if available."""
    state = current_state()
    if state is None or account is None:
        return
    identity = getattr(account, "id", None)
    state.auth_manager = getattr(account, "auth_manager", None)
    state.auth_generation = credential_generation(state.auth_manager)
    if isinstance(identity, str):
        binding = identity + ("\0" + state.auth_generation if state.auth_generation else "")
        state.account_scope = hashlib.sha256(binding.encode("utf-8")).hexdigest()
    state.model_cache = getattr(account, "model_cache", None)


def install_upstream_account_context() -> None:
    """Hook both pool and legacy account selection without changing route APIs."""
    if _originals:
        return
    from kiro.account_manager import AccountManager

    next_account = AccountManager.get_next_account
    first_account = AccountManager.get_first_account
    _originals.update(next=next_account, first=first_account)

    async def get_next(self: Any, *args: Any, **kwargs: Any) -> Any:
        account = await next_account(self, *args, **kwargs)
        bind_account(account)
        return account

    def get_first(self: Any, *args: Any, **kwargs: Any) -> Any:
        account = first_account(self, *args, **kwargs)
        bind_account(account)
        return account

    AccountManager.get_next_account = get_next
    AccountManager.get_first_account = get_first


def uninstall_upstream_account_context() -> None:
    """Restore original account selectors for isolated tests."""
    if not _originals:
        return
    from kiro.account_manager import AccountManager

    AccountManager.get_next_account = _originals["next"]
    AccountManager.get_first_account = _originals["first"]
    _originals.clear()
