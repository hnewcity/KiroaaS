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
Kiro API error enhancement and user-friendly message formatting.

This module provides a centralized system for enhancing cryptic Kiro API errors
with clear, actionable, user-friendly messages.

Architecture:
- KiroErrorReason: Enum of known error reasons from Kiro API
- KiroErrorInfo: Structured information about an enhanced error
- enhance_kiro_error(): Analyzes error JSON and returns enhanced message

Example:
    >>> error_json = {"message": "Input is too long.", "reason": "CONTENT_LENGTH_EXCEEDS_THRESHOLD"}
    >>> error_info = enhance_kiro_error(error_json)
    >>> print(error_info.user_message)
    "Model context limit reached. Conversation size exceeds model capacity."
"""

import re

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any

from loguru import logger


@dataclass
class KiroErrorInfo:
    """
    Structured information about a Kiro API error.
    
    Contains both the enhanced user-friendly message and the original
    error details for logging and debugging.
    
    Attributes:
        reason: Error reason code from Kiro API (as string, e.g. "CONTENT_LENGTH_EXCEEDS_THRESHOLD")
        user_message: Enhanced, user-friendly message for end users
        original_message: Original message from Kiro API (for logging)
    """
    reason: str
    user_message: str
    original_message: str


def enhance_kiro_error(error_json: Dict[str, Any]) -> KiroErrorInfo:
    """
    Enhances Kiro API error with user-friendly message.
    
    Takes raw error JSON from Kiro API and returns structured information
    with enhanced, user-friendly messages that help users understand what
    went wrong without technical jargon.
    
    Args:
        error_json: Parsed JSON from Kiro API error response
                   Accepts Generate {"message": "...", "reason": "..."} or
                   Responses {"error": {"message": "...", "code": "..."}}.
                   Reason/code fields are optional; malformed shapes are ignored.
    
    Returns:
        KiroErrorInfo with enhanced message and original details
    
    Example:
        >>> error_json = {"message": "Input is too long.", "reason": "CONTENT_LENGTH_EXCEEDS_THRESHOLD"}
        >>> error_info = enhance_kiro_error(error_json)
        >>> print(error_info.user_message)
        "Model context limit reached. Conversation size exceeds model capacity."
        >>> print(error_info.original_message)
        "Input is too long."
    
    Example (unknown error):
        >>> error_json = {"message": "Something went wrong.", "reason": "UNKNOWN_REASON"}
        >>> error_info = enhance_kiro_error(error_json)
        >>> print(error_info.user_message)
        "Something went wrong. (reason: UNKNOWN_REASON)"
    """
    # Responses returns a nested error object, unlike Generate's flat body.
    # Inspect only known scalar fields; do not stringify arbitrary error payloads.
    envelope = error_json if isinstance(error_json, dict) else {}
    nested = envelope.get("error")
    source = nested if isinstance(nested, dict) else envelope
    original_message = source.get("message")
    if not isinstance(original_message, str):
        original_message = envelope.get("message")
    if not isinstance(original_message, str):
        original_message = "Unknown error"

    reason = source.get("reason")
    if reason is None and isinstance(nested, dict):
        reason = source.get("code")
        if reason is None:
            reason = source.get("type")
    if not isinstance(reason, str):
        reason = "UNKNOWN"
    
    # Map known reasons to user-friendly messages
    if reason == "CONTENT_LENGTH_EXCEEDS_THRESHOLD":
        # Context limit exceeded - conversation is too long
        user_message = "Model context limit reached. Conversation size exceeds model capacity."
    
    elif reason == "MONTHLY_REQUEST_COUNT":
        # Monthly request limit exceeded - account quota exhausted
        user_message = "Monthly request limit exceeded. Account has reached its monthly quota."
    
    elif reason == "INVALID_MODEL_ID":
        # Invalid model name or subscription tier insufficient
        user_message = "Invalid model ID or insufficient subscription level to use it."

    elif original_message == "Improperly formed request." and reason in (None, "UNKNOWN", "null"):
        # Generic 400 error
        user_message = (
            "Kiro API rejected the request. If problem persists, open issue with info and attached debug logs at:"
            "https://github.com/jwadow/kiro-gateway/issues"
        )

    # Future error enhancements can be added here:
    # elif reason == "RATE_LIMIT_EXCEEDED":
    #     user_message = "Rate limit exceeded. Too many requests in a short time."
    # elif reason == "INVALID_MODEL":
    #     user_message = "Invalid model specified. The requested model is not available."
    
    else:
        # Unknown error or no enhancement available
        # Keep original message and append reason if present
        if reason != "UNKNOWN":
            user_message = f"{original_message} (reason: {reason})"
        else:
            user_message = original_message
    
    # Responses may identify the rejected field separately from its generic
    # message. Preserve a bounded field path, never an arbitrary structured value.
    parameter = source.get("param") if isinstance(nested, dict) else None
    if isinstance(parameter, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\[\]-]{0,127}", parameter):
        user_message += f" (parameter: {parameter})"

    return KiroErrorInfo(
        reason=reason,
        user_message=user_message,
        original_message=original_message
    )
