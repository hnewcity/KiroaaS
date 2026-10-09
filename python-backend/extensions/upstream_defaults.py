"""
Default values for upstream settings, ported from the kiro-gateway fork.

The fork changed these defaults in kiro/config.py (commits f27e12a, b664610):

- FIRST_TOKEN_TIMEOUT 15 -> 60: reasoning models can take well over 15s to emit
  a first token on long prompts, and each premature cancel re-sends the whole
  prompt upstream, adding load instead of recovering from it.
- STREAMING_READ_TIMEOUT 300 -> 120: an upstream silent for two minutes
  mid-stream is not coming back; waiting five minutes only turns a fast failure
  into a hang the client cannot retry around.
- FIRST_TOKEN_MAX_RETRIES 3 -> 2: every attempt re-sends the full prompt.
- WEB_SEARCH_ENABLED true -> false: stop auto-injecting the emulated web_search
  tool. Native Anthropic server-side web search still works.

kiro/config.py reads these at import time, so this must run before anything
imports kiro (app_entry calls it first). Values are only defaulted: anything set
in the environment or in .env wins. Under Tauri, FIRST_TOKEN_TIMEOUT and
STREAMING_READ_TIMEOUT always come from the app settings (src-tauri config.rs).
"""

import os

from dotenv import load_dotenv


UPSTREAM_DEFAULTS = {
    "FIRST_TOKEN_TIMEOUT": "60",
    "STREAMING_READ_TIMEOUT": "120",
    "FIRST_TOKEN_MAX_RETRIES": "2",
    "WEB_SEARCH_ENABLED": "false",
}


def apply_upstream_defaults() -> None:
    """Default the fork's settings in os.environ without overriding user values."""
    # Load .env first so its values count as "set by the user"; kiro/config.py's
    # own load_dotenv() later is a no-op for keys that already exist.
    load_dotenv()
    for key, value in UPSTREAM_DEFAULTS.items():
        os.environ.setdefault(key, value)
