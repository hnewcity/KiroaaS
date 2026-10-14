"""Conservative, offline model request capabilities from ListAvailableModels.

``ModelCapabilities.from_model`` snapshots metadata; it never guesses from a
model name. Missing/null metadata is UNKNOWN, whereas an explicit empty object
advertises no fields (UNSUPPORTED). Unknown schema constructs remain UNKNOWN,
not permission to send arbitrary parameters. The builder is deliberately strict:
explicit requests against unknown capabilities raise ModelCapabilityError. A
transport adapter may implement a separately documented unvalidated pass-through
policy using these states, but must preserve the caller's original parameters.

Supported schema subset: direct object properties/required; scalar type, enum,
const, default, inclusive/exclusive numeric bounds, and nested oneOf/anyOf/allOf.
Scalar unions use actual oneOf exclusivity, not just a union of enum strings.
Object-level unions, references, conditional validation, object defaults, and
other unimplemented constraints are UNKNOWN. This is not a general JSON Schema
validator. Only advertised scalar defaults are applied; no thinking budget is invented, and no
effort alias, or token count is invented. tokenLimits.maxOutputTokens is an extra
ceiling, not evidence that the additional-field max_tokens transport is supported.

Static evidence: CLI 2.29.1 / @kiro/agent 0.66.33, acp-server.readable.js, LF
127577-127643 and 127705-127735; effort precedence and disabled-thinking exclusions
are at LF 127749-127754. Unlike that CLI's silent xhigh/max downgrade, this module
raises on incompatible choices. Numeric validation and conservative unknown
handling are gateway policy, not claims of observed upstream execution.

This module has no I/O, logging side effects, external dependencies, or imports
of gateway configuration. All public capability records are immutable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Literal


ThinkingMode = Literal["enabled", "disabled", "adaptive"]
Scalar = str | int | float | bool | None
_MISSING = object()
_THINKING_MODES = ("enabled", "disabled", "adaptive")
_THINKING_REQUIRED_EFFORTS = frozenset(("xhigh", "max"))
_ANNOTATIONS = frozenset(("$schema", "$id", "$comment", "title", "description", "examples"))
_JSON_TYPES = frozenset(("string", "integer", "number", "boolean", "null", "object", "array"))
_MAX_SCHEMA_DEPTH = 32


class CapabilityStatus(str, Enum):
    """UNKNOWN means unverified; UNSUPPORTED means not advertised/allowed."""

    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    SUPPORTED = "supported"


class ModelCapabilityError(ValueError):
    """Actionable validation failure with stable model_id, field, and status."""

    def __init__(
        self,
        model_id: str,
        field: str,
        message: str,
        *,
        status: CapabilityStatus | None = None,
    ) -> None:
        """Initialize an error without logging or altering a request.

        Args:
            model_id: Exact advertised/requested model identifier.
            field: Client field or dotted metadata path responsible for failure.
            message: Explanation and suggested corrective action.
            status: Capability state, when the error is about support.
        """
        self.model_id = model_id
        self.field = field
        self.status = status
        super().__init__(f"Model {model_id!r}, field {field!r}: {message}")


@dataclass(frozen=True, slots=True)
class EnumCapability:
    """Finite advertised choices; None default means no advertised default.

    ``path`` uses upstream names, e.g. ("output_config", "effort"). Empty
    ``values`` alone does not distinguish unknown from unsupported; use status.
    """

    status: CapabilityStatus
    path: tuple[str, ...]
    values: tuple[str, ...] = ()
    default: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IntegerCapability:
    """Integer capability with inclusive bounds and an optional default.

    Bounds describe an envelope for unions; gaps/exclusive oneOf branches are
    also checked by the builder. Values are never clamped to either bound.
    """

    status: CapabilityStatus
    minimum: int | None = None
    maximum: int | None = None
    default: int | None = None
    reason: str | None = None
    _schema: _ScalarSchema | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class TokenLimits:
    """Advertised positive integer limits; absent members remain None."""

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class _ScalarSchema:
    """Immutable compiled scalar constraints; no raw input objects are kept."""

    types: tuple[str, ...] = ()
    choices: tuple[Scalar, ...] | None = None
    default: Scalar | object = _MISSING
    minimum: int | float | None = None
    maximum: int | float | None = None
    exclusive_minimum: int | float | None = None
    exclusive_maximum: int | float | None = None
    combinations: tuple[tuple[str, tuple[_ScalarSchema, ...]], ...] = ()
    reason: str | None = None
    allowed: bool = True


@dataclass(frozen=True, slots=True)
class _ObjectSchema:
    """Parent constraints needed to validate the emitted nested objects."""

    path: tuple[str, ...]
    required: tuple[str, ...] = ()
    reason: str | None = None
    allowed: bool = True


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Parsed ListAvailableModels record, safe to share in a model cache.

    Use ``from_model`` rather than assembling records by hand. ``schema_status``
    describes root metadata, while per-field status describes actual support.
    SUPPORTED root metadata does not imply every field is supported. Missing
    tokenLimits is None; a present empty tokenLimits is TokenLimits(None, None).
    ``model_id`` is only an error label, never a capability heuristic.
    """

    model_id: str
    schema_status: CapabilityStatus
    effort: EnumCapability
    thinking: EnumCapability
    max_tokens: IntegerCapability
    token_limits: TokenLimits | None = None
    _objects: tuple[_ObjectSchema, ...] = field(default=(), repr=False)
    thinking_budget: IntegerCapability = field(default_factory=lambda: IntegerCapability(
        CapabilityStatus.UNKNOWN, reason="No thinking budget schema was supplied."
    ))

    @classmethod
    def from_model(
        cls, raw_model: Mapping[str, Any] | None, *, model_id: str | None = None
    ) -> ModelCapabilities:
        """Parse a raw ListAvailableModels entry without retaining/mutating it.

        Args:
            raw_model: Model dictionary, or None for a cache miss/unknown model.
            model_id: Error-label fallback when the record lacks modelId.

        Returns:
            Immutable capabilities, including explicit unknown/unsupported states.

        Raises:
            ModelCapabilityError: Malformed supported metadata or invalid defaults.
                Unimplemented schema keywords produce UNKNOWN instead of guessing.
        """
        label = model_id if model_id is not None else "<unknown>"
        if not isinstance(label, str) or not label.strip():
            raise ModelCapabilityError("<unknown>", "modelId", "Use a non-empty model identifier.")
        if raw_model is not None and not isinstance(raw_model, Mapping):
            raise ModelCapabilityError(label, "model", "Use a model dictionary or None for a cache miss.")
        raw = raw_model if raw_model is not None else {}
        if "modelId" in raw:
            label = raw["modelId"]
            if not isinstance(label, str) or not label.strip():
                raise ModelCapabilityError(model_id or "<unknown>", "modelId", "Use a non-empty model identifier.")
        limits = _parse_token_limits(raw.get("tokenLimits"), label)
        schema = raw.get("additionalModelRequestFieldsSchema")
        if schema is None:
            reason = "No additionalModelRequestFieldsSchema was supplied; support is unknown."
            return cls(
                label, CapabilityStatus.UNKNOWN,
                EnumCapability(CapabilityStatus.UNKNOWN, (), reason=reason),
                EnumCapability(CapabilityStatus.UNKNOWN, ("thinking", "type"), reason=reason),
                IntegerCapability(CapabilityStatus.UNKNOWN, reason=reason), limits,
            )

        root, properties = _parse_object(schema, label, ())
        objects = [root]
        effort = EnumCapability(CapabilityStatus.UNSUPPORTED, (), reason="No effort property is advertised.")
        # Same precedence as the shipped CLI. Unknown metadata at the preferred
        # path is not silently bypassed in favor of a different transport path.
        for name in ("output_config", "reasoning"):
            leaf, parent = _nested_scalar(properties, name, "effort", label, root)
            if parent is not None:
                objects.append(parent)
            candidate = _enum_capability(leaf, (name, "effort"), label, parent or root)
            if candidate.status is not CapabilityStatus.UNSUPPORTED:
                effort = candidate
                break
        leaf, parent = _nested_scalar(properties, "thinking", "type", label, root)
        if parent is not None:
            objects.append(parent)
        thinking = _enum_capability(leaf, ("thinking", "type"), label, parent or root)
        if thinking.status is CapabilityStatus.SUPPORTED:
            if thinking.default is not None and thinking.default not in _THINKING_MODES:
                raise ModelCapabilityError(label, "thinking", "The advertised default is not enabled, disabled, or adaptive; refresh model metadata.")
            modes = tuple(value for value in thinking.values if value in _THINKING_MODES)
            thinking = EnumCapability(
                CapabilityStatus.SUPPORTED if modes else CapabilityStatus.UNSUPPORTED,
                thinking.path, modes, thinking.default,
                None if modes else "No supported native thinking mode is advertised.",
            )
        budget_leaf, budget_parent = _nested_scalar(properties, "thinking", "budget_tokens", label, root)
        budget = _integer_capability(budget_leaf, label, budget_parent or root, None, name="thinking.budget_tokens")
        tokens = _integer_capability(properties.get("max_tokens", _MISSING), label, root, limits)
        status = CapabilityStatus.UNKNOWN if root.reason else (
            CapabilityStatus.SUPPORTED if properties and root.allowed else CapabilityStatus.UNSUPPORTED
        )
        return cls(label, status, effort, thinking, tokens, limits, tuple(objects), budget)


