"""Explicit protocol settings and operation-aware wire preparation.

Legacy routing stays the default. CLI RPC, management and raw Responses require
explicit selection. This module does not acquire credentials or send requests.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any
from urllib.parse import urlsplit

from extensions.protocol_profile import OperationSpec, ProtocolProfile, select_protocol_profile
from extensions.request_context import current_state
from extensions.responses_adapter import build_responses_payload
from kiro.client_identity import application_version

_UNSET = object()

GENERATION_OPERATIONS = frozenset(("generateAssistantResponse", "responses"))
CONTROL_OPERATIONS = frozenset(("ListAvailableModels", "GetUsageLimits", "ListAvailableProfiles", "mcp"))


def _flag(name: str, default: bool) -> bool:
    """Reject misspelled rollout flags rather than silently selecting a protocol."""
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise ValueError(f"{name} must be true or false")


def _text_attr(value: Any, name: str) -> str | None:
    found = getattr(value, name, None) if value is not None else None
    return found if isinstance(found, str) and found else None


def configured_profile(auth: Any = None) -> ProtocolProfile:
    """Select coherent settings for the current selected account, without probing."""
    state = current_state()
    if auth is None and state is not None:
        auth = state.auth_manager
    region = _text_attr(auth, "region") or _text_attr(auth, "_region") or os.getenv("KIRO_REGION", "us-east-1")
    return select_protocol_profile(
        os.getenv("KIRO_PROTOCOL_PROFILE", "legacy"),
        generation_protocol=os.getenv("KIRO_GENERATION_PROTOCOL", "generate"),
        native_system_prompt=_flag("KIRO_NATIVE_SYSTEM_PROMPT", False),
        data_collection_opt_out=not _flag("KIRO_CONTENT_COLLECTION_ENABLED", False),
        region=region,
        runtime_endpoint=os.getenv("KIRO_RUNTIME_ENDPOINT") or None,
        management_endpoint=os.getenv("KIRO_MANAGEMENT_ENDPOINT") or None,
        legacy_q_endpoint=os.getenv("KIRO_LEGACY_Q_ENDPOINT") or None,
    )


def validate_protocol_settings() -> None:
    """Validate startup configuration without making a network call."""
    configured_profile()
    application_version()


def auth_method(auth: Any) -> str | None:
    """Read an explicit credential mechanism, not a guessed token/provider label."""
    method = _text_attr(auth, "auth_method") or _text_attr(auth, "_auth_method")
    if method:
        return method
    value = getattr(auth, "auth_type", None)
    if not isinstance(value, str):
        value = getattr(value, "value", None)
    return value if isinstance(value, str) else None


def identify_operation(url: str, payload: dict | None = None, explicit: str | None = None) -> str | None:
    """Classify legacy call sites before rewriting to RPC root paths."""
    if explicit is not None:
        if explicit not in GENERATION_OPERATIONS | CONTROL_OPERATIONS:
            raise ValueError("Unknown Kiro operation")
        return explicit
    path = urlsplit(url).path.rstrip("/")
    for name in ("generateAssistantResponse", "ListAvailableModels", "GetUsageLimits", "ListAvailableProfiles", "mcp"):
        if path.endswith("/" + name):
            return name
    if path.endswith("/v1/responses"):
        return "responses"
    if isinstance(payload, dict) and "conversationState" in payload:
        return "generateAssistantResponse"
    return None


@dataclass(frozen=True)
class PreparedOperation:
    """A complete wire request plan, excluding correlation/attempt headers."""

    operation: str | None
    profile: ProtocolProfile
    method: str
    url: str
    payload: dict | None
    params: dict | None
    headers: dict[str, str]

    @property
    def is_inference(self) -> bool:
        return self.operation in GENERATION_OPERATIONS

    @property
    def is_responses(self) -> bool:
        return self.operation == "responses"


def require_credential_binding(auth: Any) -> None:
    """Prevent a payload prepared for an old credential epoch from reaching a new one."""
    from extensions.upstream_account import credential_generation
    from fastapi import HTTPException

    state = current_state()
    if state is not None and state.auth_manager is auth and state.auth_generation is not None:
        if credential_generation(auth) != state.auth_generation:
            state.upstream_status, state.upstream_reason = 409, None
            raise HTTPException(status_code=409, detail="Kiro credentials changed while preparing this request; retry with the intended account. Native history from another credential context cannot be reused.")


def prepare_operation(
    auth: Any, token: str, method: str, url: str, payload: dict | None = None,
    params: dict | None = None, *, operation: str | None = None,
    legacy_target: Any = _UNSET, profile_override: ProtocolProfile | None = None,
) -> PreparedOperation:
    """Serialize one operation with consistent body, headers and endpoint.

    The original URL is honored in legacy mode unless an explicit origin override
    was configured. CLI mode follows the actual JSON-RPC serializer (POST /,
    modeled members in the body); Responses follows the explicit raw REST path.
    """
    profile = profile_override or configured_profile(auth)
    kind = identify_operation(url, payload, operation)
    arn = _text_attr(auth, "profile_arn") or _text_attr(auth, "_profile_arn")
    if kind is None:
        # Unknown library operations keep their address, but never inherit a
        # GenerateAssistantResponse target or agent-mode header.
        headers = profile.build_headers(app_version=application_version(), token=token,
                                        auth_method=auth_method(auth))
        headers.pop("x-amz-target", None)
        headers.pop("x-amzn-kiro-origin", None)
        return PreparedOperation(None, profile, method, url, payload, params, headers)
    if kind in GENERATION_OPERATIONS or kind == "mcp":
        require_credential_binding(auth)
    if kind in GENERATION_OPERATIONS:
        kind = "responses" if profile.generation_protocol == "responses" else "generateAssistantResponse"
    spec = profile.resolve_operation(kind)
    headers = profile.build_headers(app_version=application_version(), token=token,
                                    auth_method=auth_method(auth), operation=kind, profile_arn=arn)
    body = dict(payload) if payload is not None else None
    query = dict(params) if params is not None else None
    selected_url = spec.url
    if kind in GENERATION_OPERATIONS:
        if not isinstance(body, dict):
            raise ValueError("An inference operation requires a command body")
        if kind == "responses":
            body = build_responses_payload(body)
        elif profile.name == "legacy":
            mode = body.pop("agentMode", "vibe")
            headers["x-amzn-kiro-agent-mode"] = mode
        # CLI Generate serializes agentMode in JSON; its httpHeader annotation
        # is not consumed by the selected AwsJson1_0Protocol.
        query = None
        if profile.name == "legacy" and kind == "generateAssistantResponse" and not os.getenv("KIRO_RUNTIME_ENDPOINT"):
            selected_url = url
            if legacy_target is not _UNSET:
                if legacy_target is None:
                    headers.pop("x-amz-target", None)
                else:
                    headers["x-amz-target"] = legacy_target
    elif kind == "ListAvailableModels":
        values = dict(query or body or {})
        values["origin"] = profile.origin
        if arn:
            values["profileArn"] = arn
        body, query = (values, None) if profile.name == "cli" else (None, values)
    elif kind == "mcp":
        body = dict(body or {})
        if profile.name == "cli" and arn:
            body["profileArn"] = arn
        query = None
    else:
        body = dict(body or query or {})
        query = None
        if kind == "GetUsageLimits":
            body["origin"] = profile.origin
            if arn:
                body["profileArn"] = arn
    if kind in CONTROL_OPERATIONS and profile.name == "legacy" and not os.getenv("KIRO_LEGACY_Q_ENDPOINT"):
        selected_url = url
    # User-provided legacy addresses still require an HTTPS origin without userinfo.
    parsed = urlsplit(selected_url)
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("Kiro endpoints must be HTTPS without credentials or fragments")
    return PreparedOperation(kind, profile, spec.method, selected_url, body, query, headers)

async def request_operation(
    auth: Any, operation: str, *, payload: dict | None = None, params: dict | None = None,
    client: Any = None,
) -> Any:
    """Execute a known control operation through the shared routing/retry policy."""
    from kiro.http_client import KiroHttpClient
    from extensions.upstream_retry import request_with_retry

    profile = configured_profile(auth)
    q_host = _text_attr(auth, "q_host") or profile.legacy_q_endpoint
    if q_host.startswith("https://runtime."):
        q_host = profile.legacy_q_endpoint
    if operation == "ListAvailableModels":
        legacy_url, method = q_host.rstrip("/") + "/ListAvailableModels", "GET"
    elif operation == "mcp":
        legacy_url, method = q_host.rstrip("/") + "/mcp", "POST"
    elif operation in ("GetUsageLimits", "ListAvailableProfiles"):
        legacy_url, method = q_host.rstrip("/") + "/", "POST"
    else:
        raise ValueError("request_operation expects a known control-plane operation")
    owner = KiroHttpClient(auth, shared_client=client)
    try:
        return await request_with_retry(owner, method, legacy_url, payload, params, operation=operation)
    finally:
        await owner.close()
