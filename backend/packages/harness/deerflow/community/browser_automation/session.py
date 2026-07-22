"""Stateful, loop-affine browser sessions backed by Playwright.

Playwright's async objects (``Browser``/``BrowserContext``/``Page``) are affine
to the event loop that created them. DeerFlow tools may be awaited on the
Gateway loop, the TUI loop, or a fresh test loop, and a browser session must
survive across turns of the same thread. To decouple Playwright's loop from the
caller's loop, every Playwright operation runs on one private daemon event loop
(same approach the BoxLite provider uses for its loop-affine box handles); async
tools await the result via :func:`asyncio.wrap_future`.

Playwright itself is an optional dependency — it is imported lazily inside the
private loop so the core harness installs without it.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Element roles/tags treated as interactive when building a page snapshot. The
# model addresses elements by the ``data-df-ref`` index this snapshot stamps, so
# it never has to guess a CSS selector or hold a stale element handle.
_SNAPSHOT_JS = r"""
() => {
  // Clear ref stamps from any previous snapshot first. GitHub-style SPAs keep
  // stale (now-hidden) nodes in the DOM carrying old data-df-ref values; if we
  // don't strip them, a later click selector like [data-df-ref="5"] can match
  // the hidden leftover ahead of the current visible element in DOM order and
  // time out waiting for it to become actionable.
  for (const stale of document.querySelectorAll("[data-df-ref]")) {
    stale.removeAttribute("data-df-ref");
  }
  const INTERACTIVE = new Set(["A", "BUTTON", "INPUT", "TEXTAREA", "SELECT"]);
  const results = [];
  let ref = 0;
  const nodes = document.querySelectorAll(
    "a, button, input, textarea, select, [role=button], [role=link], [role=tab], [role=checkbox], [onclick]"
  );
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    const visible = rect.width > 0 && rect.height > 0 &&
      window.getComputedStyle(el).visibility !== "hidden" &&
      window.getComputedStyle(el).display !== "none";
    if (!visible) continue;
    ref += 1;
    el.setAttribute("data-df-ref", String(ref));
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute("role") || "";
    const type = el.getAttribute("type") || "";
    let name = (el.getAttribute("aria-label") || el.getAttribute("name") ||
      el.getAttribute("placeholder") || el.innerText || el.value || "").trim();
    if (name.length > 120) name = name.slice(0, 120) + "…";
    results.push({ ref, tag, role, type, name });
    if (results.length >= 200) break;
  }
  return { url: location.href, title: document.title, elements: results };
}
"""


_WHEEL_SCROLL_JS = r"""
({ x, y, dx, dy }) => {
  const root = document.scrollingElement || document.documentElement;
  const candidates = [];
  let node = document.elementFromPoint(x, y);

  while (node && node !== document.documentElement) {
    if (node instanceof Element) {
      candidates.push(node);
    }
    node = node.parentElement;
  }
  candidates.push(root);

  const canScroll = (el, axis, delta) => {
    if (!delta || !el) {
      return false;
    }
    const max =
      axis === "y"
        ? el.scrollHeight - el.clientHeight
        : el.scrollWidth - el.clientWidth;
    if (max <= 0) {
      return false;
    }
    const current = axis === "y" ? el.scrollTop : el.scrollLeft;
    return delta < 0 ? current > 0 : current < max;
  };

  for (const el of candidates) {
    if (!canScroll(el, "y", dy) && !canScroll(el, "x", dx)) {
      continue;
    }
    const beforeLeft = el.scrollLeft;
    const beforeTop = el.scrollTop;
    el.scrollBy({ left: dx, top: dy, behavior: "auto" });
    return el.scrollLeft !== beforeLeft || el.scrollTop !== beforeTop;
  }

  const beforeX = window.scrollX;
  const beforeY = window.scrollY;
  window.scrollBy({ left: dx, top: dy, behavior: "auto" });
  return window.scrollX !== beforeX || window.scrollY !== beforeY;
}
"""


# Per-action timeout for clicks. Kept well under the session default (30s) so a
# stale/invalid ref fails fast and the model can re-snapshot instead of blocking
# the whole browsing loop (and tripping the agent loop-detection safety stop).
_CLICK_TIMEOUT_MS = 8000
# Short, best-effort settle wait after a click. SPA (client-side) navigations
# never fire a fresh load event, so this must never block the action.
_POST_CLICK_LOAD_TIMEOUT_MS = 3000
_LIVE_FRAME_JPEG_QUALITY = 85
_MANUAL_LIVE_FRAME_MIN_INTERVAL_S = 0.75
_LIVE_FRAME_INPUT_INTERVAL_S = 0.05
_LIVE_FRAME_SETTLE_DELAYS_S = (0.8, 2.0)

# Bound per-thread Chromium accumulation on a long-running multi-user gateway.
# Sessions unused past the idle timeout are lazily evicted on the next
# get_session call, and the LRU session is closed once the cap is exceeded.
_DEFAULT_MAX_SESSIONS = 32
_DEFAULT_IDLE_TIMEOUT_S = 30 * 60.0


def browser_multi_worker_error(workers: int | None = None) -> str | None:
    """Return the fail-closed reason for process-local browser sessions."""
    if workers is None:
        try:
            workers = int(os.environ.get("GATEWAY_WORKERS", "1"))
        except (TypeError, ValueError):
            workers = 1
    if workers <= 1:
        return None
    return f"GATEWAY_WORKERS={workers} cannot enable agentic browser tools: browser sessions are process-local and uvicorn does not provide thread affinity. Set GATEWAY_WORKERS=1 or disable the browser_navigate tool."


def ensure_browser_worker_compatibility() -> None:
    """Reject runtime browser use when requests can land in another worker."""
    error = browser_multi_worker_error()
    if error is not None:
        raise RuntimeError(error)


class BrowserSessionCapacityError(RuntimeError):
    """Raised when the browser session cap has no evictable slot."""


class BrowserLiveViewerError(RuntimeError):
    """Raised when a second Live viewer tries to attach to a session."""


def _is_playwright_timeout_error(exc: Exception) -> bool:
    """Recognize Playwright timeouts without requiring Playwright at import time."""
    return exc.__class__.__name__ == "TimeoutError" and exc.__class__.__module__.startswith("playwright.")


def redact_browser_url(url: str) -> str:
    """Drop query/fragment so a blocked-URL log line can't leak tokens/PII."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return "<unparsable-url>"


