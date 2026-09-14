"""Shared redaction primitives for bearer credentials that can reach telemetry."""

from __future__ import annotations

import re

# Conversation-share tokens ride in URLs. A complete token has exactly 43
# urlsafe body characters, so that shape is detected even when an attacker
# prepends another word character (``xdfs_...``); the credential beginning at
# the second character remains usable. Short/truncated bodies are also masked
# when they have a real left boundary. Both branches recognize percent-encoded
# prefix/body characters because raw request lines may retain that encoding.
SHARE_TOKEN_PATTERN = re.compile(
    r"(?:"
    r"(?P<full>(?:d|%64)(?:f|%66)(?:s|%73)(?:_|%5[fF])"
    r"(?=(?:(?:[A-Za-z0-9_-]|%[0-9A-Fa-f]{2})){43})"
    r"(?:[A-Za-z0-9_-]|%[0-9A-Fa-f]{2})+)"
    r"|"
    r"(?P<boundary>^|[^A-Za-z0-9_-]|%[0-9A-Fa-f]{2})"
    r"(?P<fragment>(?:d|%64)(?:f|%66)(?:s|%73)(?:_|%5[fF])"
    r"(?:[A-Za-z0-9_-]|%[0-9A-Fa-f]{2})+)"
    r")",
    re.IGNORECASE,
)
SHARE_TOKEN_REDACTION_MASK = "dfs_***"


def redact_share_tokens(value: str) -> str:
    """Mask conversation-share bearer tokens in *value*."""
    if "dfs_" not in value.lower() and "%" not in value:
        return value
    return SHARE_TOKEN_PATTERN.sub(
        lambda match: f"{match.group('boundary') or ''}{SHARE_TOKEN_REDACTION_MASK}",
        value,
    )


def contains_share_token(value: str) -> bool:
    """Return whether *value* contains a conversation-share bearer token."""
    return ("dfs_" in value.lower() or "%" in value) and SHARE_TOKEN_PATTERN.search(value) is not None
