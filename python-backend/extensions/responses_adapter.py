"""Bounded, transport-free adapter for Kiro's upstream Responses dialect.

Evidence: shipped CLI 2.29.1 / @kiro/agent 0.66.33, acp-server.readable.js,
LF 362590-363265 (counted with split("\\n")). Request helpers are at
362619-362723; stream mappings at 363067-363265. The referenced reasoning
codec (362504-362534), MIME table (362574-362583), and effort readers
(127596-127623, disabled literal at 127753) were also inspected statically.
The CreateResponse operation/request schema (184984-184990, 184557-184579),
output-limit constants (184375, 184380), and adjacent ReasoningConfig
(184790-184800) were inspected for the gateway output-limit compatibility mapping.
No claim of runtime equivalence or general OpenAI API support is made.

Request contract:
* Only explicitly implemented fields are accepted; arbitrary JSON tool schemas
  and arguments are copied, never repaired. Unsupported generation parameters
  (including inferenceConfig, temperature and thinking budgets) still fail.
* Gateway compatibility mapping: additionalModelRequestFields.max_tokens becomes
  max_output_tokens, with a positive Python integer required (not bool/float),
  without coercion, clamping, defaults or silent dropping. CreateResponseRequest$
  models maxOutputTokens (EPa, 184375) with jsonName max_output_tokens (xPa,
  184380), paired at 184562/184571. This is operation-schema-backed support,
  NOT a claim that luo sends the field: luo/jHc at 362690-362723 omit it.
  Positive-integer validation is gateway policy; static schema evidence does
  not establish backend/model limits. Experimental protocol live-gating remains
  the parent's responsibility. No other adjacent schema fields are enabled.
* Source-established order: history then current; results before user content;
  assistant reasoning before text before calls. Only current tools are declared.
* Known Generate-only fields are validated and consumed, NOT sent to Responses:
  conversationState.chatTriggerType (MANUAL/DIAGNOSTIC/INLINE_CHAT), agentTaskType
  (vibe/spectask), and tool-result status (success/error). luo/WHc/uuo do not map
  these fields. Task type does not imply agentMode; error status does not inject
  is_error, text prefixes or invented cloud metadata. Result text stays unchanged.
* Per-message modelId/origin are local routing labels, not generation overrides:
  uuo omits them, and luo uses command routing. History labels may differ after
  a model switch. GHc ignores historical tool declarations; we validate their
  known shapes but only declare tools from the current message, as GHc does.
* The local-field enums are observed at LF 185548, 185587, 185646 (also in the
  second SDK copy at 437577, 437637, 437657). Generate construction at
  366660-366667 supplies task type and MANUAL before luo translation.
* Explicit empty content/mode/IDs are retained instead of JS truthiness filtering.
* Compatibility additions, NOT established by that source: model aliases modelId;
  current user modelId/origin supply defaults ONLY when command routing is absent.
  JSON base64 strings represent binary bytes (Python bytes/bytearray and integer
  byte lists are also accepted). Missing media bytes are errors, not silent loss.
* encode_reasoning_envelope/decode_reasoning_envelope implement L3r/ouo's JSON
  envelope: {"reasoningText":{"text":...,"signature":...}} OR
  {"redactedContent":BASE64}. The public helper input/output is the parent's
  flat canonical text/signature/redactedContent union. _reasoning bridges the
  request's SDK reasoningContent union to that codec, as HHc does.
* Provider-encrypted data remains opaque INSIDE redactedContent, including
  base64-encoded {id,encrypted_content} bytes recognized by L6e (362163-362177).
  We never unwrap/reinterpret these bytes or invent a different cloud contract.
  Codec round trips preserve text/signature/base64 data, not JSON whitespace.
  Standalone encryptedContent and undecodable/unknown cloud envelopes fail with
  actionable errors rather than emitting a field the parent would discard.

Stream contract (all returned envelopes are JSON serializable):
* feed(bytes) and finalize() return ordered lists; they perform no I/O.
* assistantResponseEvent(content), reasoningContentEvent(text/signature/
  redactedContent), toolUseEvent(toolUseId/name/input/stop),
  metadataEvent, contextUsageEvent, meteringEvent and codeReferenceEvent are used.
* Added compatibility mappings: full-text/tool snapshots fill ONLY missing
  suffixes. Reasoning summary events/parts stay in metadataEvent.upstreamEvent,
  NOT signed reasoning text (the source does not map summaries). Unknown
  application events/items and control events are retained there as well.
  SSE id/retry fields are retained as metadataEvent.sse; comments are ignored.
  When supplied, sequence_number must increase (no replay or reordering).
* Recognized signed envelopes produce canonical text/signature; source _uo emits
  signature after already-streamed text. Full signed-text snapshots also fill a
  missing suffix here, without replaying earlier parts. A differing signed text
  is an error, never permission to sign a summary or altered content.
  Redacted envelopes produce ONLY redactedContent BASE64 TEXT (the JSON-safe
  equivalent of source _uo's Buffer). Neither the decoder nor helpers emit
  standalone encryptedContent. Opaque and signed values remain separate events.
* Tool identity must precede argument deltas. Interleaving uses item_id and/or
  output_index, never a global last-tool pointer. Unidentified ambiguous deltas
  fail. The first arguments.done or output_item.done with complete JSON-object
  arguments emits one stop immediately in event order. Incomplete items never
  produce stops; malformed arguments declared complete are protocol errors.
  Later snapshots reconcile missing output but never repeat an emitted stop.
  Source _uo emits arguments.done stops at 363140-363146; its item-done-only
  path queues stops at 363149-363163 for terminal handling at 363205-363206.
  This adapter follows the integration contract's explicit normalization of BOTH
  validated done signals to immediate stops, not a claim that the source's
  item-done-only branch already does so. A tool stop is NOT response completion:
  later failed/incomplete/error or truncated EOF remains explicit. Terminal
  snapshots alone may close remaining valid calls only on response.completed.
* Only response.completed makes completed true. response.incomplete is terminal
  but NOT successful: metadata contains responseStatus and incompleteDetails;
  unknown reasons use INCOMPLETE rather than the source's misleading END_TURN.
  [DONE] is optional after a terminal response and is never proof of completion.
  EOF without a terminal event, partial UTF-8/JSON/SSE records, conflicting
  snapshots, and data after termination are errors, not successful empty streams.
* On an error, ResponsesStreamError.events contains the ordered outputs from
  THAT failing feed/finalize call only; previously returned outputs are not
  repeated. The parent should forward these before encoding the exception.
  Failure is sticky. finalize is idempotent on success; feed after finalize fails.
  Unknown upstream error categories use InternalServerException; raw error data
  stays in details, rather than inventing additional SDK exception mappings.

Default finite budgets: request 32 MiB / 100,000 nodes / depth 64; stream record
4 MiB, retained semantic state 16 MiB, wire stream 64 MiB, 1,024 items,
4,096 text parts and 100,000 records. JSON values also obey the depth/node
budgets above. CRLF counts as one delimiter in the record budget. Stream budgets
are constructor parameters.
Budgets bound retained buffers, not the caller-owned input or returned lists.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

__all__ = ["build_responses_payload", "ResponsesSSEDecoder", "ResponsesStreamError",
           "encode_reasoning_envelope", "decode_reasoning_envelope"]

MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_REQUEST_NODES = 100_000
MAX_REQUEST_DEPTH = 64
_DOCUMENT_MIME = {
    "pdf": "application/pdf", "csv": "text/csv", "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html", "txt": "text/plain", "md": "text/markdown",
}
_LINE_END = re.compile(b"[\r\n]")
_STOP_REASONS = {
    "max_output_tokens": "MAX_TOKENS", "content_filter": "CONTENT_FILTERED",
    "compaction_required_for_model_handoff": "COMPACTION_REQUIRED_FOR_MODEL_HANDOFF",
}


def _object(value: Any, path: str, allowed: set[str] | None = None) -> dict:
    """Validate an envelope and reject unsupported explicit fields at its path."""
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError(f"{path}: expected an object with string keys")
    if allowed is not None and (unknown := value.keys() - allowed):
        raise ValueError(f"{path}: unsupported explicit field(s): {', '.join(sorted(unknown))}; "
                         "no source-supported mapping; remove or handle explicitly before Responses translation")
    return value


def _text(value: Any, path: str, *, nonempty: bool = False) -> str:
    """Require a Unicode string without changing whitespace or opaque values."""
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError(f"{path}: expected {'nonempty ' if nonempty else ''}string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{path}: invalid Unicode surrogate") from exc
    return value


def _array(value: Any, path: str) -> list:
    """Require an explicit list rather than coercing nulls or iterables."""
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")
    return value


def _json(value: Any, path: str) -> str:
    """Encode strict compact JSON, rejecting values JSON cannot preserve."""
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"{path}: expected finite, acyclic JSON data") from exc


def _check_request_budget(value: Any) -> None:
    """Bound traversal before conversion, including cycles and binary content."""
    pending = [(value, 0)]
    nodes = size = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        size += 8  # Conservative structural overhead, also bounds empty containers.
        if nodes > MAX_REQUEST_NODES or depth > MAX_REQUEST_DEPTH:
            raise ValueError("command: request node/depth limit exceeded (or cyclic input)")
        if isinstance(item, (str, bytes, bytearray)):
            size += len(_text(item, "command").encode("utf-8")) if isinstance(item, str) else len(item)
        elif isinstance(item, (dict, list)):
            count = len(item) * (2 if isinstance(item, dict) else 1)
            if count + len(pending) + nodes > MAX_REQUEST_NODES:
                raise ValueError("command: request node limit exceeded")
            if isinstance(item, dict):
                for key, val in item.items():
                    _text(key, "command object key")
                    pending.extend(((key, depth + 1), (val, depth + 1)))
            else:
                pending.extend((val, depth + 1) for val in item)
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError("command: unsupported non-JSON value")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("command: non-finite number is not JSON")
        if size > MAX_REQUEST_BYTES:
            raise ValueError("command: request exceeds 32 MiB budget")


def _base64(value: Any, path: str) -> str:
    """Accept byte buffers, byte lists, or validated JSON base64 without guessing."""
    if isinstance(value, str):
        try:
            base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{path}: expected valid base64 text or bytes") from exc
        return value
    if isinstance(value, list):
        if any(type(v) is not int or not 0 <= v <= 255 for v in value):
            raise ValueError(f"{path}: byte arrays require integers in [0, 255]")
        value = bytes(value)
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{path}: expected bytes, byte array or base64 string")
    return base64.b64encode(value).decode("ascii")


def encode_reasoning_envelope(content: dict) -> str:
    """Encode canonical reasoning using the shipped L3r/HHc wire envelope.

    Args:
        content: Accumulated {text, signature?} or {redactedContent: base64/bytes}.
            A signature-only delta must first be accumulated with its exact text.

    Returns:
        Compact JSON for a Responses reasoning item's encrypted_content. Opaque
        provider bytes are base64-wrapped, never decoded or assigned new meaning.

    Raises:
        ValueError: Unsupported/mixed fields, missing text, invalid/empty base64,
            or an exceeded request budget. No standalone encryptedContent alias
            is accepted because it has no established canonical replay contract.
    """
    _check_request_budget(content)
    path = "reasoning envelope"
    obj = _object(content, path, {"text", "signature", "redactedContent"})
    if "redactedContent" in obj:
        if len(obj) != 1:
            raise ValueError(f"{path}: opaque redactedContent must be separate from text/signature")
        data = _base64(obj["redactedContent"], path + ".redactedContent")
        if not data:
            raise ValueError(f"{path}.redactedContent: nonempty base64 is required by the source codec")
        result = {"redactedContent": data}
    else:
        text = {"text": _text(obj.get("text"), path + ".text")}
        if "signature" in obj:
            text["signature"] = _text(obj["signature"], path + ".signature")
        result = {"reasoningText": text}
    encoded = _json(result, path)
    if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError(f"{path}: encoded reasoning exceeds the request byte budget")
    return encoded


def decode_reasoning_envelope(encrypted_content: str) -> dict[str, str]:
    """Decode the shipped ouo envelope to parent-compatible canonical fields.

    Args:
        encrypted_content: JSON string from a Responses reasoning output item.

    Returns:
        A detached {text, signature?} or {redactedContent: base64} dictionary.
        Pass accumulated canonical data to encode_reasoning_envelope to replay.

    Raises:
        ValueError: Malformed/unknown envelope or invalid canonical content. The
            source logs and drops undecodable envelopes; this adapter fails
            explicitly instead. It never fabricates signatures or repackages an
            unknown cloud string as a different provider-encrypted blob.
    """
    path = "Responses encrypted_content"
    value = _text(encrypted_content, path, nonempty=True)
    _check_request_budget(value)
    try:
        envelope = _object(_load_json(value), path, {"reasoningText", "redactedContent"})
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"{path}: unsupported reasoning envelope; expected JSON reasoningText "
                         "or base64 redactedContent, not standalone opaque encryptedContent") from exc
    if len(envelope) != 1:
        raise ValueError(f"{path}: exactly one reasoningText or redactedContent envelope is required")
    if "redactedContent" in envelope:
        data = _text(envelope["redactedContent"], path + ".redactedContent", nonempty=True)
        return {"redactedContent": _base64(data, path + ".redactedContent")}
    signed = _object(envelope["reasoningText"], path + ".reasoningText", {"text", "signature"})
    result = {"text": _text(signed.get("text"), path + ".reasoningText.text")}
    if "signature" in signed:
        result["signature"] = _text(signed["signature"], path + ".reasoningText.signature")
    return result


def _reasoning(value: Any, path: str) -> dict:
    """Bridge the SDK reasoningContent union to the source-established codec."""
    obj = _object(value, path, {"reasoningText", "redactedContent"})
    if len(obj) != 1:
        raise ValueError(f"{path}: exactly one reasoning representation is required")
    if "reasoningText" in obj:
        canonical = _object(obj["reasoningText"], path + ".reasoningText", {"text", "signature"})
    else:
        canonical = obj
    return {"type": "reasoning", "summary": [],
            "encrypted_content": encode_reasoning_envelope(canonical)}


def _consume_local_enum(obj: dict, key: str, values: set[str], path: str) -> None:
    """Validate a known Generate-only enum without inventing a Responses field."""
    if key in obj:
        value = _text(obj[key], path + "." + key)
        if value not in values:
            raise ValueError(f"{path}.{key}: unsupported protocol-local value; expected {', '.join(sorted(values))}")


def _media(value: Any, path: str, *, document: bool) -> dict:
    """Map bytes to source-established data URLs, retaining unknown document MIME."""
    allowed = {"format", "source", "name"} if document else {"format", "source"}
    obj = _object(value, path, allowed)
    fmt = _text(obj.get("format"), f"{path}.format", nonempty=True).lower()
    if not re.fullmatch(r"[a-z0-9.+-]+", fmt):
        raise ValueError(f"{path}.format: expected a file/image format, not a MIME type")
    src = _object(obj.get("source"), f"{path}.source", {"bytes"})
    if "bytes" not in src:
        raise ValueError(f"{path}.source.bytes: required; media must not be silently dropped")
    data = _base64(src["bytes"], f"{path}.source.bytes")
    if not document:
        return {"type": "input_image", "image_url": f"data:image/{fmt};base64,{data}"}
    name = _text(obj.get("name"), f"{path}.name")
    mime = _DOCUMENT_MIME.get(fmt, "application/octet-stream")
    return {"type": "input_file", "filename": f"{name}.{fmt}", "file_data": f"data:{mime};base64,{data}"}


def _message(value: Any, path: str, *, current: bool) -> tuple[list, list]:
    """Map a single Kiro message union; return ordered input items and declarations."""
    msg = _object(value, path, {"userInputMessage", "assistantResponseMessage"})
    if len(msg) != 1:
        raise ValueError(f"{path}: exactly one user or assistant message is required")
    items: list[dict] = []
    tools: list[dict] = []
    if "assistantResponseMessage" in msg:
        obj = _object(msg["assistantResponseMessage"], path + ".assistantResponseMessage",
                      {"content", "toolUses", "reasoningContent"})
        if "reasoningContent" in obj:
            items.append(_reasoning(obj["reasoningContent"], path + ".reasoningContent"))
        if "content" in obj:
            # Unlike JS truthiness filtering, an explicit empty message is retained.
            items.append({"role": "assistant", "content": _text(obj["content"], path + ".content")})
        for index, call in enumerate(_array(obj.get("toolUses", []), path + ".toolUses")):
            loc = f"{path}.toolUses[{index}]"
            call = _object(call, loc, {"toolUseId", "name", "input"})
            arguments = call.get("input", {})
            items.append({"type": "function_call",
                          "call_id": _text(call.get("toolUseId"), loc + ".toolUseId", nonempty=True),
                          "name": _text(call.get("name"), loc + ".name", nonempty=True),
                          "arguments": arguments if isinstance(arguments, str) else _json(arguments, loc + ".input")})
        return items, tools
    obj = _object(msg["userInputMessage"], path + ".userInputMessage",
                  {"content", "images", "documents", "userInputMessageContext", "modelId", "origin"})
    for key in ("modelId", "origin"):
        if key in obj:
            _text(obj[key], path + "." + key)  # uuo does not use per-message routing.
    context = _object(obj.get("userInputMessageContext", {}), path + ".userInputMessageContext",
                      {"tools", "toolResults"})
    for index, result in enumerate(_array(context.get("toolResults", []), path + ".toolResults")):
        loc = f"{path}.toolResults[{index}]"
        result = _object(result, loc, {"toolUseId", "content", "status"})
        _consume_local_enum(result, "status", {"success", "error"}, loc)
        chunks = []
        for part in _array(result.get("content"), loc + ".content"):
            part = _object(part, loc + ".content[]", {"text"})
            chunks.append(_text(part.get("text"), loc + ".content[].text"))
        items.append({"type": "function_call_output",
                      "call_id": _text(result.get("toolUseId"), loc + ".toolUseId", nonempty=True),
                      "output": "\n".join(chunks)})
    declarations = _array(context.get("tools", []), path + ".tools")
    for index, tool in enumerate(declarations):
        loc = f"{path}.tools[{index}]"
        tool = _object(tool, loc, {"toolSpecification"})
        spec = _object(tool.get("toolSpecification"), loc + ".toolSpecification", {"name", "description", "inputSchema"})
        schema = _object(spec.get("inputSchema"), loc + ".inputSchema", {"json"})
        if "json" not in schema:
            raise ValueError(f"{loc}.inputSchema.json: required")
        declared = {"type": "function", "name": _text(spec.get("name"), loc + ".name", nonempty=True),
                    "parameters": json.loads(_json(schema["json"], loc + ".inputSchema.json"))}
        if "description" in spec:
            declared["description"] = _text(spec["description"], loc + ".description")
        if current:  # GHc reads only currentMessage tools, not history snapshots.
            tools.append(declared)
    parts = []
    if "content" in obj:
        parts.append({"type": "input_text", "text": _text(obj["content"], path + ".content")})
    for field_name in ("images", "documents"):
        for index, media in enumerate(_array(obj.get(field_name, []), path + "." + field_name)):
            parts.append(_media(media, f"{path}.{field_name}[{index}]", document=field_name == "documents"))
    if parts:
        content = parts[0]["text"] if len(parts) == 1 and parts[0]["type"] == "input_text" else parts
        items.append({"role": "user", "content": content})
    return items, tools


def _additional_fields(value: Any) -> dict:
    """Map observed effort controls and the schema-backed output-limit alias.

    Args:
        value: additionalModelRequestFields with only the supported controls.

    Returns:
        Responses reasoning and/or max_output_tokens fields. The max_tokens
        alias is gateway compatibility backed by CreateResponseRequest$, not
        behavior attributed to luo. Supplied integer limits are kept exactly.

    Raises:
        ValueError: Unknown controls, invalid limits or conflicting effort.
            Thinking token budgets have no verified mapping and remain errors.
    """
    path = "command.additionalModelRequestFields"
    obj = _object(value, path, {"reasoning", "output_config", "thinking", "max_tokens"})
    result = {}
    if "max_tokens" in obj:
        limit = obj["max_tokens"]
        if type(limit) is not int or limit <= 0:
            raise ValueError(f"{path}.max_tokens: expected a positive integer; "
                             "coercion and clamping are not applied")
        result["max_output_tokens"] = limit
    efforts = []
    for key in ("output_config", "reasoning"):
        if key in obj:
            sub = _object(obj[key], path + "." + key, {"effort"})
            efforts.append(_text(sub.get("effort"), path + "." + key + ".effort", nonempty=True))
    if "thinking" in obj:
        sub = _object(obj["thinking"], path + ".thinking", {"type"})
        if sub.get("type") != "disabled":
            raise ValueError(f"{path}.thinking.type: only disabled has an established mapping")
        efforts.append("none")
    if len(set(efforts)) > 1:
        raise ValueError(f"{path}: conflicting reasoning effort settings")
    if efforts:
        result["reasoning"] = {"effort": efforts[0]}
    return result


def build_responses_payload(command: dict) -> dict:
    """Convert a finite supported Kiro command without mutation or I/O.

    Args:
        command: Kiro command with conversationState and modelId (or model).

    Returns:
        A detached JSON-compatible Responses request with stream=True.

    Raises:
        ValueError: Unsupported explicit field, conflicting routing, invalid data
            or exhausted request budget. Known Generate-only fields are consumed
            as documented; explicit generation controls are never silently dropped.
            No credentials/default profiles are read.
    """
    _check_request_budget(command)
    command = _object(command, "command", {"conversationState", "systemPrompt", "modelId", "model",
                                          "origin", "profileArn", "agentMode", "additionalModelRequestFields"})
    state = _object(command.get("conversationState"), "command.conversationState",
                    {"history", "currentMessage", "conversationId", "rootConversationId", "agentContinuationId",
                     "agentTaskType", "chatTriggerType"})
    _consume_local_enum(state, "agentTaskType", {"vibe", "spectask"}, "conversationState")
    _consume_local_enum(state, "chatTriggerType", {"MANUAL", "DIAGNOSTIC", "INLINE_CHAT"}, "conversationState")
    current = state.get("currentMessage", {})
    nested = current.get("userInputMessage", {}) if isinstance(current, dict) else {}
    nested = nested if isinstance(nested, dict) else {}
    model = _text(command.get("modelId", command.get("model", nested.get("modelId"))), "command.modelId/model", nonempty=True)
    if "model" in command and _text(command["model"], "command.model") != model:
        raise ValueError("command.model/modelId: conflicting model aliases")
    origin = command.get("origin", nested.get("origin"))
    if "origin" in command or "origin" in nested:
        origin = _text(origin, "command.origin")
    payload: dict[str, Any] = {"model": model, "input": [], "stream": True}
    if origin is not None:
        payload["origin"] = origin
    for source, dest in (("systemPrompt", "instructions"), ("profileArn", "profileArn")):
        if source in command:
            payload[dest] = _text(command[source], "command." + source)
    metadata = {}
    if "agentMode" in command:
        metadata["kiro:agent_mode"] = _text(command["agentMode"], "command.agentMode")
    for source, dest in (("conversationId", "conversation_id"), ("rootConversationId", "root_conversation_id"),
                         ("agentContinuationId", "agent_continuation_id")):
        if source in state:
            metadata["kiro:" + dest] = _text(state[source], "conversationState." + source)
    if metadata:
        payload["metadata"] = metadata
    for index, msg in enumerate(_array(state.get("history", []), "conversationState.history")):
        items, _ = _message(msg, f"conversationState.history[{index}]", current=False)
        payload["input"].extend(items)
    if "currentMessage" in state:
        items, tools = _message(state["currentMessage"], "conversationState.currentMessage", current=True)
        payload["input"].extend(items)
        if tools:
            payload["tools"] = tools
    if "additionalModelRequestFields" in command:
        payload.update(_additional_fields(command["additionalModelRequestFields"]))
    serialized = _json(payload, "payload")
    if len(serialized.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("payload: encoded request exceeds 32 MiB budget")
    return json.loads(serialized)


class ResponsesStreamError(ValueError):
    """Protocol/upstream failure ready for the parent's exception-frame encoder.

    Attributes:
        exception_type: Stable Kiro or adapter exception name.
        message: Actionable error description (payloads are never logged).
        details: Original upstream error record, or empty for parser failures.
        events: Outputs produced in the failing API call, in wire order.
    """

    def __init__(self, exception_type: str, message: str, *, details: dict | None = None) -> None:
        """Initialize an explicit failure with no implicit retry or stream closure."""
        super().__init__(message)
        self.exception_type = exception_type
        self.message = message
        self.details = details if details is not None else {}
        self.events: list[dict] = []


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    """Reject duplicate JSON keys instead of silently replacing opaque fields."""
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON object key")
        obj[key] = value
    return obj


def _invalid_constant(value: str) -> Any:
    """Reject non-standard JSON constants such as NaN and Infinity."""
    raise ValueError("non-finite JSON constant")


def _load_json(text: str) -> Any:
    """Read strict JSON without permissive duplicate-key or number conversion."""
    value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    _check_request_budget(value)  # Also rejects exponent overflow and lone surrogates.
    return value


@dataclass
class _TextState:
    """Retain only the emitted prefix needed to reconcile completed snapshots."""

    chunks: list[str] = field(default_factory=list)
    closed: bool = False


@dataclass
class _ItemState:
    """Correlate one output item independently of neighboring/interleaved items."""

    kind: str
    item_id: str | None = None
    index: int | None = None
    call_id: str | None = None
    name: str | None = None
    arguments: _TextState = field(default_factory=_TextState)
    started: bool = False
    done: bool = False
    incomplete: bool = False
    stopped: bool = False
    encrypted: str | None = None
    parts: dict[tuple[str, int], _TextState] = field(default_factory=dict)


class ResponsesSSEDecoder:
    """Incremental SSE-to-Kiro event decoder with explicit terminal semantics.

    Args:
        max_buffer_bytes: Maximum bytes in one SSE record, including comments.
        max_state_bytes: Maximum retained UTF-8 prefixes/identities/opaque strings.
        max_stream_bytes: Maximum cumulative wire bytes per decoder.
        max_items: Maximum correlated output items.
        max_parts: Maximum text/refusal/reasoning parts across all items.
        max_events: Maximum nonempty SSE data records.

    Raises:
        ValueError: A budget is not a positive integer.
        ResponsesStreamError: Invalid framing, data, lifecycle, exhausted limits,
            or explicit upstream failure. See module docstring for recovery.
    """

    def __init__(self, *, max_buffer_bytes: int = 4 * 1024 * 1024,
                 max_state_bytes: int = 16 * 1024 * 1024,
                 max_stream_bytes: int = 64 * 1024 * 1024,
                 max_items: int = 1024, max_parts: int = 4096,
                 max_events: int = 100_000) -> None:
        """Allocate empty per-stream state; no process-global state is changed."""
        for value in (max_buffer_bytes, max_state_bytes, max_stream_bytes, max_items, max_parts, max_events):
            if type(value) is not int or value <= 0:
                raise ValueError("Responses SSE budgets must be positive integers")
        self._max_buffer = max_buffer_bytes
        self._max_state = max_state_bytes
        self._max_wire = max_stream_bytes
        self._max_items = max_items
        self._max_parts = max_parts
        self._max_events = max_events
        self._line = bytearray()
        self._data: list[str] = []
        self._sse: dict[str, Any] = {}
        self._event_name: str | None = None
        self._record_bytes = self._wire_bytes = self._state_bytes = self._event_count = self._part_count = 0
        self._after_cr = False
        self._first_line = True
        self._items: list[_ItemState] = []
        self._aliases: dict[tuple[str, Any], _ItemState] = {}
        self._terminal: str | None = None
        self._response_id: str | None = None
        self._last_sequence: int | None = None
        self._done_marker = False
        self._finalized = False
        self._failure: ResponsesStreamError | None = None

    @property
    def completed(self) -> bool:
        """Whether response.completed was validated, not merely whether EOF arrived."""
        return self._terminal == "completed" and self._failure is None

    @property
    def terminal_status(self) -> str | None:
        """Return completed/incomplete/failed when observed, otherwise None."""
        return self._terminal

    @staticmethod
    def _fail(message: str, kind: str = "ResponsesProtocolError") -> None:
        """Raise a typed adapter failure without including untrusted payload text."""
        raise ResponsesStreamError(kind, message)

    def _retain(self, text: str) -> None:
        """Charge each newly retained string to the semantic-state budget."""
        self._state_bytes += len(text.encode("utf-8"))
        if self._state_bytes > self._max_state:
            self._fail("Responses retained-state byte limit exceeded", "ResponsesBufferLimitExceeded")

    def _remember_failure(self, exc: ResponsesStreamError, events: list[dict]) -> None:
        """Make failure sticky while exposing this call's already-produced outputs."""
        exc.events = events
        self._failure = exc
        logger.debug("Responses adapter stream failed: {}", exc.exception_type)

    def feed(self, chunk: bytes) -> list[dict]:
        """Consume arbitrary byte boundaries, including split UTF-8 and split CRLF.

        Args:
            chunk: The next bytes from the upstream body; empty chunks are valid.

        Returns:
            Kiro event envelopes in wire order, with no repeated completed text.

        Raises:
            ResponsesStreamError: Protocol/limit/upstream errors. Drain its events
                before reporting the exception if earlier records in this call
                already produced output. The decoder cannot be reused after error.
        """
        if self._failure is not None:
            raise self._failure
        events: list[dict] = []
        try:
            if self._finalized:
                self._fail("feed() called after finalize()")
            if not isinstance(chunk, bytes):
                self._fail("feed() requires bytes")
            self._wire_bytes += len(chunk)
            if self._wire_bytes > self._max_wire:
                self._fail("Responses total wire-byte limit exceeded", "ResponsesBufferLimitExceeded")
            pos = 0
            for match in _LINE_END.finditer(chunk):
                end = match.start()
                if self._after_cr:
                    self._after_cr = False
                    if end == pos and chunk[end] == 10:
                        pos = end + 1
                        continue
                self._append_line(chunk[pos:end])
                self._record_bytes += 1
                if self._record_bytes > self._max_buffer:
                    self._fail("Responses SSE record byte limit exceeded", "ResponsesBufferLimitExceeded")
                self._consume_line(events)
                self._after_cr = chunk[end] == 13
                pos = end + 1
            if pos < len(chunk):
                self._after_cr = False
                self._append_line(chunk[pos:])
        except ResponsesStreamError as exc:
            self._remember_failure(exc, events)
            raise
        except (ValueError, UnicodeError, RecursionError) as exc:
            failure = ResponsesStreamError("ResponsesProtocolError", f"Malformed Responses stream: {exc}")
            self._remember_failure(failure, events)
            raise failure from exc
        return events

    def _append_line(self, data: bytes) -> None:
        """Bound byte retention before extending an incomplete UTF-8 line."""
        self._record_bytes += len(data)
        if self._record_bytes > self._max_buffer:
            self._fail("Responses SSE record byte limit exceeded", "ResponsesBufferLimitExceeded")
        self._line.extend(data)

    def _consume_line(self, events: list[dict]) -> None:
        """Apply SSE line rules; only a blank line dispatches a complete record."""
        try:
            line = self._line.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ResponsesStreamError("ResponsesProtocolError", "Invalid UTF-8 in Responses SSE line") from exc
        self._line.clear()
        if self._first_line:
            line = line.removeprefix("\ufeff")
            self._first_line = False
        if not line:
            data = "\n".join(self._data)
            event_name, sse = self._event_name, self._sse
            self._data, self._sse, self._event_name = [], {}, None
            self._record_bytes = 0
            if sse:
                events.append({"metadataEvent": {"sse": sse}})
            if data:
                self._record(data, event_name, events)
            return
        if line.startswith(":"):
            return
        name, colon, value = line.partition(":")
        if colon and value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data.append(value)
        elif name == "event":
            self._event_name = value
        elif name == "id" and "\x00" not in value:
            self._sse["id"] = value
        elif name == "retry" and value and value.isascii() and value.isdecimal():
            # Preserve as text: no unbounded integer conversion of a transport hint.
            self._sse["retry"] = value
        # Other SSE transport fields are ignored by the SSE framing contract.

    def finalize(self) -> list[dict]:
        """Validate EOF; never synthesize success, a tool stop, or a partial record.

        Returns:
            An empty list after a fully framed completed/incomplete response.
            Repeated successful finalization is idempotent.

        Raises:
            ResponsesStreamError: Truncated UTF-8/SSE or missing terminal event;
                incomplete responses are explicit terminal metadata, not EOF errors.
        """
        if self._failure is not None:
            raise self._failure
        if self._finalized:
            return []
        try:
            if self._line or self._data or self._event_name is not None or self._sse:
                self._fail("EOF inside a Responses SSE record (missing blank-line delimiter or UTF-8 bytes)",
                           "ResponsesTruncatedStream")
            if self._terminal not in {"completed", "incomplete"}:
                self._fail("EOF before response.completed or response.incomplete", "ResponsesTruncatedStream")
            self._finalized = True
        except ResponsesStreamError as exc:
            self._remember_failure(exc, [])
            raise
        return []

    def _record(self, text: str, event_name: str | None, events: list[dict]) -> None:
        """Decode one completed JSON record and enforce terminal framing rules."""
        self._event_count += 1
        if self._event_count > self._max_events:
            self._fail("Responses SSE record count limit exceeded", "ResponsesBufferLimitExceeded")
        if text.strip() == "[DONE]":
            if self._terminal not in {"completed", "incomplete"}:
                self._fail("[DONE] before an explicit terminal response", "ResponsesTruncatedStream")
            if self._done_marker:
                self._fail("Duplicate Responses [DONE] marker")
            self._done_marker = True
            return
        if self._terminal is not None:
            self._fail("Responses data arrived after terminal response")
        try:
            obj = _object(_load_json(text), "SSE data")
        except (ValueError, RecursionError) as exc:
            raise ResponsesStreamError("ResponsesProtocolError", "Responses SSE data must be a strict JSON object") from exc
        kind = obj.get("type")
        if kind is None and event_name and event_name != "message":
            kind = event_name
        kind = _text(kind, "SSE type", nonempty=True)
        if event_name and event_name != "message" and event_name != kind:
            self._fail("SSE event name disagrees with JSON type")
        if "sequence_number" in obj:
            sequence = self._index(obj["sequence_number"], "sequence_number")
            if self._last_sequence is not None and sequence <= self._last_sequence:
                self._fail("Responses sequence_number repeated or went backwards")
            self._last_sequence = sequence
        start = len(events)
        self._dispatch(kind, obj, events)
        common = {"type", "sequence_number", "output_index", "item_id"}
        if kind in {"response.completed", "response.incomplete", "response.created", "response.in_progress", "response.queued"}:
            handled = common | {"response"}
        elif kind.startswith("response.output_item."):
            handled = common | {"item"}
        elif kind.startswith("response.function_call_arguments."):
            handled = common | {"arguments" if kind.endswith(".done") else "delta"}
        elif "_part." in kind:
            handled = common | {"part", "content_index", "summary_index"}
        elif kind == "kiro:code_reference.added":
            handled = common | {"annotations"}
        else:
            handled = common | {"content_index", "summary_index",
                                ("refusal" if kind == "response.refusal.done" else "text") if kind.endswith(".done") else "delta"}
        part = obj.get("part")
        extras = obj.keys() - handled or (isinstance(part, dict) and part.keys() - {"type", "text", "refusal"})
        if extras and not any(e.get("metadataEvent", {}).get("upstreamEvent") is obj for e in events[start:]):
            events.append({"metadataEvent": {"upstreamEvent": obj}})

    @staticmethod
    def _index(value: Any, path: str) -> int:
        """Validate a nonnegative item/part index without accepting booleans."""
        if type(value) is not int or value < 0:
            raise ValueError(f"{path}: expected nonnegative integer")
        return value

    def _item(self, event: dict, kind: str, item: dict | None = None) -> _ItemState:
        """Resolve explicit item identities, rejecting collisions and ambiguous deltas."""
        item = item if item is not None else {}
        aliases = []
        if "output_index" in event:
            aliases.append(("index", self._index(event["output_index"], "output_index")))
        for obj, key in ((event, "item_id"), (item, "id")):
            if key in obj:
                aliases.append(("id", _text(obj[key], key, nonempty=True)))
        if "call_id" in item:
            aliases.append(("call", _text(item["call_id"], "call_id", nonempty=True)))
        candidates = []
        for alias in aliases:
            candidate = self._aliases.get(alias)
            if candidate is not None and all(candidate is not seen for seen in candidates):
                candidates.append(candidate)
        if len(candidates) > 1:
            self._fail("Conflicting Responses output_index/item_id/call_id")
        if candidates:
            state = candidates[0]
        else:
            unkeyed = [state for state in self._items if state.kind == kind and state.item_id is None
                       and state.index is None and state.call_id is None]
            available = [state for state in self._items if state.kind == kind]
            if aliases and len(unkeyed) == 1:
                state = unkeyed[0]
            elif not aliases and len(available) == 1:
                state = available[0]
            elif not aliases and len(available) > 1:
                self._fail("Ambiguous Responses delta: include item_id or output_index")
            else:
                if kind == "function_call" and not item:
                    self._fail("Tool argument delta has no preceding function_call identity")
                if len(self._items) >= self._max_items:
                    self._fail("Responses output-item limit exceeded", "ResponsesBufferLimitExceeded")
                state = _ItemState(kind)
                self._items.append(state)
        if state.kind != kind:
            self._fail("Responses item changed output type")
        for alias in aliases:
            attr = {"index": "index", "id": "item_id", "call": "call_id"}[alias[0]]
            previous = getattr(state, attr)
            if previous is not None and previous != alias[1]:
                self._fail("Responses item identity changed")
            if alias not in self._aliases:
                self._retain(str(alias[1]))
                self._aliases[alias] = state
            setattr(state, attr, alias[1])
        return state

    def _part(self, item: _ItemState, channel: str, index: int) -> _TextState:
        """Allocate one bounded content part, preserving independent channel order."""
        key = (channel, index)
        if key not in item.parts:
            if self._part_count >= self._max_parts:
                self._fail("Responses text-part limit exceeded", "ResponsesBufferLimitExceeded")
            self._part_count += 1
            item.parts[key] = _TextState()
        return item.parts[key]

    def _append_text(self, state: _TextState, value: str, *, snapshot: bool, close: bool) -> str:
        """Reconcile a full snapshot with an emitted prefix, returning only its suffix."""
        if snapshot:
            prefix = "".join(state.chunks)
            state.chunks = [prefix] if prefix else []
            if not value.startswith(prefix):
                self._fail("Completed Responses content conflicts with previously emitted prefix")
            suffix = value[len(prefix):]
        else:
            suffix = value
        if state.closed and (suffix or not snapshot):
            self._fail("Responses delta/content changed after part completion")
        if suffix:
            self._retain(suffix)
            state.chunks.append(suffix)
        state.closed = state.closed or close
        return suffix

    def _text_event(self, item: _ItemState, channel: str, index: int, value: Any,
                    events: list[dict], *, snapshot: bool, close: bool = False) -> None:
        """Emit assistant or reasoning text with item-local snapshot deduplication."""
        value = _text(value, channel)
        if item.done and not snapshot:
            self._fail("Text delta arrived after output item completion")
        suffix = self._append_text(self._part(item, channel, index), value, snapshot=snapshot, close=close)
        if suffix:
            envelope, key = ("reasoningContentEvent", "text") if channel.startswith("reasoning") else ("assistantResponseEvent", "content")
            events.append({envelope: {key: suffix}})

    @staticmethod
    def _validate_tool_arguments(state: _ItemState) -> None:
        """Require a complete JSON object before any tool completion is emitted."""
        try:
            arguments = _load_json("".join(state.arguments.chunks))
        except (ValueError, RecursionError) as exc:
            raise ResponsesStreamError("ResponsesProtocolError", "Completed tool arguments are truncated or invalid JSON") from exc
        if not isinstance(arguments, dict):
            raise ResponsesStreamError("ResponsesProtocolError", "Completed function_call arguments must be a JSON object")

    def _emit_tool_stop(self, state: _ItemState, events: list[dict]) -> None:
        """Emit the first validated tool stop only; it does not complete the response."""
        if state.stopped or state.incomplete:
            return
        self._validate_tool_arguments(state)
        events.append({"toolUseEvent": {"toolUseId": state.call_id, "stop": True}})
        state.stopped = True

    def _tool(self, state: _ItemState, item: dict, events: list[dict], *, close: bool, emit_stop: bool) -> None:
        """Emit a tool declaration/snapshot without authorizing an incomplete call."""
        call_id = item.get("call_id", state.call_id or item.get("id"))
        name = item.get("name", state.name)
        call_id = _text(call_id, "function_call.call_id/id", nonempty=True)
        name = _text(name, "function_call.name", nonempty=True)
        if state.started and (call_id != state.call_id or name != state.name):
            self._fail("Responses tool identity/name changed")
        if not state.started:
            # An id-only call still gets a stable alias for later snapshots.
            alias = ("call", call_id)
            if alias in self._aliases and self._aliases[alias] is not state:
                self._fail("Duplicate Responses tool call_id")
            self._aliases[alias] = state
            self._retain(call_id + name)
            state.call_id, state.name, state.started = call_id, name, True
            initial = _text(item.get("arguments", ""), "function_call.arguments")
            self._append_text(state.arguments, initial, snapshot=True, close=close)
            events.append({"toolUseEvent": {"toolUseId": call_id, "name": name, "input": initial, "stop": False}})
        elif "arguments" in item:
            suffix = self._append_text(state.arguments, _text(item["arguments"], "function_call.arguments"), snapshot=True, close=close)
            if suffix:
                events.append({"toolUseEvent": {"toolUseId": call_id, "input": suffix, "stop": False}})
        state.incomplete = state.incomplete or item.get("status") == "incomplete"
        if close:
            state.done = True
            state.arguments.closed = True
            if emit_stop:
                self._emit_tool_stop(state, events)

    def _encrypted(self, state: _ItemState, value: Any, events: list[dict]) -> None:
        """Project the source envelope solely into parent-supported canonical fields."""
        value = _text(value, "reasoning.encrypted_content")
        if state.encrypted is not None:
            if value != state.encrypted and decode_reasoning_envelope(value) != decode_reasoning_envelope(state.encrypted):
                self._fail("Responses reasoning encrypted_content changed after emission")
            return
        canonical = decode_reasoning_envelope(value)
        self._retain(value)
        state.encrypted = value
        if "redactedContent" in canonical:
            events.append({"reasoningContentEvent": canonical})
            return
        plain = sorted((index, part) for (channel, index), part in state.parts.items()
                       if channel == "reasoning_text")
        if plain:
            prefix = "".join("".join(part.chunks) for _, part in plain)
            if not canonical["text"].startswith(prefix):
                self._fail("Signed reasoning conflicts with previously emitted text")
            suffix = canonical["text"][len(prefix):]
            if suffix:
                self._text_event(state, "reasoning_text", plain[-1][0], suffix,
                                 events, snapshot=False, close=True)
            for _, part in plain:
                part.closed = True
        else:
            self._text_event(state, "reasoning_text", 0, canonical["text"], events, snapshot=True, close=True)
        if "signature" in canonical:
            events.append({"reasoningContentEvent": {"signature": canonical["signature"]}})

    def _content_part(self, state: _ItemState, part: dict, index: int, events: list[dict], *, close: bool) -> bool:
        """Project a known content part; unknown parts require raw metadata retention."""
        kind = _text(part.get("type"), "content part.type", nonempty=True)
        mapping = {"output_text": ("output_text", "text"), "refusal": ("refusal", "refusal"),
                   "reasoning_text": ("reasoning_text", "text")}
        if kind not in mapping:
            return False
        if (state.kind == "reasoning") != (kind == "reasoning_text"):
            return False
        channel, key = mapping[kind]
        self._text_event(state, channel, index, part.get(key), events, snapshot=True, close=close)
        return True

    def _output_item(self, event: dict, item: dict, events: list[dict], *, close: bool, emit_tool_stop: bool = True) -> None:
        """Handle an added/done/final item, including full-output-only responses."""
        kind = _text(item.get("type"), "output item.type", nonempty=True)
        if kind not in {"function_call", "message", "reasoning"}:
            events.append({"metadataEvent": {"upstreamEvent": event}})
            return
        state = self._item(event, kind, item)
        if "status" in item:
            item_status = _text(item["status"], "output item.status")
            if item_status not in {"in_progress", "completed", "incomplete"}:
                self._fail("Unsupported Responses output item status")
            state.incomplete = state.incomplete or item_status == "incomplete"
        if kind == "message" and "role" in item and item["role"] != "assistant":
            self._fail("Responses output message role must be assistant")
        for field_name in ("content", "summary"):
            if field_name in item:
                _array(item[field_name], "output item." + field_name)
        needs_raw = False
        if kind == "function_call":
            self._tool(state, item, events, close=close, emit_stop=emit_tool_stop)
        else:
            for field_name in (("content", "summary") if kind == "reasoning" else ("content",)):
                if field_name in item:
                    for index, part in enumerate(_array(item[field_name], "output item." + field_name)):
                        if not self._content_part(state, _object(part, "content part"), index, events, close=close):
                            needs_raw = True
            if close and kind == "reasoning" and item.get("encrypted_content") is not None:
                self._encrypted(state, item["encrypted_content"], events)
            if close:
                state.done = True
                for part in state.parts.values():
                    part.closed = True
        # Preserve annotations and future item fields without replaying them as text.
        known = {"type", "id", "status"} | {
            "message": {"role", "content"},
            "reasoning": {"content", "summary", "encrypted_content"},
            "function_call": {"call_id", "name", "arguments"},
        }[kind]
        if needs_raw or (not close and "encrypted_content" in item) or item.keys() - known or any(isinstance(p, dict) and p.keys() - {"type", "text", "refusal"}
                                     for key in ("content", "summary") for p in item.get(key, [])):
            events.append({"metadataEvent": {"upstreamEvent": event}})

    def _upstream_error(self, event: dict, kind: str) -> None:
        """Map the finite source-observed error categories; retain all raw details."""
        error = event.get("error") if kind == "error" else _object(event.get("response"), "response.failed.response").get("error")
        if error is None:
            error = event if kind == "error" else {}
        error = _object(error, "upstream error")
        code = _text(error.get("code") if error.get("code") is not None else "", "upstream error.code")
        category = _text(error.get("type") if error.get("type") is not None else "", "upstream error.type").lower()
        message = _text(error.get("message", "Upstream Responses request failed"), "upstream error.message")
        if code == "rate_limit_exceeded" or category == "too_many_requests" or "throttl" in category:
            exception = "ThrottlingException"
        elif code == "credit_balance_exhausted" or category == "insufficient_quota" or "quota" in category:
            exception = "ServiceQuotaExceededException"
        elif code == "kiro:model_requires_user_opt_in":
            exception = "ValidationException"
        elif code == "access_denied" or "access" in category or "denied" in category:
            exception = "AccessDeniedException"
        elif code in {"context_length_exceeded", "model_not_found"} or code.startswith(("invalid_", "unsupported_", "missing_")) or category in {"invalid_request", "not_found"}:
            exception = "ValidationException"
        elif code == "server_is_overloaded" or "service_unavailable" in category:
            exception = "ServiceUnavailableException"
        else:
            exception = "InternalServerException"
        self._terminal = "failed"
        raise ResponsesStreamError(exception, message, details=event)

    def _terminal_response(self, kind: str, event: dict, events: list[dict]) -> None:
        """Fill missing output, close unstopped valid tools, and preserve response status."""
        response = _object(event.get("response"), kind + ".response")
        status = "incomplete" if kind == "response.incomplete" else "completed"
        if "status" in response and response["status"] != status:
            self._fail("Terminal Responses event disagrees with response.status")
        if "id" in response:
            response_id = _text(response["id"], "response.id", nonempty=True)
            if self._response_id is not None and self._response_id != response_id:
                self._fail("Responses response.id changed within stream")
            if self._response_id is None:
                self._retain(response_id)
            self._response_id = response_id
        if response.get("error") is not None:
            self._upstream_error({"type": "error", "error": response["error"]}, "error")
        for index, item in enumerate(_array(response.get("output", []), "response.output")):
            item = _object(item, "response.output[]")
            # A terminal snapshot is not a new independent item-done signal.
            # Validate the whole terminal record before synthesizing missing stops.
            self._output_item({"type": "response.output_item.done", "output_index": index, "item": item},
                              item, events, close=True, emit_tool_stop=False)
        terminal_events: list[dict] = []
        if status == "completed":
            for state in self._items:
                if state.incomplete:
                    self._fail("Completed response contains an incomplete tool/output item")
                if state.kind == "function_call":
                    self._validate_tool_arguments(state)
        details = response.get("incomplete_details", {})
        if details is None:
            details = {}
        details = _object(details, "response.incomplete_details")
        reason = details.get("reason")
        if reason is not None:
            reason = _text(reason, "response.incomplete_details.reason")
        stop = "END_TURN" if status == "completed" else _STOP_REASONS.get(reason, "INCOMPLETE")
        metadata: dict[str, Any] = {"stopReason": stop, "responseStatus": status, "upstreamEvent": event}
        if self._response_id is not None:
            metadata["responseId"] = self._response_id
        if status == "incomplete":
            metadata["incompleteDetails"] = details
        usage = response.get("usage")
        if usage is not None:
            usage = _object(usage, "response.usage")
            metadata["usage"] = usage
        terminal_events.append({"metadataEvent": metadata})
        if usage is not None:
            context = usage.get("kiro:context_usage_percentage")
            if context is not None:
                self._number(context, "context usage percentage")
                terminal_events.append({"contextUsageEvent": {"contextUsagePercentage": context}})
            credit = usage.get("kiro:credits")
            if credit is not None:
                credit = _object(credit, "kiro:credits")
                value = credit.get("value")
                self._number(value, "kiro:credits.value")
                metering = {"usage": value}
                for source, dest in (("unit", "unit"), ("unit_plural", "unitPlural")):
                    if source in credit:
                        metering[dest] = _text(credit[source], "kiro:credits." + source)
                terminal_events.append({"meteringEvent": metering})
        if status == "completed":
            for state in self._items:
                if state.kind == "function_call":
                    self._emit_tool_stop(state, events)
        events.extend(terminal_events)
        self._terminal = status
        logger.debug("Responses adapter terminal status: {}", status)

    @staticmethod
    def _number(value: Any, path: str) -> None:
        """Validate finite numeric usage without accepting booleans or coercion."""
        if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError(f"{path}: expected finite number")

    def _dispatch(self, kind: str, event: dict, events: list[dict]) -> None:
        """Dispatch only the bounded Responses event vocabulary; keep unknown data."""
        if kind in {"error", "response.failed"}:
            self._upstream_error(event, kind)
        elif kind in {"response.completed", "response.incomplete"}:
            self._terminal_response(kind, event, events)
        elif kind in {"response.created", "response.in_progress", "response.queued"}:
            response = _object(event.get("response"), kind + ".response")
            if "id" in response:
                response_id = _text(response["id"], "response.id", nonempty=True)
                if self._response_id is not None and self._response_id != response_id:
                    self._fail("Responses response.id changed within stream")
                if self._response_id is None:
                    self._retain(response_id)
                self._response_id = response_id
            events.append({"metadataEvent": {"upstreamEvent": event}})
        elif kind in {"response.output_item.added", "response.output_item.done"}:
            self._output_item(event, _object(event.get("item"), "output item"), events, close=kind.endswith(".done"))
        elif kind in {"response.function_call_arguments.delta", "response.function_call_arguments.done"}:
            state = self._item(event, "function_call")
            if not state.started:
                self._fail("Tool arguments require a preceding function_call declaration")
            snapshot = kind.endswith(".done")
            value = event.get("arguments", "".join(state.arguments.chunks)) if snapshot else event.get("delta")
            suffix = self._append_text(state.arguments, _text(value, "function_call arguments"), snapshot=snapshot, close=snapshot)
            if suffix:
                events.append({"toolUseEvent": {"toolUseId": state.call_id, "input": suffix, "stop": False}})
            if snapshot:
                self._emit_tool_stop(state, events)
        elif kind in {"response.content_part.added", "response.content_part.done", "response.reasoning_summary_part.added", "response.reasoning_summary_part.done"}:
            reasoning = "reasoning_summary" in kind
            state = self._item(event, "reasoning" if reasoning else "message")
            index = self._index(event.get("summary_index" if reasoning else "content_index", 0), "part index")
            if not self._content_part(state, _object(event.get("part"), "content part"), index, events, close=kind.endswith(".done")):
                events.append({"metadataEvent": {"upstreamEvent": event}})
        elif kind.startswith("response.") and kind.rsplit(".", 1)[-1] in {"delta", "done"} and kind.rsplit(".", 1)[0] in {
            "response.output_text", "response.refusal", "response.reasoning_text", "response.reasoning",
        }:
            channel = kind.split(".")[1]
            if channel == "reasoning":
                channel = "reasoning_text"
            reasoning = channel.startswith("reasoning")
            state = self._item(event, "reasoning" if reasoning else "message")
            index = self._index(event.get("content_index", 0), "part index")
            snapshot = kind.endswith(".done")
            field_name = ("refusal" if channel == "refusal" else "text") if snapshot else "delta"
            self._text_event(state, channel, index, event.get(field_name), events, snapshot=snapshot, close=snapshot)
        elif kind == "kiro:code_reference.added":
            references = []
            for annotation in _array(event.get("annotations"), "annotations"):
                annotation = _object(annotation, "annotation")
                if annotation.get("type", "kiro:code_reference") != "kiro:code_reference":
                    continue
                ref = {}
                for source, dest in (("license_name", "licenseName"), ("repository", "repository"), ("url", "url")):
                    if source in annotation:
                        ref[dest] = _text(annotation[source], "annotation." + source)
                if "recommendation_content_span" in annotation:
                    ref["recommendationContentSpan"] = _object(annotation["recommendation_content_span"], "recommendation_content_span")
                if ref:
                    references.append(ref)
            if references:
                events.append({"codeReferenceEvent": {"references": references}})
            events.append({"metadataEvent": {"upstreamEvent": event}})
        else:
            events.append({"metadataEvent": {"upstreamEvent": event}})
