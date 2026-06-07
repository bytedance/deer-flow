"""Extract candidate group signals from Telegram messages.

Pure functions over MessageData-like objects: scan the text/entities/
forward fields and return CandidateSignal dicts. No I/O, no Telethon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


# Reserved Telegram paths that look like usernames in URLs but aren't.
_RESERVED_USERNAMES: frozenset[str] = frozenset({
    "joinchat", "addstickers", "share", "addtheme", "iv", "proxy", "socks",
    "c", "addemoji", "telegram", "telegrambot",
})

# Telegram username rule: 5-32 chars, starts with letter, [A-Za-z0-9_]
# (we enforce 5-32 explicitly so "@abc" doesn't sneak through).
_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_])")

# Public link: https://t.me/<username>[/12345]
_T_ME_USERNAME_RE = re.compile(
    r"https?://t\.me/([A-Za-z][A-Za-z0-9_]{4,31})(?:/\d+)?(?![A-Za-z0-9_])"
)

# Modern invite: https://t.me/+<hash>
_T_ME_INVITE_PLUS_RE = re.compile(r"https?://t\.me/\+([A-Za-z0-9_\-]+)")

# Legacy invite: https://t.me/joinchat/<hash>
_T_ME_INVITE_JOINCHAT_RE = re.compile(r"https?://t\.me/joinchat/([A-Za-z0-9_\-]+)")


@dataclass
class CandidateSignal:
    """A single 'this group exists' signal extracted from a message."""

    username: str | None      # public group/channel username (lowercased)
    invite_hash: str | None   # private group invite hash (case preserved)
    channel: str              # how it was found: text / forward / entity / bio
    source_group: str         # group the signal was seen in
    source_msg_id: int
    seen_at: datetime

    @property
    def key(self) -> str:
        """Stable identifier — used by CandidatePool for dedupe."""
        if self.username:
            return self.username
        return f"+{self.invite_hash}"


class GroupExtractor:
    """Pull candidate group references out of messages."""

    def extract_from(self, messages: Iterable) -> list[CandidateSignal]:
        signals: list[CandidateSignal] = []
        for msg in messages:
            signals.extend(self._extract_one(msg))
        return signals

    def _extract_one(self, msg) -> list[CandidateSignal]:
        text: str = getattr(msg, "text", "") or ""
        source_group: str = getattr(msg, "group_name", "") or ""
        source_msg_id: int = getattr(msg, "msg_id", 0) or 0
        seen_at: datetime = getattr(msg, "date", None) or datetime.utcnow()

        # Use a dict keyed by stable identifier so we dedupe within a message.
        found: dict[str, CandidateSignal] = {}

        def _add(username: str | None, invite_hash: str | None, channel: str) -> None:
            if username:
                # Skip if this signal points back to its own source group.
                if username.lower() == source_group.lower():
                    return
                key = username.lower()
                if key not in found:
                    found[key] = CandidateSignal(
                        username=username.lower(),
                        invite_hash=None,
                        channel=channel,
                        source_group=source_group,
                        source_msg_id=source_msg_id,
                        seen_at=seen_at,
                    )
            elif invite_hash:
                key = f"+{invite_hash}"
                if key not in found:
                    found[key] = CandidateSignal(
                        username=None,
                        invite_hash=invite_hash,
                        channel=channel,
                        source_group=source_group,
                        source_msg_id=source_msg_id,
                        seen_at=seen_at,
                    )

        # 1. Invite links — try first so /joinchat/ and /+ aren't shadowed by
        #    the bare username matcher.
        for m in _T_ME_INVITE_PLUS_RE.finditer(text):
            _add(None, m.group(1), "text")
        for m in _T_ME_INVITE_JOINCHAT_RE.finditer(text):
            _add(None, m.group(1), "text")

        # 2. Public t.me links → username (skip reserved paths).
        for m in _T_ME_USERNAME_RE.finditer(text):
            uname = m.group(1)
            if uname.lower() in _RESERVED_USERNAMES:
                continue
            _add(uname, None, "text")

        # 3. Bare @mentions (skip reserved).
        for m in _USERNAME_RE.finditer(text):
            uname = m.group(1)
            if uname.lower() in _RESERVED_USERNAMES:
                continue
            _add(uname, None, "text")

        # 4. Forwarded-from username, if MessageData provides it.
        fwd = getattr(msg, "forward_from_username", None)
        if fwd:
            _add(fwd, None, "forward")

        return list(found.values())
