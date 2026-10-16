"""Native reasoning preservation and bounded, account/model-bound replay state.

Signatures and encrypted blocks are opaque, not gateway-generated signatures.
Only responses actually decoded by this gateway become replay evidence. Ordered
assistant blocks and complete projections are stored in an encrypted durable ledger;
RAM is a bounded accelerator, not the source of authority. Default evidence has no
time expiry. Missing provenance never permits another account's state to be used.
"""

from __future__ import annotations

import base64
import binascii
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Iterator

from kiro.native_replay_storage import ReplayStorage, ReplayStorageError, set_storage


class NativeReasoningError(ValueError):
    """Native reasoning is malformed or cannot be safely bound to this request."""


def normalize_delta(data: Any) -> dict[str, str]:
    """Validate event fields and normalize the SDK byte representation to base64."""
    if not isinstance(data, dict):
        raise NativeReasoningError("reasoningContentEvent must contain an object")
    result: dict[str, str] = {}
    for key in ("text", "signature"):
        if key in data:
            if not isinstance(data[key], str):
                raise NativeReasoningError(f"Native reasoning {key} must be a string")
            try:
                data[key].encode("utf-8")
            except UnicodeError as error:
                raise NativeReasoningError(f"Native reasoning {key} is not valid Unicode") from error
            result[key] = data[key]
    if "redactedContent" in data:
        value = data["redactedContent"]
        if isinstance(value, list) and all(type(item) is int and 0 <= item <= 255 for item in value):
            value = base64.b64encode(bytes(value)).decode("ascii")
        if not isinstance(value, str):
            raise NativeReasoningError("Opaque reasoning must be base64 or a byte array")
        try:
            base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise NativeReasoningError("Opaque reasoning is not valid base64") from error
        result["redactedContent"] = value
    if not result:
        raise NativeReasoningError("Native reasoning event has no supported fields")
    if "redactedContent" in result and any(k in result for k in ("text", "signature")):
        raise NativeReasoningError("Opaque and signed textual reasoning must be separate events")
    return result


def reasoning_blocks(content: Any, *, include_unsigned: bool = False) -> list[dict[str, str]]:
    """Extract canonical native blocks from Anthropic content/OpenAI details.

    Repeated indexes in OpenAI streaming deltas are assembled in order. Unsigned
    thinking text is displayed to clients but cannot be replayed as signed state.
    """
    if content is None:
        return []
    if not isinstance(content, list):
        return []
    result: list[dict[str, str]] = []
    indexes: dict[int, dict[str, str]] = {}
    for raw in content:
        block = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(block, dict) or block.get("type") not in ("thinking", "redacted_thinking"):
            continue
        index = block.get("index")
        if index is not None and (type(index) is not int or index < 0):
            raise NativeReasoningError("reasoning_details index must be a nonnegative integer")
        if block["type"] == "redacted_thinking":
            data = normalize_delta({"redactedContent": block.get("data")})["redactedContent"]
            result.append({"type": "redacted_thinking", "data": data})
        else:
            text, signature = block.get("thinking", ""), block.get("signature", "")
            normalize_delta({"text": text, "signature": signature})
            if index is not None and index in indexes:
                indexes[index]["thinking"] += text
                indexes[index]["signature"] += signature
            else:
                current = {"type": "thinking", "thinking": text, "signature": signature}
                result.append(current)
                if index is not None:
                    indexes[index] = current
    return [block for block in result if include_unsigned or (
        bool(block.get("data")) if block["type"] == "redacted_thinking"
        else bool(block.get("signature") and block.get("thinking"))
    )]


def tool_ids(tools: list[dict[str, Any]] | None) -> tuple[str, ...]:
    """Canonical tool identity set, independent of reversible name aliases."""
    return tuple(sorted(str(tool.get("id") or tool.get("toolUseId") or "") for tool in (tools or [])))


