"""
Tests for the payload builder extension (port of the kiro-gateway fork's
converters_core / payload_guards / converters_* changes in 61d9b68 + dc0fe43).

The classes below are the fork's tests, pointed at extensions.kiro_payload_builder.
The extension is installed for the whole module, so tests that go through
kiro.converters_core / kiro.converters_anthropic exercise the patched pipeline
exactly as app_entry wires it.
"""

import json
from unittest.mock import patch

import pytest

from extensions.kiro_payload_builder import (
    build_kiro_payload,
    derive_conversation_id,
    extract_session_id,
    inject_thinking_tags,
    install_kiro_payload_builder,
    model_has_native_reasoning,
    sanitize_json_schema,
    should_inject_thinking,
    trim_payload_to_limit,
    uninstall_kiro_payload_builder,
)
from kiro.converters_core import ThinkingConfig, UnifiedMessage, UnifiedTool


def _advertised_model(model_id, *, effort_path="output_config", default_effort="low", output_limit=64000):
    """Synthetic metadata, not a capture or a claim about the named cloud model."""
    return {"modelId": model_id, "additionalModelRequestFieldsSchema": {
        "type": "object", "properties": {
            effort_path: {"type": "object", "properties": {"effort": {
                "type": "string", "enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max"], "default": default_effort,
            }}},
            "thinking": {"type": "object", "properties": {
                "type": {"type": "string", "enum": ["enabled", "disabled", "adaptive"]},
                "budget_tokens": {"type": "integer", "minimum": 1, "maximum": output_limit},
            }},
            "max_tokens": {"type": "integer", "minimum": 1, "maximum": output_limit},
        },
    }}


@pytest.fixture(autouse=True)
def advertised_account_metadata():
    from kiro.cache import ModelInfoCache
    from extensions.request_context import start_request_state, reset_request_state

    state, token = start_request_state()
    # Direct converter unit calls below represent distinct requests. Real route
    # tests use the middleware's managed budget and selection hook instead.
    state.retry_budget = None
    cache = ModelInfoCache()
    cache._cache = {name: _advertised_model(name, output_limit=limit) for name, limit in (
        ("claude-sonnet-4.6", 64000), ("claude-opus-4.6", 64000),
        ("claude-opus-4.7", 128000), ("claude-opus-4.8", 128000),
        ("claude-opus-5.5", 128000), ("claude-sonnet-5", 64000),
    )}
    cache._cache["gpt-5.6-sol"] = _advertised_model("gpt-5.6-sol", effort_path="reasoning", default_effort="high")
    for name in ("claude-sonnet-4", "claude-sonnet-4.5", "claude-haiku-4.5", "claude-3.7-sonnet", "auto-kiro", "deepseek-3.2"):
        cache._cache[name] = {"modelId": name, "additionalModelRequestFieldsSchema": {}}
    state.model_cache = cache
    try:
        yield cache
    finally:
        reset_request_state(token)


@pytest.fixture(autouse=True)
def installed():
    uninstall_kiro_payload_builder()
    install_kiro_payload_builder()
    yield
    uninstall_kiro_payload_builder()


from extensions.kiro_payload_builder import (  # noqa: E402
    additional_fields_skipped,
    build_additional_model_request_fields,
    derive_agent_continuation_id,
    drop_trailing_assistant_messages,
    model_max_output_tokens,
)


def _payload(messages, tools=None, system_prompt="", model_id="claude-sonnet-4.6", **kwargs):
    """Build a payload with gateway system additions disabled for deterministic output."""
    with patch("kiro.converters_core.FAKE_REASONING_ENABLED", False), \
            patch("kiro.config.TRUNCATION_RECOVERY", False):
        return build_kiro_payload(
            messages=messages,
            system_prompt=system_prompt,
            model_id=model_id,
            tools=tools,
            conversation_id="conv-1",
            profile_arn="",
            thinking_config=ThinkingConfig(enabled=False),
            **kwargs,
        ).payload


def _tool(name="shell"):
    return UnifiedTool(name=name, description="d", input_schema={"type": "object", "properties": {}})


def _call(tool_id, name="shell"):
    return {"id": tool_id, "type": "function", "function": {"name": name, "arguments": "{}"}}


def _result(tool_id, content="ok"):
    return {"type": "tool_result", "tool_use_id": tool_id, "content": content}


