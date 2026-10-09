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


class TestSanitizeJsonSchemaStrict:
    """Port of kiro2cc-proxy schema.rs normalization."""

    def test_resolves_defs_ref_and_drops_defs(self):
        schema = {
            "type": "object",
            "properties": {"item": {"$ref": "#/$defs/Item", "description": "the item"}},
            "$defs": {"Item": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
        }
        result = sanitize_json_schema(schema)
        assert "$defs" not in result
        item = result["properties"]["item"]
        assert item["type"] == "object"
        assert item["properties"]["id"] == {"type": "integer"}
        assert item["required"] == ["id"]
        assert item["description"] == "the item"  # sibling key wins

    def test_resolves_definitions_ref(self):
        schema = {
            "properties": {"x": {"$ref": "#/definitions/X"}},
            "definitions": {"X": {"type": "string", "enum": ["a", "b"]}},
        }
        result = sanitize_json_schema(schema)
        assert result["properties"]["x"] == {"type": "string", "enum": ["a", "b"]}
        assert "definitions" not in result

    def test_unresolvable_ref_becomes_permissive_object(self):
        schema = {"type": "object", "properties": {"x": {"$ref": "#/components/schemas/X"}}}
        result = sanitize_json_schema(schema)
        assert result["properties"]["x"] == {"type": "object", "properties": {}}

    def test_cyclic_ref_is_depth_limited(self):
        schema = {
            "properties": {"node": {"$ref": "#/$defs/Node"}},
            "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}},
        }
        result = sanitize_json_schema(schema)
        depth = 0
        node = result["properties"]["node"]
        while "child" in node.get("properties", {}):
            node = node["properties"]["child"]
            depth += 1
        assert 10 <= depth <= 20
        assert node["type"] == "object"

    def test_strips_nulls_and_type_arrays(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": ["null", "string"], "description": None}},
            "required": None,
        }
        result = sanitize_json_schema(schema)
        assert result == {"type": "object", "properties": {"name": {"type": "string"}}}

    def test_properties_null_becomes_dict(self):
        assert sanitize_json_schema({"type": "object", "properties": None}) == {"type": "object", "properties": {}}

    def test_required_filtered_to_known_string_properties(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a", "missing", 3, "a"]}
        assert sanitize_json_schema(schema)["required"] == ["a"]

    def test_combinators_removed(self):
        schema = {"type": "object", "properties": {"v": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}}
        assert sanitize_json_schema(schema)["properties"]["v"] == {}

    def test_single_branch_optional_anyof_is_collapsed(self):
        schema = {"type": "object", "properties": {"v": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "d"}}}
        assert sanitize_json_schema(schema)["properties"]["v"] == {"type": "string", "description": "d"}

    def test_allof_single_ref_is_collapsed(self):
        schema = {
            "properties": {"e": {"allOf": [{"$ref": "#/$defs/E"}]}},
            "$defs": {"E": {"type": "string", "enum": ["x"]}},
        }
        assert sanitize_json_schema(schema)["properties"]["e"] == {"type": "string", "enum": ["x"]}

    def test_whitelists_keys_and_drops_additional_properties(self):
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "T",
            "additionalProperties": False,
            "properties": {"n": {"type": "number", "minimum": 0, "default": 1, "format": "x"}},
        }
        assert sanitize_json_schema(schema) == {"type": "object", "properties": {"n": {"type": "number"}}}

    def test_items_tuple_takes_first_schema(self):
        schema = {"type": "object", "properties": {"l": {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}}}
        assert sanitize_json_schema(schema)["properties"]["l"] == {"type": "array", "items": {"type": "string"}}

    def test_root_forced_to_object(self):
        assert sanitize_json_schema({"type": "string"}) == {"type": "object", "properties": {}}

    def test_enum_keeps_only_scalars(self):
        schema = {"properties": {"e": {"type": "string", "enum": ["a", None, {"x": 1}, 2]}}}
        assert sanitize_json_schema(schema)["properties"]["e"]["enum"] == ["a", 2]

    def test_does_not_mutate_input(self):
        schema = {"properties": {"x": {"$ref": "#/$defs/X"}}, "$defs": {"X": {"type": "string"}}}
        sanitize_json_schema(schema)
        assert schema["properties"]["x"] == {"$ref": "#/$defs/X"}
        assert "$defs" in schema


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

    def test_gateway_additions_go_into_system_pair_and_thinking_tags_into_current(self):
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

    def test_agent_task_type_spectask_with_tools(self):
        cs = _payload([UnifiedMessage(role="user", content="Hi")], tools=[_tool()])["conversationState"]
        assert cs["agentTaskType"] == "spectask"

    def test_agent_task_type_vibe_without_tools(self):
        cs = _payload([UnifiedMessage(role="user", content="Hi")])["conversationState"]
        assert cs["agentTaskType"] == "vibe"
        assert cs["chatTriggerType"] == "MANUAL"

    def test_agent_continuation_id_matches_reference_derivation(self):
        import hashlib
        digest = hashlib.sha256(b"agent-continuation:conv-1").hexdigest()
        expected = f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"
        assert derive_agent_continuation_id("conv-1") == expected
        cs = _payload([UnifiedMessage(role="user", content="Hi")])["conversationState"]
        assert cs["agentContinuationId"] == expected

    def test_agent_continuation_id_is_deterministic_and_distinct(self):
        assert derive_agent_continuation_id("a") == derive_agent_continuation_id("a")
        assert derive_agent_continuation_id("a") != derive_agent_continuation_id("b")
        assert len(derive_agent_continuation_id("a")) == 36


