"""
Kiro upstream connection hardening, ported from the kiro-gateway fork (61d9b68, dc0fe43).

Replaces KiroHttpClient.request_with_retry at runtime (kiro/ stays zero-diff):

- 5xx / 408 / network errors: capped exponential backoff with +/-25% jitter
  (MAX_RETRY_DELAY) instead of uncapped 1s/2s/4s. 408 is now retried.
- 429: linear backoff + jitter (THROTTLE_BASE_DELAY / THROTTLE_STEP_DELAY /
  THROTTLE_MAX_DELAY), honouring Retry-After. No pointless sleep after the
  last attempt.
- Optional endpoint rotation on 429 (KIRO_ENDPOINTS, e.g. "runtime,ide"): each
  endpoint is reported to have its own rate-limit bucket, so a throttled one is
  parked for ENDPOINT_THROTTLE_SECONDS and the next one is tried immediately.
- amz-sdk-request reports the real attempt number; x-amzn-kiro-agent-mode
  follows the payload's agentTaskType (set by kiro_payload_builder).
- When Kiro rejects additionalModelRequestFields with a 400, the field is
  stripped and the request retried once. Only "not supported" is remembered per
  model; a rejected *value* (e.g. an unknown effort) affects that request only.

Differences from the fork, for KiroaaS:
- The URL the route asked for is always the first candidate, sent with the
  exact upstream headers. chat_host_fallback points profile-less accounts at
  q.{region}.amazonaws.com; the fork would have rewritten that to runtime, which
  400s without a profileArn. Rotation targets are only added from KIRO_ENDPOINTS
  (default "runtime" = no rotation), and runtime is skipped for such accounts.
- With KiroaaS Cloud on, endpoints the cloud connector cannot tunnel
  (codewhisperer.*) are skipped so traffic never silently bypasses it.

Also records the last non-200 upstream status in the request state, which the
client_compat extension uses to map errors for Anthropic clients.
"""

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException
from loguru import logger

from extensions.request_context import current_state


# ==================================================================================================
# Settings
# ==================================================================================================

def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        logger.warning(f"Invalid {name}={os.getenv(name)!r}, using {default}")
        return float(default)


# Upper bound for exponential backoff on 5xx/408/network errors (seconds)
MAX_RETRY_DELAY: float = _env_float("MAX_RETRY_DELAY", "5")

# 429 backoff: THROTTLE_BASE_DELAY + attempt * THROTTLE_STEP_DELAY, capped, plus jitter.
# Retry-After from upstream (when present) takes precedence, capped at THROTTLE_MAX_DELAY.
THROTTLE_BASE_DELAY: float = _env_float("THROTTLE_BASE_DELAY", "2")
THROTTLE_STEP_DELAY: float = _env_float("THROTTLE_STEP_DELAY", "1")
THROTTLE_MAX_DELAY: float = _env_float("THROTTLE_MAX_DELAY", "8")

# Kiro upstream endpoints for generateAssistantResponse, tried in order on 429.
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
    """Backoff for 429: linear growth with jitter; honours Retry-After if present."""
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), THROTTLE_MAX_DELAY)
        except ValueError:
            pass
    base = min(THROTTLE_BASE_DELAY + attempt * THROTTLE_STEP_DELAY, THROTTLE_MAX_DELAY)
    return base + random.uniform(0.0, 1.5)


# Models for which Kiro rejected additionalModelRequestFields (learned at runtime)
_ADDITIONAL_FIELDS_REJECTED: set = set()

ADDITIONAL_FIELDS_KEY = "additionalModelRequestFields"


def _payload_model_id(json_data: Optional[dict]) -> Optional[str]:
    """The Kiro modelId from a generateAssistantResponse payload, if any."""
    try:
        return json_data["conversationState"]["currentMessage"]["userInputMessage"]["modelId"]
    except (KeyError, TypeError):
        return None


def strip_rejected_additional_fields(json_data: Optional[dict]) -> Optional[dict]:
    """Drops additionalModelRequestFields for models Kiro already rejected it for."""
    if isinstance(json_data, dict) and ADDITIONAL_FIELDS_KEY in json_data:
        if _payload_model_id(json_data) in _ADDITIONAL_FIELDS_REJECTED:
            return {k: v for k, v in json_data.items() if k != ADDITIONAL_FIELDS_KEY}
    return json_data