class TestSanitizeJsonSchemaContract:
    """The installed payload path must preserve the standalone schema contract."""

    def test_references_and_recursive_definitions_survive(self):
        schema = {
            "type": "object",
            "properties": {"node": {"$ref": "#/$defs/Node"}},
            "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}},
        }
        assert sanitize_json_schema(schema) == schema

    def test_unknown_refs_are_not_replaced_by_permissive_objects(self):
        schema = {"properties": {"x": {"$ref": "#/components/schemas/X"}}}
        assert sanitize_json_schema(schema) == schema

    def test_constraints_union_and_boolean_schemas_survive(self):
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "n": {"type": "integer", "minimum": 1, "maximum": 9},
                "tag": {"const": "fixed"},
                "union": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                "nullable": {"type": ["string", "null"]},
                "denied": False,
            },
        }
        assert sanitize_json_schema(schema) == schema

    def test_invalid_required_is_actionable(self):
        with pytest.raises(ValueError, match="required"):
            sanitize_json_schema({"type": "object", "required": ["a", 3]})
        assert sanitize_json_schema({"type": "object", "required": ["missing", "missing"]})["required"] == ["missing"]

    def test_tuple_items_and_enum_values_survive(self):
        schema = {"type": "array", "items": [{"type": "string"}, {"enum": [None, {"x": 1}]}]}
        assert sanitize_json_schema(schema) == schema

    def test_missing_schema_has_object_convention(self):
        assert sanitize_json_schema(None) == {"type": "object", "properties": {}}
        assert sanitize_json_schema({}) == {"type": "object", "properties": {}}

    def test_root_type_is_not_silently_rewritten(self):
        assert sanitize_json_schema({"type": "string"}) == {"type": "string"}

    def test_caller_schema_not_mutated(self):
        schema = {"title": "Root", "type": "object", "properties": {"x": {"minimum": 2}}}
        normalized = sanitize_json_schema(schema)
        normalized["properties"]["x"]["minimum"] = 10
        assert schema["properties"]["x"]["minimum"] == 2
        assert schema["title"] == "Root"


class TestPlaceholderToolSpecs:

    def test_adds_placeholder_for_history_only_tool(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1", "old_tool")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
        ]
        payload = _payload(messages, tools=[_tool("shell")])
        tools = payload["conversationState"]["currentMessage"]["userInputMessage"]["userInputMessageContext"]["tools"]
        names = [t["toolSpecification"]["name"] for t in tools]
        assert names == ["shell", "old_tool"]
        placeholder = tools[1]["toolSpecification"]
        assert placeholder["description"] == "Tool used in conversation history"
        assert placeholder["inputSchema"]["json"] == {"type": "object", "properties": {}}

    def test_case_insensitive_match_adds_no_placeholder(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1", "SHELL")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
        ]
        payload = _payload(messages, tools=[_tool("shell")])
        tools = payload["conversationState"]["currentMessage"]["userInputMessage"]["userInputMessageContext"]["tools"]
        assert len(tools) == 1

    def test_no_tools_still_strips_tool_content(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1", "old_tool")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
        ]
        payload = _payload(messages, tools=None)
        current = payload["conversationState"]["currentMessage"]["userInputMessage"]
        assert "userInputMessageContext" not in current
        assert "[Tool Result (t1)]" in current["content"]


