"""Validated configuration for the official OpenViking memory adapter."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlparse

from .credentials import (
    OpenVikingCredential,
    has_control_chars,
    validate_api_key,
    validate_provider_path,
    validate_user_key,
)

_SAFE_PEER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
GENERATED_PEER_PREFIX = "df-agent-"
_DEFAULT_POOL_MAX_CLIENTS = 64
_MAX_POOL_CLIENTS = 4096
_DEFAULT_POOL_IDLE_TTL_SECONDS = 900.0
_ALLOWED_USER_CREDENTIAL_KEYS = frozenset({"api_key", "api_key_env", "tenant_id"})
_REMOVED_CUSTOM_HTTP_FIELDS = frozenset(
    {
        "connect_timeout_seconds",
        "max_connections",
        "max_keepalive_connections",
        "max_retries",
        "pool_timeout_seconds",
        "read_timeout_seconds",
        "write_timeout_seconds",
    }
)


@dataclass(frozen=True, slots=True)
class OpenVikingConfig:
    """Credential-bound connection settings and existing DeerFlow policy."""

    base_url: str
    storage_path: str
    owner_user_id: str | None
    api_key: str = field(repr=False)
    api_key_env: str | None
    isolation_mode: Literal["single_user", "multi_user"]
    user_credentials: Mapping[str, OpenVikingCredential] = field(repr=False)
    credential_provider: str | None
    credential_provider_config: Mapping[str, Any] = field(repr=False)
    pool_max_clients: int
    pool_idle_ttl_seconds: float | None
    default_peer_id: str
    timeout_seconds: float
    search_top_k: int
    score_threshold: float | None
    max_injection_chars: int
    content_mode: Literal["auto", "abstract", "overview", "read"]
    injection_query: str
    startup_policy: Literal["fail_fast", "warn"]
    read_failure_policy: Literal["fail_open", "raise"]
    write_failure_policy: Literal["log_and_drop", "raise"]
    allow_insecure_http: bool
    max_seen_message_ids: int

    @classmethod
    def from_backend_config(
        cls,
        backend_config: dict[str, Any] | None,
        *,
        has_injected_credential_provider: bool = False,
    ) -> OpenVikingConfig:
        """Parse and validate ``backend_config`` without imports or network I/O."""

        cfg = dict(backend_config or {})
        if "auth_mode" in cfg or "account" in cfg:
            raise ValueError("OpenViking trusted mode is no longer supported by this backend; use a USER API key and configure owner_user_id, user_credentials, or credential_provider")
        removed_fields = sorted(_REMOVED_CUSTOM_HTTP_FIELDS.intersection(cfg))
        if removed_fields:
            raise ValueError("OpenViking custom HTTP client fields are no longer supported: " + ", ".join(removed_fields))

        retrieval = _mapping(cfg.pop("retrieval", {}), "retrieval")
        failure_policy = _mapping(cfg.pop("failure_policy", {}), "failure_policy")
        client_pool = _mapping(cfg.pop("client_pool", {}), "client_pool")

        credential_provider = _parse_credential_provider(cfg.pop("credential_provider", None))
        provider_config = _mapping(cfg.pop("credential_provider_config", {}), "credential_provider_config")

        has_explicit_owner_user_id = "owner_user_id" in cfg
        has_explicit_api_key_env = "api_key_env" in cfg
        raw_owner_user_id = cfg.pop("owner_user_id", None)
        raw_api_key_env = cfg.pop("api_key_env", None)
        raw_user_credentials = cfg.pop("user_credentials", None)

        is_multi_user = raw_user_credentials is not None or credential_provider is not None or has_injected_credential_provider

        if provider_config and credential_provider is None:
            raise ValueError("OpenViking credential_provider_config requires credential_provider in backend_config")
        if client_pool and not is_multi_user:
            raise ValueError("OpenViking client_pool is only supported in multi-user mode with user_credentials or credential_provider")

        user_credential_unknowns: list[str] = []
        if is_multi_user:
            if has_explicit_owner_user_id or has_explicit_api_key_env:
                raise ValueError("OpenViking owner_user_id and api_key_env cannot be used in multi-user mode with user_credentials or credential_provider")
            if raw_user_credentials is not None:
                user_credential_unknowns = _validate_user_credentials_structure(raw_user_credentials)
            isolation_mode: Literal["single_user", "multi_user"] = "multi_user"
            owner_user_id: str | None = None
            api_key_env: str | None = None
            api_key = ""
        else:
            isolation_mode = "single_user"
            if raw_owner_user_id is None:
                owner_user_id = ""
            elif not isinstance(raw_owner_user_id, str) or has_control_chars(raw_owner_user_id):
                raise ValueError("OpenViking owner_user_id must be a string without control characters")
            else:
                owner_user_id = raw_owner_user_id.strip()
            if raw_api_key_env is None:
                api_key_env = "OPENVIKING_API_KEY"
            elif not isinstance(raw_api_key_env, str) or has_control_chars(raw_api_key_env):
                raise ValueError("OpenViking api_key_env must be a string without control characters")
            else:
                api_key_env = raw_api_key_env.strip()
            if not api_key_env:
                raise ValueError("OpenViking api_key_env must not be empty")
            api_key = os.environ.get(api_key_env, "").strip()

        pool_max_clients = _pool_int(client_pool, "max_clients", _DEFAULT_POOL_MAX_CLIENTS)
        pool_idle_ttl_seconds = _pool_idle_ttl(client_pool)

        base_url = str(cfg.pop("base_url", "http://127.0.0.1:1933")).rstrip("/")
        storage_path = str(cfg.pop("storage_path", ""))
        default_peer_id = str(cfg.pop("default_peer_id", "deerflow")).strip()
        timeout_seconds = _number(cfg, "timeout_seconds", 30.0, float)
        search_top_k = _number(retrieval, "top_k", 8, int)
        score_threshold = _optional_float(retrieval.pop("score_threshold", None), "score_threshold")
        max_injection_chars = _number(retrieval, "max_injection_chars", 12_000, int)
        content_mode = str(retrieval.pop("content_mode", "overview")).lower()
        injection_query = str(
            retrieval.pop(
                "injection_query",
                "user profile preferences important entities events ongoing goals constraints and prior decisions",
            )
        ).strip()
        startup_policy = str(cfg.pop("startup_policy", "fail_fast")).lower()
        read_failure_policy = str(failure_policy.pop("read", "fail_open")).lower()
        write_failure_policy = str(failure_policy.pop("write", "log_and_drop")).lower()
        allow_insecure_http = _boolean(cfg.pop("allow_insecure_http", False), "allow_insecure_http")
        max_seen_message_ids = _number(cfg, "max_seen_message_ids", 512, int)

        unknown = sorted(
            [
                *cfg,
                *(f"retrieval.{key}" for key in retrieval),
                *(f"failure_policy.{key}" for key in failure_policy),
                *(f"client_pool.{key}" for key in client_pool),
                *user_credential_unknowns,
            ]
        )
        if unknown:
            raise ValueError("Unknown OpenViking backend_config fields: " + ", ".join(unknown))

        parsed_user_credentials: dict[str, OpenVikingCredential] = {}
        if is_multi_user and raw_user_credentials is not None:
            if not raw_user_credentials and credential_provider is None and not has_injected_credential_provider:
                raise ValueError("OpenViking user_credentials must not be empty when no credential_provider is configured")
            parsed_user_credentials = _resolve_user_credentials(raw_user_credentials)

        result = cls(
            base_url=base_url,
            storage_path=storage_path,
            owner_user_id=owner_user_id,
            api_key=api_key,
            api_key_env=api_key_env,
            isolation_mode=isolation_mode,
            user_credentials=MappingProxyType(parsed_user_credentials),
            credential_provider=credential_provider,
            credential_provider_config=MappingProxyType(provider_config),
            pool_max_clients=pool_max_clients,
            pool_idle_ttl_seconds=pool_idle_ttl_seconds,
            default_peer_id=default_peer_id,
            timeout_seconds=timeout_seconds,
            search_top_k=search_top_k,
            score_threshold=score_threshold,
            max_injection_chars=max_injection_chars,
            content_mode=content_mode,  # type: ignore[arg-type]
            injection_query=injection_query,
            startup_policy=startup_policy,  # type: ignore[arg-type]
            read_failure_policy=read_failure_policy,  # type: ignore[arg-type]
            write_failure_policy=write_failure_policy,  # type: ignore[arg-type]
            allow_insecure_http=allow_insecure_http,
            max_seen_message_ids=max_seen_message_ids,
        )
        result._validate()
        return result

    def _validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenViking base_url must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("OpenViking base_url must not embed credentials; configure api_key_env, user_credentials, or credential_provider instead")
        if parsed.scheme == "http" and not self.allow_insecure_http and parsed.hostname not in {"127.0.0.1", "localhost", "openviking"}:
            raise ValueError("OpenViking plain HTTP is allowed only for localhost/openviking; set allow_insecure_http=true only for a trusted internal network")
        if self.isolation_mode == "single_user":
            if not self.owner_user_id:
                raise ValueError("OpenViking owner_user_id must not be empty")
            if not self.api_key:
                raise ValueError(f"OpenViking USER API key is missing; set {self.api_key_env}")
            validate_api_key(self.api_key)
        if not 1 <= self.pool_max_clients <= _MAX_POOL_CLIENTS:
            raise ValueError(f"OpenViking client_pool.max_clients must be between 1 and {_MAX_POOL_CLIENTS}")
        if self.pool_idle_ttl_seconds is not None and (not isfinite(self.pool_idle_ttl_seconds) or self.pool_idle_ttl_seconds <= 0):
            raise ValueError("OpenViking client_pool.idle_ttl_seconds must be a finite value > 0 or null")
        if not is_safe_peer_id(self.default_peer_id):
            raise ValueError("OpenViking default_peer_id must start with a lowercase letter or digit and contain at most 64 lowercase letters, digits, '_' or '-'")
        if self.default_peer_id.startswith(GENERATED_PEER_PREFIX):
            raise ValueError(f"OpenViking default_peer_id must not start with the reserved prefix {GENERATED_PEER_PREFIX!r}")
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("OpenViking timeout_seconds must be a finite value > 0")
        if not 1 <= self.search_top_k <= 100:
            raise ValueError("OpenViking retrieval.top_k must be between 1 and 100")
        if self.score_threshold is not None and (not isfinite(self.score_threshold) or not 0 <= self.score_threshold <= 1):
            raise ValueError("OpenViking retrieval.score_threshold must be a finite value between 0 and 1")
        if not 256 <= self.max_injection_chars <= 100_000:
            raise ValueError("OpenViking retrieval.max_injection_chars must be between 256 and 100000")
        if self.content_mode not in {"auto", "abstract", "overview", "read"}:
            raise ValueError("OpenViking retrieval.content_mode must be auto, abstract, overview, or read")
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


def is_safe_peer_id(value: str) -> bool:
    """Return whether *value* is valid for an OpenViking actor peer."""

    return _SAFE_PEER_RE.fullmatch(value) is not None


def _parse_credential_provider(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("OpenViking credential_provider must be a non-empty string")
    if not value.strip():
        raise ValueError("OpenViking credential_provider must not be empty")
    validate_provider_path(value)
    return value


def _validate_user_credentials_structure(raw_user_credentials: Any) -> list[str]:
    if not isinstance(raw_user_credentials, dict):
        raise ValueError("OpenViking user_credentials must be a mapping")
    unknown: list[str] = []
    for raw_uid, raw_spec in raw_user_credentials.items():
        uid = validate_user_key(raw_uid)
        if not isinstance(raw_spec, dict):
            raise ValueError(f"OpenViking user_credentials.{uid} must be a mapping")
        for key in raw_spec:
            if not isinstance(key, str):
                raise ValueError(f"OpenViking user_credentials.{uid} keys must be strings, got {type(key).__name__}")
            if key not in _ALLOWED_USER_CREDENTIAL_KEYS:
                unknown.append(f"user_credentials.{uid}.{key}")
    return unknown


def _resolve_user_credentials(raw_user_credentials: dict[str, dict[str, Any]]) -> dict[str, OpenVikingCredential]:
    resolved: dict[str, OpenVikingCredential] = {}
    seen_fingerprints: dict[str, str] = {}
    for uid, spec in raw_user_credentials.items():
        has_inline = spec.get("api_key") is not None
        has_env = spec.get("api_key_env") is not None
        if has_inline == has_env:
            raise ValueError(f"OpenViking user_credentials.{uid} must specify exactly one of 'api_key' or 'api_key_env'")

        raw_tenant = spec.get("tenant_id")
        env_name: str | None = None
        if has_env:
            raw_env = spec["api_key_env"]
            if not isinstance(raw_env, str) or not raw_env.strip() or has_control_chars(raw_env):
                raise ValueError(f"OpenViking user_credentials.{uid}.api_key_env must be a non-empty string without control characters")
            env_name = raw_env.strip()
            api_key_value = os.environ.get(env_name, "").strip()
            if not api_key_value:
                raise ValueError(f"OpenViking USER API key is missing for user {uid!r}; set {env_name}")
        else:
            api_key_value = spec["api_key"]

        try:
            cred = OpenVikingCredential(
                api_key=api_key_value,
                tenant_id=raw_tenant,
                api_key_env=env_name,
            )
        except ValueError as exc:
            raise ValueError(f"Invalid OpenViking user_credentials.{uid}: {exc}") from exc

        existing_uid = seen_fingerprints.get(cred.key_fingerprint)
        if existing_uid is not None:
            raise ValueError(f"OpenViking user_credentials must not share the same API key across users ({existing_uid!r} and {uid!r})")
        seen_fingerprints[cred.key_fingerprint] = uid
        resolved[uid] = cred
    return resolved


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"OpenViking {name} must be a mapping")
    return dict(value)


def _number[T](cfg: dict[str, Any], key: str, default: T, cast: Callable[[Any], T]) -> T:
    """Read a numeric knob, treating a value-less key as unset.

    ``timeout_seconds:`` with nothing after it in YAML arrives as ``None``, and
    ``float(None)`` raises ``TypeError`` from inside backend construction without
    naming the knob or the file. A key carrying no value keeps its default -- the
    line ``_mapping`` and ``_boolean`` already draw -- and a value that cannot be
    cast is reported as the config mistake it is. Numeric strings keep working,
    because that is what ``int``/``float`` already accept.
    """
    value = cfg.pop(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ValueError(f"OpenViking {key} must be a number, got {type(value).__name__}")
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ValueError(f"OpenViking {key} must be a number, got {type(value).__name__}") from None


def _optional_float(value: Any, name: str) -> float | None:
    """Read a numeric knob where ``None`` is a meaningful value of its own: an
    unset score threshold means "apply none", so it stays ``None`` rather than
    falling back to a default."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"OpenViking {name} must be a number, got {type(value).__name__}")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"OpenViking {name} must be a number, got {type(value).__name__}") from None


def _pool_int(pool: dict[str, Any], key: str, default: int) -> int:
    value = pool.pop(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, (bool, float)):
        raise ValueError(f"OpenViking client_pool.{key} must be an integer, got {type(value).__name__}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"OpenViking client_pool.{key} must be an integer, got {type(value).__name__}") from None


def _pool_idle_ttl(pool: dict[str, Any]) -> float | None:
    if "idle_ttl_seconds" not in pool:
        return _DEFAULT_POOL_IDLE_TTL_SECONDS
    value = pool.pop("idle_ttl_seconds")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"OpenViking client_pool.idle_ttl_seconds must be a number, got {type(value).__name__}")
    if isinstance(value, str) and not value.strip():
        raise ValueError("OpenViking client_pool.idle_ttl_seconds must be a number or null, got empty str")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"OpenViking client_pool.idle_ttl_seconds must be a number, got {type(value).__name__}") from None


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
