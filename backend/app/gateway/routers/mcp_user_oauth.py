"""Browser-owned grants for operator-configured MCP connections."""

import asyncio
import hashlib
import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME
from app.gateway.csrf_middleware import is_secure_request
from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.auth import require_session_source
from deerflow.config.extensions_config import MCP_USER_OAUTH_CALLBACK_PATH
from deerflow.mcp import browser_oauth as oauth
from deerflow.mcp.oauth_store import McpOAuthTokenKey, McpOAuthTokenStoreUnavailable, get_mcp_oauth_token_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mcp/user-oauth", tags=["mcp"])
_STATE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_LANDING = "/workspace/capabilities?tab=plugins&mcp_oauth={status}#my-mcp-connections"


class Connection(BaseModel):
    server_key: str
    display_name: str
    status: str


class Connections(BaseModel):
    connections: list[Connection]


async def _owner(request: Request) -> str:
    require_session_source(request)
    user = await get_current_user_from_request(request)
    return str(user.id)


def _browser_binding(request: Request, nonce: str) -> str:
    # Bind this browser attempt to the exact authenticated login session.
    session = request.cookies[ACCESS_TOKEN_COOKIE_NAME]
    return hashlib.sha256(f"{session}:{nonce}".encode()).hexdigest()


def _store():
    store = get_mcp_oauth_token_store()
    if store is None:
        raise HTTPException(503, "MCP user OAuth requires shared SQL storage.")
    return store


async def _servers():
    try:
        return await asyncio.to_thread(oauth.configured_servers)
    except Exception:
        raise HTTPException(503, "MCP server configuration is unavailable.") from None


async def _server(name):
    server = (await _servers()).get(name)
    if server is None:
        raise HTTPException(404, "This MCP server does not offer user authorization.")
    return server


@router.get("", response_model=Connections)
async def list_connections(response: Response, owner: str = Depends(_owner)):
    servers = await _servers()

    def list_rows():
        result = []
        for name, server in servers.items():
            try:
                state = oauth.connection_state(name, server, owner)
            except McpOAuthTokenStoreUnavailable:
                state = "unavailable"
            result.append(Connection(server_key=name, display_name=name, status=state))
        store = get_mcp_oauth_token_store()
        if store is not None:
            try:
                saved = store.list_delegated_servers(owner)
            except McpOAuthTokenStoreUnavailable:
                raise HTTPException(503, "MCP authorization storage is unavailable.") from None
            result.extend(Connection(server_key=name, display_name=name, status="removed") for name in saved if name not in servers)
        return result

    response.headers["Cache-Control"] = "no-store"
    return Connections(connections=await asyncio.to_thread(list_rows))


@router.post("/{server_key}/connect")
async def connect(server_key: str, request: Request, owner: str = Depends(_owner)):
    _store()
    server = await _server(server_key)
    state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    try:
        destination = await oauth.begin_connection(server_key, server, owner, _browser_binding(request, binding), state)
    except oauth.BrowserOAuthError as exc:
        raise HTTPException(502, str(exc)) from None
    except McpOAuthTokenStoreUnavailable:
        raise HTTPException(503, "MCP authorization storage is unavailable.") from None
    except Exception:
        raise HTTPException(502, "Could not start MCP authorization. Check the server configuration.") from None
    response = JSONResponse({"authorization_url": destination}, headers={"Cache-Control": "no-store"})
    response.set_cookie("df_mcp_" + state, binding, max_age=300, path=MCP_USER_OAUTH_CALLBACK_PATH, httponly=True, samesite="lax", secure=is_secure_request(request))
    return response


@router.get("/callback", response_class=RedirectResponse)
async def callback(request: Request, owner: str = Depends(_owner)):
    state = request.query_params.get("state", "")
    valid_state = bool(_STATE.fullmatch(state))
    cookie = "df_mcp_" + state if valid_state else ""
    binding = request.cookies.get(cookie) if cookie else None
    ok = False
    if binding:
        try:
            attempt = await asyncio.to_thread(_store().consume_delegated, state, owner_user_id=owner, browser_binding=_browser_binding(request, binding))
            code = request.query_params.get("code")
            issued_by = request.query_params.get("iss")
            if attempt and code and len(code) <= 8192 and not request.query_params.get("error") and (issued_by is None or issued_by == attempt.context.issuer):
                server = await _server(attempt.key.server_key)
                ok = await oauth.finish_connection(attempt, server, code)
        except Exception as exc:
            # Provider and storage exceptions may contain credentials.
            logger.warning("MCP user OAuth callback failed (%s)", type(exc).__name__)
    response = RedirectResponse(_LANDING.format(status="connected" if ok else "failed"), status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    if cookie:
        response.delete_cookie(cookie, path=MCP_USER_OAUTH_CALLBACK_PATH, httponly=True, samesite="lax", secure=is_secure_request(request))
    return response


@router.delete("/{server_key}", status_code=204)
async def disconnect(server_key: str, owner: str = Depends(_owner)):
    try:
        await asyncio.to_thread(_store().disconnect_delegated, McpOAuthTokenKey.for_delegated(server_key, owner))
    except McpOAuthTokenStoreUnavailable:
        raise HTTPException(503, "MCP authorization storage is unavailable.") from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