class _PlaywrightLoopThread:
    """A private asyncio event loop running on a dedicated daemon thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="deerflow-browser-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Schedule *coro* on the private loop and await it from any loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(future)

    def submit(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule *coro* on the private loop without blocking the caller."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _log_failure(done: Any) -> None:
            try:
                done.result()
            except Exception as exc:
                logger.debug("browser background task failed: %s", exc)

        future.add_done_callback(_log_failure)

    def run_sync(self, coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)


@dataclass
class SnapshotElement:
    ref: int
    tag: str
    role: str
    type: str
    name: str

    def render(self) -> str:
        label = self.role or self.tag
        detail = f" type={self.type}" if self.type else ""
        name = self.name or "(no text)"
        return f"[{self.ref}] {label}{detail}: {name}"


@dataclass
class PageSnapshot:
    url: str
    title: str
    elements: list[SnapshotElement] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"URL: {self.url}", f"Title: {self.title}", ""]
        if not self.elements:
            lines.append("No interactive elements detected.")
        else:
            lines.append("Interactive elements (address them by [ref] number):")
            lines.extend(el.render() for el in self.elements)
        return "\n".join(lines)


@dataclass
class BrowserTab:
    index: int
    url: str
    title: str
    active: bool


class BrowserSession:
    """A single Playwright browser+page bound to the private loop."""

    def __init__(
        self,
        loop: _PlaywrightLoopThread,
        *,
        headless: bool,
        timeout_ms: int,
        viewport: dict[str, int],
        cdp_url: str | None = None,
        url_guard: Callable[[str], str | None] | None = None,
        on_activity: Callable[[], None] | None = None,
    ) -> None:
        self._loop = loop
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._viewport = viewport
        # Optional SSRF guard applied at the browser request boundary. It returns
        # an error string to block a URL (redirect/popup/subresource) or None to
        # allow it. The explicit navigate URL is screened by the caller, but
        # Playwright follows redirects and issues subresource/popup requests that
        # bypass that single check — so we also validate every request the page
        # makes here, catching a public URL that 30x-redirects to a private or
        # cloud-metadata host.
        self._url_guard = url_guard
        self._request_guard_bound = False
        # When set, attach to an already-running Chrome via the DevTools
        # Protocol (like Codex's "connect to your real browser") instead of
        # launching a private headless instance. The user watches the agent
        # drive their own visible browser, with their real login sessions.
        self._cdp_url = cdp_url
        self._on_activity = on_activity
        self._activity_lock = threading.Lock()
        self._active_refs = 0
        self._connected_over_cdp = False
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # Tool calls and the Live WebSocket share this session and can observe a
        # closed page concurrently. Only one caller may rebuild the browser
        # hierarchy; the second check inside the lock reuses its result.
        self._ensure_page_lock = asyncio.Lock()
        # Live screencast state. When streaming, ``_on_frame`` is retained so the
        # screencast can be re-bound to a new page — login/OAuth flows commonly
        # open a popup or a fresh tab, and the user must see (and drive) it.
        self._on_frame: Callable[[str], None] | None = None
        # The page the live screencast's CDP session is currently bound to. Frames
        # are captured from ``self._page`` (the live active page), but the CDP
        # repaint signal is tied to a specific page; when the active page diverges
        # from this one we must rebind so new-page repaints keep driving frames.
        self._screencast_page: Page | None = None
        # Guards against re-entrant rebinds: while (re)binding the screencast we
        # may call _ensure_page (which routes through _set_active_page); without
        # this flag that would schedule another rebind and recurse.
        self._screencast_binding = False
        self._last_manual_live_frame_at = 0.0
        self._settle_live_frames_pending = False
        self._input_live_frame_generation = 0
        self._input_live_frame_pending = False
        self._page_listener_bound = False

    @property
    def active_refs(self) -> int:
        with self._activity_lock:
            return self._active_refs

    def _pin(self) -> None:
        """Keep this session in the manager while a caller owns it."""
        with self._activity_lock:
            self._active_refs += 1

    def _unpin(self) -> None:
        with self._activity_lock:
            self._active_refs = max(0, self._active_refs - 1)

    @contextlib.contextmanager
    def _activity(self):
        """Reference a real browser operation and refresh its recency."""
        self._pin()
        if self._on_activity is not None:
            self._on_activity()
        try:
            yield
        finally:
            self._unpin()

    async def _ensure_page(self) -> Page:
        if self._page is not None and not self._page.is_closed():
            return self._page
        async with self._ensure_page_lock:
            if self._page is not None and not self._page.is_closed():
                return self._page
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            if self._cdp_url:
                # Attach to the user's running Chrome (started with
                # --remote-debugging-port). Reuse its default context + an existing
                # tab: calling new_context()/new_page() on a CDP-attached real
                # Chrome trips "Browser context management is not supported", so we
                # adopt the tab Chrome already opened instead.
                if self._browser is None or not self._browser.is_connected():
                    self._browser = await self._playwright.chromium.connect_over_cdp(self._cdp_url)
                    self._connected_over_cdp = True
                    # CDP-attached real Chrome owns its own browsing context, so the
                    # SSRF request guard is intentionally NOT installed for it (see
                    # _install_request_guard). Surface that to operators — for this
                    # session redirects/subresources to private/metadata hosts are
                    # not aborted; cdp_url is documented local/trusted-only.
                    logger.warning(
                        "browser SSRF request guard is disabled for CDP-attached session (cdp_url=%s)",
                        redact_browser_url(self._cdp_url),
                    )
                self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
                self._context.set_default_timeout(self._timeout_ms)
                existing = self._context.pages
                self._set_active_page(existing[-1] if existing else await self._context.new_page())
                self._bind_new_page_listener()
                return self._page

            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._playwright.chromium.launch(headless=self._headless)
            # device_scale_factor=2 renders screenshots at retina density so the
            # panel stays crisp when the image is scaled up to fill the view.
            self._context = await self._browser.new_context(viewport=self._viewport, device_scale_factor=2)
            self._context.set_default_timeout(self._timeout_ms)
            await self._install_request_guard()
            self._set_active_page(await self._context.new_page())
            self._bind_new_page_listener()
            return self._page

    def _set_active_page(self, page: Page) -> None:
        """Adopt *page* as the active page and keep the live screencast on it.

        Every path that changes the active page (initial/rebuilt page, popups and
        new tabs, explicit tab switches) routes through here so the live stream can
        never drift onto a stale page. The CDP screencast's repaint signal is bound
        to one page; when the active page diverges from the one the screencast is
        bound to, rebind it. Rebinding is scheduled with error handling so a
        transient failure cannot leave the callback un-awaited and silently
        swallowed (the previous fire-and-forget rebind could strand Live on the
        old page — address bar / snapshot moved on, frames did not).
        """
        self._page = page
        if self._on_frame is not None and not self._screencast_binding and page is not self._screencast_page:
            asyncio.ensure_future(self._rebind_screencast_safe())

    def _bind_new_page_listener(self) -> None:
        """Follow popups/new tabs so auth flows stay visible and controllable.

        Login and OAuth consent screens routinely open a popup or a fresh tab.
        Without following it the user sees a frozen frame and cannot authorize.
        On a new page we adopt it as the active page and, if a screencast is
        running, re-bind it so the stream tracks the tab the user must act on.
        """
        if self._context is None or self._page_listener_bound:
            return

        def _on_new_page(page: Page) -> None:
            self._set_active_page(page)

        self._context.on("page", _on_new_page)
        self._page_listener_bound = True

    async def _install_request_guard(self) -> None:
        """Abort any request whose URL fails the SSRF guard.

        Runs at the context level so it covers the top navigation, every
        redirect hop, popups/new tabs, iframes, and subresource fetches — the
        paths a one-time initial-URL check cannot see. A public URL that
        redirects to ``http://169.254.169.254/...`` is aborted before the
        response is exposed through snapshots/text. Skipped for CDP-attached
        real Chrome, which owns its own browsing context.
        """
        if self._url_guard is None or self._context is None or self._request_guard_bound or self._cdp_url:
            return

        guard = self._url_guard

        async def _route(route: Any) -> None:
            url = ""
            with contextlib.suppress(Exception):
                url = route.request.url
            if url.startswith(("http://", "https://")) and guard(url) is not None:
                logger.warning("browser request blocked by SSRF guard: %s", redact_browser_url(url))
                with contextlib.suppress(Exception):
                    await route.abort("blockedbyclient")
                return
            with contextlib.suppress(Exception):
                await route.continue_()

        with contextlib.suppress(Exception):
            await self._context.route("**/*", _route)
            self._request_guard_bound = True

    async def _rebind_screencast(self) -> None:
        if self._on_frame is not None:
            await self._start_screencast(self._on_frame)

    async def _rebind_screencast_safe(self) -> None:
        try:
            await self._rebind_screencast()
        except Exception as exc:
            logger.debug("browser live screencast rebind failed: %s", exc)

    async def _navigate(self, url: str) -> PageSnapshot:
        page = await self._ensure_page()
        await page.goto(url, wait_until="domcontentloaded")
        return await self._snapshot_impl(page)

    async def _snapshot_impl(self, page: Page) -> PageSnapshot:
        data = await page.evaluate(_SNAPSHOT_JS)
        elements = [SnapshotElement(ref=int(e["ref"]), tag=e["tag"], role=e["role"], type=e["type"], name=e["name"]) for e in data["elements"]]
        return PageSnapshot(url=data["url"], title=data["title"], elements=elements)

    async def _snapshot(self) -> PageSnapshot:
        page = await self._ensure_page()
        return await self._snapshot_impl(page)

    async def _click(self, ref: int) -> PageSnapshot:
        page = await self._ensure_page()
        selector = f'[data-df-ref="{ref}"]'
        base = page.locator(selector)

        # Fast-fail on a stale ref instead of blocking on the 30s session
        # default: after a SPA re-render the ref may no longer exist, and the
        # model should re-snapshot and retry rather than the browsing loop
        # stalling until it trips the agent loop-detection safety stop.
        if await base.count() == 0:
            raise RuntimeError(f"element [{ref}] is no longer on the page; call browser_snapshot to get fresh refs")

        locator = base.first
        # Bring the target into view; harmless if it is already on-screen.
        try:
            await locator.scroll_into_view_if_needed(timeout=_CLICK_TIMEOUT_MS)
        except Exception as exc:
            if not _is_playwright_timeout_error(exc):
                raise

        try:
            await locator.click(timeout=_CLICK_TIMEOUT_MS)
        except Exception as exc:
            if not _is_playwright_timeout_error(exc):
                raise
            raise RuntimeError(f"element [{ref}] was not clickable within {_CLICK_TIMEOUT_MS // 1000}s; the page may have changed — call browser_snapshot and retry") from exc

        # SPA (client-side) navigations never fire a fresh load event, so this
        # settle wait is best-effort and must never block the snapshot.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=_POST_CLICK_LOAD_TIMEOUT_MS)
        except Exception as exc:
            if not _is_playwright_timeout_error(exc):
                raise

        return await self._snapshot_impl(page)

    async def _type(self, ref: int, text: str, submit: bool) -> PageSnapshot:
        page = await self._ensure_page()
        selector = f'[data-df-ref="{ref}"]'
        await page.fill(selector, text)
        if submit:
            await page.press(selector, "Enter")
            # Best-effort settle; a client-side search/submit may never fire a
            # fresh load event, so this must not block the snapshot for 30s.
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=_POST_CLICK_LOAD_TIMEOUT_MS)
            except Exception as exc:
                if not _is_playwright_timeout_error(exc):
                    raise
        return await self._snapshot_impl(page)

    async def _get_text(self, max_chars: int) -> str:
        page = await self._ensure_page()
        text = await page.inner_text("body")
        return text[:max_chars]

    async def _screenshot_bytes(self, full_page: bool) -> bytes:
        page = await self._ensure_page()
        return await page.screenshot(full_page=full_page, type="png")

    async def _live_frame(self) -> str:
        page = await self._ensure_page()
        shot = await page.screenshot(type="jpeg", quality=_LIVE_FRAME_JPEG_QUALITY)
        return base64.b64encode(shot).decode("ascii")

    async def _emit_live_frame(self) -> None:
        if self._on_frame is None:
            return
        with self._activity():
            self._on_frame(await self._live_frame())
            self._last_manual_live_frame_at = time.monotonic()

    async def _settle_live_frames(self) -> None:
        previous_delay = 0.0
        try:
            for delay in _LIVE_FRAME_SETTLE_DELAYS_S:
                await asyncio.sleep(max(0.0, delay - previous_delay))
                previous_delay = delay
                await self._emit_live_frame()
        finally:
            self._settle_live_frames_pending = False

    def _schedule_settle_live_frames(self) -> None:
        if self._settle_live_frames_pending:
            return
        self._settle_live_frames_pending = True
        asyncio.ensure_future(self._settle_live_frames())

    async def _push_live_frame(self) -> None:
        if self._on_frame is None:
            return
        elapsed = time.monotonic() - self._last_manual_live_frame_at
        if elapsed >= _MANUAL_LIVE_FRAME_MIN_INTERVAL_S:
            await self._emit_live_frame()
        # One frame is often too early for SPAs: the URL may have changed while
        # the page body is still rendering. Add a small, bounded settle burst
        # instead of returning to continuous screencast.
        self._schedule_settle_live_frames()

    async def _flush_input_live_frames(self) -> None:
        try:
            # Coalesce the first burst, then keep refreshing at a bounded cadence
            # while input continues. A trailing debounce would freeze the visible
            # page until a wheel/keyboard gesture stopped.
            await asyncio.sleep(_LIVE_FRAME_INPUT_INTERVAL_S)
            while self._on_frame is not None:
                generation = self._input_live_frame_generation
                await self._emit_live_frame()
                if generation == self._input_live_frame_generation:
                    self._schedule_settle_live_frames()
                    return
                await asyncio.sleep(_LIVE_FRAME_INPUT_INTERVAL_S)
        finally:
            self._input_live_frame_pending = False

    def _schedule_input_live_frame(self) -> None:
        self._input_live_frame_generation += 1
        if self._input_live_frame_pending:
            return
        self._input_live_frame_pending = True
        asyncio.ensure_future(self._flush_input_live_frames())

    async def _back(self) -> PageSnapshot:
        page = await self._ensure_page()
        await page.go_back(wait_until="domcontentloaded")
        return await self._snapshot_impl(page)

    async def _current_url(self) -> str | None:
        page = await self._ensure_page()
        try:
            return page.url
        except Exception:
            return None

    async def _tabs(self) -> list[BrowserTab]:
        await self._ensure_page()
        if self._context is None:
            return []
        pages = [page for page in self._context.pages if not page.is_closed()]
        tabs: list[BrowserTab] = []
        for index, page in enumerate(pages):
            try:
                title = await page.title()
            except Exception:
                title = ""
            try:
                url = page.url
            except Exception:
                url = ""
            tabs.append(BrowserTab(index=index, url=url, title=title, active=page == self._page))
        return tabs

    async def _activate_tab(self, index: int) -> None:
        await self._ensure_page()
        if self._context is None:
            return
        pages = [page for page in self._context.pages if not page.is_closed()]
        if index < 0 or index >= len(pages):
            return
        target = pages[index]
        await target.bring_to_front()
        # This path is async, so rebind the screencast inline (awaited) rather
        # than going through _set_active_page's scheduled rebind — that keeps the
        # frame source aligned with the switched-to tab before this call returns.
        self._page = target
        if self._on_frame is not None and target is not self._screencast_page:
            await self._rebind_screencast()

    async def _close(self) -> None:
        try:
            with contextlib.suppress(Exception):
                await self._stop_screencast()
            if self._connected_over_cdp:
                # Attached to the user's real Chrome — never close their browser,
                # context, or the tab we adopted. Just disconnect Playwright.
                if self._browser is not None:
                    with contextlib.suppress(Exception):
                        await self._browser.close()
            else:
                if self._context is not None:
                    with contextlib.suppress(Exception):
                        await self._context.close()
                if self._browser is not None:
                    with contextlib.suppress(Exception):
                        await self._browser.close()
            if self._playwright is not None:
                with contextlib.suppress(Exception):
                    await self._playwright.stop()
        finally:
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._screencast_page = None
            self._connected_over_cdp = False
            self._on_frame = None
            self._settle_live_frames_pending = False
            self._input_live_frame_generation += 1
            self._page_listener_bound = False
            self._request_guard_bound = False

    async def _start_screencast(self, on_frame: Callable[[str], None]) -> None:
        """Start Live mode and send an initial JPEG frame.

        This used to attach Chrome's CDP screencast and then turn every repaint
        into a high-quality Playwright screenshot. That made GitHub-like pages
        expensive to open because a mostly static panel still kept the headless
        renderer/GPU busy. Live control now uses on-demand frames instead:
        initial connect, browser tool completion, and user input all push a
        throttled screenshot.
        """
        page = await self._ensure_page()
        if self._on_frame is not None and self._on_frame is not on_frame:
            raise BrowserLiveViewerError("Browser live stream already has an active viewer")
        await self._stop_screencast()
        self._on_frame = on_frame
        self._screencast_page = page
        await self._emit_live_frame()
        self._schedule_settle_live_frames()

    async def _stop_screencast(self, on_frame: Callable[[str], None] | None = None) -> None:
        if on_frame is not None and self._on_frame is not on_frame:
            return
        self._on_frame = None
        self._settle_live_frames_pending = False
        self._input_live_frame_generation += 1
        self._screencast_page = None

    async def _dispatch_input(self, event: dict) -> None:
        page = await self._ensure_page()
        vw = self._viewport.get("width", 1280)
        vh = self._viewport.get("height", 720)
        etype = event.get("type")
        if etype in {"click", "move", "down", "up"}:
            x = float(event.get("nx", 0)) * vw
            y = float(event.get("ny", 0)) * vh
            if etype == "click":
                await page.mouse.click(x, y)
            elif etype == "move":
                await page.mouse.move(x, y)
            elif etype == "down":
                await page.mouse.move(x, y)
                await page.mouse.down()
            elif etype == "up":
                await page.mouse.up()
        elif etype == "wheel":
            dx = float(event.get("dx", 0))
            dy = float(event.get("dy", 0))
            nx = event.get("nx")
            ny = event.get("ny")
            x = vw / 2
            y = vh / 2
            if nx is not None and ny is not None:
                try:
                    x = max(0.0, min(1.0, float(nx))) * vw
                    y = max(0.0, min(1.0, float(ny))) * vh
                    await page.mouse.move(x, y)
                except (TypeError, ValueError) as e:
                    logger.debug("invalid browser wheel coordinates: %s", e)
            try:
                handled = bool(await page.evaluate(_WHEEL_SCROLL_JS, {"x": x, "y": y, "dx": dx, "dy": dy}))
            except Exception as e:
                logger.debug("browser js scroll failed: %s", e)
                handled = False
            if not handled:
                await page.mouse.wheel(dx, dy)
        elif etype == "key":
            key = event.get("key")
            if key:
                await page.keyboard.press(key)
        elif etype == "text":
            text = event.get("text")
            if text:
                await page.keyboard.type(text)
        elif etype == "navigate":
            url = event.get("url")
            if url:
                await page.goto(url, wait_until="domcontentloaded")
        elif etype == "back":
            await page.go_back(wait_until="domcontentloaded")
        elif etype == "forward":
            await page.go_forward(wait_until="domcontentloaded")
        elif etype == "activate_tab":
            index = event.get("index")
            if isinstance(index, int) and not isinstance(index, bool):
                await self._activate_tab(index)
        if etype != "move":
            self._schedule_input_live_frame()

    # Public API — each marshals onto the private loop.
    async def navigate(self, url: str) -> PageSnapshot:
        with self._activity():
            return await self._loop.run(self._navigate(url))

    async def snapshot(self) -> PageSnapshot:
        with self._activity():
            return await self._loop.run(self._snapshot())

    async def click(self, ref: int) -> PageSnapshot:
        with self._activity():
            return await self._loop.run(self._click(ref))

    async def type_text(self, ref: int, text: str, submit: bool = False) -> PageSnapshot:
        with self._activity():
            return await self._loop.run(self._type(ref, text, submit))

    async def get_text(self, max_chars: int = 8000) -> str:
        with self._activity():
            return await self._loop.run(self._get_text(max_chars))

    async def screenshot_bytes(self, full_page: bool = False) -> bytes:
        with self._activity():
            return await self._loop.run(self._screenshot_bytes(full_page))

    async def live_frame(self) -> str:
        with self._activity():
            return await self._loop.run(self._live_frame())

    async def push_live_frame(self) -> None:
        with self._activity():
            await self._loop.run(self._push_live_frame())

    def schedule_live_frames(self) -> None:
        self._loop.submit(self._push_live_frame())

    async def back(self) -> PageSnapshot:
        with self._activity():
            return await self._loop.run(self._back())

    async def current_url(self) -> str | None:
        with self._activity():
            return await self._loop.run(self._current_url())

    async def tabs(self) -> list[BrowserTab]:
        with self._activity():
            return await self._loop.run(self._tabs())

    async def start_screencast(self, on_frame: Callable[[str], None]) -> None:
        with self._activity():
            await self._loop.run(self._start_screencast(on_frame))

    async def stop_screencast(self, on_frame: Callable[[str], None] | None = None) -> None:
        with self._activity():
            await self._loop.run(self._stop_screencast(on_frame))

    async def dispatch_input(self, event: dict) -> None:
        with self._activity():
            await self._loop.run(self._dispatch_input(event))

    async def close(self) -> None:
        await self._loop.run(self._close())


class BrowserSessionManager:
    """Process-local registry of per-thread browser sessions.

    Sessions are keyed by ``thread_id`` and each owns a headless Chromium
    process, so a long-running multi-user gateway would otherwise accumulate one
    browser per thread that ever used the tools (a real memory/FD leak). To bound
    that, ``get_session`` lazily evicts sessions that have been idle past
    ``idle_timeout_s`` and enforces a ``max_sessions`` cap by closing the
    least-recently-used unpinned session. Active browser operations and Live
    WebSocket leases are reference-counted, so eviction never closes a session
    while it is in use. Admission is a hard bound: when every existing session
    is pinned, a new thread is rejected instead of exceeding ``max_sessions``.
    Eviction is fire-and-forget on the private Playwright loop so it never
    blocks the caller; the just-requested thread is always kept.
    """

    def __init__(self, *, max_sessions: int = _DEFAULT_MAX_SESSIONS, idle_timeout_s: float = _DEFAULT_IDLE_TIMEOUT_S) -> None:
        self._loop: _PlaywrightLoopThread | None = None
        self._sessions: dict[str, BrowserSession] = {}
        self._last_used: dict[str, float] = {}
        self._max_sessions = max_sessions
        self._idle_timeout_s = idle_timeout_s
        self._lock = threading.Lock()

    def _touch_session(self, key: str) -> None:
        with self._lock:
            if key in self._sessions:
                self._last_used[key] = time.monotonic()

    def _ensure_loop(self) -> _PlaywrightLoopThread:
        if self._loop is None:
            self._loop = _PlaywrightLoopThread()
        return self._loop

    def get_session(
        self,
        thread_id: str | None,
        *,
        headless: bool = True,
        timeout_ms: int = 30000,
        viewport: dict[str, int] | None = None,
        cdp_url: str | None = None,
        allow_unguarded_cdp: bool = False,
        url_guard: Callable[[str], str | None] | None = None,
        pin: bool = False,
    ) -> BrowserSession:
        ensure_browser_worker_compatibility()
        if cdp_url and not allow_unguarded_cdp:
            raise RuntimeError("cdp_url uses a browser context where DeerFlow cannot enforce its SSRF request guard; set allow_unguarded_cdp: true only for an explicitly trusted local Chrome session")
        key = thread_id or "default"
        now = time.monotonic()
        evicted: list[BrowserSession] = []
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                evicted.extend(self._collect_idle_locked(keep_key=key, now=now))
                if self._max_sessions > 0 and len(self._sessions) >= self._max_sessions:
                    lru = self._pop_lru_unpinned_locked(excluded_keys={key})
                    if lru is None:
                        raise BrowserSessionCapacityError(f"Browser session capacity is full ({self._max_sessions}); close an active Live browser before opening another")
                    evicted.append(lru)
                session = BrowserSession(
                    self._ensure_loop(),
                    headless=headless,
                    timeout_ms=timeout_ms,
                    viewport=viewport or {"width": 1280, "height": 720},
                    cdp_url=cdp_url,
                    url_guard=url_guard,
                    on_activity=lambda: self._touch_session(key),
                )
                self._sessions[key] = session
            if pin:
                session._pin()
            self._last_used[key] = now
            evicted.extend(self._collect_evictable_locked(keep_key=key, now=now))
        for evicted_session in evicted:
            self._schedule_close(evicted_session)
        return session

    @contextlib.contextmanager
    def acquire_session(self, thread_id: str | None, **kwargs: Any):
        """Acquire an atomically pinned session for one browser operation."""
        key = thread_id or "default"
        session = self.get_session(key, pin=True, **kwargs)
        try:
            yield session
        finally:
            self.release_session(key, session)

    def release_session(self, thread_id: str | None, session: BrowserSession) -> None:
        """Release a lease and restore idle/LRU bounds when it becomes evictable."""
        key = thread_id or "default"
        session._unpin()
        now = time.monotonic()
        with self._lock:
            evicted = self._collect_evictable_locked(keep_key=None, now=now) if self._sessions.get(key) is session else []
        for evicted_session in evicted:
            self._schedule_close(evicted_session)

    def _collect_evictable_locked(self, *, keep_key: str | None, now: float) -> list[BrowserSession]:
        """Drop idle/over-cap sessions from the registry; return them for close.

        Must be called under ``self._lock``. When set, ``keep_key`` (the
        just-touched thread) is never evicted so a new request cannot lose its
        session. Lease release passes ``None`` so newly unpinned sessions can
        restore the configured bounds without waiting for another request.
        """
        to_close: list[BrowserSession] = []
        to_close.extend(self._collect_idle_locked(keep_key=keep_key, now=now))
        if self._max_sessions > 0:
            excluded = {keep_key} if keep_key is not None else set()
            while len(self._sessions) > self._max_sessions:
                session = self._pop_lru_unpinned_locked(excluded_keys=excluded)
                if session is None:
                    break
                to_close.append(session)
        return to_close

    def _collect_idle_locked(self, *, keep_key: str | None, now: float) -> list[BrowserSession]:
        """Drop idle, unpinned sessions from the registry."""
        to_close: list[BrowserSession] = []
        if self._idle_timeout_s > 0:
            for other_key, last_used in list(self._last_used.items()):
                if other_key == keep_key:
                    continue
                session = self._sessions.get(other_key)
                if session is not None and session.active_refs:
                    continue
                if now - last_used >= self._idle_timeout_s:
                    session = self._sessions.pop(other_key, None)
                    self._last_used.pop(other_key, None)
                    if session is not None:
                        to_close.append(session)
        return to_close

    def _pop_lru_unpinned_locked(self, *, excluded_keys: set[str]) -> BrowserSession | None:
        candidates = [(last_used, other_key) for other_key, last_used in self._last_used.items() if other_key not in excluded_keys and (session := self._sessions.get(other_key)) is not None and not session.active_refs]
        if not candidates:
            return None
        _, lru_key = min(candidates)
        session = self._sessions.pop(lru_key, None)
        self._last_used.pop(lru_key, None)
        return session

    def _schedule_close(self, session: BrowserSession) -> None:
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(Exception):
            loop.submit(session._close())

    async def close_session(self, thread_id: str | None) -> bool:
        key = thread_id or "default"
        with self._lock:
            session = self._sessions.pop(key, None)
            self._last_used.pop(key, None)
        if session is None:
            return False
        await session.close()
        return True

    async def close_all_sessions(self) -> int:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._last_used.clear()
        for session in sessions:
            await session.close()
        return len(sessions)


_manager: BrowserSessionManager | None = None
_manager_lock = threading.Lock()


def get_browser_session_manager() -> BrowserSessionManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = BrowserSessionManager()
    return _manager


def reset_browser_session_manager() -> None:
    """Test hook: drop the process-local manager without closing sessions."""
    global _manager
    with _manager_lock:
        _manager = None
