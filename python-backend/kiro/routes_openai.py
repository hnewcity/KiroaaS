# -*- coding: utf-8 -*-

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
FastAPI routes for Kiro Gateway.

Contains all API endpoints:
- / and /health: Health check
- /usage: Kiro credit usage (requires API key)
- /v1/models: Models list
- /v1/chat/completions: Chat completions
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from loguru import logger

from kiro.config import (
    PROXY_API_KEY,
    APP_VERSION,
)
from kiro.models_openai import (
    OpenAIModel,
    ModelList,
    ChatCompletionRequest,
)
from kiro.auth import KiroAuthManager, AuthType
from kiro.cache import ModelInfoCache
from kiro.model_resolver import ModelResolver
from kiro.converters_openai import build_kiro_payload
from kiro.streaming_openai import stream_kiro_to_openai, collect_stream_response, stream_with_first_token_retry
from kiro.http_client import KiroHttpClient
from kiro.utils import generate_conversation_id, get_kiro_headers

# Import debug_logger
try:
    from kiro.debug_logger import debug_logger
except ImportError:
    debug_logger = None


# --- Security scheme ---
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def verify_api_key(auth_header: str = Security(api_key_header)) -> bool:
    """
    Verify API key in Authorization header.
    
    Expects format: "Bearer {PROXY_API_KEY}"
    
    Args:
        auth_header: Authorization header value
    
    Returns:
        True if key is valid
    
    Raises:
        HTTPException: 401 if key is invalid or missing
    """
    if not auth_header or auth_header != f"Bearer {PROXY_API_KEY}":
        logger.warning("Access attempt with invalid API key.")
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
    return True


# --- Router ---
router = APIRouter()


@router.get("/")
async def root():
    """
    Health check endpoint.
    
    Returns:
        Status and application version
    """
    return {
        "status": "ok",
        "message": "Kiro Gateway is running",
        "version": APP_VERSION
    }


