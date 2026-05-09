import json
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config
from deerflow.config.server_presets import get_oauth_preset, list_oauth_presets
from deerflow.mcp.google_oauth import build_authorization_url, exchange_code_for_tokens
from deerflow.mcp.oauth_session import get_session_store, pkce_challenge
from deerflow.mcp.secrets import encrypt_server_sensitive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mcp"])


def _maybe_encrypt(server: dict) -> dict:
    """Encrypt sensitive fields when ``MCP_ENCRYPT_SECRETS`` is opted in.

    Default is plaintext: an earlier wiring of always-on encryption broke
    LangGraph's MCP spawns when its long-lived process kept reading values
    through a stale module cache (see commit 2ee972bf). This makes the
    write path opt-in so operators can flip it on once they're ready to
    restart LangGraph alongside the Gateway.
    """
    if os.environ.get("MCP_ENCRYPT_SECRETS", "").lower() in ("1", "true", "yes"):
        return encrypt_server_sensitive(server)
    return server


class McpOAuthConfigResponse(BaseModel):
    """OAuth configuration for an MCP server."""

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(default="", description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(default="client_credentials", description="OAuth grant type")
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience")
    token_field: str = Field(default="access_token", description="Token response field containing access token")
    token_type_field: str = Field(default="token_type", description="Token response field containing token type")
    expires_in_field: str = Field(default="expires_in", description="Token response field containing expires-in seconds")
    default_token_type: str = Field(default="Bearer", description="Default token type when response omits token_type")
    refresh_skew_seconds: int = Field(default=60, description="Refresh this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")


class McpServerConfigResponse(BaseModel):
    """Response model for MCP server configuration."""

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfigResponse | None = Field(default=None, description="OAuth configuration for MCP HTTP/SSE servers")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")


class McpConfigResponse(BaseModel):
    """Response model for MCP configuration."""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
    )


class McpConfigUpdateRequest(BaseModel):
    """Request model for updating MCP configuration."""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        ...,
        description="Map of MCP server name to configuration",
    )


@router.get(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Get MCP Configuration",
    description="Retrieve the current Model Context Protocol (MCP) server configurations.",
)
async def get_mcp_configuration() -> McpConfigResponse:
    """Get the current MCP configuration.

    Returns:
        The current MCP configuration with all servers.

    Example:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_xxx"},
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    config = get_extensions_config()

    return McpConfigResponse(mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in config.mcp_servers.items()})


@router.put(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Update MCP Configuration",
    description="Update Model Context Protocol (MCP) server configurations and save to file.",
)
async def update_mcp_configuration(request: McpConfigUpdateRequest) -> McpConfigResponse:
    """Update the MCP configuration.

    This will:
    1. Save the new configuration to the mcp_config.json file
    2. Reload the configuration cache
    3. Reset MCP tools cache to trigger reinitialization

    Args:
        request: The new MCP configuration to save.

    Returns:
        The updated MCP configuration.

    Raises:
        HTTPException: 500 if the configuration file cannot be written.

    Example Request:
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    try:
        # Get the current config path (or determine where to save it)
        config_path = ExtensionsConfig.resolve_config_path()

        # If no config file exists, create one in the parent directory (project root)
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

        # Load current config to preserve skills configuration
        current_config = get_extensions_config()

        # Convert request to dict format for JSON serialization.
        config_data = {
            "mcpServers": {name: _maybe_encrypt(server.model_dump()) for name, server in request.mcp_servers.items()},
            "skills": {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()},
        }

        # Write the configuration to file
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"MCP configuration updated and saved to: {config_path}")

        # NOTE: No need to reload/reset cache here - LangGraph Server (separate process)
        # will detect config file changes via mtime and reinitialize MCP tools automatically

        # Reload the configuration and update the global cache
        reloaded_config = reload_extensions_config()
        return McpConfigResponse(mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in reloaded_config.mcp_servers.items()})

    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MCP configuration: {str(e)}")


# ============================================================================
# OAuth authorization_code flow for interactive MCP presets (Gmail, Drive, ...)
# ============================================================================


