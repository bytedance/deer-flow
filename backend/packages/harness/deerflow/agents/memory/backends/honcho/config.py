"""Honcho backend config — parses ``backend_config`` (see noop/config.py for the golden rule).

The backend receives everything through the ABC method args and this dict; it
imports nothing from deer-flow. Self-hosted Honcho commonly runs auth-less over
plain HTTP; a configured ``api_key`` over plain HTTP requires the explicit
``allow_insecure_http: true`` opt-in (same posture as the mem0 backend).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_id(raw: str) -> str:
    """Map an arbitrary string onto Honcho's id grammar (``^[a-zA-Z0-9_-]+$``; grammar allows up to 100, capped here at 64)."""
    return _ID_RE.sub("-", str(raw)).strip("-")[:64]


def _parse_override_map(cfg: dict[str, Any], key: str) -> dict[str, str]:
    """Overrides map raw user ids to explicit workspace/peer ids; an empty or
    null VALUE is always a config mistake (empty string is falsy and would
    silently fall through to the default derivation; YAML null would stringify
    into an id literally named "None"), so fail fast at parse time."""
    out: dict[str, str] = {}
    for k, v in (cfg.get(key) or {}).items():
        if v is None or not str(v).strip():
            raise ValueError(f"Honcho backend: {key}[{k!r}] has an empty value; remove the entry or set a non-empty id.")
        out[str(k)] = str(v)
    return out


@dataclass
class HonchoConfig:
    base_url: str = "http://localhost:8000"
    api_key: str | None = None
    workspace_prefix: str = "deerflow-u-"
    workspace_overrides: dict[str, str] = field(default_factory=dict)
    user_peer_overrides: dict[str, str] = field(default_factory=dict)
    assistant_peer: str = "deerflow"
    timeout_seconds: float = 10.0
    connect_timeout_seconds: float = 3.0
    message_char_limit: int = 8000
    max_injection_chars: int = 6000
    allow_insecure_http: bool = False
    read_fail_closed: bool = False
    storage_path: str = ""

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> HonchoConfig:
        cfg = dict(backend_config or {})
        failure_policy = cfg.get("failure_policy") or {}
        base_url = str(cfg.get("base_url", "http://localhost:8000")).rstrip("/")
        api_key = cfg.get("api_key") or None
        allow_insecure = bool(cfg.get("allow_insecure_http", False))
        if api_key and base_url.startswith("http://") and not allow_insecure:
            raise ValueError("Honcho backend: api_key over plain http requires backend_config.allow_insecure_http: true (the key would be sent unencrypted). Use https, or set the opt-in for local development.")
        return cls(
            base_url=base_url,
            api_key=api_key,
            workspace_prefix=str(cfg.get("workspace_prefix", "deerflow-u-")),
            workspace_overrides=_parse_override_map(cfg, "workspace_overrides"),
            user_peer_overrides=_parse_override_map(cfg, "user_peer_overrides"),
            assistant_peer=str(cfg.get("assistant_peer", "deerflow")),
            timeout_seconds=float(cfg.get("timeout_seconds", 10.0)),
            connect_timeout_seconds=float(cfg.get("connect_timeout_seconds", 3.0)),
            message_char_limit=int(cfg.get("message_char_limit", 8000)),
            max_injection_chars=int(cfg.get("max_injection_chars", 6000)),
            allow_insecure_http=allow_insecure,
            read_fail_closed=str(failure_policy.get("read", "")).lower() == "fail_closed",
            storage_path=str(cfg.get("storage_path") or ""),
        )
