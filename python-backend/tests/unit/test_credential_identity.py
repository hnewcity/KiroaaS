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