class TestToolPairingCleanup:

    def test_drops_tool_use_without_result(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="calling", tool_calls=[_call("t1"), _call("t2")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
            UnifiedMessage(role="assistant", content="done"),
            UnifiedMessage(role="user", content="next"),
        ]
        history = _payload(messages, tools=[_tool()])["conversationState"]["history"]
        tool_uses = history[1]["assistantResponseMessage"]["toolUses"]
        assert [tu["toolUseId"] for tu in tool_uses] == ["t1"]

    def test_keeps_last_assistant_tool_uses_answered_by_current(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
        ]
        cs = _payload(messages, tools=[_tool()])["conversationState"]
        assert cs["history"][-1]["assistantResponseMessage"]["toolUses"][0]["toolUseId"] == "t1"
        current = cs["currentMessage"]["userInputMessage"]
        assert current["userInputMessageContext"]["toolResults"][0]["toolUseId"] == "t1"
        assert current["content"] == "(tool result above)"

    def test_all_tool_uses_removed_leaves_valid_content(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1")]),
            UnifiedMessage(role="user", content="never mind"),
        ]
        history = _payload(messages, tools=[_tool()])["conversationState"]["history"]
        assistant = history[1]["assistantResponseMessage"]
        assert "toolUses" not in assistant
        assert assistant["content"].strip()

    def test_duplicate_tool_result_dropped(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1"), _result("t1", "again")]),
        ]
        current = _payload(messages, tools=[_tool()])["conversationState"]["currentMessage"]["userInputMessage"]
        results = current["userInputMessageContext"]["toolResults"]
        assert len(results) == 1
        assert results[0]["content"][0]["text"] == "ok"

    def test_result_for_earlier_turn_tool_use_becomes_text(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t2")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t2"), _result("t1", "stale")]),
        ]
        current = _payload(messages, tools=[_tool()])["conversationState"]["currentMessage"]["userInputMessage"]
        assert [r["toolUseId"] for r in current["userInputMessageContext"]["toolResults"]] == ["t2"]
        assert "stale" not in current["content"]  # already answered -> duplicate, dropped

    def test_orphan_result_without_any_tool_use_becomes_text(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1"), _result("ghost", "ghost data")]),
        ]
        current = _payload(messages, tools=[_tool()])["conversationState"]["currentMessage"]["userInputMessage"]
        assert [r["toolUseId"] for r in current["userInputMessageContext"]["toolResults"]] == ["t1"]
        assert "[Tool Result (ghost)]" in current["content"]
        assert "ghost data" in current["content"]


class TestPlaceholderSemantics:

    def test_history_user_with_only_tool_results(self):
        messages = [
            UnifiedMessage(role="user", content="go"),
            UnifiedMessage(role="assistant", content="", tool_calls=[_call("t1")]),
            UnifiedMessage(role="user", content="", tool_results=[_result("t1")]),
            UnifiedMessage(role="assistant", content="done"),
            UnifiedMessage(role="user", content="thanks"),
        ]
        history = _payload(messages, tools=[_tool()])["conversationState"]["history"]
        assert history[1]["assistantResponseMessage"]["content"] == " "
        assert history[2]["userInputMessage"]["content"] == "(tool result above)"

    def test_trailing_assistant_prefill_dropped(self):
        messages = [
            UnifiedMessage(role="user", content="Hello"),
            UnifiedMessage(role="assistant", content="{"),
        ]
        cs = _payload(messages)["conversationState"]
        assert cs["currentMessage"]["userInputMessage"]["content"] == "Hello"
        assert "history" not in cs

    def test_drop_trailing_assistant_keeps_assistant_only_list(self):
        messages = [UnifiedMessage(role="assistant", content="hi")]
        assert drop_trailing_assistant_messages(messages) == messages

    def test_assistant_only_conversation_still_builds(self):
        cs = _payload([UnifiedMessage(role="assistant", content="hi")])["conversationState"]
        assert cs["history"][-1]["assistantResponseMessage"]["content"] == "hi"
        assert cs["currentMessage"]["userInputMessage"]["content"] == "(empty placeholder)"

    def test_truly_empty_current_message_fallback(self):
        cs = _payload([UnifiedMessage(role="user", content="")])["conversationState"]
        assert cs["currentMessage"]["userInputMessage"]["content"] == "(empty placeholder)"