def agent_mode_for_payload(json_data: Optional[dict]) -> str:
    """x-amzn-kiro-agent-mode from the payload's agentTaskType ("spectask" or "vibe")."""
    if isinstance(json_data, dict):
        task_type = (json_data.get("conversationState") or {}).get("agentTaskType")
        if task_type == "spectask":
            return "spectask"
    return "vibe"


def build_headers(auth_manager: Any, token: str, endpoint: Endpoint, attempt: int, agent_mode: str) -> dict:
    """
    Upstream get_kiro_headers(), adjusted per endpoint and attempt.

    Looked up through kiro.http_client so any other patch of get_kiro_headers applies.
    """
    import kiro.http_client as http_client_module

    headers = http_client_module.get_kiro_headers(auth_manager, token)
    if endpoint.amz_target:
        headers["x-amz-target"] = endpoint.amz_target
    else:
        headers.pop("x-amz-target", None)
    headers["amz-sdk-request"] = f"attempt={attempt}; max=3"
    headers["x-amzn-kiro-agent-mode"] = agent_mode
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

async def request_with_retry(
    self,
    method: str,
    url: str,
    json_data: Optional[dict] = None,
    params: Optional[dict] = None,
    stream: bool = False
) -> httpx.Response:
    """
    Executes an HTTP request with retry logic (replaces KiroHttpClient.request_with_retry).

    - 403: refreshes token via auth_manager.force_refresh() and retries
    - 429: rotates to the next configured endpoint (KIRO_ENDPOINTS), otherwise
      waits with linear backoff + jitter (Retry-After honoured)
    - 408/5xx: waits with capped exponential backoff + jitter
    - 400 rejecting additionalModelRequestFields: strips it and retries
    - Timeouts / network errors: capped exponential backoff + jitter

    Returns:
        httpx.Response (200, or the last 429/5xx/4xx for the caller to classify)

    Raises:
        HTTPException: On network failure after all attempts (502/504)
    """
    from kiro.config import MAX_RETRIES, FIRST_TOKEN_MAX_RETRIES
    import kiro.http_client as http_client_module

    classify_network_error = http_client_module.classify_network_error
    get_short_error_message = http_client_module.get_short_error_message

    max_retries = FIRST_TOKEN_MAX_RETRIES if stream else MAX_RETRIES

    client = await self._get_client(stream=stream)
    last_error_info = None
    last_response: Optional[httpx.Response] = None  # last 429/5xx, returned after exhaustion

    json_data = strip_rejected_additional_fields(json_data)
    has_profile_arn = bool(getattr(self.auth_manager, "_profile_arn", None) or getattr(self.auth_manager, "profile_arn", None))
    endpoints = endpoint_candidates(url, has_profile_arn=has_profile_arn)
    account_key = id(self.auth_manager)
    agent_mode = agent_mode_for_payload(json_data)

    attempt = 0
    while attempt < max_retries:
        # Advanced at the end of every pass except the free additionalModelRequestFields
        # retry below (which can happen at most once: the field is gone afterwards).
        consumes_attempt = True
        try:
            # Rotate across endpoints: throttled buckets are moved to the back
            endpoint = endpoint_registry.order(account_key, endpoints)[0]
            request_url = url if endpoint.name == "requested" else endpoint.url

            token = await self.auth_manager.get_access_token()
            headers = build_headers(self.auth_manager, token, endpoint, attempt + 1, agent_mode)

            request_kwargs: Dict[str, Any] = {"headers": headers}
            if json_data is not None:
                request_kwargs["content"] = json.dumps(json_data).encode()
            if params is not None:
                request_kwargs["params"] = params

            if stream:
                # Prevent CLOSE_WAIT connection leak (issue #38)
                headers["Connection"] = "close"
                req = client.build_request(method, request_url, **request_kwargs)
                logger.debug(f"Sending request to Kiro API ({endpoint.name})...")
                response = await client.send(req, stream=True)
            else:
                logger.debug(f"Sending request to Kiro API ({endpoint.name})...")
                response = await client.request(method, request_url, **request_kwargs)

            if response.status_code == 200:
                return response

            # 403 - token expired, refresh and retry
            if response.status_code == 403:
                logger.warning(f"Received 403, refreshing token (attempt {attempt + 1}/{max_retries})")
                await self.auth_manager.force_refresh()
                continue

            # 429 - rate limit: mark endpoint bucket, rotate, back off
            if response.status_code == 429:
                last_response = response
                if len(endpoints) > 1:
                    endpoint_registry.throttle(account_key, endpoint.name)
                retry_after = None
                resp_headers = getattr(response, "headers", None)
                if isinstance(resp_headers, (dict, httpx.Headers)):
                    retry_after = resp_headers.get("retry-after")
                # Other endpoints are separate buckets: switch without waiting
                free_left = len(endpoints) > 1 and any(
                    not endpoint_registry.is_throttled(account_key, e.name) for e in endpoints
                )
                if free_left:
                    logger.warning(
                        f"Received 429 on '{endpoint.name}', switching endpoint "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    continue
                if attempt < max_retries - 1:
                    delay = throttle_delay(attempt, retry_after)
                    logger.warning(f"Received 429, waiting {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                continue

            # 408 / 5xx - transient server error, wait and retry
            if response.status_code == 408 or 500 <= response.status_code < 600:
                last_response = response
                if attempt < max_retries - 1:
                    delay = backoff_delay(attempt)
                    logger.warning(
                        f"Received {response.status_code}, waiting {delay:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(delay)
                continue

            # 400 because this model doesn't accept additionalModelRequestFields:
            # strip the field and retry
            if (
                response.status_code == 400
                and isinstance(json_data, dict)
                and ADDITIONAL_FIELDS_KEY in json_data
            ):
                body = await response.aread()
                if ADDITIONAL_FIELDS_KEY.encode() in body:
                    model_id = _payload_model_id(json_data)
                    # Remember the model only when the field itself is unsupported;
                    # a rejected value (e.g. an unknown effort) affects this request only.
                    if model_id and b"not supported" in body.lower():
                        _ADDITIONAL_FIELDS_REJECTED.add(model_id)
                    logger.warning(
                        f"Kiro rejected {ADDITIONAL_FIELDS_KEY} for model '{model_id}': "
                        f"{body[:200].decode('utf-8', errors='replace')} - retrying without it"
                    )
                    await response.aclose()
                    json_data = {k: v for k, v in json_data.items() if k != ADDITIONAL_FIELDS_KEY}
                    consumes_attempt = False
                    continue

            # Other errors - return as is
            _record_upstream_status(response.status_code)
            return response

        except (httpx.TimeoutException, httpx.RequestError) as e:
            error_info = classify_network_error(e)
            last_error_info = error_info
            short_msg = get_short_error_message(error_info)

            if error_info.is_retryable and attempt < max_retries - 1:
                delay = backoff_delay(attempt)
                logger.warning(f"{short_msg} - waiting {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
            else:
                logger.error(f"{short_msg} - no more retries (attempt {attempt + 1}/{max_retries})")
                if not error_info.is_retryable:
                    break
        finally:
            if consumes_attempt:
                attempt += 1

    # 429/5xx retries exhausted: return the response so the caller sees the real status
    if last_response is not None:
        logger.warning(
            f"Retries exhausted for HTTP {last_response.status_code}, "
            f"returning response to caller for classification"
        )
        _record_upstream_status(last_response.status_code)
        return last_response

    if last_error_info:
        error_message = last_error_info.user_message
        if last_error_info.troubleshooting_steps:
            error_message += "\n\nTroubleshooting:\n"
            for i, step in enumerate(last_error_info.troubleshooting_steps, 1):
                error_message += f"{i}. {step}\n"
        error_message += f"\nTechnical details: {last_error_info.technical_details}"
        raise HTTPException(
            status_code=last_error_info.suggested_http_code,
            detail=error_message.strip()
        )

    if stream:
        raise HTTPException(
            status_code=504,
            detail=f"Streaming failed after {max_retries} attempts. Unknown error."
        )
    raise HTTPException(
        status_code=502,
        detail=f"Request failed after {max_retries} attempts. Unknown error."
    )


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
        + (f" (429 rotation to: {', '.join(extra)})" if extra else "")
    )


def uninstall_upstream_retry() -> None:
    """Restore the patched method. Intended for unit tests."""
    global _installed
    if _originals:
        from kiro.http_client import KiroHttpClient

        KiroHttpClient.request_with_retry = _originals["request_with_retry"]

    _originals.clear()
    endpoint_registry.clear()
    _ADDITIONAL_FIELDS_REJECTED.clear()
    _installed = False
