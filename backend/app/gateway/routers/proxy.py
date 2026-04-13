"""Reverse-proxy router that absorbs the responsibilities formerly handled
by the nginx sidecar (``docker/nginx/*``).

The gateway is now the public entry point for DeerFlow. nginx used to do four
things in front of it: route ``/api/langgraph/*`` to the LangGraph server,
route ``/api/sandboxes`` to the sandbox provisioner, fall everything else
through to the Next.js frontend, and add CORS headers. CORS is now handled
by ``fastapi.middleware.cors.CORSMiddleware`` registered on the gateway app;
the routing is handled by this router.

Routes registered (registration order matters — most-specific first):

* ``/api/langgraph/{path:path}`` →
  ``$DEERFLOW_PROXY_LANGGRAPH_UPSTREAM$DEERFLOW_PROXY_LANGGRAPH_REWRITE{path}``.
  Default upstream ``http://langgraph:2024`` and rewrite ``/`` reproduce
  nginx's standard mode. In gateway mode, set the upstream back to the
  gateway itself and rewrite to ``/api/`` to dispatch to the LangGraph
  Platform-compat routers (assistants_compat, runs, thread_runs).

* ``/api/sandboxes`` and ``/api/sandboxes/{path:path}`` →
  ``$DEERFLOW_PROXY_PROVISIONER_UPSTREAM/api/sandboxes...``.
  Default upstream ``http://provisioner:8002``. Marked as *optional*: when
  the provisioner container is not running, requests fail with HTTP 503
  instead of bringing down the rest of the API. This matches the lazy
  resolution nginx used for the provisioner upstream.

* ``/{path:path}`` → ``$DEERFLOW_PROXY_FRONTEND_UPSTREAM/{path}``.
  Default upstream ``http://frontend:3000``. Catches every path not owned
  by another router (the Next.js app + static assets). A defensive check
  rejects paths whose first segment is owned by the gateway (e.g., ``api/``,
  ``docs``, ``health``) so a missing API route returns 404 instead of
  silently being proxied to the frontend.

A WebSocket route mirrors the frontend HTTP catch-all so the Next.js dev
server's HMR socket (``/_next/webpack-hmr``) works through the gateway. It
uses the ``websockets`` library that already ships with ``uvicorn[standard]``.

Streaming behaviour matches nginx's old ``proxy_buffering off`` +
``proxy_read_timeout 600s`` configuration: request and response bodies are
streamed via httpx, with a 600s read/write timeout. SSE responses pass
through unmodified, large file uploads are streamed (no body buffering, no
size cap), and hop-by-hop headers are stripped on both directions.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Configuration helpers ────────────────────────────────────────────────────


def _normalize_upstream(value: str) -> str:
    """Normalize an upstream URL: strip trailing slash, add http:// scheme."""
    value = value.strip().rstrip("/")
    if not value:
        return value
    if "://" not in value:
        value = f"http://{value}"
    return value


def _normalize_rewrite(value: str) -> str:
    """Normalize a rewrite prefix: must start AND end with a single slash."""
    value = value.strip()
    if not value.startswith("/"):
        value = "/" + value
    if not value.endswith("/"):
        value = value + "/"
    return value


def _langgraph_upstream() -> str:
    return _normalize_upstream(os.getenv("DEERFLOW_PROXY_LANGGRAPH_UPSTREAM", "http://langgraph:2024"))


def _langgraph_rewrite() -> str:
    return _normalize_rewrite(os.getenv("DEERFLOW_PROXY_LANGGRAPH_REWRITE", "/"))


def _provisioner_upstream() -> str:
    return _normalize_upstream(os.getenv("DEERFLOW_PROXY_PROVISIONER_UPSTREAM", "http://provisioner:8002"))


def _frontend_upstream() -> str:
    return _normalize_upstream(os.getenv("DEERFLOW_PROXY_FRONTEND_UPSTREAM", "http://frontend:3000"))


# Long timeout for streaming/SSE (matches nginx's old ``proxy_read_timeout 600s``).
PROXY_TIMEOUT = httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=30.0)


# Path prefixes/exact matches owned by the gateway itself. The frontend
# catch-all must NOT swallow these — if no more-specific route matched, return
# 404 rather than silently forwarding internal paths to the Next.js app.
GATEWAY_OWNED_EXACT: frozenset[str] = frozenset(
    {
        "api",
        "docs",
        "redoc",
        "openapi.json",
        "health",
    }
)
GATEWAY_OWNED_PREFIXES: tuple[str, ...] = (
    "api/",
    "docs/",
    "redoc/",
    "health/",
)


def _is_gateway_owned(path: str) -> bool:
    """Return True if ``path`` (no leading slash) is owned by another route."""
    if path in GATEWAY_OWNED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in GATEWAY_OWNED_PREFIXES)


# Hop-by-hop headers that must not be forwarded across the proxy boundary
# (RFC 7230 §6.1). Plus a few that httpx/Starlette compute themselves and
# would conflict if forwarded verbatim.
_HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

