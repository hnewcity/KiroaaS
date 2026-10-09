"""
Kiro payload building, ported from the kiro-gateway fork (61d9b68 + dc0fe43).

Runtime replacement for kiro.converters_core.build_kiro_payload and the helpers
it relies on, so kiro/ stays zero-diff. The function bodies below are the
fork's, unchanged except that upstream settings are read live from
kiro.converters_core. What changes on the wire:

- The system prompt goes into a dedicated leading history pair (user: system,
  assistant: "I will follow these instructions.") instead of being glued onto
  the first user message. The prefix stays byte-stable across turns, which is
  what upstream prompt caching keys on, and auto-trim never removes that pair.
- Tool JSON schemas are normalised to the strict subset Kiro accepts ($ref
  resolution, anyOf/oneOf/allOf collapse, type arrays, key whitelist).
- toolUse/toolResult pairing is repaired: duplicate results dropped, orphan
  results turned into text, toolUses without a result removed. Tools that only
  appear in history get placeholder specs.
- Trailing assistant messages (prefill) are dropped; Kiro does not support it.
- conversationState gets agentTaskType (spectask with tools, vibe otherwise)
  and a stable agentContinuationId derived from the conversationId.
- Top-level additionalModelRequestFields: output_config.effort + clamped
  max_tokens for Claude >= 4.6, reasoning.effort for GPT. The client's effort is
  passed through; KIRO_DEFAULT_CLAUDE_EFFORT / KIRO_DEFAULT_GPT_EFFORT otherwise.
- Fake reasoning (<thinking_mode> tags) is never injected into models with
  native reasoning (Claude >= 4.6, GPT): claude-opus-5.5 refuses those requests
  with CONTENT_FILTERED / REASONING_EXTRACTION. For older models tags are only
  injected when the client explicitly asks (FAKE_REASONING_MODE=explicit, the
  default), and the slow "take the time you need" instruction is gone.

Settings (env, all optional): FAKE_REASONING_MODE (explicit | always),
KIRO_ADDITIONAL_MODEL_FIELDS (true), KIRO_DEFAULT_CLAUDE_EFFORT (low),
KIRO_DEFAULT_GPT_EFFORT (high).

Install after tool_name_alias: its wrappers of convert_tools_to_kiro_format,
extract_tool_uses_from_message and validate_tool_names live in the
kiro.converters_core namespace, which the code below calls through at runtime.
"""

import hashlib
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

import kiro.converters_core as _core
from kiro.converters_core import (
    KiroPayloadResult,
    ThinkingConfig,
    UnifiedMessage,
    UnifiedTool,
    convert_images_to_kiro_format,
    convert_tool_results_to_kiro_format,
    ensure_alternating_roles,
    ensure_assistant_before_tool_results,
    ensure_first_message_is_user,
    extract_images_from_content,
    extract_text_content,
    extract_tool_results_from_content,
    get_truncation_recovery_system_addition,
    merge_adjacent_messages,
    normalize_message_roles,
    process_tools_with_long_descriptions,
    strip_all_tool_content,
)
from kiro.payload_guards import (
    PayloadTrimStats,
    _align_to_user_message,
    _repair_orphaned_tool_results,
    _strip_empty_tool_uses,
    check_payload_size,
)


# ==================================================================================================
# Settings
# ==================================================================================================

def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in ("true", "1", "yes")


# explicit (default): inject fake reasoning only when the client asks for thinking
# always: legacy behaviour, inject unless the client disables thinking
_FAKE_REASONING_MODE_RAW = os.getenv("FAKE_REASONING_MODE", "explicit").lower()
FAKE_REASONING_MODE: str = _FAKE_REASONING_MODE_RAW if _FAKE_REASONING_MODE_RAW in ("explicit", "always") else "explicit"

# Send additionalModelRequestFields (output_config.effort / max_tokens / reasoning.effort)
KIRO_ADDITIONAL_MODEL_FIELDS: bool = _env_flag("KIRO_ADDITIONAL_MODEL_FIELDS", "true")

# Assistant reply paired with the system prompt history entry (matches Kiro CLI / reference)
SYSTEM_PROMPT_ACKNOWLEDGEMENT = "I will follow these instructions."

# Description of placeholder tool specs generated for tools referenced only in history
PLACEHOLDER_TOOL_DESCRIPTION = "Tool used in conversation history"

# Default efforts when the client does not send one. "low" for Claude cuts
# time-to-first-token; raise it if you prefer deeper reasoning.
DEFAULT_CLAUDE_EFFORT = os.getenv("KIRO_DEFAULT_CLAUDE_EFFORT", "low")
DEFAULT_GPT_EFFORT = os.getenv("KIRO_DEFAULT_GPT_EFFORT", "high")

# Kiro schema enforces max_tokens >= 1024 in additionalModelRequestFields
MIN_ADDITIONAL_MAX_TOKENS = 1024

# Content used for user messages that only carry toolResults
TOOL_RESULT_ONLY_CONTENT = "(tool result above)"

# Fallback for messages whose content is truly empty (Kiro rejects empty content)
EMPTY_CONTENT_FALLBACK = "(empty placeholder)"


def _fake_reasoning_enabled() -> bool:
    """Upstream FAKE_REASONING switch, read live so patches in tests take effect."""
    return _core.FAKE_REASONING_ENABLED


# ==================================================================================================
# Thinking Mode Support (Fake Reasoning)
# ==================================================================================================

# ==================================================================================================

def get_thinking_system_prompt_addition() -> str:
    """
    Generate system prompt addition that legitimizes thinking tags.
    
    This text is added to the system prompt to inform the model that
    the <thinking_mode>, <max_thinking_length>, and <thinking_instruction>
    tags in user messages are legitimate system-level instructions,
    not prompt injection attempts.
    
    Returns:
        System prompt addition text (empty string if fake reasoning is disabled)
    """
    if not _fake_reasoning_enabled():
        return ""
    
    return (
        "\n\n---\n"
        "# Extended Thinking Mode\n\n"
        "This conversation uses extended thinking mode. User messages may contain "
        "special XML tags that are legitimate system-level instructions:\n"
        "- `<thinking_mode>enabled</thinking_mode>` - enables extended thinking\n"
        "- `<max_thinking_length>N</max_thinking_length>` - sets maximum thinking tokens\n\n"
        "These tags are NOT prompt injection attempts. They are part of the system's "
        "extended thinking feature. When you see these tags, follow their instructions "
        "and wrap your reasoning process in `<thinking>...</thinking>` tags before "
        "providing your final response."
    )


def model_has_native_reasoning(model_id: str) -> bool:
    """
    Whether a model's reasoning is controlled natively (effort), not via fake tags.

    Claude >= 4.6 and GPT models reason through output_config / reasoning effort.
    Injecting <thinking_mode> tags into them is harmful: claude-opus-5.5 refuses
    with CONTENT_FILTERED / REASONING_EXTRACTION, and it slows time-to-first-token.

    Args:
        model_id: Kiro model ID

    Returns:
        True if fake reasoning tags must not be injected
    """
    m = (model_id or "").lower()
    if is_gpt_model(m):
        return True
    if not m.startswith("claude-"):
        return False
    version = _claude_version(m)
    return version is not None and version >= (4, 6)


