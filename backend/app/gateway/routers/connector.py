"""Proxy router for AnyConnect admin API.

Forwards browser requests to an AnyConnect runtime so the wasp frontend
can manage connector providers, connections, and OAuth flows without
talking to AnyConnect directly.  Wasp stores nothing — AnyConnect
remains the sole source of truth for credentials, connections, and run
logs.
"""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/connector", tags=["connector"])

logger = logging.getLogger(__name__)

_USERID_HEADER = "x-ac-connector-userid"

_CONTENT_HEADERS = {"content-type"}
# Only forward these request headers to AnyConnect.  Never forward browser
# credentials (Cookie, Authorization) or session metadata — the connector
# proxy supplies its own app-scoped Authorization unconditionally.
_REQUEST_HEADER_ALLOWLIST = frozenset(
    {
        "accept",
        "content-type",
        "user-agent",
    }
)

# httpx exceptions that mean AnyConnect is unreachable — treat as
# "no data available" rather than a server error so the frontend can
# render an empty state instead of an error page.
_UNREACHABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
    httpx.WriteTimeout,
)


def _get_connector_auth_header() -> str | None:
    """Return the Authorization header configured for the connectors MCP server."""
    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        config = ExtensionsConfig.from_file()
        server_cfg = config.mcp_servers.get("connectors")
        if server_cfg is None:
            logger.warning("No 'connectors' entry in extensions_config mcpServers — proxy requests will lack auth")
            return None
        if not server_cfg.enabled:
            logger.warning("Connectors MCP server is disabled — proxy requests will lack auth")
            return None
        headers = server_cfg.headers or {}
        auth = headers.get("Authorization") or headers.get("authorization")
        if not auth:
            logger.warning("No Authorization header configured for connectors — proxy requests will lack auth")
        return auth
    except Exception:
        logger.warning("Cannot read connector auth header", exc_info=True)
        return None


def _get_connector_server_config():
    """Return the connectors MCP server config, or None if absent/disabled."""
    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        config = ExtensionsConfig.from_file()
        server_cfg = config.mcp_servers.get("connectors")
        if server_cfg and server_cfg.enabled:
            return server_cfg
    except Exception:
        logger.debug("Cannot read connector server config", exc_info=True)
    return None


def _get_connector_base_url() -> str | None:
    """Return the AnyConnect base URL from extensions config, or None if not configured."""
    server_cfg = _get_connector_server_config()
    if server_cfg and server_cfg.url:
        url = server_cfg.url.rstrip("/")
        if url.endswith("/mcp"):
            return url[:-4]
        return url
    return None


def _oc_url(path: str) -> str | None:
    """Build a full AnyConnect URL for *path* (must start with ``/``).

    Returns None when the connector is not configured or disabled.
    """
    base = _get_connector_base_url()
    if base is None:
        return None
    return f"{base}{path}"


def _resolve_connector_user_id(request: Request) -> str | None:
    """Return the current user id, or ``None`` if unavailable.

    Uses DeerFlow's ``get_effective_user_id`` so the same account isolation
    that applies to threads/memory also applies to connector connections.
    """
    from deerflow.runtime.user_context import get_effective_user_id

    try:
        user_id = get_effective_user_id()
        logger.info("Connector user id resolved: %s", user_id)
        if user_id and user_id != "default":
            return user_id
    except Exception:
        logger.debug("Cannot resolve connector user id", exc_info=True)
    return None


def _inject_user_id(headers: dict[str, str], user_id: str | None) -> None:
    """Inject the ``x-ac-connector-userid`` header into *headers*.

    Only sets the header when *user_id* is non-empty, so the default
    connection is used when there is no per-user identifier.
    """
    if user_id:
        headers[_USERID_HEADER] = user_id


async def _proxy(
    request: Request,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
) -> StreamingResponse:
    """Forward *request* to AnyConnect and stream the response back."""
    # Build headers from a narrow allowlist — never forward browser
    # credentials (Cookie) or session tokens.
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        if k.lower() in _REQUEST_HEADER_ALLOWLIST:
            headers[k] = v
    _inject_user_id(headers, _resolve_connector_user_id(request))
    # Always set the configured connector app credential.
    auth = _get_connector_auth_header()
    if auth:
        headers["Authorization"] = auth
    url = _oc_url(path)
    if url is None:
        logger.warning("Connector is not configured or disabled — refusing to proxy %s %s", method, path)
        return _json_response({}, status_code=503)
    logger.debug("connector proxy: %s %s", method, url)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        upstream = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body or request.stream(),
            follow_redirects=False,
        )

    # Only forward content-related headers, not transport ones.
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() in _CONTENT_HEADERS}

    # For OAuth redirects, rewrite the Location header so the browser
    # comes back to wasp instead of landing on AnyConnect directly.
    if 300 <= upstream.status_code < 400:
        loc = upstream.headers.get("location")
        if loc and loc.startswith(_get_connector_base_url()):
            # Relative redirects are fine; rewrite absolute ones that
            # point back to the OC origin.
            rewritten = loc.replace(_get_connector_base_url(), "", 1)
            response_headers["location"] = rewritten
        elif loc and loc.startswith("/oauth/callback"):
            # Already relative — pass through as-is.
            response_headers["location"] = loc

    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def _proxy_raw(
    request: Request,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
) -> httpx.Response:
    """Forward *request* to AnyConnect and return the full httpx Response."""
    # Build headers from a narrow allowlist — never forward browser
    # credentials (Cookie) or session tokens.
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        if k.lower() in _REQUEST_HEADER_ALLOWLIST:
            headers[k] = v
    _inject_user_id(headers, _resolve_connector_user_id(request))
    # Always set the configured connector app credential.
    auth = _get_connector_auth_header()
    if auth:
        headers["Authorization"] = auth
    url = _oc_url(path)
    if url is None:
        raise RuntimeError("Connector is not configured or disabled")
    logger.debug("connector proxy (raw): %s %s", method, url)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        return await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body or request.stream(),
            follow_redirects=False,
        )


