"""Kiro command construction with explicit identity and capability contracts.

Installed by app_entry after tool aliases. Tools preserve schema semantics;
mode/task type and conversation/turn identity are independent. Additional model
fields use the selected account's advertised schema, never model-name heuristics,
forced effort defaults, or silent token clamping. Missing metadata is unknown and
explicit parameters fail actionably until verified metadata is available.

Legacy textual thinking tags require KIRO_LEGACY_FAKE_REASONING=true and remain
separate from native thinking fields. Native/system/transport choices are explicit
protocol features; the legacy system history prefix is not a universal CLI contract.
"""

from contextvars import ContextVar
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from extensions.request_context import current_state
from extensions.session_identity import SessionIdentity, request_identity
from kiro.native_reasoning import NativeReasoningError, reasoning_blocks, reasoning_store, expand_history, tool_ids, restore_native_projections
from extensions.tool_schema import normalize_tool_schema
from extensions.protocol_runtime import configured_profile
from extensions.model_capabilities import (CapabilityStatus, ModelCapabilities, ModelCapabilityError, build_model_request_fields, build_responses_request_fields)

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
    check_payload_size as _base_check_payload_size,
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

# Legacy gateway system-prefix acknowledgment; not a universal CLI wire contract.
SYSTEM_PROMPT_ACKNOWLEDGEMENT = "I will follow these instructions."

# Description of placeholder tool specs generated for tools referenced only in history
PLACEHOLDER_TOOL_DESCRIPTION = "Tool used in conversation history"

# Content used for user messages that only carry toolResults
TOOL_RESULT_ONLY_CONTENT = "(tool result above)"

# Fallback for messages whose content is truly empty (Kiro rejects empty content)
EMPTY_CONTENT_FALLBACK = "(empty placeholder)"


def _fake_reasoning_enabled() -> bool:
    """Upstream FAKE_REASONING switch, read live so patches in tests take effect."""
    return _core.FAKE_REASONING_ENABLED and _env_flag("KIRO_LEGACY_FAKE_REASONING", "false")


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


def get_model_capabilities(model_id: str) -> ModelCapabilities:
    """Read the selected account cache, preserving UNKNOWN on absent metadata."""
    from kiro.model_resolver import normalize_model_name

    state = current_state()
    cache = state.model_cache if state is not None else None
    raw = None
    if cache is not None:
        candidate = cache.get(model_id)
        if isinstance(candidate, dict):
            raw = candidate
        if raw is None:
            ids = cache.get_all_model_ids()
            if isinstance(ids, list):
                for key in ids:
                    item = cache.get(key)
                    if isinstance(item, dict) and (
                        item.get("_internal_id") == model_id
                        or normalize_model_name(key) == normalize_model_name(model_id)
                    ):
                        raw = item
                        break
    return ModelCapabilities.from_model(raw, model_id=model_id)


def model_has_native_reasoning(model_id: str) -> bool:
    """Whether selected-account metadata advertises native reasoning controls."""
    capability = get_model_capabilities(model_id)
    return CapabilityStatus.SUPPORTED in (capability.effort.status, capability.thinking.status)


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

def sanitize_json_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize tool schemas without dropping constraints or inlining references.

    Resource and structural errors remain ValueErrors so both API routes return
    actionable client errors rather than silently widening accepted tool inputs.
    """
    return normalize_tool_schema(schema)


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


def _expand_native_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expand signed assistant groups only after pairing repair and whole-turn trim."""
    result = []
    for entry in history:
        assistant = entry.get("assistantResponseMessage", {})
        native = assistant.get("_native_history")
        if native is None:
            result.append(entry)
            continue
        expected = [tool for part in native for tool in part.get("assistantResponseMessage", {}).get("toolUses", [])]
        if tool_ids(assistant.get("toolUses")) != tool_ids(expected):
            raise NativeReasoningError("Tool pairing repair changed signed native history; provide complete tool results")
        result.extend(native)
    return result


def check_payload_size(payload: Dict[str, Any]) -> int:
    """Measure the actual wire history while trimming compact signed turn groups."""
    conversation = payload.get("conversationState", {})
    if "history" not in conversation:
        return _base_check_payload_size(payload)
    return _base_check_payload_size({**payload, "conversationState": {
        **conversation, "history": _expand_native_history(conversation["history"]),
    }})


