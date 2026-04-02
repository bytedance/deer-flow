"""Shared utilities for channel adapters."""

from __future__ import annotations


# Platform message length limits
TELEGRAM_MAX_LENGTH = 4096
SLACK_MAX_LENGTH = 12000
DISCORD_MAX_LENGTH = 2000
FEISHU_MAX_LENGTH = 30000  # Feishu is generous


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks that fit a platform's character limit.

    Splits at natural boundaries in order of preference:
    1. Paragraph breaks (double newline)
    2. Single newlines
    3. Spaces
    4. Hard cut (last resort)

    Each chunk is stripped of leading/trailing whitespace.

    Args:
        text: The message text to split.
        max_length: Maximum characters per chunk (platform-specific).

    Returns:
        List of message chunks, each within max_length.
    """
    if not text or len(text) <= max_length:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a paragraph break
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at == -1:
            # Try single newline
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            # Try space
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1:
            # Hard cut
            split_at = max_length

        chunk = remaining[:split_at].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    return chunks
