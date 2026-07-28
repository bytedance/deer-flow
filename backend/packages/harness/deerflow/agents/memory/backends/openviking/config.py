"""Configuration for the OpenViking HTTP memory backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse


@dataclass(frozen=True)
class OpenVikingConfig:
    """Parsed backend-private configuration.

    The backend is intentionally remote-only: DeerFlow talks to an independent
    OpenViking server and does not import the OpenViking Python runtime.
    """

    base_url: str
    storage_path: str
    auth_mode: Literal["trusted", "dev"]
    account: str
    api_key: str | None = field(repr=False)
    connect_timeout_seconds: float
    read_timeout_seconds: float
    write_timeout_seconds: float
    pool_timeout_seconds: float
    max_connections: int
    max_keepalive_connections: int
    max_retries: int
    search_top_k: int
    score_threshold: float | None
    max_injection_chars: int
    injection_query: str
    startup_policy: Literal["fail_fast", "warn"]
    read_failure_policy: Literal["fail_open", "raise"]
    write_failure_policy: Literal["log_and_drop", "raise"]
    allow_insecure_http: bool
    allow_insecure_dev: bool
    max_seen_message_ids: int

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> OpenVikingConfig:
        cfg = dict(backend_config or {})
        retrieval = _mapping(cfg.pop("retrieval", {}), "retrieval")
        failure_policy = _mapping(cfg.pop("failure_policy", {}), "failure_policy")

        api_key_env = str(cfg.pop("api_key_env", "OPENVIKING_API_KEY")).strip()
        api_key = os.environ.get(api_key_env) if api_key_env else None

        result = cls(
            base_url=str(cfg.pop("base_url", "http://127.0.0.1:1933")).rstrip("/"),
            storage_path=str(cfg.pop("storage_path", "")),
            auth_mode=str(cfg.pop("auth_mode", "trusted")).lower(),  # type: ignore[arg-type]
            account=str(cfg.pop("account", "deerflow")).strip(),
            api_key=api_key,
            connect_timeout_seconds=float(cfg.pop("connect_timeout_seconds", 2.0)),
            read_timeout_seconds=float(cfg.pop("read_timeout_seconds", 10.0)),
            write_timeout_seconds=float(cfg.pop("write_timeout_seconds", 10.0)),
            pool_timeout_seconds=float(cfg.pop("pool_timeout_seconds", 2.0)),
            max_connections=int(cfg.pop("max_connections", 100)),
            max_keepalive_connections=int(cfg.pop("max_keepalive_connections", 20)),
            max_retries=int(cfg.pop("max_retries", 1)),
            search_top_k=int(retrieval.pop("top_k", 8)),
            score_threshold=_optional_float(retrieval.pop("score_threshold", None)),
            max_injection_chars=int(retrieval.pop("max_injection_chars", 12_000)),
            injection_query=str(
                retrieval.pop(
                    "injection_query",
                    "user profile preferences important entities events ongoing goals constraints and prior decisions",
                )
            ).strip(),
            startup_policy=str(cfg.pop("startup_policy", "fail_fast")).lower(),  # type: ignore[arg-type]
            read_failure_policy=str(failure_policy.pop("read", "fail_open")).lower(),  # type: ignore[arg-type]
            write_failure_policy=str(failure_policy.pop("write", "log_and_drop")).lower(),  # type: ignore[arg-type]
            allow_insecure_http=bool(cfg.pop("allow_insecure_http", False)),
            allow_insecure_dev=bool(cfg.pop("allow_insecure_dev", False)),
            max_seen_message_ids=int(cfg.pop("max_seen_message_ids", 512)),
        )

        unknown = sorted([*cfg, *(f"retrieval.{key}" for key in retrieval), *(f"failure_policy.{key}" for key in failure_policy)])
        if unknown:
            raise ValueError(f"Unknown OpenViking backend_config fields: {', '.join(unknown)}")
        result._validate()
        return result

    def _validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenViking base_url must be an absolute http(s) URL")
        if parsed.scheme == "http" and not self.allow_insecure_http and parsed.hostname not in {"127.0.0.1", "localhost", "openviking"}:
            raise ValueError("OpenViking plain HTTP is allowed only for localhost/openviking; set allow_insecure_http=true for a trusted internal network")
        if self.auth_mode not in {"trusted", "dev"}:
            raise ValueError("OpenViking auth_mode must be 'trusted' or 'dev'")
        if self.auth_mode == "dev" and not self.allow_insecure_dev:
            raise ValueError("OpenViking auth_mode='dev' requires allow_insecure_dev=true")
        if self.auth_mode == "trusted" and not self.account:
            raise ValueError("OpenViking trusted auth requires a non-empty account")
        for field_name in ("connect_timeout_seconds", "read_timeout_seconds", "write_timeout_seconds", "pool_timeout_seconds"):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"OpenViking {field_name} must be > 0")
        if not 1 <= self.max_connections <= 1000:
            raise ValueError("OpenViking max_connections must be between 1 and 1000")
        if not 0 <= self.max_keepalive_connections <= self.max_connections:
            raise ValueError("OpenViking max_keepalive_connections must be between 0 and max_connections")
        if not 0 <= self.max_retries <= 5:
            raise ValueError("OpenViking max_retries must be between 0 and 5")
        if not 1 <= self.search_top_k <= 100:
            raise ValueError("OpenViking retrieval.top_k must be between 1 and 100")
        if self.score_threshold is not None and not 0 <= self.score_threshold <= 1:
            raise ValueError("OpenViking retrieval.score_threshold must be between 0 and 1")
        if not 256 <= self.max_injection_chars <= 100_000:
            raise ValueError("OpenViking retrieval.max_injection_chars must be between 256 and 100000")
        if not self.injection_query:
            raise ValueError("OpenViking retrieval.injection_query must not be empty")
        if self.startup_policy not in {"fail_fast", "warn"}:
            raise ValueError("OpenViking startup_policy must be 'fail_fast' or 'warn'")
        if self.read_failure_policy not in {"fail_open", "raise"}:
            raise ValueError("OpenViking failure_policy.read must be 'fail_open' or 'raise'")
        if self.write_failure_policy not in {"log_and_drop", "raise"}:
            raise ValueError("OpenViking failure_policy.write must be 'log_and_drop' or 'raise'")
        if not 16 <= self.max_seen_message_ids <= 10_000:
            raise ValueError("OpenViking max_seen_message_ids must be between 16 and 10000")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"OpenViking {name} must be a mapping")
    return dict(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
