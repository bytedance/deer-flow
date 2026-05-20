"""Helpers for request-level client context.

The HTTP API accepts a broad ``context`` object for compatibility with
LangGraph SDK clients.  Only a small, explicit subset of client-provided data
should be preserved for runtime use or rendered into model-visible reminders.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from html import escape
from typing import Any

_CLIENT_CONTEXT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_MAX_CLIENT_CONTEXT_ITEMS = 32
_MAX_CLIENT_NAME_LENGTH = 80
_MAX_CLIENT_VALUE_LENGTH = 200

_PROMPT_EMPTY_CLIENT_CONTEXT = "<client_context>not provided</client_context>"


def _clean_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip()
    if not key or not _CLIENT_CONTEXT_KEY_RE.fullmatch(key):
        return None
    return key


def _clean_text(value: Any, *, max_length: int = _MAX_CLIENT_VALUE_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    # Collapse all whitespace so client-provided values cannot introduce
    # prompt structure by adding line breaks or tags across lines.
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > max_length:
        text = text[:max_length]
    return text


def _clean_preference_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _clean_text(value)
    return None


def sanitize_client_context(raw_client: Any) -> dict[str, Any] | None:
    """Return the safe subset of ``context.client`` for runtime use.

    Accepted prompt-visible fields:
    - ``name``: short client identifier
    - ``capabilities``: mapping of capability name to boolean support flag
    - ``preferences``: mapping of preference name to a scalar value

    Unknown keys and nested structures are intentionally dropped.
    """

    if not isinstance(raw_client, Mapping):
        return None

    client: dict[str, Any] = {}

    name = _clean_text(raw_client.get("name"), max_length=_MAX_CLIENT_NAME_LENGTH)
    if name:
        client["name"] = name

    raw_capabilities = raw_client.get("capabilities")
    if isinstance(raw_capabilities, Mapping):
        capabilities: dict[str, bool] = {}
        for raw_key, raw_value in list(raw_capabilities.items())[:_MAX_CLIENT_CONTEXT_ITEMS]:
            key = _clean_key(raw_key)
            if key is None or not isinstance(raw_value, bool):
                continue
            capabilities[key] = raw_value
        if capabilities:
            client["capabilities"] = dict(sorted(capabilities.items()))

    raw_preferences = raw_client.get("preferences")
    if isinstance(raw_preferences, Mapping):
        preferences: dict[str, str | int | float | bool] = {}
        for raw_key, raw_value in list(raw_preferences.items())[:_MAX_CLIENT_CONTEXT_ITEMS]:
            key = _clean_key(raw_key)
            value = _clean_preference_value(raw_value)
            if key is None or value is None:
                continue
            preferences[key] = value
        if preferences:
            client["preferences"] = dict(sorted(preferences.items()))

    return client or None


def _format_prompt_value(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return escape(value, quote=False)
    return str(value)


def render_client_context_for_prompt(raw_client: Any) -> str | None:
    """Render safe client context as a compact model-visible reminder block."""

    client = sanitize_client_context(raw_client)
    if not client:
        return None

    lines = ["<client_context>"]

    name = client.get("name")
    if isinstance(name, str):
        lines.append(f"name: {escape(name, quote=False)}")

    capabilities = client.get("capabilities")
    if isinstance(capabilities, Mapping):
        enabled = sorted(key for key, enabled in capabilities.items() if enabled is True)
        disabled = sorted(key for key, enabled in capabilities.items() if enabled is False)
        if enabled:
            lines.append(f"capabilities: {', '.join(enabled)}")
        if disabled:
            lines.append(f"unsupported_capabilities: {', '.join(disabled)}")

    preferences = client.get("preferences")
    if isinstance(preferences, Mapping):
        rendered = [f"{key}={_format_prompt_value(value)}" for key, value in preferences.items() if isinstance(value, (str, int, float, bool))]
        if rendered:
            lines.append(f"preferences: {'; '.join(rendered)}")

    lines.append("</client_context>")
    return "\n".join(lines)


def render_empty_client_context_for_prompt() -> str:
    """Render an explicit reminder that no client context is active."""

    return _PROMPT_EMPTY_CLIENT_CONTEXT