def _parse_token_limits(raw: Any, model: str) -> TokenLimits | None:
    """Read token limits; distinguish absent metadata from an empty object."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ModelCapabilityError(model, "tokenLimits", "Expected an object; refresh model metadata.")
    values: list[int | None] = []
    for key in ("maxInputTokens", "maxOutputTokens"):
        value = raw.get(key)
        if key in raw and (type(value) is not int or value <= 0):
            raise ModelCapabilityError(model, f"tokenLimits.{key}", "Expected a positive integer (not bool); refresh model metadata.")
        values.append(value)
    return TokenLimits(*values)


def _parse_object(
    raw: Any, model: str, path: tuple[str, ...]
) -> tuple[_ObjectSchema, Mapping[str, Any]]:
    """Parse direct object structure; unsupported object constraints stay unknown."""
    name = ".".join(path) or "additionalModelRequestFieldsSchema"
    if type(raw) is bool:
        return _ObjectSchema(path, reason="An unrestricted schema does not advertise fields." if raw else None, allowed=raw), {}
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise ModelCapabilityError(model, name, "Expected a schema object with string keys; refresh model metadata.")
    props = raw.get("properties", {})
    if not isinstance(props, Mapping) or any(not isinstance(key, str) for key in props):
        raise ModelCapabilityError(model, name, "properties must be an object with string keys; refresh model metadata.")
    required = raw.get("required", [])
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required) or len(set(required)) != len(required):
        raise ModelCapabilityError(model, name, "required must be a list of unique property names; refresh model metadata.")
    unknown = set(raw) - _ANNOTATIONS - {"type", "properties", "required", "additionalProperties"}
    if "type" in raw and raw["type"] != "object":
        unknown.add("non-object type")
    if "additionalProperties" in raw and type(raw["additionalProperties"]) is not bool:
        unknown.add("additionalProperties schema")
    reason = f"Cannot validate object constraints: {', '.join(sorted(unknown))}." if unknown else None
    return _ObjectSchema(path, tuple(required), reason), props


def _nested_scalar(
    properties: Mapping[str, Any], parent_name: str, child: str, model: str, root: _ObjectSchema
) -> tuple[Any, _ObjectSchema | None]:
    """Resolve a known nested path while retaining unknown root restrictions."""
    if parent_name not in properties:
        return _MISSING, None
    parent, nested = _parse_object(properties[parent_name], model, (parent_name,))
    if root.reason:
        parent = _ObjectSchema(parent.path, parent.required, root.reason, parent.allowed)
    return nested.get(child, _MISSING), parent


def _number(value: Any) -> bool:
    """Return whether a schema number is finite and is not a Python bool."""
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _same(left: Scalar, right: Scalar) -> bool:
    """Compare JSON scalars without treating true as the number one."""
    return left == right and (type(left) is type(right) or (_number(left) and _number(right)))


def _parse_scalar(raw: Any, model: str, path: str, depth: int = 0) -> _ScalarSchema:
    """Compile the supported scalar subset with bounded recursion and no aliases."""
    if depth > _MAX_SCHEMA_DEPTH:
        raise ModelCapabilityError(model, path, "Schema is cyclic or too deeply nested; refresh model metadata.")
    if type(raw) is bool:
        return _ScalarSchema(allowed=raw)
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise ModelCapabilityError(model, path, "Expected a scalar schema object; refresh model metadata.")
    types = raw.get("type", [])
    if isinstance(types, str):
        types = [types]
    if not isinstance(types, list) or ("type" in raw and not types) or any(not isinstance(item, str) or item not in _JSON_TYPES for item in types):
        raise ModelCapabilityError(model, path, "Invalid schema type; refresh model metadata.")
    choices = raw.get("enum")
    if "enum" in raw and (not isinstance(choices, list) or not choices):
        raise ModelCapabilityError(model, path, "enum must be a non-empty array; refresh model metadata.")
    unknown = set(raw) - _ANNOTATIONS - {
        "type", "enum", "const", "default", "minimum", "maximum",
        "exclusiveMinimum", "exclusiveMaximum", "oneOf", "anyOf", "allOf",
    }
    for key in ("enum", "const", "default"):
        values = raw.get(key, []) if key == "enum" else [raw[key]] if key in raw else []
        for value in values:
            if value is not None and type(value) not in (str, int, float, bool):
                unknown.add(f"non-scalar {key}")
            elif type(value) is float and not math.isfinite(value):
                raise ModelCapabilityError(model, path, f"{key} must contain finite JSON values; refresh model metadata.")
    if "const" in raw:
        constant = raw["const"]
        choices = [constant] if choices is None else [item for item in choices if _same(item, constant)]
    bounds: list[int | float | None] = []
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        value = raw.get(key)
        if key in raw and not _number(value):
            raise ModelCapabilityError(model, path, f"{key} must be a finite number (not bool); refresh model metadata.")
        bounds.append(value)
    combinations = []
    for key in ("oneOf", "anyOf", "allOf"):
        if key in raw:
            branches = raw[key]
            if not isinstance(branches, list) or not branches:
                raise ModelCapabilityError(model, path, f"{key} must be a non-empty array of schemas; refresh model metadata.")
            compiled = tuple(_parse_scalar(branch, model, path, depth + 1) for branch in branches)
            combinations.append((key, compiled))
            unknown.update(branch.reason for branch in compiled if branch.reason)
    # Never retain mutable/unknown default or enum payloads in a frozen record.
    reason = f"Cannot validate scalar constraints: {', '.join(sorted(unknown))}." if unknown else None
    return _ScalarSchema(
        tuple(types), tuple(choices) if choices is not None and not reason else None,
        raw.get("default", _MISSING) if not reason else _MISSING,
        *bounds, tuple(combinations), reason,
    )


def _matches(schema: _ScalarSchema, value: Scalar) -> bool:
    """Evaluate supported constraints, including exact oneOf branch counts."""
    if not schema.allowed or schema.reason:
        return False
    if schema.types:
        if value is None:
            actual = "null"
        elif type(value) is bool:
            actual = "boolean"
        elif isinstance(value, str):
            actual = "string"
        else:
            # JSON Schema integers include integral JSON numbers (e.g. enum
            # 2.0). The public max_tokens argument still requires Python int.
            actual = "integer" if value == int(value) else "number"
        if actual not in schema.types and not (actual == "integer" and "number" in schema.types):
            return False
    if schema.choices is not None and not any(_same(value, item) for item in schema.choices):
        return False
    if _number(value):
        if schema.minimum is not None and value < schema.minimum:
            return False
        if schema.maximum is not None and value > schema.maximum:
            return False
        if schema.exclusive_minimum is not None and value <= schema.exclusive_minimum:
            return False
        if schema.exclusive_maximum is not None and value >= schema.exclusive_maximum:
            return False
    for kind, branches in schema.combinations:
        count = sum(_matches(branch, value) for branch in branches)
        if (kind == "oneOf" and count != 1) or (kind == "anyOf" and count == 0) or (kind == "allOf" and count != len(branches)):
            return False
    return True


def _finite_choices(schema: _ScalarSchema) -> tuple[Scalar, ...] | None:
    """Find a complete finite domain, never a partial union of known branches."""
    if not schema.allowed:
        return ()
    candidates = schema.choices
    for kind, branches in schema.combinations:
        parts = [_finite_choices(branch) for branch in branches]
        if kind == "allOf":
            finite = next((part for part in parts if part is not None), None)
        else:
            finite = tuple(value for part in parts for value in part) if all(part is not None for part in parts) else None
        if candidates is None and finite is not None:
            candidates = finite
    if candidates is None:
        return None
    result: list[Scalar] = []
    for value in candidates:
        if _matches(schema, value) and not any(_same(value, item) for item in result):
            result.append(value)
    return tuple(result)


def _schema_default(schema: _ScalarSchema, model: str, path: str) -> Scalar | object:
    """Use explicit defaults, rejecting invalid or conflicting branch defaults."""
    if schema.default is not _MISSING:
        defaults = [schema.default]
    else:
        defaults = [
            default for _, branches in schema.combinations for branch in branches
            if (default := _schema_default(branch, model, path)) is not _MISSING
        ]
    if not defaults:
        return _MISSING
    value = defaults[0]
    if any(not _same(value, other) for other in defaults[1:]):
        raise ModelCapabilityError(model, path, "Conflicting advertised defaults; refresh metadata with one unambiguous default.")
    if not _matches(schema, value):
        raise ModelCapabilityError(model, path, f"Advertised default {value!r} violates its schema; refresh model metadata.")
    return value


def _enum_capability(
    raw: Any, path: tuple[str, ...], model: str, parent: _ObjectSchema
) -> EnumCapability:
    """Resolve finite string choices or a reason why support cannot be proven."""
    if parent.reason:
        return EnumCapability(CapabilityStatus.UNKNOWN, path, reason=parent.reason)
    if raw is _MISSING or not parent.allowed:
        return EnumCapability(CapabilityStatus.UNSUPPORTED, path, reason="This field is not advertised by the schema.")
    schema = _parse_scalar(raw, model, ".".join(path))
    if schema.reason:
        return EnumCapability(CapabilityStatus.UNKNOWN, path, reason=schema.reason)
    choices = _finite_choices(schema)
    if choices is None:
        return EnumCapability(CapabilityStatus.UNKNOWN, path, reason="No complete finite enum of accepted strings is advertised.")
    if any(not isinstance(value, str) or not value for value in choices):
        raise ModelCapabilityError(model, ".".join(path), "Expected non-empty string choices; refresh model metadata.")
    default = _schema_default(schema, model, ".".join(path))
    return EnumCapability(
        CapabilityStatus.SUPPORTED if choices else CapabilityStatus.UNSUPPORTED,
        path, choices, None if default is _MISSING else default,
        None if choices else "The schema allows no values for this field.",
    )


def _integer_bounds(schema: _ScalarSchema) -> tuple[int, int | None]:
    """Compute an inclusive integer envelope; exact constraints remain compiled."""
    lower, upper = 1, None
    if not schema.allowed or (schema.types and not {"integer", "number"}.intersection(schema.types)):
        return 1, 0
    if schema.minimum is not None:
        lower = max(lower, math.ceil(schema.minimum))
    if schema.exclusive_minimum is not None:
        lower = max(lower, math.floor(schema.exclusive_minimum) + 1)
    if schema.maximum is not None:
        upper = math.floor(schema.maximum)
    if schema.exclusive_maximum is not None:
        bound = math.ceil(schema.exclusive_maximum) - 1
        upper = bound if upper is None else min(upper, bound)
    finite = _finite_choices(schema)
    if finite is not None:
        integers = [int(value) for value in finite if _number(value) and value == int(value) and value > 0]
        if not integers:
            return 1, 0
        lower = max(lower, min(integers))
        upper = max(integers) if upper is None else min(upper, max(integers))
    for kind, branches in schema.combinations:
        intervals = [_integer_bounds(branch) for branch in branches]
        if kind == "allOf":
            low = max(item[0] for item in intervals)
            highs = [item[1] for item in intervals if item[1] is not None]
            high = min(highs) if highs else None
        else:
            intervals = [(lo, hi) for lo, hi in intervals if hi is None or lo <= hi]
            if not intervals:
                return 1, 0
            low = min(item[0] for item in intervals)
            high = None if any(item[1] is None for item in intervals) else max(item[1] for item in intervals)
        lower = max(lower, low)
        if high is not None:
            upper = high if upper is None else min(upper, high)
    return lower, upper


def _integer_capability(
    raw: Any, model: str, parent: _ObjectSchema, limits: TokenLimits | None,
    *, name: str = "max_tokens",
) -> IntegerCapability:
    """Compile max_tokens only when its additional-fields path is advertised."""
    if parent.reason:
        return IntegerCapability(CapabilityStatus.UNKNOWN, reason=parent.reason)
    if raw is _MISSING or not parent.allowed:
        return IntegerCapability(CapabilityStatus.UNSUPPORTED, reason=f"No {name} additional request field is advertised.")
    schema = _parse_scalar(raw, model, name)
    if schema.reason:
        return IntegerCapability(CapabilityStatus.UNKNOWN, reason=schema.reason)
    if not schema.allowed:
        return IntegerCapability(
            CapabilityStatus.UNSUPPORTED, reason=f"The schema explicitly forbids {name}."
        )
    if schema == _ScalarSchema():
        return IntegerCapability(CapabilityStatus.UNKNOWN, reason=f"An unrestricted {name} schema does not advertise numeric constraints.")
    low, high = _integer_bounds(schema)
    if limits is not None and limits.max_output_tokens is not None:
        high = limits.max_output_tokens if high is None else min(high, limits.max_output_tokens)
    if high is not None and low > high:
        raise ModelCapabilityError(model, name, "Schema/tokenLimits allow no positive integer token count; refresh model metadata.")
    default = _schema_default(schema, model, name)
    if default is not _MISSING and (type(default) is not int or default < low or (high is not None and default > high)):
        raise ModelCapabilityError(model, name, "Advertised default is not a positive integer within the advertised limits; refresh model metadata.")
    return IntegerCapability(CapabilityStatus.SUPPORTED, low, high, None if default is _MISSING else default, _schema=schema)


def _require_support(
    capabilities: ModelCapabilities, name: str, capability: EnumCapability | IntegerCapability
) -> None:
    """Fail closed instead of dropping or forwarding an unverified parameter."""
    if capability.status is not CapabilityStatus.SUPPORTED:
        action = "Refresh model metadata or explicitly select an unvalidated transport policy outside this helper." if capability.status is CapabilityStatus.UNKNOWN else "Omit this parameter or select a model that advertises it."
        raise ModelCapabilityError(capabilities.model_id, name, f"Capability is {capability.status.value}. {capability.reason or ''} {action}", status=capability.status)


def build_model_request_fields(
    capabilities: ModelCapabilities,
    *,
    effort: str | None = None,
    thinking: ThinkingMode | None = None,
    max_tokens: int | None = None,
    thinking_budget: int | None = None,
) -> dict[str, Any] | None:
    """Build additionalModelRequestFields from verified metadata, without I/O.

    Args:
        capabilities: Snapshot returned by ModelCapabilities.from_model.
        effort: Exact advertised string, including none/minimal/xhigh if allowed.
            None means omitted, not the literal effort "none". No aliases/casing
            changes are applied. output_config precedes reasoning, as in the CLI.
        thinking: Native mode string enabled/disabled/adaptive, not a bool or
            client thinking object. Pass an explicit advertised budget separately.
        thinking_budget: Optional exact thinking.budget_tokens value; validated
            independently of output limits and never fabricated or silently removed.
        max_tokens: Positive Python int (not bool). Must have an advertised
            max_tokens schema and satisfy both it and tokenLimits.maxOutputTokens.

    Returns:
        A fresh nested dictionary, or None when nothing is requested/defaulted.
        Unknown/unsupported fields contribute no defaults. Explicit arguments
        take precedence over advertised defaults and are never silently removed.

    Raises:
        ModelCapabilityError: Unsupported/unknown explicit fields, invalid values,
            missing required fields, or disabled thinking combined with xhigh/max
            effort (even if one value came from a default). No value is capped,
            raised to a minimum, or downgraded. Pure helper; caller owns logging.
    """
    if not isinstance(capabilities, ModelCapabilities):
        raise ModelCapabilityError("<unknown>", "capabilities", "Parse model metadata with ModelCapabilities.from_model first.")
    values = {"effort": effort, "thinking": thinking, "max_tokens": max_tokens, "thinking_budget": thinking_budget}
    result: dict[str, Any] = {}
    for name, capability in (("effort", capabilities.effort), ("thinking", capabilities.thinking), ("max_tokens", capabilities.max_tokens), ("thinking_budget", capabilities.thinking_budget)):
        value = values[name]
        if value is not None:
            _require_support(capabilities, name, capability)
        elif capability.status is CapabilityStatus.SUPPORTED:
            value = capability.default
        if value is None:
            continue
        if isinstance(capability, IntegerCapability):
            tokens = capability
            if type(value) is not int or value <= 0:
                raise ModelCapabilityError(capabilities.model_id, name, "Use a positive integer, not bool, float, or a string.")
            if (tokens.minimum is not None and value < tokens.minimum) or (tokens.maximum is not None and value > tokens.maximum):
                raise ModelCapabilityError(capabilities.model_id, name, f"Requested {value}; use a value in [{tokens.minimum}, {tokens.maximum if tokens.maximum is not None else 'unbounded'}]. Token counts are never clamped.")
            if tokens._schema is None or not _matches(tokens._schema, value):
                raise ModelCapabilityError(capabilities.model_id, name, "Value violates the advertised enum/union constraints; select an allowed token count.")
            if name == "thinking_budget":
                result.setdefault("thinking", {})["budget_tokens"] = value
            else:
                result[name] = value
        else:
            choice = capabilities.effort if name == "effort" else capabilities.thinking
            if not isinstance(value, str) or value not in choice.values:
                raise ModelCapabilityError(capabilities.model_id, name, f"Use an advertised value: {', '.join(choice.values)}; received {value!r}.")
            if name == "thinking" and value not in _THINKING_MODES:
                raise ModelCapabilityError(capabilities.model_id, name, "Use enabled, disabled, or adaptive.")
            result[choice.path[0]] = {choice.path[1]: value}
        values[name] = value
    if values["thinking"] == "disabled" and values["thinking_budget"] is not None:
        raise ModelCapabilityError(capabilities.model_id, "thinking.budget_tokens", "A thinking budget cannot be combined with disabled thinking; omit the budget or explicitly enable an advertised mode.")
    if values["thinking"] == "disabled" and values["effort"] in _THINKING_REQUIRED_EFFORTS:
        raise ModelCapabilityError(capabilities.model_id, "effort", "xhigh/max effort is incompatible with disabled thinking. Enable an advertised thinking mode or explicitly choose a supported lower effort; no automatic downgrade is performed.")
    if not result:
        return None
    for parent in capabilities._objects:
        obj = result.get(parent.path[0]) if parent.path else result
        if obj is None:
            continue
        missing = [key for key in parent.required if key not in obj]
        if missing:
            path = ".".join((*parent.path, missing[0]))
            raise ModelCapabilityError(capabilities.model_id, path, "The advertised schema requires this field. Supply it through a capable adapter or choose a schema/mode without this requirement; it will not be invented.")
    return result

def build_responses_request_fields(
    capabilities: ModelCapabilities, *, effort: str | None = None,
    thinking: ThinkingMode | None = None, max_tokens: int | None = None,
    thinking_budget: int | None = None,
) -> dict[str, Any] | None:
    """Prepare semantic fields for the modeled global Responses operation.

    Its max_output_tokens and reasoning controls are not Generate's per-model
    additional-field transport. Preserve explicit global fields; use model
    limits/effort choices when advertised, but never invent defaults from a name.
    No Responses thinking-token budget mapping is established by the reference.
    """
    if thinking_budget is not None:
        raise ModelCapabilityError(capabilities.model_id, "thinking.budget_tokens", "Responses has no verified thinking-budget mapping; use the generate protocol with an advertised budget field.")
    if thinking is not None and thinking not in _THINKING_MODES:
        raise ModelCapabilityError(capabilities.model_id, "thinking", "Use enabled, disabled or adaptive.")
    result: dict[str, Any] = {}
    if max_tokens is not None:
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ModelCapabilityError(capabilities.model_id, "max_tokens", "Use a positive integer output limit.")
        ceiling = capabilities.token_limits.max_output_tokens if capabilities.token_limits else None
        if ceiling is not None and max_tokens > ceiling:
            raise ModelCapabilityError(capabilities.model_id, "max_tokens", f"Requested limit exceeds advertised model output limit {ceiling}; no clamping is performed.")
        result["max_tokens"] = max_tokens
    explicit_effort = effort is not None
    if thinking == "disabled":
        if effort is not None and effort != "none":
            raise ModelCapabilityError(capabilities.model_id, "effort", "Responses disabled thinking requires reasoning effort none; conflicting explicit effort cannot be ignored.")
        effort = "none"
    elif effort is None and capabilities.effort.status is CapabilityStatus.SUPPORTED:
        effort = capabilities.effort.default
    if thinking in ("enabled", "adaptive") and (effort is None or effort == "none"):
        raise ModelCapabilityError(capabilities.model_id, "thinking", "Set an advertised non-none effort to express enabled/adaptive thinking on Responses.")
    if effort is not None:
        if not isinstance(effort, str) or not effort or effort != effort.strip():
            raise ModelCapabilityError(capabilities.model_id, "effort", "Use an exact nonempty effort string.")
        disabling = effort == "none" and (thinking == "disabled" or "disabled" in capabilities.thinking.values)
        if capabilities.effort.status is CapabilityStatus.SUPPORTED and not disabling and effort not in capabilities.effort.values:
            raise ModelCapabilityError(capabilities.model_id, "effort", "Effort is not advertised for this model.")
        result["reasoning"] = {"effort": effort}
    return result or None
