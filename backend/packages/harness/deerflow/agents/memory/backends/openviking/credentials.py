"""Credential types, validation, and dynamic provider loading for OpenViking."""

from __future__ import annotations

import hashlib
import importlib
import keyword
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

_MAX_TENANT_ID_LENGTH = 128
_ALLOWED_PROVIDER_RESULT_KEYS = frozenset({"api_key", "tenant_id"})


def has_control_chars(value: str) -> bool:
    """Return whether *value* contains NUL or any Unicode control character."""

    return any(ord(ch) < 0x20 or ord(ch) == 0x7F or 0x80 <= ord(ch) <= 0x9F or unicodedata.category(ch) == "Cc" for ch in value)


def validate_api_key(api_key: Any) -> str:
    """Validate an OpenViking USER API key without ever echoing its value."""

    if not isinstance(api_key, str):
        raise ValueError(f"OpenViking API key must be a non-empty string, got {type(api_key).__name__}")
    if not api_key:
        raise ValueError("OpenViking API key must not be empty")
    if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in api_key):
        raise ValueError("OpenViking API key must contain printable ASCII characters only (0x21..0x7E)")
    return api_key


def validate_tenant_id(tenant_id: Any) -> str | None:
    """Validate an optional DeerFlow tenant identifier."""

    if tenant_id is None:
        return None
    if not isinstance(tenant_id, str):
        raise ValueError(f"OpenViking tenant_id must be a string, got {type(tenant_id).__name__}")
    if not tenant_id:
        raise ValueError("OpenViking tenant_id must not be empty")
    if tenant_id != tenant_id.strip():
        raise ValueError("OpenViking tenant_id must not have leading or trailing whitespace")
    if len(tenant_id) > _MAX_TENANT_ID_LENGTH:
        raise ValueError(f"OpenViking tenant_id must be at most {_MAX_TENANT_ID_LENGTH} characters")
    if has_control_chars(tenant_id):
        raise ValueError("OpenViking tenant_id must not contain control characters")
    return tenant_id


def validate_user_key(user_id: Any) -> str:
    """Validate a static ``user_credentials`` map key."""

    if not isinstance(user_id, str):
        raise ValueError(f"OpenViking user_credentials keys must be strings, got {type(user_id).__name__}")
    if not user_id or user_id != user_id.strip() or has_control_chars(user_id):
        raise ValueError(f"OpenViking user_credentials key {user_id!r} must be a non-empty stripped string without control characters")
    return user_id


@dataclass(frozen=True, slots=True)
class OpenVikingCredential:
    """Validated OpenViking USER API credential for one DeerFlow identity."""

    api_key: str = field(repr=False)
    tenant_id: str | None = None
    api_key_env: str | None = None
    key_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        validated_key = validate_api_key(self.api_key)
        validated_tenant = validate_tenant_id(self.tenant_id)
        object.__setattr__(self, "api_key", validated_key)
        object.__setattr__(self, "tenant_id", validated_tenant)
        if self.api_key_env is not None:
            if not isinstance(self.api_key_env, str) or not self.api_key_env.strip() or has_control_chars(self.api_key_env):
                raise ValueError("OpenViking api_key_env must be a non-empty string without control characters when provided")
            object.__setattr__(self, "api_key_env", self.api_key_env.strip())
        digest = hashlib.sha256(validated_key.encode("utf-8")).hexdigest()
        object.__setattr__(self, "key_fingerprint", digest)


@runtime_checkable
class OpenVikingCredentialProvider(Protocol):
    """Dynamic per-user credential resolver for multi-user OpenViking deployments."""

    def resolve(self, user_id: str) -> OpenVikingCredential | Mapping[str, Any] | str | None:
        """Resolve an OpenViking USER credential for *user_id*, or ``None`` if unauthorized."""
        ...


def _is_valid_identifier(part: str) -> bool:
    return bool(part) and part.isidentifier() and not keyword.iskeyword(part)


