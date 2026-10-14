"""Bounded Kiro transport recovery without silently changing client intent.

All inference sends share a middleware request budget. Authentication recovery
requires an actual token error, abandoned responses are drained and closed, and
429 retries honor Kiro/HTTP hints without assuming independent endpoint quotas.
Explicit legacy additional-field fallback is opt-in and scoped with a TTL.
"""

import asyncio
import uuid
from collections import OrderedDict
import json
import math
import os
import random
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException
from loguru import logger

from extensions.request_context import current_state
from extensions.protocol_runtime import configured_profile, identify_operation, prepare_operation, GENERATION_OPERATIONS, CONTROL_OPERATIONS
from extensions.responses_transport import adapt_responses_stream
from extensions.retry_policy import RetryBudget, is_expired_auth, refresh_if_current, retry_after_seconds


# ==================================================================================================
# Settings
# ==================================================================================================

def _env_float(name: str, default: str) -> float:
    try:
        value = float(os.getenv(name, default))
        if math.isfinite(value) and value >= 0:
            return value
    except ValueError:
        pass
    logger.warning(f"Invalid {name}; using {default}")
    return float(default)


# Upper bound for exponential backoff on 5xx/408/network errors (seconds)
MAX_RETRY_DELAY: float = _env_float("MAX_RETRY_DELAY", "5")

# 429 backoff: THROTTLE_BASE_DELAY + attempt * THROTTLE_STEP_DELAY, capped, plus jitter.
# Retry-After from upstream (when present) takes precedence, capped at THROTTLE_MAX_DELAY.
THROTTLE_BASE_DELAY: float = _env_float("THROTTLE_BASE_DELAY", "2")
THROTTLE_STEP_DELAY: float = _env_float("THROTTLE_STEP_DELAY", "1")
THROTTLE_MAX_DELAY: float = _env_float("THROTTLE_MAX_DELAY", "8")

# Explicit compatibility endpoints, tried only for an unsupported operation.
#   runtime       -> runtime.{region}.kiro.dev (default, the only one enabled by default)
#   ide           -> q.{region}.amazonaws.com
#   codewhisperer -> codewhisperer.us-east-1.amazonaws.com (q.{region} elsewhere) + x-amz-target
#   amazonq       -> q.{region}.amazonaws.com + x-amz-target SendMessage
KIRO_ENDPOINTS: List[str] = [
    e.strip().lower() for e in os.getenv("KIRO_ENDPOINTS", "runtime").split(",") if e.strip()
]

# How long an endpoint is skipped after it returned 429 (seconds)
ENDPOINT_THROTTLE_SECONDS: float = _env_float("ENDPOINT_THROTTLE_SECONDS", "30")


# ==================================================================================================
# Endpoints (kiro/endpoints.py in the fork)
# ==================================================================================================

GENERATE_PATH = "/generateAssistantResponse"

# Target upstream always sends; kept for the requested URL to avoid behaviour change.
CODEWHISPERER_TARGET = "AmazonCodeWhispererStreamingService.GenerateAssistantResponse"
AMAZONQ_TARGET = "AmazonQDeveloperStreamingService.SendMessage"

KNOWN_ENDPOINTS = ("runtime", "ide", "codewhisperer", "amazonq")


@dataclass(frozen=True)
class Endpoint:
    """
    A concrete upstream endpoint.

    Attributes:
        name: Endpoint name (requested / runtime / ide / codewhisperer / amazonq)
        base_url: Scheme + host, e.g. "https://runtime.us-east-1.kiro.dev"
        amz_target: Value for the x-amz-target header, or None to omit it
    """
    name: str
    base_url: str
    amz_target: Optional[str]

    @property
    def url(self) -> str:
        """Full generateAssistantResponse URL."""
        return f"{self.base_url}{GENERATE_PATH}"


def build_endpoint(name: str, region: str) -> Endpoint:
    """
    Builds an endpoint for the given name and region.

    Raises:
        ValueError: If name is unknown
    """
    region = region.lower()
    if name == "runtime":
        return Endpoint(name, f"https://runtime.{region}.kiro.dev", CODEWHISPERER_TARGET)
    if name == "ide":
        return Endpoint(name, f"https://q.{region}.amazonaws.com", None)
    if name == "codewhisperer":
        # codewhisperer.* host only exists in us-east-1
        host = (
            "codewhisperer.us-east-1.amazonaws.com"
            if region == "us-east-1"
            else f"q.{region}.amazonaws.com"
        )
        return Endpoint(name, f"https://{host}", CODEWHISPERER_TARGET)
    if name == "amazonq":
        return Endpoint(name, f"https://q.{region}.amazonaws.com", AMAZONQ_TARGET)
    raise ValueError(f"Unknown Kiro endpoint: {name}")