def _public_base_url() -> str:
    """Resolve the externally-reachable base URL used for OAuth redirect URIs."""
    base = os.getenv("DEER_FLOW_PUBLIC_URL")
    if base:
        return base.rstrip("/")
    # Fallback: assume local development
    return "http://localhost:3000"


def _redirect_uri() -> str:
    return f"{_public_base_url()}/api/mcp/oauth/callback"


class OAuthStartRequest(BaseModel):
    preset_id: str = Field(..., description="ID of the OAuth preset to connect")


class OAuthStartResponse(BaseModel):
    authorization_url: str
    state: str


class OAuthPresetListResponse(BaseModel):
    presets: list[dict]


@router.get(
    "/mcp/oauth/presets",
    response_model=OAuthPresetListResponse,
    summary="List OAuth presets",
    description="List the OAuth-based MCP server presets available for the catalog.",
)
async def list_mcp_oauth_presets() -> OAuthPresetListResponse:
    return OAuthPresetListResponse(presets=list_oauth_presets())


@router.post(
    "/mcp/oauth/start",
    response_model=OAuthStartResponse,
    summary="Begin an MCP OAuth flow",
    description="Generate a PKCE challenge + state and return the provider authorization URL for the popup.",
)
async def start_mcp_oauth(request: OAuthStartRequest) -> OAuthStartResponse:
    preset = get_oauth_preset(request.preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth preset: {request.preset_id}")

    client_id = os.getenv(preset.client_id_env)
    client_secret = os.getenv(preset.client_secret_env)
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail=(
                f"OAuth preset '{preset.id}' is not configured: set "
                f"{preset.client_id_env} and {preset.client_secret_env} in the server env."
            ),
        )

    store = get_session_store()
    session = store.create(preset_id=preset.id, redirect_uri=_redirect_uri())

    authorization_url = build_authorization_url(
        authorization_url=preset.authorization_url,
        client_id=client_id,
        redirect_uri=session.redirect_uri,
        scope=preset.scope,
        state=session.state,
        code_challenge=pkce_challenge(session.code_verifier),
        extra_params=preset.extra_auth_params,
    )

    return OAuthStartResponse(authorization_url=authorization_url, state=session.state)


