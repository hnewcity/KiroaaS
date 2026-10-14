"""Explicit, account-scoped session identity and bounded execution-turn state.

Content is never used to invent a session. Within an explicitly identified session,
a history-prefix digest only locates a user turn so tool-result continuations reuse
its execution ID. No prompt text, credentials, or tool results are retained.
"""

import hashlib
import json
import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from extensions.request_context import current_state

_SESSION_NAMESPACE = uuid.UUID("e73b65c1-b6b9-4b8b-9c4a-8a654c95e2a1")
_SAFE_MODE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class SessionIdentity:
    """Upstream identity for one execution within an account-scoped conversation."""

    conversation_id: str
    root_conversation_id: str
    continuation_id: str


@dataclass
class _SessionTurns:
    expires_at: float
    root_session: str
    turns: OrderedDict = field(default_factory=OrderedDict)


class SessionRegistry:
    """Bounded, thread-safe, TTL-limited continuation IDs for explicit sessions."""

    def __init__(self, max_sessions: int = 1024, max_turns: int = 32, ttl: float = 3600) -> None:
        if max_sessions < 1 or max_turns < 1 or ttl <= 0:
            raise ValueError("Session registry limits must be positive")
        self.max_sessions, self.max_turns, self.ttl = max_sessions, max_turns, ttl
        self._sessions: OrderedDict = OrderedDict()
        self._lock = threading.RLock()

    def resolve(
        self, scope: str, session: str, root: Optional[str], turn: str,
        *, explicit_turn: bool = False,
    ) -> SessionIdentity:
        """Resolve stable conversation and turn IDs without storing message content."""
        with self._lock:
            now = time.monotonic()
            for key, entry in list(self._sessions.items()):
                if entry.expires_at <= now:
                    del self._sessions[key]
            key = (scope, session)
            entry = self._sessions.get(key)
            if entry is None:
                entry = _SessionTurns(now + self.ttl, root or session)
                self._sessions[key] = entry
            elif root is not None and root != entry.root_session:
                raise ValueError("The root session cannot change within an existing session; use a new session ID")
            entry.expires_at = now + self.ttl
            self._sessions.move_to_end(key)
            turn_key = (explicit_turn, turn)
            if turn_key not in entry.turns:
                entry.turns[turn_key] = (
                    str(uuid.uuid5(_SESSION_NAMESPACE, scope + "\0" + session + "\0turn\0" + turn))
                    if explicit_turn else str(uuid.uuid4())
                )
            entry.turns.move_to_end(turn_key)
            continuation = entry.turns[turn_key]
            while len(entry.turns) > self.max_turns:
                entry.turns.popitem(last=False)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return SessionIdentity(
                str(uuid.uuid5(_SESSION_NAMESPACE, scope + "\0" + session)),
                str(uuid.uuid5(_SESSION_NAMESPACE, scope + "\0" + entry.root_session)),
                continuation,
            )

    def clear(self) -> None:
        """Discard transient state, used during uninstall and isolated tests."""
        with self._lock:
            self._sessions.clear()


session_registry = SessionRegistry()


def _dump_message(message: Any) -> Dict[str, Any]:
    """Normalize only fields relevant to turn boundaries and history identity."""
    if hasattr(message, "model_dump"):
        message = message.model_dump(exclude_none=True)
    if isinstance(message, dict):
        return message
    return {"role": getattr(message, "role", ""), "content": getattr(message, "content", None)}


def _ordinary_user(message: Dict[str, Any]) -> bool:
    """Tool-only result envelopes continue a turn; a real user message starts one."""
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, list) and content:
        return any(
            (block.get("type") if isinstance(block, dict) else getattr(block, "type", None)) != "tool_result"
            for block in content
        )
    return not message.get("tool_results")


