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
