"""Offline encrypted replay persistence, integrity, quota and process isolation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from kiro.native_replay_storage import ReplayStorage, ReplayStorageError
from kiro.native_reasoning import NativeReasoningError, ReasoningStore, reasoning_blocks
from tests.unit.test_native_reasoning import identity, ledger
from tests.unit.test_native_projection import fixture_projection, SCOPE


def test_encrypted_records_survive_restart_and_memory_eviction(tmp_path: Path) -> None:
    """The earliest turn remains recoverable beyond the old 512-record ceiling."""
    storage = ReplayStorage(tmp_path)
    store = ReasoningStore(max_records=2, storage=storage)
    original = ledger()
    store.record(SCOPE, identity(), "private-original-turn-fixture", original)
    for index in range(513):
        store.record(SCOPE, identity(), str(index), ledger(signature=f"fixture-{index}"))
    assert len(store._records) == 2
    restarted = ReasoningStore(max_records=2, storage=ReplayStorage(tmp_path))
    found = restarted.find(SCOPE, "answer", [], reasoning_blocks(original.blocks))
    assert found.root_conversation_id == "root"
    assert len(restarted._records) == 1
    raw = storage.path.read_bytes()
    assert b'"thinking"' not in raw and b'"signature"' not in raw
    assert b"fixture-512" not in raw and b"private-original-turn-fixture" not in raw
    assert b"thought" not in (tmp_path / "replay.key").read_bytes()


@pytest.mark.parametrize("anthropic", [True, False])
def test_complete_projection_survives_restart(tmp_path: Path, anthropic: bool) -> None:
    """Original tool IDs and generated results survive both public API projections."""
    from kiro.native_reasoning import restore_native_projections

    store = ReasoningStore(storage=ReplayStorage(tmp_path))
    _, _, _, _, _, message = fixture_projection(anthropic, store=store)
    before = restore_native_projections([message], scope=SCOPE, anthropic=anthropic, store=store)
    restarted = ReasoningStore(storage=ReplayStorage(tmp_path))
    after = restore_native_projections([message], scope=SCOPE, anthropic=anthropic, store=restarted)
    assert after == before
    assert restarted._records
    message = json.loads(json.dumps(message))
    message["content"] = "tampered" if not anthropic else [{"type": "text", "text": "tampered"}, *message["content"]]
    if anthropic:
        with pytest.raises(NativeReasoningError):
            restore_native_projections([message], scope=SCOPE, anthropic=True, store=restarted)


def test_projection_can_be_attached_after_original_ram_eviction(tmp_path: Path) -> None:
    """Disk reads must release SQLite read locks before the projection write."""
    store = ReasoningStore(storage=ReplayStorage(tmp_path))
    _, generated, origin, exchanges, visible, _ = fixture_projection(store=store, record=False)
    store.record(SCOPE, origin, "anchor", generated)
    store.clear()
    store.record_projection(SCOPE, origin, "anchor", generated, exchanges, anthropic=True, emitted=visible)
    store.clear()
    assert store.find_projection(SCOPE, visible, anthropic=True) is not None


@pytest.mark.parametrize("field", [0, 1, 2])
def test_restart_does_not_bypass_scope_isolation(tmp_path: Path, field: int) -> None:
    """Changing any client/account/model component cannot authorize replay."""
    original = ledger()
    ReasoningStore(storage=ReplayStorage(tmp_path)).record(SCOPE, identity(), "turn", original)
    changed = list(SCOPE)
    changed[field] = "different"
    store = ReasoningStore(storage=ReplayStorage(tmp_path))
    with pytest.raises(NativeReasoningError, match="native_history_unavailable"):
        store.find(tuple(changed), "answer", [], reasoning_blocks(original.blocks))
    with pytest.raises(NativeReasoningError):
        store.find(SCOPE, "edited-answer", [], reasoning_blocks(original.blocks))


def test_quota_refuses_new_write_without_deleting_old_proof(tmp_path: Path) -> None:
    """A storage limit is an explicit failure, never silent LRU history loss."""
    storage = ReplayStorage(tmp_path, max_bytes=4096)
    storage.put("test", "old", {"message": "keep"})
    with pytest.raises(ReplayStorageError, match="full"):
        storage.put("test", "new", {"message": "x" * 10000})
    assert storage.get("test", "new") is None
    assert storage.get("test", "old") == {"message": "keep"}


def test_missing_key_is_not_recreated(tmp_path: Path) -> None:
    """Losing the key requires restoring it, not silently starting another ledger."""
    ReplayStorage(tmp_path).put("test", "old", {"data": "private"})
    (tmp_path / "replay.key").unlink()
    with pytest.raises(ReplayStorageError, match="key is missing"):
        ReplayStorage(tmp_path)
    assert not (tmp_path / "replay.key").exists()


def test_corrupt_record_and_swapped_rows_fail_authentication(tmp_path: Path) -> None:
    """Authenticated envelopes bind ciphertext to its kind and record key."""
    storage = ReplayStorage(tmp_path)
    storage.put("test", "a", {"data": "one"})
    storage.put("test", "b", {"data": "two"})
    with sqlite3.connect(storage.path) as connection:
        connection.execute("UPDATE evidence SET payload=(SELECT payload FROM evidence WHERE id='a') WHERE id='b'")
    with pytest.raises(ReplayStorageError, match="authenticated"):
        storage.get("test", "b")
    with sqlite3.connect(storage.path) as connection:
        connection.execute("UPDATE evidence SET payload=? WHERE id='a'", (b"broken",))
    with pytest.raises(ReplayStorageError, match="authenticated"):
        storage.get("test", "a")


def test_read_failure_is_not_reported_as_missing_history(tmp_path: Path) -> None:
    """Disk corruption has an actionable storage error rather than a generic 400."""
    storage = ReplayStorage(tmp_path)
    storage.path.write_bytes(b"not-a-database")
    with pytest.raises(ReplayStorageError, match="I/O"):
        storage.get("test", "record")


def test_concurrent_initialization_uses_one_complete_key(tmp_path: Path) -> None:
    """Parallel initializers never read a half-written or replaced encryption key."""
    def initialize(index: int) -> str:
        store = ReplayStorage(tmp_path)
        store.put("test", str(index), {"index": index})
        return store.fingerprint("same", "value")

    with ThreadPoolExecutor(max_workers=4) as pool:
        fingerprints = list(pool.map(initialize, range(8)))
    assert len(set(fingerprints)) == 1
    assert all(ReplayStorage(tmp_path).get("test", str(i)) == {"index": i} for i in range(8))


def test_real_subprocess_can_reopen_proof(tmp_path: Path) -> None:
    """Exercise a fresh interpreter, not just another in-process object."""
    store = ReplayStorage(tmp_path)
    store.put("test", "record", {"text": "private fixture"})
    backend = str(Path(__file__).resolve().parents[2])
    code = ("from pathlib import Path; from kiro.native_replay_storage import ReplayStorage; "
            "import sys; s=ReplayStorage(Path(sys.argv[1])); "
            "assert s.get('test','record') == {'text':'private fixture'}; print('reopened')")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                            env={**os.environ, "PYTHONPATH": backend},
                            capture_output=True, text=True, timeout=30, check=True)
    assert result.stdout.strip() == "reopened"


def test_explicit_memory_mode_and_lifecycle_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration is lazy; memory opt-out never creates a database/key."""
    from kiro.native_reasoning import initialize_native_replay, shutdown_native_replay, reasoning_store
    from kiro.native_replay_storage import current_storage

    monkeypatch.setenv("KIRO_NATIVE_REPLAY_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("KIRO_NATIVE_REPLAY_MODE", "memory")
    try:
        initialize_native_replay(str(tmp_path / "state.json"))
        assert current_storage() is None and not (tmp_path / "private").exists()
        monkeypatch.setenv("KIRO_NATIVE_REPLAY_MODE", "persistent")
        initialize_native_replay(str(tmp_path / "state.json"))
        assert reasoning_store.storage is current_storage()
        assert current_storage().path.is_file()
        shutdown_native_replay()
        assert current_storage() is None
        assert (tmp_path / "private" / "replay.sqlite3").exists()
    finally:
        shutdown_native_replay()


@pytest.mark.parametrize("mode,budget", [("invalid", "4096"), ("persistent", "0"), ("persistent", "NaN")])
def test_invalid_configuration_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                          mode: str, budget: str) -> None:
    """Invalid options never fall back to silently non-resumable operation."""
    from kiro.native_reasoning import initialize_native_replay
    monkeypatch.setenv("KIRO_NATIVE_REPLAY_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("KIRO_NATIVE_REPLAY_MODE", mode)
    monkeypatch.setenv("KIRO_NATIVE_REPLAY_MAX_BYTES", budget)
    with pytest.raises(ValueError):
        initialize_native_replay(str(tmp_path / "state.json"))


def test_other_database_key_cannot_unlock_existing_history(tmp_path: Path) -> None:
    """A valid but unrelated encryption key must not make old records look absent."""
    first, second = tmp_path / "a", tmp_path / "b"
    ReplayStorage(first).put("test", "record", {"data": "private"})
    ReplayStorage(second)
    (first / "replay.key").write_bytes((second / "replay.key").read_bytes())
    with pytest.raises(ReplayStorageError, match="authenticated"):
        ReplayStorage(first)


@pytest.mark.skipif(os.name == "nt", reason="POSIX filesystem permission policy")
def test_shared_key_permissions_are_rejected(tmp_path: Path) -> None:
    """Without a Windows keystore, the raw key must not be readable by others."""
    ReplayStorage(tmp_path)
    (tmp_path / "replay.key").chmod(0o644)
    with pytest.raises(ReplayStorageError, match="owner-only"):
        ReplayStorage(tmp_path)
