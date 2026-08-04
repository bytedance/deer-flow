"""Configuration for the official OpenViking LangChain adapter path."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Literal
from urllib.parse import urlparse

_SAFE_PEER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
GENERATED_PEER_PREFIX = "df-agent-"


@dataclass(frozen=True, slots=True)
class OfficialOpenVikingConfig:
    """Validated credential-bound OpenViking connection and memory policy."""

    base_url: str
    storage_path: str
    owner_user_id: str
    api_key: str = field(repr=False)
    api_key_env: str
    default_peer_id: str
    timeout_seconds: float
    search_mode: Literal["find", "search"]
    search_top_k: int
    score_threshold: float | None
    max_injection_chars: int
    content_mode: Literal["auto", "abstract", "overview", "read"]
    startup_policy: Literal["fail_fast", "warn"]
    read_failure_policy: Literal["fail_open", "fail_closed"]
    write_failure_policy: Literal["fail_open", "fail_closed"]
    allow_insecure_http: bool
    max_seen_message_ids: int

    @classmethod
    def from_backend_config(
        cls,
        backend_config: dict[str, Any] | None,
    ) -> OfficialOpenVikingConfig:
        cfg = dict(backend_config or {})
        retrieval = _mapping(cfg.pop("retrieval", {}), "retrieval")
        failure_policy = _mapping(cfg.pop("failure_policy", {}), "failure_policy")

        api_key_env = str(cfg.pop("api_key_env", "OPENVIKING_API_KEY")).strip()
        if not api_key_env:
            raise ValueError("OpenViking api_key_env must not be empty")
        api_key = os.environ.get(api_key_env, "").strip()

        result = cls(
            base_url=str(cfg.pop("base_url", "http://127.0.0.1:1933")).rstrip("/"),
            storage_path=str(cfg.pop("storage_path", "")),
            owner_user_id=str(cfg.pop("owner_user_id", "default")).strip(),
            api_key=api_key,
            api_key_env=api_key_env,
            default_peer_id=str(cfg.pop("default_peer_id", "deerflow")).strip(),
            timeout_seconds=float(cfg.pop("timeout_seconds", 30.0)),
            search_mode=str(retrieval.pop("search_mode", "search")).lower(),  # type: ignore[arg-type]
            search_top_k=int(retrieval.pop("top_k", 8)),
            score_threshold=_optional_float(retrieval.pop("score_threshold", None)),
            max_injection_chars=int(retrieval.pop("max_injection_chars", 12_000)),
            content_mode=str(retrieval.pop("content_mode", "auto")).lower(),  # type: ignore[arg-type]
            startup_policy=str(cfg.pop("startup_policy", "fail_fast")).lower(),  # type: ignore[arg-type]
            read_failure_policy=str(failure_policy.pop("read", "fail_open")).lower(),  # type: ignore[arg-type]
            write_failure_policy=str(failure_policy.pop("write", "fail_open")).lower(),  # type: ignore[arg-type]
            allow_insecure_http=_boolean(
                cfg.pop("allow_insecure_http", False),
                "allow_insecure_http",
            ),
            max_seen_message_ids=int(cfg.pop("max_seen_message_ids", 512)),
        )

        unknown = sorted(
            [
                *cfg,
                *(f"retrieval.{key}" for key in retrieval),
                *(f"failure_policy.{key}" for key in failure_policy),
            ]
        )
        if unknown:
            raise ValueError("Unknown official OpenViking backend_config fields: " + ", ".join(unknown))
        result._validate()
        return result

    def _validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenViking base_url must be an absolute http(s) URL")
        if parsed.scheme == "http" and not self.allow_insecure_http and parsed.hostname not in {"127.0.0.1", "localhost", "openviking"}:
            raise ValueError("OpenViking plain HTTP is allowed only for localhost/openviking; set allow_insecure_http=true only for a trusted internal network")
        if not self.owner_user_id:
            raise ValueError("OpenViking owner_user_id must not be empty")
        if not self.api_key:
            raise ValueError(f"OpenViking USER API key is missing; set {self.api_key_env}")
        if not self.default_peer_id:
            raise ValueError("OpenViking default_peer_id must not be empty")
        if not is_safe_peer_id(self.default_peer_id):
            raise ValueError("OpenViking default_peer_id must start with a lowercase letter or digit and contain at most 64 lowercase letters, digits, '_' or '-'")
        if self.default_peer_id.startswith(GENERATED_PEER_PREFIX):
            raise ValueError(f"OpenViking default_peer_id must not start with the reserved prefix {GENERATED_PEER_PREFIX!r}")
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("OpenViking timeout_seconds must be a finite value > 0")
        if self.search_mode not in {"find", "search"}:
            raise ValueError("OpenViking retrieval.search_mode must be 'find' or 'search'")
        if not 1 <= self.search_top_k <= 100:
            raise ValueError("OpenViking retrieval.top_k must be between 1 and 100")
        if self.score_threshold is not None and (not isfinite(self.score_threshold) or not 0 <= self.score_threshold <= 1):
            raise ValueError("OpenViking retrieval.score_threshold must be a finite value between 0 and 1")
        if not 256 <= self.max_injection_chars <= 100_000:
            raise ValueError("OpenViking retrieval.max_injection_chars must be between 256 and 100000")
        if self.content_mode not in {"auto", "abstract", "overview", "read"}:
            raise ValueError("OpenViking retrieval.content_mode must be auto, abstract, overview, or read")
        if self.startup_policy not in {"fail_fast", "warn"}:
            raise ValueError("OpenViking startup_policy must be 'fail_fast' or 'warn'")
        if self.read_failure_policy not in {"fail_open", "fail_closed"}:
            raise ValueError("OpenViking failure_policy.read must be 'fail_open' or 'fail_closed'")
        if self.write_failure_policy not in {"fail_open", "fail_closed"}:
            raise ValueError("OpenViking failure_policy.write must be 'fail_open' or 'fail_closed'")
        if not 16 <= self.max_seen_message_ids <= 10_000:
            raise ValueError("OpenViking max_seen_message_ids must be between 16 and 10000")


def is_legacy_openviking_config(backend_config: dict[str, Any] | None) -> bool:
    """Return whether a config contains a deprecated custom-HTTP-only field."""

    cfg = backend_config or {}
    legacy_fields = {
        "auth_mode",
        "account",
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "write_timeout_seconds",
        "pool_timeout_seconds",
        "max_connections",
        "max_keepalive_connections",
        "max_retries",
        "allow_insecure_dev",
    }
    if any(field in cfg for field in legacy_fields):
        return True
    retrieval = cfg.get("retrieval")
    if isinstance(retrieval, dict) and "injection_query" in retrieval:
        return True
    failure_policy = cfg.get("failure_policy")
    if isinstance(failure_policy, dict):
        return failure_policy.get("read") == "raise" or failure_policy.get("write") in {"raise", "log_and_drop"}
    return False


def is_safe_peer_id(value: str) -> bool:
    """Return whether *value* is valid for an OpenViking actor peer."""

    return _SAFE_PEER_RE.fullmatch(value) is not None


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"OpenViking {name} must be a mapping")
    return dict(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"OpenViking {name} must be a boolean")
