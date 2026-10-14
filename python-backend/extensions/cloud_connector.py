"""
KiroaaS Cloud egress connector.

When enabled, intercepts httpx requests to q.*.amazonaws.com and re-routes them
through the KiroaaS Cloud forward Lambda. The session token is injected by the
Tauri shell as KIROAAS_CLOUD_API_KEY when spawning this process — the backend
never reads the OS keychain directly (cross-binary keychain ACLs block subprocess
access on macOS).

Mirrors the runtime-patch style of `tool_name_alias.py`: monkey-patches
httpx.AsyncClient.__init__ at startup, no upstream `kiro/` files touched.
"""

import hashlib
import os
import re
from urllib.parse import urlsplit
from typing import Optional

import httpx
from loguru import logger


_REGION = r"(?:[a-z]{2}|eusc)(?:-[a-z]{2,12}){1,3}-[1-9][0-9]?"
_KIRO_HOST = re.compile(rf"^(?:runtime|management)\.{_REGION}\.kiro\.dev$")
_AWS_HOST = re.compile(rf"^(?:q|oidc)\.{_REGION}\.amazonaws\.com$")
_DESKTOP_HOST = re.compile(rf"^prod\.{_REGION}\.auth\.desktop\.kiro\.dev$")


def _is_target_host(host: str) -> bool:
    """Finite service-host allowlist; adding CLI management does not allow arbitrary hosts."""
    host = host.lower()
    return bool(_KIRO_HOST.fullmatch(host) or _AWS_HOST.fullmatch(host) or _DESKTOP_HOST.fullmatch(host))


def require_cloud_route(url: str) -> None:
    """Fail closed when an explicitly enabled relay cannot safely carry an operation."""
    if os.getenv("KIROAAS_CLOUD_ENABLED", "false").lower() != "true":
        return
    target = urlsplit(url)
    if target.scheme != "https" or target.username is not None or not _is_target_host(target.hostname or ""):
        raise ValueError("Cloud mode cannot forward this upstream endpoint; configure a supported service endpoint or explicitly disable Cloud")
    if not _installed:
        raise ValueError("Cloud mode was requested but its transport is not installed; configure its URL/key and launch app_entry.py")


_installed = False
_originals = {}


class _CloudTransport(httpx.AsyncBaseTransport):
    def __init__(
        self, inner: httpx.AsyncBaseTransport, forward_url: str, token: str
    ) -> None:
        self._inner = inner
        self._forward_url = httpx.URL(forward_url)
        self._token = token
        self._announced = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").lower()
        if request.extensions.get("kiro_upstream") or _is_target_host(host):
            require_cloud_route(str(request.url))
            original = str(request.url)
            path = request.url.path + (
                f"?{request.url.query.decode()}" if request.url.query else ""
            )
            request.headers["X-Kiro-Target-Url"] = original
            request.headers["X-Cloud-Key"] = self._token
            # CloudFront OAC SigningBehavior=always rewrites the Authorization
            # header with its own SigV4. Stash kiro's Bearer token under a
            # custom header so the forward Lambda can restore it upstream.
            auth = request.headers.pop("authorization", None) or request.headers.pop(
                "Authorization", None
            )
            if auth:
                request.headers["X-Kiro-Authorization"] = auth
            # CloudFront OAC + Lambda Function URL requires the payload SHA256
            # in x-amz-content-sha256. CloudFront uses this hash when computing
            # the SigV4 signature it sends to Lambda. Without it, Lambda rejects
            # with InvalidSignatureException. (AWS docs: "Lambda doesn't support
            # unsigned payloads".)
            body = request.content or b""
            request.headers["x-amz-content-sha256"] = hashlib.sha256(body).hexdigest()
            # Rewrite (don't pop) Host: h11 mandates it, and httpx won't recompute
            # because we mutate request.url in place rather than rebuilding the request.
            request.headers["Host"] = self._forward_url.netloc.decode("ascii")
            request.url = self._forward_url
            if not self._announced:
                logger.info(
                    f"[cloud] FIRST forwarded request → {self._forward_url.host} (target={original})"
                )
                self._announced = True
            else:
                logger.debug(f"[cloud] forwarding {request.method} {path}")
            response = await self._inner.handle_async_request(request)
            req_id = response.headers.get("x-amzn-requestid") or response.headers.get(
                "x-amz-apigw-id"
            )
            logger.info(
                f"[cloud] {request.method} {path} → status={response.status_code} req_id={req_id or '-'}"
            )
            return response
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def install_cloud_connector() -> None:
    """Patch httpx so q.*.amazonaws.com calls are tunneled through the forward Lambda."""
    global _installed
    if _installed:
        return
    if (os.getenv("KIROAAS_CLOUD_ENABLED") or "").lower() != "true":
        logger.debug("[cloud_connector] disabled (KIROAAS_CLOUD_ENABLED != true)")
        return

    forward_url = os.getenv("KIROAAS_CLOUD_FORWARD_URL")
    token = os.getenv("KIROAAS_CLOUD_API_KEY")
    if not forward_url:
        raise ValueError("Cloud mode requires KIROAAS_CLOUD_FORWARD_URL; direct fallback is disabled")
    if not token:
        raise ValueError("Cloud mode requires sign-in/API key; direct fallback is disabled")
    parsed = urlsplit(forward_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("Cloud forward URL must be HTTPS without credentials or fragments")
    if any(ord(char) < 32 or ord(char) == 127 for char in token):
        raise ValueError("Cloud API key contains invalid header characters")

    _originals["AsyncClient.__init__"] = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        _originals["AsyncClient.__init__"](self, *args, **kwargs)
        try:
            inner = getattr(self, "_transport", None)
            if inner is not None and not isinstance(inner, _CloudTransport):
                self._transport = _CloudTransport(inner, forward_url, token)
            mounts = getattr(self, "_mounts", None)
            if isinstance(mounts, dict):
                for key, t in list(mounts.items()):
                    if t is not None and not isinstance(t, _CloudTransport):
                        mounts[key] = _CloudTransport(t, forward_url, token)
        except (AttributeError, TypeError, ValueError) as error:
            raise RuntimeError("Cloud transport could not be installed; refusing direct fallback") from error

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[assignment]
    _installed = True
    logger.info("[cloud_connector] installed for HTTPS relay host {}", parsed.hostname)


def uninstall_cloud_connector() -> None:
    global _installed
    if "AsyncClient.__init__" in _originals:
        httpx.AsyncClient.__init__ = _originals.pop("AsyncClient.__init__")  # type: ignore[assignment]
    _installed = False
