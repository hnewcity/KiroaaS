"""Offline tests for opaque credential-generation bookkeeping."""

from kiro.credential_identity import CredentialIdentity


def test_new_and_empty_bindings_are_stable_and_manager_local() -> None:
    """Even missing credentials have a stable key, never shared by managers."""
    identity = CredentialIdentity()
    key = identity.binding_key
    assert key == identity.binding_key
    assert key != CredentialIdentity().binding_key
    assert len(key) == 32


def test_external_observation_changes_key_but_equal_projection_does_not() -> None:
    """Field order does not matter; changed credential material does."""
    identity = CredentialIdentity()
    initial = identity.binding_key
    assert identity.observe("json", {"refreshToken": "fake-refresh", "accessToken": "fake-access"})
    loaded = identity.binding_key
    assert loaded != initial
    assert not identity.observe("json", {"accessToken": "fake-access", "refreshToken": "fake-refresh"})
    assert identity.binding_key == loaded
    assert identity.observe("json", {"refreshToken": "fake-other"})
    assert identity.binding_key != loaded
    assert "fake" not in identity.binding_key


def test_own_write_and_unchanged_read_only_source_share_an_epoch() -> None:
    """Both old disk data and locally rotated tokens retain continuity."""
    identity = CredentialIdentity()
    identity.observe("sqlite-token", {"refresh_token": "fake-old"})
    key = identity.binding_key
    identity.record_write("sqlite-token", {"refresh_token": "fake-new"})
    assert identity.binding_key == key
    assert not identity.observe("sqlite-token", {"refresh_token": "fake-old"})
    assert not identity.observe("sqlite-token", {"refresh_token": "fake-new"})
    assert identity.binding_key == key


def test_external_change_drops_old_refresh_authority_and_prevents_aba() -> None:
    """A previous generation's locally issued tokens cannot revive its key."""
    identity = CredentialIdentity()
    identity.observe("json", {"refreshToken": "fake-a"})
    first = identity.binding_key
    identity.record_write("json", {"refreshToken": "fake-rotated-a"})
    identity.observe("json", {"refreshToken": "fake-b"})
    second = identity.binding_key
    assert second != first
    assert identity.observe("json", {"refreshToken": "fake-rotated-a"})
    assert identity.binding_key not in (first, second)


def test_removed_and_null_credentials_are_distinct_observations() -> None:
    """A successfully parsed empty source is not a failed read."""
    identity = CredentialIdentity()
    identity.observe("json", {"refreshToken": "fake-refresh"})
    assert identity.observe("json", {})
    assert not identity.observe("json", {})
    assert identity.observe("json", {"refreshToken": None})


def test_durable_binding_survives_restart_and_own_refresh(tmp_path, monkeypatch) -> None:
    """Replay identity survives; per-request generation still changes on restart."""
    import kiro.native_replay_storage as persistence
    storage = persistence.ReplayStorage(tmp_path)
    monkeypatch.setattr(persistence, "_storage", storage)
    first = CredentialIdentity()
    first.observe("json", {"refreshToken": "fake-old"})
    replay = first.replay_binding("account-A")
    first.record_write("json", {"refreshToken": "fake-new"})
    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path))
    second = CredentialIdentity()
    second.observe("json", {"refreshToken": "fake-new"})
    assert first.binding_key != second.binding_key
    assert second.replay_binding("account-A") == replay
    # A live worker still remembers the old read + its new authorized write.
    # A restarted peer reading the new token must not revoke either worker.
    assert first.replay_binding("account-A") == replay
    assert second.replay_binding("account-A") == replay
    assert second.replay_binding("account-B") != replay
    assert b"fake-old" not in storage.path.read_bytes()
    assert b"fake-new" not in storage.path.read_bytes()


def test_durable_external_replacement_and_aba_never_revive_scope(tmp_path, monkeypatch) -> None:
    """A changed source invalidates old state even if the path stays the same."""
    import kiro.native_replay_storage as persistence
    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path))
    identity = CredentialIdentity()
    identity.observe("json", {"token": "A"})
    first = identity.replay_binding("same-path")
    identity.observe("json", {"token": "B"})
    second = identity.replay_binding("same-path")
    identity.observe("json", {"token": "A"})
    third = identity.replay_binding("same-path")
    assert len({first, second, third}) == 3


def test_other_process_revocation_cannot_be_undone_by_stale_manager(tmp_path, monkeypatch) -> None:
    """An old manager must reload credentials, not overwrite a newer binding."""
    import pytest
    import kiro.native_replay_storage as persistence
    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path))
    first = CredentialIdentity()
    first.observe("json", {"token": "A"})
    first.replay_binding("account")
    second = CredentialIdentity()
    second.observe("json", {"token": "B"})
    current = second.replay_binding("account")
    with pytest.raises(persistence.ReplayStorageError, match="another process"):
        first.replay_binding("account")
    assert second.replay_binding("account") == current


def test_empty_credentials_cannot_recover_a_persistent_account(tmp_path, monkeypatch) -> None:
    """Absence of credentials is not a shared principal identity."""
    import kiro.native_replay_storage as persistence
    monkeypatch.setattr(persistence, "_storage", persistence.ReplayStorage(tmp_path))
    first, second = CredentialIdentity(), CredentialIdentity()
    assert first.replay_binding("account") != second.replay_binding("account")