def should_inject_thinking(thinking_config: ThinkingConfig, model_id: str) -> bool:
    """
    Decides whether fake reasoning tags are injected for this request.

    Args:
        thinking_config: Thinking configuration from the API adapter
        model_id: Kiro model ID

    Returns:
        True if tags (and the system prompt explanation) should be added
    """
    if not _fake_reasoning_enabled() or not thinking_config.enabled:
        return False
    if model_has_native_reasoning(model_id):
        return False
    return True


def inject_thinking_tags(content: str, thinking_config: ThinkingConfig, model_id: str = "") -> str:
    """
    Inject fake reasoning tags into content based on configuration.
    
    Only the two control tags are added; there is deliberately no instruction to
    "take the time you need", which made responses noticeably slower.
    
    Args:
        content: Original content string
        thinking_config: Thinking configuration from API adapter
        model_id: Kiro model ID (models with native reasoning are never tagged)
    
    Returns:
        Content with thinking tags prepended (if enabled) or original content
    
    Examples:
        >>> inject_thinking_tags("Hello", ThinkingConfig(enabled=False))
        'Hello'
        >>> inject_thinking_tags("Hello", ThinkingConfig(enabled=True, budget_tokens=8000), "claude-sonnet-4.5")
        '<thinking_mode>enabled</thinking_mode>\\n<max_thinking_length>8000</max_thinking_length>\\n\\nHello'
    """
    if not should_inject_thinking(thinking_config, model_id):
        return content
    
    # Determine effective budget
    if thinking_config.budget_tokens is not None:
        effective_budget = thinking_config.budget_tokens
    else:
        effective_budget = _core.FAKE_REASONING_MAX_TOKENS
    
    # Apply cap if enabled
    if _core.FAKE_REASONING_BUDGET_CAP > 0 and effective_budget > _core.FAKE_REASONING_BUDGET_CAP:
        logger.warning(
            f"Client requested thinking budget {effective_budget} exceeds cap {_core.FAKE_REASONING_BUDGET_CAP}, "
            f"using capped value"
        )
        effective_budget = _core.FAKE_REASONING_BUDGET_CAP
    
    thinking_prefix = (
        f"<thinking_mode>enabled</thinking_mode>\n"
        f"<max_thinking_length>{effective_budget}</max_thinking_length>\n\n"
    )
    
    logger.debug(f"Injecting thinking tags with budget={effective_budget}")
    
    return thinking_prefix + content


# ==================================================================================================
# JSON Schema Sanitization
# ==================================================================================================

_SCHEMA_BASIC_TYPES = ("object", "array", "string", "number", "integer", "boolean")
_SCHEMA_MAX_REF_DEPTH = 16
_SCHEMA_DESCRIPTION_MAX_CHARS = 2000
_SCHEMA_COMBINATOR_KEYS = ("anyOf", "oneOf", "allOf")


def _extract_schema_defs(schema: Any) -> Dict[str, Any]:
    """
    Collect top-level `$defs` / `definitions` as the `$ref` resolution table.

    Args:
        schema: Root JSON Schema

    Returns:
        Mapping of definition name to schema
    """
    defs: Dict[str, Any] = {}
    if isinstance(schema, dict):
        for key in ("$defs", "definitions"):
            table = schema.get(key)
            if isinstance(table, dict):
                defs.update(table)
    return defs


def _resolve_schema_refs(value: Any, defs: Dict[str, Any], depth: int) -> Any:
    """
    Recursively inline `#/$defs/<name>` and `#/definitions/<name>` references.

    Sibling keys next to `$ref` (e.g. description) win over the target's keys.
    Unresolvable refs (external URLs, OpenAPI paths, missing defs) and refs beyond
    the depth limit (cycles) degrade to a permissive object schema.

    Args:
        value: Schema node
        defs: Definition table from the root schema
        depth: Current `$ref` expansion depth

    Returns:
        Schema node without `$ref`
    """
    if depth > _SCHEMA_MAX_REF_DEPTH:
        return {"type": "object"}

    if isinstance(value, list):
        return [_resolve_schema_refs(item, defs, depth) for item in value]
    if not isinstance(value, dict):
        return value

    obj = dict(value)
    ref = obj.pop("$ref", None)
    if isinstance(ref, str):
        name: Optional[str] = None
        for prefix in ("#/$defs/", "#/definitions/"):
            if ref.startswith(prefix):
                name = ref[len(prefix):]
                break
        target = defs.get(name) if name is not None else None
        if isinstance(target, dict):
            resolved = _resolve_schema_refs(target, defs, depth + 1)
            if isinstance(resolved, dict):
                for key, val in resolved.items():
                    obj.setdefault(key, val)
        else:
            logger.debug(f"Unresolvable $ref in tool schema, degrading to permissive object: {ref}")
            obj.setdefault("type", "object")

    return {key: _resolve_schema_refs(val, defs, depth) for key, val in obj.items()}


def _normalize_schema_type(raw: Any) -> Optional[str]:
    """
    Normalize a JSON Schema `type` value to a single basic type.

    Args:
        raw: `type` value (string or list of strings)

    Returns:
        Basic type name, or None if no supported type is present
    """
    candidates = raw if isinstance(raw, list) else [raw]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip() in _SCHEMA_BASIC_TYPES:
            return candidate.strip()
    return None


def _collapse_schema_combinators(obj: Dict[str, Any]) -> None:
    """
    Remove anyOf/oneOf/allOf, keeping the single real branch when there is one.

    Kiro rejects combinator schemas, so the reference drops them. As a strict
    superset, when a combinator has exactly one non-null branch (the common
    pydantic `Optional[X]` / `allOf: [{$ref}]` shapes) that branch's keys are
    merged in (existing keys win) so the constraint is not lost.

    Args:
        obj: Schema object (mutated in place)
    """
    for key in _SCHEMA_COMBINATOR_KEYS:
        variants = obj.pop(key, None)
        if not isinstance(variants, list):
            continue
        branches = [
            v for v in variants
            if isinstance(v, dict) and v.get("type") != "null"
        ]
        if len(branches) == 1:
            for branch_key, branch_value in branches[0].items():
                if branch_key not in _SCHEMA_COMBINATOR_KEYS:
                    obj.setdefault(branch_key, branch_value)