def _is_connector_unreachable(exc: Exception) -> bool:
    """Return True when *exc* means AnyConnect is unreachable."""
    return isinstance(exc, _UNREACHABLE_EXCEPTIONS)


async def _proxy_raw_safe(
    request: Request,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
) -> httpx.Response | None:
    """Like :func:`_proxy_raw` but returns ``None`` when AnyConnect is unreachable."""
    try:
        return await _proxy_raw(request, method, path, body=body)
    except _UNREACHABLE_EXCEPTIONS:
        logger.warning(
            "AnyConnect unreachable at %s (request: %s %s)",
            _get_connector_base_url(),
            method,
            path,
        )
        return None


async def _read_upstream_body(upstream: httpx.Response) -> bytes:
    """Drain the upstream response body into bytes."""
    return await upstream.aread()


def _json_response(data: object, status_code: int = 200) -> StreamingResponse:
    """Return a StreamingResponse with JSON-encoded *data*."""
    import json as _json

    content = _json.dumps(data, ensure_ascii=False, default=str)
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        status_code=status_code,
        media_type="application/json",
    )


# ── Provider catalogue (read-only, public) ───────────────────────────


@router.get("/providers")
async def list_providers(request: Request) -> StreamingResponse:
    """List available provider apps scoped to the configured app API key.

    Returns an empty list when the connector is not configured, disabled,
    or unreachable so the frontend can render an empty state.
    """
    if _get_connector_server_config() is None:
        return _json_response({"providers": []})
    upstream = await _proxy_raw_safe(request, "GET", "/v1/providers")
    if upstream is None or not upstream.is_success:
        return _json_response({"providers": []})
    body = await _read_upstream_body(upstream)
    try:
        envelope = json.loads(body) if body else {}
    except json.JSONDecodeError:
        envelope = {}
    data = envelope.get("data", []) if isinstance(envelope, dict) else []
    return _json_response({"providers": data})


@router.get("/providers/{service:path}")
async def get_provider(request: Request, service: str) -> StreamingResponse:
    """Get a single provider's detail including actions and auth config."""
    return await _proxy(request, "GET", f"/api/providers/{service}")


# ── Connections (per-user) ───────────────────────────────────────────


@router.get("/connections")
async def list_connections(request: Request) -> StreamingResponse:
    """List connections for the current user, wrapped as ``{connections: [...]}``.

    Returns an empty list when the connector is not configured, disabled,
    or unreachable.
    """
    if _get_connector_server_config() is None:
        return _json_response({"connections": []})
    user_id = _resolve_connector_user_id(request) or "default"
    upstream = await _proxy_raw_safe(request, "GET", f"/v1/connections?userId={user_id}")
    if upstream is None or not upstream.is_success:
        return _json_response({"connections": []})
    body = await _read_upstream_body(upstream)
    try:
        envelope = json.loads(body) if body else {}
    except json.JSONDecodeError:
        envelope = {}
    data = envelope.get("data", []) if isinstance(envelope, dict) else []
    return _json_response({"connections": data})


@router.put("/connections/{service:path}")
async def upsert_connection(request: Request, service: str) -> StreamingResponse:
    """Create or replace a connection for the configured app."""
    body = await request.body()
    return await _proxy(request, "PUT", f"/v1/connections/{service}", body=body)


@router.delete("/connections/{service:path}")
async def delete_connection(request: Request, service: str) -> StreamingResponse:
    """Remove the configured app's connection."""
    return await _proxy(request, "DELETE", f"/v1/connections/{service}")


# ── OAuth ─────────────────────────────────────────────────────────────


@router.post("/oauth/authorize")
async def oauth_authorize(request: Request) -> StreamingResponse:
    """Start an OAuth authorization flow. Returns the redirect URL."""
    body = await request.body()
    return await _proxy(request, "POST", "/v1/oauth/authorizations", body=body)


@router.get("/oauth/callback")
@router.post("/oauth/callback")
async def oauth_callback(request: Request) -> StreamingResponse:
    """Handle OAuth callback — AnyConnect exchanges the code for tokens."""
    return await _proxy(
        request,
        request.method,
        f"/oauth/callback?{request.url.query}",
    )


# ── Actions (read-only discovery) ─────────────────────────────────────


@router.get("/actions")
async def list_actions(request: Request) -> StreamingResponse:
    """List or search actions scoped to the configured app."""
    return await _proxy(request, "GET", f"/v1/actions?{request.url.query}")


@router.get("/actions/{action_id:path}")
async def get_action(request: Request, action_id: str) -> StreamingResponse:
    """Get a single action's detail."""
    return await _proxy(request, "GET", f"/api/actions/{action_id}")
