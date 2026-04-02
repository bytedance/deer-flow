"""Shared agent identity rules for internal slugs and user-visible names."""

from __future__ import annotations

import hashlib
import re
import unicodedata

DISPLAY_NAME_MAX_LENGTH = 80
AGENT_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")
_ASCII_SLUG_CHUNK_RE = re.compile(r"[^a-z0-9]+")


def normalize_agent_display_name(value: str) -> str:
    """Normalize a user-visible agent name for validation and comparisons."""
    return unicodedata.normalize("NFKC", value).strip()


def display_name_key(value: str) -> str:
    """Return a normalized key for display-name uniqueness checks."""
    return normalize_agent_display_name(value).casefold()


def validate_agent_display_name(value: str) -> str:
    """Validate and return a normalized user-visible agent name."""
    normalized = normalize_agent_display_name(value)
    if not normalized:
        raise ValueError("Agent display name cannot be empty.")
    if len(normalized) > DISPLAY_NAME_MAX_LENGTH:
        raise ValueError(f"Agent display name must be at most {DISPLAY_NAME_MAX_LENGTH} characters.")
    if any(ch in {"/", "\\"} for ch in normalized):
        raise ValueError("Agent display name cannot contain '/' or '\\'.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized):
        raise ValueError("Agent display name cannot contain control characters.")
    return normalized


def normalize_agent_slug(value: str) -> str:
    """Normalize an internal slug used in routes and filesystem paths."""
    return value.strip().lower()


def validate_agent_slug(value: str) -> str:
    """Validate and return a normalized internal agent slug."""
    normalized = normalize_agent_slug(value)
    if not AGENT_SLUG_PATTERN.fullmatch(normalized):
        raise ValueError("Agent slug must contain only lowercase letters, digits, and hyphens.")
    return normalized


def is_valid_agent_slug(value: str) -> bool:
    """Check whether a string is already a valid internal slug."""
    try:
        validate_agent_slug(value)
    except ValueError:
        return False
    return True


def build_agent_slug(display_name: str) -> str:
    """Build a deterministic ASCII slug from a display name."""
    normalized_display_name = validate_agent_display_name(display_name)
    ascii_slug = _ASCII_SLUG_CHUNK_RE.sub("-", normalized_display_name.lower()).strip("-")
    if ascii_slug:
        return ascii_slug
    digest = hashlib.sha1(normalized_display_name.encode("utf-8")).hexdigest()[:10]
    return f"agent-{digest}"


def build_unique_agent_slug(
    display_name: str,
    existing_slugs: set[str],
    explicit_slug: str | None = None,
) -> str:
    """Build a stable slug that does not collide with existing slugs."""
    base_slug = validate_agent_slug(explicit_slug) if explicit_slug is not None else build_agent_slug(display_name)
    if base_slug not in existing_slugs:
        return base_slug

    suffix = hashlib.sha1(validate_agent_display_name(display_name).encode("utf-8")).hexdigest()[:6]
    candidate = f"{base_slug}-{suffix}"
    if candidate not in existing_slugs:
        return candidate

    counter = 2
    while True:
        numbered = f"{candidate}-{counter}"
        if numbered not in existing_slugs:
            return numbered
        counter += 1