def _find_native_record(model_id: str, content: str, tools: Any, native: Any) -> Any:
    """Resolve generated native state without trusting caller-provided model labels."""
    if not native:
        return None
    state = current_state()
    if state is None or not state.account_scope:
        raise NativeReasoningError("Native history requires a selected account and managed request context")
    record = reasoning_store.find((state.client_scope, state.account_scope, model_id), content, tools, native)
    identity = state.wire_identity
    if record is not None and identity is not None and record.root_conversation_id != identity.root_conversation_id:
        raise NativeReasoningError("Native reasoning belongs to a different root conversation; keep its original session")
    return record


def _prepare_native_history(request: Any, *, anthropic: bool) -> Any:
    """Recover anonymous session identity only from verified upstream output, never prompts."""
    from kiro.model_resolver import get_model_id_for_kiro
    from kiro.config import HIDDEN_MODELS

    model_id = get_model_id_for_kiro(request.model, HIDDEN_MODELS)
    state = current_state()
    if state is not None:
        state.upstream_model_id = model_id
        state.recovered_reasoning_record = None
        state.wire_identity = None
    if state is not None and state.account_scope:
        restored = restore_native_projections(request.messages, scope=(state.client_scope, state.account_scope, model_id), anthropic=anthropic)
        request = request.model_copy(update={"messages": restored})
    found = []
    for message in request.messages:
        if message.role != "assistant":
            continue
        blocks = message.content if anthropic else getattr(message, "reasoning_details", None)
        native = reasoning_blocks(blocks)
        if not native:
            continue
        plain_content = [block.model_dump() if hasattr(block, "model_dump") else block for block in message.content] if isinstance(message.content, list) else message.content
        content = extract_text_content(plain_content)
        tool_calls = getattr(message, "tool_calls", None)
        tools = _core.extract_tool_uses_from_message(plain_content, tool_calls)
        record = _find_native_record(model_id, content, tools, native)
        if record is not None:
            found.append(record)
    if found and state is not None:
        if len({record.root_conversation_id for record in found}) != 1:
            raise NativeReasoningError("Native history contains unrelated root conversations")
        state.recovered_reasoning_record = found[-1]
    return request


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
                "origin": configured_profile().origin,
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
            
            record = _find_native_record(model_id, content, tool_uses, msg.native_blocks)
            # Unsigned empty turns keep the legacy fallback; native reasoning entries
            # explicitly allow empty content, as in the shipped CLI expansion.
            if not content.strip() and record is None:
                content = " " if tool_uses else EMPTY_CONTENT_FALLBACK
            
            assistant_response = {"content": content}
            if record is not None:
                assistant_response["_native_history"] = expand_history(record, tool_uses)
            if tool_uses:
                assistant_response["toolUses"] = tool_uses
            
            history.append({"assistantResponseMessage": assistant_response})
    
    return history


# ==================================================================================================
# Envelope Helpers (agentContinuationId, agentTaskType, additionalModelRequestFields)
# ==================================================================================================

def derive_agent_continuation_id(conversation_id: str) -> str:
    """Allocate a new execution ID; conversation identity cannot define its lifetime.

    Retained as a compatibility helper. Session-aware callers must use
    request_identity so tool continuations and physical retries share their turn.
    """
    return str(uuid.uuid4())


def determine_agent_task_type(tools: Optional[List[UnifiedTool]]) -> str:
    """Read explicit task semantics, independently of the declared tool list."""
    state = current_state()
    return state.task_type if state is not None else "vibe"


def additional_fields_skipped(model_id: str) -> bool:
    """Whether metadata advertises no usable additional fields (not a name gate)."""
    return get_model_capabilities(model_id).schema_status is not CapabilityStatus.SUPPORTED


def model_max_output_tokens(model_id: str) -> Optional[int]:
    """Return the advertised output ceiling, or None when unknown/unbounded."""
    capability = get_model_capabilities(model_id)
    if capability.max_tokens.status is CapabilityStatus.SUPPORTED:
        return capability.max_tokens.maximum
    return capability.token_limits.max_output_tokens if capability.token_limits is not None else None


