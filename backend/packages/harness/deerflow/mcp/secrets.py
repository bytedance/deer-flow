"""Fernet-based encryption for sensitive values in ``extensions_config.json``.

The config file holds MCP server env vars, OAuth refresh tokens, and
client secrets. These should not live on disk in plaintext. The helpers
here wrap strings with a ``"fernet:"`` prefix and transparently decrypt
them on load, re-encrypt on save.

Key resolution (first hit wins):
1. ``MCP_SECRETS_KEY`` environment variable (urlsafe base64 Fernet key).
2. ``<DEER_FLOW_DATA_DIR>/mcp_secret.key`` (auto-generated with 0600 perms
   on first use; path is ``backend/.deer-flow/mcp_secret.key`` by default).

Plaintext values are accepted on load (for forward-migration), so existing
deployments can transparently upgrade: on the next save everything is
rewritten as ciphertext.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

PREFIX = "fernet:"
# Env var names we deliberately leave as plaintext (they're non-sensitive
# routing/config, and the MCP server needs to read the literal value).
# Everything else in ``env`` is encrypted on save by default — safer than
# maintaining a "sensitive" allowlist that misses embedded tokens (e.g.
# Notion uses OPENAPI_MCP_HEADERS which carries a Bearer token).
PLAINTEXT_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "PWD",
        "SHELL",
        "NODE_PATH",
        "PYTHONPATH",
        "DEBUG",
        "LOG_LEVEL",
        "NO_COLOR",
    }
)


def _default_key_path() -> Path:
    base = os.environ.get("DEER_FLOW_DATA_DIR")
    if base:
        return Path(base) / "mcp_secret.key"
    backend_dir = Path(__file__).resolve().parents[4]
    return backend_dir / ".deer-flow" / "mcp_secret.key"


_cached_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    """Return a cached Fernet instance from env var or generated key file."""
    global _cached_fernet
    if _cached_fernet is not None:
        return _cached_fernet

    key_str = os.environ.get("MCP_SECRETS_KEY")
    if key_str:
        _cached_fernet = Fernet(key_str.encode("ascii"))
        return _cached_fernet

    key_path = _default_key_path()
    if key_path.exists():
        key_bytes = key_path.read_bytes().strip()
    else:
        key_bytes = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key_bytes)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        logger.warning(
            "Generated new MCP secrets key at %s. Back this up: losing it invalidates all stored MCP credentials. Set MCP_SECRETS_KEY env var to manage it out-of-band.",
            key_path,
        )

    _cached_fernet = Fernet(key_bytes)
    return _cached_fernet


def reset_cache() -> None:
    """Forget the cached Fernet (for tests or key rotation)."""
    global _cached_fernet
    _cached_fernet = None


def encrypt(value: str) -> str:
    """Encrypt a string. Returns ``"fernet:<ciphertext>"``.

    Values that are already encrypted are returned unchanged so repeated
    save passes are idempotent.
    """
    if not value:
        return value
    if value.startswith(PREFIX):
        return value
    token = get_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(value: str) -> str:
    """Decrypt a ``"fernet:"``-prefixed string. Returns plaintext unchanged.

    Raises ``InvalidToken`` if the ciphertext is corrupted or was encrypted
    with a different key.
    """
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    ciphertext = value[len(PREFIX) :].encode("ascii")
    try:
        return get_fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt an MCP secret. The key may have been rotated; reconnect the affected MCP server to refresh credentials.")
        raise


def should_encrypt_env_key(key: str) -> bool:
    """Encrypt every env var except a small allowlist of known non-secrets."""
    return key.upper() not in PLAINTEXT_ENV_KEYS


def encrypt_server_sensitive(server: dict) -> dict:
    """Return a copy of an MCP server config dict with secrets encrypted."""
    out = dict(server)

    env = server.get("env") or {}
    if env:
        new_env: dict[str, str] = {}
        for k, v in env.items():
            if isinstance(v, str) and should_encrypt_env_key(k):
                new_env[k] = encrypt(v)
            else:
                new_env[k] = v
        out["env"] = new_env

    oauth = server.get("oauth")
    if isinstance(oauth, dict):
        new_oauth = dict(oauth)
        for field in ("client_secret", "refresh_token"):
            val = new_oauth.get(field)
            if isinstance(val, str) and val:
                new_oauth[field] = encrypt(val)
        out["oauth"] = new_oauth

    return out


def decrypt_server_sensitive(server: dict) -> dict:
    """Return a copy with secrets decrypted back to plaintext."""
    out = dict(server)

    env = server.get("env") or {}
    if env:
        new_env: dict[str, str] = {}
        for k, v in env.items():
            new_env[k] = decrypt(v) if isinstance(v, str) else v
        out["env"] = new_env

    oauth = server.get("oauth")
    if isinstance(oauth, dict):
        new_oauth = dict(oauth)
        for field in ("client_secret", "refresh_token"):
            val = new_oauth.get(field)
            if isinstance(val, str):
                new_oauth[field] = decrypt(val)
        out["oauth"] = new_oauth

    return out
