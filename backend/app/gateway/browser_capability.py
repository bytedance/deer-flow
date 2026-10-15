"""Shared browser-control capability checks for Gateway surfaces."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from deerflow.community.browser_automation.session import browser_multi_worker_error
from deerflow.config.app_config import AppConfig


@dataclass(frozen=True)
class BrowserCapability:
    """Frontend/API availability for the agentic browser control surface."""

    configured: bool
    available: bool
    reason: str | None = None


def _tool_config(config: AppConfig) -> Any | None:
    get_tool_config = getattr(config, "get_tool_config", None)
    if callable(get_tool_config) and callable(getattr(type(config), "get_tool_config", None)):
        return get_tool_config("browser_navigate")
    return next(
        (tool for tool in (getattr(config, "tools", None) or []) if getattr(tool, "name", None) == "browser_navigate"),
        None,
    )


def _tool_extra(tool_cfg: Any) -> dict[str, Any]:
    extra = getattr(tool_cfg, "model_extra", None)
    return extra if isinstance(extra, dict) else {}


def browser_capability(config: AppConfig) -> BrowserCapability:
    """Return whether browser control can actually serve frontend requests."""

    tool_cfg = _tool_config(config)
    if tool_cfg is None:
        return BrowserCapability(configured=False, available=False, reason="browser_navigate is not configured")

    worker_error = browser_multi_worker_error()
    if worker_error is not None:
        return BrowserCapability(configured=True, available=False, reason=worker_error)

    extra = _tool_extra(tool_cfg)
    cdp_url = extra.get("cdp_url")
    if isinstance(cdp_url, str) and cdp_url.strip() and extra.get("allow_unguarded_cdp") is not True:
        return BrowserCapability(
            configured=True,
            available=False,
            reason="cdp_url requires allow_unguarded_cdp: true because DeerFlow cannot enforce the SSRF request guard on a CDP-attached browser",
        )

    if importlib.util.find_spec("playwright") is None or importlib.util.find_spec("playwright.async_api") is None:
        return BrowserCapability(
            configured=True,
            available=False,
            reason="Playwright is not installed; install the backend browser extra and run `playwright install chromium`",
        )

    return BrowserCapability(configured=True, available=True)


def ensure_browser_runtime_available(config: AppConfig) -> None:
    """Fail startup when browser control is configured but cannot run."""

    capability = browser_capability(config)
    if capability.configured and not capability.available:
        raise RuntimeError(capability.reason or "Browser automation is not available")
