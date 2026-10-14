"""Conservative, offline normalization of JSON Schema tool input definitions.

The compatibility baseline is Kiro CLI 2.29.1 / @kiro/agent 0.66.33,
``acp-server.readable.js`` LF lines 363297-363502 (j3r, v9c, pCt, G3r).
Unlike a generic schema "sanitizer", this module never drops validation
keywords, expands references, or chooses a branch of an ambiguous union.

Deliberate safety differences from that CLI:
* Keep $id, $schema, definitions and $defs; they can control reference meaning.
* Do not infer an object type for a nonempty schema, or traverse instance data
  in const/default/examples as though it were a schema.
* Lift only array branches with known type-specific constraints. For example,
  widening type does NOT make an array branch with const/enum accept null.
* Preserve structure when reference scopes, anchors, unknown dialects, opaque
  references, or references in instance data make relocation uncertain.
* Decode URI fragments before JSON Pointer tokens, including percent-encoded
  separators, and reject malformed pointers for relocation (not as input).

This is not a complete metaschema validator. It checks JSON representability,
resource limits, root required entries and standard subschema containers.
Unknown keywords and unresolvable references are retained for the caller's
validator. Missing/empty tool schemas (including roots emptied by repairs) use the
CLI's object-schema convention; repairing malformed root required is the other
intentional validation repair.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
import json
import math
import re
from typing import Any, Iterator
from urllib.parse import quote, unquote

from loguru import logger

__all__ = [
    "normalize_tool_schema", "ToolSchemaNormalizationError",
    "MAX_SCHEMA_DEPTH", "MAX_SCHEMA_NODES", "MAX_SCHEMA_BYTES",
]

MAX_SCHEMA_DEPTH = 64
"""Maximum JSON edge depth, with the root at depth zero (including data)."""
MAX_SCHEMA_NODES = 20_000
"""Maximum JSON occurrences, counting containers, values and dictionary keys."""
MAX_SCHEMA_BYTES = 1_048_576
"""Maximum compact, ensure_ascii=False, UTF-8 JSON bytes before normalization."""

_Path = tuple[str, ...]
_ANNOTATIONS = frozenset({"title", "description", "default", "examples", "$comment",
                          "deprecated", "readOnly", "writeOnly"})
_ROOT_METADATA = ("title", "default", "examples")
_SCHEMA_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions",
                          "dependentSchemas"})
_SCHEMA_SINGLE = frozenset({"additionalProperties", "unevaluatedProperties", "propertyNames",
                            "contains", "additionalItems", "unevaluatedItems", "not", "if",
                            "then", "else", "contentSchema"})
_SCHEMA_ARRAYS = frozenset({"anyOf", "allOf", "oneOf", "prefixItems"})
_SCOPE_KEYS = frozenset({"$id", "id", "$anchor", "$dynamicAnchor", "$recursiveAnchor",
                        "$dynamicRef", "$recursiveRef", "$vocabulary"})
_KNOWN_DIALECTS = frozenset({
    "http://json-schema.org/draft-04/schema#", "http://json-schema.org/draft-06/schema#",
    "http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft/2019-09/schema",
    "https://json-schema.org/draft/2020-12/schema",
})
# Each assertion below ignores null. General assertions such as const, enum,
# $ref and combinators are intentionally absent, as are custom formats
# (their applicability can be validator-defined) and unknown extensions.
_SAFE_ARRAY_KEYS = _ANNOTATIONS | frozenset({
    "type", "$defs", "definitions", "items", "prefixItems", "additionalItems", "contains",
    "minContains", "maxContains", "minItems", "maxItems", "uniqueItems", "unevaluatedItems",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "contentEncoding", "contentMediaType",
    "properties", "patternProperties", "additionalProperties", "unevaluatedProperties",
    "propertyNames", "required", "minProperties", "maxProperties", "dependencies",
    "dependentRequired", "dependentSchemas",
})
_BAD_PERCENT = re.compile(r"%(?![0-9a-fA-F]{2})")
_BAD_TILDE = re.compile(r"~(?![01])")


class ToolSchemaNormalizationError(ValueError):
    """Actionable invalid/oversized input error with stable code and pointer path."""

    def __init__(self, code: str, path: _Path, detail: str) -> None:
        """Store machine-readable context without embedding schema values.

        Args:
            code: Stable failure category, such as too_deep or invalid_json.
            path: Original JSON location as unescaped tokens.
            detail: Explanation including a suggested correction.
        """
        self.code = code
        self.path = _pointer(path)
        display_path = self.path if len(self.path) <= 160 else self.path[:157] + "..."
        super().__init__(f"Invalid tool schema at {display_path}: {detail}")


def _pointer(path: _Path) -> str:
    """Encode path tokens as a URI-fragment JSON Pointer.

    Args:
        path: Unescaped property names and array indices.

    Returns:
        A local reference with escaped slashes, tildes and UTF-8 characters.
    """
    return "#" + "".join("/" + quote(p.replace("~", "~0").replace("/", "~1"), safe="$~")
                         for p in path)


@dataclass
class _Budget:
    """Track copying work before allocating or recursing into untrusted JSON."""

    nodes: int = 0
    size: int = 0
    ancestors: set[int] = field(default_factory=set)

    def charge(self, path: _Path, size: int = 0, nodes: int = 0) -> None:
        """Charge JSON bytes and occurrences or raise an actionable limit error.

        Args:
            path: Location to report on failure.
            size: Additional compact JSON bytes.
            nodes: Additional key/value/container occurrences.

        Raises:
            ToolSchemaNormalizationError: The byte or node budget is exceeded.
        """
        self.size += size
        self.nodes += nodes
        if self.size > MAX_SCHEMA_BYTES:
            raise ToolSchemaNormalizationError(
                "too_large", path, f"exceeds {MAX_SCHEMA_BYTES} JSON bytes; shorten the schema.")
        if self.nodes > MAX_SCHEMA_NODES:
            raise ToolSchemaNormalizationError(
                "too_many_nodes", path,
                f"exceeds {MAX_SCHEMA_NODES} JSON nodes; reduce properties or array entries.")


def _scalar_size(value: Any, path: _Path) -> int:
    """Measure a bounded JSON scalar without accepting NaN or invalid Unicode.

    Args:
        value: A scalar with a native JSON-compatible Python type.
        path: Original location for diagnostics.

    Returns:
        Its exact compact UTF-8 JSON byte length.

    Raises:
        ToolSchemaNormalizationError: Serialization is invalid or oversized.
    """
    if isinstance(value, str) and len(value) > MAX_SCHEMA_BYTES:
        raise ToolSchemaNormalizationError("too_large", path, "string is too long; shorten it.")
    if isinstance(value, int) and value.bit_length() > MAX_SCHEMA_BYTES * 4:
        raise ToolSchemaNormalizationError("too_large", path, "integer is too large; reduce it.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolSchemaNormalizationError("invalid_json", path, "use a finite number, not NaN or infinity.")
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise ToolSchemaNormalizationError(
            "invalid_json", path, "use valid UTF-8 text and a JSON-serializable number.") from exc


def _copy_json(value: Any, path: _Path, budget: _Budget) -> Any:
    """Deep-copy a JSON tree with bounded depth, size and alias expansion.

    Args:
        value: Input JSON value; references in strings are never followed.
        path: Current path, also defining the JSON edge depth.
        budget: Shared occurrence/size budget and active container identities.

    Returns:
        Independent JSON containers, with shared input aliases copied separately.

    Raises:
        ToolSchemaNormalizationError: Invalid JSON, a Python cycle or a limit breach.
    """
    if len(path) > MAX_SCHEMA_DEPTH:
        raise ToolSchemaNormalizationError(
            "too_deep", path, f"exceeds depth {MAX_SCHEMA_DEPTH}; reduce nesting or use local $refs.")
    budget.charge(path, nodes=1)
    if type(value) not in (dict, list, str, int, float, bool, type(None)):
        raise ToolSchemaNormalizationError(
            "invalid_json", path, "use only JSON objects, arrays, strings, finite numbers, booleans or null.")
    if not isinstance(value, (dict, list)):
        budget.charge(path, size=_scalar_size(value, path))
        return value
    if id(value) in budget.ancestors:
        raise ToolSchemaNormalizationError(
            "cyclic_input", path, "Python containers form a cycle; express recursion with a local $ref.")
    budget.charge(path, size=2 + max(0, len(value) - 1))
    budget.ancestors.add(id(value))
    try:
        if isinstance(value, list):
            return [_copy_json(item, path + (str(i),), budget) for i, item in enumerate(value)]
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ToolSchemaNormalizationError(
                    "invalid_json", path, "object keys must be strings; convert the non-string key.")
            budget.charge(path, size=_scalar_size(key, path) + 1, nodes=1)
            result[key] = _copy_json(item, path + (key,), budget)
        return result
    finally:
        budget.ancestors.remove(id(value))


def _schema_children(node: dict[str, Any], path: _Path) -> Iterator[tuple[_Path, Any]]:
    """Yield genuine subschemas, never objects embedded in instance data.

    Args:
        node: One schema object.
        path: Its original location for validation errors.

    Yields:
        Relative path and dictionary/boolean child pairs.

    Raises:
        ToolSchemaNormalizationError: A standard subschema container is malformed.
    """
    for key, value in node.items():
        entries: list[tuple[_Path, Any]] = []
        if key in _SCHEMA_MAPS or key == "dependencies":
            if not isinstance(value, dict):
                raise ToolSchemaNormalizationError(
                    "invalid_schema", path + (key,), "expected an object mapping names to schemas.")
            entries = [((key, name), child) for name, child in value.items()
                       if not (key == "dependencies" and isinstance(child, list))]
        elif key in _SCHEMA_ARRAYS or (key == "items" and isinstance(value, list)):
            if not isinstance(value, list) or not value:
                raise ToolSchemaNormalizationError(
                    "invalid_schema", path + (key,), "expected a nonempty array of schemas.")
            entries = [((key, str(i)), child) for i, child in enumerate(value)]
        elif key in _SCHEMA_SINGLE or key == "items":
            entries = [((key,), value)]
        for relative, child in entries:
            if not isinstance(child, (dict, bool)):
                raise ToolSchemaNormalizationError(
                    "invalid_schema", path + relative, "expected a schema object or boolean schema.")
            yield relative, child


def _walk_schemas(node: Any, path: _Path = ()) -> Iterator[tuple[_Path, dict[str, Any]]]:
    """Walk schema objects in a bounded copied tree.

    Args:
        node: A dictionary or boolean schema.
        path: Original JSON location.

    Yields:
        Schema object paths and their mutable, privately owned dictionaries.
    """
    if isinstance(node, dict):
        yield path, node
        for relative, child in _schema_children(node, path):
            yield from _walk_schemas(child, path + relative)


def _walk_json(value: Any, path: _Path = ()) -> Iterator[tuple[_Path, dict[str, Any]]]:
    """Visit all copied objects, including opaque instance data, for safety checks.

    Args:
        value: Bounded copied JSON value.
        path: Original JSON location.

    Yields:
        Paths and dictionaries without dereferencing any schema reference.
    """
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_json(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, path + (str(index),))


def _parse_pointer(ref: str) -> _Path | None:
    """Parse only unambiguous local URI-fragment JSON Pointers.

    Args:
        ref: An unchanged input reference string.

    Returns:
        Decoded tokens, or None for remote, anchor or malformed references.
    """
    if not ref.startswith("#") or _BAD_PERCENT.search(ref):
        return None
    try:
        fragment = unquote(ref[1:], encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if not fragment:
        return ()
    if not fragment.startswith("/"):
        return None
    tokens = fragment[1:].split("/")
    if any(_BAD_TILDE.search(token) for token in tokens):
        return None
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in tokens)


def _lookup(root: Any, path: _Path) -> Any:
    """Check a pointer's literal destination without expanding reference chains.

    Args:
        root: Original copied document.
        path: Decoded JSON Pointer tokens.

    Returns:
        The target value, or None when the pointer does not resolve.
    """
    value = root
    for token in path:
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif (isinstance(value, list) and token.isascii() and token.isdigit()
              and (token == "0" or not token.startswith("0"))
              and len(token) <= len(str(len(value))) and int(token) < len(value)):
            value = value[int(token)]
        else:
            return None
    return value


@dataclass
class _References:
    """Reference inventory plus relocations; never a dereferenced schema graph."""

    targets: list[_Path] = field(default_factory=list)
    uses: list[tuple[dict[str, Any], _Path]] = field(default_factory=list)
    relocations: dict[_Path, _Path] = field(default_factory=dict)
    opaque: bool = False
    skipped: int = 0

    def beneath(self, path: _Path) -> Iterator[_Path]:
        """Yield only targets inside a subtree using a sorted prefix index.

        Args:
            path: Inclusive subtree prefix.

        Yields:
            Original target paths with the requested prefix.
        """
        index = bisect_left(self.targets, path)
        while index < len(self.targets):
            target = self.targets[index]
            if target[:len(path)] != path:
                break
            yield target
            index += 1


def _reference_index(root: dict[str, Any]) -> _References:
    """Inventory reference targets and conservatively detect unknown scopes.

    Args:
        root: Validated, copied schema document.

    Returns:
        Local reference uses/targets and an opaque-reference safety flag.

    Raises:
        ToolSchemaNormalizationError: A real schema's $ref is not a string.
    """
    schema_paths = {path for path, _ in _walk_schemas(root)}
    refs = _References()
    for path, node in _walk_json(root):
        if _SCOPE_KEYS.intersection(node):
            refs.opaque = True
        if "$schema" in node:
            dialect = node["$schema"]
            if path or not isinstance(dialect, str) or dialect not in _KNOWN_DIALECTS:
                refs.opaque = True
        if "$ref" not in node:
            continue
        if path not in schema_paths:
            refs.opaque = True
            continue
        if not isinstance(node["$ref"], str):
            raise ToolSchemaNormalizationError(
                "invalid_schema", path + ("$ref",), "use a string URI or local JSON Pointer reference.")
        target = _parse_pointer(node["$ref"])
        if target is None:
            refs.opaque = True
            continue
        refs.targets.append(target)
        target_value = _lookup(root, target)
        if not isinstance(target_value, (dict, bool)):
            refs.opaque = True
            continue
        refs.uses.append((node, target))
        # A ref may make an otherwise opaque annotation/extension a schema.
        # Do not rewrite that unvisited vocabulary or its outbound refs.
        if target not in schema_paths and isinstance(target_value, dict):
            refs.opaque = True
    refs.targets = sorted(set(refs.targets))
    return refs


def _is_wrapper(node: Any) -> bool:
    """Check a pure anyOf wrapper, allowing only CLI-compatible annotations.

    Args:
        node: Candidate JSON value.

    Returns:
        Whether flattening its alternatives cannot discard sibling assertions.
    """
    return (isinstance(node, dict) and isinstance(node.get("anyOf"), list)
            and set(node) <= {"anyOf", "description", "title"})


@dataclass
class _Alternatives:
    """Flattened pure anyOf candidates with their original reference locations."""

    real: list[tuple[dict[str, Any] | bool, _Path]] = field(default_factory=list)
    nullable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _alternatives(node: dict[str, Any], path: _Path, result: _Alternatives) -> None:
    """Collect pure wrappers, exact null branches and exact false branches.

    Args:
        node: A pure anyOf wrapper.
        path: Original location of that wrapper.
        result: Accumulator with branch locations and inner-first annotations.
    """
    for index, child in enumerate(node["anyOf"]):
        child_path = path + ("anyOf", str(index))
        if child is False or (isinstance(child, dict) and child.get("not") == {}
                              and set(child) <= {"not", "title", "description"}):
            continue
        if (isinstance(child, dict) and child.get("type") == "null"
                and set(child) <= {"type", "title", "description"}):
            result.nullable = True
        elif _is_wrapper(child):
            _alternatives(child, child_path, result)
            for key in ("description", "title"):
                if key in child:
                    result.metadata.setdefault(key, child[key])
        else:
            result.real.append((child, child_path))


def _normalize_node(node: Any, source: _Path, destination: _Path, refs: _References) -> Any:
    """Normalize genuine subschemas while recording source-to-destination moves.

    Args:
        node: Privately owned schema object or boolean.
        source: Its original location, used to protect reference targets.
        destination: Its final location after ancestor collapses.
        refs: Shared original targets and longest-prefix relocation map.

    Returns:
        A semantically equivalent schema; the root wrapper is not collapsed.
    """
    if not isinstance(node, dict):
        return node
    if source and _is_wrapper(node):
        alternatives = _Alternatives()
        _alternatives(node, source, alternatives)
        if len(alternatives.real) == 1:
            branch, branch_path = alternatives.real[0]
            if (isinstance(branch, dict) and branch.get("type") in ("array", ["array"])
                    and set(branch) <= _SAFE_ARRAY_KEYS):
                safe = all(
                    target == source or (target[:len(branch_path)] == branch_path
                                         and not (alternatives.nullable and target == branch_path))
                    for target in refs.beneath(source)
                )
                if safe:
                    refs.relocations[branch_path] = destination
                    result = _normalize_node(branch, branch_path, destination, refs)
                    if alternatives.nullable:
                        result["type"] = ["array", "null"]
                    for key in ("description", "title"):
                        if key not in result:
                            if key in alternatives.metadata:
                                result[key] = alternatives.metadata[key]
                            elif key in node:
                                result[key] = node[key]
                    return result
                refs.skipped += 1
    for relative, child in list(_schema_children(node, source)):
        parent: Any = node
        for token in relative[:-1]:
            parent = parent[int(token)] if isinstance(parent, list) else parent[token]
        key: str | int = int(relative[-1]) if isinstance(parent, list) else relative[-1]
        parent[key] = _normalize_node(child, source + relative, destination + relative, refs)
    return node


def normalize_tool_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Return an independent, bounded, conservatively normalized tool schema.

    None/empty dictionaries, including roots emptied by the repairs below,
    become ``{"type": "object", "properties": {}}``.
    Root ``required`` values that are not lists are removed unless a local ref
    targets them (an error). Lists must contain strings and are deduplicated in
    order, WITHOUT filtering against properties.
    Only unreferenced root title/default/examples annotations are removed.
    Eligible nested array anyOf wrappers are collapsed with pointer relocation;
    ambiguous unions, boolean subschemas, recursive refs and all constraints
    otherwise survive. Nonempty schemas are never forced to type object.

    Limits apply to the original JSON, including metadata that would be removed:
    MAX_SCHEMA_DEPTH edges, MAX_SCHEMA_NODES occurrences and MAX_SCHEMA_BYTES
    compact UTF-8 bytes. Python cycles are invalid, but recursive $refs are legal.
    All work is local: no network, reference fetching, auth, target execution,
    integration hooks or mutation of caller-owned containers.

    Args:
        schema: A plain JSON-compatible dictionary, or None for an absent schema.
            Root booleans/lists/scalars are invalid for this tool-definition API;
            nested boolean schemas are fully supported.

    Returns:
        A fresh dictionary. JSON containers are never shared with the input.

    Raises:
        ToolSchemaNormalizationError: Invalid root/JSON/subschema containers,
            non-string required entries, a Python cycle, or a resource limit.
            Inspect ``code`` and ``path`` for machine-readable error context.
    """
    if schema is None:
        return {"type": "object", "properties": {}}
    if type(schema) is not dict:
        raise ToolSchemaNormalizationError(
            "invalid_root", (), "provide a schema object or None; root booleans/arrays/scalars are not tool schemas.")
    root = _copy_json(schema, (), _Budget())
    refs = _reference_index(root)
    if "required" in root:
        required = root["required"]
        if not isinstance(required, list):
            if any(refs.beneath(("required",))):
                raise ToolSchemaNormalizationError(
                    "invalid_schema", ("required",),
                    "cannot remove a referenced required value; move the target into $defs, "
                    "update its $ref and use an array of names for required.")
            del root["required"]
        else:
            if any(not isinstance(name, str) for name in required):
                raise ToolSchemaNormalizationError(
                    "invalid_schema", ("required",), "required must list property names as strings; remove non-string entries.")
            root["required"] = list(dict.fromkeys(required))
    if not refs.opaque:
        for key in _ROOT_METADATA:
            if not any(refs.beneath((key,))):
                root.pop(key, None)
        _normalize_node(root, (), (), refs)
    relocated = 0
    for node, target in refs.uses:
        for length in range(len(target), -1, -1):
            prefix = target[:length]
            if prefix in refs.relocations:
                node["$ref"] = _pointer(refs.relocations[prefix] + target[length:])
                relocated += 1
                break
    logger.debug("Tool schema normalized: collapses={}, relocated_refs={}, skipped={}, opaque_refs={}",
                 len(refs.relocations), relocated, refs.skipped, refs.opaque)
    return root or {"type": "object", "properties": {}}
