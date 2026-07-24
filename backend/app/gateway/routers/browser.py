import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.browser_capability import browser_capability
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id, reset_current_user, set_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["browser"])


class BrowserNavigateRequest(BaseModel):
    url: str = Field(..., description="The http(s) URL to open in the thread's live browser session")


class BrowserNavigateResponse(BaseModel):
    screenshot: str | None = Field(default=None, description="Virtual artifact path of the captured screenshot")
    url: str = Field(..., description="The resolved URL after navigation")
    title: str = Field(default="", description="The page title after navigation")


def _normalize_browser_seed_url(url: str | None) -> str:
    return (url or "").split("#", 1)[0].rstrip("/")


def _should_apply_browser_seed(current: str | None, seed: str | None) -> bool:
    if not seed:
        return False
    if not current or current == "about:blank":
        return True
    return _normalize_browser_seed_url(current) != _normalize_browser_seed_url(seed)


def _browser_tools_enabled() -> bool:
    """Whether the browser tools are turned on in config.

    The live browser HTTP/WS endpoints are an opt-in surface: they must only be
    reachable when the operator has enabled the ``browser_navigate`` tool in
    ``config.yaml``. Merely having Playwright importable (it may be preinstalled
    in a base image) is not sufficient — otherwise the endpoints would expose
    server-side browser control the operator never turned on.
    """
    from deerflow.config import get_app_config

    with contextlib.suppress(Exception):
        capability = browser_capability(get_app_config())
        if capability.configured and not capability.available and capability.reason:
            logger.error("browser automation disabled: %s", capability.reason)
        return capability.available
    return False


async def _browser_thread_owned_by(thread_store, thread_id: str, user_id: str) -> bool:
    """Require an explicit owner for browser control's high-trust surface.

    General thread reads retain compatibility with legacy ``user_id=NULL``
    rows. A retained browser may contain authenticated cookies and page data,
    so REST navigation and the Live socket deliberately use a stricter policy:
    only an existing row whose owner exactly matches may drive it.
    """
    record = await thread_store.get(thread_id, user_id=user_id)
    return record is not None and record.get("user_id") == user_id


@router.post(
    "/threads/{thread_id}/browser/navigate",
    response_model=BrowserNavigateResponse,
    summary="Navigate The Live Browser Session",
    description="Steer the thread's live browser session to a URL from the UI and capture a screenshot.",
)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def navigate_browser(thread_id: str, body: BrowserNavigateRequest, request: Request) -> BrowserNavigateResponse:
    user_id = str(request.state.auth.user.id)
    thread_store = getattr(request.app.state, "thread_store", None)
    if thread_store is None or not await _browser_thread_owned_by(thread_store, thread_id, user_id):
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    if not _browser_tools_enabled():
        raise HTTPException(status_code=404, detail="Browser automation is not enabled")

    try:
        from deerflow.community.browser_automation import navigate_and_capture, redact_browser_url
    except ImportError as exc:  # Playwright is an optional dependency.
        raise HTTPException(status_code=501, detail="Browser automation is not available") from exc

    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    outputs_path = get_paths().sandbox_outputs_dir(thread_id, user_id=get_effective_user_id())
    try:
        result = await navigate_and_capture(thread_id=thread_id, url=url, outputs_path=outputs_path)
    except ValueError as exc:
        # SSRF / URL validation failure.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Browser navigate failed: thread_id=%s url=%s err_type=%s",
            thread_id,
            redact_browser_url(url),
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Browser navigation failed") from exc

    return BrowserNavigateResponse(**result)


async def _authenticate_ws(websocket: WebSocket):
    """Resolve the user for a WebSocket, honoring auth-disabled mode.

    WebSocket upgrades bypass ``AuthMiddleware`` (a BaseHTTPMiddleware), so we
    replicate the minimal cookie → user resolution here. Returns the user or
    ``None`` when unauthenticated.
    """
    from app.gateway.auth import decode_token
    from app.gateway.auth.errors import TokenError
    from app.gateway.auth_disabled import get_auth_disabled_user, is_auth_disabled
    from app.gateway.deps import get_local_provider

    access_token = websocket.cookies.get("access_token")
    if access_token:
        payload = decode_token(access_token)
        if not isinstance(payload, TokenError):
            provider = get_local_provider()
            user = await provider.get_user(payload.sub)
            if user is not None and user.token_version == payload.ver:
                return user
    if is_auth_disabled():
        return get_auth_disabled_user()
    return None


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    """Reject cross-origin WebSocket upgrades (WS-CSRF defense).

    WS upgrades bypass ``CSRFMiddleware`` (also a BaseHTTPMiddleware), so a
    cross-origin page could otherwise open this socket riding the victim's
    cookie and both observe frames and drive their authenticated browser. The
    ``Origin`` header is browser-controlled but always sent on cross-origin
    upgrades, so validating it is a standard, cheap mitigation.

    Allow when: no ``Origin`` (non-browser clients such as native ws/tests do
    not send it), the origin is an explicitly configured CORS origin, or it is
    same-origin with the upgrade target's host. The WS scheme (ws/wss) differs
    from the page scheme (http/https), so same-origin compares host[:port].
    """
    from app.gateway.csrf_middleware import (
        _first_header_value,
        _normalize_origin,
        get_configured_cors_origins,
    )

    origin = websocket.headers.get("origin")
    if not origin:
        return True

    normalized = _normalize_origin(origin)
    if normalized is None:
        return False
    if normalized in get_configured_cors_origins():
        return True

    target_host = _first_header_value(websocket.headers.get("x-forwarded-host")) or websocket.headers.get("host")
    if target_host:
        normalized_host = normalized.split("://", 1)[-1]
        if normalized_host == target_host.strip().lower():
            return True
    return False