class TestSystemPromptPair:

    def test_single_turn_system_pair(self):
        cs = _payload([UnifiedMessage(role="user", content="Hi")], system_prompt="Be nice")["conversationState"]
        assert cs["history"] == [
            {"userInputMessage": {"content": "Be nice", "modelId": "claude-sonnet-4.6", "origin": "AI_EDITOR"}},
            {"assistantResponseMessage": {"content": "I will follow these instructions."}},
        ]
        assert cs["currentMessage"]["userInputMessage"]["content"] == "Hi"

    def test_multi_turn_system_pair_and_alternation(self):
        messages = [
            UnifiedMessage(role="user", content="Q1"),
            UnifiedMessage(role="assistant", content="A1"),
            UnifiedMessage(role="user", content="Q2"),
        ]
        history = _payload(messages, system_prompt="Sys")["conversationState"]["history"]
        roles = ["user" if "userInputMessage" in h else "assistant" for h in history]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert history[0]["userInputMessage"]["content"] == "Sys"
        assert history[2]["userInputMessage"]["content"] == "Q1"

    def test_no_system_prompt_no_pair(self):
        cs = _payload([UnifiedMessage(role="user", content="Hi")])["conversationState"]
        assert "history" not in cs

    def test_prefix_is_stable_across_turns(self):
        turn1 = _payload([UnifiedMessage(role="user", content="Q1")], system_prompt="Sys")
        turn2 = _payload([
            UnifiedMessage(role="user", content="Q1"),
            UnifiedMessage(role="assistant", content="A1"),
            UnifiedMessage(role="user", content="Q2"),
        ], system_prompt="Sys")
        assert turn1["conversationState"]["history"][:2] == turn2["conversationState"]["history"][:2]

    def test_gateway_additions_go_into_system_pair_and_thinking_tags_into_current(self, monkeypatch):
        monkeypatch.setenv("KIRO_LEGACY_FAKE_REASONING", "true")
        with patch("kiro.converters_core.FAKE_REASONING_ENABLED", True):
            payload = build_kiro_payload(
                messages=[UnifiedMessage(role="user", content="Hi")],
                system_prompt="Sys",
                model_id="claude-sonnet-4.5",
                tools=None,
                conversation_id="c",
                profile_arn="",
                thinking_config=ThinkingConfig(enabled=True, budget_tokens=1000),
            ).payload
        cs = payload["conversationState"]
        assert "Sys" in cs["history"][0]["userInputMessage"]["content"]
        assert "Extended Thinking Mode" in cs["history"][0]["userInputMessage"]["content"]
        current = cs["currentMessage"]["userInputMessage"]["content"]
        assert current.startswith("<thinking_mode>enabled</thinking_mode>")
        assert current.endswith("Hi")

    def test_trim_keeps_system_pair(self):
        messages = []
        for i in range(10):
            messages.append(UnifiedMessage(role="user", content=f"u{i} " + "x" * 500))
            messages.append(UnifiedMessage(role="assistant", content=f"a{i} " + "y" * 500))
        messages.append(UnifiedMessage(role="user", content="now"))
        with patch("kiro.converters_core.AUTO_TRIM_PAYLOAD", True), \
                patch("kiro.converters_core.KIRO_MAX_PAYLOAD_BYTES", 4000):
            history = _payload(messages, system_prompt="Sys")["conversationState"]["history"]
        assert history[0]["userInputMessage"]["content"] == "Sys"
        assert history[1]["assistantResponseMessage"]["content"] == "I will follow these instructions."
        assert "userInputMessage" in history[2]
        assert len(history) < 22


class TestEnvelopeFields:

    def test_tools_do_not_select_spec_task(self):
        cs = _payload([UnifiedMessage(role="user", content="Hi")], tools=[_tool()])["conversationState"]
        assert cs["agentTaskType"] == "vibe"

    def test_agent_task_type_vibe_without_tools(self):
        cs = _payload([UnifiedMessage(role="user", content="Hi")])["conversationState"]
        assert cs["agentTaskType"] == "vibe"
        assert cs["chatTriggerType"] == "MANUAL"

    def test_anonymous_execution_id_is_not_derived_from_conversation(self):
        import uuid
        cs = _payload([UnifiedMessage(role="user", content="Hi")])["conversationState"]
        assert str(uuid.UUID(cs["agentContinuationId"])) == cs["agentContinuationId"]
        assert cs["rootConversationId"] == cs["conversationId"]
        assert derive_agent_continuation_id("conv-1") != cs["agentContinuationId"]

    def test_new_anonymous_execution_ids_are_distinct(self):
        assert derive_agent_continuation_id("a") != derive_agent_continuation_id("a")
        assert len(derive_agent_continuation_id("a")) == 36


