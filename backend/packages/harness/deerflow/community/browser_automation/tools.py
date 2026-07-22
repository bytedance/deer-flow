"""Agentic browser tools — a stateful navigate → observe → act loop.

Unlike the read-only ``web_fetch`` / ``web_capture`` tools, these keep a live
per-thread browser session (see :mod:`.session`) so the agent can click, type,
submit forms, and follow multi-step flows on JavaScript-heavy or authenticated
pages. Every action returns a fresh page snapshot whose interactive elements are
addressed by a stable ``[ref]`` index, so the model acts on what it just
observed instead of guessing selectors.

All URLs are SSRF-screened with the shared :func:`validate_public_http_url`
helper (opt-out only for intentional internal targets).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.community.url_safety import resolve_host_addresses as _resolve_host_addresses
from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.constants import BROWSER_FRAMES_DIRNAME
from deerflow.tools.types import Runtime

from .session import BrowserSession, BrowserSessionManager, PageSnapshot, get_browser_session_manager

logger = logging.getLogger(__name__)

_OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"
# Auto-captured per-step screenshots are live progress feedback (shown in the
# browser panel + inline thumbnails), not deliverables. Keep them in a hidden
# subdir so the workspace-changes review does not list them as file changes.
# The dir name is a shared constant so the scanner's ignore list cannot drift.
_BROWSER_FRAMES_DIRNAME = BROWSER_FRAMES_DIRNAME
_FRAMES_VIRTUAL_PREFIX = f"{_OUTPUTS_VIRTUAL_PREFIX}/{_BROWSER_FRAMES_DIRNAME}"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _get_tool_config(tool_name: str) -> dict:
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        return {}
    return config.model_extra or {}


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _thread_id(runtime: Runtime) -> str | None:
    return runtime.context.get("thread_id") if runtime.context else None


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


class _SessionLease:
    """Context manager that keeps a process-local browser session pinned."""

    def __init__(self, manager: BrowserSessionManager, thread_id: str | None, session: BrowserSession) -> None:
        self._manager = manager
        self._thread_id = thread_id
        self.session = session

    def __enter__(self) -> BrowserSession:
        return self.session

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._manager.release_session(self._thread_id, self.session)


def _resolve_session(runtime: Runtime, tool_name: str) -> _SessionLease:
    # Launch config (headless/viewport/timeout/cdp_url) is read from a single
    # canonical source — always ``browser_navigate`` — regardless of which tool
    # first creates the session. ``get_session`` caches per thread and ignores
    # these params for later callers, so keying launch config off the calling
    # tool made it "first tool to run wins": a ``headless: false`` set only on
    # ``browser_navigate`` was silently dropped if another tool (or the live WS)
    # initialized the session first. ``tool_name`` is retained for callers that
    # read their own non-launch config (e.g. ``browser_get_text``'s max_chars).
    del tool_name
    cfg = _get_tool_config("browser_navigate")
    headless = _as_bool(cfg.get("headless"), True)
    timeout_ms = _as_int(cfg.get("timeout_ms"), 30000)
    width = _as_int(cfg.get("viewport_width"), 1280)
    height = _as_int(cfg.get("viewport_height"), 720)
    cdp_url = _as_str(cfg.get("cdp_url"))
    manager = get_browser_session_manager()
    thread_id = _thread_id(runtime)
    session = manager.get_session(
        thread_id,
        headless=headless,
        timeout_ms=timeout_ms,
        viewport={"width": width, "height": height},
        cdp_url=cdp_url,
        allow_unguarded_cdp=_as_bool(cfg.get("allow_unguarded_cdp"), False),
        url_guard=validate_browser_url,
        pin=True,
    )
    return _SessionLease(manager, thread_id, session)


def validate_browser_url(url: str, *, tool_name: str = "browser_navigate") -> str | None:
    """SSRF-screen a browser navigation URL using the tool's config policy.

    Returns an ``"Error: ..."`` string when the URL must be rejected, or ``None``
    when navigation may proceed. Shared by the agent tools and the Gateway live
    stream so every path that can steer the browser enforces the same allow/deny
    policy (``allow_private_addresses`` from the ``browser_navigate`` tool config).
    """
    cfg = _get_tool_config(tool_name)
    allow_private = _as_bool(cfg.get("allow_private_addresses"), False)
    return validate_public_http_url(
        url,
        allow_private_addresses=allow_private,
        action="browse",
        resolver=_resolve_host_addresses,
    )


def _validate_url(tool_name: str, url: str) -> str | None:
    return validate_browser_url(url, tool_name=tool_name)


def _snapshot_message(snapshot: PageSnapshot, prefix: str = "") -> str:
    body = snapshot.render()
    return f"{prefix}\n\n{body}" if prefix else body


def _tool_message(content: str, tool_call_id: str) -> Command:
    return Command(update={"messages": [ToolMessage(content, tool_call_id=tool_call_id)]})


def _step_screenshot_name(action: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    safe = _SAFE_FILENAME_RE.sub("_", action).strip("._-") or "step"
    return f"browser-{safe}-{stamp}.png"


async def _capture_step_screenshot(runtime: Runtime, session: BrowserSession, action: str) -> str | None:
    """Best-effort per-action screenshot saved as hidden live-progress feedback.

    Returns the artifact virtual path (under the hidden ``.browser-frames`` dir so
    it stays out of the workspace-changes review), or ``None`` when outputs are
    unavailable or capture fails — a failed capture must never break the action.
    """
    outputs_path = _thread_outputs_path(runtime)
    if isinstance(outputs_path, str):
        return None
    try:
        content = await session.screenshot_bytes(full_page=False)
        name = _step_screenshot_name(action)
        frames_dir = outputs_path / _BROWSER_FRAMES_DIRNAME
        final_name = await asyncio.to_thread(_write_screenshot, frames_dir, name, content)
        with contextlib.suppress(Exception):
            session.schedule_live_frames()
        return f"{_FRAMES_VIRTUAL_PREFIX}/{final_name}"
    except Exception as e:
        logger.warning(f"browser step screenshot failed: {e}")
        return None


def _snapshot_command(
    runtime: Runtime,
    session: BrowserSession,
    snapshot: PageSnapshot,
    tool_call_id: str,
    prefix: str,
    screenshot_path: str | None,
) -> Command:
    """Build a ToolMessage carrying the text snapshot plus an inline screenshot.

    The screenshot rides both as a thread ``artifacts`` entry (so it opens in the
    artifacts side panel) and on ``ToolMessage.additional_kwargs.browser_view``
    (so the chat can render an inline thumbnail per browser step).
    """
    text = _snapshot_message(snapshot, prefix)
    additional_kwargs: dict = {}
    update: dict = {}
    if screenshot_path:
        additional_kwargs["browser_view"] = {"screenshot": screenshot_path, "url": snapshot.url, "title": snapshot.title}
        update["artifacts"] = [screenshot_path]
    update["messages"] = [ToolMessage(text, tool_call_id=tool_call_id, additional_kwargs=additional_kwargs)]
    return Command(update=update)


async def navigate_and_capture(*, thread_id: str | None, url: str, outputs_path: Path) -> dict:
    """Drive the per-thread browser session to *url* and capture a screenshot.

    Used by the Gateway browser router so a user can steer the live session from
    the UI URL bar. Shares the same per-thread session, SSRF policy, and
    screenshot pipeline as :func:`browser_navigate_tool`.

    Returns ``{"screenshot": virtual_path|None, "url": str, "title": str}``.
    Raises :class:`ValueError` when the URL fails SSRF validation.
    """
    url_error = _validate_url("browser_navigate", url)
    if url_error:
        raise ValueError(url_error)
    cfg = _get_tool_config("browser_navigate")
    manager = get_browser_session_manager()
    with manager.acquire_session(
        thread_id,
        headless=_as_bool(cfg.get("headless"), True),
        timeout_ms=_as_int(cfg.get("timeout_ms"), 30000),
        viewport={"width": _as_int(cfg.get("viewport_width"), 1280), "height": _as_int(cfg.get("viewport_height"), 720)},
        cdp_url=_as_str(cfg.get("cdp_url")),
        allow_unguarded_cdp=_as_bool(cfg.get("allow_unguarded_cdp"), False),
        url_guard=validate_browser_url,
    ) as session:
        snapshot = await session.navigate(url)
        screenshot_path: str | None = None
        try:
            content = await session.screenshot_bytes(full_page=False)
            name = _step_screenshot_name("navigate")
            frames_dir = outputs_path / _BROWSER_FRAMES_DIRNAME
            final_name = await asyncio.to_thread(_write_screenshot, frames_dir, name, content)
            screenshot_path = f"{_FRAMES_VIRTUAL_PREFIX}/{final_name}"
        except Exception as e:
            logger.warning(f"browser gateway navigate screenshot failed: {e}")
    return {"screenshot": screenshot_path, "url": snapshot.url, "title": snapshot.title}


@tool("browser_navigate", parse_docstring=True)
async def browser_navigate_tool(runtime: Runtime, url: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Open a URL in a live browser session and return the page's interactive elements.

    Use this to START a browsing flow. Unlike web_fetch (read-only), this keeps a
    stateful browser so you can then click and type on the page. The result lists
    interactive elements as ``[ref] role: name`` — use those ``[ref]`` numbers with
    browser_click and browser_type. The session persists across tool calls for this
    conversation until browser_close. Every navigate/click/type step is
    auto-captured as a screenshot the user can see, so you do not need to call
    browser_screenshot just to show progress.
    URLs must include the scheme, e.g. https://example.com.

    Args:
        url: The http(s) URL to open.
    """
    try:
        url_error = _validate_url("browser_navigate", url)
        if url_error:
            return _tool_message(url_error, tool_call_id)
        with _resolve_session(runtime, "browser_navigate") as session:
            snapshot = await session.navigate(url)
            screenshot = await _capture_step_screenshot(runtime, session, "navigate")
            return _snapshot_command(runtime, session, snapshot, tool_call_id, f"Navigated to {url}.", screenshot)
    except Exception as e:
        logger.error(f"browser_navigate failed: {e}")
        return _tool_message(f"Error: browser navigation failed: {e}", tool_call_id)