def region_from_url(url: str) -> Optional[str]:
    """Region of a runtime/q/codewhisperer generateAssistantResponse URL, else None."""
    if not url.endswith(GENERATE_PATH):
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0]
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] in ("runtime", "q", "codewhisperer"):
        return parts[1]
    return None


def _host(base_url: str) -> str:
    return base_url.split("://", 1)[-1].split("/", 1)[0].lower()


def _cloud_can_tunnel(base_url: str) -> bool:
    """False when KiroaaS Cloud is on and would not forward this host."""
    if (os.getenv("KIROAAS_CLOUD_ENABLED") or "").lower() != "true":
        return True
    from extensions.cloud_connector import _is_target_host

    return _is_target_host(_host(base_url))


def endpoint_candidates(url: str, has_profile_arn: bool = True) -> List[Endpoint]:
    """
    Ordered endpoints to try for a request URL.

    The first entry is always the requested URL with upstream's headers, so the
    default configuration (and every non-chat URL) behaves exactly like upstream.

    Args:
        url: URL the caller asked for
        has_profile_arn: Whether the account carries a profileArn (runtime needs one)

    Returns:
        List of endpoints (at least one)
    """
    base = url[: -len(GENERATE_PATH)] if url.endswith(GENERATE_PATH) else url
    requested = Endpoint("requested", base, CODEWHISPERER_TARGET)
    region = region_from_url(url)
    if region is None:
        return [requested]

    endpoints = [requested]
    seen = {(_host(base), CODEWHISPERER_TARGET)}
    for name in KIRO_ENDPOINTS:
        if name not in KNOWN_ENDPOINTS:
            continue
        if name == "runtime" and not has_profile_arn:
            continue  # runtime.kiro.dev 400s without a profileArn
        ep = build_endpoint(name, region)
        key = (_host(ep.base_url), ep.amz_target)
        if key in seen or not _cloud_can_tunnel(ep.base_url):
            continue
        seen.add(key)
        endpoints.append(ep)
    return endpoints


class EndpointThrottleRegistry:
    """Remembers which (account, endpoint) buckets recently returned 429. Entries expire on their own."""

    def __init__(self) -> None:
        self._until: Dict[Tuple[int, str], float] = {}

    def throttle(self, account_key: int, endpoint_name: str, seconds: Optional[float] = None) -> None:
        seconds = ENDPOINT_THROTTLE_SECONDS if seconds is None else seconds
        self._until[(account_key, endpoint_name)] = time.monotonic() + seconds
        logger.debug(f"Endpoint '{endpoint_name}' throttled for {seconds:.0f}s")

    def is_throttled(self, account_key: int, endpoint_name: str) -> bool:
        until = self._until.get((account_key, endpoint_name))
        return until is not None and until > time.monotonic()

    def order(self, account_key: int, endpoints: List[Endpoint]) -> List[Endpoint]:
        """Non-throttled endpoints first (stable otherwise)."""
        free = [e for e in endpoints if not self.is_throttled(account_key, e.name)]
        busy = [e for e in endpoints if self.is_throttled(account_key, e.name)]
        return free + busy

    def clear(self) -> None:
        self._until.clear()


endpoint_registry = EndpointThrottleRegistry()


# ==================================================================================================
# Backoff and payload helpers (kiro/http_client.py in the fork)
# ==================================================================================================

