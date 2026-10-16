"""Encrypted, non-expiring replay evidence. Memory eviction is not evidence deletion.

SQLite contains authenticated encrypted values and keyed lookup indexes only.
Windows protects the separate encryption key with current-user DPAPI; other hosts
require an owner-only directory/key. No credential material is persisted: credential
continuity uses keyed digests, never account labels as proof of identity.
"""

from __future__ import annotations

from contextlib import contextmanager
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterator
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken


class ReplayStorageError(ValueError):
    """Replay storage is unavailable or unauthenticated; never bypass verification."""


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    """Protect/unprotect bytes for the current Windows user, without showing UI."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError(ctypes.get_last_error(), "Current-user DPAPI failed")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def _load_key(directory: Path, database: Path) -> bytes:
    """Atomically publish a complete key; never regenerate a lost database key."""
    path = directory / "replay.key"
    if path.is_symlink() or database.is_symlink():
        raise ReplayStorageError("Native replay key/database must not be symbolic links")
    if not path.exists():
        if database.exists() and database.stat().st_size:
            raise ReplayStorageError("Native replay key is missing; restore the original key, not a new one")
        key = Fernet.generate_key()
        encoded = b"DPAPI1:" + _dpapi(key) if os.name == "nt" else b"FERNET1:" + key
        descriptor, temporary = tempfile.mkstemp(prefix=".replay-key-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # Unlike replacing the destination, this preserves a concurrent winner.
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ReplayStorageError("Native replay key must have owner-only permissions (0600)")
    encoded = path.read_bytes()
    if os.name == "nt" and encoded.startswith(b"DPAPI1:"):
        return _dpapi(encoded[7:], decrypt=True)
    if os.name != "nt" and encoded.startswith(b"FERNET1:"):
        return encoded[8:]
    raise ReplayStorageError("Native replay key format/platform mismatch; restore the original protected key")


class ReplayStorage:
    """Bounded encrypted evidence with atomic writes and no automatic TTL eviction.

    Args:
        directory: Private application directory containing the database and key.
        max_bytes: Maximum encrypted value bytes. Full storage refuses new writes;
            it never silently evicts a conversation needed by another request.
    """

    def __init__(self, directory: Path, max_bytes: int = 512 * 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("Native replay storage limit must be positive")
        self.directory = Path(directory).absolute()
        self.path = self.directory / "replay.sqlite3"
        self.max_bytes = max_bytes
        try:
            if self.directory.is_symlink():
                raise ReplayStorageError("Native replay directory must not be a symbolic link")
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt" and self.directory.stat().st_mode & 0o077:
                raise ReplayStorageError("Native replay directory must have owner-only permissions (0700)")
            key = _load_key(self.directory, self.path)
            try:
                self._cipher = Fernet(key)
            except ValueError as error:
                raise ReplayStorageError("Native replay encryption key is invalid; restore the original key") from error
            self._index_key = base64.urlsafe_b64decode(key)
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            with self._connection(write=True) as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS evidence ("
                                   "kind TEXT NOT NULL, id TEXT NOT NULL, lookup TEXT NOT NULL, "
                                   "payload BLOB NOT NULL, PRIMARY KEY(kind, id))")
                connection.execute("CREATE INDEX IF NOT EXISTS evidence_lookup ON evidence(kind, lookup)")
                row = connection.execute("SELECT payload FROM evidence WHERE kind='meta' AND id='version'").fetchone()
                if row is None:
                    if connection.execute("SELECT count(*) FROM evidence").fetchone()[0]:
                        raise ReplayStorageError("Native replay schema marker is missing")
                    self._write(connection, "meta", "version", "", {"version": 1})
                elif self._decode("meta", "version", row[0]) != {"version": 1}:
                    raise ReplayStorageError("Unsupported native replay schema; keep the original database")
        except (OSError, sqlite3.Error, InvalidToken) as error:
            raise ReplayStorageError("Native replay storage cannot be opened/unlocked; check its directory and key") from error

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

    def _decode(self, kind: str, key: str, payload: bytes) -> dict[str, Any]:
        """Authenticate the value and its row identity before returning any data."""
        try:
            envelope = json.loads(self._cipher.decrypt(payload))
            if (not isinstance(envelope, dict) or envelope.get("kind") != kind
                    or envelope.get("id") != key or not isinstance(envelope.get("value"), dict)):
                raise ReplayStorageError("Native replay record identity is invalid; do not bypass history verification")
            return envelope["value"]
        except (InvalidToken, ValueError, UnicodeError) as error:
            raise ReplayStorageError("Native replay record cannot be authenticated; restore the original database/key") from error

    def _write(self, connection: sqlite3.Connection, kind: str, key: str, lookup: str,
               value: dict[str, Any]) -> None:
        """Write one complete encrypted record without evicting other evidence."""
        encoded = json.dumps({"kind": kind, "id": key, "value": value}, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        payload = self._cipher.encrypt(encoded)
        used = connection.execute("SELECT coalesce(sum(length(payload)), 0) FROM evidence").fetchone()[0]
        previous = connection.execute("SELECT length(payload) FROM evidence WHERE kind=? AND id=?", (kind, key)).fetchone()
        if used + len(payload) - (previous[0] if previous else 0) > self.max_bytes:
            raise ReplayStorageError("Native replay storage is full; increase KIRO_NATIVE_REPLAY_MAX_BYTES or explicitly clear unneeded history")
        connection.execute("INSERT INTO evidence(kind, id, lookup, payload) VALUES(?, ?, ?, ?) "
                           "ON CONFLICT(kind, id) DO UPDATE SET lookup=excluded.lookup, payload=excluded.payload",
                           (kind, key, lookup, payload))

    def put(self, kind: str, key: str, value: dict[str, Any], *, lookup: str = "") -> None:
        """Commit authenticated evidence before it becomes available in RAM."""
        with self._connection(write=True) as connection:
            self._write(connection, kind, key, lookup, value)

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        """Read one exact key, distinguishing absence from an unreadable store."""
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM evidence WHERE kind=? AND id=?", (kind, key)).fetchone()
            return self._decode(kind, key, row[0]) if row else None

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
            yield self._decode(kind, key, payload)

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