@tool("browser_snapshot")
async def browser_snapshot_tool(runtime: Runtime, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Re-read the current page's interactive elements without acting. Use this to refresh the [ref] element list after the page changed on its own (e.g. async content loaded) or when you are unsure of the current state."""
    try:
        with _resolve_session(runtime, "browser_snapshot") as session:
            snapshot = await session.snapshot()
            screenshot = await _capture_step_screenshot(runtime, session, "snapshot")
            return _snapshot_command(runtime, session, snapshot, tool_call_id, "", screenshot)
    except Exception as e:
        logger.error(f"browser_snapshot failed: {e}")
        return _tool_message(f"Error: browser snapshot failed: {e}", tool_call_id)


@tool("browser_click", parse_docstring=True)
async def browser_click_tool(runtime: Runtime, ref: int, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Click an interactive element by its ``[ref]`` number from the latest snapshot.

    The ref comes from the numbered element list returned by browser_navigate,
    browser_snapshot, browser_click, or browser_type. Returns the updated page
    snapshot after the click (with new ``[ref]`` numbers).

    Args:
        ref: The element reference number to click.
    """
    try:
        with _resolve_session(runtime, "browser_click") as session:
            snapshot = await session.click(ref)
            screenshot = await _capture_step_screenshot(runtime, session, "click")
            return _snapshot_command(runtime, session, snapshot, tool_call_id, f"Clicked element [{ref}].", screenshot)
    except Exception as e:
        logger.error(f"browser_click failed: {e}")
        return _tool_message(f"Error: could not click element [{ref}]: {e}", tool_call_id)


@tool("browser_type", parse_docstring=True)
async def browser_type_tool(
    runtime: Runtime,
    ref: int,
    text: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    submit: bool = False,
) -> Command:
    """Type text into an input/textarea element by its ``[ref]`` number.

    Fills the field identified by ref. Set submit=true to press Enter afterward
    (e.g. to run a search or submit a form). Returns the updated page snapshot.

    Args:
        ref: The element reference number of the input to type into.
        text: The text to enter.
        submit: When true, press Enter after typing to submit.
    """
    try:
        with _resolve_session(runtime, "browser_type") as session:
            snapshot = await session.type_text(ref, text, submit=submit)
            action = f"Typed into element [{ref}] and submitted." if submit else f"Typed into element [{ref}]."
            screenshot = await _capture_step_screenshot(runtime, session, "type")
            return _snapshot_command(runtime, session, snapshot, tool_call_id, action, screenshot)
    except Exception as e:
        logger.error(f"browser_type failed: {e}")
        return _tool_message(f"Error: could not type into element [{ref}]: {e}", tool_call_id)


@tool("browser_get_text")
async def browser_get_text_tool(runtime: Runtime, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Read the visible text content of the current page. Use this to extract readable text after navigating/interacting, e.g. to quote results or summarize content. Output is truncated for large pages."""
    try:
        with _resolve_session(runtime, "browser_get_text") as session:
            cfg = _get_tool_config("browser_get_text")
            max_chars = _as_int(cfg.get("max_chars"), 8000)
            text = await session.get_text(max_chars=max_chars)
        return _tool_message(text or "(page has no visible text)", tool_call_id)
    except Exception as e:
        logger.error(f"browser_get_text failed: {e}")
        return _tool_message(f"Error: could not read page text: {e}", tool_call_id)


@tool("browser_back")
async def browser_back_tool(runtime: Runtime, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Go back to the previous page in the browser session's history."""
    try:
        with _resolve_session(runtime, "browser_back") as session:
            snapshot = await session.back()
            screenshot = await _capture_step_screenshot(runtime, session, "back")
            return _snapshot_command(runtime, session, snapshot, tool_call_id, "Went back.", screenshot)
    except Exception as e:
        logger.error(f"browser_back failed: {e}")
        return _tool_message(f"Error: could not go back: {e}", tool_call_id)


def _safe_screenshot_name(filename: str | None) -> str:
    if filename:
        stem = Path(filename).stem or "browser-capture"
    else:
        stem = f"browser-capture-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    safe = _SAFE_FILENAME_RE.sub("_", stem).strip("._-") or "browser-capture"
    return f"{safe[:100]}.png"


def _thread_outputs_path(runtime: Runtime) -> Path | str:
    if runtime.state is None:
        return "Error: Thread runtime state is not available"
    thread_data = runtime.state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        return "Error: Thread outputs path is not available"
    return Path(outputs_path)


def _write_screenshot(outputs_path: Path, name: str, content: bytes) -> str:
    outputs_path.mkdir(parents=True, exist_ok=True)
    (outputs_path / name).write_bytes(content)
    return name


@tool("browser_screenshot", parse_docstring=True)
async def browser_screenshot_tool(
    runtime: Runtime,
    tool_call_id: Annotated[str, InjectedToolCallId],
    filename: str | None = None,
    full_page: bool = False,
) -> Command:
    """Capture a screenshot of the current browser page and save it as an artifact.

    Use this for visual evidence of the current interactive session state (after
    clicking/typing), which web_capture cannot provide because it renders a fresh,
    stateless page load.

    Args:
        filename: Optional output filename (extension is forced to .png).
        full_page: Capture the full scrollable page instead of just the viewport.
    """
    try:
        outputs_path = _thread_outputs_path(runtime)
        if isinstance(outputs_path, str):
            return _tool_message(outputs_path, tool_call_id)
        with _resolve_session(runtime, "browser_screenshot") as session:
            content = await session.screenshot_bytes(full_page=full_page)
            name = _safe_screenshot_name(filename)
            final_name = await asyncio.to_thread(_write_screenshot, outputs_path, name, content)
        virtual_path = f"{_OUTPUTS_VIRTUAL_PREFIX}/{final_name}"
        return Command(
            update={
                "artifacts": [virtual_path],
                "messages": [ToolMessage(f"Saved browser screenshot: {virtual_path}", tool_call_id=tool_call_id)],
            }
        )
    except Exception as e:
        logger.error(f"browser_screenshot failed: {e}")
        return _tool_message(f"Error: could not capture screenshot: {e}", tool_call_id)


@tool("browser_close")
async def browser_close_tool(runtime: Runtime, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Close the current browser session and free its resources. Call this when done with the browsing flow; a later browser_navigate starts a fresh session."""
    try:
        manager = get_browser_session_manager()
        closed = await manager.close_session(_thread_id(runtime))
        msg = "Browser session closed." if closed else "No active browser session to close."
        return _tool_message(msg, tool_call_id)
    except Exception as e:
        logger.error(f"browser_close failed: {e}")
        return _tool_message(f"Error: could not close browser session: {e}", tool_call_id)
