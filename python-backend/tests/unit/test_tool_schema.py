"""Offline adversarial tests for the independent tool-schema normalizer.

Run without application/auth fixtures:
    python -B -m pytest --confcutdir=tests/unit -p no:cacheprovider \
        tests/unit/test_tool_schema.py -q
"""

from __future__ import annotations

from copy import deepcopy
import json
import socket
from typing import Any
from urllib.parse import quote

import pytest

from extensions import tool_schema
from extensions.tool_schema import ToolSchemaNormalizationError, normalize_tool_schema


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block socket networking even when application conftest is excluded."""
    def blocked(*args: Any, **kwargs: Any) -> Any:
        """Fail immediately if normalization unexpectedly attempts network I/O."""
        raise AssertionError("Tool schema tests must be entirely offline")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def nullable_array(**constraints: Any) -> dict[str, Any]:
    """Build a small eligible array-or-null wrapper for test cases."""
    return {"anyOf": [{"type": "array", **constraints}, {"type": "null"}]}


def tool_with_ref(ref: str, wrapper: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an object with one array candidate and a separate reference user."""
    return {"type": "object", "properties": {
        "values": nullable_array(items={"type": "integer", "minimum": 2}) if wrapper is None else wrapper,
        "other": {"$ref": ref},
    }}


