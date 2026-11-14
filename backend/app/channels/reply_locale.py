"""Language and wording of the replies DeerFlow itself writes in IM chats.

Host replies (the ``/connect`` handshake below, ``/goal`` in
``goal_status.py``) use the binding owner's web UI language (the ``locale``
user preference, which the web app keeps in sync), else
``channel_connections.notification_locale``, else en-US: the same order as
scheduled-task notices. A reply with no known owner, such as one to an invalid
or expired code, uses the configured default. Agent output is never translated.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.scheduler.notification_text import DEFAULT_NOTIFICATION_LOCALE, NOTIFICATION_LOCALES
from deerflow.persistence.user.preferences import UserPreferencesRepository

logger = logging.getLogger(__name__)


def supported_locale(value: object, default: str = DEFAULT_NOTIFICATION_LOCALE) -> str:
    """``value`` when it is a supported reply language, else ``default``."""
    return value if isinstance(value, str) and value in NOTIFICATION_LOCALES else default


async def resolve_reply_locale(owner_user_id: str | None, *, session_factory: Any | None, default_locale: str = DEFAULT_NOTIFICATION_LOCALE) -> str:
    """The owner's web UI language, else ``default_locale``, else en-US.

    Never raises: without an owner or a database the default applies, and a
    failed read is logged and falls back, so a reply is never lost to it.
    """
    default = supported_locale(default_locale)
    if not owner_user_id or session_factory is None:
        return default
    try:
        locale = (await UserPreferencesRepository(session_factory).get(owner_user_id)).get("locale")
    except Exception:
        logger.warning("Could not read the owner's language preference; replying in %s", default, exc_info=True)
        return default
    return supported_locale(locale, default)


@dataclass(frozen=True)
class ReplyLocaleResolver:
    """``resolve_reply_locale`` bound to the shared database and the configured default.

    ``ChannelService`` builds one for its manager and every channel it starts;
    a manager or channel built without one replies in en-US.
    """

    session_factory: Any | None = None
    default_locale: str = DEFAULT_NOTIFICATION_LOCALE

    async def locale_for(self, owner_user_id: str | None) -> str:
        return await resolve_reply_locale(owner_user_id, session_factory=self.session_factory, default_locale=self.default_locale)


# Platform names in replies; zh-CN uses the web UI's Chinese names where it has them.
_PROVIDER_NAMES: dict[str, dict[str, str]] = {
    "en-US": {
        "buzz": "Buzz",
        "dingtalk": "DingTalk",
        "discord": "Discord",
        "feishu": "Feishu",
        "qq": "QQ",
        "slack": "Slack",
        "telegram": "Telegram",
        "wechat": "WeChat",
        "wecom": "WeCom",
    },
    "zh-CN": {"dingtalk": "钉钉", "feishu": "飞书", "wechat": "微信", "wecom": "企业微信"},
}

# Replies to ``/connect <code>`` (Telegram: the ``/start <code>`` deep link).
# ``{provider}`` is the platform's name. The English wording predates the table.
CONNECT_REPLY_TEXT: dict[str, dict[str, str]] = {
    "en-US": {
        "connected": "{provider} connected to DeerFlow.",
        "invalid_code": "{provider} connection code is invalid or expired.",
        "invalid_link": "{provider} connection link is invalid or expired.",
        "incomplete": "{provider} connection could not be completed from this message.",
        "private_chat_only": "Please send the connection code in a private chat with the bot.",
    },
    "zh-CN": {
        "connected": "{provider} 已连接到 DeerFlow。",
        "invalid_code": "{provider} 绑定码无效或已过期。",
        "invalid_link": "{provider} 绑定链接无效或已过期。",
        "incomplete": "无法通过这条消息完成 {provider} 绑定。",
        "private_chat_only": "请在与机器人的私聊中发送绑定码。",
    },
}

_LATIN_NAME = re.compile(r"[A-Za-z0-9]")


def connect_reply_text(key: str, *, provider: str, locale: str) -> str:
    """The ``key`` reply for ``provider`` (a channel name such as ``feishu``) in ``locale``."""
    locale = supported_locale(locale)
    name = _PROVIDER_NAMES[locale].get(provider) or _PROVIDER_NAMES[DEFAULT_NOTIFICATION_LOCALE].get(provider) or provider
    template = CONNECT_REPLY_TEXT[locale][key]
    if not _LATIN_NAME.match(name):
        # As on the web: a Latin name keeps its spaces ("Slack 已连接"), a Chinese one does not ("飞书已连接").
        template = template.replace(" {provider}", "{provider}").replace("{provider} ", "{provider}")
    return template.format(provider=name)