def _normalize_schema_node(schema: Any, root: bool) -> Dict[str, Any]:
    """
    Normalize one schema node into the strict subset Kiro accepts.

    Args:
        schema: Schema node (refs already resolved)
        root: Whether this is the root (always an object schema)

    Returns:
        Normalized schema with only type/properties/required/items/description/enum
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    obj = {key: val for key, val in schema.items() if val is not None}
    _collapse_schema_combinators(obj)
    obj = {key: val for key, val in obj.items() if val is not None}

    normalized_type = _normalize_schema_type(obj.get("type"))
    is_object = root or normalized_type == "object" or (
        normalized_type is None and "properties" in obj
    )

    result: Dict[str, Any] = {}
    if is_object:
        result["type"] = "object"
    elif normalized_type:
        result["type"] = normalized_type

    if is_object:
        raw_props = obj.get("properties")
        properties: Dict[str, Any] = {}
        if isinstance(raw_props, dict):
            for prop_name, prop_schema in raw_props.items():
                properties[str(prop_name)] = _normalize_schema_node(prop_schema, False)
        result["properties"] = properties

        raw_required = obj.get("required")
        required: List[str] = []
        if isinstance(raw_required, list):
            for name in raw_required:
                if isinstance(name, str) and name in properties and name not in required:
                    required.append(name)
        # Kiro rejects empty required arrays - only emit when non-empty
        if required:
            result["required"] = required

    items = obj.get("items")
    if isinstance(items, list):
        first = next((item for item in items if isinstance(item, dict)), None)
        if first is not None:
            result["items"] = _normalize_schema_node(first, False)
    elif isinstance(items, dict):
        result["items"] = _normalize_schema_node(items, False)

    description = obj.get("description")
    if isinstance(description, str):
        result["description"] = description[:_SCHEMA_DESCRIPTION_MAX_CHARS]

    enum_values = obj.get("enum")
    if isinstance(enum_values, list):
        scalars = [v for v in enum_values if isinstance(v, (str, int, float, bool))]
        if scalars:
            result["enum"] = scalars

    # additionalProperties and all other keywords are dropped (Kiro strict mode)
    return result


def sanitize_json_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Normalizes a tool JSON Schema into the strict subset the Kiro API accepts.

    Kiro returns 400 "Improperly formed request" for many valid JSON Schemas.
    Port of kiro2cc-proxy schema.rs:
    - `$ref` resolved against `$defs`/`definitions` (depth limit 16); unresolvable
      refs become a permissive object; `$defs`/`definitions` dropped
    - null values stripped; `type` arrays reduced to the first non-null basic type
    - object schemas always get a dict `properties`; `required` keeps only strings
      that exist in `properties` and is omitted when empty
    - `items` must be a schema (first schema of a tuple list)
    - anyOf/oneOf/allOf removed (single non-null branch merged in)
    - keys whitelisted to type/properties/required/items/description/enum
      (so `additionalProperties` is always dropped)
    - the root is always an object schema

    Args:
        schema: JSON Schema to sanitize

    Returns:
        Sanitized copy of schema (never mutates the input)
    """
    defs = _extract_schema_defs(schema)
    resolved = _resolve_schema_refs(schema if schema is not None else {}, defs, 0)
    return _normalize_schema_node(resolved, True)



# ==================================================================================================
# toolUse/toolResult Pairing and Trimming (kiro/payload_guards.py in the fork)
# ==================================================================================================

def _tool_result_text(tool_result: Dict[str, Any]) -> str:
    """
    Extract plain text from a Kiro-format toolResult.

    Args:
        tool_result: Kiro toolResult ({"content": [{"text": ...}], "toolUseId": ...})

    Returns:
        Concatenated text content (may be empty)
    """
    content = tool_result.get("content")
    parts: List[str] = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                parts.append(str(part["text"]))
    elif isinstance(content, str) and content:
        parts.append(content)
    return "\n".join(parts)


def _orphan_results_to_text(tool_results: List[Dict[str, Any]]) -> str:
    """
    Render orphaned toolResults as text so their context is not lost.

    Uses the same "[Tool Result (id)]" format as converters_core.tool_results_to_text.

    Args:
        tool_results: Orphaned Kiro-format toolResults

    Returns:
        Text representation (empty string if nothing to render)
    """
    parts = []
    for tr in tool_results:
        text = _tool_result_text(tr) or "(empty result)"
        tool_use_id = tr.get("toolUseId", "")
        header = f"[Tool Result ({tool_use_id})]" if tool_use_id else "[Tool Result]"
        parts.append(f"{header}\n{text}")
    return "\n\n".join(parts)


def _tool_use_ids(entry: Optional[Dict[str, Any]]) -> Set[str]:
    """
    Collect toolUseIds of an assistant history entry.

    Args:
        entry: History entry (any role) or None

    Returns:
        Set of toolUseIds (empty if the entry is not an assistant message)
    """
    ids: Set[str] = set()
    if not entry:
        return ids
    assistant = entry.get("assistantResponseMessage")
    if not assistant:
        return ids
    for tu in assistant.get("toolUses") or []:
        tool_use_id = tu.get("toolUseId") if isinstance(tu, dict) else None
        if tool_use_id:
            ids.add(tool_use_id)
    return ids


