"""Shared command definitions used by all channel implementations.

Keeping the authoritative command set in one place ensures that channel
parsers (e.g. Feishu) and the ChannelManager dispatcher stay in sync
automatically — adding or removing a command here is the single edit
required.
"""

from __future__ import annotations

KNOWN_CHANNEL_COMMANDS: frozenset[str] = frozenset(
    {
        "/bootstrap",
        "/goal",
        "/new",
        "/status",
        "/models",
        "/memory",
        "/help",
    }
)


def _is_leading_mention_token(token: str) -> bool:
    """Return whether *token* looks like a platform bot/user mention.

    Group chats often require ``@bot`` before the message is delivered. Slack
    and Discord strip those tokens before connect parsing; Feishu / DingTalk
    leave them in the text (``@_user_1``, ``@bot``, ``<@id>``). Treat them as
    transport noise only when they lead the message so
    ``@bot /connect <code>`` still binds.
    """
    if not token:
        return False
    # Slack / Discord style: <@U123> or <@!U123> or <@U123|name>
    if token.startswith("<@") and token.endswith(">"):
        return True
    # Feishu / DingTalk / generic: @_user_1, @bot, @nickname
    if token.startswith("@") and len(token) > 1:
        return True
    return False


def strip_leading_mentions(text: str) -> str:
    """Drop leading platform mention tokens (``@bot``, ``<@id>``) so a group-chat
    ``@bot /goal`` reads as ``/goal`` for command classification and dispatch.

    A mention must be flush at the start (no preceding whitespace), mirroring the
    "a control command must be at position 0" rule in :func:`is_known_channel_command`:
    text with a leading space or no leading mention is returned unchanged, so
    ``" /new"`` stays a non-command. Whitespace is otherwise preserved (unlike
    :func:`extract_connect_code`, which is deliberately whitespace-lenient for the
    bind path). Channels that resolve their own bot id (Slack/Discord) strip only
    the bot's mention upstream; this is for adapters that leave the mention in the
    text and cannot tell the bot's mention from another user's (Feishu/DingTalk).
    """
    remainder = text
    while True:
        parts = remainder.split(maxsplit=1)
        if not parts or remainder[0].isspace() or not _is_leading_mention_token(parts[0]):
            break
        remainder = parts[1] if len(parts) > 1 else ""
    return remainder


def extract_connect_code(text: str) -> str | None:
    """Extract the one-time channel binding code from a connect command.

    Accepts a leading platform mention so group ``@bot /connect <code>``
    messages bind the same way as bare ``/connect <code>`` (Slack/Discord
    already strip mentions before calling this helper).
    """
    parts = text.strip().split()
    index = 0
    while index < len(parts) and _is_leading_mention_token(parts[index]):
        index += 1
    if index + 1 >= len(parts):
        return None
    command = parts[index].lower()
    if command in {"/connect", "connect"}:
        return parts[index + 1]
    return None


def is_known_channel_command(text: str) -> bool:
    """Return whether text starts with a registered channel control command."""
    if not text.startswith("/"):
        return False
    return text.split(maxsplit=1)[0].lower() in KNOWN_CHANNEL_COMMANDS
