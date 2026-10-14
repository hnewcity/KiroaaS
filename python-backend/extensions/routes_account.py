"""
Extension routes: /usage and /account.

Lives outside the upstream kiro/ tree so upstream can be sync'd without conflicts.
Mounted by app_entry.py.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from kiro.auth import KiroAuthManager
from kiro.routes_openai import verify_api_key
from kiro.utils import get_kiro_headers
from extensions.protocol_runtime import request_operation


router = APIRouter()


def _resolve_auth_manager(request: Request) -> KiroAuthManager:
    account = request.app.state.account_manager.get_first_account()
    if not account or not account.auth_manager:
        raise HTTPException(status_code=503, detail="No initialized account available")
    return account.auth_manager


@router.get("/usage", dependencies=[Depends(verify_api_key)])
async def get_usage(request: Request):
    """
    Query Kiro credit usage via GetUsageLimits API.

    Returns subscription info, credit usage breakdown, overage config,
    and reset date — the same data shown by kiro-cli's /usage command.
    """
    logger.info("Request to /usage")

    auth_manager = _resolve_auth_manager(request)
    shared_client = request.app.state.http_client

    try:
        response = await request_operation(auth_manager, "GetUsageLimits", payload={"isEmailRequired": True}, client=shared_client)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return JSONResponse(content=response.json())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching usage: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch usage: {str(e)}")


@router.get("/account", dependencies=[Depends(verify_api_key)])
async def get_account(request: Request):
    """
    Query Kiro account profile by calling the usage endpoint internally.

    Returns account name, email, subscription plan, quota information,
    trial plan details, and expiration dates.
    """
    logger.info("Request to /account")

    auth_manager = _resolve_auth_manager(request)
    shared_client = request.app.state.http_client

    try:
        response = await request_operation(auth_manager, "GetUsageLimits", payload={"isEmailRequired": True}, client=shared_client)

        logger.debug(f"Kiro API response status: {response.status_code}")

        if response.status_code != 200:
            error_text = response.text
            logger.error("Kiro usage API returned HTTP {}", response.status_code)
            raise HTTPException(status_code=response.status_code, detail=error_text)

        usage_data = response.json()

        user_info = usage_data.get("userInfo", {})
        subscription_info = usage_data.get("subscriptionInfo", {})
        usage_list = usage_data.get("usageBreakdownList", [])

        logger.debug("Received account usage fields: {}", list(usage_data))

        usage_info = usage_list[0] if usage_list else {}

        free_trial_info = usage_info.get("freeTrialInfo", {})
        is_trial = free_trial_info.get("freeTrialStatus") == "ACTIVE"

        trial_expiry_ts = free_trial_info.get("freeTrialExpiry")
        trial_expiry = None
        if trial_expiry_ts:
            trial_expiry = datetime.fromtimestamp(trial_expiry_ts).strftime("%Y-%m-%d")

        subscription_expiry = subscription_info.get("expiryDate") or subscription_info.get("subscriptionExpiryDate")

        account_status = "Trial" if is_trial else "Active"
        if subscription_info.get("status"):
            account_status = subscription_info.get("status")

        bonuses = usage_info.get("bonuses", [])
        active_bonuses = [b for b in bonuses if b.get("status") == "ACTIVE"]
        bonus_quota = sum(b.get("usageLimitWithPrecision", b.get("usageLimit", 0)) for b in active_bonuses) if active_bonuses else None
        bonus_usage = sum(b.get("currentUsageWithPrecision", b.get("currentUsage", 0)) for b in active_bonuses) if active_bonuses else None
        bonus_remaining = (bonus_quota - bonus_usage) if bonus_quota and bonus_usage else None

        trial_quota = free_trial_info.get("usageLimitWithPrecision") or free_trial_info.get("usageLimit") or 0
        trial_usage = free_trial_info.get("currentUsageWithPrecision") or free_trial_info.get("currentUsage") or 0

        free_quota = usage_info.get("usageLimitWithPrecision") or usage_info.get("usageLimit") or 0
        free_usage = usage_info.get("currentUsageWithPrecision") or usage_info.get("currentUsage") or 0

        total_quota = trial_quota + free_quota
        total_usage = trial_usage + free_usage

        remaining_quota = (total_quota - total_usage) if total_quota and total_usage else None
        usage_percentage = round((total_usage / total_quota) * 100, 2) if total_quota and total_usage else 0

        account_data = {
            "accountName": user_info.get("email") or "User",
            "email": user_info.get("email"),
            "provider": user_info.get("provider"),
            "planType": subscription_info.get("type", "Free"),
            "subscriptionTitle": subscription_info.get("subscriptionTitle"),
            "isTrial": is_trial,
            "trialExpiryDate": trial_expiry,
            "subscriptionExpiryDate": subscription_expiry,
            "totalQuota": total_quota,
            "currentUsage": total_usage,
            "remainingQuota": remaining_quota,
            "usagePercentage": usage_percentage,
            "trialQuota": trial_quota,
            "trialUsage": trial_usage,
            "freeQuota": free_quota,
            "freeUsage": free_usage,
            "bonusQuota": bonus_quota,
            "bonusUsage": bonus_usage,
            "bonusRemaining": bonus_remaining,
            "accountStatus": account_status,
            "resetDate": usage_info.get("resetDate"),
            "overageEnabled": usage_info.get("overageEnabled", False),
        }

        logger.info(f"Account retrieved: {account_data.get('email')} (trial={is_trial}, quota={total_quota}, bonus={bonus_quota})")
        return JSONResponse(content=account_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching account: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch account: {str(e)}")
