"""Static per-provider channel capabilities.

Dependency-free on purpose: the scheduler and the Settings API read it without
importing any channel SDK. ``tests/test_channel_capabilities.py`` keeps it in
sync with the channel registry and the channel classes.

- ``supports_streaming``: the fallback the channel manager uses when no live
  channel instance is running (a running channel answers for itself).
- ``proactive_notifications``: the provider's channel class implements
  ``Channel.send_notification`` (push with no inbound message to reply to).
  Only these providers get scheduled-task notification rows; to add one, see
  the ``Channel.send_notification`` docstring.
"""

from __future__ import annotations

CHANNEL_CAPABILITIES: dict[str, dict[str, bool]] = {
    "buzz": {"supports_streaming": True, "proactive_notifications": False},
    "dingtalk": {"supports_streaming": False, "proactive_notifications": False},
    "discord": {"supports_streaming": False, "proactive_notifications": False},
    "feishu": {"supports_streaming": True, "proactive_notifications": False},
    "github": {"supports_streaming": False, "proactive_notifications": False},
    "qq": {"supports_streaming": False, "proactive_notifications": False},
    "slack": {"supports_streaming": False, "proactive_notifications": False},
    "telegram": {"supports_streaming": True, "proactive_notifications": False},
    "wechat": {"supports_streaming": False, "proactive_notifications": False},
    "wecom": {"supports_streaming": True, "proactive_notifications": True},
}


def supports_proactive_notifications(provider: str) -> bool:
    """Whether scheduled-task notices can be pushed to ``provider`` (unknown provider: False)."""
    entry = CHANNEL_CAPABILITIES.get(provider) if isinstance(provider, str) else None
    return bool(entry) and entry.get("proactive_notifications") is True
