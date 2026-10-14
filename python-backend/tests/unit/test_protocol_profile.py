"""Standalone offline profile tests; no backend bootstrap, secrets, or fixtures.

Run from the workspace root with:
    python -B -m pytest -q -p no:cacheprovider python-backend/tests/unit/test_protocol_profile.py

Loading the one pure module by path intentionally avoids backend conftest hooks
(which create credential fixtures and initialize unrelated application code).
"""

from __future__ import annotations

import builtins
import importlib.util
import itertools
import os
from pathlib import Path
import socket
import sys
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "extensions/protocol_profile.py"
_SPEC = importlib.util.spec_from_file_location("_kiroaas_protocol_profile_tests", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
ProtocolProfile = _MODULE.ProtocolProfile
select_protocol_profile = _MODULE.select_protocol_profile
token_type_for_auth_method = _MODULE.token_type_for_auth_method

AWS_JSON = "application/x-amz-json-1.0"
JSON = "application/json"
LEGACY_TARGET = "AmazonCodeWhispererStreamingService.GenerateAssistantResponse"
CLI_TARGET = "KiroRuntimeService.GenerateAssistantResponse"
USAGE_TARGET = "com.amazon.aws.codewhisperer.runtime.AmazonCodeWhispererService.GetUsageLimits"
VERSION = "2026.10.14-rc.1+offline"
TOKEN = "synthetic-test-token"
PROFILE_ARN = "arn:aws:codewhisperer:us-east-1:123456789012:profile/test-only"


def headers(profile: Any, operation: str | None = None, **kwargs: Any) -> dict[str, str]:
    """Build headers from explicit synthetic test values, never local secrets."""
    return profile.build_headers(app_version=VERSION, token=TOKEN, operation=operation, **kwargs)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make accidental network calls fail before opening sockets or DNS."""
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Offline test attempted network access")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def test_default_profile_is_explicit_legacy_generate() -> None:
    profile = select_protocol_profile()
    assert profile == ProtocolProfile()
    assert profile.name == "legacy"
    assert profile.generation_protocol == "generate"
    assert profile.native_system_prompt is False
    assert profile.data_collection_opt_out is True
    assert profile.origin == "AI_EDITOR"
    assert profile.body_content_type == AWS_JSON
    assert profile.streaming_target == LEGACY_TARGET
    assert profile.runtime_endpoint == "https://runtime.us-east-1.kiro.dev"
    assert profile.management_endpoint == "https://management.us-east-1.kiro.dev"
    assert profile.legacy_q_endpoint == "https://q.us-east-1.amazonaws.com"
    assert profile.resolve_operation().name == "generateAssistantResponse"


@pytest.mark.parametrize("name,protocol,native,opt_out", tuple(itertools.product(
    ("legacy", "cli"), ("generate", "responses"), (False, True), (False, True),
)))
def test_all_explicit_profile_combinations_are_consistent(
    name: str, protocol: str, native: bool, opt_out: bool,
) -> None:
    profile = select_protocol_profile(
        name, generation_protocol=protocol, native_system_prompt=native,
        data_collection_opt_out=opt_out,
    )
    spec = profile.resolve_operation()
    result = headers(profile)
    assert profile.origin == ("AI_EDITOR" if name == "legacy" else "KIRO_CLI")
    assert profile.native_system_prompt is native
    assert result["Content-Type"] == spec.content_type == profile.body_content_type
    assert result.get("x-amz-target") == spec.amz_target == profile.streaming_target
    if protocol == "responses":
        assert spec.name == "responses"
        assert spec.url.endswith("/v1/responses")
        assert spec.amz_target is None
        assert result["x-amzn-kiro-origin"] == profile.origin
        assert result["x-amzn-codewhisperer-optout"] == str(opt_out).lower()
    else:
        assert spec.name == "generateAssistantResponse"
        assert spec.amz_target == (LEGACY_TARGET if name == "legacy" else CLI_TARGET)
        assert result.get("x-amzn-codewhisperer-optout") == ("true" if opt_out else None)
        assert "x-amzn-kiro-origin" not in result


@pytest.mark.parametrize("name,operation,method,url,content_type,target", [
    ("legacy", "generateAssistantResponse", "POST", "https://runtime.us-east-1.kiro.dev/generateAssistantResponse", AWS_JSON, LEGACY_TARGET),
    ("legacy", "ListAvailableModels", "GET", "https://q.us-east-1.amazonaws.com/ListAvailableModels", JSON, None),
    ("legacy", "GetUsageLimits", "POST", "https://q.us-east-1.amazonaws.com/", AWS_JSON, USAGE_TARGET),
    ("legacy", "mcp", "POST", "https://q.us-east-1.amazonaws.com/mcp", JSON, None),
    ("cli", "generateAssistantResponse", "POST", "https://runtime.us-east-1.kiro.dev/", AWS_JSON, CLI_TARGET),
    ("cli", "ListAvailableModels", "POST", "https://management.us-east-1.kiro.dev/", AWS_JSON, "KiroControlPlaneBearerService.ListAvailableModels"),
    ("cli", "GetUsageLimits", "POST", "https://management.us-east-1.kiro.dev/", AWS_JSON, "KiroControlPlaneBearerService.GetUsageLimits"),
    ("cli", "mcp", "POST", "https://runtime.us-east-1.kiro.dev/", AWS_JSON, "KiroRuntimeService.InvokeMCP"),
])
def test_operation_wire_paths_methods_and_targets(
    name: str, operation: str, method: str, url: str, content_type: str, target: str | None,
) -> None:
    profile = select_protocol_profile(name)
    spec = profile.resolve_operation(operation)
    assert (spec.name, spec.method, spec.url, spec.content_type, spec.amz_target) == (
        operation, method, url, content_type, target,
    )
    result = headers(profile, operation)
    assert result["Content-Type"] == content_type
    assert result.get("x-amz-target") == target
    if operation != "generateAssistantResponse":
        assert result.get("x-amz-target") not in (LEGACY_TARGET, CLI_TARGET)
        assert "x-amzn-kiro-origin" not in result


@pytest.mark.parametrize("name,operation", tuple(itertools.product(
    ("legacy", "cli"), ("ListAvailableModels", "GetUsageLimits", "mcp"),
)))
def test_generation_selection_does_not_change_other_operations(name: str, operation: str) -> None:
    generate = select_protocol_profile(name)
    responses = select_protocol_profile(name, generation_protocol="responses", native_system_prompt=True)
    assert generate.resolve_operation(operation) == responses.resolve_operation(operation)
    assert headers(generate, operation) == headers(responses, operation)


@pytest.mark.parametrize("protocol,inactive", [
    ("generate", "responses"), ("responses", "generateAssistantResponse"),
])
def test_generation_cannot_be_switched_implicitly(protocol: str, inactive: str) -> None:
    profile = select_protocol_profile(generation_protocol=protocol)
    with pytest.raises(ValueError, match="generation_protocol"):
        profile.resolve_operation(inactive)
    with pytest.raises(ValueError, match="generation_protocol"):
        headers(profile, inactive)


@pytest.mark.parametrize("method,expected", [
    (None, None), ("IdC", "SSO_OIDC"), ("SSO", "SSO_OIDC"),
    ("SSO_OIDC", "SSO_OIDC"), ("aws_sso_oidc", "SSO_OIDC"),
    ("external_idp", "EXTERNAL_IDP"), ("machine_token", "KIRO_MACHINE_TOKEN"),
    ("api_key", "API_KEY"), ("kiro_desktop", None), ("social", None),
    ("google", None), ("github", None), ("builder_id", None),
    ("idc", None), ("API_KEY", None), ("EXTERNAL_IDP", None), ("unknown", None),
])
@pytest.mark.parametrize("name", ["legacy", "cli"])
def test_auth_mapping_is_explicit_for_every_operation(method: str | None, expected: str | None, name: str) -> None:
    assert token_type_for_auth_method(method) == expected
    for protocol in ("generate", "responses"):
        profile = select_protocol_profile(name, generation_protocol=protocol)
        for operation in (None, "ListAvailableModels", "GetUsageLimits", "mcp"):
            result = headers(profile, operation, auth_method=method)
            assert result.get("TokenType") == expected
            assert ("TokenType" in result) == (expected is not None)
            assert result["Authorization"] == f"Bearer {TOKEN}"
            assert "x-api-key" not in result


@pytest.mark.parametrize("token", ["IdC", "api_key", "eyJhbGciOiJub25lIn0.test.signature", "EXTERNAL_IDP"])
def test_auth_is_never_inferred_from_bearer_text(token: str) -> None:
    result = select_protocol_profile("cli").build_headers(app_version=VERSION, token=token)
    assert "TokenType" not in result


@pytest.mark.parametrize("name,protocol", tuple(itertools.product(("legacy", "cli"), ("generate", "responses"))))
def test_user_agents_are_truthful_and_headers_have_no_transport_fabrication(name: str, protocol: str) -> None:
    profile = select_protocol_profile(name, generation_protocol=protocol)
    for operation in (None, "ListAvailableModels", "GetUsageLimits", "mcp"):
        result = headers(profile, operation)
        assert result["User-Agent"] == result["x-amz-user-agent"] == f"KiroaaS/{VERSION}"
        assert not any(k in result for k in ("amz-sdk-invocation-id", "amz-sdk-request", "Host"))
        assert all(bad not in str(result) for bad in ("KiroIDE", "KiroCLI/", "0.7.45", "aws-sdk-js", "win32"))
        assert len({key.lower() for key in result}) == len(result)


@pytest.mark.parametrize("name", ["legacy", "cli"])
def test_profile_header_is_only_for_raw_responses(name: str) -> None:
    for protocol in ("generate", "responses"):
        profile = select_protocol_profile(name, generation_protocol=protocol)
        assert "x-amzn-kiro-profile" not in headers(profile)
        for operation in (None, "ListAvailableModels", "GetUsageLimits", "mcp"):
            result = headers(profile, operation, profile_arn=PROFILE_ARN)
            assert result.get("x-amzn-kiro-profile") == (PROFILE_ARN if protocol == "responses" and operation is None else None)


def test_profiles_operations_and_private_mapping_are_immutable() -> None:
    profile = select_protocol_profile()
    for field, value in (("name", "cli"), ("runtime_endpoint", "https://other.example"), ("native_system_prompt", True)):
        with pytest.raises(FrozenInstanceError):
            setattr(profile, field, value)
    with pytest.raises(FrozenInstanceError):
        profile.resolve_operation().url = "https://other.example/"
    with pytest.raises(FrozenInstanceError):
        del profile.name
    with pytest.raises(TypeError):
        _MODULE._TOKEN_TYPES["api_key"] = "fake"
    assert not hasattr(profile, "__dict__")
    assert hash(profile) == hash(select_protocol_profile())
    assert replace(profile, name="cli").origin == "KIRO_CLI"
    with pytest.raises(ValueError):
        replace(profile, name="automatic")


def test_headers_are_fresh_and_tokens_never_persist_in_profile() -> None:
    profile = select_protocol_profile("cli")
    before = asdict(profile)
    first = headers(profile, auth_method="IdC")
    first["TokenType"] = "changed"
    first["Authorization"] = "changed"
    first["x-amz-target"] = "changed"
    assert headers(profile, auth_method="IdC")["TokenType"] == "SSO_OIDC"
    assert headers(profile)["Authorization"] == f"Bearer {TOKEN}"
    assert headers(profile)["x-amz-target"] == CLI_TARGET
    assert asdict(profile) == before
    assert TOKEN not in repr(profile)


@pytest.mark.parametrize("region", ["us-east-1", "eu-central-1", "us-gov-east-1", "us-gov-west-1", "ap-southeast-2", "us-iso-east-1", "eusc-de-east-1"])
def test_valid_region_shapes_apply_to_each_independent_origin(region: str) -> None:
    profile = select_protocol_profile("cli", region=region)
    assert profile.runtime_endpoint == f"https://runtime.{region}.kiro.dev"
    assert profile.management_endpoint == f"https://management.{region}.kiro.dev"
    assert profile.legacy_q_endpoint == f"https://q.{region}.amazonaws.com"


@pytest.mark.parametrize("endpoint,normalized", [
    ("https://example.com", "https://example.com"),
    ("HTTPS://EXAMPLE.COM/", "https://example.com"),
    ("https://example.com:8443/", "https://example.com:8443"),
    ("https://localhost:443", "https://localhost:443"),
    ("https://127.0.0.1:8443/", "https://127.0.0.1:8443"),
    ("https://[2001:db8::1]:443/", "https://[2001:db8::1]:443"),
])
def test_endpoint_validation_is_origin_only_not_cloud_authorization(endpoint: str, normalized: str) -> None:
    profile = select_protocol_profile(runtime_endpoint=endpoint)
    assert profile.runtime_endpoint == normalized
    assert profile.resolve_operation().url == normalized + "/generateAssistantResponse"
    assert profile.management_endpoint == "https://management.us-east-1.kiro.dev"
    assert profile.legacy_q_endpoint == "https://q.us-east-1.amazonaws.com"


@pytest.mark.parametrize("name,protocol", tuple(itertools.product(("legacy", "cli"), ("generate", "responses"))))
def test_explicit_endpoint_overrides_never_cross_service_boundaries(name: str, protocol: str) -> None:
    profile = select_protocol_profile(
        name, generation_protocol=protocol,
        runtime_endpoint="https://runtime.example:8443/",
        management_endpoint="https://management.example/",
        legacy_q_endpoint="https://q.example/",
    )
    assert urlsplit(profile.resolve_operation().url).netloc == "runtime.example:8443"
    for operation in ("ListAvailableModels", "GetUsageLimits"):
        assert urlsplit(profile.resolve_operation(operation).url).netloc == ("management.example" if name == "cli" else "q.example")
    assert urlsplit(profile.resolve_operation("mcp").url).netloc == ("runtime.example:8443" if name == "cli" else "q.example")


@pytest.mark.parametrize("field,bad", [
    *[("name", v) for v in (None, "", "CLI", "auto", " cli", "legacy\n", 0, False, [], {})],
    *[("generation_protocol", v) for v in (None, "", "auto", "response", "Responses", "generate ", [], True)],
    *[(field, v) for field in ("native_system_prompt", "data_collection_opt_out") for v in (None, "false", "true", 0, 1, [], {})],
    *[("region", v) for v in (None, "", 1, False, [], "US-EAST-1", " us-east-1", "us-east-1\n", "us-east-0", "us-east-01", "us_east_1", "us-east", "us-east-1.evil", "us-east-1/path", "us-east-1:443", "us-east-1@evil", "u-east-1", "us--east-1", "us-east-1\x7f", "us-east-1\u2028", "x" * 4096)],
])
def test_malformed_configuration_is_rejected_by_factory_and_constructor(field: str, bad: Any) -> None:
    for factory in (select_protocol_profile, ProtocolProfile):
        with pytest.raises(ValueError, match=field):
            factory(**{field: bad})


@pytest.mark.parametrize("field", ["runtime_endpoint", "management_endpoint", "legacy_q_endpoint"])
@pytest.mark.parametrize("bad", [
    "", False, 0, [], {}, "http://example.com", "http://localhost:8080",
    "ftp://example.com", "//example.com", "https:example.com", "https:///example.com",
    "https://user:synthetic-secret@example.com", "https://user@example.com", "https://@example.com",
    "https://example.com/path", "https://example.com//", "https://example.com/../",
    "https://example.com?token=synthetic-secret", "https://example.com?", "https://example.com#",
    "https://example.com/#synthetic-secret", "https://example.com/%0a",
    "https://user%40example.com", "https://example.com\\@evil.example", "https://example.com\\evil",
    " https://example.com", "https://example.com\n", "https://exa\tmple.com", "https://example.com\x00",
    "https://example.com\x7f", "https://example.com\u0085", "https://example.com\u2028", "https://ｅxample.com",
    "https://example.com:0", "https://example.com:65536", "https://example.com:-1",
    "https://example.com:+443", "https://example.com:", "https://example.com:port",
    "https://", "https://.", "https://example..com", "https://-example.com", "https://example-.com",
    "https://example_com", "https://example.com.", "https://999.1.1.1", "https://2130706433",
    "https://[::1", "https://[::1]junk", "https://[v1.foo]", "https://[fe80::1%25eth0]",
    "https://" + "a" * 64 + ".example", "https://" + ".".join(["a" * 60] * 5),
    "https://" + "a" * 2050,
])
def test_all_endpoint_overrides_reject_malformed_or_credential_urls(field: str, bad: Any) -> None:
    for factory in (select_protocol_profile, ProtocolProfile):
        with pytest.raises(ValueError) as caught:
            factory(**{field: bad})
        assert field in str(caught.value)
        assert "synthetic-secret" not in str(caught.value)


@pytest.mark.parametrize("bad", ["", "GenerateAssistantResponse", "Responses", "generate", "getUsageLimits", "MCP", "/mcp", "ListAvailableModels\n", [], {}, True, 1])
def test_unknown_operations_cannot_become_paths_or_targets(bad: Any) -> None:
    profile = select_protocol_profile("cli")
    with pytest.raises(ValueError, match="operation"):
        profile.resolve_operation(bad)
    with pytest.raises(ValueError, match="operation"):
        headers(profile, bad)


@pytest.mark.parametrize("field,bad", [
    *[("app_version", v) for v in (None, "", 1, [], "1.0\nX: bad", "1.0 fake/1", "1/2", "x" * 129, "版本", "1.0\x7f")],
    *[("token", v) for v in (None, "", 1, [], "Bearer value", " token", "token ", "secret\r\nX:bad", "secret\x00", "secret\x7f", "secret\u0085", "secret\u2028")],
    *[("profile_arn", v) for v in ("", 1, [], "profile\nX:bad", "profile\tbad", "profile\x7f")],
    *[("auth_method", v) for v in ("", 1, [], {}, "IdC\r\nX:bad", "IdC ", "SSO OIDC", "IdC\x7f", "x" * 65)],
])
def test_header_inputs_reject_injection_without_echoing_credentials(field: str, bad: Any) -> None:
    values = {"app_version": VERSION, "token": TOKEN, "profile_arn": PROFILE_ARN, "auth_method": "IdC"}
    values[field] = bad
    with pytest.raises(ValueError, match=field) as caught:
        select_protocol_profile(generation_protocol="responses").build_headers(**values)
    assert TOKEN not in str(caught.value)
    assert "secret" not in str(caught.value)
    assert PROFILE_ARN not in str(caught.value)


def test_unknown_configuration_fields_and_missing_version_are_not_silently_accepted() -> None:
    with pytest.raises(TypeError):
        select_protocol_profile(auto_detect=True)
    with pytest.raises(TypeError):
        select_protocol_profile().build_headers(token=TOKEN)
    with pytest.raises(TypeError):
        select_protocol_profile().build_headers(app_version=VERSION)
    with pytest.raises(TypeError):
        select_protocol_profile().build_headers(app_version=VERSION, token=TOKEN, extra_headers={"x-amz-target": "unsafe"})


def test_resolution_reads_no_environment_files_or_secrets_and_performs_no_io() -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Pure resolution attempted I/O or ambient configuration")

    with patch.object(builtins, "open", denied), patch.object(Path, "read_text", denied), patch.object(Path, "read_bytes", denied), patch.object(os, "getenv", denied), patch.object(os, "environ", {}):
        for name, protocol in itertools.product(("legacy", "cli"), ("generate", "responses")):
            profile = select_protocol_profile(name, generation_protocol=protocol)
            for operation in (None, "ListAvailableModels", "GetUsageLimits", "mcp"):
                spec = profile.resolve_operation(operation)
                result = headers(profile, operation, auth_method="api_key")
                assert result["Content-Type"] == spec.content_type
                assert spec.url.startswith("https://")


@pytest.mark.parametrize("codepoint", list(range(33)) + list(range(127, 160)))
def test_every_ascii_control_and_c1_control_is_rejected(codepoint: int) -> None:
    control = chr(codepoint)
    config_values = {
        "name": f"cli{control}",
        "generation_protocol": f"generate{control}",
        "region": f"us-east-{control}1",
        "runtime_endpoint": f"https://exa{control}mple.com",
        "management_endpoint": f"https://exa{control}mple.com",
        "legacy_q_endpoint": f"https://exa{control}mple.com",
    }
    for field, value in config_values.items():
        with pytest.raises(ValueError):
            select_protocol_profile(**{field: value})
    profile = select_protocol_profile()
    for field, value in (
        ("app_version", f"1.{control}0"), ("token", f"token{control}value"),
        ("profile_arn", f"arn:{control}profile"), ("auth_method", f"IdC{control}"),
    ):
        values = {"app_version": VERSION, "token": TOKEN, field: value}
        with pytest.raises(ValueError):
            profile.build_headers(**values)


@pytest.mark.parametrize("name,protocol", tuple(itertools.product(("legacy", "cli"), ("generate", "responses"))))
def test_opt_in_policy_is_consistent_for_every_operation(name: str, protocol: str) -> None:
    profile = select_protocol_profile(name, generation_protocol=protocol, data_collection_opt_out=False)
    for operation in (None, "ListAvailableModels", "GetUsageLimits", "mcp"):
        expected = "false" if protocol == "responses" and operation is None else None
        assert headers(profile, operation).get("x-amzn-codewhisperer-optout") == expected


@pytest.mark.parametrize("port", [1, 443, 65535])
def test_port_range_boundaries_are_valid(port: int) -> None:
    profile = select_protocol_profile(runtime_endpoint=f"https://example.com:{port}/")
    assert profile.runtime_endpoint == f"https://example.com:{port}"


@pytest.mark.parametrize("version", ["1", "1.0.0", "v2.1.3-rc.4+sha.abcdef", "a" * 128])
def test_version_token_boundaries_are_preserved_exactly(version: str) -> None:
    result = select_protocol_profile().build_headers(app_version=version, token=TOKEN)
    assert result["User-Agent"] == f"KiroaaS/{version}"


def test_ambient_configuration_and_endpoint_spelling_do_not_select_profile() -> None:
    with patch.dict(os.environ, {"KIRO_PROTOCOL_PROFILE": "cli", "KIRO_GENERATION_PROTOCOL": "responses", "KIRO_NATIVE_SYSTEM_PROMPT": "true"}):
        profile = select_protocol_profile(runtime_endpoint="https://management.example")
        assert profile.name == "legacy"
        assert profile.generation_protocol == "generate"
        assert profile.native_system_prompt is False
        assert profile.resolve_operation().url == "https://management.example/generateAssistantResponse"
        assert headers(profile, auth_method="IdC")["x-amz-target"] == LEGACY_TARGET
