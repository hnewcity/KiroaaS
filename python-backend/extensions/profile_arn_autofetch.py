"""
Auto-fetch a missing profileArn at runtime.

runtime.kiro.dev requires a profileArn on every request for all auth types
(see routes_*.py, which send `auth_manager.profile_arn or PROFILE_ARN or ""`).
Some accounts — notably Enterprise IdC — don't carry a profileArn in their
credentials file, so requests go out with an empty ARN and can 400.

Upstream kiro-gateway solved this with KiroAuthManager.fetch_profile_arn(),
gated behind an is_enterprise_ide check. KiroaaS keeps kiro/ zero-diff against
upstream, so instead of patching auth.py we wrap KiroAuthManager.get_access_token
at runtime (installed from app_entry.py).

Simplification vs upstream: no is_enterprise_ide gate. If a manager has no
profileArn, we try to fetch one — regardless of auth type. This is safe because
the send side already sends profileArn for every auth type; we only turn an
empty ARN into a real one. ListAvailableProfiles lives on q.{region}.amazonaws.com
(runtime.kiro.dev does not serve it), and the call is read-only — failures are
non-fatal and leave behavior exactly as it is today (empty ARN).
"""

import asyncio
import json

import httpx
from loguru import logger


_installed = False
_original_get_access_token = None

# ListAvailableProfiles is served by q.amazonaws.com, NOT runtime.kiro.dev.
# auth_manager.q_host points at runtime.kiro.dev (config KIRO_Q_HOST_TEMPLATE),
# so we build the host here to keep kiro/config.py zero-diff.
_LIST_PROFILES_HOST_TEMPLATE = "https://q.{region}.amazonaws.com/"

# Per-instance guard: set once we enter the fetch branch (success OR failure),
# so a profile-less account never hammers ListAvailableProfiles on every request.
_FETCH_ATTEMPTED_ATTR = "_profile_arn_fetch_attempted"


async def _fetch_profile_arn(auth_manager, token: str) -> None:
    """
    Resolve a profileArn via ListAvailableProfiles and store it on the manager.

    The caller passes the already-resolved access token so we never re-enter
    get_access_token() (which would re-acquire the non-reentrant self._lock).
    All failure modes are swallowed with a warning — the request proceeds with
    whatever profileArn (possibly empty) it had before.
    """
    from extensions.protocol_runtime import configured_profile, prepare_operation
    from extensions.cloud_connector import require_cloud_route

    profile = configured_profile(auth_manager)
    region = auth_manager._sso_region or auth_manager._region
    legacy_url = _LIST_PROFILES_HOST_TEMPLATE.format(region=region)
    prepared = prepare_operation(auth_manager, token, "POST", legacy_url, {"nextToken": None}, operation="ListAvailableProfiles")
    require_cloud_route(prepared.url)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(prepared.method, prepared.url, headers=prepared.headers,
                                            json=prepared.payload, follow_redirects=False,
                                            extensions={"kiro_upstream": True})

        if response.status_code != 200:
            logger.warning(
                f"ListAvailableProfiles returned {response.status_code}; proceeding without profileArn"
            )
            return

        data = response.json() or {}
        profiles = data.get("profiles") or []
        if not profiles:
            logger.warning(
                "ListAvailableProfiles returned empty profiles list — cannot resolve profileArn"
            )
            return

        arn = profiles[0].get("arn") or profiles[0].get("profileArn")
        if not arn:
            logger.warning(
                "ListAvailableProfiles: first profile has no ARN field"
            )
            return

        auth_manager._profile_arn = arn
        logger.info(
            f"profileArn resolved via ListAvailableProfiles: "
            f"profile={profiles[0].get('profileName', '?')}"
        )

        # Persist only for file-backed creds. _save_credentials_to_file() writes
        # profileArn and early-returns when _creds_file is None; the sqlite saver
        # does not persist profile_arn at all, so sqlite accounts simply re-fetch
        # once per process (cheap, guarded).
        if auth_manager._creds_file:
            await asyncio.to_thread(auth_manager._save_credentials_to_file)

    except Exception as e:
        logger.warning(f"profileArn autofetch failed (will proceed without profileArn): {e}")


def install_profile_arn_autofetch() -> None:
    """Wrap KiroAuthManager.get_access_token to backfill a missing profileArn."""
    global _installed, _original_get_access_token
    if _installed:
        return

    from kiro.auth import KiroAuthManager

    _original_get_access_token = KiroAuthManager.get_access_token

    async def get_access_token_with_autofetch(self):
        token = await _original_get_access_token(self)

        # The original released self._lock before returning, so fetching here is
        # serial (not nested) — no deadlock. asyncio is single-threaded, so the
        # check-and-set below runs without an intervening await: setting the flag
        # before `await _fetch_profile_arn` is enough to prevent concurrent
        # get_access_token() calls from fetching more than once.
        if (
            token
            and not self._profile_arn
            and getattr(self, _FETCH_ATTEMPTED_ATTR, None) != self.credential_generation
        ):
            setattr(self, _FETCH_ATTEMPTED_ATTR, self.credential_generation)
            await _fetch_profile_arn(self, token)

        return token

    KiroAuthManager.get_access_token = get_access_token_with_autofetch
    _installed = True
    logger.info("Installed profileArn autofetch extension")


def uninstall_profile_arn_autofetch() -> None:
    """Restore the original get_access_token. Intended for unit tests."""
    global _installed, _original_get_access_token

    if _original_get_access_token is not None:
        from kiro.auth import KiroAuthManager

        KiroAuthManager.get_access_token = _original_get_access_token

    _original_get_access_token = None
    _installed = False