PROXY_METHODS: tuple[str, ...] = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")


def _build_forward_headers(
    headers: Iterable[tuple[str, str]],
    *,
    client_host: str | None,
    scheme: str,
    host: str,
) -> dict[str, str]:
    """Copy request headers, dropping hop-by-hop and adding X-Forwarded-*."""
    forwarded: dict[str, str] = {}
    existing_xff = ""
    for key, value in headers:
        lower = key.lower()
        if lower in _HOP_BY_HOP_HEADERS:
            continue
        if lower == "x-forwarded-for":
            existing_xff = value
            continue
        forwarded[key] = value
    if client_host:
        forwarded["X-Forwarded-For"] = f"{existing_xff}, {client_host}" if existing_xff else client_host
        forwarded["X-Real-IP"] = client_host
    elif existing_xff:
        forwarded["X-Forwarded-For"] = existing_xff
    forwarded["X-Forwarded-Proto"] = scheme
    if host:
        forwarded["X-Forwarded-Host"] = host
    return forwarded


def _filter_response_raw_headers(headers: httpx.Headers) -> list[tuple[bytes, bytes]]:
    """Build raw (bytes, bytes) header tuples for a Starlette response.

    We must use ``httpx.Headers.multi_items()`` and set Starlette's
    ``raw_headers`` directly because:

    1. ``httpx.Headers.items()`` collapses duplicate-name headers into a
       single comma-joined value, which is correct for most headers but
       *wrong* for ``Set-Cookie`` (RFC 6265 forbids comma-joining since
       cookie expiry dates contain commas).
    2. ``StreamingResponse(headers=mapping)`` only accepts a ``Mapping``
       and goes through ``.items()``, which would silently drop duplicate
       keys even if we passed a list.

    Setting ``raw_headers`` after constructing the response bypasses both
    issues and preserves every individual header entry as-is.
    """
    return [(key.encode("latin-1"), value.encode("latin-1")) for key, value in headers.multi_items() if key.lower() not in _HOP_BY_HOP_HEADERS]


# ── Core HTTP proxy ──────────────────────────────────────────────────────────


async def _proxy_http(
    request: Request,
    upstream_base: str,
    upstream_path: str,
    *,
    optional: bool = False,
) -> Response:
    """Stream a single HTTP request to an upstream and stream the response back.

    Args:
        request: Incoming Starlette request.
        upstream_base: Normalized base URL of the upstream (e.g. ``http://frontend:3000``).
        upstream_path: Path to append to the base, must start with ``/``.
        optional: If True, connection failures return HTTP 503 instead of 502.
            Used for the sandbox provisioner which is not always running.
    """
    client: httpx.AsyncClient | None = getattr(request.app.state, "proxy_client", None)
    owns_client = False
    if client is None:
        # Fallback for tests / standalone use that don't run the gateway lifespan.
        client = httpx.AsyncClient(timeout=PROXY_TIMEOUT, follow_redirects=False)
        owns_client = True

    target_url = f"{upstream_base}{upstream_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    forwarded_headers = _build_forward_headers(
        request.headers.items(),
        client_host=request.client.host if request.client else None,
        scheme=request.url.scheme,
        host=request.headers.get("host", ""),
    )

    has_body = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
    request_kwargs: dict = {
        "method": request.method,
        "url": target_url,
        "headers": forwarded_headers,
    }
    if has_body:
        request_kwargs["content"] = request.stream()

    try:
        upstream_request = client.build_request(**request_kwargs)
        upstream_response = await client.send(upstream_request, stream=True)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
        if owns_client:
            await client.aclose()
        if optional:
            logger.warning("Optional upstream %s unavailable: %s", upstream_base, exc)
            raise HTTPException(status_code=503, detail=f"Upstream {upstream_base} unavailable") from exc
        logger.exception("Failed to reach upstream %s", upstream_base)
        raise HTTPException(status_code=502, detail=f"Bad gateway: {upstream_base}") from exc
    except httpx.HTTPError as exc:
        if owns_client:
            await client.aclose()
        logger.exception("Proxy error for upstream %s", upstream_base)
        raise HTTPException(status_code=502, detail="Bad gateway") from exc

    raw_response_headers = _filter_response_raw_headers(upstream_response.headers)
    media_type = upstream_response.headers.get("content-type")

    async def body_iter():
        try:
            # In production, ``client.send(stream=True)`` returns an open
            # stream and ``aiter_raw()`` yields chunks as they arrive. In
            # tests using ``httpx.MockTransport``, the response is created
            # with pre-buffered ``content=bytes`` which sets
            # ``is_stream_consumed`` immediately — fall back to the buffered
            # ``content`` attribute in that case so tests don't need a real
            # streaming transport.
            if upstream_response.is_stream_consumed:
                if upstream_response.content:
                    yield upstream_response.content
                return
            async for chunk in upstream_response.aiter_raw():
                yield chunk
        finally:
            await upstream_response.aclose()
            if owns_client:
                await client.aclose()

    response = StreamingResponse(
        body_iter(),
        status_code=upstream_response.status_code,
        media_type=media_type,
    )
    # Override raw_headers AFTER construction so duplicate-name headers like
    # ``Set-Cookie`` are preserved verbatim. Starlette's ``init_headers``
    # collapses duplicates via ``Mapping.items()``.
    response.raw_headers = raw_response_headers
    return response