class TestToolSchemaSuccess:
    """CLI-compatible repairs without loss of ordinary validation keywords."""

    @pytest.mark.parametrize("schema", [None, {}])
    def test_absent_schema_has_fresh_object_default(self, schema: Any) -> None:
        """What: default missing tools. Purpose: match the CLI's empty contract."""
        result = normalize_tool_schema(schema)
        assert result == {"type": "object", "properties": {}}
        result["properties"]["new"] = True
        assert normalize_tool_schema(schema) == {"type": "object", "properties": {}}

    def test_only_known_root_annotations_are_removed(self) -> None:
        """What: strip three root annotations. Purpose: retain real constraints."""
        schema = {
            "title": "Tool", "default": {}, "examples": [{}], "description": "Kept",
            "type": "object", "additionalProperties": False, "minProperties": 1,
            "properties": {"n": {"title": "Number", "default": 3, "examples": [2, 4],
                                  "type": "integer", "minimum": 2, "maximum": 4,
                                  "exclusiveMinimum": 1, "exclusiveMaximum": 5,
                                  "multipleOf": 1, "const": 3}},
            "$defs": {"unused": {"type": "number", "maximum": 42}},
            "definitions": {"legacy": False},
        }
        expected = deepcopy(schema)
        for key in ("title", "default", "examples"):
            del expected[key]
        assert normalize_tool_schema(schema) == expected

    @pytest.mark.parametrize("schema", [
        {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "string"}]},
        {"$ref": "#/$defs/value", "$defs": {"value": {"type": "integer"}}},
        {"const": 5}, {"enum": [False, 0, None]}, {"minimum": -10, "maximum": 10},
        {"properties": {"a": True}, "additionalProperties": False},
        {"not": {}}, {"type": ["string", "null"]},
    ])
    def test_nonempty_root_is_never_narrowed_to_object(self, schema: dict[str, Any]) -> None:
        """What: preserve non-object roots. Purpose: avoid CLI type injection."""
        assert normalize_tool_schema(schema) == schema

    @pytest.mark.parametrize("required", [None, "x", 1, False, {"x": True}])
    def test_malformed_root_required_is_removed(self, required: Any) -> None:
        """What: remove non-list required. Purpose: reproduce a targeted CLI repair."""
        assert normalize_tool_schema({"type": "object", "required": required}) == {"type": "object"}

    def test_required_deduplicates_without_filtering_undeclared_names(self) -> None:
        """What: preserve required intent. Purpose: undeclared properties are legal."""
        schema = {"properties": {"known": True}, "required": ["未知", "known", "未知", "", "__proto__"]}
        assert normalize_tool_schema(schema)["required"] == ["未知", "known", "", "__proto__"]
        assert schema["required"] == ["未知", "known", "未知", "", "__proto__"]
        assert normalize_tool_schema({"required": []}) == {"required": []}

    def test_boolean_schemas_and_combinators_survive(self) -> None:
        """What: retain boolean branches. Purpose: never replace false with an object."""
        schema = {"type": "object", "properties": {"deny": False, "allow": True},
                  "additionalProperties": False, "unevaluatedProperties": False,
                  "allOf": [True, {"not": False}], "oneOf": [False, {"const": {}}],
                  "anyOf": [{"required": ["deny"]}, {"required": ["allow"]}],
                  "if": {"required": ["allow"]}, "then": True, "else": False,
                  "dependentSchemas": {"allow": False}, "dependentRequired": {"allow": ["deny"]},
                  "dependencies": {"deny": ["allow"], "allow": {"minProperties": 2}},
                  "propertyNames": {"minLength": 1}, "patternProperties": {"^x": False}}
        assert normalize_tool_schema(schema) == schema

    def test_unicode_and_prototype_like_property_names_remain_literal(self) -> None:
        """What: keep arbitrary keys. Purpose: names must not be treated as keywords."""
        names = ["anyOf", "required", "properties", "__proto__", "constructor", "prototype",
                 "", "工具/名字~", "😀", "line\u2028separator", "x%2Fy"]
        schema = {"type": "object", "properties": {name: {"type": "string"} for name in names},
                  "required": names}
        assert normalize_tool_schema(schema) == schema

    def test_does_not_normalize_instance_data_or_unknown_extensions(self) -> None:
        """What: keep schema-looking data. Purpose: const/default are not applicators."""
        data = {"anyOf": [{"type": "array"}, {"type": "null"}], "required": None}
        schema = {"type": "object", "properties": {
            "data": {"const": data, "default": data, "examples": [data], "x-schema": data},
        }, "x-extension": data}
        assert normalize_tool_schema(schema) == schema

    def test_full_deep_copy_and_shared_input_aliases(self) -> None:
        """What: detach every output container. Purpose: prevent mutation and alias leaks."""
        shared = nullable_array(items={"enum": [1, 2, 3]})
        schema = {"type": "object", "properties": {"a": shared, "b": shared}}
        before = deepcopy(schema)
        result = normalize_tool_schema(schema)
        assert schema == before
        result["properties"]["a"]["items"]["enum"].append(4)
        assert result["properties"]["b"]["items"]["enum"] == [1, 2, 3]
        assert schema == before

    @pytest.mark.parametrize("schema", [
        {"title": "Only metadata"}, {"required": None},
        {"properties": {"v": nullable_array()}},
        {"$defs": {"node": {"properties": {"child": {"$ref": "#/$defs/node"}}}}, "$ref": "#/$defs/node"},
    ])
    def test_normalization_is_idempotent(self, schema: dict[str, Any]) -> None:
        """What: repeat normalization. Purpose: integration may pass a schema twice."""
        result = normalize_tool_schema(schema)
        assert normalize_tool_schema(result) == result