class TestAdditionalModelRequestFields:
    def test_advertised_default_and_exact_output_limit(self):
        assert build_additional_model_request_fields("claude-sonnet-4.6", 8192) == {
            "output_config": {"effort": "low"}, "max_tokens": 8192,
        }
        with pytest.raises(ValueError, match="never clamped"):
            build_additional_model_request_fields("claude-sonnet-4.6", 200000)

    def test_small_output_limit_not_silently_raised(self):
        assert build_additional_model_request_fields("claude-sonnet-4.6", 64)["max_tokens"] == 64

    def test_caps_are_metadata_not_model_generation(self, advertised_account_metadata):
        assert model_max_output_tokens("claude-opus-4.7") == 128000
        advertised_account_metadata._cache["claude-opus-4.7"] = _advertised_model("claude-opus-4.7", output_limit=2500)
        assert model_max_output_tokens("claude-opus-4.7") == 2500
        with pytest.raises(ValueError):
            build_additional_model_request_fields("claude-opus-4.7", 4096)

    def test_effort_passthrough(self):
        for effort in ("none", "minimal", "medium", "xhigh"):
            assert build_additional_model_request_fields("claude-sonnet-4.6", 4096, {"effort": effort})["output_config"]["effort"] == effort

    def test_known_unsupported_fields_are_errors_not_silently_omitted(self):
        assert build_additional_model_request_fields("claude-sonnet-4.5") is None
        with pytest.raises(ValueError, match="unsupported"):
            build_additional_model_request_fields("claude-sonnet-4.5", 8192)

    def test_unknown_metadata_not_guessed_from_name(self):
        assert build_additional_model_request_fields("claude-opus-100") is None
        assert model_max_output_tokens("claude-opus-100") is None
        with pytest.raises(ValueError, match="unknown"):
            build_additional_model_request_fields("claude-opus-100", 64)

    def test_reasoning_path_and_tokens_follow_metadata(self):
        assert build_additional_model_request_fields("gpt-5.6-sol", 4096, {"effort": "low"}) == {
            "reasoning": {"effort": "low"}, "max_tokens": 4096,
        }

    def test_disabled_fields_reject_explicit_intent(self):
        with patch("extensions.kiro_payload_builder.KIRO_ADDITIONAL_MODEL_FIELDS", False):
            assert build_additional_model_request_fields("claude-sonnet-4.6") is None
            with pytest.raises(ValueError, match="disabled"):
                build_additional_model_request_fields("claude-sonnet-4.6", 4096)

    def test_placed_at_payload_top_level(self):
        payload = _payload([UnifiedMessage(role="user", content="Hi")], max_tokens=8192, output_config={"effort": "medium"})
        assert payload["additionalModelRequestFields"] == {"output_config": {"effort": "medium"}, "max_tokens": 8192}
        assert "additionalModelRequestFields" not in payload["conversationState"]

    def test_native_thinking_and_budget_are_not_discarded(self):
        assert build_additional_model_request_fields("claude-sonnet-4.6", 4096, native_thinking="enabled", thinking_budget=1024)["thinking"] == {"type": "enabled", "budget_tokens": 1024}
        with pytest.raises(ValueError, match="disabled thinking"):
            build_additional_model_request_fields("claude-sonnet-4.6", 4096, native_thinking="disabled", thinking_budget=1024)


# ==================================================================================================
# payload_guards: pairing repair and prefix-preserving trim
# ==================================================================================================

def _make_payload(num_pairs=5, content_size=100):
    """Helper: build a minimal Kiro-shaped payload with N user/assistant pairs."""
    history = []
    for i in range(num_pairs):
        history.append({
            "userInputMessage": {"content": f"user message {i} " + "x" * content_size}
        })
        history.append({
            "assistantResponseMessage": {"content": f"assistant message {i} " + "y" * content_size}
        })
    return {
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": "test-conv",
            "currentMessage": {
                "userInputMessage": {"content": "current message", "modelId": "test"}
            },
            "history": history,
        },
        "profileArn": "arn:aws:test",
    }



class TestRepairToolPairing:

    def test_removes_unanswered_tool_use_and_keeps_current(self):
        from extensions.kiro_payload_builder import repair_tool_pairing
        history = [
            {"userInputMessage": {"content": "go"}},
            {"assistantResponseMessage": {"content": "x", "toolUses": [
                {"toolUseId": "a", "name": "t"}, {"toolUseId": "b", "name": "t"}]}},
        ]
        kept, orphan_text = repair_tool_pairing(history, [{"toolUseId": "a", "content": [{"text": "r"}]}])
        assert [r["toolUseId"] for r in kept] == ["a"]
        assert orphan_text == ""
        assert [tu["toolUseId"] for tu in history[1]["assistantResponseMessage"]["toolUses"]] == ["a"]

    def test_history_orphan_replaces_tool_result_hint(self):
        from extensions.kiro_payload_builder import repair_tool_pairing
        history = [
            {"userInputMessage": {"content": "go"}},
            {"assistantResponseMessage": {"content": "no tools"}},
            {"userInputMessage": {"content": "(tool result above)", "userInputMessageContext": {
                "toolResults": [{"toolUseId": "z", "content": [{"text": "zzz"}]}]}}},
            {"assistantResponseMessage": {"content": "ok"}},
        ]
        repair_tool_pairing(history, None)
        user = history[2]["userInputMessage"]
        assert "userInputMessageContext" not in user
        assert user["content"] == "[Tool Result (z)]\nzzz"


