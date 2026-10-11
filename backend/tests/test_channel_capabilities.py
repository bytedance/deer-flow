"""The static channel capability table stays in sync with the channel code.

The scheduler and the Settings page read ``proactive_notifications`` from
``app.channels.capabilities`` without importing channel SDKs, so these tests
pin that table to the channel registry and to the channel classes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.channels.base import Channel
from app.channels.capabilities import CHANNEL_CAPABILITIES, supports_proactive_notifications
from app.channels.service import _CHANNEL_REGISTRY
from deerflow.reflection import resolve_class

_BACKEND_DIR = Path(__file__).resolve().parents[1]
# Third-party modules the channel implementations import at module level.
_CHANNEL_SDK_MODULES = ("lark_oapi", "slack_sdk", "telegram", "discord", "dingtalk_stream", "aibot", "websockets", "cryptography", "markdown_to_mrkdwn")


def test_capabilities_cover_channel_registry():
    # A provider registered without a capability entry (as qq once was) fails here.
    assert set(CHANNEL_CAPABILITIES) == set(_CHANNEL_REGISTRY)
    assert CHANNEL_CAPABILITIES["qq"]["proactive_notifications"] is False


def test_every_entry_declares_both_flags_as_bools():
    for provider, entry in CHANNEL_CAPABILITIES.items():
        assert set(entry) == {"supports_streaming", "proactive_notifications"}, provider
        assert all(isinstance(value, bool) for value in entry.values()), provider


def test_only_wecom_pushes_proactively_today():
    assert {provider for provider, entry in CHANNEL_CAPABILITIES.items() if entry["proactive_notifications"]} == {"wecom"}
    assert supports_proactive_notifications("wecom") is True
    assert supports_proactive_notifications("feishu") is False


@pytest.mark.parametrize("provider", ["", "unknown", "WeCom", None, 1])
def test_unknown_provider_has_no_proactive_push(provider):
    assert supports_proactive_notifications(provider) is False


def _missing_optional_module(exc: BaseException) -> str | None:
    """The third-party module a resolution failure is missing, or None for any other failure."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ModuleNotFoundError):
            name = current.name or ""
            return name if name and name != "app" and not name.startswith("app.") else None
        current = current.__cause__ or current.__context__
    return None


@pytest.mark.parametrize("provider", sorted(CHANNEL_CAPABILITIES))
def test_proactive_flag_matches_send_notification_override(provider):
    # Resolved exactly as the channel service starts a channel.
    try:
        cls = resolve_class(_CHANNEL_REGISTRY[provider], base_class=None)
    except ImportError as exc:
        missing = _missing_optional_module(exc)
        if missing is None or provider == "wecom":
            # wecom imports no SDK at module level, so it must always resolve.
            raise
        pytest.skip(f"{provider}: optional SDK {missing} not installed")
    overrides = cls.send_notification is not Channel.send_notification
    assert CHANNEL_CAPABILITIES[provider]["proactive_notifications"] is overrides


def test_importing_capabilities_loads_no_channel_sdk():
    code = (
        "import sys\n"
        "import app.channels.capabilities\n"
        f"sdk = {_CHANNEL_SDK_MODULES!r}\n"
        f"providers = {tuple(sorted(_CHANNEL_REGISTRY))!r}\n"
        "loaded = sorted(name for name in sys.modules if name.split('.')[0] in sdk or name in {'app.channels.' + p for p in providers})\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""


def test_qq_streaming_is_unchanged_by_its_new_entry():
    from app.channels.manager import ChannelManager

    # No running channel service: the manager falls back to the static table,
    # which says False for qq, as the missing entry did before.
    assert ChannelManager._channel_supports_streaming("qq") is False
