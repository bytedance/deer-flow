"""Process-wide Python startup customizations for local development."""

from __future__ import annotations

import asyncio
import sys


def _configure_windows_event_loop_policy() -> None:
    if sys.platform != "win32":
        return

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return

    if not isinstance(asyncio.get_event_loop_policy(), selector_policy):
        asyncio.set_event_loop_policy(selector_policy())


_configure_windows_event_loop_policy()