class TestTrimKeepsPrefix:

    def test_keep_prefix_entries(self):
        payload = _make_payload(num_pairs=10, content_size=500)
        history = payload["conversationState"]["history"]
        first_two = [dict(history[0]), dict(history[1])]
        trim_payload_to_limit(payload, max_bytes=3000, keep_prefix_entries=2)
        assert history[:2] == first_two
        assert "userInputMessage" in history[2]
        assert len(history) < 20


class TestAdditionalFieldsGating:
    @pytest.mark.parametrize("model,skipped", [
        ("claude-sonnet-4", True),        # verified live: Kiro rejects with REQUEST_BODY_INVALID
        ("claude-sonnet-4.5", True),
        ("claude-sonnet-4-5-20250929", True),
        ("claude-haiku-4.5", True),
        ("claude-3.7-sonnet", True),
        ("claude-opus-4.6", False),
        ("claude-opus-4.7", False),
        ("claude-sonnet-5", False),
        ("auto-kiro", True),
        ("deepseek-3.2", True),
    ])
    def test_version_gate(self, model, skipped):
        from extensions.kiro_payload_builder import additional_fields_skipped

        assert additional_fields_skipped(model) is skipped


class TestThinkingPolicy:
    @pytest.mark.parametrize("model,native", [
        ("claude-opus-5.5", True), ("claude-sonnet-4.6", True), ("claude-opus-4.7", True),
        ("gpt-5.6-sol", True), ("claude-sonnet-4.5", False), ("claude-haiku-4.5", False),
        ("claude-sonnet-4", False), ("deepseek-3.2", False),
    ])
    def test_native_reasoning(self, model, native):
        assert model_has_native_reasoning(model) is native

    def test_never_inject_into_native_models(self, monkeypatch):
        monkeypatch.setenv("KIRO_LEGACY_FAKE_REASONING", "true")
        cfg = ThinkingConfig(enabled=True, budget_tokens=8000)
        with patch("kiro.converters_core.FAKE_REASONING_ENABLED", True):
            assert inject_thinking_tags("Hi", cfg, "claude-opus-5.5") == "Hi"
            assert not should_inject_thinking(cfg, "claude-opus-5.5")
            assert should_inject_thinking(cfg, "claude-sonnet-4.5")

    def test_native_model_payload_has_no_thinking_text(self):
        from kiro.converters_core import UnifiedMessage

        with patch("kiro.converters_core.FAKE_REASONING_ENABLED", True):
            payload = build_kiro_payload(
                messages=[UnifiedMessage(role="user", content="Hi")], system_prompt="Sys",
                model_id="claude-opus-5.5", tools=None, conversation_id="c", profile_arn="",
                thinking_config=ThinkingConfig(enabled=True, budget_tokens=8000),
                output_config={"effort": "high"},
            ).payload
        dumped = json.dumps(payload)
        assert "thinking_mode" not in dumped
        assert "Extended Thinking Mode" not in dumped
        assert payload["additionalModelRequestFields"]["output_config"]["effort"] == "high"

    @pytest.mark.parametrize("thinking,expected", [
        (None, False), ({"type": "adaptive"}, False), ({"type": "disabled"}, False),
        ({"type": "enabled", "budget_tokens": 2000}, True),
    ])
    def test_anthropic_explicit_mode(self, thinking, expected):
        from kiro.converters_anthropic import extract_thinking_config_from_anthropic
        from kiro.models_anthropic import AnthropicMessagesRequest

        body = {"model": "claude-sonnet-4.5", "max_tokens": 64, "messages": [{"role": "user", "content": "x"}]}
        if thinking:
            body["thinking"] = thinking
        assert extract_thinking_config_from_anthropic(AnthropicMessagesRequest(**body)).enabled is expected

    def test_always_mode_restores_legacy(self, monkeypatch):
        from kiro.converters_anthropic import extract_thinking_config_from_anthropic
        from kiro.models_anthropic import AnthropicMessagesRequest

        monkeypatch.setattr("extensions.kiro_payload_builder.FAKE_REASONING_MODE", "always")
        req = AnthropicMessagesRequest(model="claude-sonnet-4.5", max_tokens=64, messages=[{"role": "user", "content": "x"}])
        assert extract_thinking_config_from_anthropic(req).enabled is True