class TestAdditionalModelRequestFields:

    def test_default_effort_and_clamped_max_tokens(self):
        fields = build_additional_model_request_fields("claude-sonnet-4.6", 200000, None)
        assert fields == {"output_config": {"effort": "low"}, "max_tokens": 64000}

    def test_min_max_tokens_is_1024(self):
        fields = build_additional_model_request_fields("claude-sonnet-4.6", 200, None)
        assert fields["max_tokens"] == 1024

    def test_opus_large_cap(self):
        assert model_max_output_tokens("claude-opus-4.7") == 128000
        assert model_max_output_tokens("claude-opus-5") == 128000
        assert model_max_output_tokens("claude-sonnet-5") == 64000
        fields = build_additional_model_request_fields("claude-opus-4.8", 500000, {"effort": "high"})
        assert fields == {"output_config": {"effort": "high"}, "max_tokens": 128000}

    def test_no_max_tokens(self):
        assert build_additional_model_request_fields("claude-sonnet-4.6", None, None) == {
            "output_config": {"effort": "low"}
        }

    def test_skipped_for_45_generation_and_legacy(self):
        assert additional_fields_skipped("claude-sonnet-4.5")
        assert additional_fields_skipped("claude-haiku-4.5")
        assert additional_fields_skipped("claude-opus-4.5")
        assert additional_fields_skipped("claude-3.7-sonnet")
        assert additional_fields_skipped("auto")
        assert not additional_fields_skipped("claude-sonnet-4.6")
        assert build_additional_model_request_fields("claude-sonnet-4.5", 4096, None) is None

    def test_gpt_reasoning_effort(self):
        assert build_additional_model_request_fields("gpt-5.6-sol", 4096, None) == {"reasoning": {"effort": "high"}}
        assert build_additional_model_request_fields("gpt-5.6-sol", 4096, {"effort": "low"}) == {
            "reasoning": {"effort": "low"}
        }

    def test_env_flag_disables(self):
        with patch("extensions.kiro_payload_builder.KIRO_ADDITIONAL_MODEL_FIELDS", False):
            assert build_additional_model_request_fields("claude-sonnet-4.6", 4096, None) is None

    def test_placed_at_payload_top_level(self):
        payload = _payload([UnifiedMessage(role="user", content="Hi")], max_tokens=8192, output_config={"effort": "medium"})
        assert payload["additionalModelRequestFields"] == {"output_config": {"effort": "medium"}, "max_tokens": 8192}
        assert "additionalModelRequestFields" not in payload["conversationState"]

    def test_absent_for_skipped_model(self):
        payload = _payload([UnifiedMessage(role="user", content="Hi")], model_id="claude-sonnet-4.5", max_tokens=8192)
        assert "additionalModelRequestFields" not in payload


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

    def test_never_inject_into_native_models(self):
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

    def test_fallback_stable_and_order_independent(self):
        a = derive_conversation_id(None, "sys", ["b", "a"], "hi")
        b = derive_conversation_id({}, "sys", ["a", "b"], "hi")
        assert a == b
        assert len(a) == 36

    def test_fallback_ignores_billing_header(self):
        a = derive_conversation_id(None, "x-anthropic-billing-header: cc_version=1;\nYou are X", [], "hi")
        b = derive_conversation_id(None, "x-anthropic-billing-header: cc_version=2;\nYou are X", [], "hi")
        assert a == b

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
        "max_tokens": 200000,
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
        assert fields["max_tokens"] == 64000  # clamped to the model cap

    def test_default_effort_when_output_config_missing(self):
        import kiro.routes_anthropic as routes

        payload = routes.anthropic_to_kiro(_anthropic_request(), "rand", "")
        assert payload["additionalModelRequestFields"]["output_config"]["effort"] == "low"

    def test_session_id_becomes_conversation_id(self):
        import kiro.routes_anthropic as routes

        request = _anthropic_request(metadata={"user_id": f"user_abc_account__session_{SESSION}"})
        payload = routes.anthropic_to_kiro(request, "random-id", "")
        assert payload["conversationState"]["conversationId"] == SESSION

    def test_conversation_id_stable_across_turns(self):
        import kiro.routes_anthropic as routes

        turn1 = _anthropic_request()
        turn2 = _anthropic_request(messages=[
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "More"},
        ])
        a = routes.anthropic_to_kiro(turn1, "r1", "")["conversationState"]
        b = routes.anthropic_to_kiro(turn2, "r2", "")["conversationState"]
        assert a["conversationId"] == b["conversationId"]
        assert a["agentContinuationId"] == b["agentContinuationId"]
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

    def test_unmapped_effort_uses_default(self):
        import kiro.routes_openai as routes

        payload = routes.build_kiro_payload(self._request(reasoning_effort="xhigh"), "c", "")
        assert payload["additionalModelRequestFields"]["output_config"]["effort"] == "low"

    def test_no_reasoning_effort_means_no_fake_reasoning(self):
        from kiro.converters_openai import extract_thinking_config_from_openai

        assert extract_thinking_config_from_openai(self._request()).enabled is False
        assert extract_thinking_config_from_openai(self._request(reasoning_effort="high")).enabled is True

    def test_conversation_id_stable_across_turns(self):
        import kiro.routes_openai as routes

        a = routes.build_kiro_payload(self._request(), "r1", "")
        b = routes.build_kiro_payload(self._request(messages=[
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
