"""Auto-load credentials from Claude Code CLI and Codex CLI.

Implements two credential strategies:
  1. Claude Code OAuth token from ~/.claude/.credentials.json
     - Uses Authorization: Bearer header (NOT x-api-key)
     - Requires anthropic-beta: oauth-2025-04-20,claude-code-20250219
     - Override path with $CLAUDE_CODE_CREDENTIALS_PATH
  2. Codex CLI token from ~/.codex/auth.json
     - Uses chatgpt.com/backend-api/codex/responses endpoint
     - Supports both legacy top-level tokens and current nested tokens shape
     - Override path with $CODEX_AUTH_PATH
"""

import json
import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Required beta headers for Claude Code OAuth tokens
OAUTH_ANTHROPIC_BETAS = "oauth-2025-04-20,claude-code-20250219,interleaved-thinking-2025-05-14"


def is_oauth_token(token: str) -> bool:
    """Check if a token is a Claude Code OAuth token (not a standard API key)."""
    return isinstance(token, str) and "sk-ant-oat" in token


@dataclass
class ClaudeCodeCredential:
    """Claude Code CLI OAuth credential."""

    access_token: str
    refresh_token: str = ""
    expires_at: int = 0
    source: str = ""

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() * 1000 > self.expires_at - 60_000  # 1 min buffer


@dataclass
class CodexCliCredential:
    """Codex CLI credential."""

    access_token: str
    account_id: str = ""
    source: str = ""


def _resolve_credential_path(env_var: str, default_relative_path: str) -> Path:
    configured_path = os.getenv(env_var)
    if configured_path:
        return Path(configured_path).expanduser()
    return Path.home() / default_relative_path


def _load_json_file(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        logger.debug(f"{label} not found: {path}")
        return None
    if path.is_dir():
        logger.warning(f"{label} path is a directory, expected a file: {path}")
        return None

    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read {label}: {e}")
        return None


def _claude_code_oauth_file_suffix() -> str:
    if os.getenv("CLAUDE_CODE_CUSTOM_OAUTH_URL"):
        return "-custom-oauth"
    if os.getenv("USE_LOCAL_OAUTH") or os.getenv("LOCAL_BRIDGE"):
        return "-local-oauth"
    if os.getenv("USE_STAGING_OAUTH"):
        return "-staging-oauth"
    return ""


def _claude_code_keychain_service_name() -> str:
    service = f"Claude Code{_claude_code_oauth_file_suffix()}-credentials"
    config_dir = os.getenv("CLAUDE_CONFIG_DIR")
    if config_dir:
        config_hash = sha256(str(Path(config_dir).expanduser()).encode()).hexdigest()[:8]
        service = f"{service}-{config_hash}"
    return service


def _claude_code_keychain_account_name() -> str:
    return os.getenv("USER") or "claude-code-user"


def _load_claude_code_keychain_container() -> dict[str, Any] | None:
    if platform.system() != "Darwin":
        return None

    service = _claude_code_keychain_service_name()
    account = _claude_code_keychain_account_name()

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-w", "-s", service],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        logger.debug(f"Failed to invoke macOS security tool: {e}")
        return None

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if stderr:
            logger.debug(f"Claude Code credentials not available in Keychain: {stderr}")
        return None

    secret = (result.stdout or "").strip()
    if not secret:
        return None

    try:
        return json.loads(secret)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse Claude Code Keychain credentials: {e}")
        return None


def _extract_claude_code_credential(data: dict[str, Any], source: str) -> ClaudeCodeCredential | None:
    oauth = data.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken", "")
    if not access_token:
        logger.debug("Claude Code credentials container exists but no accessToken found")
        return None

    cred = ClaudeCodeCredential(
        access_token=access_token,
        refresh_token=oauth.get("refreshToken", ""),
        expires_at=oauth.get("expiresAt", 0),
        source=source,
    )

    if cred.is_expired:
        logger.warning("Claude Code OAuth token is expired. Run 'claude' to refresh.")
        return None

    return cred


def load_claude_code_credential() -> ClaudeCodeCredential | None:
    """Load OAuth credential from Claude Code CLI.

    Reads ~/.claude/.credentials.json which contains:
    {
      "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-...",
        "refreshToken": "sk-ant-ort01-...",
        "expiresAt": 1773430695128,
        "scopes": ["user:inference", ...],
        ...
      }
    }
    """
    override_path = os.getenv("CLAUDE_CODE_CREDENTIALS_PATH")
    if override_path:
        data = _load_json_file(Path(override_path).expanduser(), "Claude Code credentials")
        if data is None:
            return None
        cred = _extract_claude_code_credential(data, "claude-cli-file")
        if cred:
            logger.info(f"Loaded Claude Code OAuth credential from override path (expires_at={cred.expires_at})")
        return cred

    keychain_data = _load_claude_code_keychain_container()
    if keychain_data is not None:
        cred = _extract_claude_code_credential(keychain_data, "claude-cli-keychain")
        if cred:
            logger.info(f"Loaded Claude Code OAuth credential from macOS Keychain (expires_at={cred.expires_at})")
            return cred

    cred_path = _resolve_credential_path("CLAUDE_CODE_CREDENTIALS_PATH", ".claude/.credentials.json")
    data = _load_json_file(cred_path, "Claude Code credentials")
    if data is None:
        return None
    cred = _extract_claude_code_credential(data, "claude-cli-file")
    if cred:
        logger.info(f"Loaded Claude Code OAuth credential from plaintext file (expires_at={cred.expires_at})")
    return cred


def load_codex_cli_credential() -> CodexCliCredential | None:
    """Load credential from Codex CLI (~/.codex/auth.json)."""
    cred_path = _resolve_credential_path("CODEX_AUTH_PATH", ".codex/auth.json")
    data = _load_json_file(cred_path, "Codex CLI credentials")
    if data is None:
        return None
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}

    access_token = data.get("access_token") or data.get("token") or tokens.get("access_token", "")
    account_id = data.get("account_id") or tokens.get("account_id", "")
    if not access_token:
        logger.debug("Codex CLI credentials file exists but no token found")
        return None

    logger.info("Loaded Codex CLI credential")
    return CodexCliCredential(
        access_token=access_token,
        account_id=account_id,
        source="codex-cli",
    )