# ── HTTP proxy routes ────────────────────────────────────────────────────────


@router.api_route(
    "/api/langgraph/{path:path}",
    methods=list(PROXY_METHODS),
    include_in_schema=False,
)
async def langgraph_proxy(path: str, request: Request) -> Response:
    """Proxy ``/api/langgraph/<path>`` to the configured LangGraph upstream."""
    upstream_path = f"{_langgraph_rewrite()}{path}"
    return await _proxy_http(request, _langgraph_upstream(), upstream_path)


@router.api_route(
    "/api/sandboxes",
    methods=list(PROXY_METHODS),
    include_in_schema=False,
)
async def provisioner_proxy_root(request: Request) -> Response:
    """Proxy ``/api/sandboxes`` (no trailing path) to the sandbox provisioner."""
    return await _proxy_http(request, _provisioner_upstream(), "/api/sandboxes", optional=True)


@router.api_route(
    "/api/sandboxes/{path:path}",
    methods=list(PROXY_METHODS),
    include_in_schema=False,
)
async def provisioner_proxy_sub(path: str, request: Request) -> Response:
    """Proxy ``/api/sandboxes/<path>`` to the sandbox provisioner."""
    return await _proxy_http(request, _provisioner_upstream(), f"/api/sandboxes/{path}", optional=True)


@router.api_route(
    "/{path:path}",
    methods=list(PROXY_METHODS),
    include_in_schema=False,
)
async def frontend_proxy(path: str, request: Request) -> Response:
    """Catch-all proxy to the frontend. MUST be the last route registered."""
    if _is_gateway_owned(path):
        raise HTTPException(status_code=404)
    return await _proxy_http(request, _frontend_upstream(), f"/{path}")


# ── WebSocket proxy ──────────────────────────────────────────────────────────
# Next.js's dev server uses a WebSocket at /_next/webpack-hmr for Hot Module
# Replacement. The ``websockets`` library ships with ``uvicorn[standard]``,
# so this requires no extra dependency.


@router.websocket("/{path:path}")
async def frontend_ws_proxy(websocket: WebSocket, path: str) -> None:
    if _is_gateway_owned(path):
        await websocket.close(code=1008)
        return

    try:
        import websockets
    except ImportError:
        logger.warning("websockets package not available; cannot proxy WebSocket /%s", path)
        await websocket.close(code=1011)
        return

    upstream_url = _frontend_upstream().replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    upstream_url = f"{upstream_url}/{path}"
    if websocket.url.query:
        upstream_url = f"{upstream_url}?{websocket.url.query}"

    excluded_headers = {
        "host",
        "upgrade",
        "connection",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
        "sec-websocket-accept",
        "content-length",
    }
    forward_headers = [(k, v) for k, v in websocket.headers.items() if k.lower() not in excluded_headers]

    await websocket.accept()

    # ``additional_headers`` was renamed from ``extra_headers`` in
    # websockets 13. Try the new name, fall back to the old.
    upstream = None
    try:
        try:
            upstream = await websockets.connect(
                upstream_url,
                additional_headers=forward_headers,
                max_size=None,
            )
        except TypeError:
            upstream = await websockets.connect(
                upstream_url,
                extra_headers=forward_headers,
                max_size=None,
            )
    except Exception:
        logger.exception("Failed to open upstream WebSocket to %s", upstream_url)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
        return

    async def client_to_upstream() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if message.get("bytes") is not None:
                    await upstream.send(message["bytes"])
                elif message.get("text") is not None:
                    await upstream.send(message["text"])
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("Client→upstream WebSocket forwarding error")

    async def upstream_to_client() -> None:
        try:
            async for message in upstream:
                if isinstance(message, (bytes, bytearray, memoryview)):
                    await websocket.send_bytes(bytes(message))
                else:
                    await websocket.send_text(message)
        except Exception:
            logger.exception("Upstream→client WebSocket forwarding error")

    # Use ``FIRST_COMPLETED`` so that when *either* side disconnects we
    # immediately cancel the *other* direction. Plain ``asyncio.gather``
    # would block forever on the still-listening half and leak the
    # websocket connection until the read timeout fires.
    client_task = asyncio.create_task(client_to_upstream())
    upstream_task = asyncio.create_task(upstream_to_client())
    try:
        _done, pending = await asyncio.wait(
            {client_task, upstream_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        # Drain the cancelled tasks so their ``finally`` blocks run and any
        # exceptions surface in logs (but don't propagate out of cleanup).
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        try:
            await upstream.close()
        except Exception:
            pass
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