class TestNullableArrayNormalization:
    """Only proven-equivalent nullable wrappers are collapsed."""

    def test_preserves_all_array_constraints_and_numeric_item_bounds(self) -> None:
        """What: lift a constrained array. Purpose: no constraint weakening."""
        branch = {"type": ["array"], "minItems": 1, "maxItems": 8, "uniqueItems": True,
                  "items": {"type": "number", "minimum": -2, "maximum": 7, "multipleOf": 0.5},
                  "contains": {"const": 3}, "minContains": 1, "maxContains": 2,
                  "prefixItems": [False, {"const": 2}], "unevaluatedItems": False,
                  "additionalItems": False, "description": "inner", "default": [3]}
        schema = {"properties": {"values": {"anyOf": [branch, {"type": "null"}]}}}
        expected = {**branch, "type": ["array", "null"]}
        assert normalize_tool_schema(schema)["properties"]["values"] == expected

    @pytest.mark.parametrize("branch", [
        {"type": "array", "const": []}, {"type": "array", "enum": [[], [1]]},
        {"type": "array", "allOf": [{"maxItems": 1}]},
        {"type": "array", "anyOf": [{"const": []}]},
        {"type": "array", "oneOf": [{"minItems": 1}]},
        {"type": "array", "not": {"type": "null"}},
        {"type": "array", "if": {"type": "null"}, "then": False},
        {"type": "array", "$ref": "#/$defs/array"},
        {"type": "array", "x-constraint": True},
        {"type": "array", "format": "custom-array-only-format"},
    ])
    def test_general_assertions_prevent_unsafe_type_widening(self, branch: dict[str, Any]) -> None:
        """What: keep const/enum/ref unions. Purpose: widening type alone rejects null."""
        schema = {"$defs": {"array": {"type": "array"}},
                  "properties": {"value": {"anyOf": [branch, {"type": "null"}]}}}
        assert normalize_tool_schema(schema) == schema

    @pytest.mark.parametrize("wrapper", [
        {"anyOf": [{"type": "array"}, {"type": "string"}, {"type": "null"}]},
        {"anyOf": [{"type": "array"}, {"type": "array", "minItems": 1}]},
        {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        {"oneOf": [{"type": "array"}, {"type": "null"}]},
        {"anyOf": [True, {"type": "array"}, {"type": "null"}]},
        {"anyOf": [{"type": "array"}, {"type": "null", "const": 1}]},
        {"anyOf": [{"type": "array"}, {"type": "null"}], "const": []},
        {"anyOf": [{"type": "array"}, {"type": "null"}], "default": None},
        {"anyOf": [{"type": "array"}, {"type": "null"}], "additionalProperties": False},
        {"anyOf": [{"type": ["array", "null"]}, {"type": "null"}]},
    ])
    def test_ambiguous_or_constrained_wrapper_is_retained(self, wrapper: dict[str, Any]) -> None:
        """What: retain uncertain unions. Purpose: never arbitrarily select a branch."""
        schema = {"properties": {"value": wrapper}}
        assert normalize_tool_schema(schema) == schema

    def test_nested_wrappers_and_metadata_precedence(self) -> None:
        """What: flatten eligible nesting. Purpose: match CLI inner-first annotations."""
        wrapper = {"anyOf": [False, {"not": {}}, {"anyOf": [
            {"type": "array", "title": "branch", "items": False}, {"type": "null"}],
            "description": "inner", "title": "inner title"}],
            "description": "outer", "title": "outer title"}
        assert normalize_tool_schema({"properties": {"v": wrapper}})["properties"]["v"] == {
            "type": ["array", "null"], "title": "branch", "items": False, "description": "inner"}

    def test_single_real_branch_without_null_does_not_add_null(self) -> None:
        """What: lift a singleton anyOf. Purpose: do not introduce null accidentally."""
        schema = {"properties": {"v": {"anyOf": [{"type": ["array"], "items": True}, {"not": {}}],
                                           "description": "outer"}}}
        assert normalize_tool_schema(schema)["properties"]["v"] == {
            "type": ["array"], "items": True, "description": "outer"}

    @pytest.mark.parametrize("keyword", ["$defs", "definitions", "properties", "patternProperties", "dependentSchemas"])
    def test_map_subschema_positions_are_normalized(self, keyword: str) -> None:
        """What: normalize values, not map keys. Purpose: respect schema grammar."""
        assert normalize_tool_schema({keyword: {"anyOf": nullable_array()}}) == {
            keyword: {"anyOf": {"type": ["array", "null"]}}}

    @pytest.mark.parametrize("keyword", ["items", "additionalProperties", "unevaluatedProperties", "propertyNames",
                                          "contains", "additionalItems", "unevaluatedItems", "not", "if", "then", "else", "contentSchema"])
    def test_single_subschema_positions_are_normalized(self, keyword: str) -> None:
        """What: normalize standalone subschemas. Purpose: cover each grammar position."""
        assert normalize_tool_schema({keyword: nullable_array()}) == {keyword: {"type": ["array", "null"]}}

    @pytest.mark.parametrize("keyword", ["items", "prefixItems", "allOf", "anyOf", "oneOf"])
    def test_array_subschema_positions_are_normalized(self, keyword: str) -> None:
        """What: keep outer combinators. Purpose: normalize only their eligible children."""
        assert normalize_tool_schema({keyword: [nullable_array(), False]}) == {
            keyword: [{"type": ["array", "null"]}, False]}

    def test_schema_dependencies_are_normalized_but_required_lists_are_not(self) -> None:
        """What: distinguish legacy dependency forms. Purpose: no data traversal."""
        assert normalize_tool_schema({"dependencies": {"a": nullable_array(), "b": ["anyOf"]}}) == {
            "dependencies": {"a": {"type": ["array", "null"]}, "b": ["anyOf"]}}


class TestToolSchemaReferences:
    """Reference integrity, pointer escaping, recursion and adversarial targets."""

    @pytest.mark.parametrize("ref", [
        "#/properties/values/anyOf/0/items", "#/properties/values/anyOf/0%2Fitems",
        "#%2Fproperties%2Fvalues%2FanyOf%2F0%2Fitems",
    ])
    def test_reference_to_retained_child_is_relocated(self, ref: str) -> None:
        """What: move child pointers. Purpose: no dangling references after a collapse."""
        result = normalize_tool_schema(tool_with_ref(ref))
        assert result["properties"]["other"]["$ref"] == "#/properties/values/items"
        assert result["properties"]["values"] == {
            "type": ["array", "null"], "items": {"type": "integer", "minimum": 2}}

    @pytest.mark.parametrize("ref", [
        "#/properties/values/anyOf/0", "#/properties/values/anyOf/1",
        "#/properties/values/anyOf", "#/properties/values/anyOf/0/type",
    ])
    def test_refs_to_widened_or_removed_targets_prevent_collapse(self, ref: str) -> None:
        """What: protect original targets. Purpose: branch-root nullability must not widen."""
        schema = tool_with_ref(ref)
        assert normalize_tool_schema(schema) == schema

    def test_ref_to_wrapper_remains_valid(self) -> None:
        """What: keep wrapper identity. Purpose: semantically identical targets can move internally."""
        result = normalize_tool_schema(tool_with_ref("#/properties/values"))
        assert result["properties"]["other"]["$ref"] == "#/properties/values"
        assert result["properties"]["values"]["type"] == ["array", "null"]

    def test_nonnullable_branch_root_can_move_without_widening(self) -> None:
        """What: move a nonnullable branch ref. Purpose: distinguish identity from widening."""
        wrapper = {"anyOf": [{"type": "array", "items": False}, {"not": {}}]}
        result = normalize_tool_schema(tool_with_ref("#/properties/values/anyOf/0", wrapper))
        assert result["properties"]["other"]["$ref"] == "#/properties/values"
        assert result["properties"]["values"] == {"type": "array", "items": False}

    def test_ref_to_intermediate_wrapper_keeps_its_location(self) -> None:
        """What: protect an intermediate wrapper. Purpose: a flattening cannot erase its ref target."""
        wrapper = {"anyOf": [nullable_array(items=True), {"not": {}}]}
        schema = tool_with_ref("#/properties/values/anyOf/0", wrapper)
        result = normalize_tool_schema(schema)
        assert result["properties"]["values"] == {
            "anyOf": [{"type": ["array", "null"], "items": True}, {"not": {}}]}
        assert result["properties"]["other"]["$ref"] == "#/properties/values/anyOf/0"
        assert normalize_tool_schema(result) == result

    def test_ref_to_discardable_false_branch_prevents_its_deletion(self) -> None:
        """What: keep a referenced false schema. Purpose: impossible alternatives may be shared."""
        wrapper = {"anyOf": [{"not": {}}, {"type": "array"}, {"type": "null"}]}
        schema = tool_with_ref("#/properties/values/anyOf/0", wrapper)
        assert normalize_tool_schema(schema) == schema

    def test_longest_prefix_relocation_handles_nested_collapses(self) -> None:
        """What: compose ancestor moves. Purpose: refs retain the deepest selected target."""
        schema = tool_with_ref("#/properties/values/anyOf/0/items/anyOf/0/items",
                               nullable_array(items=nullable_array(items={"const": 2})))
        result = normalize_tool_schema(schema)
        assert result["properties"]["other"]["$ref"] == "#/properties/values/items/items"
        assert result["properties"]["values"]["items"] == {
            "type": ["array", "null"], "items": {"const": 2}}

    def test_reference_prefixes_compare_tokens_not_string_prefixes(self) -> None:
        """What: separate sibling names. Purpose: valuesExtra must not freeze values."""
        schema = tool_with_ref("#/properties/valuesExtra/anyOf/0")
        schema["properties"]["valuesExtra"] = nullable_array()
        result = normalize_tool_schema(schema)
        assert result["properties"]["values"]["type"] == ["array", "null"]
        assert result["properties"]["valuesExtra"] == schema["properties"]["valuesExtra"]

    @pytest.mark.parametrize("name", ["", "工具/名~😀", "~1", "%2F", "__proto__", "a b", "line\u2028separator"])
    def test_relocation_escapes_unicode_slashes_tildes_and_percent_once(self, name: str) -> None:
        """What: relocate arbitrary property names. Purpose: preserve literal pointer tokens."""
        token = quote(name.replace("~", "~0").replace("/", "~1"), safe="$~")
        schema = {"properties": {name: nullable_array(items=False),
                                 "user": {"$ref": f"#/properties/{token}/anyOf/0/items"}}}
        result = normalize_tool_schema(schema)
        assert result["properties"]["user"]["$ref"] == f"#/properties/{token}/items"
        assert result["properties"][name] == {"type": ["array", "null"], "items": False}

    @pytest.mark.parametrize("ref", ["#", "#/$defs/node"])
    def test_recursive_references_are_preserved_without_expansion(self, ref: str) -> None:
        """What: retain recursion. Purpose: JSON references are not Python container cycles."""
        schema = {"$defs": {"node": {"properties": {
            "children": nullable_array(items={"$ref": ref})}}}, "$ref": "#/$defs/node"}
        result = normalize_tool_schema(schema)
        children = result["$defs"]["node"]["properties"]["children"]
        assert children == {"type": ["array", "null"], "items": {"$ref": ref}}
        assert result["$ref"] == "#/$defs/node"

    def test_recursive_branch_root_blocks_nullable_widening(self) -> None:
        """What: guard self-referencing branch roots. Purpose: no recursion semantic changes."""
        schema = {"properties": {"value": nullable_array(items={"$ref": "#/properties/value/anyOf/0"})}}
        assert normalize_tool_schema(schema) == schema

    def test_mutually_recursive_refs_and_siblings_remain_opaque(self) -> None:
        """What: preserve a recursive graph. Purpose: never inline refs or drop siblings."""
        schema = {"$defs": {"a": {"$ref": "#/$defs/b", "minimum": 1},
                            "b": {"$ref": "#/$defs/a", "maximum": 5}},
                  "$ref": "#/$defs/a", "const": 3}
        assert normalize_tool_schema(schema) == schema

    @pytest.mark.parametrize("ref", [
        "#/missing", "#/properties/values/anyOf/999", "#/properties/values/anyOf/00/items",
        "#/properties/values/anyOf/-1", "#/properties/values/anyOf/١", "#/foo~2bar",
        "#/%ZZ", "#/%FF", "#anchor", "", "other.json#/items",
        "https://schemas.invalid/remote#/$defs/value", "file:///not/a/real/schema.json",
    ])
    def test_opaque_or_unresolved_refs_are_retained_without_fetching(self, ref: str) -> None:
        """What: keep unknown refs exactly. Purpose: no guessing, fetching or weak fallback."""
        schema = tool_with_ref(ref)
        schema["title"] = "Keep metadata while reference scope is uncertain"
        assert normalize_tool_schema(schema) == schema

    @pytest.mark.parametrize("scope", [
        {"$id": "https://schemas.invalid/root"}, {"id": "legacy"}, {"$anchor": "node"},
        {"$dynamicAnchor": "node"}, {"$dynamicRef": "#node"},
        {"$recursiveRef": "#"}, {"$recursiveAnchor": True},
        {"$vocabulary": {"https://schemas.invalid/custom": True}},
        {"$schema": "https://schemas.invalid/custom"}, {"$schema": []},
    ])
    def test_scope_sensitive_documents_are_left_structurally_intact(self, scope: dict[str, Any]) -> None:
        """What: retain ids/anchors/dialects. Purpose: document-global relocation is unsafe."""
        schema = {**scope, "properties": {"v": nullable_array()}, "title": "Keep"}
        assert normalize_tool_schema(schema) == schema

    def test_known_dialect_is_retained_while_safe_children_normalize(self) -> None:
        """What: preserve dialect declaration. Purpose: never silently switch JSON Schema drafts."""
        dialect = "https://json-schema.org/draft/2020-12/schema"
        assert normalize_tool_schema({"$schema": dialect, "properties": {"v": nullable_array()}}) == {
            "$schema": dialect, "properties": {"v": {"type": ["array", "null"]}}}

    def test_nested_scope_and_nested_dialect_prevent_relocation(self) -> None:
        """What: account for embedded resources. Purpose: fragments may not be document-relative."""
        for marker in ({"$id": "nested"}, {"$schema": "http://json-schema.org/draft-07/schema#"}):
            schema = {"properties": {"v": nullable_array(), "resource": marker}}
            assert normalize_tool_schema(schema) == schema

    def test_references_inside_instance_data_are_not_rewritten(self) -> None:
        """What: keep literal $ref objects. Purpose: a constant is data, not a ref user."""
        schema = tool_with_ref("#/properties/values/anyOf/0/items")
        schema["properties"]["literal"] = {"const": {"$ref": "#/properties/values/anyOf/0/items"}}
        assert normalize_tool_schema(schema) == schema

    @pytest.mark.parametrize("target", [False, {"type": "integer"}, {"$ref": "#/properties/values/anyOf/0/items"}])
    def test_referenced_root_metadata_is_not_deleted(self, target: Any) -> None:
        """What: protect schema targets in metadata. Purpose: annotations can be referenced."""
        schema = tool_with_ref("#/default")
        schema["default"] = target
        result = normalize_tool_schema(schema)
        assert result["default"] == target
        assert result["properties"]["other"]["$ref"] == "#/default"


class TestToolSchemaErrors:
    """Actionable validation and bounded work, including hostile Python inputs."""

    @pytest.mark.parametrize("root", [True, False, 0, 1.5, "", "object", [], [True], (), set()])
    def test_invalid_roots_raise_specific_value_error(self, root: Any) -> None:
        """What: reject non-tool roots. Purpose: do not silently weaken malformed input."""
        with pytest.raises(ToolSchemaNormalizationError, match="provide a schema object") as error:
            normalize_tool_schema(root)
        assert isinstance(error.value, ValueError)
        assert error.value.code == "invalid_root"
        assert error.value.path == "#"

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), b"bytes", (1,), {1}, object(), "\ud800"])
    def test_non_json_values_are_rejected_before_cleanup(self, value: Any) -> None:
        """What: validate even removable metadata. Purpose: no hidden unserializable data."""
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema({"default": value})
        assert error.value.code == "invalid_json"
        assert error.value.path == "#/default"

    def test_nonstring_or_invalid_unicode_keys_raise_actionable_error(self) -> None:
        """What: reject keys that cannot encode JSON. Purpose: ensure predictable output."""
        for schema in ({1: True}, {"\ud800": True}):
            with pytest.raises(ToolSchemaNormalizationError) as error:
                normalize_tool_schema(schema)
            assert error.value.code == "invalid_json"

    @pytest.mark.parametrize("schema", [
        {"properties": []}, {"properties": {"x": None}}, {"$defs": {"x": 0}},
        {"items": None}, {"items": [True, None]}, {"additionalProperties": "false"},
        {"anyOf": {}}, {"allOf": []}, {"oneOf": [3]}, {"prefixItems": []},
        {"dependencies": {"x": 3}}, {"$ref": 3},
        {"required": ["x", None]}, {"required": [False]},
    ])
    def test_malformed_known_schema_containers_raise(self, schema: dict[str, Any]) -> None:
        """What: reject malformed applicators. Purpose: never replace invalid nodes with {}."""
        before = deepcopy(schema)
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema(schema)
        assert error.value.code == "invalid_schema"
        assert schema == before

    @pytest.mark.parametrize("kind", ["dict", "list"])
    def test_python_cycles_are_rejected_but_input_is_unchanged(self, kind: str) -> None:
        """What: detect actual cycles. Purpose: prevent recursion overflow and mutations."""
        schema: dict[str, Any] = {}
        schema["default"] = schema if kind == "dict" else [schema]
        with pytest.raises(ToolSchemaNormalizationError, match="local \\$ref") as error:
            normalize_tool_schema(schema)
        assert error.value.code == "cyclic_input"
        if kind == "dict":
            assert schema["default"] is schema
        else:
            assert schema["default"][0] is schema

    def test_depth_limit_has_exact_boundary(self) -> None:
        """What: bound opaque data too. Purpose: avoid stack exhaustion before validation."""
        value: Any = "leaf"
        for _ in range(tool_schema.MAX_SCHEMA_DEPTH - 1):
            value = [value]
        assert normalize_tool_schema({"const": value}) == {"const": value}
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema({"const": [value]})
        assert error.value.code == "too_deep"
        assert "reduce nesting" in str(error.value)

    def test_node_limit_counts_keys_values_and_shared_occurrences(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """What: bound breadth and alias expansion. Purpose: no exponential copy workload."""
        monkeypatch.setattr(tool_schema, "MAX_SCHEMA_NODES", 6)
        assert normalize_tool_schema({"enum": [1, 2, 3]}) == {"enum": [1, 2, 3]}
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema({"enum": [1, 2, 3, 4]})
        assert error.value.code == "too_many_nodes"
        shared: Any = "leaf"
        for _ in range(10):
            shared = [shared, shared]
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema({"const": shared})
        assert error.value.code == "too_many_nodes"

    def test_byte_limit_counts_utf8_escaping_and_original_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """What: enforce exact JSON bytes. Purpose: Unicode/control characters need byte accounting."""
        schema = {"default": "工具\n\"\\😀"}
        size = len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        monkeypatch.setattr(tool_schema, "MAX_SCHEMA_BYTES", size)
        assert normalize_tool_schema(schema) == {"type": "object", "properties": {}}
        monkeypatch.setattr(tool_schema, "MAX_SCHEMA_BYTES", size - 1)
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema(schema)
        assert error.value.code == "too_large"

    def test_large_input_is_rejected_without_input_mutation(self) -> None:
        """What: reject an over-budget scalar. Purpose: cheap checks precede expensive encoding."""
        schema = {"title": "a" * (tool_schema.MAX_SCHEMA_BYTES + 1)}
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema(schema)
        assert error.value.code == "too_large"
        assert len(schema["title"]) == tool_schema.MAX_SCHEMA_BYTES + 1

    def test_huge_integer_returns_our_error_not_python_serialization_error(self) -> None:
        """What: wrap native integer serialization limits. Purpose: one stable error family."""
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema({"const": 10 ** 10_000})
        assert error.value.code in {"too_large", "invalid_json"}

    def test_safe_error_path_escapes_unicode_and_pointer_characters(self) -> None:
        """What: expose the exact failing location. Purpose: callers can identify bad fields."""
        with pytest.raises(ToolSchemaNormalizationError) as error:
            normalize_tool_schema({"properties": {"名字/~": {"items": None}}})
        assert error.value.path == "#/properties/%E5%90%8D%E5%AD%97~1~0/items"
        assert "expected a schema object or boolean schema" in str(error.value)

    @pytest.mark.parametrize("required", [None, False, "name", {"type": "integer"}])
    def test_required_repair_never_deletes_a_reference_target(self, required: Any) -> None:
        """What: reject a destructive repair. Purpose: never leave a new dangling ref."""
        schema = {"required": required, "properties": {"x": {"$ref": "#/required"}}}
        before = deepcopy(schema)
        with pytest.raises(ToolSchemaNormalizationError, match="move the target into \\$defs"):
            normalize_tool_schema(schema)
        assert schema == before


def accepts_array_test_fragment(schema: dict[str, Any] | bool, value: Any) -> bool:
    """Evaluate only the finite test vocabulary, independently of normalization.

    This is NOT a general JSON Schema validator. Unsupported keywords fail the
    test rather than being silently ignored. The finite oracle includes the
    general assertions that make naive nullable type-widening incorrect.
    """
    if isinstance(schema, bool):
        return schema
    supported = {"type", "anyOf", "allOf", "oneOf", "not", "const", "enum", "items",
                 "minimum", "maximum", "minItems", "maxItems", "uniqueItems", "contains",
                 "minContains", "maxContains"}
    assert set(schema) <= supported, "The finite semantic oracle needs an explicit keyword implementation"
    if "anyOf" in schema and not any(accepts_array_test_fragment(s, value) for s in schema["anyOf"]):
        return False
    if "allOf" in schema and not all(accepts_array_test_fragment(s, value) for s in schema["allOf"]):
        return False
    if "oneOf" in schema and sum(accepts_array_test_fragment(s, value) for s in schema["oneOf"]) != 1:
        return False
    if "not" in schema and accepts_array_test_fragment(schema["not"], value):
        return False
    # JSON text separates booleans from integers, unlike Python's equality.
    encoded = json.dumps(value, sort_keys=True)
    if "const" in schema and encoded != json.dumps(schema["const"], sort_keys=True):
        return False
    if "enum" in schema and encoded not in [json.dumps(v, sort_keys=True) for v in schema["enum"]]:
        return False
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        matches = {"array": isinstance(value, list), "null": value is None,
                   "number": type(value) in (int, float), "integer": type(value) is int,
                   "string": isinstance(value, str), "object": isinstance(value, dict),
                   "boolean": isinstance(value, bool)}
        if not any(matches[kind] for kind in types):
            return False
    if type(value) in (int, float):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            return False
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            return False
        if "items" in schema and not all(accepts_array_test_fragment(schema["items"], v) for v in value):
            return False
        if "contains" in schema:
            matches_count = sum(accepts_array_test_fragment(schema["contains"], v) for v in value)
            if not schema.get("minContains", 1) <= matches_count <= schema.get("maxContains", float("inf")):
                return False
    return True


class TestFiniteSemanticEquivalence:
    """A deterministic validation grid supplements structural regression tests."""

    def test_nullable_array_rewrites_preserve_acceptance(self) -> None:
        """What: compare 147 schemas on 18 instances. Purpose: expose weakened/strengthened constraints."""
        instances = [None, False, True, 0, "", {}, [], [None], [False], [0], [1], [2],
                     [-1], [0, 1], [1, 1], [2, 3], [0, 1, 2], [[]]]
        constraints = [{}, {"items": False}, {"items": True},
                       {"items": {"type": "integer", "minimum": 0, "maximum": 2}},
                       {"contains": {"const": 1}, "minContains": 1, "maxContains": 1},
                       {"contains": False, "minContains": 0, "maxContains": 0},
                       {"minimum": 0, "maximum": 3}, {"uniqueItems": True}]
        branches = [{"type": "array", "minItems": minimum, "maxItems": maximum,
                     "uniqueItems": unique, **constraint}
                    for minimum in (0, 1, 2) for maximum in (1, 2, 3)
                    for unique in (False, True) for constraint in constraints]
        branches += [{"type": "array", "const": []}, {"type": "array", "enum": [[], [1]]},
                     {"type": "array", "not": {"type": "null"}}]
        assert len(branches) == 147
        for branch in branches:
            wrapper = {"anyOf": [{"not": {}}, branch, {"type": "null"}]}
            original = deepcopy(wrapper)
            result = normalize_tool_schema({"properties": {"value": wrapper}})["properties"]["value"]
            assert wrapper == original
            assert normalize_tool_schema({"properties": {"value": result}})["properties"]["value"] == result
            for instance in instances:
                assert accepts_array_test_fragment(wrapper, instance) == accepts_array_test_fragment(result, instance), (
                    branch, instance, result)