class TestConversationId:
    SESSION = "1b2c3d4e-0000-4000-8000-000000000000"

    @pytest.mark.parametrize("user_id", [
        SESSION,
        SESSION.upper(),
        json.dumps({"session_id": SESSION, "device_id": "d"}),
        json.dumps({"id": SESSION}),
        f"user_abc_account__session_{SESSION}",
    ])
    def test_extract_session(self, user_id):
        assert extract_session_id(user_id) == self.SESSION

    @pytest.mark.parametrize("user_id", [None, "", "user_abc", '{"session_id": "nope"}', "{bad json"])
    def test_extract_none(self, user_id):
        assert extract_session_id(user_id) is None

    def test_session_wins(self):
        assert derive_conversation_id({"user_id": self.SESSION}, "sys", ["a"], "hi") == self.SESSION

    def test_anonymous_sessions_are_independent_even_with_same_prompt(self):
        a = derive_conversation_id(None, "sys", ["b", "a"], "hi")
        b = derive_conversation_id({}, "sys", ["a", "b"], "hi")
        assert a != b
        assert len(a) == 36

    def test_anonymous_sessions_do_not_use_billing_header_hashes(self):
        a = derive_conversation_id(None, "x-anthropic-billing-header: cc_version=1;\nYou are X", [], "hi")
        b = derive_conversation_id(None, "x-anthropic-billing-header: cc_version=2;\nYou are X", [], "hi")
        assert a != b

    def test_fallback_differs_by_first_message(self):
        assert derive_conversation_id(None, "s", [], "hi") != derive_conversation_id(None, "s", [], "yo")


# ==================================================================================================
# Adapters as the routes call them (kiro.routes_* globals)
# ==================================================================================================

SESSION = "1b2c3d4e-0000-4000-8000-000000000000"


def _anthropic_request(**overrides):
    from kiro.models_anthropic import AnthropicMessagesRequest

    body = {
        "model": "claude-sonnet-4.6",
        "max_tokens": 8192,
        "system": "You are X",
        "messages": [{"role": "user", "content": "Hi"}],
    }
    body.update(overrides)
    return AnthropicMessagesRequest(**body)


class TestAnthropicAdapter:
    def test_output_config_and_max_tokens_forwarded(self):
        import kiro.routes_anthropic as routes

        payload = routes.anthropic_to_kiro(_anthropic_request(output_config={"effort": "high"}), "rand", "")
        fields = payload["additionalModelRequestFields"]
        assert fields["output_config"]["effort"] == "high"
        assert fields["max_tokens"] == 8192  # exact client value, not a model-name cap

    def test_default_effort_when_output_config_missing(self):
        import kiro.routes_anthropic as routes

        payload = routes.anthropic_to_kiro(_anthropic_request(), "rand", "")
        assert payload["additionalModelRequestFields"]["output_config"]["effort"] == "low"

    def test_session_id_becomes_conversation_id(self):
        import kiro.routes_anthropic as routes

        request = _anthropic_request(metadata={"user_id": f"user_abc_account__session_{SESSION}"})
        payload = routes.anthropic_to_kiro(request, "random-id", "")
        again = routes.anthropic_to_kiro(request, "another-random-id", "")
        assert payload["conversationState"]["conversationId"] == again["conversationState"]["conversationId"]
        assert payload["conversationState"]["rootConversationId"] == payload["conversationState"]["conversationId"]

    def test_conversation_id_stable_across_turns(self):
        import kiro.routes_anthropic as routes

        turn1 = _anthropic_request(metadata={"user_id": SESSION})
        turn2 = _anthropic_request(metadata={"user_id": SESSION}, messages=[
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "More"},
        ])
        a = routes.anthropic_to_kiro(turn1, "r1", "")["conversationState"]
        b = routes.anthropic_to_kiro(turn2, "r2", "")["conversationState"]
        assert a["conversationId"] == b["conversationId"]
        assert a["agentContinuationId"] != b["agentContinuationId"]
        # system pair is a byte-stable prefix
        assert a["history"][:2] == b["history"][:2]

    def test_stable_id_toggle(self, monkeypatch):
        import extensions.kiro_payload_builder as builder
        import kiro.routes_anthropic as routes

        monkeypatch.setattr(builder, "STABLE_CONVERSATION_ID", False)
        payload = routes.anthropic_to_kiro(_anthropic_request(), "random-id", "")
        assert payload["conversationState"]["conversationId"] == "random-id"

    def test_extras_do_not_leak_between_requests(self):
        import kiro.converters_core as core

        import kiro.routes_anthropic as routes

        routes.anthropic_to_kiro(_anthropic_request(output_config={"effort": "high"}), "r", "")
        # A direct core call afterwards must not inherit the previous request's effort
        result = core.build_kiro_payload(
            messages=[UnifiedMessage(role="user", content="Hi")], system_prompt="",
            model_id="claude-sonnet-4.6", tools=None, conversation_id="c", profile_arn="",
            thinking_config=ThinkingConfig(enabled=False),
        )
        assert result.payload["additionalModelRequestFields"]["output_config"]["effort"] == "low"