def _callback_html(status: str, preset_id: str | None, message: str) -> str:
    """HTML page rendered in the OAuth popup after the redirect."""
    payload = json.dumps({"type": "mcp-oauth-result", "status": status, "preset_id": preset_id, "message": message})
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>MCP OAuth {status}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 2rem; color: #222; }}
  .ok {{ color: #0a7f2e; }}
  .err {{ color: #b00020; }}
</style>
</head>
<body>
<h1 class="{'ok' if status == 'success' else 'err'}">{status.title()}</h1>
<p>{message}</p>
<p>You can close this window.</p>
<script>
try {{
  if (window.opener) {{
    window.opener.postMessage({payload}, "*");
  }}
}} catch (e) {{ /* no-op */ }}
setTimeout(function () {{ window.close(); }}, 800);
</script>
</body>
</html>"""


@router.get(
    "/mcp/oauth/callback",
    response_class=HTMLResponse,
    summary="OAuth authorization_code callback",
    description="Receives the provider redirect, exchanges the code, and persists the MCP server config.",
)
async def mcp_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(_callback_html("error", None, f"Authorization denied: {error}"), status_code=400)
    if not code or not state:
        return HTMLResponse(_callback_html("error", None, "Missing code or state parameter."), status_code=400)

    store = get_session_store()
    session = store.pop(state)
    if session is None:
        return HTMLResponse(
            _callback_html("error", None, "OAuth session expired or not found. Please retry."),
            status_code=400,
        )

    preset = get_oauth_preset(session.preset_id)
    if preset is None:
        return HTMLResponse(
            _callback_html("error", session.preset_id, f"Unknown preset: {session.preset_id}"),
            status_code=500,
        )

    client_id = os.getenv(preset.client_id_env)
    client_secret = os.getenv(preset.client_secret_env)
    if not client_id or not client_secret:
        return HTMLResponse(
            _callback_html("error", preset.id, "OAuth preset is not configured on the server."),
            status_code=500,
        )

    try:
        tokens = await exchange_code_for_tokens(
            token_url=preset.token_url,
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=session.redirect_uri,
            code_verifier=session.code_verifier,
        )
    except Exception as e:
        logger.error("OAuth token exchange failed: %s", e, exc_info=True)
        return HTMLResponse(
            _callback_html("error", preset.id, f"Token exchange failed: {e}"),
            status_code=502,
        )

    try:
        server_config = preset.build_server_config(
            tokens.access_token,
            tokens.refresh_token,
            client_id,
            client_secret,
        )
    except Exception as e:
        logger.error("Preset config build failed: %s", e, exc_info=True)
        return HTMLResponse(
            _callback_html("error", preset.id, f"Failed to write credentials: {e}"),
            status_code=500,
        )

    # Merge the new server into extensions_config.json (preserving skills + other servers)
    try:
        current = get_extensions_config()
        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info("No existing extensions config; creating at %s", config_path)

        merged_servers = {name: _maybe_encrypt(server.model_dump()) for name, server in current.mcp_servers.items()}
        merged_servers[preset.id] = _maybe_encrypt(server_config)

        config_data = {
            "mcpServers": merged_servers,
            "skills": {name: {"enabled": skill.enabled} for name, skill in current.skills.items()},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        reload_extensions_config()
        logger.info("MCP OAuth preset '%s' connected; config saved to %s", preset.id, config_path)
    except Exception as e:
        logger.error("Failed to persist MCP config after OAuth: %s", e, exc_info=True)
        return HTMLResponse(
            _callback_html("error", preset.id, f"Failed to save config: {e}"),
            status_code=500,
        )

    return HTMLResponse(
        _callback_html("success", preset.id, f"{preset.display_name} connected successfully."),
        status_code=200,
    )


# ============================================================================
# Test Connection — probe a saved MCP server by spawning it and listing tools
# ============================================================================


class McpServerTestResponse(BaseModel):
    ok: bool
    tool_count: int | None = None
    tool_names: list[str] = Field(default_factory=list)
    error: str | None = None


@router.post(
    "/mcp/servers/{server_name}/test",
    response_model=McpServerTestResponse,
    summary="Test Connection to an MCP server",
    description="Spawn the saved MCP server, run initialize + list_tools, and return the result.",
)
async def test_mcp_server(server_name: str) -> McpServerTestResponse:
    config = get_extensions_config()
    server = config.mcp_servers.get(server_name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"Unknown MCP server: {server_name}")

    transport = (server.type or "stdio").lower()
    if transport != "stdio":
        # Phase 3 scope: only stdio test is implemented. HTTP/SSE presets
        # surface transport errors through the regular agent path anyway.
        return McpServerTestResponse(
            ok=False,
            error=f"Test Connection for '{transport}' transport is not implemented yet.",
        )

    if not server.command:
        return McpServerTestResponse(ok=False, error="Server config is missing 'command'.")

    try:
        from mcp.client.session import ClientSession  # noqa: PLC0415
        from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - mcp package always present
        return McpServerTestResponse(ok=False, error=f"MCP client unavailable: {e}")

    # Inherit the current process env so $PATH etc. are populated for spawned
    # npx/node/python, then overlay the server-specific env (which is already
    # plaintext because load went through decrypt_secrets).
    merged_env = {**os.environ, **(server.env or {})}

    params = StdioServerParameters(
        command=server.command,
        args=list(server.args or []),
        env=merged_env,
    )

    import asyncio  # noqa: PLC0415

    try:
        async with asyncio.timeout(30):
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    names = [t.name for t in tools_result.tools]
                    return McpServerTestResponse(
                        ok=True,
                        tool_count=len(names),
                        tool_names=names,
                    )
    except TimeoutError:
        return McpServerTestResponse(ok=False, error="Server did not respond within 30s.")
    except Exception as e:
        logger.warning("Test Connection for %s failed: %s", server_name, e)
        return McpServerTestResponse(ok=False, error=str(e))
