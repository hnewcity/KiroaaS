"""Truthful gateway client identification without fabricated IDE/SDK versions."""

from functools import lru_cache
import json
import os
from pathlib import Path
import re

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")


@lru_cache(maxsize=1)
def _source_version() -> str:
    """Read the owned development manifest; frozen builds use the launch env."""
    manifest = Path(__file__).resolve().parents[2] / "package.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unversioned"
    version = data.get("version") if isinstance(data, dict) and data.get("name") == "kiroaas" else None
    return version if isinstance(version, str) and _VERSION.fullmatch(version) else "unversioned"


def application_version() -> str:
    """Use a validated actual launch version, never pretend to be the official CLI."""
    value = os.getenv("KIROAAS_APP_VERSION") or _source_version()
    if not _VERSION.fullmatch(value):
        raise ValueError("KIROAAS_APP_VERSION must be an ASCII version token")
    return value


def user_agent() -> str:
    """Return the identification shared by inference, control-plane, and auth."""
    return "KiroaaS/" + application_version()
