"""Durable native replay evidence in a plain SQLite ledger.

Records are ordinary JSON rows. The file is private conversation history created
owner-only, the same protection as the credential files beside it. When the size
budget is reached the least recently used conversations are evicted, so new
requests keep working. Credential continuity uses keyed digests, never raw tokens.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any, Iterator
from uuid import uuid4

from loguru import logger


class ReplayStorageError(ValueError):
    """Replay storage is unavailable or unreadable; never bypass verification."""


# Only conversation evidence is evictable. Account bindings are tiny and must
# survive so credential continuity is not silently reset by unrelated traffic.
_EVICTABLE = ("record", "projection")
# Files written by the earlier encrypted ledger; they are ignored, never deleted.
_LEGACY_FILES = ("replay.sqlite3", "replay.key")


class ReplayStorage:
    """Bounded evidence with atomic writes and least-recently-used eviction.

    Args:
        directory: Private application directory containing the database.
        max_bytes: Maximum stored JSON bytes. When full, the least recently used
            conversations are evicted; a single oversized entry is not persisted.
    """

    def __init__(self, directory: Path, max_bytes: int = 512 * 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("Native replay storage limit must be positive")
        self.directory = Path(directory).absolute()
        self.path = self.directory / "history.sqlite3"
        self.max_bytes = max_bytes
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        except OSError as error:
            raise ReplayStorageError("Native replay storage cannot be created; check its directory") from error
        with self._connection(write=True) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS evidence ("
                               "kind TEXT NOT NULL, id TEXT NOT NULL, lookup TEXT NOT NULL, "
                               "payload TEXT NOT NULL, size INTEGER NOT NULL, accessed INTEGER NOT NULL, "
                               "PRIMARY KEY(kind, id))")
            connection.execute("CREATE INDEX IF NOT EXISTS evidence_lookup ON evidence(kind, lookup)")
            connection.execute("CREATE INDEX IF NOT EXISTS evidence_accessed ON evidence(accessed)")
            row = connection.execute("SELECT payload FROM evidence WHERE kind='meta' AND id='index'").fetchone()
            if row is None:
                if connection.execute("SELECT count(*) FROM evidence").fetchone()[0]:
                    raise ReplayStorageError("Native replay index key is missing; restore the original database")
                secret = secrets.token_hex(32)
                self._write(connection, "meta", "index", "", {"version": 2, "key": secret})
            else:
                meta = self._decode("meta", "index", row[0])
                secret = meta.get("key")
                if meta.get("version") != 2 or not isinstance(secret, str) or len(secret) != 64:
                    raise ReplayStorageError("Unsupported native replay schema; keep the original database")
        try:
            self._index_key = bytes.fromhex(secret)
        except ValueError as error:
            raise ReplayStorageError("Native replay index key is invalid; restore the original database") from error
        legacy = [name for name in _LEGACY_FILES if (self.directory / name).exists()]
        if legacy:
            logger.warning(f"Ignoring legacy encrypted native replay files {legacy} in {self.directory}; "
                           "they are no longer read and can be deleted")

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Use a short transaction; connections are never shared across threads."""
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=10)
            # FULL + rollback journal keeps the committed record crash-atomic.
            connection.execute("PRAGMA synchronous=FULL")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except (sqlite3.Error, OSError) as error:
            raise ReplayStorageError("Native replay storage I/O failed; check free space, permissions and database health") from error
        finally:
            if connection is not None:
                connection.close()

    def fingerprint(self, domain: str, value: Any) -> str:
        """Return a domain-separated private lookup digest, never a credential hash."""
        material = json.dumps([domain, value], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(self._index_key, material.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _decode(kind: str, key: str, payload: Any) -> dict[str, Any]:
        """Check the row's own identity before returning any data."""
        try:
            envelope = json.loads(payload)
        except (TypeError, ValueError) as error:
            raise ReplayStorageError("Native replay record is unreadable; the database may be corrupt") from error
        if (not isinstance(envelope, dict) or envelope.get("kind") != kind
                or envelope.get("id") != key or not isinstance(envelope.get("value"), dict)):
            raise ReplayStorageError("Native replay record identity is invalid; do not bypass history verification")
        return envelope["value"]

    def _evict(self, connection: sqlite3.Connection, needed: int, kind: str, key: str) -> int:
        """Delete least recently used evidence, except the row being written."""
        placeholders = ",".join("?" for _ in _EVICTABLE)
        cursor = connection.execute(f"SELECT rowid, size FROM evidence WHERE kind IN ({placeholders}) "
                                    "AND NOT (kind=? AND id=?) ORDER BY accessed, rowid",
                                    (*_EVICTABLE, kind, key))
        victims, freed = [], 0
        for rowid, size in cursor:
            if freed >= needed:
                break
            victims.append((rowid,))
            freed += size
        cursor.close()
        connection.executemany("DELETE FROM evidence WHERE rowid=?", victims)
        if victims:
            logger.info(f"Native replay storage reached its budget; evicted {len(victims)} least recently used entries")
        return freed

    def _write(self, connection: sqlite3.Connection, kind: str, key: str, lookup: str,
               value: dict[str, Any]) -> bool:
        """Write one complete record, evicting old evidence when over budget.

        Returns:
            False when the entry alone exceeds the budget and was not persisted.
        """
        payload = json.dumps({"kind": kind, "id": key, "value": value}, ensure_ascii=False,
                             separators=(",", ":"))
        size = len(payload.encode("utf-8"))
        if size > self.max_bytes:
            logger.warning(f"Native replay {kind} entry ({size} bytes) exceeds KIRO_NATIVE_REPLAY_MAX_BYTES; "
                           "kept in memory only")
            return False
        used = connection.execute("SELECT coalesce(sum(size), 0) FROM evidence").fetchone()[0]
        previous = connection.execute("SELECT size FROM evidence WHERE kind=? AND id=?", (kind, key)).fetchone()
        excess = used + size - (previous[0] if previous else 0) - self.max_bytes
        if excess > 0 and self._evict(connection, excess, kind, key) < excess:
            logger.warning(f"Native replay storage cannot free space for a {kind} entry; kept in memory only")
            return False
        connection.execute("INSERT INTO evidence(kind, id, lookup, payload, size, accessed) VALUES(?, ?, ?, ?, ?, ?) "
                           "ON CONFLICT(kind, id) DO UPDATE SET lookup=excluded.lookup, payload=excluded.payload, "
                           "size=excluded.size, accessed=excluded.accessed",
                           (kind, key, lookup, payload, size, time.time_ns()))
        return True

    def _touch(self, rowid: int) -> None:
        """Mark evidence as recently used; a failed update only affects eviction order."""
        try:
            with self._connection(write=True) as connection:
                connection.execute("UPDATE evidence SET accessed=? WHERE rowid=?", (time.time_ns(), rowid))
        except ReplayStorageError as error:
            logger.debug(f"Native replay access time was not updated: {error}")

    def put(self, kind: str, key: str, value: dict[str, Any], *, lookup: str = "") -> bool:
        """Commit evidence before it becomes available in RAM.

        Returns:
            False when the entry was too large to persist under the budget.
        """
        with self._connection(write=True) as connection:
            return self._write(connection, kind, key, lookup, value)

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        """Read one exact key, distinguishing absence from an unreadable store."""
        with self._connection() as connection:
            row = connection.execute("SELECT rowid, payload FROM evidence WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            return None
        value = self._decode(kind, key, row[1])
        self._touch(row[0])
        return value

    def find(self, kind: str, lookup: str) -> Iterator[dict[str, Any]]:
        """Yield candidates; callers still verify their complete semantic identity."""
        before = 9223372036854775807
        while True:
            # Close the read transaction before yielding: a caller may attach a
            # projection with a separate write transaction to the same database.
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT rowid, id, payload FROM evidence WHERE kind=? AND lookup=? AND rowid<? "
                    "ORDER BY rowid DESC LIMIT 1", (kind, lookup, before),
                ).fetchone()
            if row is None:
                return
            before, key, payload = row
            value = self._decode(kind, key, payload)
            self._touch(before)
            yield value

    def bind_credentials(self, namespace: str, observed: dict[str, str], owned: dict[str, str],
                         *, expected: str | None, rotate: bool) -> str:
        """Recover a binding only from matching keyed credential-source snapshots.

        Local refresh writes extend a binding. External replacement rotates it.
        Compare-and-swap prevents an old manager from reviving a revoked binding.
        No tokens or other raw credential fields enter the persisted snapshot.
        """
        key = self.fingerprint("account", namespace)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT payload FROM evidence WHERE kind='account' AND id=?", (key,)).fetchone()
            previous = self._decode("account", key, row[0]) if row else None
            if expected is not None and (previous is None or previous.get("binding") != expected):
                raise ReplayStorageError("Native replay account binding changed in another process; reload the current credentials")
            # An already bound, unchanged manager remains in this epoch even if
            # a restarted peer observed its locally refreshed token on disk.
            # External observe() changes set rotate=True; a different DB epoch
            # was rejected by the compare-and-swap check above.
            compatible = bool(previous and (
                (expected is not None and not rotate) or
                (observed and set(observed) == set(previous["observed"])
                 and all(digest in (previous["observed"].get(source), previous["owned"].get(source))
                         for source, digest in observed.items()))
            ))
            binding = previous["binding"] if compatible and not rotate else uuid4().hex
            snapshot = {"binding": binding, "observed": observed,
                        "owned": {**(previous["owned"] if compatible and not rotate else {}), **owned}}
            if snapshot != previous:
                self._write(connection, "account", key, "", snapshot)
            return binding


_storage: ReplayStorage | None = None


def current_storage() -> ReplayStorage | None:
    """Return lifecycle-configured storage; importing modules never touches disk."""
    return _storage


def set_storage(storage: ReplayStorage | None) -> None:
    """Bind storage before account managers are initialized (also isolates tests)."""
    global _storage
    _storage = storage
