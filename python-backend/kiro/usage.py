"""Translate authoritative Responses counters without inventing token usage."""

from typing import Any


def validate_responses_usage(value: Any) -> dict:
    """Validate only modeled token counters; retain provider extensions verbatim."""
    if not isinstance(value, dict):
        raise ValueError("Responses usage must be an object")
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        if name in value and (type(value[name]) is not int or value[name] < 0):
            raise ValueError(f"Responses usage.{name} must be a nonnegative integer")
    for group, name in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens")):
        detail = value.get(group)
        if detail is not None:
            if not isinstance(detail, dict):
                raise ValueError(f"Responses usage.{group} must be an object")
            if name in detail and (type(detail[name]) is not int or detail[name] < 0):
                raise ValueError(f"Responses usage.{group}.{name} must be a nonnegative integer")
    cached = (value.get("input_tokens_details") or {}).get("cached_tokens", 0)
    if "input_tokens" in value and cached > value["input_tokens"]:
        raise ValueError("Cached input tokens cannot exceed total input tokens")
    reasoning = (value.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
    if "output_tokens" in value and reasoning > value["output_tokens"]:
        raise ValueError("Reasoning output tokens cannot exceed total output tokens")
    return value


def authoritative_usage(usage: dict | None, api: str) -> dict:
    """Return only known standard counters, overriding estimates when available.

    Responses input_tokens includes cached tokens. Anthropic exposes uncached
    input_tokens plus a separate cache_read_input_tokens counter. Missing usage
    stays missing: no cost, cached count, or output count is fabricated.
    """
    if not isinstance(usage, dict) or not isinstance(usage.get("_responses_usage"), dict):
        return {}
    value = validate_responses_usage(usage["_responses_usage"])
    result = {}
    details = value.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    if api == "anthropic":
        if "input_tokens" in value:
            result["input_tokens"] = value["input_tokens"] - cached
        if "cached_tokens" in details:
            result["cache_read_input_tokens"] = cached
        if "output_tokens" in value:
            result["output_tokens"] = value["output_tokens"]
    elif api == "openai":
        if "input_tokens" in value:
            result["prompt_tokens"] = value["input_tokens"]
        if "output_tokens" in value:
            result["completion_tokens"] = value["output_tokens"]
        if "input_tokens" in value and "output_tokens" in value:
            result["total_tokens"] = value["input_tokens"] + value["output_tokens"]
        if "cached_tokens" in details:
            result["prompt_tokens_details"] = {"cached_tokens": cached}
        output_details = value.get("output_tokens_details") or {}
        if "reasoning_tokens" in output_details:
            result["completion_tokens_details"] = {"reasoning_tokens": output_details["reasoning_tokens"]}
    else:
        raise ValueError("Unknown API usage surface")
    return result