def _filter_tool_results(
    tool_results: List[Dict[str, Any]],
    valid_ids: Set[str],
    answered_ids: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Split toolResults into kept and orphaned, dropping duplicates.

    Args:
        tool_results: Kiro-format toolResults of one user message
        valid_ids: toolUseIds of the immediately preceding assistant message
        answered_ids: toolUseIds already answered (mutated: kept ids are added)

    Returns:
        Tuple of (kept results, orphaned results). Duplicates are in neither.
    """
    kept: List[Dict[str, Any]] = []
    orphaned: List[Dict[str, Any]] = []
    for tr in tool_results:
        tool_use_id = tr.get("toolUseId")
        if tool_use_id in answered_ids:
            logger.warning(f"Dropping duplicate toolResult for already answered toolUseId={tool_use_id}")
        elif tool_use_id in valid_ids:
            kept.append(tr)
            answered_ids.add(tool_use_id)
        else:
            logger.warning(f"Converting orphaned toolResult to text (no matching toolUse): toolUseId={tool_use_id}")
            orphaned.append(tr)
    return kept, orphaned


def repair_tool_pairing(
    history: List[Dict[str, Any]],
    current_tool_results: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Enforce Kiro toolUse/toolResult pairing on an assembled history (in place).

    Rules (reference: kiro2cc-proxy tools.rs validate_tool_pairing /
    remove_orphaned_tool_uses):
    - duplicate toolResults (toolUseId already answered) are dropped
    - orphaned toolResults (toolUseId not in the immediately preceding assistant
      message) are converted to text instead of silently dropped, so the model
      keeps their content
    - toolUses that never receive a toolResult (in history or in the current
      message) are removed from their assistant message

    Args:
        history: Kiro-format history entries (mutated in place)
        current_tool_results: Kiro-format toolResults of the current message,
            which may answer the toolUses of the last history entry

    Returns:
        Tuple of (kept current toolResults, text of orphaned current toolResults)
    """
    answered_ids: Set[str] = set()

    for i, entry in enumerate(history):
        user_msg = entry.get("userInputMessage")
        if not user_msg:
            continue
        ctx = user_msg.get("userInputMessageContext")
        if not ctx or not ctx.get("toolResults"):
            continue

        valid_ids = _tool_use_ids(history[i - 1]) if i > 0 else set()
        original = ctx["toolResults"]
        kept, orphaned = _filter_tool_results(original, valid_ids, answered_ids)
        if len(kept) == len(original):
            continue

        if kept:
            ctx["toolResults"] = kept
        else:
            del ctx["toolResults"]
            if not ctx:
                del user_msg["userInputMessageContext"]

        orphan_text = _orphan_results_to_text(orphaned)
        content = user_msg.get("content", "")
        if content == TOOL_RESULT_ONLY_CONTENT and not kept:
            # Message no longer carries results; replace the "results above" hint
            user_msg["content"] = orphan_text or EMPTY_CONTENT_FALLBACK
        elif orphan_text:
            user_msg["content"] = f"{content}\n\n{orphan_text}" if content else orphan_text

    kept_current: List[Dict[str, Any]] = []
    current_orphan_text = ""
    if current_tool_results:
        last_ids = _tool_use_ids(history[-1]) if history else set()
        kept_current, orphaned = _filter_tool_results(current_tool_results, last_ids, answered_ids)
        current_orphan_text = _orphan_results_to_text(orphaned)

    # Remove toolUses that never got a result
    removed = 0
    for entry in history:
        assistant = entry.get("assistantResponseMessage")
        if not assistant or not assistant.get("toolUses"):
            continue
        tool_uses = assistant["toolUses"]
        remaining = [tu for tu in tool_uses if tu.get("toolUseId") in answered_ids]
        if len(remaining) == len(tool_uses):
            continue
        removed += len(tool_uses) - len(remaining)
        if remaining:
            assistant["toolUses"] = remaining
        else:
            del assistant["toolUses"]
            if not str(assistant.get("content", "")).strip():
                assistant["content"] = EMPTY_CONTENT_FALLBACK
    if removed:
        logger.warning(f"Removed {removed} toolUse(s) without matching toolResult from history")

    return kept_current, current_orphan_text


def trim_payload_to_limit(
    payload: Dict[str, Any],
    max_bytes: int,
    keep_prefix_entries: int = 0,
) -> PayloadTrimStats:
    """
    Trim oldest history entries so the serialized payload fits under max_bytes.

    Trims in user/assistant pairs (2 entries at a time), aligns start to
    userInputMessage, and repairs orphaned toolResults after trimming.

    Args:
        payload: Kiro payload (mutated in place)
        max_bytes: Target maximum serialized size in bytes
        keep_prefix_entries: Number of leading history entries that are never
            trimmed (e.g. 2 for the system prompt user/assistant pair)

    Returns:
        PayloadTrimStats describing the operation
    """
    original_bytes = check_payload_size(payload)
    history = payload.get("conversationState", {}).get("history")

    if not history:
        return PayloadTrimStats(
            original_bytes=original_bytes,
            final_bytes=original_bytes,
            original_entries=0,
            final_entries=0,
            trimmed=False,
        )

    original_entries = len(history)

    # Strip empty toolUses before measuring
    _strip_empty_tool_uses(history)

    keep = max(0, min(keep_prefix_entries, len(history)))

    # Trim pairs after the protected prefix until under limit (keep at least 2 trimmable entries)
    while len(history) - keep > 2 and check_payload_size(payload) > max_bytes:
        # Remove 2 entries (a user/assistant pair)
        history.pop(keep)
        history.pop(keep)

    # Align to userInputMessage boundary
    if keep:
        while len(history) > keep and "userInputMessage" not in history[keep]:
            history.pop(keep)
    else:
        _align_to_user_message(history)

    # Repair orphaned tool results after trimming
    _repair_orphaned_tool_results(history)

    final_bytes = check_payload_size(payload)
    return PayloadTrimStats(
        original_bytes=original_bytes,
        final_bytes=final_bytes,
        original_entries=original_entries,
        final_entries=len(history),
        trimmed=original_entries != len(history),
    )



# ==================================================================================================
# Kiro History Building
# ==================================================================================================

def build_kiro_history(messages: List[UnifiedMessage], model_id: str) -> List[Dict[str, Any]]:
    """
    Builds history array for Kiro API from unified messages.
    
    Kiro API expects alternating userInputMessage and assistantResponseMessage.
    This function converts unified format to Kiro format.
    
    All messages should have 'user' or 'assistant' roles at this point,
    as unknown roles are normalized earlier in the pipeline by normalize_message_roles().
    
    Args:
        messages: List of messages in unified format (with normalized roles)
        model_id: Internal Kiro model ID
    
    Returns:
        List of dictionaries for history field in Kiro API
    """
    history = []
    
    for msg in messages:
        if msg.role == "user":
            content = extract_text_content(msg.content)
            
            # Fallback for empty content - Kiro API requires non-empty content.
            # A user turn that only carries tool results gets a neutral hint so the
            # model answers based on the results instead of reading it as "continue".
            if not content:
                has_results = bool(msg.tool_results) or bool(
                    extract_tool_results_from_content(msg.content)
                )
                content = TOOL_RESULT_ONLY_CONTENT if has_results else EMPTY_CONTENT_FALLBACK
            
            user_input = {
                "content": content,
                "modelId": model_id,
                "origin": "AI_EDITOR",
            }
            
            # Process images - extract from message or content
            # IMPORTANT: images go directly into userInputMessage, NOT into userInputMessageContext
            # This matches the native Kiro IDE format
            images = msg.images or extract_images_from_content(msg.content)
            if images:
                kiro_images = convert_images_to_kiro_format(images)
                if kiro_images:
                    user_input["images"] = kiro_images
            
            # Build userInputMessageContext for tools and toolResults only
            user_input_context: Dict[str, Any] = {}
            
            # Process tool_results - convert to Kiro format if present
            if msg.tool_results:
                kiro_tool_results = convert_tool_results_to_kiro_format(msg.tool_results)
                if kiro_tool_results:
                    user_input_context["toolResults"] = kiro_tool_results
            else:
                # Try to extract from content (already in Kiro format)
                tool_results = extract_tool_results_from_content(msg.content)
                if tool_results:
                    user_input_context["toolResults"] = tool_results
            
            # Add context if not empty (contains toolResults only, not images)
            if user_input_context:
                user_input["userInputMessageContext"] = user_input_context
            
            history.append({"userInputMessage": user_input})
            
        elif msg.role == "assistant":
            content = extract_text_content(msg.content)
            
            # Process tool_calls
            tool_uses = _core.extract_tool_uses_from_message(msg.content, msg.tool_calls)
            
            # Fallback for empty content - Kiro API requires non-empty content.
            # Assistant turns with only toolUses use a single space (reference behaviour).
            if not content.strip():
                content = " " if tool_uses else EMPTY_CONTENT_FALLBACK
            
            assistant_response = {"content": content}
            
            if tool_uses:
                assistant_response["toolUses"] = tool_uses
            
            history.append({"assistantResponseMessage": assistant_response})
    
    return history


# ==================================================================================================
# Envelope Helpers (agentContinuationId, agentTaskType, additionalModelRequestFields)
# ==================================================================================================

def derive_agent_continuation_id(conversation_id: str) -> str:
    """
    Derive a stable agentContinuationId from the conversationId.

    Port of kiro2cc-proxy session.rs: SHA-256 over "agent-continuation:" + id,
    first 16 bytes formatted as a UUID string. The same conversationId always
    yields the same agentContinuationId.

    Args:
        conversation_id: Conversation ID sent in conversationState

    Returns:
        UUID-formatted lowercase hex string
    """
    digest = hashlib.sha256(b"agent-continuation:" + conversation_id.encode("utf-8")).hexdigest()
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def determine_agent_task_type(tools: Optional[List[UnifiedTool]]) -> str:
    """
    Determine conversationState.agentTaskType (reference convert.rs).

    Args:
        tools: Tools declared by the client

    Returns:
        "spectask" when any tool is declared, otherwise "vibe"
    """
    return "spectask" if tools else "vibe"


def is_gpt_model(model_id: str) -> bool:
    """
    Check whether the Kiro model ID belongs to the GPT family.

    Args:
        model_id: Kiro model ID

    Returns:
        True for gpt-* models
    """
    return model_id.lower().startswith("gpt-")


def additional_fields_skipped(model_id: str) -> bool:
    """
    Check whether additionalModelRequestFields must be omitted for a model.

    Kiro rejects the field for the "4.5" generation (sonnet/opus/haiku 4.5) with
    400 REQUEST_BODY_INVALID (reference thinking.rs). Legacy claude-3.x models
    are also skipped (the reference never sends to them), as are non-Claude,
    non-GPT models whose schema is unknown.

    Args:
        model_id: Kiro model ID

    Returns:
        True if the field must not be sent
    """
    m = model_id.lower()
    if is_gpt_model(m):
        return False
    if not m.startswith("claude-"):
        return True
    # Only send to generations known to accept it (>= 4.6). Kiro rejects it for
    # claude-3.x, 4.0 (verified: claude-sonnet-4) and 4.5 with REQUEST_BODY_INVALID.
    version = _claude_version(m)
    return version is None or version < (4, 6)


def _claude_version(model_id: str) -> Optional[tuple]:
    """
    Extracts (major, minor) from a Claude model ID.

    Handles "claude-sonnet-4.5", "claude-sonnet-4-5", "claude-opus-5", "claude-3.7-sonnet".

    Args:
        model_id: Lower-case Kiro model ID

    Returns:
        (major, minor) tuple, or None if no version found
    """
    match = re.search(r"(?<![\d])(\d+)(?:[.-](\d)(?![\d]))?", model_id)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def model_max_output_tokens(model_id: str) -> int:
    """
    Kiro max_tokens upper bound per model generation (reference fields.rs).

    Args:
        model_id: Kiro model ID

    Returns:
        128000 for opus 4.7 / 4.8 / 5.x, otherwise 64000
    """
    m = model_id.lower()
    if any(tag in m for tag in ("opus-4-7", "opus-4.7", "opus-4-8", "opus-4.8", "opus-5", "opus.5", "opus 5")):
        return 128000
    return 64000


def _extract_effort(output_config: Any) -> Optional[str]:
    """
    Read `effort` from an Anthropic output_config (dict or object).

    Args:
        output_config: output_config value from the client request

    Returns:
        Non-empty effort string, or None
    """
    if output_config is None:
        return None
    effort = output_config.get("effort") if isinstance(output_config, dict) else getattr(output_config, "effort", None)
    if isinstance(effort, str) and effort.strip():
        return effort.strip()
    return None


def build_additional_model_request_fields(
    model_id: str,
    max_tokens: Optional[int] = None,
    output_config: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Build top-level additionalModelRequestFields (port of reference fields.rs).

    - Disabled entirely by KIRO_ADDITIONAL_MODEL_FIELDS=false
    - Skipped for models in additional_fields_skipped() (4.5 generation etc.)
    - GPT family: {"reasoning": {"effort": <effort or "high">}}
    - Claude: {"output_config": {"effort": <effort or "low">},
               "max_tokens": clamp(max_tokens, 1024, model cap)} (max_tokens only if > 0)
    - The `thinking` field is intentionally never sent (reference: adds TTFB)

    Args:
        model_id: Kiro model ID
        max_tokens: Client max_tokens (None/0 = omit)
        output_config: Client output_config (dict with "effort"), optional

    Returns:
        Fields dict, or None when nothing should be sent
    """
    if not KIRO_ADDITIONAL_MODEL_FIELDS or additional_fields_skipped(model_id):
        return None

    effort = _extract_effort(output_config)

    if is_gpt_model(model_id):
        return {"reasoning": {"effort": effort or DEFAULT_GPT_EFFORT}}

    fields: Dict[str, Any] = {"output_config": {"effort": effort or DEFAULT_CLAUDE_EFFORT}}
    if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0:
        capped = min(max_tokens, model_max_output_tokens(model_id))
        fields["max_tokens"] = max(capped, MIN_ADDITIONAL_MAX_TOKENS)
    return fields


def build_placeholder_tool_specs(
    history: List[Dict[str, Any]],
    kiro_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Create minimal tool specs for toolUse names in history that are not declared.

    Kiro requires every tool referenced in history to be defined in
    currentMessage tools. Names are compared case-insensitively (Kiro matches
    tool names ignoring case). Reference: websearch.rs create_placeholder_tool.

    Args:
        history: Kiro-format history (after pairing cleanup)
        kiro_tools: Declared tools in Kiro toolSpecification format

    Returns:
        Placeholder specs to append to the tools list (may be empty)
    """
    known = {
        str(t.get("toolSpecification", {}).get("name", "")).lower()
        for t in kiro_tools
    }
    placeholders: List[Dict[str, Any]] = []
    for entry in history:
        assistant = entry.get("assistantResponseMessage")
        if not assistant:
            continue
        for tool_use in assistant.get("toolUses") or []:
            name = tool_use.get("name") if isinstance(tool_use, dict) else None
            if not name or name.lower() in known:
                continue
            known.add(name.lower())
            placeholders.append({
                "toolSpecification": {
                    "name": name,
                    "description": PLACEHOLDER_TOOL_DESCRIPTION,
                    "inputSchema": {"json": {"type": "object", "properties": {}}},
                }
            })
    if placeholders:
        logger.debug(
            f"Added {len(placeholders)} placeholder tool definition(s) for history-only tools: "
            f"{[p['toolSpecification']['name'] for p in placeholders]}"
        )
    return placeholders


def drop_trailing_assistant_messages(messages: List[UnifiedMessage]) -> List[UnifiedMessage]:
    """
    Drop trailing assistant messages (prefill) - Kiro does not support prefill.

    Reference convert.rs: the conversation is truncated after the last non-assistant
    message. Unknown roles count as user (they are normalized later).

    Args:
        messages: Messages in unified format

    Returns:
        New list without trailing assistant messages (input is not mutated).
        An assistant-only list is returned unchanged.
    """
    end = len(messages)
    while end > 0 and messages[end - 1].role == "assistant":
        end -= 1
    if end == 0:
        # Assistant-only conversation: nothing to answer. Keep it unchanged and let
        # build_kiro_payload move the assistant turn into history (legacy behaviour).
        return list(messages)
    if end != len(messages):
        logger.info(f"Dropping {len(messages) - end} trailing assistant message(s) (prefill is not supported by Kiro)")
    return list(messages[:end])


# ==================================================================================================
# Main Payload Building
# ==================================================================================================

def build_kiro_payload(
    messages: List[UnifiedMessage],
    system_prompt: str,
    model_id: str,
    tools: Optional[List[UnifiedTool]],
    conversation_id: str,
    profile_arn: str,
    thinking_config: ThinkingConfig,
    max_tokens: Optional[int] = None,
    output_config: Optional[Any] = None,
) -> KiroPayloadResult:
    """
    Builds complete payload for Kiro API from unified data.
    
    This is the main function that assembles the Kiro API payload from
    API-agnostic unified message and tool formats.

    Layout:
    - history[0..1]: system prompt as user {system} + assistant
      "I will follow these instructions." (only when a system prompt exists)
    - history[2..]: conversation turns (trailing assistant prefill dropped)
    - currentMessage: last user turn with tools (+ placeholders) and toolResults
    - conversationState.agentTaskType / agentContinuationId envelope fields
    - top-level additionalModelRequestFields (gated by KIRO_ADDITIONAL_MODEL_FIELDS)
    
    Args:
        messages: List of messages in unified format (without system messages)
        system_prompt: Already extracted system prompt
        model_id: Internal Kiro model ID
        tools: List of tools in unified format (or None)
        conversation_id: Unique conversation ID
        profile_arn: AWS CodeWhisperer profile ARN
        thinking_config: Thinking configuration from API adapter
        max_tokens: Client max output tokens (for additionalModelRequestFields), optional
        output_config: Client output_config ({"effort": ...}), optional
    
    Returns:
        KiroPayloadResult with payload and tool documentation
    
    Raises:
        ValueError: If there are no messages to send
    """
    # Process tools with long descriptions
    processed_tools, tool_documentation = process_tools_with_long_descriptions(tools)
    
    # Validate tool names against Kiro API 64-character limit
    _core.validate_tool_names(processed_tools)
    
    # Add tool documentation to system prompt if present
    full_system_prompt = system_prompt
    if tool_documentation:
        full_system_prompt = full_system_prompt + tool_documentation if full_system_prompt else tool_documentation.strip()
    
    # Add thinking mode legitimization only when tags are actually injected
    thinking_system_addition = (
        get_thinking_system_prompt_addition()
        if should_inject_thinking(thinking_config, model_id) else ""
    )
    if thinking_system_addition:
        full_system_prompt = full_system_prompt + thinking_system_addition if full_system_prompt else thinking_system_addition.strip()
    
    # Add truncation recovery legitimization to system prompt if enabled
    truncation_system_addition = get_truncation_recovery_system_addition()
    if truncation_system_addition:
        full_system_prompt = full_system_prompt + truncation_system_addition if full_system_prompt else truncation_system_addition.strip()

    # Kiro does not support assistant prefill - drop trailing assistant messages
    messages = drop_trailing_assistant_messages(messages)
    
    # If no tools are defined, strip ALL tool-related content from messages
    # Kiro API rejects requests with toolResults but no tools
    if not tools:
        messages_with_assistants, _ = strip_all_tool_content(messages)
    else:
        # Tool results without a preceding assistant tool call are converted to text
        messages_with_assistants, _ = ensure_assistant_before_tool_results(messages)
    
    # Merge adjacent messages with the same role
    merged_messages = merge_adjacent_messages(messages_with_assistants)
    
    # Ensure first message is from user (Kiro API requirement, fixes issue #60)
    merged_messages = ensure_first_message_is_user(merged_messages)
    
    # Normalize unknown roles to 'user' (fixes issue #64)
    # This must happen BEFORE ensure_alternating_roles() so that consecutive
    # messages with unknown roles (e.g., 'developer') are properly detected
    merged_messages = normalize_message_roles(merged_messages)
    
    # Ensure alternating user/assistant roles (fixes issue #64)
    # Insert synthetic assistant messages between consecutive user messages
    merged_messages = ensure_alternating_roles(merged_messages)
    
    if not merged_messages:
        raise ValueError("No messages to send")
    
    # History = all messages except the last one; current = last (always user after prefill drop)
    history_messages = merged_messages[:-1]
    current_message = merged_messages[-1]
    if current_message.role == "assistant":
        # Only reachable for assistant-only conversations (see drop_trailing_assistant_messages)
        history_messages = merged_messages
        current_message = UnifiedMessage(role="user", content="")
    history = build_kiro_history(history_messages, model_id)
    current_content = extract_text_content(current_message.content)
    
    # Tool results of the current message (Kiro format)
    if current_message.tool_results:
        current_tool_results = convert_tool_results_to_kiro_format(current_message.tool_results)
    else:
        current_tool_results = extract_tool_results_from_content(current_message.content)

    # Enforce toolUse/toolResult pairing: drop duplicate results, convert orphaned
    # results to text, remove toolUses that never get a result
    current_tool_results, current_orphan_text = repair_tool_pairing(history, current_tool_results)
    if current_orphan_text:
        current_content = f"{current_content}\n\n{current_orphan_text}" if current_content else current_orphan_text

    # Empty content fallbacks
    if not current_content:
        current_content = TOOL_RESULT_ONLY_CONTENT if current_tool_results else EMPTY_CONTENT_FALLBACK

    # System prompt as a separate leading user/assistant pair (stable prefix)
    system_prefix_entries = 0
    if full_system_prompt:
        history = [
            {"userInputMessage": {"content": full_system_prompt, "modelId": model_id, "origin": "AI_EDITOR"}},
            {"assistantResponseMessage": {"content": SYSTEM_PROMPT_ACKNOWLEDGEMENT}},
        ] + history
        system_prefix_entries = 2
    
    # Process images in current message - extract from message or content
    # IMPORTANT: images go directly into userInputMessage, NOT into userInputMessageContext
    # This matches the native Kiro IDE format
    images = current_message.images or extract_images_from_content(current_message.content)
    kiro_images = None
    if images:
        kiro_images = convert_images_to_kiro_format(images)
        if kiro_images:
            logger.debug(f"Added {len(kiro_images)} image(s) to current message")
    
    # Build user_input_context for tools and toolResults only (NOT images)
    user_input_context: Dict[str, Any] = {}
    
    # Add tools if present, plus placeholder specs for tools referenced only in history
    kiro_tools = _core.convert_tools_to_kiro_format(processed_tools)
    if kiro_tools:
        kiro_tools.extend(build_placeholder_tool_specs(history, kiro_tools))
        user_input_context["tools"] = kiro_tools
    
    if current_tool_results:
        user_input_context["toolResults"] = current_tool_results
    
    # Inject thinking tags if enabled (current user message only)
    current_content = inject_thinking_tags(current_content, thinking_config, model_id)
    
    # Build userInputMessage
    user_input_message = {
        "content": current_content,
        "modelId": model_id,
        "origin": "AI_EDITOR",
    }
    
    # Add images directly to userInputMessage (NOT to userInputMessageContext)
    if kiro_images:
        user_input_message["images"] = kiro_images
    
    # Add user_input_context if present (contains tools and toolResults only)
    if user_input_context:
        user_input_message["userInputMessageContext"] = user_input_context
    
    # Assemble final payload
    payload: Dict[str, Any] = {
        "conversationState": {
            "agentContinuationId": derive_agent_continuation_id(conversation_id),
            "agentTaskType": determine_agent_task_type(tools),
            "chatTriggerType": "MANUAL",
            "conversationId": conversation_id,
            "currentMessage": {
                "userInputMessage": user_input_message
            }
        }
    }
    
    # Add history only if not empty
    if history:
        payload["conversationState"]["history"] = history
    
    # Add profileArn
    if profile_arn:
        payload["profileArn"] = profile_arn

    # Model-specific request fields (top level, next to conversationState)
    additional_fields = build_additional_model_request_fields(model_id, max_tokens, output_config)
    if additional_fields:
        payload["additionalModelRequestFields"] = additional_fields

    # Payload size guard — auto-trim if enabled (system prompt pair is never trimmed)
    if _core.AUTO_TRIM_PAYLOAD:
        payload_size = check_payload_size(payload)
        if payload_size > _core.KIRO_MAX_PAYLOAD_BYTES:
            stats = trim_payload_to_limit(
                payload, _core.KIRO_MAX_PAYLOAD_BYTES, keep_prefix_entries=system_prefix_entries
            )
            logger.info(
                f"Trimmed conversation history: {stats.original_entries} -> {stats.final_entries} messages "
                f"({stats.original_bytes} -> {stats.final_bytes} bytes)"
            )

    return KiroPayloadResult(payload=payload, tool_documentation=tool_documentation)


# ==================================================================================================
# Stable Conversation IDs (kiro/utils.py in the fork)
# ==================================================================================================

# Derive a stable Kiro conversationId per client conversation (metadata.user_id
# session, else a hash of system + tools + first message) instead of a random UUID
# per request. Lets Kiro reuse server-side conversation state / prompt cache.
STABLE_CONVERSATION_ID: bool = _env_flag("STABLE_CONVERSATION_ID", "true")

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _is_uuid(value: str) -> bool:
    """Returns True if value is a canonical UUID string."""
    return bool(_UUID_RE.match(value or ""))


def extract_session_id(user_id: Optional[str]) -> Optional[str]:
    """
    Extracts a client session UUID from Anthropic metadata.user_id.

    Supports the formats Claude Code sends:
    - plain UUID
    - JSON string {"session_id": "..."} or {"id": "..."}
    - legacy "user_<hash>_account__session_<uuid>"

    Args:
        user_id: metadata.user_id value

    Returns:
        Lower-case session UUID, or None if none found
    """
    if not user_id or not isinstance(user_id, str):
        return None
    if _is_uuid(user_id):
        return user_id.lower()
    if user_id.lstrip().startswith("{"):
        try:
            parsed = json.loads(user_id)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("session_id", "id"):
                candidate = parsed.get(key)
                if isinstance(candidate, str) and _is_uuid(candidate):
                    return candidate.lower()
    pos = user_id.find("session_")
    if pos != -1:
        candidate = user_id[pos + 8:pos + 8 + 36]
        if _is_uuid(candidate):
            return candidate.lower()
    return None


def derive_conversation_id(
    metadata: Optional[Dict[str, Any]],
    system: Any = None,
    tool_names: Optional[List[str]] = None,
    first_message: Any = None,
) -> str:
    """
    Derives a stable Kiro conversationId for a client conversation.

    Kiro can reuse server-side state across requests of the same conversation,
    which a random ID per request defeats. Priority:
    1. session UUID from metadata.user_id (Claude Code)
    2. SHA-256 of system + sorted tool names + first message (first 4096 chars)

    Args:
        metadata: Anthropic request metadata
        system: System prompt (str or list of blocks)
        tool_names: Declared tool names
        first_message: Content of the first message

    Returns:
        UUID-formatted conversation ID
    """
    user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
    session_id = extract_session_id(user_id)
    if session_id:
        return session_id

    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)

    # Claude Code's billing header line changes per request; keep it out of the hash
    system_text = "\n".join(
        line for line in _text(system).splitlines()
        if "x-anthropic-billing-header" not in line
    )
    hasher = hashlib.sha256()
    hasher.update(system_text.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(",".join(sorted(tool_names or [])).encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(_text(first_message)[:4096].encode("utf-8"))
    return str(uuid.UUID(bytes=hasher.digest()[:16], version=4))


def _dump(value: Any) -> Any:
    """Pydantic models -> plain data, so hashing is independent of model classes."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value


def stable_conversation_id_for_anthropic(request: Any) -> Optional[str]:
    """Stable conversationId for an Anthropic request, or None when disabled."""
    if not STABLE_CONVERSATION_ID:
        return None
    tool_names = [getattr(t, "name", "") or "" for t in (request.tools or [])]
    first_message = _dump(request.messages[0].content) if request.messages else None
    return derive_conversation_id(request.metadata, _dump(request.system), tool_names, first_message)


def stable_conversation_id_for_openai(request: Any) -> Optional[str]:
    """Stable conversationId for an OpenAI chat request, or None when disabled.

    Uses system messages + tool names + first non-system message, so every turn
    of the same conversation maps to the same Kiro conversation.
    """
    if not STABLE_CONVERSATION_ID:
        return None
    messages = list(request.messages or [])
    system = [_dump(m.content) for m in messages if getattr(m, "role", None) in ("system", "developer")]
    first = next((_dump(m.content) for m in messages if getattr(m, "role", None) not in ("system", "developer")), None)
    tool_names = []
    for tool in request.tools or []:
        function = getattr(tool, "function", None)
        name = getattr(function, "name", None) if function is not None else getattr(tool, "name", None)
        if name:
            tool_names.append(name)
    user = getattr(request, "user", None)
    metadata = {"user_id": user} if isinstance(user, str) else None
    return derive_conversation_id(metadata, system, tool_names, first)


# ==================================================================================================
# API Adapters (converters_anthropic / converters_openai in the fork)
# ==================================================================================================

def extract_thinking_config_from_anthropic(request: Any) -> ThinkingConfig:
    """
    Thinking config for Anthropic requests under FAKE_REASONING_MODE.

    explicit: only thinking.type="enabled" turns fake reasoning on; no thinking
    param or "adaptive" leaves it to the model. always: upstream behaviour.
    """
    implicit_default = FAKE_REASONING_MODE == "always"
    thinking = request.thinking
    if not thinking or not isinstance(thinking, dict):
        return ThinkingConfig(enabled=implicit_default, budget_tokens=None)
    thinking_type = thinking.get("type")
    if thinking_type == "disabled":
        return ThinkingConfig(enabled=False, budget_tokens=None)
    if thinking_type == "enabled":
        budget = thinking.get("budget_tokens")
        if budget:
            logger.debug(f"Extracted thinking config from Anthropic: type='enabled', budget={budget}")
        return ThinkingConfig(enabled=True, budget_tokens=budget)
    # "adaptive" / unknown type -> model decides; no fake tags in explicit mode
    return ThinkingConfig(enabled=implicit_default, budget_tokens=None)


def _reasoning_effort_to_output_config(request: Any) -> Optional[Dict[str, str]]:
    """
    Map OpenAI reasoning_effort to an output_config for additionalModelRequestFields.

    Only low/medium/high are forwarded (values shared by Claude output_config.effort
    and GPT reasoning.effort); other values fall back to the defaults.
    """
    if getattr(request, "reasoning_effort", None) in ("low", "medium", "high"):
        return {"effort": request.reasoning_effort}
    return None


_installed = False
_originals: Dict[str, Any] = {}


def install_kiro_payload_builder() -> None:
    """Replace build_kiro_payload and wire the fork's adapters in at runtime."""
    global _installed
    if _installed:
        return

    import kiro.converters_anthropic as converters_anthropic
    import kiro.converters_openai as converters_openai
    import kiro.payload_guards as payload_guards
    import kiro.routes_anthropic as routes_anthropic
    import kiro.routes_openai as routes_openai

    _originals.update(
        core_build_kiro_payload=_core.build_kiro_payload,
        core_sanitize_json_schema=_core.sanitize_json_schema,
        core_inject_thinking_tags=_core.inject_thinking_tags,
        core_get_thinking_system_prompt_addition=_core.get_thinking_system_prompt_addition,
        core_build_kiro_history=_core.build_kiro_history,
        guards_trim_payload_to_limit=payload_guards.trim_payload_to_limit,
        anthropic_build_kiro_payload=converters_anthropic.build_kiro_payload,
        anthropic_extract_thinking=converters_anthropic.extract_thinking_config_from_anthropic,
        anthropic_to_kiro=converters_anthropic.anthropic_to_kiro,
        routes_anthropic_to_kiro=routes_anthropic.anthropic_to_kiro,
        openai_core_build=converters_openai.core_build_kiro_payload,
        openai_extract_thinking=converters_openai.extract_thinking_config_from_openai,
        openai_build_kiro_payload=converters_openai.build_kiro_payload,
        routes_openai_build=routes_openai.build_kiro_payload,
    )
    original_anthropic_to_kiro = converters_anthropic.anthropic_to_kiro
    original_openai_build = converters_openai.build_kiro_payload
    original_openai_thinking = converters_openai.extract_thinking_config_from_openai

    # Per-call extras the upstream adapters don't know how to pass along
    # (max_tokens / output_config). Set by the adapter wrappers right before they
    # call upstream, read by build_kiro_payload below. Plain module state is
    # enough: conversion is synchronous, so no await can interleave two requests.
    extras: Dict[str, Any] = {}

    def build_kiro_payload_from_adapter(**kwargs):
        kwargs.setdefault("max_tokens", extras.get("max_tokens"))
        kwargs.setdefault("output_config", extras.get("output_config"))
        return build_kiro_payload(**kwargs)

    def anthropic_to_kiro(request, conversation_id, profile_arn):
        conversation_id = stable_conversation_id_for_anthropic(request) or conversation_id
        extras.clear()
        extras.update(
            max_tokens=request.max_tokens,
            # output_config is not a declared field; it arrives via model_config extra="allow"
            output_config=getattr(request, "output_config", None),
        )
        try:
            return original_anthropic_to_kiro(request, conversation_id, profile_arn)
        finally:
            extras.clear()

    def openai_build_kiro_payload(request_data, conversation_id, profile_arn):
        conversation_id = stable_conversation_id_for_openai(request_data) or conversation_id
        extras.clear()
        extras.update(
            max_tokens=request_data.max_tokens or request_data.max_completion_tokens,
            output_config=_reasoning_effort_to_output_config(request_data),
        )
        try:
            return original_openai_build(request_data, conversation_id, profile_arn)
        finally:
            extras.clear()

    def extract_thinking_config_from_openai(request):
        if not request.reasoning_effort:
            # No reasoning_effort -> inject only in legacy "always" mode
            return ThinkingConfig(enabled=FAKE_REASONING_MODE == "always", budget_tokens=None)
        return original_openai_thinking(request)

    # Core: the fork's builder plus the helpers other upstream code calls directly
    _core.build_kiro_payload = build_kiro_payload
    _core.sanitize_json_schema = sanitize_json_schema
    _core.inject_thinking_tags = inject_thinking_tags
    _core.get_thinking_system_prompt_addition = get_thinking_system_prompt_addition
    _core.build_kiro_history = build_kiro_history
    payload_guards.trim_payload_to_limit = trim_payload_to_limit

    # Adapters: they imported build_kiro_payload by name at import time
    converters_anthropic.build_kiro_payload = build_kiro_payload_from_adapter
    converters_anthropic.extract_thinking_config_from_anthropic = extract_thinking_config_from_anthropic
    converters_anthropic.anthropic_to_kiro = anthropic_to_kiro
    converters_openai.core_build_kiro_payload = build_kiro_payload_from_adapter
    converters_openai.extract_thinking_config_from_openai = extract_thinking_config_from_openai
    converters_openai.build_kiro_payload = openai_build_kiro_payload

    # Routes look these up as module globals on every request
    routes_anthropic.anthropic_to_kiro = anthropic_to_kiro
    routes_openai.build_kiro_payload = openai_build_kiro_payload

    _installed = True
    logger.info("Installed Kiro payload builder extension")


def uninstall_kiro_payload_builder() -> None:
    """Restore patched functions. Intended for unit tests."""
    global _installed
    if _originals:
        import kiro.converters_anthropic as converters_anthropic
        import kiro.converters_openai as converters_openai
        import kiro.payload_guards as payload_guards
        import kiro.routes_anthropic as routes_anthropic
        import kiro.routes_openai as routes_openai

        _core.build_kiro_payload = _originals["core_build_kiro_payload"]
        _core.sanitize_json_schema = _originals["core_sanitize_json_schema"]
        _core.inject_thinking_tags = _originals["core_inject_thinking_tags"]
        _core.get_thinking_system_prompt_addition = _originals["core_get_thinking_system_prompt_addition"]
        _core.build_kiro_history = _originals["core_build_kiro_history"]
        payload_guards.trim_payload_to_limit = _originals["guards_trim_payload_to_limit"]
        converters_anthropic.build_kiro_payload = _originals["anthropic_build_kiro_payload"]
        converters_anthropic.extract_thinking_config_from_anthropic = _originals["anthropic_extract_thinking"]
        converters_anthropic.anthropic_to_kiro = _originals["anthropic_to_kiro"]
        routes_anthropic.anthropic_to_kiro = _originals["routes_anthropic_to_kiro"]
        converters_openai.core_build_kiro_payload = _originals["openai_core_build"]
        converters_openai.extract_thinking_config_from_openai = _originals["openai_extract_thinking"]
        converters_openai.build_kiro_payload = _originals["openai_build_kiro_payload"]
        routes_openai.build_kiro_payload = _originals["routes_openai_build"]

    _originals.clear()
    _installed = False