def _extract_effort(output_config: Any) -> Optional[str]:
    """Read an exact explicit effort without silently stripping invalid values."""
    if output_config is None:
        return None
    if hasattr(output_config, "model_dump"):
        output_config = output_config.model_dump(exclude_none=True)
    if not isinstance(output_config, dict) or set(output_config) - {"effort"}:
        raise ValueError("output_config currently accepts only effort; unsupported fields cannot be discarded")
    if "effort" not in output_config:
        return None
    effort = output_config["effort"]
    if not isinstance(effort, str) or not effort or effort != effort.strip():
        raise ValueError("output_config.effort must be an exact nonempty advertised string")
    return effort


def build_additional_model_request_fields(
    model_id: str, max_tokens: Optional[int] = None, output_config: Optional[Any] = None,
    *, native_thinking: Optional[str] = None, thinking_budget: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Validate and serialize exact caller intent against account model metadata.

    Unknown schemas are not inferred from the model ID. Native thinking budgets
    are validated when advertised. Explicit legacy textual thinking is the sole
    opt-in alternative, not an automatic fallback when the server rejects a field.
    """
    effort = _extract_effort(output_config)
    if not KIRO_ADDITIONAL_MODEL_FIELDS:
        if any(value is not None for value in (max_tokens, effort, native_thinking, thinking_budget)):
            raise ValueError("Additional model fields are disabled; enable KIRO_ADDITIONAL_MODEL_FIELDS to honor explicit generation parameters")
        return None
    capability = get_model_capabilities(model_id)
    if configured_profile().generation_protocol == "responses":
        return build_responses_request_fields(capability, effort=effort, thinking=native_thinking, max_tokens=max_tokens, thinking_budget=thinking_budget)
    if _fake_reasoning_enabled() and capability.thinking.status is not CapabilityStatus.SUPPORTED:
        # This deployment explicitly selected legacy text controls. No automatic
        # native-to-text fallback is performed in the default configuration.
        native_thinking, thinking_budget = None, None
    return build_model_request_fields(
        capability, effort=effort, thinking=native_thinking,
        max_tokens=max_tokens, thinking_budget=thinking_budget,
    )


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
    identity: Optional[SessionIdentity] = None,
    native_thinking: Optional[str] = None,
    thinking_budget: Optional[int] = None,
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
    identity = identity or request_identity(conversation_id, None, messages, fallback_account=profile_arn)
    state = current_state()
    profile = configured_profile()
    if state is not None:
        state.protocol_profile = profile
        state.wire_identity = identity
        state.upstream_model_id = model_id
        state.legacy_thinking = should_inject_thinking(thinking_config, model_id)

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
    if full_system_prompt and not profile.native_system_prompt:
        history = [
            {"userInputMessage": {"content": full_system_prompt, "modelId": model_id, "origin": configured_profile().origin}},
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
        "origin": configured_profile().origin,
    }
    
    # Add images directly to userInputMessage (NOT to userInputMessageContext)
    if kiro_images:
        user_input_message["images"] = kiro_images
    
    # Add user_input_context if present (contains tools and toolResults only)
    if user_input_context:
        user_input_message["userInputMessageContext"] = user_input_context
    
    # Identity follows the explicit session/turn lifecycle, not tool presence.
    identity = identity or request_identity(conversation_id, None, messages, fallback_account=profile_arn)
    state = current_state()
    payload: Dict[str, Any] = {
        "agentMode": state.agent_mode if state is not None else "vibe",
        "conversationState": {
            "agentContinuationId": identity.continuation_id,
            "rootConversationId": identity.root_conversation_id,
            "agentTaskType": determine_agent_task_type(tools),
            "chatTriggerType": "MANUAL",
            "conversationId": identity.conversation_id,
            "currentMessage": {
                "userInputMessage": user_input_message
            }
        }
    }
    
    if profile.native_system_prompt and full_system_prompt:
        payload["systemPrompt"] = full_system_prompt
    # Add history only if not empty
    if history:
        payload["conversationState"]["history"] = history
    
    # Add profileArn
    if profile_arn:
        payload["profileArn"] = profile_arn

    # Model-specific request fields (top level, next to conversationState)
    additional_fields = build_additional_model_request_fields(
        model_id, max_tokens, output_config,
        native_thinking=native_thinking, thinking_budget=thinking_budget,
    )
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

    if "history" in payload["conversationState"]:
        payload["conversationState"]["history"] = _expand_native_history(payload["conversationState"]["history"])
    return KiroPayloadResult(payload=payload, tool_documentation=tool_documentation)


# ==================================================================================================
# Stable Conversation IDs (kiro/utils.py in the fork)
# ==================================================================================================

# Recognize explicit client session metadata. Anonymous requests remain independent;
# content hashes are not reliable session identifiers.
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
    metadata: Optional[Dict[str, Any]], system: Any = None,
    tool_names: Optional[List[str]] = None, first_message: Any = None,
) -> str:
    """Use a caller-provided session UUID, never a hash of conversation content.

    Legacy positional arguments are accepted for compatibility but cannot create
    a session identity. Anonymous requests receive independent random UUIDs.
    """
    user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
    return extract_session_id(user_id) or str(uuid.uuid4())


def stable_conversation_id_for_anthropic(request: Any) -> Optional[str]:
    """Return only an explicit session, leaving anonymous request IDs independent."""
    if not STABLE_CONVERSATION_ID:
        return None
    metadata = request.metadata
    return extract_session_id(metadata.get("user_id")) if isinstance(metadata, dict) else None


def stable_conversation_id_for_openai(request: Any) -> Optional[str]:
    """Recognize the supported explicit session form; never hash prompt/tools."""
    if not STABLE_CONVERSATION_ID:
        return None
    return extract_session_id(getattr(request, "user", None))


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
    """Pass every explicit effort through capability validation, including none/xhigh."""
    effort = getattr(request, "reasoning_effort", None)
    return {"effort": effort} if effort is not None else None


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

    # Context-local converter metadata also isolates calls from worker threads.
    extras: ContextVar[Optional[Dict[str, Any]]] = ContextVar("kiro_payload_extras", default=None)

    def build_kiro_payload_from_adapter(**kwargs):
        options = extras.get() or {}
        for name in ("max_tokens", "output_config", "identity", "native_thinking", "thinking_budget"):
            kwargs.setdefault(name, options.get(name))
        return build_kiro_payload(**kwargs)

    def anthropic_to_kiro(request, conversation_id, profile_arn):
        request = _prepare_native_history(request, anthropic=True)
        explicit_session = stable_conversation_id_for_anthropic(request)
        identity = request_identity(conversation_id, explicit_session, request.messages, fallback_account=profile_arn)
        thinking = request.thinking
        if thinking is not None:
            if not isinstance(thinking, dict) or set(thinking) - {"type", "budget_tokens"}:
                raise ValueError("thinking accepts type and budget_tokens; unsupported fields cannot be discarded")
            if thinking.get("type") not in ("enabled", "disabled", "adaptive"):
                raise ValueError("thinking.type must be enabled, disabled, or adaptive")
            if "budget_tokens" in thinking and (type(thinking["budget_tokens"]) is not int or thinking["budget_tokens"] <= 0):
                raise ValueError("thinking.budget_tokens must be a positive integer")
        token = extras.set({
            "native_thinking": thinking.get("type") if thinking is not None else None,
            "thinking_budget": thinking.get("budget_tokens") if thinking is not None else None,
            "max_tokens": request.max_tokens,
            "output_config": getattr(request, "output_config", None),
            "identity": identity,
        })
        try:
            return original_anthropic_to_kiro(request, identity.conversation_id, profile_arn)
        finally:
            extras.reset(token)

    def openai_build_kiro_payload(request_data, conversation_id, profile_arn):
        request_data = _prepare_native_history(request_data, anthropic=False)
        explicit_session = stable_conversation_id_for_openai(request_data)
        identity = request_identity(conversation_id, explicit_session, request_data.messages, fallback_account=profile_arn)
        token = extras.set({
            "max_tokens": request_data.max_completion_tokens if request_data.max_completion_tokens is not None else request_data.max_tokens,
            "output_config": _reasoning_effort_to_output_config(request_data),
            "identity": identity,
        })
        try:
            return original_openai_build(request_data, identity.conversation_id, profile_arn)
        finally:
            extras.reset(token)

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