def turn_anchor(messages: List[Any]) -> str:
    """Find a turn within an explicit session, excluding trailing tool exchanges."""
    normalized = [_dump_message(message) for message in messages]
    position = next((i for i in range(len(normalized) - 1, -1, -1) if _ordinary_user(normalized[i])), None)
    if position is None:
        # Without a real user anchor there is no reliable cross-request binding.
        return str(uuid.uuid4())
    prefix = [item for item in normalized[:position + 1] if item.get("role") not in ("system", "developer")]
    encoded = json.dumps(prefix, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def request_identity(
    fallback_conversation_id: str, explicit_session: Optional[str], messages: List[Any],
    *, fallback_account: str = "",
) -> SessionIdentity:
    """Bind conversation/turn IDs to explicit client and selected account context.

    Anonymous requests do not enter the session registry. Retries of the same
    ASGI request still reuse their identity through the request-local state.
    """
    state = current_state()
    if state is not None and state.retry_budget is None:
        state = None
    session = (state.session_id if state is not None else None) or explicit_session
    account = (state.account_scope if state is not None else "") or fallback_account
    client = state.client_scope if state is not None else "standalone"
    scope = hashlib.sha256((client + "\0" + account).encode()).hexdigest()
    if state is not None and scope in state.execution_identities:
        return state.execution_identities[scope]
    anchor = turn_anchor(messages)
    if state is not None:
        state.input_turn_anchor = anchor
    recovered = state.recovered_reasoning_record if state is not None else None
    if session is None and recovered is not None:
        identity = SessionIdentity(
            recovered.conversation_id, recovered.root_conversation_id,
            recovered.continuation_id if anchor == recovered.turn_anchor else str(uuid.uuid4()),
        )
        state.execution_identities[scope] = identity
        return identity
    if session:
        turn = (state.turn_id if state is not None else None) or anchor
        root = state.root_session_id if state is not None else None
        identity = session_registry.resolve(scope, session, root, turn, explicit_turn=bool(state is not None and state.turn_id))
    else:
        base = state.anonymous_session_id if state is not None else fallback_conversation_id
        # An API request lacking session identity must never collide by content.
        conversation = str(uuid.uuid5(_SESSION_NAMESPACE, scope + "\0" + base)) if state is not None else base
        identity = SessionIdentity(conversation, conversation, str(uuid.uuid4()))
    if state is not None:
        state.execution_identities[scope] = identity
    return identity


def read_identity_headers(headers: List[Tuple[bytes, bytes]]) -> Dict[str, str]:
    """Validate optional gateway session/mode headers before payload conversion.

    Returns:
        Validated identity metadata and a one-way client credential namespace.

    Raises:
        ValueError: For duplicate, control-character, oversized or invalid headers.
    """
    names = {
        b"x-kiro-session-id": "session_id", b"x-kiro-root-session-id": "root_session_id",
        b"x-kiro-turn-id": "turn_id", b"x-kiro-agent-mode": "agent_mode",
        b"x-kiro-task-type": "task_type",
    }
    result: Dict[str, str] = {}
    credentials: List[Tuple[bytes, bytes]] = []
    for key, raw in headers:
        key = key.lower()
        if key == b"x-api-key":
            credentials.append((b"api-key", raw))
        elif key == b"authorization":
            scheme, _, value = raw.partition(b" ")
            credentials.append((b"api-key", value) if scheme.lower() == b"bearer" else (key, raw))
        if key not in names:
            continue
        field_name = names[key]
        if field_name in result:
            raise ValueError(f"Duplicate {key.decode()} header")
        value = raw.decode("latin-1")
        if not value or len(value) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError(f"{key.decode()} must contain 1-256 printable ASCII characters without whitespace")
        result[field_name] = value
    if "root_session_id" in result and "session_id" not in result:
        raise ValueError("x-kiro-root-session-id requires x-kiro-session-id")
    if "turn_id" in result and "session_id" not in result:
        raise ValueError("x-kiro-turn-id requires x-kiro-session-id")
    mode = result.get("agent_mode", "vibe")
    if not _SAFE_MODE.fullmatch(mode):
        raise ValueError("x-kiro-agent-mode must be a 1-64 character mode identifier")
    task = result.get("task_type", "spectask" if mode == "spec" else "vibe")
    if task not in ("vibe", "spectask"):
        raise ValueError("x-kiro-task-type must be vibe or spectask")
    credential = b"\0".join(key + b"\0" + value for key, value in sorted(set(credentials)))
    result.update(agent_mode=mode, task_type=task, client_scope=hashlib.sha256(credential).hexdigest())
    return result
