"""Pure, bounded upstream protocol selection; no I/O, hooks, or fallback.

Configuration is explicit: ``select_protocol_profile()`` selects legacy/generate,
with native ``systemPrompt`` disabled and content collection opted out. A caller
must pass its real ``app_version`` and an already obtained bearer token to build
headers. Profiles contain no credentials. Origin is a wire-compatibility value,
not a claim to be the IDE/CLI; both user-agent headers identify KiroaaS.

Static evidence: CLI 2.29.1 ``acp-server.readable.js`` (one-based LF lines, read
with split('\\n')):
* 88965-88975 and 123115-123127: TokenType mappings; 123038-123049: opt-out.
* 126376-126392: runtime/management hosts; 126536-126615: user-agent attribution.
* 184664-184671, 184423: native systemPrompt schema, NOT proof of live support.
* 363511-363534: origin values; 362734-362767: raw Responses path and headers.
* 528108-528154: KiroRuntimeClient selection and auth/opt-out middleware.
* 107165-107205, 119583-119591, 182435-182443: AWS JSON-RPC POST / and targets.
* 122219-122225, 185082-185091: management/runtime JSON-RPC service targets.
* 184984-185028, 122116-122146: REST-style schema annotations are NOT the
  selected JSON-RPC wire paths. In particular, CLI management is not a GET to
  /List-Available-Models or /Get-Usage-Limits. CLI MCP is runtime InvokeMCP.

Legacy routes preserve this repository's utils.py, account_manager.py,
extensions/routes_account.py and control_plane_host.py contracts: runtime
/generateAssistantResponse, q /ListAvailableModels, q root GetUsageLimits RPC,
and q /mcp. They are compatibility policy, not claims about the new CLI.

Remaining uncertainties/boundaries:
* No live requests verified account/region entitlement, server acceptance of
  KiroaaS attribution, RPC targets, Responses, MCP, or native systemPrompt.
  Responses is experimental and explicitly selected; the native flag only
  instructs a parent builder, without altering any payload here.
* Region validation is syntactic, not an assertion of service availability.
* Endpoint overrides are HTTPS ORIGINS only, not paths/queries or credentials.
  Validation is NOT an allowlist, DNS/SSRF check, or permission to forward via
  Cloud. The caller must retain its independent Cloud/destination policy.
* IdC is the bundle's SSO key. SSO, SSO_OIDC and aws_sso_oidc are explicit
  adapter aliases for that same flow, not additional bundle observations.
  Unknown/social methods receive no invented TokenType. All tokens, including
  API keys, remain bearer credentials; token acquisition/refresh is external.
* Privacy opt-out is applied to every operation as local policy (the bundle
  does not establish that every service consumes it). Opt-in omits the header
  except on Responses, whose raw implementation explicitly sends 'false'.
* The parent owns body/query serialization, transport, retries, redirects,
  response decoding, endpoint authorization, and any SDK invocation metadata.
  A downstream non-streaming response does not change upstream operation rules.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, cast
from urllib.parse import urlsplit

__all__ = [
    "OperationSpec",
    "ProtocolProfile",
    "select_protocol_profile",
    "token_type_for_auth_method",
]

_JSON = "application/json"
_AWS_JSON = "application/x-amz-json-1.0"
_LEGACY_STREAMING = "AmazonCodeWhispererStreamingService.GenerateAssistantResponse"
_LEGACY_USAGE = "com.amazon.aws.codewhisperer.runtime.AmazonCodeWhispererService.GetUsageLimits"
_RUNTIME_TARGET = "KiroRuntimeService"
_MANAGEMENT_TARGET = "KiroControlPlaneBearerService"
_REGION = re.compile(r"(?:[a-z]{2}|eusc)(?:-[a-z]{2,12}){1,3}-[1-9][0-9]?")
_AUTHORITY = re.compile(r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]{1,5})?")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")
_AUTH_METHOD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_TOKEN_TYPES = MappingProxyType({
    "IdC": "SSO_OIDC",
    "SSO": "SSO_OIDC",
    "SSO_OIDC": "SSO_OIDC",
    "aws_sso_oidc": "SSO_OIDC",
    "external_idp": "EXTERNAL_IDP",
    "machine_token": "KIRO_MACHINE_TOKEN",
    "api_key": "API_KEY",
})

OperationName = Literal[
    "generateAssistantResponse", "responses", "ListAvailableModels", "GetUsageLimits", "ListAvailableProfiles", "mcp"
]


def _choice(value: str, choices: tuple[str, ...], field: str) -> None:
    """Validate an exact finite option without reflecting untrusted input.

    Args:
        value: Supplied option, with no coercion or whitespace stripping.
        choices: Supported spellings.
        field: Trusted configuration field name.

    Raises:
        ValueError: The option is not one of the supported strings.
    """
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{field} must be one of: {', '.join(choices)}")


def _header_value(value: str, field: str) -> str:
    """Validate a nonempty visible ASCII header value without leaking it.

    Args:
        value: Caller-supplied token or profile ARN.
        field: Trusted field name for a sanitized error.

    Returns:
        The unchanged input, never a stripped or repaired credential.

    Raises:
        ValueError: The value is empty, non-text, whitespace, or non-ASCII.
    """
    if not isinstance(value, str) or not value or any(not 33 <= ord(c) <= 126 for c in value):
        raise ValueError(f"{field} must be nonempty visible ASCII without whitespace")
    return value


def _endpoint_origin(value: str, field: str) -> str:
    """Validate a credential-free HTTPS origin; this does not authorize it.

    Args:
        value: Explicit endpoint origin, optionally with a port/trailing slash.
        field: Trusted configuration field name.

    Returns:
        Lowercase HTTPS origin without a trailing slash.

    Raises:
        ValueError: Scheme, authority, port, host, or origin syntax is unsafe.
    """
    error = f"{field} must be an HTTPS origin without credentials, path, query, or fragment"
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or any(not 33 <= ord(c) <= 126 for c in value)
        or any(c in value for c in "\\%@?#")
    ):
        raise ValueError(error)
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ValueError(error) from None
    if (
        parts.scheme != "https"
        or _AUTHORITY.fullmatch(parts.netloc) is None
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or parts.netloc.endswith(":")
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError(error)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if (
            len(host) > 253
            or host.split(".")[-1].isdigit()
            or any(_DNS_LABEL.fullmatch(label) is None for label in host.split("."))
        ):
            raise ValueError(error) from None
        authority = host
    else:
        authority = f"[{address.compressed}]" if address.version == 6 else str(address)
    if port is not None:
        authority += f":{port}"
    return f"https://{authority}"


def token_type_for_auth_method(auth_method: str | None) -> str | None:
    """Resolve only evidenced token types and the documented SSO aliases.

    Args:
        auth_method: Explicit, case-sensitive auth method; None means unknown.
            Valid but unrecognized names (including social/desktop) omit it.

    Returns:
        The TokenType header value, or None; credentials are never inspected.

    Raises:
        ValueError: The method is not None or a bounded ASCII identifier.
    """
    if auth_method is None:
        return None
    if not isinstance(auth_method, str) or _AUTH_METHOD.fullmatch(auth_method) is None:
        raise ValueError("auth_method must be None or an ASCII method identifier")
    return _TOKEN_TYPES.get(auth_method)


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Resolved wire contract, not a request or an endpoint authorization.

    Attributes:
        name: Selected finite operation name.
        method: HTTP method; CLI RPC operations use POST even for management.
        url: Complete operation URL, without credentials or query parameters.
        content_type: Operation-specific request body media type.
        amz_target: Exact operation target, or None for path-routed operations.
    """

    name: OperationName
    method: Literal["GET", "POST"]
    url: str
    content_type: str
    amz_target: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtocolProfile:
    """Immutable validated profile; direct construction is also validated.

    Args:
        name: 'legacy' (default) or 'cli'; never inferred from auth or a URL.
        generation_protocol: 'generate' or experimental 'responses'.
        native_system_prompt: Explicit builder capability flag, default False.
        data_collection_opt_out: Explicit privacy policy, default True.
        region: Syntactically valid region, default us-east-1.
        runtime_endpoint: Optional HTTPS origin for generation and CLI MCP.
        management_endpoint: Optional HTTPS origin for CLI management only.
        legacy_q_endpoint: Optional HTTPS origin for legacy management/MCP.

    Raises:
        ValueError: Invalid explicit configuration. Booleans are not coerced.
    """

    name: str = "legacy"
    generation_protocol: str = "generate"
    native_system_prompt: bool = False
    data_collection_opt_out: bool = True
    region: str = "us-east-1"
    runtime_endpoint: str | None = None
    management_endpoint: str | None = None
    legacy_q_endpoint: str | None = None

    def __post_init__(self) -> None:
        """Validate all options and freeze normalized independent origins.

        Raises:
            ValueError: Any option or even an unused override is malformed.
        """
        _choice(self.name, ("legacy", "cli"), "name")
        _choice(self.generation_protocol, ("generate", "responses"), "generation_protocol")
        for field in ("native_system_prompt", "data_collection_opt_out"):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f"{field} must be an explicit bool, not a string or integer")
        if not isinstance(self.region, str) or _REGION.fullmatch(self.region) is None:
            raise ValueError("region must be a lowercase region such as us-east-1")
        defaults = (
            ("runtime_endpoint", f"https://runtime.{self.region}.kiro.dev"),
            ("management_endpoint", f"https://management.{self.region}.kiro.dev"),
            ("legacy_q_endpoint", f"https://q.{self.region}.amazonaws.com"),
        )
        for field, default in defaults:
            value = getattr(self, field)
            normalized = _endpoint_origin(default if value is None else value, field)
            object.__setattr__(self, field, normalized)

    @property
    def origin(self) -> str:
        """Return the body origin (also a header on raw Responses)."""
        return "KIRO_CLI" if self.name == "cli" else "AI_EDITOR"

    @property
    def body_content_type(self) -> str:
        """Return the selected generation body's media type, not its stream type."""
        return _JSON if self.generation_protocol == "responses" else _AWS_JSON

    @property
    def streaming_target(self) -> str | None:
        """Return generation's x-amz-target policy; never reuse it for other ops."""
        if self.generation_protocol == "responses":
            return None
        if self.name == "cli":
            return f"{_RUNTIME_TARGET}.GenerateAssistantResponse"
        return _LEGACY_STREAMING

    def resolve_operation(self, operation: str | None = None) -> OperationSpec:
        """Resolve exactly one wire operation; never discover or try alternatives.

        Args:
            operation: None selects configured generation. Otherwise one of
                generateAssistantResponse, responses, ListAvailableModels,
                GetUsageLimits, or mcp. Explicit generation must match config.

        Returns:
            Immutable URL, method, body content type, and operation target.

        Raises:
            ValueError: Unknown operation or an unselected generation protocol.
        """
        generation = (
            "responses" if self.generation_protocol == "responses"
            else "generateAssistantResponse"
        )
        selected = generation if operation is None else operation
        _choice(
            selected,
            ("generateAssistantResponse", "responses", "ListAvailableModels", "GetUsageLimits", "ListAvailableProfiles", "mcp"),
            "operation",
        )
        if selected in ("generateAssistantResponse", "responses") and selected != generation:
            raise ValueError("operation must match the explicitly selected generation_protocol")
        if selected == "responses":
            return OperationSpec("responses", "POST", f"{self.runtime_endpoint}/v1/responses", _JSON)
        if selected == "generateAssistantResponse":
            path = "/" if self.name == "cli" else "/generateAssistantResponse"
            return OperationSpec(
                "generateAssistantResponse", "POST", f"{self.runtime_endpoint}{path}",
                self.body_content_type, self.streaming_target,
            )
        if selected == "mcp":
            if self.name == "cli":
                return OperationSpec(
                    "mcp", "POST", f"{self.runtime_endpoint}/",
                    _AWS_JSON, f"{_RUNTIME_TARGET}.InvokeMCP",
                )
            return OperationSpec("mcp", "POST", f"{self.legacy_q_endpoint}/mcp", _JSON)
        if self.name == "cli":
            return OperationSpec(
                cast(OperationName, selected), "POST", f"{self.management_endpoint}/",
                _AWS_JSON, f"{_MANAGEMENT_TARGET}.{selected}",
            )
        if selected == "ListAvailableModels":
            return OperationSpec(
                "ListAvailableModels", "GET",
                f"{self.legacy_q_endpoint}/ListAvailableModels", _JSON,
            )
        if selected == "ListAvailableProfiles":
            return OperationSpec("ListAvailableProfiles", "POST", f"{self.legacy_q_endpoint}/", _AWS_JSON, "AmazonCodeWhispererService.ListAvailableProfiles")
        return OperationSpec("GetUsageLimits", "POST", f"{self.legacy_q_endpoint}/", _AWS_JSON, _LEGACY_USAGE)

    def build_headers(
        self, *, app_version: str, token: str, auth_method: str | None = None,
        operation: str | None = None, profile_arn: str | None = None,
    ) -> dict[str, str]:
        """Build fresh headers for an operation, never merge arbitrary extras.

        Args:
            app_version: Actual running KiroaaS version; no invented SDK/IDE UA.
            token: Already obtained upstream bearer credential, never stored.
            auth_method: Explicit method for TokenType, not inferred from token.
            operation: As in resolve_operation; None selects generation.
            profile_arn: Optional Responses profile header only. For other ops
                the parent places this in the body/query, not in headers here.

        Returns:
            New header dictionary. Invocation/retry IDs belong to transport.

        Raises:
            ValueError: Invalid operation, version, token, method, or profile.
        """
        spec = self.resolve_operation(operation)
        if not isinstance(app_version, str) or _VERSION.fullmatch(app_version) is None:
            raise ValueError(
                "app_version must be the real app version as a 1-128 character ASCII version token"
            )
        bearer = _header_value(token, "token")
        token_type = token_type_for_auth_method(auth_method)
        if profile_arn is not None:
            _header_value(profile_arn, "profile_arn")
        user_agent = f"KiroaaS/{app_version}"
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": spec.content_type,
            "User-Agent": user_agent,
            "x-amz-user-agent": user_agent,
        }
        if spec.amz_target is not None:
            headers["x-amz-target"] = spec.amz_target
        if self.data_collection_opt_out:
            headers["x-amzn-codewhisperer-optout"] = "true"
        if token_type is not None:
            headers["TokenType"] = token_type
        if spec.name == "responses":
            headers["x-amzn-kiro-origin"] = self.origin
            headers["x-amzn-codewhisperer-optout"] = (
                "true" if self.data_collection_opt_out else "false"
            )
            if profile_arn is not None:
                headers["x-amzn-kiro-profile"] = profile_arn
        return headers


