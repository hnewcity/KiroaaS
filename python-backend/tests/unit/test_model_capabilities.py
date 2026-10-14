"""Offline tests for model capabilities; synthetic schemas, no gateway imports.

Run with unittest (or pytest --noconftest) to avoid unrelated credential fixtures.
Only the standard library and the new extension are required.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any
import unittest

from extensions.model_capabilities import (
    CapabilityStatus, ModelCapabilities, ModelCapabilityError, TokenLimits,
    build_model_request_fields,
)

MISSING = object()


def model(*, effort: Any = MISSING, thinking: Any = MISSING,
          tokens: Any = MISSING, route: str = "output_config",
          limits: Any = MISSING, model_id: str = "synthetic-model") -> dict[str, Any]:
    """Make a synthetic model with only the specified advertised fields."""
    props: dict[str, Any] = {}
    if effort is not MISSING:
        props[route] = {"type": "object", "properties": {"effort": effort}}
    if thinking is not MISSING:
        props["thinking"] = {"type": "object", "properties": {"type": thinking}}
    if tokens is not MISSING:
        props["max_tokens"] = tokens
    raw: dict[str, Any] = {"modelId": model_id, "additionalModelRequestFieldsSchema": {
        "type": "object", "properties": props,
    }}
    if limits is not MISSING:
        raw["tokenLimits"] = limits
    return raw


def capabilities(**kwargs: Any) -> ModelCapabilities:
    """Parse a synthetic model without importing configuration or a cache."""
    return ModelCapabilities.from_model(model(**kwargs))


class TestCapabilityParsing(unittest.TestCase):
    """Unknown/unsupported distinction, identities, and immutable snapshots."""

    def test_missing_schema_is_unknown_even_with_token_limits(self) -> None:
        """Legacy capacity metadata does not prove a max_tokens transport path."""
        cap = ModelCapabilities.from_model({"modelId": "legacy", "tokenLimits": {"maxOutputTokens": 100}})
        self.assertEqual(cap.schema_status, CapabilityStatus.UNKNOWN)
        for item in (cap.effort, cap.thinking, cap.max_tokens):
            self.assertEqual(item.status, CapabilityStatus.UNKNOWN)
        self.assertEqual(cap.token_limits, TokenLimits(None, 100))
        self.assertIsNone(build_model_request_fields(cap))
        with self.assertRaises(ModelCapabilityError) as caught:
            build_model_request_fields(cap, max_tokens=50)
        self.assertEqual(caught.exception.status, CapabilityStatus.UNKNOWN)
        self.assertIn("unvalidated transport policy", str(caught.exception))

    def test_explicit_empty_schema_is_unsupported_not_unknown(self) -> None:
        """An explicit empty schema advertises no additional fields."""
        for schema in ({}, {"type": "object"}, {"properties": {}}, False):
            with self.subTest(schema=schema):
                cap = ModelCapabilities.from_model({"modelId": "empty", "additionalModelRequestFieldsSchema": schema})
                self.assertEqual(cap.schema_status, CapabilityStatus.UNSUPPORTED)
                for item in (cap.effort, cap.thinking, cap.max_tokens):
                    self.assertEqual(item.status, CapabilityStatus.UNSUPPORTED)
                with self.assertRaises(ModelCapabilityError) as caught:
                    build_model_request_fields(cap, max_tokens=1)
                self.assertEqual(caught.exception.status, CapabilityStatus.UNSUPPORTED)

    def test_null_schema_and_unknown_models_remain_unknown(self) -> None:
        """Familiar-looking names cannot enable hardcoded capabilities."""
        for name in ("new-model", "claude-opus-4.6", "gpt-x", "auto"):
            for raw in (None, {"modelId": name}, {"modelId": name, "additionalModelRequestFieldsSchema": None}):
                with self.subTest(name=name, raw=raw):
                    cap = ModelCapabilities.from_model(raw, model_id=name)
                    self.assertEqual(cap.model_id, name)
                    self.assertEqual(cap.schema_status, CapabilityStatus.UNKNOWN)
                    self.assertIsNone(build_model_request_fields(cap))
                    for args in ({"effort": "none"}, {"thinking": "disabled"}, {"max_tokens": 20}):
                        with self.assertRaises(ModelCapabilityError):
                            build_model_request_fields(cap, **args)

    def test_known_schema_works_for_unknown_model_name(self) -> None:
        """Support comes only from metadata, not a model registry."""
        cap = capabilities(effort={"enum": ["none", "minimal", "xhigh"]}, model_id="never-seen")
        self.assertEqual(build_model_request_fields(cap, effort="minimal"), {"output_config": {"effort": "minimal"}})

    def test_model_identity_and_fallback_validation(self) -> None:
        """Advertised identities win over the optional error-label fallback."""
        self.assertEqual(ModelCapabilities.from_model(None).model_id, "<unknown>")
        self.assertEqual(ModelCapabilities.from_model({}, model_id="fallback").model_id, "fallback")
        self.assertEqual(ModelCapabilities.from_model({"modelId": "actual"}, model_id="fallback").model_id, "actual")
        for raw in ([], "model", 1, True):
            with self.subTest(raw=raw), self.assertRaises(ModelCapabilityError):
                ModelCapabilities.from_model(raw)
        for bad in (None, "", " ", 1, True):
            with self.subTest(bad=bad), self.assertRaises(ModelCapabilityError):
                ModelCapabilities.from_model({"modelId": bad})
        with self.assertRaises(ModelCapabilityError):
            ModelCapabilities.from_model(None, model_id="")

    def test_absent_empty_partial_token_limits_are_distinct(self) -> None:
        """Unknown limit members remain None instead of invented defaults."""
        self.assertIsNone(capabilities().token_limits)
        self.assertIsNone(capabilities(limits=None).token_limits)
        self.assertEqual(capabilities(limits={}).token_limits, TokenLimits())
        self.assertEqual(capabilities(limits={"maxInputTokens": 200}).token_limits, TokenLimits(200, None))
        self.assertEqual(capabilities(limits={"maxOutputTokens": 20}).token_limits, TokenLimits(None, 20))

    def test_raw_inputs_results_and_capabilities_have_no_mutable_aliases(self) -> None:
        """Mutations of source metadata or prior results cannot affect the cache."""
        raw = model(effort={"enum": ["none", "minimal"], "default": "minimal"},
                    thinking={"enum": ["disabled", "adaptive"], "default": "adaptive"},
                    tokens={"type": "integer", "default": 10}, limits={"maxOutputTokens": 100})
        original = deepcopy(raw)
        cap = ModelCapabilities.from_model(raw)
        first = build_model_request_fields(cap)
        self.assertEqual(raw, original)
        first["thinking"]["type"] = "disabled"
        first["max_tokens"] = 90
        raw["additionalModelRequestFieldsSchema"]["properties"]["output_config"]["properties"]["effort"]["enum"].clear()
        raw["tokenLimits"]["maxOutputTokens"] = 1
        self.assertEqual(build_model_request_fields(cap), {
            "output_config": {"effort": "minimal"}, "thinking": {"type": "adaptive"}, "max_tokens": 10})
        with self.assertRaises(FrozenInstanceError):
            cap.model_id = "changed"
        with self.assertRaises(FrozenInstanceError):
            cap.effort.default = "none"
        with self.assertRaises(FrozenInstanceError):
            cap.token_limits.max_output_tokens = 1

    def test_explicit_client_mapping_is_not_mutated_even_on_error(self) -> None:
        """Unsupported thinking objects fail intact instead of losing a budget."""
        cap = capabilities(thinking={"enum": ["enabled", "disabled"]})
        request = {"type": "enabled", "budget_tokens": 1024}
        before = deepcopy(request)
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, thinking=request)
        self.assertEqual(request, before)


class TestEnumRequests(unittest.TestCase):
    """Literal client intent and the observed effort transport paths."""

    def test_defaults_and_explicit_overrides(self) -> None:
        """Only advertised defaults apply, and explicit client values take priority."""
        cap = capabilities(effort={"type": "string", "enum": ["none", "minimal", "high"], "default": "high"},
                           thinking={"enum": ["enabled", "disabled", "adaptive"], "default": "adaptive"},
                           tokens={"type": "integer", "minimum": 1, "maximum": 100, "default": 50})
        self.assertEqual(build_model_request_fields(cap), {
            "output_config": {"effort": "high"}, "thinking": {"type": "adaptive"}, "max_tokens": 50})
        self.assertEqual(build_model_request_fields(cap, effort="none", thinking="disabled", max_tokens=1), {
            "output_config": {"effort": "none"}, "thinking": {"type": "disabled"}, "max_tokens": 1})

    def test_single_choice_or_bound_does_not_imply_default(self) -> None:
        """Even a single allowed value is a constraint, not an advertised default."""
        for effort in ({"enum": ["high"]}, {"const": "high"}):
            with self.subTest(effort=effort):
                cap = capabilities(effort=effort, thinking={"enum": ["adaptive"]}, tokens={"type": "integer", "minimum": 10})
                self.assertIsNone(build_model_request_fields(cap))

    def test_explicit_none_minimal_xhigh_and_future_efforts_are_preserved(self) -> None:
        """Any exact advertised effort string can be emitted on either path."""
        levels = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "future"]
        for route in ("output_config", "reasoning"):
            cap = capabilities(route=route, effort={"enum": levels})
            for value in levels:
                with self.subTest(route=route, value=value):
                    self.assertEqual(build_model_request_fields(cap, effort=value), {route: {"effort": value}})

    def test_unadvertised_effort_aliases_types_and_case_raise(self) -> None:
        """Unsupported intent is never normalized to high or silently removed."""
        cap = capabilities(effort={"enum": ["high"]})
        for value in ("none", "minimal", "xhigh", "HIGH", " high ", "", False, 0, [], {}):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError) as caught:
                build_model_request_fields(cap, effort=value)
            self.assertEqual(caught.exception.field, "effort")
            self.assertIn("high", str(caught.exception))

    def test_effort_path_precedence_matches_cli(self) -> None:
        """output_config wins even if reasoning has a different allowed enum."""
        raw = model(effort={"enum": ["minimal"]})
        raw["additionalModelRequestFieldsSchema"]["properties"]["reasoning"] = {"properties": {"effort": {"enum": ["high"]}}}
        cap = ModelCapabilities.from_model(raw)
        self.assertEqual(cap.effort.path, ("output_config", "effort"))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, effort="high")

    def test_empty_preferred_path_allows_reasoning(self) -> None:
        """An unadvertised output_config.effort does not hide reasoning.effort."""
        raw = model(route="reasoning", effort={"enum": ["none"]})
        raw["additionalModelRequestFieldsSchema"]["properties"]["output_config"] = {"properties": {}}
        self.assertEqual(build_model_request_fields(ModelCapabilities.from_model(raw), effort="none"), {"reasoning": {"effort": "none"}})

    def test_unknown_preferred_path_is_not_bypassed(self) -> None:
        """Do not silently reroute around unrecognized validation constraints."""
        raw = model(effort={"$ref": "#/$defs/effort"})
        raw["additionalModelRequestFieldsSchema"]["properties"]["reasoning"] = {"properties": {"effort": {"enum": ["high"]}}}
        cap = ModelCapabilities.from_model(raw)
        self.assertEqual(cap.effort.status, CapabilityStatus.UNKNOWN)
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, effort="high")

    def test_native_modes_require_individual_advertisement(self) -> None:
        """Enabled support does not require a disabled/adaptive toggle pair."""
        for mode in ("enabled", "disabled", "adaptive"):
            cap = capabilities(thinking={"enum": [mode]})
            self.assertEqual(build_model_request_fields(cap, thinking=mode), {"thinking": {"type": mode}})
            for other in {"enabled", "disabled", "adaptive"} - {mode}:
                with self.subTest(mode=mode, other=other), self.assertRaises(ModelCapabilityError):
                    build_model_request_fields(cap, thinking=other)

    def test_thinking_bool_mapping_or_non_native_modes_raise(self) -> None:
        """No truthiness coercion, ignored budgets, or inferred mode conversions."""
        cap = capabilities(thinking={"enum": ["enabled", "disabled", "adaptive", "future"]})
        for value in (True, False, 0, "on", "off", "ENABLED", "", "future", {}, {"type": "enabled"}):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, thinking=value)

    def test_future_only_native_modes_are_unsupported(self) -> None:
        """An unknown mode does not become implemented just because it is listed."""
        self.assertEqual(capabilities(thinking={"enum": ["future"]}).thinking.status, CapabilityStatus.UNSUPPORTED)
        with self.assertRaises(ModelCapabilityError):
            capabilities(thinking={"enum": ["future"], "default": "future"})

    def test_disabled_thinking_never_silently_downgrades_xhigh_or_max(self) -> None:
        """Explicit values and defaulted values must both obey the incompatibility."""
        for route in ("output_config", "reasoning"):
            for level in ("xhigh", "max"):
                for effort_default, thinking_default in ((False, False), (True, False), (False, True), (True, True)):
                    effort_schema: dict[str, Any] = {"enum": ["none", "high", "xhigh", "max"]}
                    thinking_schema: dict[str, Any] = {"enum": ["disabled", "enabled", "adaptive"]}
                    if effort_default:
                        effort_schema["default"] = level
                    if thinking_default:
                        thinking_schema["default"] = "disabled"
                    cap = capabilities(route=route, effort=effort_schema, thinking=thinking_schema)
                    with self.subTest(route=route, level=level, defaults=(effort_default, thinking_default)), self.assertRaises(ModelCapabilityError) as caught:
                        build_model_request_fields(cap, effort=None if effort_default else level, thinking=None if thinking_default else "disabled")
                    self.assertEqual(caught.exception.field, "effort")
                    self.assertIn("no automatic downgrade", str(caught.exception))

    def test_explicit_override_resolves_default_conflict(self) -> None:
        """The caller may resolve a conflict; the helper cannot choose for them."""
        cap = capabilities(effort={"enum": ["none", "xhigh"], "default": "xhigh"}, thinking={"enum": ["disabled", "adaptive"], "default": "disabled"})
        self.assertEqual(build_model_request_fields(cap, effort="none"), {"output_config": {"effort": "none"}, "thinking": {"type": "disabled"}})
        self.assertEqual(build_model_request_fields(cap, thinking="adaptive"), {"output_config": {"effort": "xhigh"}, "thinking": {"type": "adaptive"}})

    def test_unknown_request_does_not_disappear_beside_supported_fields(self) -> None:
        """A supported effort cannot hide an unverified explicit thinking choice."""
        cap = capabilities(effort={"enum": ["none"]}, thinking={"type": "string"})
        with self.assertRaises(ModelCapabilityError) as caught:
            build_model_request_fields(cap, effort="none", thinking="disabled")
        self.assertEqual(caught.exception.field, "thinking")
        self.assertEqual(caught.exception.status, CapabilityStatus.UNKNOWN)


class TestScalarCombinations(unittest.TestCase):
    """Finite-domain extraction must honor composition, not collect all strings."""

    def test_oneof_anyof_with_enums_and_consts(self) -> None:
        """All finite branch encodings preserve the exact supported values."""
        for kind in ("oneOf", "anyOf"):
            cap = capabilities(effort={kind: [{"const": "none"}, {"enum": ["minimal", "xhigh"]}]})
            self.assertEqual(cap.effort.values, ("none", "minimal", "xhigh"))
            for value in cap.effort.values:
                self.assertEqual(build_model_request_fields(cap, effort=value), {"output_config": {"effort": value}})

    def test_thinking_scalar_union_default(self) -> None:
        """Native thinking uses the same composed enum discovery as effort."""
        cap = capabilities(thinking={"oneOf": [{"const": "disabled"}, {"enum": ["enabled", "adaptive"]}], "default": "adaptive"})
        self.assertEqual(build_model_request_fields(cap), {"thinking": {"type": "adaptive"}})

    def test_oneof_overlap_is_not_valid_anyof_overlap_is(self) -> None:
        """Exactly one branch must match for oneOf; at least one for anyOf."""
        branches = [{"enum": ["none", "high"]}, {"enum": ["high", "xhigh"]}]
        one = capabilities(effort={"oneOf": branches})
        any_ = capabilities(effort={"anyOf": branches})
        self.assertEqual(one.effort.values, ("none", "xhigh"))
        self.assertEqual(any_.effort.values, ("none", "high", "xhigh"))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(one, effort="high")

    def test_nested_allof_and_sibling_enum_intersect(self) -> None:
        """Sibling validators and nested combinations cannot widen the enum."""
        cap = capabilities(effort={"enum": ["none", "minimal", "high"], "allOf": [{"anyOf": [{"const": "none"}, {"const": "minimal"}]}]})
        self.assertEqual(cap.effort.values, ("none", "minimal"))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, effort="high")

    def test_open_union_branch_yields_unknown_not_partial_enum(self) -> None:
        """Incomplete possible-value discovery is never presented as complete."""
        for kind in ("oneOf", "anyOf"):
            cap = capabilities(effort={kind: [{"enum": ["none"]}, {"type": "string"}]})
            self.assertEqual(cap.effort.status, CapabilityStatus.UNKNOWN)
            with self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, effort="none")

    def test_outer_enum_can_bound_open_branches(self) -> None:
        """A complete sibling domain provides candidates for exact validation."""
        cap = capabilities(effort={"enum": ["none", "high"], "oneOf": [{"type": "string"}, {"const": "high"}]})
        self.assertEqual(cap.effort.values, ("none",))

    def test_empty_intersection_is_unsupported(self) -> None:
        """A contradictory enum does not become an unknown capability."""
        cap = capabilities(effort={"enum": ["none"], "const": "high"})
        self.assertEqual(cap.effort.status, CapabilityStatus.UNSUPPORTED)
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, effort="none")

    def test_unambiguous_branch_default_is_used(self) -> None:
        """The overall schema must also accept a default advertised by a branch."""
        cap = capabilities(effort={"oneOf": [{"const": "none"}, {"const": "minimal", "default": "minimal"}]})
        self.assertEqual(build_model_request_fields(cap), {"output_config": {"effort": "minimal"}})

    def test_repeated_identical_anyof_defaults_are_unambiguous(self) -> None:
        """Identical branch annotations are not competing default choices."""
        cap = capabilities(effort={"anyOf": [{"enum": ["none", "high"], "default": "none"}, {"const": "none", "default": "none"}]})
        self.assertEqual(cap.effort.default, "none")

    def test_conflicting_branch_defaults_raise(self) -> None:
        """Branch order cannot decide which default gets sent."""
        with self.assertRaises(ModelCapabilityError) as caught:
            capabilities(effort={"anyOf": [{"const": "none", "default": "none"}, {"const": "high", "default": "high"}]})
        self.assertIn("Conflicting", str(caught.exception))

    def test_outer_default_overrides_conflicting_branch_annotations(self) -> None:
        """An overall advertised default resolves ambiguous branch defaults."""
        cap = capabilities(effort={"anyOf": [{"const": "none", "default": "none"}, {"const": "high", "default": "high"}], "default": "high"})
        self.assertEqual(cap.effort.default, "high")

    def test_default_matching_two_oneof_branches_raises(self) -> None:
        """Being an advertised enum member is insufficient under exact oneOf."""
        with self.assertRaises(ModelCapabilityError):
            capabilities(effort={"oneOf": [{"enum": ["none", "high"]}, {"const": "high"}], "default": "high"})


class TestTokenRequests(unittest.TestCase):
    """Strict integers, metadata ceilings, schema bounds, and exact unions."""

    def test_bounds_include_endpoints_and_never_clamp(self) -> None:
        """Counts outside either bound must fail rather than be rewritten."""
        cap = capabilities(tokens={"type": "integer", "minimum": 16, "maximum": 64})
        self.assertEqual((cap.max_tokens.minimum, cap.max_tokens.maximum), (16, 64))
        for value in (16, 30, 64):
            self.assertEqual(build_model_request_fields(cap, max_tokens=value), {"max_tokens": value})
        for value in (1, 15, 65, 1000):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError) as caught:
                build_model_request_fields(cap, max_tokens=value)
            self.assertIn("never clamped", str(caught.exception))

    def test_bool_float_string_zero_and_negative_counts_raise(self) -> None:
        """bool is not a usable integer token count, even though true == 1."""
        cap = capabilities(tokens={"type": "integer"})
        for value in (True, False, 1.0, 0.5, "10", 0, -1, [], {}, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, max_tokens=value)

    def test_fractional_and_exclusive_numeric_bounds(self) -> None:
        """Derived integer bounds narrow validation, never change caller values."""
        cases = [
            ({"minimum": 1.2, "maximum": 4.8}, (2, 4)),
            ({"exclusiveMinimum": 2, "exclusiveMaximum": 5}, (3, 4)),
            ({"exclusiveMinimum": 1.2, "exclusiveMaximum": 4.8}, (2, 4)),
            ({"minimum": 2, "exclusiveMinimum": 3, "maximum": 8, "exclusiveMaximum": 7}, (4, 6)),
        ]
        for bounds, expected in cases:
            cap = capabilities(tokens={"type": "integer", **bounds})
            with self.subTest(bounds=bounds):
                self.assertEqual((cap.max_tokens.minimum, cap.max_tokens.maximum), expected)
                for value in expected:
                    self.assertEqual(build_model_request_fields(cap, max_tokens=value), {"max_tokens": value})
                for value in (expected[0] - 1, expected[1] + 1):
                    with self.assertRaises(ModelCapabilityError):
                        build_model_request_fields(cap, max_tokens=value)

    def test_output_limit_intersects_schema_but_input_limit_does_not(self) -> None:
        """Input context size is not an output-token ceiling."""
        for schema_max, output_max in ((100, 50), (50, 100)):
            cap = capabilities(tokens={"type": "integer", "maximum": schema_max}, limits={"maxInputTokens": 2, "maxOutputTokens": output_max})
            self.assertEqual(cap.max_tokens.maximum, 50)
            self.assertEqual(build_model_request_fields(cap, max_tokens=50), {"max_tokens": 50})
            with self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, max_tokens=51)
        cap = capabilities(tokens={"type": "integer"}, limits={"maxInputTokens": 2})
        self.assertEqual(build_model_request_fields(cap, max_tokens=100), {"max_tokens": 100})

    def test_output_limit_alone_does_not_prove_transport_support(self) -> None:
        """Capacity and permission to emit an additional field are distinct."""
        cap = capabilities(limits={"maxOutputTokens": 100})
        self.assertEqual(cap.max_tokens.status, CapabilityStatus.UNSUPPORTED)
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, max_tokens=10)

    def test_maximum_is_not_a_token_default(self) -> None:
        """A capacity limit does not allocate a default output budget."""
        cap = capabilities(tokens={"type": "integer", "maximum": 100}, limits={"maxOutputTokens": 50})
        self.assertIsNone(build_model_request_fields(cap))

    def test_number_schema_still_requires_integer_client_count(self) -> None:
        """The public Python int contract remains strict under a number schema."""
        cap = capabilities(tokens={"type": "number", "minimum": 1, "maximum": 10})
        self.assertEqual(build_model_request_fields(cap, max_tokens=3), {"max_tokens": 3})
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, max_tokens=3.0)

    def test_integer_enum_and_union_gaps_are_not_permitted(self) -> None:
        """Being within the min/max envelope does not satisfy every enum/union."""
        for schema in (
            {"type": "integer", "enum": [2, 4, 8]},
            {"type": "integer", "anyOf": [{"minimum": 2, "maximum": 4}, {"minimum": 8, "maximum": 10}]},
        ):
            cap = capabilities(tokens=schema)
            for value in (2, 8):
                self.assertEqual(build_model_request_fields(cap, max_tokens=value), {"max_tokens": value})
            with self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, max_tokens=6)

    def test_integer_oneof_excludes_overlap(self) -> None:
        """Matching two interval branches is invalid under oneOf."""
        cap = capabilities(tokens={"type": "integer", "oneOf": [{"minimum": 1, "maximum": 5}, {"minimum": 3, "maximum": 8}]})
        for value in (1, 2, 6, 8):
            self.assertEqual(build_model_request_fields(cap, max_tokens=value), {"max_tokens": value})
        for value in (3, 4, 5):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, max_tokens=value)

    def test_integer_allof_bounds_intersect(self) -> None:
        """Both sibling and allOf bounds remain in effect."""
        cap = capabilities(tokens={"type": "integer", "maximum": 20, "allOf": [{"minimum": 5}, {"maximum": 10}]})
        self.assertEqual((cap.max_tokens.minimum, cap.max_tokens.maximum), (5, 10))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, max_tokens=4)

    def test_impossible_numeric_bounds_are_errors(self) -> None:
        """An empty positive-integer domain is not repaired by raising limits."""
        for schema, limits in (
            ({"minimum": 20, "maximum": 10}, {}), ({"minimum": 20}, {"maxOutputTokens": 10}),
            ({"maximum": 0}, {}), ({"exclusiveMinimum": 1, "exclusiveMaximum": 2}, {}),
            ({"enum": [True]}, {}),
        ):
            with self.subTest(schema=schema, limits=limits), self.assertRaises(ModelCapabilityError):
                capabilities(tokens={"type": "integer", **schema}, limits=limits)

    def test_invalid_token_defaults_raise_at_parse(self) -> None:
        """Bad metadata defaults cannot produce invalid requests on omission."""
        for value in (True, False, 0, -1, 1.0, "3", None, 11):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError):
                capabilities(tokens={"type": "integer", "minimum": 2, "maximum": 10, "default": value})
        with self.assertRaises(ModelCapabilityError):
            capabilities(tokens={"type": "integer", "default": 20}, limits={"maxOutputTokens": 10})

    def test_integral_json_enum_numbers_accept_integer_requests(self) -> None:
        """JSON numeric equality does not confuse 2.0 with a float client request."""
        cap = capabilities(tokens={"type": "integer", "enum": [2.0, 4.0]})
        self.assertEqual(build_model_request_fields(cap, max_tokens=2), {"max_tokens": 2})
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, max_tokens=2.0)

    def test_explicit_false_token_schema_is_unsupported(self) -> None:
        """An explicit prohibition differs from both malformed and missing metadata."""
        cap = capabilities(tokens=False)
        self.assertEqual(cap.max_tokens.status, CapabilityStatus.UNSUPPORTED)
        with self.assertRaises(ModelCapabilityError) as caught:
            build_model_request_fields(cap, max_tokens=2)
        self.assertEqual(caught.exception.status, CapabilityStatus.UNSUPPORTED)

    def test_huge_integer_counts_do_not_overflow(self) -> None:
        """Finite Python ints need no lossy float conversion."""
        value = 10 ** 400
        cap = capabilities(tokens={"type": "integer", "minimum": value, "maximum": value})
        self.assertEqual(build_model_request_fields(cap, max_tokens=value), {"max_tokens": value})


class TestUnknownAndMalformedSchemas(unittest.TestCase):
    """Conservative schema coverage, required fields, and actionable failures."""

    def test_unknown_object_constraints_block_defaults_and_requests(self) -> None:
        """Partial parsing never ignores root validation requirements."""
        for addition in (
            {"$ref": "#/$defs/model"}, {"oneOf": [{"properties": {}}]}, {"anyOf": [{"properties": {}}]},
            {"if": {}, "then": {}}, {"default": {"max_tokens": 10}},
            {"dependentRequired": {"max_tokens": ["foo"]}}, {"additionalProperties": {"type": "integer"}},
        ):
            raw = model(tokens={"type": "integer", "default": 10})
            raw["additionalModelRequestFieldsSchema"].update(addition)
            cap = ModelCapabilities.from_model(raw)
            with self.subTest(addition=addition):
                self.assertEqual(cap.schema_status, CapabilityStatus.UNKNOWN)
                self.assertIsNone(build_model_request_fields(cap))
                with self.assertRaises(ModelCapabilityError):
                    build_model_request_fields(cap, max_tokens=10)

    def test_allow_all_boolean_schema_is_unknown(self) -> None:
        """An unrestricted schema does not advertise named request fields."""
        cap = ModelCapabilities.from_model({"additionalModelRequestFieldsSchema": True})
        self.assertEqual(cap.schema_status, CapabilityStatus.UNKNOWN)
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, effort="none")

    def test_unknown_scalar_constraints_do_not_hide_other_fields(self) -> None:
        """Only the locally unrecognized capability loses support."""
        for addition in ({"pattern": "high"}, {"$ref": "#/$defs/effort"}, {"not": {"const": "none"}}, {"enum": [{"value": "high"}]}):
            cap = capabilities(effort={"enum": ["none", "high"], "default": "high", **addition}, thinking={"enum": ["disabled"]})
            with self.subTest(addition=addition):
                self.assertEqual(cap.effort.status, CapabilityStatus.UNKNOWN)
                self.assertEqual(build_model_request_fields(cap, thinking="disabled"), {"thinking": {"type": "disabled"}})
                with self.assertRaises(ModelCapabilityError):
                    build_model_request_fields(cap, effort="high")

    def test_unknown_branch_constraints_are_not_ignored(self) -> None:
        """Unknown branch validation prevents incomplete enum discovery."""
        cap = capabilities(effort={"anyOf": [{"const": "none"}, {"enum": ["high"], "pattern": "high"}]})
        self.assertEqual(cap.effort.status, CapabilityStatus.UNKNOWN)
        self.assertIsNone(build_model_request_fields(cap))

    def test_unknown_numeric_constraint_is_not_ignored(self) -> None:
        """Unsupported multipleOf cannot silently accept odd token counts."""
        cap = capabilities(tokens={"type": "integer", "multipleOf": 2, "default": 10})
        self.assertEqual(cap.max_tokens.status, CapabilityStatus.UNKNOWN)
        self.assertIsNone(build_model_request_fields(cap))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, max_tokens=3)

    def test_empty_scalar_schema_is_unknown_not_unrestricted(self) -> None:
        """A named but unconstrained field is distinct from an absent field."""
        cap = capabilities(effort={}, thinking={}, tokens={})
        for item in (cap.effort, cap.thinking, cap.max_tokens):
            self.assertEqual(item.status, CapabilityStatus.UNKNOWN)
        self.assertIsNone(build_model_request_fields(cap))

    def test_required_thinking_budget_is_never_invented(self) -> None:
        """The mode-only API rejects a missing required thinking budget."""
        raw = model(thinking={"enum": ["enabled", "disabled"]})
        raw["additionalModelRequestFieldsSchema"]["properties"]["thinking"]["required"] = ["type", "budget_tokens"]
        cap = ModelCapabilities.from_model(raw)
        with self.assertRaises(ModelCapabilityError) as caught:
            build_model_request_fields(cap, thinking="enabled")
        self.assertEqual(caught.exception.field, "thinking.budget_tokens")
        self.assertIn("will not be invented", str(caught.exception))

    def test_required_root_members_only_apply_when_object_is_emitted(self) -> None:
        """No output remains None; a partially filled output must be valid."""
        raw = model(effort={"enum": ["none"]}, tokens={"type": "integer"})
        raw["additionalModelRequestFieldsSchema"]["required"] = ["max_tokens"]
        cap = ModelCapabilities.from_model(raw)
        self.assertIsNone(build_model_request_fields(cap))
        with self.assertRaises(ModelCapabilityError) as caught:
            build_model_request_fields(cap, effort="none")
        self.assertEqual(caught.exception.field, "max_tokens")
        self.assertEqual(build_model_request_fields(cap, effort="none", max_tokens=1), {"output_config": {"effort": "none"}, "max_tokens": 1})

    def test_required_unrelated_fields_are_not_silently_dropped(self) -> None:
        """Errors identify required fields outside this bounded adapter's API."""
        raw = model(tokens={"type": "integer", "default": 10})
        raw["additionalModelRequestFieldsSchema"]["required"] = ["other"]
        with self.assertRaises(ModelCapabilityError) as caught:
            build_model_request_fields(ModelCapabilities.from_model(raw))
        self.assertEqual(caught.exception.field, "other")

    def test_nested_object_combinations_are_explicitly_unknown(self) -> None:
        """Object unions are deliberately outside the supported scalar subset."""
        raw = model(thinking={"enum": ["enabled", "disabled"], "default": "enabled"})
        raw["additionalModelRequestFieldsSchema"]["properties"]["thinking"]["oneOf"] = [{"required": ["budget_tokens"]}]
        cap = ModelCapabilities.from_model(raw)
        self.assertEqual(cap.thinking.status, CapabilityStatus.UNKNOWN)
        self.assertIsNone(build_model_request_fields(cap))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, thinking="disabled")

    def test_annotations_do_not_hide_fields(self) -> None:
        """Descriptions/titles/examples do not add validation constraints."""
        cap = capabilities(effort={"enum": ["none"], "description": "effort", "title": "Effort", "examples": ["none"]})
        self.assertEqual(build_model_request_fields(cap, effort="none"), {"output_config": {"effort": "none"}})

    def test_malformed_root_and_nested_objects_raise_with_context(self) -> None:
        """Malformed schemas are errors, not permission to ignore client fields."""
        for schema in ([], "{}", 0, 4.5, {1: {}}, {"properties": []}, {"properties": None}, {"required": "x"}, {"required": [1]}, {"required": ["x", "x"]}):
            with self.subTest(schema=schema), self.assertRaises(ModelCapabilityError) as caught:
                ModelCapabilities.from_model({"modelId": "broken", "additionalModelRequestFieldsSchema": schema})
            self.assertEqual(caught.exception.model_id, "broken")
            self.assertEqual(caught.exception.field, "additionalModelRequestFieldsSchema")
        raw = model()
        raw["additionalModelRequestFieldsSchema"]["properties"]["thinking"] = None
        with self.assertRaises(ModelCapabilityError):
            ModelCapabilities.from_model(raw)

    def test_malformed_scalar_keywords_raise(self) -> None:
        """Malformed supported keywords cannot be treated as absent capability."""
        for schema in (None, [], "string", 1, {"enum": []}, {"enum": "high"}, {"enum": None}, {"enum": [True]}, {"enum": [""]}, {"type": None}, {"type": []}, {"type": "wrong"}, {"anyOf": []}, {"oneOf": {}}, {"allOf": [None]}):
            with self.subTest(schema=schema), self.assertRaises(ModelCapabilityError):
                capabilities(effort=schema)

    def test_invalid_enum_defaults_raise(self) -> None:
        """Defaults must be supported nonempty string values."""
        for value in ("low", "", None, False, 2):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError):
                capabilities(effort={"enum": ["high"], "default": value})

    def test_malformed_bounds_and_token_limits_raise(self) -> None:
        """Booleans/non-finite values are not numbers for these metadata fields."""
        for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            for value in (True, False, None, "10", float("nan"), float("inf"), []):
                with self.subTest(key=key, value=value), self.assertRaises(ModelCapabilityError):
                    capabilities(tokens={"type": "integer", key: value})
        for key in ("maxInputTokens", "maxOutputTokens"):
            for value in (True, False, None, 0, -1, 1.0, "10", []):
                with self.subTest(key=key, value=value), self.assertRaises(ModelCapabilityError):
                    capabilities(limits={key: value})
        for raw in ([], "{}", True, 1):
            with self.subTest(raw=raw), self.assertRaises(ModelCapabilityError):
                capabilities(limits=raw)

    def test_recursive_and_deep_schemas_fail_boundedly(self) -> None:
        """Untrusted in-memory metadata cannot cause unbounded recursion."""
        cyclic: dict[str, Any] = {}
        cyclic["anyOf"] = [cyclic]
        with self.assertRaises(ModelCapabilityError) as caught:
            capabilities(effort=cyclic)
        self.assertIn("deeply nested", str(caught.exception))
        nested: dict[str, Any] = {"const": "high"}
        for _ in range(40):
            nested = {"anyOf": [nested]}
        with self.assertRaises(ModelCapabilityError):
            capabilities(effort=nested)

    def test_error_contract_has_model_field_and_action(self) -> None:
        """Transport adapters can distinguish policy errors from valid output."""
        cap = capabilities(effort={"enum": ["minimal"]}, model_id="my-model")
        with self.assertRaises(ValueError) as caught:
            build_model_request_fields(cap, effort="xhigh")
        self.assertIsInstance(caught.exception, ModelCapabilityError)
        self.assertEqual(caught.exception.model_id, "my-model")
        self.assertEqual(caught.exception.field, "effort")
        self.assertIn("Use an advertised value", str(caught.exception))
        self.assertIn("my-model", str(caught.exception))
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(None, effort="none")