class NativeMessageLedger:
    """Maintain exact text/native/tool block ordering from unified upstream events."""

    def __init__(self) -> None:
        self.blocks: list[dict[str, Any]] = []
        self.has_native = False
        self._bytes = 0

    def feed(self, event: Any) -> int | None:
        """Append a unified event; return its reasoning block index when applicable."""
        if event.type == "content" and event.content:
            self._bytes += len(event.content.encode("utf-8"))
            if self._bytes > 16 * 1024 * 1024:
                raise NativeReasoningError("Assistant output exceeds the bounded native replay ledger")
            if self.blocks and self.blocks[-1]["type"] == "text":
                self.blocks[-1]["text"] += event.content
            else:
                self.blocks.append({"type": "text", "text": event.content})
        elif event.type == "native_reasoning":
            data = normalize_delta(event.reasoning or {})
            self._bytes += sum(len(value.encode("utf-8")) for value in data.values())
            if self._bytes > 16 * 1024 * 1024:
                raise NativeReasoningError("Reasoning output exceeds the bounded native replay ledger")
            self.has_native = True
            if "redactedContent" in data:
                self.blocks.append({"type": "redacted_thinking", "data": data["redactedContent"]})
            else:
                if not self.blocks or self.blocks[-1]["type"] != "thinking":
                    self.blocks.append({"type": "thinking", "thinking": "", "signature": ""})
                self.blocks[-1]["thinking"] += data.get("text", "")
                self.blocks[-1]["signature"] += data.get("signature", "")
            if len(self.blocks) > 4096:
                raise NativeReasoningError("Native response exceeds the bounded block count")
            return len(self.blocks) - 1
        elif event.type == "tool_use" and event.tool_use:
            tool = event.tool_use
            function = tool.get("function", {})
            arguments = function.get("arguments", tool.get("input", {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError as error:
                    raise NativeReasoningError("Tool arguments are incomplete; native history cannot be bound") from error
            self._bytes += len(json.dumps(arguments, ensure_ascii=True).encode("utf-8"))
            self.blocks.append({"type": "tool_use", "id": tool.get("id") or tool.get("toolUseId"),
                                "name": function.get("name", tool.get("name", "")), "input": arguments})
        if self._bytes > 16 * 1024 * 1024 or len(self.blocks) > 4096:
            raise NativeReasoningError("Assistant response exceeds the bounded replay ledger")
        return None


@dataclass(frozen=True)
class ReasoningRecord:
    """An ordered generated response bound to its origin, without credentials."""

    scope: tuple[str, str, str]
    conversation_id: str
    root_conversation_id: str
    continuation_id: str
    turn_anchor: str
    blocks: list[dict[str, Any]]
    expires_at: float
    size: int
    projections: dict[bool, "ProjectionReceipt"] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class ProjectionReceipt:
    """A complete gateway projection, sharing its original record's lifetime."""

    fingerprint: str
    results: list[dict[str, Any]]
    size: int


class ReasoningStore:
    """Bounded RAM cache over optional durable, non-expiring replay evidence.

    Args:
        max_records: RAM record budget; disk evidence is not evicted with RAM.
        max_bytes: RAM/individual response budget.
        ttl: Optional legacy memory-only expiry, never a production default.
        storage: Authenticated persistent ledger, configured at application startup.
    """

    def __init__(self, max_records: int = 512, max_bytes: int = 16 * 1024 * 1024,
                 ttl: float | None = None, storage: ReplayStorage | None = None) -> None:
        if max_records < 1 or max_bytes < 1 or (ttl is not None and ttl <= 0):
            raise ValueError("Reasoning store limits must be positive")
        if storage is not None and ttl is not None:
            raise ValueError("Durable native history must not use process-local TTLs")
        self.max_records, self.max_bytes, self.ttl = max_records, max_bytes, ttl
        self.storage = storage
        self._records: OrderedDict[str, ReasoningRecord] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def _expire(self) -> None:
        for key, record in list(self._records.items()):
            if record.expires_at <= time.monotonic():
                self._bytes -= record.size
                del self._records[key]

    def record(self, scope: tuple[str, str, str], identity: Any, anchor: str, ledger: NativeMessageLedger) -> None:
        """Register only actual native output, retaining exact bytes through JSON."""
        if not ledger.has_native or not reasoning_blocks(ledger.blocks):
            return
        encoded = json.dumps({"scope": scope, "identity": [identity.conversation_id, identity.root_conversation_id, identity.continuation_id], "anchor": anchor, "blocks": ledger.blocks}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise NativeReasoningError("Native response exceeds the bounded replay cache; reduce response size")
        record = ReasoningRecord(scope, identity.conversation_id, identity.root_conversation_id,
                                 identity.continuation_id, anchor, deepcopy(ledger.blocks),
                                 time.monotonic() + self.ttl if self.ttl is not None else float("inf"), len(encoded))
        with self._lock:
            if self.storage is not None:
                self.storage.put("record", self._record_key(record), self._serialize(record),
                                 lookup=self._native_key(scope, reasoning_blocks(record.blocks)))
            self._remember(record)

    def find(
        self, scope: tuple[str, str, str], text: str, tools: list[dict[str, Any]] | None,
        native: list[dict[str, str]],
    ) -> ReasoningRecord | None:
        """Validate client replay against generated content and tool identity.

        The scope contains client, account and normalized model. Multiple sessions
        are never inferred from a common prompt; only an actual signed/opaque
        response can supply a prior conversation identity to an anonymous client.
        """
        if not native:
            return None
        with self._lock:
            for record in self._candidates(scope, native):
                if record.scope != scope or reasoning_blocks(record.blocks) != native:
                    continue
                stored_text = "".join(block["text"] for block in record.blocks if block["type"] == "text")
                stored_tools = [block for block in record.blocks if block["type"] == "tool_use"]
                if stored_text != text or tool_ids(stored_tools) != tool_ids(tools):
                    continue
                self._remember(record)
                return deepcopy(record)
        raise NativeReasoningError(
            "Native reasoning cannot be verified for this client/account/model or message content. "
            "[native_history_unavailable] Keep the original account/model and unchanged assistant history. "
            "If this history predates durable replay or its storage was cleared, its proof cannot be recovered automatically."
        )

    def _record_key(self, record: ReasoningRecord) -> str:
        """Identify the original response independently of cache location/projections."""
        return record.record_id

    def _native_key(self, scope: tuple[str, str, str], native: Any) -> str:
        """Index native candidates only within the selected trusted scope."""
        assert self.storage is not None
        return self.storage.fingerprint("native", [scope, native])

    def _remember(self, record: ReasoningRecord) -> None:
        """Admit to the bounded accelerator; eviction never deletes disk evidence."""
        self._expire()
        key = self._record_key(record)
        previous = self._records.pop(key, None)
        self._bytes += record.size - (previous.size if previous else 0)
        self._records[key] = record
        while len(self._records) > self.max_records or self._bytes > self.max_bytes:
            _, expired = self._records.popitem(last=False)
            self._bytes -= expired.size

    @staticmethod
    def _serialize(record: ReasoningRecord) -> dict[str, Any]:
        """Persist original data, not monotonic deadlines or decrypted credentials."""
        value = asdict(record)
        value.pop("expires_at")
        value["projections"] = {str(int(api)): asdict(receipt) for api, receipt in record.projections.items()}
        return value

    @staticmethod
    def _deserialize(value: dict[str, Any]) -> ReasoningRecord:
        """Rehydrate authenticated data; malformed state is not a cache miss."""
        try:
            value = dict(value)
            value["scope"] = tuple(value["scope"])
            value["projections"] = {bool(int(api)): ProjectionReceipt(**receipt)
                                    for api, receipt in value["projections"].items()}
            return ReasoningRecord(**value, expires_at=float("inf"))
        except (KeyError, TypeError, ValueError) as error:
            raise ReplayStorageError("Native replay record schema is invalid; restore the original database") from error

    def _candidates(self, scope: tuple[str, str, str], native: Any) -> Iterator[ReasoningRecord]:
        """Search RAM first, then disk, including records evicted in another run."""
        self._expire()
        yield from reversed(list(self._records.values()))
        if self.storage is not None:
            for value in self.storage.find("record", self._native_key(scope, native)):
                yield self._deserialize(value)

    def record_projection(
        self, scope: tuple[str, str, str], identity: Any, anchor: str,
        ledger: NativeMessageLedger, exchanges: dict[int, dict[str, Any]], *, anthropic: bool, emitted: Any,
    ) -> None:
        """Attach a formatter receipt only to a completed, decoder-proven response.

        Args:
            scope: Managed client, selected account, and resolved upstream model.
            identity: Decoder response conversation identity, not client metadata.
            anchor: Original request turn anchor.
            ledger: The exact decoder ledger observed by the formatter.
            exchanges: Successful gateway emulations keyed by original block index.
            anthropic: Whether server blocks or flattened OpenAI text were emitted.
            emitted: Complete assistant content observed at the formatter output.

        Missing provenance produces no receipt. Complete receipts are durable;
        their RAM copies count against the same cache budget as native state.
        """
        if not exchanges or not ledger.has_native:
            return
        visible: list[dict[str, Any]] = []
        results = []
        for index, block in enumerate(ledger.blocks):
            exchange = exchanges.get(index)
            if exchange is None:
                visible.append(block)
                continue
            if block != exchange["original"] or block.get("type") != "tool_use":
                raise NativeReasoningError("Gateway projection no longer matches its original tool call")
            visible.extend(exchange["visible"])
            results.append({"id": block["id"], "content": exchange["result"]})
        if len(results) != len(exchanges):
            raise NativeReasoningError("Gateway projection has an invalid original block index")
        projected = visible if anthropic else _openai_projection(visible)
        fingerprint = _projection_fingerprint(projected)
        if fingerprint != _projection_fingerprint(emitted):
            # Unmodelled formatter additions cannot authorize a hypothetical replay.
            return
        size = len(_projection_json({"fingerprint": fingerprint, "results": results}).encode("utf-8"))
        receipt = ProjectionReceipt(fingerprint, deepcopy(results), size)
        with self._lock:
            for record in self._candidates(scope, reasoning_blocks(ledger.blocks)):
                if (record.scope != scope or record.blocks != ledger.blocks
                        or record.turn_anchor != anchor
                        or (record.conversation_id, record.root_conversation_id, record.continuation_id)
                        != (identity.conversation_id, identity.root_conversation_id, identity.continuation_id)):
                    continue
                previous = record.projections.get(anthropic)
                new_size = record.size + size - (previous.size if previous else 0)
                if new_size > self.max_bytes:
                    raise NativeReasoningError("Native projection exceeds the bounded replay cache")
                projections = {**record.projections, anthropic: receipt}
                updated = replace(record, size=new_size, projections=projections)
                if self.storage is not None:
                    key = self.storage.fingerprint("projection", [scope, anthropic, fingerprint])
                    self.storage.put("projection", key, self._serialize(updated))
                self._remember(updated)
                return

    def find_projection(
        self, scope: tuple[str, str, str], visible: Any, *, anthropic: bool,
    ) -> tuple[ReasoningRecord, ProjectionReceipt] | None:
        """Find an exact emitted projection in the selected trusted scope.

        Args:
            scope: Managed client/account/model scope.
            visible: Canonical protocol-specific assistant content.
            anthropic: Select the protocol receipt; receipts are not cross-protocol.

        Returns:
            Detached original state and receipt, or None when no proof matches.
        """
        fingerprint = _projection_fingerprint(visible)
        with self._lock:
            self._expire()
            for key, record in reversed(list(self._records.items())):
                receipt = record.projections.get(anthropic)
                if record.scope == scope and receipt is not None and receipt.fingerprint == fingerprint:
                    self._records.move_to_end(key)
                    return deepcopy((record, receipt))
            if self.storage is not None:
                key = self.storage.fingerprint("projection", [scope, anthropic, fingerprint])
                value = self.storage.get("projection", key)
                if value is not None:
                    record = self._deserialize(value)
                    receipt = record.projections.get(anthropic)
                    if record.scope != scope or receipt is None or receipt.fingerprint != fingerprint:
                        raise ReplayStorageError("Native replay projection identity does not match")
                    self._remember(record)
                    return deepcopy((record, receipt))
        return None

    def clear(self) -> None:
        """Clear RAM only; durable evidence is not destroyed on process shutdown."""
        with self._lock:
            self._records.clear()
            self._bytes = 0


reasoning_store = ReasoningStore()


def initialize_native_replay(state_file: str) -> None:
    """Configure encrypted replay before account initialization, without import I/O.

    Args:
        state_file: Existing application state path; the default private replay
            directory is adjacent to it. Explicit memory mode disables disk I/O.
    """
    mode = os.getenv("KIRO_NATIVE_REPLAY_MODE", "persistent").strip().lower()
    if mode not in ("persistent", "memory"):
        raise ValueError("KIRO_NATIVE_REPLAY_MODE must be persistent or memory")
    storage = None
    if mode == "persistent":
        directory = Path(os.getenv("KIRO_NATIVE_REPLAY_DIR") or (Path(state_file).absolute().parent / "native-replay"))
        budget = int(os.getenv("KIRO_NATIVE_REPLAY_MAX_BYTES", str(512 * 1024 * 1024)))
        storage = ReplayStorage(directory, max_bytes=budget)
    reasoning_store.clear()
    reasoning_store.storage = storage
    set_storage(storage)


def shutdown_native_replay() -> None:
    """Release process-local references without deleting resumable conversations."""
    reasoning_store.clear()
    reasoning_store.storage = None
    set_storage(None)


def expand_history(record: ReasoningRecord, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restore CLI-style ordered assistant entries with current reversible aliases."""
    by_id = {str(tool.get("toolUseId")): tool for tool in tools}
    entries = []
    for block in record.blocks:
        message: dict[str, Any] = {"content": ""}
        if block["type"] == "text":
            message["content"] = block["text"]
        elif block["type"] == "thinking":
            if not block.get("signature"):
                continue
            message["reasoningContent"] = {"reasoningText": {"text": block["thinking"], "signature": block["signature"]}}
        elif block["type"] == "redacted_thinking":
            message["reasoningContent"] = {"redactedContent": block["data"]}
        elif block["type"] == "tool_use":
            tool = by_id.get(str(block["id"]))
            if tool is None:
                raise NativeReasoningError("Tool pairing repair changed a signed assistant turn; its native reasoning cannot be replayed")
            message["toolUses"] = [tool]
        entries.append({"assistantResponseMessage": message})
    return entries


def _projection_json(value: Any) -> str:
    """Serialize proof values without Python's bool/int equality ambiguity."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError, UnicodeError) as error:
        raise NativeReasoningError("Native projection must contain valid JSON values") from error


def _projection_fingerprint(value: Any) -> str:
    """Hash the complete canonical projection, including native bytes and inputs."""
    return hashlib.sha256(_projection_json(value).encode("utf-8")).hexdigest()


def _plain_projection(value: Any) -> Any:
    """Convert request models to data without discarding their extra fields."""
    if hasattr(value, "model_dump"):
        return _plain_projection(value.model_dump())
    if isinstance(value, list):
        return [_plain_projection(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain_projection(item) for key, item in value.items()}
    return value


def _openai_projection(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Represent exactly the text, native details and remaining OpenAI tools."""
    return {
        "content": "".join(block["text"] for block in blocks if block["type"] == "text"),
        "reasoning_details": reasoning_blocks(blocks, include_unsigned=True),
        "tool_calls": [block for block in blocks if block["type"] == "tool_use"],
    }


def _openai_replay(message: dict[str, Any]) -> dict[str, Any]:
    """Normalize reversible OpenAI JSON arguments and reasoning delta indexes."""
    details = reasoning_blocks(message.get("reasoning_details"), include_unsigned=True)
    text = message.get("reasoning_content")
    if text not in (None, "", "".join(block.get("thinking", "") for block in details)):
        raise NativeReasoningError("Projected reasoning_content differs from its native details")
    tools = []
    for tool in message.get("tool_calls") or []:
        function = tool.get("function") or {}
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as error:
                raise NativeReasoningError("Projected tool arguments must be complete JSON") from error
        tools.append({"type": "tool_use", "id": tool.get("id"),
                      "name": function.get("name", ""), "input": arguments})
    return {"content": message.get("content") or "", "reasoning_details": details, "tool_calls": tools}


class NativeProjectionRecorder:
    """Request-local receipts for successful formatter-owned web-search emulation.

    Nothing is persisted until the decoder has recorded the completed native
    response. A cancelled/failed parse, absent managed context, or a non-native
    response cannot mint replay proof. The object is never read from request data.
    """

    def __init__(self, *, anthropic: bool) -> None:
        from extensions.request_context import current_state

        self._state = current_state()
        self._anthropic = anthropic
        self._ledger: NativeMessageLedger | None = None
        self._exchanges: dict[int, dict[str, Any]] = {}
        self._bytes = 0
        self._observed_bytes = 0
        self._observation_available = True
        self._blocks: dict[int, dict[str, Any]] = {}
        self._inputs: dict[int, str] = {}
        self._openai: dict[str, Any] = {"content": "", "reasoning_details": [], "tool_calls": []}

    def _observe_budget(self, event: dict[str, Any]) -> bool:
        """Bound output observation and skip calls without managed replay context."""
        if (not self._observation_available or self._state is None
                or not self._state.account_scope or self._state.wire_identity is None):
            return False
        try:
            self._observed_bytes += len(_projection_json(event).encode("utf-8"))
        except NativeReasoningError:
            self._discard_observation()
            return False
        if self._observed_bytes > reasoning_store.max_bytes:
            # Observation is optional, not a new limit on ordinary responses.
            # Never retain a partial fingerprint or authorize an unobserved tail.
            self._discard_observation()
            return False
        return True

    def _discard_observation(self) -> None:
        """Withdraw incomplete projection proof without altering ordinary output."""
        self._observation_available = False
        self._blocks.clear()
        self._inputs.clear()
        self._openai.clear()
        self._exchanges.clear()
        self._ledger = None

    def observe_anthropic(self, event: dict[str, Any]) -> None:
        """Assemble only content events actually yielded by the Anthropic formatter."""
        if not self._observe_budget(event):
            return
        kind, index = event["type"], event.get("index")
        if kind == "content_block_start":
            self._blocks[index] = deepcopy(event["content_block"])
        elif kind == "content_block_delta":
            delta = event["delta"]
            for field in ("text", "thinking", "signature"):
                if field in delta:
                    self._blocks[index][field] = self._blocks[index].get(field, "") + delta[field]
            if "partial_json" in delta:
                self._inputs[index] = self._inputs.get(index, "") + delta["partial_json"]
        elif kind == "content_block_stop" and index in self._inputs:
            self._blocks[index]["input"] = json.loads(self._inputs.pop(index))

    def observe_openai(self, chunk: dict[str, Any]) -> None:
        """Assemble content/native/tool deltas actually yielded by OpenAI formatting."""
        if not self._observe_budget(chunk):
            return
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            self._openai["content"] += delta.get("content") or ""
            self._openai["reasoning_details"].extend(deepcopy(delta.get("reasoning_details") or []))
            self._openai["tool_calls"].extend(deepcopy(delta.get("tool_calls") or []))

    def web_search(
        self, tool_id: str, server_tool_id: str, query: str, results: dict[str, Any], summary: str,
    ) -> None:
        """Record only a successfully emitted gateway search, never caller blocks.

        Args:
            tool_id: Original Kiro call ID at the decoder's current tool block.
            server_tool_id: ID actually returned by the gateway's MCP call.
            query: Query actually sent to MCP and displayed to the caller.
            results: Successful MCP result object (including an empty result set).
            summary: Exact text summary actually emitted by this formatter.
        """
        if not self._observation_available:
            return
        state = self._state
        ledger = getattr(state, "native_ledger", None)
        if not isinstance(ledger, NativeMessageLedger) or not ledger.blocks:
            return
        original = ledger.blocks[-1]
        if original.get("type") != "tool_use" or original.get("id") != tool_id or original.get("name") != "web_search":
            return
        if self._ledger is not None and self._ledger is not ledger:
            raise NativeReasoningError("Gateway projection crossed decoder response boundaries")
        self._ledger = ledger
        search_content = [{"type": "web_search_result", "title": item.get("title", ""),
                           "url": item.get("url", ""), "encrypted_content": item.get("snippet", ""),
                           "page_age": None} for item in results.get("results", [])]
        exchange = {
            "original": original,
            "visible": [
                {"type": "server_tool_use", "id": server_tool_id, "name": "web_search", "input": {"query": query}},
                {"type": "web_search_tool_result", "tool_use_id": server_tool_id, "content": search_content},
                {"type": "text", "text": summary},
            ],
            # Keep generated summaries outside the original signed assistant.
            "result": _projection_json({"result": results, "summary": summary}),
        }
        self._bytes += len(_projection_json(exchange).encode("utf-8"))
        if self._bytes > reasoning_store.max_bytes or len(self._exchanges) >= 4096:
            raise NativeReasoningError("Gateway projection exceeds the bounded receipt budget")
        self._exchanges[len(ledger.blocks) - 1] = deepcopy(exchange)

    def finish(self) -> None:
        """Bind the emitted projection to the decoder's completed scoped record."""
        state, ledger = self._state, self._ledger
        if (ledger is None or not self._exchanges or state is None
                or state.native_ledger is not ledger or state.wire_identity is None
                or not state.account_scope or not state.upstream_model_id):
            return
        reasoning_store.record_projection(
            (state.client_scope, state.account_scope, state.response_model_id or state.upstream_model_id),
            state.wire_identity, state.input_turn_anchor, ledger, self._exchanges, anthropic=self._anthropic,
            emitted=([self._blocks[index] for index in sorted(self._blocks)] if self._anthropic
                     else _openai_replay(self._openai)),
        )


def restore_native_projections(
    messages: list[Any], *, scope: tuple[str, str, str], anthropic: bool,
    store: ReasoningStore | None = None,
) -> list[Any]:
    """Restore verified gateway projections before normal history conversion.

    Args:
        messages: Protocol messages (dicts or Pydantic models); never mutated.
        scope: Trusted managed client/account/resolved-model tuple, NOT request metadata.
        anthropic: True for Anthropic blocks, False for OpenAI message fields.
        store: Optional isolated replay store for tests; defaults to reasoning_store.

    Returns:
        Messages in the same protocol/model representation. Each proven projection
        becomes the original native assistant plus generated tool-result messages,
        paired to ORIGINAL Kiro IDs. Results retain both MCP data and the exact
        displayed summary as JSON text. Caller text is unchanged. Adjacent Anthropic
        caller tool-result blocks are coalesced with generated results before normal
        conversion so orphan repair cannot sever their original tool pairings.
        No synthetic summary is appended to the signed assistant's original text.

    Raises:
        NativeReasoningError: Native projection proof is absent, altered, expired,
            evicted, or belongs to another client/account/model. Normal unprojected
            native messages still require their existing decoder proof. Root-session
            checks and ordinary native verification remain the parent's responsibility.
    """
    replay_store = store if store is not None else reasoning_store
    restored: list[Any] = []
    pending_results: int | None = None
    for message in messages:
        raw = _plain_projection(message)
        if pending_results is not None:
            # Orphan repair runs BEFORE ordinary adjacent-user merging. Keep
            # caller tool results beside generated results, directly after the
            # original assistant, without adding anything to its signed text.
            if (raw.get("role") == "user" and isinstance(raw.get("content"), list)
                    and any(block.get("type") == "tool_result" for block in raw["content"])):
                previous = _plain_projection(restored[pending_results])
                if any(previous[key] != raw[key] for key in previous.keys() & raw.keys()
                       if key not in ("role", "content")):
                    raise NativeReasoningError("Combine adjacent tool results into one user message; their message metadata conflicts")
                combined = {**previous, **raw, "content": previous["content"] + deepcopy(raw["content"])}
                restored[pending_results] = (type(message).model_validate(combined)
                                             if hasattr(message, "model_validate") else combined)
                continue
            pending_results = None
        if raw.get("role") != "assistant":
            restored.append(message)
            continue
        content = raw.get("content")
        native = reasoning_blocks(content if anthropic else raw.get("reasoning_details"))
        if not native:
            restored.append(message)
            continue
        visible = content if anthropic else _openai_replay(raw)
        found = replay_store.find_projection(scope, visible, anthropic=anthropic)
        if found is None:
            if anthropic and any(block.get("type") in ("server_tool_use", "web_search_tool_result") for block in content):
                raise NativeReasoningError("Native server-tool projection cannot be verified; keep unchanged history and its original account/model")
            ordinary = _openai_projection(content) if anthropic else visible
            replay_store.find(scope, ordinary["content"], ordinary["tool_calls"], native)
            restored.append(message)
            continue
        record, receipt = found
        if anthropic:
            updates = {"content": deepcopy(record.blocks)}
        else:
            updates = {
                "content": "".join(block["text"] for block in record.blocks if block["type"] == "text"),
                "reasoning_details": reasoning_blocks(record.blocks, include_unsigned=True),
                "tool_calls": [{"type": "function", "id": block["id"], "function": {
                    "name": block["name"], "arguments": _projection_json(block["input"]),
                }} for block in record.blocks if block["type"] == "tool_use"],
            }
        original_message = {**deepcopy(raw), **updates}
        restored.append(type(message).model_validate(original_message) if hasattr(message, "model_validate")
                        else original_message)
        result_messages = ([{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": result["id"], "content": result["content"]}
            for result in receipt.results
        ]}] if anthropic else [
            {"role": "tool", "tool_call_id": result["id"], "content": result["content"]}
            for result in receipt.results
        ])
        restored.extend(type(message).model_validate(result) if hasattr(message, "model_validate") else result
                        for result in result_messages)
        if anthropic:
            pending_results = len(restored) - 1
    return restored