def backoff_delay(attempt: int) -> float:
    """Exponential backoff with +/-25% jitter for 5xx/408/network errors."""
    from kiro.config import BASE_RETRY_DELAY

    base = min(BASE_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
    return max(0.0, base * random.uniform(0.75, 1.25))


def throttle_delay(attempt: int, retry_after: Optional[str] = None) -> float:
    """Backoff for 429, accepting numeric seconds and HTTP-date retry hints."""
    hint = retry_after_seconds({"retry-after": retry_after}) if retry_after is not None else None
    if hint is not None:
        return hint
    base = min(THROTTLE_BASE_DELAY + attempt * THROTTLE_STEP_DELAY, THROTTLE_MAX_DELAY)
    return min(max(0.0, base + random.uniform(0.0, 1.5)), THROTTLE_MAX_DELAY)


# Optional compatibility decisions must never leak between accounts/endpoints.
_ADDITIONAL_FIELDS_REJECTED: OrderedDict = OrderedDict()
ADDITIONAL_FIELDS_KEY = "additionalModelRequestFields"
_REJECTION_CACHE_TTL = 300.0
_REJECTION_CACHE_LIMIT = 256


def _allow_field_fallback() -> bool:
    """Explicitly opt into dropping unsupported additional fields (off by default)."""
    return os.getenv("KIRO_ALLOW_ADDITIONAL_FIELDS_FALLBACK", "false").lower() in ("true", "1", "yes")


def _payload_model_id(json_data: Optional[dict]) -> Optional[str]:
    """The Kiro modelId from a generateAssistantResponse payload, if any."""
    try:
        return json_data["conversationState"]["currentMessage"]["userInputMessage"]["modelId"]
    except (KeyError, TypeError):
        return None


def strip_rejected_additional_fields(
    json_data: Optional[dict], scope: Optional[Tuple[str, str]] = None
) -> Optional[dict]:
    """Apply only explicit, unexpired account/endpoint-scoped compatibility choices."""
    if not _allow_field_fallback() or scope is None or not isinstance(json_data, dict):
        return json_data
    now = time.monotonic()
    for key, until in list(_ADDITIONAL_FIELDS_REJECTED.items()):
        if until <= now:
            _ADDITIONAL_FIELDS_REJECTED.pop(key, None)
    key = (*scope, _payload_model_id(json_data))
    if key in _ADDITIONAL_FIELDS_REJECTED:
        logger.warning("Applying explicitly enabled unsupported-model-field fallback")
        return {k: v for k, v in json_data.items() if k != ADDITIONAL_FIELDS_KEY}
    return json_data


def agent_mode_for_payload(json_data: Optional[dict]) -> str:
    """Read the command's independent agent mode; task type and tools do not imply it."""
    if isinstance(json_data, dict):
        mode = json_data.get("agentMode")
        if isinstance(mode, str) and mode.strip():
            return mode
    return "vibe"


def build_headers(
    auth_manager: Any, token: str, endpoint: Endpoint, attempt: int,
    agent_mode: str, *, invocation_id: Optional[str] = None, max_attempts: int = 3,
) -> dict:
    """Build coherent correlation/attempt headers for one physical send.

    Args:
        auth_manager: Account authentication manager.
        token: Current access token, never logged.
        endpoint: Explicit selected transport endpoint.
        attempt: Physical attempt within the logical request.
        agent_mode: Independent execution mode, not the task type.
        invocation_id: Stable logical request ID.
        max_attempts: The actual shared send budget.
    """
    profile = configured_profile(auth_manager)
    from kiro.client_identity import application_version
    from extensions.protocol_runtime import auth_method
    headers = profile.build_headers(app_version=application_version(), token=token, auth_method=auth_method(auth_manager))
    if profile.name == "legacy" and profile.generation_protocol == "generate":
        if endpoint.amz_target:
            headers["x-amz-target"] = endpoint.amz_target
        else:
            headers.pop("x-amz-target", None)
        headers["x-amzn-kiro-agent-mode"] = agent_mode
    headers["amz-sdk-invocation-id"] = invocation_id or str(uuid.uuid4())
    headers["amz-sdk-request"] = f"attempt={attempt}; max={max_attempts}"
    headers["x-kiro-attempt"] = f"{attempt};max={max_attempts}"
    return headers


def _record_upstream_status(status_code: int) -> None:
    """Records the status the caller is about to see; clears any earlier reason.

    The route only re-reads the reason (via enhance_kiro_error) when the error
    body is JSON, so a reason left over from a previous account in the failover
    loop would otherwise be paired with this unrelated status.
    """
    state = current_state()
    if state is not None:
        state.upstream_status = status_code
        state.upstream_reason = None


# ==================================================================================================
# request_with_retry
# ==================================================================================================

async def _read_error(response: httpx.Response, budget: RetryBudget) -> bytes:
    """Buffer an error for classification and release its connection on all paths."""
    try:
        return await budget.wait(response.aread())
    finally:
        await response.aclose()


def _compatibility_scope(auth: Any, endpoint: Endpoint) -> Tuple[str, str]:
    """Give an auth object a non-reusable cache namespace, including wire dialect."""
    from extensions.upstream_account import credential_generation
    namespace = getattr(auth, "_kiro_compatibility_namespace", None)
    if not isinstance(namespace, str):
        namespace = str(uuid.uuid4())
        setattr(auth, "_kiro_compatibility_namespace", namespace)
    return namespace + ":" + (credential_generation(auth) or ""), endpoint.base_url + "|" + (endpoint.amz_target or "")


def _remember_field_rejection(scope: Tuple[str, str], payload: dict) -> None:
    """Bound the opt-in compatibility cache and isolate endpoint/account decisions."""
    key = (*scope, _payload_model_id(payload))
    _ADDITIONAL_FIELDS_REJECTED[key] = time.monotonic() + _REJECTION_CACHE_TTL
    _ADDITIONAL_FIELDS_REJECTED.move_to_end(key)
    while len(_ADDITIONAL_FIELDS_REJECTED) > _REJECTION_CACHE_LIMIT:
        _ADDITIONAL_FIELDS_REJECTED.popitem(last=False)


def _unsupported_additional_fields(body: bytes) -> bool:
    """Recognize rejection of the field itself, not a bad effort/token-limit value."""
    text = body.lower()
    return any(marker in text for marker in (
        b"additionalmodelrequestfields is not supported",
        b"additionalmodelrequestfields are not supported",
        b"unsupported field: additionalmodelrequestfields",
    ))


async def request_with_retry(
    self: Any, method: str, url: str, json_data: Optional[dict] = None,
    params: Optional[dict] = None, stream: bool = False, operation: Optional[str] = None,
    _paginate: bool = True, _profile_override: Any = None, _deadline: Optional[float] = None,
) -> httpx.Response:
    """Send with bounded, error-aware recovery and no implicit content modification.

    A middleware budget spans nested retries/account failover. Standalone calls
    receive a local budget. Successful streams are owned by the caller; every
    error response is buffered and closed before being returned or retried.
    """
    from kiro.config import MAX_RETRIES, FIRST_TOKEN_MAX_RETRIES
    import kiro.http_client as http_client_module

    try:
        kind = identify_operation(url, json_data, operation)
        request_state = current_state()
        profile = _profile_override or (request_state.protocol_profile if (kind in GENERATION_OPERATIONS and request_state is not None and request_state.protocol_profile is not None) else configured_profile(self.auth_manager))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    inference = kind in GENERATION_OPERATIONS
    local_limit = max(1, FIRST_TOKEN_MAX_RETRIES if stream and inference else MAX_RETRIES)
    state = current_state()
    budget = state.retry_budget if state is not None and inference else None
    if budget is None:
        budget = RetryBudget.from_environment(local_limit)
        if state is not None and state.retry_budget is not None:
            budget.deadline = min(budget.deadline, state.retry_budget.deadline)
    if _deadline is not None:
        budget.deadline = min(budget.deadline, _deadline)
    client = await self._get_client(stream=stream)
    has_profile = bool(getattr(self.auth_manager, "_profile_arn", None) or getattr(self.auth_manager, "profile_arn", None))
    endpoints = endpoint_candidates(url, has_profile_arn=has_profile)
    if profile.name != "legacy" or profile.generation_protocol != "generate" or not inference:
        endpoints = endpoints[:1]
    control_fallback_used = False
    endpoint_index = 0
    account_key = id(self.auth_manager)
    mode = agent_mode_for_payload(json_data)
    last_response: Optional[httpx.Response] = None
    last_error_info = None
    delay = 0.0

    for local_attempt in range(local_limit):
        if not budget.can_retry(delay):
            if last_response is not None:
                return last_response
            if budget.last_http_error is not None:
                status, saved_headers, saved_body = budget.last_http_error
                _record_upstream_status(status)
                return httpx.Response(status, headers=saved_headers, content=saved_body)
            raise HTTPException(status_code=504, detail="Kiro request cannot be replayed: output started or shared budget exhausted.")
        try:
            if delay:
                await budget.wait(asyncio.sleep(delay))
            endpoint = endpoints[endpoint_index]
            request_url = url if endpoint.name == "requested" else endpoint.url
            token = await budget.wait(self.auth_manager.get_access_token())
            payload = json_data
            try:
                prepared = prepare_operation(
                    self.auth_manager, token, method, request_url, payload, params,
                    operation=kind, legacy_target=endpoint.amz_target, profile_override=profile,
                )
                actual_endpoint = Endpoint(prepared.operation or "unknown", prepared.url, prepared.headers.get("x-amz-target"))
                scope = _compatibility_scope(self.auth_manager, actual_endpoint)
                payload = strip_rejected_additional_fields(json_data, scope)
                if payload is not json_data:
                    prepared = prepare_operation(
                        self.auth_manager, token, method, request_url, payload, params,
                        operation=kind, legacy_target=endpoint.amz_target, profile_override=profile,
                    )
                from extensions.cloud_connector import require_cloud_route
                require_cloud_route(prepared.url)
                content = None if prepared.payload is None else json.dumps(
                    prepared.payload, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            # Validation/translation does not spend a physical-send attempt.
            attempt = budget.reserve_attempt()
            headers = prepared.headers
            headers["amz-sdk-invocation-id"] = budget.invocation_id
            headers["amz-sdk-request"] = f"attempt={attempt}; max={budget.max_attempts}"
            headers["x-kiro-attempt"] = f"{attempt};max={budget.max_attempts}"
            kwargs: Dict[str, Any] = {"headers": headers, "extensions": {"kiro_upstream": True}}
            if content is not None:
                kwargs["content"] = content
            if prepared.params is not None:
                kwargs["params"] = prepared.params
            if stream:
                headers["Connection"] = "close"
                request = client.build_request(prepared.method, prepared.url, **kwargs)
                response = await budget.wait(client.send(request, stream=True, follow_redirects=False))
            else:
                response = await budget.wait(client.request(prepared.method, prepared.url, follow_redirects=False, **kwargs))
            if response.status_code == 200:
                if isinstance(getattr(response, "extensions", None), dict):
                    response.extensions["kiro_request_deadline"] = budget.deadline
                    stream_limit = _env_float("KIRO_STREAM_TOTAL_TIMEOUT", "0")
                    if stream_limit > 0:
                        response.extensions["kiro_stream_deadline"] = time.monotonic() + stream_limit
                budget.last_http_error = None
                if state is not None:
                    state.upstream_status = None
                    state.upstream_reason = None
                if kind == "ListAvailableModels" and _paginate:
                    response = await _collect_model_pages(self, response, method, url, json_data, params, profile, budget.deadline)
                return adapt_responses_stream(response) if prepared.is_responses else response

            _record_upstream_status(response.status_code)
            try:
                body = await _read_error(response, budget)
            except (httpx.RequestError, httpx.StreamError, asyncio.TimeoutError):
                # Keep an observed HTTP error even if its diagnostic body was lost.
                body = b'{"message":"Kiro returned an error; its response body could not be read."}'
                response = httpx.Response(response.status_code, headers=response.headers, content=body)
                budget.last_http_error = (response.status_code, dict(response.headers), body)
                return response
            last_response = response
            budget.last_http_error = (response.status_code, dict(response.headers), body)
            if local_attempt + 1 >= local_limit or not budget.can_retry():
                return response

            if is_expired_auth(response.status_code, body):
                if account_key in budget.refreshed_accounts:
                    return response
                budget.refreshed_accounts.add(account_key)
                await budget.wait(refresh_if_current(self.auth_manager, token))
                delay = 0.0
                continue
            if response.status_code == 429:
                hint = retry_after_seconds(response.headers, body)
                delay = hint if hint is not None else throttle_delay(local_attempt)
                # No rotation: the server has not promised independent quotas.
                continue
            if response.status_code == 408 or 500 <= response.status_code < 600:
                hint = retry_after_seconds(response.headers, body)
                delay = hint if hint is not None else backoff_delay(local_attempt)
                continue
            if (
                response.status_code in (400, 404) and b"unknownoperation" in body.lower()
                and kind in CONTROL_OPERATIONS and profile.name == "cli" and not control_fallback_used
                and os.getenv("KIRO_CONTROL_PLANE_FALLBACK", "false").lower() in ("true", "1", "yes")
            ):
                profile = replace(profile, name="legacy", generation_protocol="generate")
                control_fallback_used = True
                delay = 0.0
                continue
            if (
                response.status_code in (400, 404)
                and b"unknownoperation" in body.lower()
                and endpoint_index + 1 < len(endpoints)
            ):
                endpoint_index += 1
                delay = 0.0
                continue
            if (
                response.status_code == 400 and _allow_field_fallback()
                and isinstance(payload, dict) and ADDITIONAL_FIELDS_KEY in payload
                and _unsupported_additional_fields(body)
            ):
                _remember_field_rejection(scope, payload)
                json_data = {k: v for k, v in payload.items() if k != ADDITIONAL_FIELDS_KEY}
                logger.warning("Retrying without additional model fields under explicit compatibility opt-in")
                delay = 0.0
                continue
            return response
        except ValueError as error:
            from extensions.protocol_runtime import require_credential_binding
            require_credential_binding(self.auth_manager)
            raise HTTPException(status_code=400, detail=str(error)) from error
        except (httpx.TimeoutException, httpx.RequestError) as error:
            last_error_info = http_client_module.classify_network_error(error)
            if not last_error_info.is_retryable:
                break
            delay = backoff_delay(local_attempt)
        except asyncio.TimeoutError:
            if last_response is not None:
                return last_response
            raise HTTPException(status_code=504, detail="Kiro request exceeded its total elapsed-time budget.") from None

    if last_response is not None:
        return last_response
    if last_error_info is not None:
        raise HTTPException(status_code=last_error_info.suggested_http_code, detail=last_error_info.user_message)
    raise HTTPException(status_code=504, detail="Kiro request exhausted its total inference attempt budget.")



async def _collect_model_pages(
    owner: Any, first: httpx.Response, method: str, url: str, payload: Optional[dict],
    params: Optional[dict], profile: Any, deadline: float,
) -> httpx.Response:
    """Collect a bounded complete discovery snapshot, never silently a first page."""
    try:
        data = first.json()
    except ValueError as error:
        raise HTTPException(502, "Kiro model discovery returned invalid JSON") from error
    if not isinstance(data, dict) or not data.get("nextToken"):
        return first
    models = data.get("models")
    if not isinstance(models, list):
        raise HTTPException(502, "Kiro model discovery returned an invalid models list")
    models = list(models)
    cursor, seen = data.get("nextToken"), set()
    for _ in range(9):
        if not isinstance(cursor, str) or cursor in seen:
            raise HTTPException(502, "Kiro model discovery returned an invalid/repeated cursor")
        seen.add(cursor)
        query = {**(params or {}), "nextToken": cursor}
        page = await request_with_retry(owner, method, url, payload, query, operation="ListAvailableModels",
                                        _paginate=False, _profile_override=profile, _deadline=deadline)
        if page.status_code != 200:
            return page
        try:
            parsed = page.json()
        except ValueError as error:
            raise HTTPException(502, "Kiro model discovery returned invalid JSON") from error
        if not isinstance(parsed, dict) or not isinstance(parsed.get("models"), list):
            raise HTTPException(502, "Kiro model discovery returned an invalid page")
        models.extend(parsed["models"])
        cursor = parsed.get("nextToken")
        if not cursor:
            combined = {**data, "models": models}
            combined.pop("nextToken", None)
            return httpx.Response(200, json=combined, headers={key: value for key, value in first.headers.items()
                                  if key.lower() not in ("content-length", "content-encoding")})
    raise HTTPException(502, "Kiro model discovery exceeded its ten-page safety limit")

_installed = False
_originals: Dict[str, Any] = {}


def install_upstream_retry() -> None:
    """Replace KiroHttpClient.request_with_retry with the hardened version."""
    global _installed
    if _installed:
        return

    from kiro.http_client import KiroHttpClient

    _originals["request_with_retry"] = KiroHttpClient.request_with_retry
    KiroHttpClient.request_with_retry = request_with_retry

    _installed = True
    extra = [e.name for e in endpoint_candidates("https://runtime.us-east-1.kiro.dev" + GENERATE_PATH)[1:]]
    logger.info(
        "Installed upstream retry extension"
        + (f" (explicit compatibility alternatives: {', '.join(extra)})" if extra else "")
    )


def uninstall_upstream_retry() -> None:
    """Restore the patched method. Intended for unit tests."""
    global _installed
    if _originals:
        from kiro.http_client import KiroHttpClient

        KiroHttpClient.request_with_retry = _originals["request_with_retry"]

    _originals.clear()
    _ADDITIONAL_FIELDS_REJECTED.clear()
    endpoint_registry.clear()
    _ADDITIONAL_FIELDS_REJECTED.clear()
    _installed = False