def _parse_provider_path(path: str) -> tuple[str, list[str]]:
    if not isinstance(path, str) or not path or path != path.strip():
        raise ValueError("OpenViking credential_provider must be a non-empty 'module:attr' or 'module.attr' path")
    if ":" in path:
        if path.count(":") != 1:
            raise ValueError("OpenViking credential_provider must contain at most one ':' separator")
        module_path, attr_path = path.split(":", 1)
        module_parts = module_path.split(".")
        attr_parts = attr_path.split(".")
        if not module_parts or not attr_parts or not all(_is_valid_identifier(p) for p in (*module_parts, *attr_parts)):
            raise ValueError(f"Invalid OpenViking credential_provider path {path!r}: expected valid Python identifiers")
        return module_path, attr_parts

    parts = path.split(".")
    if len(parts) < 2 or not all(_is_valid_identifier(p) for p in parts):
        raise ValueError(f"Invalid OpenViking credential_provider path {path!r}: expected 'pkg.mod:Attr' or 'pkg.mod.Attr'")
    return ".".join(parts[:-1]), [parts[-1]]


def validate_provider_path(path: str) -> None:
    """Validate ``credential_provider`` dotted/colon path syntax without importing or doing I/O."""

    _parse_provider_path(path)


def _is_usable_provider(provider: Any) -> bool:
    return callable(getattr(provider, "resolve", None)) or callable(provider)


def load_credential_provider(path: str, config: Mapping[str, Any]) -> Any:
    """Import and instantiate/validate a configured OpenViking credential provider."""

    module_path, attr_parts = _parse_provider_path(path)
    if not isinstance(config, Mapping):
        raise ValueError("OpenViking credential_provider_config must be a mapping")
    kwargs = dict(config)

    module = importlib.import_module(module_path)
    target: Any = module
    for attr in attr_parts:
        target = getattr(target, attr)

    if isinstance(target, type):
        try:
            provider = target(**kwargs)
        except Exception as exc:
            raise ValueError(f"OpenViking credential_provider {path!r} initialization failed ({type(exc).__name__})") from None
        if not _is_usable_provider(provider):
            raise ValueError(f"OpenViking credential_provider {path!r} instance must define a callable 'resolve(user_id)' method or be callable")
        return provider

    if callable(target):
        if kwargs:
            try:
                provider = target(**kwargs)
            except Exception as exc:
                raise ValueError(f"OpenViking credential_provider {path!r} initialization failed ({type(exc).__name__})") from None
            if not _is_usable_provider(provider):
                raise ValueError(f"OpenViking credential_provider factory {path!r} must return a callable or an object with a callable 'resolve(user_id)' method")
            return provider
        return target

    raise ValueError(f"OpenViking credential_provider {path!r} must resolve to a class or callable, got {type(target).__name__}")


def normalize_resolved_credential(raw: Any, *, user_id: str) -> OpenVikingCredential | None:
    """Normalize a provider return value into ``OpenVikingCredential`` without echoing secrets."""

    if raw is None:
        return None
    if isinstance(raw, OpenVikingCredential):
        return raw
    if isinstance(raw, str):
        return OpenVikingCredential(api_key=raw)
    if isinstance(raw, Mapping):
        if not all(isinstance(k, str) for k in raw):
            raise ValueError(f"OpenViking credential provider returned non-string keys for user {user_id!r}")
        unknown = sorted(k for k in raw if k not in _ALLOWED_PROVIDER_RESULT_KEYS)
        if unknown:
            raise ValueError(f"OpenViking credential provider returned unsupported keys for user {user_id!r}: {', '.join(unknown)}")
        if "api_key" not in raw:
            raise ValueError(f"OpenViking credential provider response for user {user_id!r} is missing 'api_key'")
        api_key = raw["api_key"]
        if not isinstance(api_key, str) or not api_key:
            raise ValueError(f"OpenViking credential provider returned invalid 'api_key' for user {user_id!r}")
        tenant_id = raw.get("tenant_id")
        if tenant_id is not None and not isinstance(tenant_id, str):
            raise ValueError(f"OpenViking credential provider returned invalid 'tenant_id' for user {user_id!r}")
        return OpenVikingCredential(api_key=api_key, tenant_id=tenant_id)
    raise ValueError(f"OpenViking credential provider returned unsupported credential type {type(raw).__name__} for user {user_id!r}")


__all__ = [
    "OpenVikingCredential",
    "OpenVikingCredentialProvider",
    "has_control_chars",
    "load_credential_provider",
    "normalize_resolved_credential",
    "validate_api_key",
    "validate_provider_path",
    "validate_tenant_id",
    "validate_user_key",
]
