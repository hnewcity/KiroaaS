"""
Entry point for launching the Kiro Gateway with local extensions.

Responsibilities:
- Import the upstream FastAPI app (zero-diff upstream)
- Mount local extension routers (/usage, /account)
- Handle Tauri-specific launch behavior (localhost binding, ready signal)
  without modifying upstream main.py

Use this instead of main.py when embedding the gateway into Tauri.
"""

import os
import sys

# Ensure python-backend root is on sys.path so `extensions` and `kiro` import.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import uvicorn
from loguru import logger

# Default the kiro-gateway fork's tuned settings (first-token / streaming
# timeouts, retries, web_search injection) BEFORE anything imports kiro:
# kiro/config.py reads them at import time. Explicit env / .env values win.
from extensions.upstream_defaults import apply_upstream_defaults

apply_upstream_defaults()

from extensions.protocol_runtime import validate_protocol_settings

validate_protocol_settings()

# Widen AnthropicMessage.role BEFORE importing main. FastAPI compiles and
# caches each route's body validator when the @router.post decorators run,
# which happens while `from main import app` imports the route modules. If we
# widen after that, the model itself accepts inline 'system' but the route's
# already-cached validator still rejects it (422). So this must run first.
from extensions.role_widening import install_role_widening

install_role_widening()

# Widen AnthropicMessage.content to accept Anthropic server-side tool blocks
# (server_tool_use / web_search_tool_result) that clients replay into history.
# Same import-order constraint as role widening: must run before the route
# modules are imported so FastAPI compiles the widened body validator.
from extensions.server_tool_blocks import install_server_tool_blocks

install_server_tool_blocks()

# Importing main runs module-level setup (logging, FastAPI instance, lifespan).
from main import (
    app,
    validate_configuration,
    parse_cli_args,
    resolve_server_config,
    print_startup_banner,
    UVICORN_LOG_CONFIG,
    SERVER_HOST,
    SERVER_PORT,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
)

from extensions.routes_account import router as account_router
from extensions.tool_name_alias import install_tool_name_aliasing
from extensions.cloud_connector import install_cloud_connector
from extensions.profile_arn_autofetch import install_profile_arn_autofetch
from extensions.control_plane_host import install_control_plane_host_redirect
from extensions.chat_host_fallback import install_chat_host_fallback
from extensions.model_id_format import install_model_id_format
from extensions.billing_header_strip import install_billing_header_strip
from extensions.kiro_stream_decoder import install_kiro_stream_decoder
from extensions.kiro_payload_builder import install_kiro_payload_builder
from extensions.upstream_retry import install_upstream_retry
from extensions.upstream_account import install_upstream_account_context
from extensions.client_compat import install_client_compat


# Mount extension routers on the upstream app. (tool-name aliasing and
# profile-ARN autofetch wrap functions/methods at runtime, so unlike
# role widening they are insensitive to import/registration order.)
install_tool_name_aliasing()
install_cloud_connector()
install_profile_arn_autofetch()
install_control_plane_host_redirect()
install_chat_host_fallback()
# Strip Claude Code's per-request billing-attribution line from the system
# prompt before forwarding to Kiro, so it doesn't poison upstream prompt-cache
# prefixes. Wraps extract_system_prompt() at runtime (order-insensitive).
install_billing_header_strip()
# Ports of the kiro-gateway fork's upstream hardening (61d9b68 / dc0fe43).
# Order matters: the payload builder calls tool_name_alias's wrappers through
# kiro.converters_core, the stream decoder wraps whatever parse_kiro_stream is
# installed (the aliasing one), and client_compat wraps the payload builder's
# route-level anthropic_to_kiro. All of them go after tool-name aliasing.
install_kiro_stream_decoder()
install_kiro_payload_builder()
install_upstream_retry()
install_upstream_account_context()
install_client_compat(app)
# Dash-format Claude model IDs on /v1/models for Claude-family clients. Added as
# a response middleware (Starlette builds the stack lazily at startup, so adding
# it post-import still takes effect) rather than wrapping the already-registered
# route handler.
install_model_id_format(app)
app.include_router(account_router)


def _is_tauri_managed() -> bool:
    return os.getenv("TAURI_MANAGED") == "true"


def _resolve_host_for_tauri(cli_host, env_host: str, default_host: str) -> str:
    """Resolve bind host. CLI > Rust-provided SERVER_HOST > env > default.

    When Tauri-managed, Rust always sets SERVER_HOST explicitly (either
    127.0.0.1 or 0.0.0.0 depending on the user's "Allow LAN Access" toggle),
    so we honor it. Fall back to 127.0.0.1 only if the env var is missing.
    """
    if cli_host is not None:
        return cli_host
    if _is_tauri_managed():
        if os.getenv("SERVER_HOST") is not None:
            return env_host
        return "127.0.0.1"
    if env_host != default_host:
        return env_host
    return default_host


def _run() -> None:
    args = parse_cli_args()
    validate_configuration()

    # Host/port resolution: mostly delegate to upstream, but override host for Tauri.
    cli_host = args.host
    cli_port = args.port
    final_host = _resolve_host_for_tauri(cli_host, SERVER_HOST, DEFAULT_SERVER_HOST)
    if cli_port is not None:
        final_port = cli_port
    elif SERVER_PORT != DEFAULT_SERVER_PORT:
        final_port = SERVER_PORT
    else:
        final_port = DEFAULT_SERVER_PORT

    if _is_tauri_managed():
        # Ready signal for any consumer that watches stdout; Tauri itself polls /health.
        print(f"KIRO_GATEWAY_READY:{final_port}", flush=True)
        logger.info(f"Server ready on port {final_port} (Tauri-managed)")
    else:
        print_startup_banner(final_host, final_port)

    logger.info(f"Starting Uvicorn server on {final_host}:{final_port}...")

    # Patch UVICORN_LOG_CONFIG to reference main.InterceptHandler
    # (upstream already uses "main.InterceptHandler", which is fine since we import main).
    uvicorn.run(
        app,
        host=final_host,
        port=final_port,
        log_config=UVICORN_LOG_CONFIG,
    )


if __name__ == "__main__":
    _run()
