"""Owner-only MCP configuration. Deployment MCP routes remain admin-only."""

import asyncio
import logging
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.gateway.deps import get_current_user_from_request, is_admin_user
from app.gateway.routers import mcp
from deerflow.capabilities.runtime import ambiguous_installation_ids
from deerflow.config.extensions_config import ExtensionsConfig, atomic_write_extensions_config, extensions_config_file_lock, extensions_config_write_lock
from deerflow.mcp.user_config import read_user_mcp_config, user_mcp_config_path
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/personal/config", tags=["mcp"])


async def _drained_mutation[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a personal-config mutation off the event loop and drain it across cancellation.

    A client that disconnects mid-request cancels the handler task: with a bare
    ``asyncio.to_thread`` a still-queued mutation never runs — the user's change
    silently vanishes — and a running one's failure is dropped because the
    handler's ``except`` never runs. ``await_drained`` lets the mutation finish
    first; its failure is logged with the exception type only — the text can
    carry configuration details — and 4xx ``HTTPException``s stay unlogged:
    they are caller-facing contracts the connected client still receives.
    """

    def _logged() -> T:
        try:
            return func(*args, **kwargs)
        except HTTPException as exc:
            if exc.status_code >= 500:
                logger.error("Personal MCP config mutation failed (HTTP %d)", exc.status_code)
            raise
        except Exception as exc:
            logger.error("Personal MCP config mutation failed (%s)", type(exc).__name__)
            raise

    return await await_drained(asyncio.to_thread(_logged))


async def _owner(request: Request) -> str:
    user = await get_current_user_from_request(request)
    return str(user.id)


def _response(raw: dict) -> mcp.McpConfigResponse:
    return mcp.McpConfigResponse(mcp_servers={name: mcp._mask_server_config(server) for name, server in mcp._mcp_server_responses_from_raw(raw).items()})


def _read_personal_config(user_id: str) -> dict:
    try:
        return read_user_mcp_config(user_id)
    except ValueError as exc:
        mcp._raise_invalid_mcp_configuration(str(exc), cause=exc)


def _validate_personal_server(server: mcp.McpServerConfigResponse, *, admin: bool) -> None:
    # A personal store must not grant ordinary users the deployment operator's
    # ability to launch arbitrary host packages or query internal services.
    if not admin:
        from deerflow.capabilities.business import is_bundled_connection

        bundled = server.type == "stdio" and is_bundled_connection(server.command, server.args, server.env) and not server.cwd
        if (server.type not in {"http", "sse"} and not bundled) or server.oauth is not None:
            raise HTTPException(403, "Only an administrator may configure host commands or OAuth token endpoints")
        from deerflow.community.url_safety import validate_public_http_url

        if not bundled and (not server.url or validate_public_http_url(server.url, action="connect to")):
            raise HTTPException(400, "Personal MCP connections require a public HTTP(S) endpoint")
    mcp._validate_mcp_update_request(mcp.McpConfigUpdateRequest(mcp_servers={"personal": server}))


def _mutate(user_id: str, operation: Literal["create", "update", "delete", "state"], body, *, admin: bool) -> dict:
    path = user_mcp_config_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with extensions_config_write_lock, extensions_config_file_lock(path):
        raw = _read_personal_config(user_id)
        servers = mcp._raw_mcp_servers(raw)
        if operation == "create":
            for name, incoming in body.mcp_servers.items():
                if name in servers:
                    raise HTTPException(409, f"MCP server '{name}' already exists")
                mcp._ensure_no_masked_secrets(incoming)
                _validate_personal_server(incoming, admin=admin)
                definition = incoming.model_dump()
                metadata = definition.get("capability")
                definition["capability"] = {**(metadata if isinstance(metadata, dict) else {}), "id": str(uuid4())}
                definition["personal_public_network"] = not admin
                servers[name] = definition
        else:
            name = body if operation == "delete" else body.server_name
            if name not in servers:
                raise HTTPException(404, "MCP server not found")
            if operation == "delete":
                del servers[name]
            elif operation == "update":
                merged = mcp._merge_preserving_secrets(body.server, mcp._mcp_server_response_from_raw(name, servers[name]), preserve_omitted_fields=False)
                _validate_personal_server(merged, admin=admin)
                servers[name] = {**merged.model_dump(), "personal_public_network": not admin}
            else:
                if body.enabled:
                    _validate_personal_server(mcp._mcp_server_response_from_raw(name, servers[name]), admin=admin)
                    servers[name]["personal_public_network"] = not admin
                servers[name]["enabled"] = body.enabled
        candidate = {"mcpServers": servers}
        try:
            # No environment expansion: these are caller-owned literal values.
            ExtensionsConfig.model_validate(candidate)
        except ValidationError:
            raise HTTPException(400, "Invalid personal MCP configuration") from None
        if ambiguous_installation_ids(servers):
            raise HTTPException(400, "Duplicate MCP installation IDs")
        atomic_write_extensions_config(path, candidate)
        path.chmod(0o600)
        return candidate


@router.get("", response_model=mcp.McpConfigResponse)
async def get_configuration(request: Request):
    owner = await _owner(request)
    return _response(await asyncio.to_thread(_read_personal_config, owner))


async def _write(request: Request, operation: str, body):
    owner = await _owner(request)
    admin = await is_admin_user(request)
    raw = await _drained_mutation(_mutate, owner, operation, body, admin=admin)
    return _response(raw)


@router.post("/servers", response_model=mcp.McpConfigResponse)
async def create_servers(request: Request, body: mcp.McpConfigUpdateRequest):
    return await _write(request, "create", body)


@router.put("/server", response_model=mcp.McpConfigResponse)
async def update_server(request: Request, body: mcp.McpServerConfigUpdateRequest):
    return await _write(request, "update", body)


@router.patch("", response_model=mcp.McpConfigResponse)
async def update_state(request: Request, body: mcp.McpServerStateUpdateRequest):
    return await _write(request, "state", body)


@router.delete("/servers/{server_name:path}", response_model=mcp.McpConfigResponse)
async def delete_server(request: Request, server_name: str):
    return await _write(request, "delete", server_name)