@router.get("/health")
async def health():
    """
    Detailed health check.
    
    Returns:
        Status, timestamp and version
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": APP_VERSION
    }


@router.get("/usage", dependencies=[Depends(verify_api_key)])
async def get_usage(request: Request):
    """
    Query Kiro credit usage via GetUsageLimits API.

    Returns subscription info, credit usage breakdown, overage config,
    and reset date — the same data shown by kiro-cli's /usage command.
    """
    logger.info("Request to /v1/usage")

    auth_manager: KiroAuthManager = request.app.state.auth_manager
    shared_client = request.app.state.http_client

    token = await auth_manager.get_access_token()
    headers = get_kiro_headers(auth_manager, token)
    headers["x-amz-target"] = "com.amazon.aws.codewhisperer.runtime.AmazonCodeWhispererService.GetUsageLimits"
    headers["Content-Type"] = "application/x-amz-json-1.0"

    url = auth_manager.api_host
    body = {"origin": "AI_EDITOR", "isEmailRequired": True}

    try:
        response = await shared_client.post(url, json=body, headers=headers)
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

    auth_manager: KiroAuthManager = request.app.state.auth_manager
    shared_client = request.app.state.http_client

    try:
        token = await auth_manager.get_access_token()
        headers = get_kiro_headers(auth_manager, token)
        headers["x-amz-target"] = "com.amazon.aws.codewhisperer.runtime.AmazonCodeWhispererService.GetUsageLimits"
        headers["Content-Type"] = "application/x-amz-json-1.0"

        url = auth_manager.api_host
        body = {"origin": "AI_EDITOR", "isEmailRequired": True}

        logger.debug(f"Calling Kiro API with headers: {headers}")
        response = await shared_client.post(url, json=body, headers=headers)

        logger.debug(f"Kiro API response status: {response.status_code}")

        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Kiro API error: {response.status_code} - {error_text}")
            raise HTTPException(status_code=response.status_code, detail=error_text)

        usage_data = response.json()

        # Extract account info from usage data
        user_info = usage_data.get("userInfo", {})
        subscription_info = usage_data.get("subscriptionInfo", {})
        usage_list = usage_data.get("usageBreakdownList", [])

        # Log full response for debugging
        logger.info(f"Full API response: {json.dumps(usage_data, indent=2)}")

        # Extract primary usage info (usually index 0 - covered in plan)
        usage_info = usage_list[0] if usage_list else {}

        # Extract trial status from freeTrialInfo (not subscriptionInfo)
        free_trial_info = usage_info.get("freeTrialInfo", {})
        is_trial = free_trial_info.get("freeTrialStatus") == "ACTIVE"

        # Extract trial expiry date (Unix timestamp)
        trial_expiry_ts = free_trial_info.get("freeTrialExpiry")
        trial_expiry = None
        if trial_expiry_ts:
            from datetime import datetime
            trial_expiry = datetime.fromtimestamp(trial_expiry_ts).strftime("%Y-%m-%d")

        subscription_expiry = subscription_info.get("expiryDate") or subscription_info.get("subscriptionExpiryDate")

        # Determine account status
        account_status = "Trial" if is_trial else "Active"
        if subscription_info.get("status"):
            account_status = subscription_info.get("status")

        # Extract bonus credits from breakdown.bonuses array (like kiro-account-manager)
        bonuses = usage_info.get("bonuses", [])
        active_bonuses = [b for b in bonuses if b.get("status") == "ACTIVE"]
        bonus_quota = sum(b.get("usageLimitWithPrecision", b.get("usageLimit", 0)) for b in active_bonuses) if active_bonuses else None
        bonus_usage = sum(b.get("currentUsageWithPrecision", b.get("currentUsage", 0)) for b in active_bonuses) if active_bonuses else None
        bonus_remaining = (bonus_quota - bonus_usage) if bonus_quota and bonus_usage else None

        # Extract quota info - use trial quota if active, otherwise use plan quota
        if is_trial:
            total_quota = free_trial_info.get("usageLimitWithPrecision") or free_trial_info.get("usageLimit")
            current_usage = free_trial_info.get("currentUsageWithPrecision") or free_trial_info.get("currentUsage")
        else:
            total_quota = usage_info.get("usageLimitWithPrecision") or usage_info.get("usageLimit")
            current_usage = usage_info.get("currentUsageWithPrecision") or usage_info.get("currentUsage")

        # Extract quota info - trial + free
        trial_quota = free_trial_info.get("usageLimitWithPrecision") or free_trial_info.get("usageLimit") or 0
        trial_usage = free_trial_info.get("currentUsageWithPrecision") or free_trial_info.get("currentUsage") or 0

        free_quota = usage_info.get("usageLimitWithPrecision") or usage_info.get("usageLimit") or 0
        free_usage = usage_info.get("currentUsageWithPrecision") or usage_info.get("currentUsage") or 0

        # Total = trial + free
        total_quota = trial_quota + free_quota
        total_usage = trial_usage + free_usage

        # Calculate remaining quota and percentage
        remaining_quota = (total_quota - total_usage) if total_quota and total_usage else None
        usage_percentage = round((total_usage / total_quota) * 100, 2) if total_quota and total_usage else 0

        # Build account response
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
            "bonusRemaining": (bonus_quota - bonus_usage) if bonus_quota and bonus_usage else None,
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


@router.get("/v1/models", response_model=ModelList, dependencies=[Depends(verify_api_key)])
async def get_models(request: Request):
    """
    Return list of available models.
    
    Models are loaded at startup (blocking) and cached.
    This endpoint returns the cached list.
    
    Args:
        request: FastAPI Request for accessing app.state
    
    Returns:
        ModelList with available models in consistent format (with dots)
    """
    logger.info("Request to /v1/models")
    
    model_resolver: ModelResolver = request.app.state.model_resolver
    
    # Get all available models from resolver (cache + hidden models)
    available_model_ids = model_resolver.get_available_models()
    
    # Build OpenAI-compatible model list
    openai_models = [
        OpenAIModel(
            id=model_id,
            owned_by="anthropic",
            description="Claude model via Kiro API"
        )
        for model_id in available_model_ids
    ]
    
    return ModelList(data=openai_models)


@router.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request, request_data: ChatCompletionRequest):
    """
    Chat completions endpoint - compatible with OpenAI API.
    
    Accepts requests in OpenAI format and translates them to Kiro API.
    Supports streaming and non-streaming modes.
    
    Args:
        request: FastAPI Request for accessing app.state
        request_data: Request in OpenAI ChatCompletionRequest format
    
    Returns:
        StreamingResponse for streaming mode
        JSONResponse for non-streaming mode
    
    Raises:
        HTTPException: On validation or API errors
    """
    logger.info(f"Request to /v1/chat/completions (model={request_data.model}, stream={request_data.stream})")
    
    auth_manager: KiroAuthManager = request.app.state.auth_manager
    model_cache: ModelInfoCache = request.app.state.model_cache
    
    # Note: prepare_new_request() and log_request_body() are now called by DebugLoggerMiddleware
    # This ensures debug logging works even for requests that fail Pydantic validation (422 errors)
    
    # Check for truncation recovery opportunities
    from kiro.truncation_state import get_tool_truncation, get_content_truncation
    from kiro.truncation_recovery import generate_truncation_tool_result, generate_truncation_user_message
    from kiro.models_openai import ChatMessage
    
    modified_messages = []
    tool_results_modified = 0
    content_notices_added = 0
    
    for msg in request_data.messages:
        # Check if this is a tool_result for a truncated tool call
        if msg.role == "tool" and msg.tool_call_id:
            truncation_info = get_tool_truncation(msg.tool_call_id)
            if truncation_info:
                # Modify tool_result content to include truncation notice
                synthetic = generate_truncation_tool_result(
                    tool_name=truncation_info.tool_name,
                    tool_use_id=msg.tool_call_id,
                    truncation_info=truncation_info.truncation_info
                )
                # Prepend truncation notice to original content
                modified_content = f"{synthetic['content']}\n\n---\n\nOriginal tool result:\n{msg.content}"
                
                # Create NEW ChatMessage object (Pydantic immutability)
                modified_msg = msg.model_copy(update={"content": modified_content})
                modified_messages.append(modified_msg)
                tool_results_modified += 1
                logger.debug(f"Modified tool_result for {msg.tool_call_id} to include truncation notice")
                continue  # Skip normal append since we already added modified version
        
        # Check if this is an assistant message with truncated content
        if msg.role == "assistant" and msg.content and isinstance(msg.content, str):
            truncation_info = get_content_truncation(msg.content)
            if truncation_info:
                # Add this message first
                modified_messages.append(msg)
                # Then add synthetic user message about truncation
                synthetic_user_msg = ChatMessage(
                    role="user",
                    content=generate_truncation_user_message()
                )
                modified_messages.append(synthetic_user_msg)
                content_notices_added += 1
                logger.debug(f"Added truncation notice after assistant message (hash: {truncation_info.message_hash})")
                continue  # Skip normal append since we already added it
        
        modified_messages.append(msg)
    
    if tool_results_modified > 0 or content_notices_added > 0:
        request_data.messages = modified_messages
        logger.info(f"Truncation recovery: modified {tool_results_modified} tool_result(s), added {content_notices_added} content notice(s)")
    
    # Generate conversation ID for Kiro API (random UUID, not used for tracking)
    conversation_id = generate_conversation_id()
    
    # Build payload for Kiro
    # profileArn is only needed for Kiro Desktop auth
    # AWS SSO OIDC (Builder ID) users don't need profileArn and it causes 403 if sent
    profile_arn_for_payload = ""
    if auth_manager.auth_type == AuthType.KIRO_DESKTOP and auth_manager.profile_arn:
        profile_arn_for_payload = auth_manager.profile_arn
    
    try:
        kiro_payload = build_kiro_payload(
            request_data,
            conversation_id,
            profile_arn_for_payload
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Log Kiro payload
    try:
        kiro_request_body = json.dumps(kiro_payload, ensure_ascii=False, indent=2).encode('utf-8')
        if debug_logger:
            debug_logger.log_kiro_request_body(kiro_request_body)
    except Exception as e:
        logger.warning(f"Failed to log Kiro request: {e}")
    
    # Create HTTP client with retry logic
    # For streaming: use per-request client to avoid CLOSE_WAIT leak on VPN disconnect (issue #54)
    # For non-streaming: use shared client for connection pooling
    url = f"{auth_manager.api_host}/generateAssistantResponse"
    logger.debug(f"Kiro API URL: {url}")
    
    if request_data.stream:
        # Streaming mode: per-request client prevents orphaned connections
        # when network interface changes (VPN disconnect/reconnect)
        http_client = KiroHttpClient(auth_manager, shared_client=None)
    else:
        # Non-streaming mode: shared client for efficient connection reuse
        shared_client = request.app.state.http_client
        http_client = KiroHttpClient(auth_manager, shared_client=shared_client)
    try:
        # Make request to Kiro API (for both streaming and non-streaming modes)
        # Important: we wait for Kiro response BEFORE returning StreamingResponse,
        # so that 200 OK means Kiro accepted the request and started responding
        response = await http_client.request_with_retry(
            "POST",
            url,
            kiro_payload,
            stream=True
        )
        
        if response.status_code != 200:
            try:
                error_content = await response.aread()
            except Exception:
                error_content = b"Unknown error"
            
            await http_client.close()
            error_text = error_content.decode('utf-8', errors='replace')
            
            # Try to parse JSON response from Kiro to extract error message
            error_message = error_text
            try:
                error_json = json.loads(error_text)
                # Enhance Kiro API errors with user-friendly messages
                from kiro.kiro_errors import enhance_kiro_error
                error_info = enhance_kiro_error(error_json)
                error_message = error_info.user_message
                # Log original error for debugging
                logger.debug(f"Original Kiro error: {error_info.original_message} (reason: {error_info.reason})")
            except (json.JSONDecodeError, KeyError):
                pass
            
            # Log access log for error (before flush, so it gets into app_logs)
            logger.warning(
                f"HTTP {response.status_code} - POST /v1/chat/completions - {error_message[:100]}"
            )
            
            # Flush debug logs on error ("errors" mode)
            if debug_logger:
                debug_logger.flush_on_error(response.status_code, error_message)
            
            # Return error in OpenAI API format
            return JSONResponse(
                status_code=response.status_code,
                content={
                    "error": {
                        "message": error_message,
                        "type": "kiro_api_error",
                        "code": response.status_code
                    }
                }
            )
        
        # Prepare data for fallback token counting
        # Convert Pydantic models to dicts for tokenizer
        messages_for_tokenizer = [msg.model_dump() for msg in request_data.messages]
        tools_for_tokenizer = [tool.model_dump() for tool in request_data.tools] if request_data.tools else None
        
        if request_data.stream:
            # Streaming mode
            async def stream_wrapper():
                streaming_error = None
                client_disconnected = False
                try:
                    async for chunk in stream_kiro_to_openai(
                        http_client.client,
                        response,
                        request_data.model,
                        model_cache,
                        auth_manager,
                        request_messages=messages_for_tokenizer,
                        request_tools=tools_for_tokenizer
                    ):
                        yield chunk
                except GeneratorExit:
                    # Client disconnected - this is normal
                    client_disconnected = True
                    logger.debug("Client disconnected during streaming (GeneratorExit in routes)")
                except Exception as e:
                    streaming_error = e
                    # Try to send [DONE] to client before finishing
                    # so client doesn't "hang" waiting for data
                    try:
                        yield "data: [DONE]\n\n"
                    except Exception:
                        pass  # Client already disconnected
                    raise
                finally:
                    await http_client.close()
                    # Log access log for streaming (success or error)
                    if streaming_error:
                        error_type = type(streaming_error).__name__
                        error_msg = str(streaming_error) if str(streaming_error) else "(empty message)"
                        logger.error(f"HTTP 500 - POST /v1/chat/completions (streaming) - [{error_type}] {error_msg[:100]}")
                    elif client_disconnected:
                        logger.info(f"HTTP 200 - POST /v1/chat/completions (streaming) - client disconnected")
                    else:
                        logger.info(f"HTTP 200 - POST /v1/chat/completions (streaming) - completed")
                    # Write debug logs AFTER streaming completes
                    if debug_logger:
                        if streaming_error:
                            debug_logger.flush_on_error(500, str(streaming_error))
                        else:
                            debug_logger.discard_buffers()
            
            return StreamingResponse(stream_wrapper(), media_type="text/event-stream")
        
        else:
            
            # Non-streaming mode - collect entire response
            openai_response = await collect_stream_response(
                http_client.client,
                response,
                request_data.model,
                model_cache,
                auth_manager,
                request_messages=messages_for_tokenizer,
                request_tools=tools_for_tokenizer
            )
            
            await http_client.close()
            
            # Log access log for non-streaming success
            logger.info(f"HTTP 200 - POST /v1/chat/completions (non-streaming) - completed")
            
            # Write debug logs after non-streaming request completes
            if debug_logger:
                debug_logger.discard_buffers()
            
            return JSONResponse(content=openai_response)
    
    except HTTPException as e:
        await http_client.close()
        # Log access log for HTTP error
        logger.error(f"HTTP {e.status_code} - POST /v1/chat/completions - {e.detail}")
        # Flush debug logs on HTTP error ("errors" mode)
        if debug_logger:
            debug_logger.flush_on_error(e.status_code, str(e.detail))
        raise
    except Exception as e:
        await http_client.close()
        logger.error(f"Internal error: {e}", exc_info=True)
        # Log access log for internal error
        logger.error(f"HTTP 500 - POST /v1/chat/completions - {str(e)[:100]}")
        # Flush debug logs on internal error ("errors" mode)
        if debug_logger:
            debug_logger.flush_on_error(500, str(e))
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")