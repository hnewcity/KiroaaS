"""Process-local credential epochs, not verified account or JWT identities."""

import hashlib
import hmac
import json
import secrets
import threading
from typing import Mapping
from uuid import uuid4

from kiro.native_replay_storage import current_storage


class CredentialIdentity:
    """Track external source changes separately from this manager's own writes.

    Public keys are random and contain neither credentials nor their hashes.
    Only private keyed digests of selected credential fields are retained. A
    source's last read and latest locally produced write share an epoch, even
    when persistence fails or a read-only source still contains older tokens.
    """

    def __init__(self) -> None:
        """Create an independent binding, including for missing credentials."""
        self._lock = threading.RLock()
        self._key = uuid4().hex
        self._digest_key = secrets.token_bytes(32)
        self._observed: dict[str, bytes] = {}
        self._owned: dict[str, bytes] = {}
        self._storage = current_storage()
        self._replay_bindings: dict[str, tuple[str, str]] = {}

    @property
    def binding_key(self) -> str:
        """Return an opaque immutable snapshot of the current credential epoch."""
        return self._key

    def _digest(self, material: Mapping[str, object]) -> bytes:
        """Digest selected source fields without exposing credential material."""
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if self._storage is not None:
            return bytes.fromhex(self._storage.fingerprint("credential-source", material))
        return hmac.digest(self._digest_key, encoded, hashlib.sha256)

    def observe(self, source: str, material: Mapping[str, object]) -> bool:
        """Observe a loader result and report whether it starts a new epoch.

        Args:
            source: Internal loader channel, never an account label or path.
            material: Credential fields actually read from that source.

        Returns:
            True when the observed credentials were not already in this epoch.
        """
        with self._lock:
            digest = self._digest(material)
            changed = digest not in (self._observed.get(source), self._owned.get(source))
            if changed:
                self._key = uuid4().hex
                self._owned.clear()
            self._observed[source] = digest
            return changed

    def record_write(self, source: str, material: Mapping[str, object]) -> None:
        """Recognize a local refresh write without advancing its credential epoch.

        Args:
            source: The loader channel that will read this write.
            material: The exact credential fields written by this manager.
        """
        with self._lock:
            self._owned[source] = self._digest(material)
            # Persist locally authorized token rotation before a possible restart.
            for namespace in list(self._replay_bindings):
                self.replay_binding(namespace)

    def replay_binding(self, namespace: str) -> str:
        """Return durable continuity proof, distinct from the in-flight epoch.

        Args:
            namespace: Selected account identity, used for partitioning, not proof.

        Returns:
            A stable opaque binding only when credential observations match.
            Accounts without observed credentials retain process-local isolation.
        """
        with self._lock:
            if self._storage is None or not self._observed:
                return self._key
            previous = self._replay_bindings.get(namespace)
            binding = self._storage.bind_credentials(
                namespace, {key: value.hex() for key, value in self._observed.items()},
                {key: value.hex() for key, value in self._owned.items()},
                expected=previous[0] if previous else None,
                rotate=previous is not None and previous[1] != self._key,
            )
            self._replay_bindings[namespace] = (binding, self._key)
            return binding