if __name__ == "__main__":
    unittest.main()

class TestAdvertisedThinkingBudget(unittest.TestCase):
    """Budget-bearing thinking uses its own advertised bounds and required fields."""

    def _model(self) -> dict:
        raw = model(thinking={"enum": ["enabled", "disabled", "adaptive"]}, tokens={"type": "integer", "minimum": 1, "maximum": 10000})
        raw["additionalModelRequestFieldsSchema"]["properties"]["thinking"]["properties"]["budget_tokens"] = {"type": "integer", "minimum": 256, "maximum": 4096}
        return raw

    def test_exact_budget_is_preserved(self) -> None:
        cap = ModelCapabilities.from_model(self._model())
        self.assertEqual(build_model_request_fields(cap, thinking="enabled", thinking_budget=1024, max_tokens=8192), {
            "thinking": {"type": "enabled", "budget_tokens": 1024}, "max_tokens": 8192,
        })

    def test_out_of_bounds_budget_never_clamped(self) -> None:
        cap = ModelCapabilities.from_model(self._model())
        for value in (255, 4097, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ModelCapabilityError):
                build_model_request_fields(cap, thinking="enabled", thinking_budget=value)

    def test_disabled_thinking_does_not_silently_discard_budget(self) -> None:
        cap = ModelCapabilities.from_model(self._model())
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, thinking="disabled", thinking_budget=1024)

    def test_required_budget_succeeds_only_when_supplied(self) -> None:
        raw = self._model()
        raw["additionalModelRequestFieldsSchema"]["properties"]["thinking"]["required"] = ["type", "budget_tokens"]
        cap = ModelCapabilities.from_model(raw)
        with self.assertRaises(ModelCapabilityError):
            build_model_request_fields(cap, thinking="enabled")
        self.assertEqual(build_model_request_fields(cap, thinking="enabled", thinking_budget=256)["thinking"]["budget_tokens"], 256)
