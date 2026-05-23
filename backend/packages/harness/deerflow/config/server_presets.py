"""Registry of OAuth-based MCP server presets.

Each preset describes:
- Display metadata (id, name, description)
- OAuth endpoints (authorization URL, token URL, scope)
- Which environment variables hold the OAuth client credentials
- How to turn an OAuth result into a concrete MCP server config

Presets are referenced by the frontend catalog and by the
`/api/mcp/oauth/*` gateway routes.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


# Anchored at the deer-flow repo root by default. Can be overridden with
# DEER_FLOW_DATA_DIR (mirrors ThreadDataMiddleware conventions).
def _default_data_dir() -> Path:
    base = os.getenv("DEER_FLOW_DATA_DIR")
    if base:
        return Path(base)
    backend_dir = Path(__file__).resolve().parents[4]
    return backend_dir / ".deer-flow"


@dataclass
class OAuthPreset:
    id: str
    display_name: str
    description: str
    provider: str  # "google" | "slack" | "notion"
    authorization_url: str
    token_url: str
    scope: str
    client_id_env: str
    client_secret_env: str
    # Called with (access_token, refresh_token, client_id, client_secret)
    # and must return the McpServerConfig dict (matching McpServerConfig schema)
    build_server_config: Callable[[str, str, str, str], dict]
    # Extra auth URL params, e.g. {"access_type": "offline", "prompt": "consent"}
    extra_auth_params: dict[str, str] = field(default_factory=dict)


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _build_gmail_server_config(
    access_token: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Write Google OAuth credential files that @gongrzhe/server-gmail-autoauth-mcp expects."""
    creds_dir = _default_data_dir() / "google_credentials" / "gmail"

    oauth_keys_path = creds_dir / "oauth_keys.json"
    _write_json_atomic(
        oauth_keys_path,
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": ["http://localhost"],
            }
        },
    )

    credentials_path = creds_dir / "credentials.json"
    _write_json_atomic(
        credentials_path,
        {
            "type": "authorized_user",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "access_token": access_token,
        },
    )

    return {
        "enabled": True,
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
        "env": {
            "GMAIL_OAUTH_PATH": str(oauth_keys_path),
            "GMAIL_CREDENTIALS_PATH": str(credentials_path),
        },
        "description": "Gmail MCP server (OAuth via Google).",
    }


def _build_gdrive_server_config(
    access_token: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Build an MCP server entry for Drive via the ``gws`` CLI wrapper.

    The deprecated ``@modelcontextprotocol/server-gdrive`` only exposed Drive
    content through MCP *resources*, which LangGraph's tool adapter does not
    surface. We instead use a thin stdio MCP wrapper (``deerflow.mcp_servers.
    gdrive_gws``) that shells out to https://github.com/googleworkspace/cli
    (installed as the ``gws`` binary on the host). ``gws`` reads a plaintext
    ``authorized_user`` credentials file pointed to by
    ``GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE`` and transparently refreshes the
    access token using the stored ``refresh_token``.
    """
    creds_dir = _default_data_dir() / "google_credentials" / "gdrive"

    credentials_path = creds_dir / "credentials.json"
    _write_json_atomic(
        credentials_path,
        {
            "type": "authorized_user",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "access_token": access_token,
        },
    )

    python_bin = os.environ.get("DEER_FLOW_PYTHON", sys.executable)

    return {
        "enabled": True,
        "type": "stdio",
        "command": python_bin,
        "args": ["-m", "deerflow.mcp_servers.gdrive_gws"],
        "env": {
            "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": str(credentials_path),
        },
        "description": "Google Drive via googleworkspace/cli — search, read, export Docs/Sheets/Slides.",
    }


OAUTH_PRESETS: dict[str, OAuthPreset] = {
    "gmail": OAuthPreset(
        id="gmail",
        display_name="Gmail",
        description="Read and send Gmail messages on behalf of the connected account.",
        provider="google",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email https://www.googleapis.com/auth/gmail.modify",
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
        build_server_config=_build_gmail_server_config,
        extra_auth_params={
            "access_type": "offline",
            "prompt": "consent",
        },
    ),
    "gdrive": OAuthPreset(
        id="gdrive",
        display_name="Google Drive",
        description="Search and read files from Google Drive.",
        provider="google",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email https://www.googleapis.com/auth/drive.readonly",
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
        build_server_config=_build_gdrive_server_config,
        extra_auth_params={
            "access_type": "offline",
            "prompt": "consent",
        },
    ),
}


def get_oauth_preset(preset_id: str) -> OAuthPreset | None:
    return OAUTH_PRESETS.get(preset_id)


def list_oauth_presets() -> list[dict]:
    """Return serializable preset metadata (safe for frontend)."""
    return [
        {
            "id": preset.id,
            "displayName": preset.display_name,
            "description": preset.description,
            "provider": preset.provider,
            "configured": bool(os.getenv(preset.client_id_env) and os.getenv(preset.client_secret_env)),
        }
        for preset in OAUTH_PRESETS.values()
    ]
