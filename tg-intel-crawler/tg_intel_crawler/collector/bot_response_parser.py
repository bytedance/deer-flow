"""Parse a search-bot reply into BotPreview entries.

A typical @JISOU reply (see screenshot) looks like:

    广告:南宫 集团🔥...                       ← ad row, drop
    🌄 X刀！... https://t.me/chan/12345         ← preview with deeplink
    🌄 ... https://t.me/another/9876
    🎬 [00:09] 赏_好身材...
    💬 你们把我当抖加                         ← preview with no link
    📂 版本_百分之一百不禁网...

Parsing strategy:
- Skip lines starting with '广告:' or '广告：'.
- Each line whose first non-whitespace char is a known result-icon emoji
  (🌄 🎬 💬 📂 📁 📄 etc.) starts a new preview.
- Pull the FIRST t.me/<channel>/<msg_id> deeplink as the message anchor;
  if none, fall back to t.me/<channel> as a channel-level signal;
  invite links (t.me/+...) do NOT become message anchors but stay in raw_line.
- If the entire reply has zero emoji-prefixed lines, wrap the whole text
  as a single preview rather than dropping the bot's response on the floor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone


# Result-icon emojis @JISOU and similar bots use to lead each result row.
# We accept any character classified as Symbol-Other or Pictograph at line
# start, but listing the common ones here makes the rules explicit and
# unicode-property regex is awkward.
_KNOWN_ICONS = "🌄🎬💬📂📁📄🎵🎤📺🔞🔥📌📎🌟🎁📷🖼📸🎯🎫🎪🎨"

_AD_PREFIXES = ("广告:", "广告：")

_T_ME_MSG_RE = re.compile(
    r"https?://t\.me/([A-Za-z][A-Za-z0-9_]{4,31})/(\d+)(?![\d/])"
)
_T_ME_CHANNEL_ONLY_RE = re.compile(
    r"https?://t\.me/([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_/])"
)


@dataclass
class BotPreview:
    bot: str                       # which bot replied, e.g. "@JISOU"
    query: str                     # the keyword we asked
    raw_line: str                  # the original line as received
    text: str                      # cleaned text portion (for LLM/storage)
    deeplink: str | None           # https://t.me/<channel>[/msg_id] — None for plain previews
    channel_username: str | None   # extracted public username, if any
    msg_id: int | None             # extracted msg_id (only for /<channel>/<msg_id> form)
    icon: str | None               # leading emoji icon, for debug
    seen_at: datetime              # parse time


def _is_icon_start(line: str) -> str | None:
    """Return the icon char if this line starts with a known result icon."""
    stripped = line.lstrip()
    if not stripped:
        return None
    first = stripped[0]
    if first in _KNOWN_ICONS:
        return first
    return None


class BotResponseParser:
    """Pure parser — no I/O, no Telethon."""

    def parse(self, reply_text: str, *, query: str, bot: str) -> list[BotPreview]:
        if not reply_text or not reply_text.strip():
            return []

        now = datetime.now(timezone.utc)

        # 1. Pre-filter ads.
        lines = [
            line for line in reply_text.splitlines()
            if not any(line.lstrip().startswith(p) for p in _AD_PREFIXES)
        ]

        # 2. Walk lines, group icon-led ones into individual previews.
        previews: list[BotPreview] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            icon = _is_icon_start(line)
            if icon is None:
                continue  # plain narrator/header text — skip
            content = stripped[len(icon):].strip()
            if not content:
                continue  # bare icon, no actual content
            previews.append(self._build_preview(
                line=stripped,
                content=content,
                icon=icon,
                query=query,
                bot=bot,
                seen_at=now,
            ))

        # 3. Fallback: if no icon-led line existed but bot did reply, keep one
        #    preview so the data isn't lost.
        if not previews:
            collapsed = "\n".join(line.strip() for line in lines if line.strip())
            if collapsed:
                previews.append(self._build_preview(
                    line=collapsed,
                    content=collapsed,
                    icon=None,
                    query=query,
                    bot=bot,
                    seen_at=now,
                ))

        return previews

    @staticmethod
    def _build_preview(
        *, line: str, content: str, icon: str | None,
        query: str, bot: str, seen_at: datetime,
    ) -> BotPreview:
        # Try a message-level deeplink first (channel + msg_id); fall back to
        # channel-only link for candidate-pool purposes.
        m_msg = _T_ME_MSG_RE.search(line)
        if m_msg:
            channel = m_msg.group(1)
            msg_id = int(m_msg.group(2))
            deeplink = f"https://t.me/{channel}/{msg_id}"
        else:
            m_chan = _T_ME_CHANNEL_ONLY_RE.search(line)
            if m_chan:
                channel = m_chan.group(1)
                msg_id = None
                deeplink = f"https://t.me/{channel}"
            else:
                channel = None
                msg_id = None
                deeplink = None

        return BotPreview(
            bot=bot,
            query=query,
            raw_line=line,
            text=content,
            deeplink=deeplink,
            channel_username=channel,
            msg_id=msg_id,
            icon=icon,
            seen_at=seen_at,
        )
