"""Honcho backend config — parses ``backend_config`` (see noop/config.py for the golden rule).

The backend receives everything through the ABC method args and this dict; it
imports nothing from deer-flow. Self-hosted Honcho commonly runs auth-less over
plain HTTP; a configured ``api_key`` over plain HTTP requires the explicit
``allow_insecure_http: true`` opt-in (same posture as the mem0 backend).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_id(raw: str) -> str:
    """Map an arbitrary string onto Honcho's id grammar (``^[a-zA-Z0-9_-]+$``; grammar allows up to 100, capped here at 64)."""
    return _ID_RE.sub("-", str(raw)).strip("-")[:64]


def _mapping(value: Any, name: str) -> dict[str, Any]:
    """Narrow an operator-supplied nested value to a mapping.

    Falsy values (absent key, YAML null, ``{}``, ``""``) mean "unset" and keep
    the default. A truthy non-mapping — a bare string, a YAML list — is a
    config mistake, and naming the key here beats the ``AttributeError`` that
    ``.get``/``.items`` would otherwise raise inside backend construction. The
    mem0 and OpenViking backends already report these keys as ``ValueError``.
    """
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Honcho backend: {name} must be a mapping, got {type(value).__name__}")
    return value


def _number[T](cfg: dict[str, Any], key: str, default: T, cast: Callable[[Any], T]) -> T:
    """Narrow an operator-supplied numeric knob.

    Falsy values (absent key, YAML null, empty string) mean "unset" and keep the
    default — the same line ``_mapping`` draws above. Anything else that cannot be
    cast is a config mistake, and naming the key here beats the ``TypeError`` that
    ``float(None)`` or ``int({...})`` raise from inside backend construction
    without mentioning which knob or which file is wrong. Numeric strings keep
    working, because that is what ``float``/``int`` already accept.
    """
    value = cfg.get(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ValueError(f"Honcho backend: {key} must be a number, got {type(value).__name__}") from None


def _parse_override_map(cfg: dict[str, Any], key: str) -> dict[str, str]:
    """Overrides map raw user ids to explicit workspace/peer ids; an empty or
    null VALUE is always a config mistake (empty string is falsy and would
    silently fall through to the default derivation; YAML null would stringify
    into an id literally named "None"), so fail fast at parse time."""
    out: dict[str, str] = {}
    for k, v in _mapping(cfg.get(key), key).items():
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

    def __post_init__(self) -> None:
        # A scheme-less or non-http value is not a relative address: httpx turns
        # "localhost:8000" into the bogus scheme "localhost:", so every later
        # request fails while Gateway startup stays green. An authority without a
        # host ("http://", "http://:8000") is the same accepted-now, dead-later
        # shape, so the guard reads hostname rather than netloc. The mem0 and
        # OpenViking backends already reject this shape; README.md and
        # HonchoMemoryManager.from_config both promise a bad URL fails fast.
        parsed_base_url = urlsplit(self.base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.hostname:
            raise ValueError("Honcho backend: base_url must be an absolute http:// or https:// URL")
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Honcho backend: timeout_seconds must be a finite value > 0")
        if not isfinite(self.connect_timeout_seconds) or self.connect_timeout_seconds <= 0:
            raise ValueError("Honcho backend: connect_timeout_seconds must be a finite value > 0")
        # add()/get_context() truncate with text[:n]. n <= 0 is empty (n == 0)
        # or a Python negative slice (n == -1 -> text[:-1]), not a length cap.
        if self.message_char_limit <= 0:
            raise ValueError("Honcho backend: message_char_limit must be > 0")
        if self.max_injection_chars <= 0:
            raise ValueError("Honcho backend: max_injection_chars must be > 0")

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> HonchoConfig:
        cfg = dict(backend_config or {})
        failure_policy = _mapping(cfg.get("failure_policy"), "failure_policy")
        base_url = str(cfg.get("base_url", "http://localhost:8000")).rstrip("/")
        api_key = cfg.get("api_key") or None
        allow_insecure = bool(cfg.get("allow_insecure_http", False))
        # The parsed scheme, not startswith("http://"): a caller can write
        # "HTTP://internal:8000" and urlsplit/httpx both treat that as plain
        # HTTP, so a case-sensitive prefix test leaks the key unencrypted.
        if api_key and urlsplit(base_url).scheme == "http" and not allow_insecure:
            raise ValueError("Honcho backend: api_key over plain http requires backend_config.allow_insecure_http: true (the key would be sent unencrypted). Use https, or set the opt-in for local development.")
        return cls(
            base_url=base_url,
            api_key=api_key,
            workspace_prefix=str(cfg.get("workspace_prefix", "deerflow-u-")),
            workspace_overrides=_parse_override_map(cfg, "workspace_overrides"),
            user_peer_overrides=_parse_override_map(cfg, "user_peer_overrides"),
            assistant_peer=str(cfg.get("assistant_peer", "deerflow")),
            timeout_seconds=_number(cfg, "timeout_seconds", 10.0, float),
            connect_timeout_seconds=_number(cfg, "connect_timeout_seconds", 3.0, float),
            message_char_limit=_number(cfg, "message_char_limit", 8000, int),
            max_injection_chars=_number(cfg, "max_injection_chars", 6000, int),
            allow_insecure_http=allow_insecure,
            read_fail_closed=str(failure_policy.get("read", "")).lower() == "fail_closed",
            storage_path=str(cfg.get("storage_path") or ""),
        )
