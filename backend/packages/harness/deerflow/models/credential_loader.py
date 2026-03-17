"""Auto-load credentials from Claude Code CLI and Codex CLI.

Implements two credential strategies:
  1. Claude Code OAuth token from ~/.claude/.credentials.json
     - Uses Authorization: Bearer header (NOT x-api-key)
     - Requires anthropic-beta: oauth-2025-04-20,claude-code-20250219
  2. Codex CLI token from ~/.codex/auth.json
     - Uses chatgpt.com/backend-api/codex/responses endpoint
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

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
    source: str = ""


def load_claude_code_credential() -> ClaudeCodeCredential | None:
    """Load OAuth credential from Claude Code CLI (~/.claude/.credentials.json)."""
    cred_path = Path.home() / ".claude" / ".credentials.json"
    if not cred_path.exists():
        logger.debug(f"Claude Code credentials not found: {cred_path}")
        return None

    try:
        data = json.loads(cred_path.read_text())
        oauth = data.get("claudeAiOauth", {})
        access_token = oauth.get("accessToken", "")
        if not access_token:
            logger.debug("Claude Code credentials file exists but no accessToken found")
            return None

        cred = ClaudeCodeCredential(
            access_token=access_token,
            refresh_token=oauth.get("refreshToken", ""),
            expires_at=oauth.get("expiresAt", 0),
            source="claude-cli",
        )

        if cred.is_expired:
            logger.warning("Claude Code OAuth token is expired. Run 'claude' to refresh.")
            return None

        logger.info(f"Loaded Claude Code OAuth credential (expires_at={cred.expires_at})")
        return cred

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read Claude Code credentials: {e}")
        return None


def load_codex_cli_credential() -> CodexCliCredential | None:
    """Load credential from Codex CLI (~/.codex/auth.json)."""
    cred_path = Path.home() / ".codex" / "auth.json"
    if not cred_path.exists():
        logger.debug(f"Codex CLI credentials not found: {cred_path}")
        return None

    try:
        data = json.loads(cred_path.read_text())
        access_token = data.get("access_token") or data.get("token", "")
        if not access_token:
            logger.debug("Codex CLI credentials file exists but no token found")
            return None

        logger.info("Loaded Codex CLI credential")
        return CodexCliCredential(access_token=access_token, source="codex-cli")

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read Codex CLI credentials: {e}")
        return None