class TestOpenAIAdapter:
    def _request(self, **overrides):
        from kiro.models_openai import ChatCompletionRequest

        body = {"model": "claude-sonnet-4.6", "messages": [{"role": "user", "content": "Hi"}]}
        body.update(overrides)
        return ChatCompletionRequest(**body)

    def test_reasoning_effort_and_max_tokens(self):
        import kiro.routes_openai as routes

        payload = routes.build_kiro_payload(self._request(reasoning_effort="medium", max_tokens=2000), "c", "")
        fields = payload["additionalModelRequestFields"]
        assert fields == {"output_config": {"effort": "medium"}, "max_tokens": 2000}

    def test_xhigh_effort_is_not_replaced_by_default(self):
        import kiro.routes_openai as routes

        payload = routes.build_kiro_payload(self._request(reasoning_effort="xhigh"), "c", "")
        assert payload["additionalModelRequestFields"]["output_config"]["effort"] == "xhigh"

    def test_no_reasoning_effort_means_no_fake_reasoning(self):
        from kiro.converters_openai import extract_thinking_config_from_openai

        assert extract_thinking_config_from_openai(self._request()).enabled is False
        assert extract_thinking_config_from_openai(self._request(reasoning_effort="high")).enabled is True

    def test_conversation_id_stable_across_turns(self):
        import kiro.routes_openai as routes

        a = routes.build_kiro_payload(self._request(user=SESSION), "r1", "")
        b = routes.build_kiro_payload(self._request(user=SESSION, messages=[
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "More"},
        ]), "r2", "")
        assert a["conversationState"]["conversationId"] == b["conversationState"]["conversationId"]


class TestComposesWithToolNameAliasing:
    def test_long_tool_name_is_aliased_in_payload(self):
        from extensions.tool_name_alias import install_tool_name_aliasing, uninstall_tool_name_aliasing

        uninstall_kiro_payload_builder()
        install_tool_name_aliasing()
        install_kiro_payload_builder()
        try:
            long_name = "mcp__server__" + "x" * 80
            tool = UnifiedTool(name=long_name, description="d", input_schema={"type": "object", "properties": {}})
            payload = build_kiro_payload(
                messages=[UnifiedMessage(role="user", content="Hi")], system_prompt="",
                model_id="claude-sonnet-4.6", tools=[tool], conversation_id="c", profile_arn="",
                thinking_config=ThinkingConfig(enabled=False),
            ).payload
            names = [t["toolSpecification"]["name"] for t in
                     payload["conversationState"]["currentMessage"]["userInputMessage"]["userInputMessageContext"]["tools"]]
            assert len(names) == 1 and len(names[0]) <= 64 and names[0] != long_name
        finally:
            uninstall_kiro_payload_builder()
            uninstall_tool_name_aliasing()
            install_kiro_payload_builder()


def test_uninstall_restores_upstream():
    import kiro.converters_core as core
    import kiro.routes_anthropic as routes

    uninstall_kiro_payload_builder()
    assert core.build_kiro_payload.__module__ == "kiro.converters_core"
    assert routes.anthropic_to_kiro.__module__ == "kiro.converters_anthropic"
    install_kiro_payload_builder()
    assert core.build_kiro_payload is build_kiro_payload