def select_protocol_profile(
    name: str = "legacy", *, generation_protocol: str = "generate",
    native_system_prompt: bool = False, data_collection_opt_out: bool = True,
    region: str = "us-east-1", runtime_endpoint: str | None = None,
    management_endpoint: str | None = None, legacy_q_endpoint: str | None = None,
) -> ProtocolProfile:
    """Select from explicit configuration only; no environment/file detection.

    Args:
        name: Exact legacy/cli profile name.
        generation_protocol: Exact generate/responses choice.
        native_system_prompt: Explicit opt-in for the parent payload builder.
        data_collection_opt_out: Explicit privacy choice, True by default.
        region: Syntactic region used to derive default origins.
        runtime_endpoint: Optional independent runtime origin override.
        management_endpoint: Optional independent CLI management origin override.
        legacy_q_endpoint: Optional independent legacy q origin override.

    Returns:
        A validated immutable ProtocolProfile with normalized origins.

    Raises:
        ValueError: Any supplied configuration value is malformed.
    """
    return ProtocolProfile(
        name=name, generation_protocol=generation_protocol,
        native_system_prompt=native_system_prompt,
        data_collection_opt_out=data_collection_opt_out, region=region,
        runtime_endpoint=runtime_endpoint, management_endpoint=management_endpoint,
        legacy_q_endpoint=legacy_q_endpoint,
    )