@router.websocket("/threads/{thread_id}/browser/stream")
async def browser_stream(websocket: WebSocket, thread_id: str) -> None:
    """Bidirectional live browser stream.

    Server → client: JSON ``{"type":"frame","data":"<base64 jpeg>"}`` frames
    captured via CDP screencast. Client → server: input events (click, move,
    down, up, wheel, key, text, navigate) that drive the live page.
    """
    user = await _authenticate_ws(websocket)
    if user is None:
        await websocket.close(code=4401)
        return

    if not _ws_origin_allowed(websocket):
        # Cross-origin upgrade — reject before touching any session (WS-CSRF).
        await websocket.close(code=4403)
        return

    thread_store = getattr(websocket.app.state, "thread_store", None)
    if thread_store is None:
        # Fail closed: the live stream drives a real browser (cookies,
        # logged-in pages), so if the ownership store can't be resolved we must
        # deny rather than let any authenticated caller attach to any thread's
        # retained session.
        await websocket.close(code=4404)
        return
    # Browser control is stricter than ordinary legacy-thread access: NULL-owner
    # rows are not shared because a retained page may expose cookies or account
    # data from a previous authenticated browser session.
    if not await _browser_thread_owned_by(thread_store, thread_id, str(user.id)):
        await websocket.close(code=4404)
        return

    if not _browser_tools_enabled():
        await websocket.close(code=4404)
        return

    try:
        from deerflow.community.browser_automation import (
            BrowserLiveViewerError,
            BrowserSessionCapacityError,
            get_browser_session_manager,
            validate_browser_url,
        )
    except ImportError:
        await websocket.close(code=4501)
        return

    await websocket.accept()

    token = set_current_user(user)
    loop = asyncio.get_running_loop()
    frame_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
    send_lock = asyncio.Lock()
    input_event = asyncio.Event()
    input_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)
    pending_move: dict | None = None
    pending_wheel: dict | None = None

    async def _send_payload(payload: dict) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(payload))

    def _on_frame(data: str) -> None:
        # Invoked on the private Playwright loop; hop to this loop and drop the
        # oldest frame when the client can't keep up (screencast is lossy).
        def _enqueue() -> None:
            if frame_queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    frame_queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                frame_queue.put_nowait(data)

        loop.call_soon_threadsafe(_enqueue)

    # Match the tool's session config (headless/viewport/cdp_url) so the live
    # stream reuses the same session the agent drives — including CDP-attach to
    # the user's real Chrome when configured.
    from deerflow.config import get_app_config

    tool_cfg = get_app_config().get_tool_config("browser_navigate")
    extra = (tool_cfg.model_extra or {}) if tool_cfg is not None else {}

    def _cfg_int(key: str, default: int) -> int:
        value = extra.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def _cfg_bool(key: str, default: bool) -> bool:
        value = extra.get(key)
        return value if isinstance(value, bool) else default

    def _cfg_str(key: str) -> str | None:
        value = extra.get(key)
        return value.strip() or None if isinstance(value, str) else None

    manager = get_browser_session_manager()
    try:
        session_lease = manager.acquire_session(
            thread_id,
            headless=_cfg_bool("headless", True),
            timeout_ms=_cfg_int("timeout_ms", 30000),
            viewport={"width": _cfg_int("viewport_width", 1280), "height": _cfg_int("viewport_height", 720)},
            cdp_url=_cfg_str("cdp_url"),
            allow_unguarded_cdp=_cfg_bool("allow_unguarded_cdp", False),
            url_guard=validate_browser_url,
        )
        session = session_lease.__enter__()
    except BrowserSessionCapacityError:
        await websocket.close(code=4429)
        reset_current_user(token)
        return
    except Exception:
        await websocket.close(code=4501)
        reset_current_user(token)
        return

    async def _pump_frames() -> None:
        while True:
            data = await frame_queue.get()
            await _send_payload({"type": "frame", "data": data})

    async def _send_url() -> None:
        # Report the page's real URL so the client's address bar reflects the
        # actual location after navigations, redirects, and history moves — not
        # the optimistic value the user typed.
        with contextlib.suppress(Exception):
            url = await session.current_url()
            if url:
                await _send_payload({"type": "url", "url": url})

    async def _send_tabs() -> None:
        with contextlib.suppress(Exception):
            tabs = await session.tabs()
            await _send_payload(
                {
                    "type": "tabs",
                    "tabs": [
                        {
                            "index": tab.index,
                            "title": tab.title,
                            "url": tab.url,
                            "active": tab.active,
                        }
                        for tab in tabs
                    ],
                },
            )

    async def _poll_location() -> None:
        # The agent drives the same session through its tools (browser_navigate /
        # click / type), which do not flow through this socket's input handler, so
        # those location changes would otherwise never reach the address bar/tabs.
        # Tool actions push their own settled Live frame after the inline
        # screenshot is captured; this poll only keeps URL/tabs metadata in sync.
        # Avoid screenshotting here, because opening a Live panel already primes a
        # frame and GitHub-style SPAs can generate many URL/render transitions.
        last_url: str | None = None
        while True:
            await asyncio.sleep(1.0)
            with contextlib.suppress(Exception):
                url = await session.current_url()
                if url and url != last_url:
                    last_url = url
                    await _send_payload({"type": "url", "url": url})
                    await _send_tabs()

    def _queue_input(event: dict) -> None:
        nonlocal pending_move, pending_wheel
        etype = event.get("type")
        if etype == "move":
            pending_move = event
        elif etype == "wheel":
            if pending_wheel is None:
                pending_wheel = event
            else:
                pending_wheel = {
                    **event,
                    "dx": float(pending_wheel.get("dx", 0)) + float(event.get("dx", 0)),
                    "dy": float(pending_wheel.get("dy", 0)) + float(event.get("dy", 0)),
                }
        else:
            pending_move = None
            pending_wheel = None
            if input_queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    input_queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                input_queue.put_nowait(event)
        input_event.set()

    def _has_pending_input() -> bool:
        return pending_move is not None or pending_wheel is not None or not input_queue.empty()

    def _take_input() -> dict | None:
        nonlocal pending_move, pending_wheel
        if not input_queue.empty():
            return input_queue.get_nowait()
        if pending_wheel is not None:
            event = pending_wheel
            pending_wheel = None
            return event
        if pending_move is not None:
            event = pending_move
            pending_move = None
            return event
        return None

    async def _read_inputs() -> None:
        while True:
            try:
                raw = await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                return
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(event, dict):
                _queue_input(event)

    async def _process_inputs() -> None:
        while True:
            await input_event.wait()
            while True:
                event = _take_input()
                if event is None:
                    input_event.clear()
                    if _has_pending_input():
                        input_event.set()
                    break
                if event.get("type") == "navigate":
                    # SSRF-screen client-driven navigations with the same policy
                    # the agent tools enforce; reject rather than dispatch.
                    url = event.get("url")
                    reason = validate_browser_url(url) if isinstance(url, str) else "Error: invalid navigation URL"
                    if reason is not None:
                        await _send_payload({"type": "nav_rejected", "url": url, "message": reason})
                        continue
                try:
                    await session.dispatch_input(event)
                except Exception as exc:
                    logger.warning("browser stream input failed: %s", exc)
                else:
                    # A location may have changed — resync the client's URL bar.
                    if event.get("type") in {"navigate", "back", "forward", "click", "activate_tab"}:
                        await _send_url()
                        await _send_tabs()

    pump_task = asyncio.create_task(_pump_frames())
    input_task: asyncio.Task | None = None
    reader_task: asyncio.Task | None = None
    poll_task: asyncio.Task | None = None
    try:
        # Seed the live page from the latest browser_view URL. A thread can have
        # a stale browser session from an earlier panel/live attempt; if that
        # page differs from the latest visible browser artifact, align Live with
        # what the user expects instead of requiring an off/on reconnect.
        seed = websocket.query_params.get("seed")
        if seed and validate_browser_url(seed) is None:
            with contextlib.suppress(Exception):
                current = await session.current_url()
                if _should_apply_browser_seed(current, seed):
                    await session.navigate(seed)
        try:
            await session.start_screencast(_on_frame)
        except BrowserLiveViewerError:
            await websocket.close(code=4409)
            return
        await _send_url()
        await _send_tabs()
        input_task = asyncio.create_task(_process_inputs())
        reader_task = asyncio.create_task(_read_inputs())
        poll_task = asyncio.create_task(_poll_location())
        await reader_task
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("browser stream error: thread_id=%s err=%s", thread_id, exc)
    finally:
        pump_task.cancel()
        if input_task is not None:
            input_task.cancel()
        if reader_task is not None:
            reader_task.cancel()
        if poll_task is not None:
            poll_task.cancel()
        with contextlib.suppress(Exception):
            await session.stop_screencast(_on_frame)
        session_lease.__exit__(None, None, None)
        reset_current_user(token)
