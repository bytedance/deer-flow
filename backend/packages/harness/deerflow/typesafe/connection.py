"""Effective TypeSafe connection settings: precedence, credential fingerprint, sharing key.

Every consumer resolves its connection through :func:`resolve_connection`, which
applies the one documented precedence — the consumer's own ``config``, then the
top-level ``typesafe:`` block, then the built-in defaults. The result is the
*effective configuration* (design §4 rule 1); a consumer override keeps working
exactly as a standalone setting did.

Two identities come out of this layer and must never be conflated (design §4
rule 2):

* :meth:`TypeSafeConnection.credential_fingerprint` and the client's
  ``sharing_key`` — internal, and the only place the credential is compared.
  They decide whether two consumers may share one request.
* :meth:`TypeSafeConnection.public_parameters` — the connection half of a
  consumer's public policy identity. It never contains the credential or its
  fingerprint.

The credential exists only inside this object: it is not in ``repr()``, not in
``public_parameters()``, and not in any error message. The environment-variable
name is kept out of ``repr()`` too, and appears only in the construction-time
error that tells an operator which variable to set.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from deerflow.typesafe.validation import finite_float, whole_number

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_API_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 5.0
DEFAULT_DEADLINE_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_RETRY_BACKOFF = 0.5

ENDPOINT_PATH = "/v1/systemone"

#: The keys a consumer ``config`` and the top-level ``typesafe:`` block may set.
#: Anything else in a consumer ``config`` is that consumer's own policy (thresholds,
#: questions, scope) and is deliberately not read here.
CONNECTION_FIELDS = (
    "api_key",
    "api_key_env",
    "base_url",
    "model",
    "timeout",
    "deadline_seconds",
    "max_attempts",
    "retry_backoff",
)

#: The one consumer mode this layer must understand: nothing is resolved, nothing
#: is constructed, no credential is looked up (design §4 rule 4).
MODE_OFF = "off"


@dataclass(frozen=True)
class TypeSafeConnection:
    """One consumer's resolved connection settings."""

    api_key: str = field(repr=False)
    api_key_env: str = field(repr=False)
    base_url: str
    model: str
    timeout: float
    deadline_seconds: float
    max_attempts: int
    retry_backoff: float

    @property
    def url(self) -> str:
        """The System One endpoint this connection posts to."""
        return f"{self.base_url.rstrip('/')}{ENDPOINT_PATH}"

    def credential_fingerprint(self) -> str:
        """A short digest of the credential, to compare consumers without recording either key."""
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:16]

    def public_parameters(self) -> dict[str, object]:
        """The connection's behaviour-affecting settings, for a consumer's public policy identity."""
        return {
            "model": self.model,
            "base_url": self.base_url.rstrip("/"),
            "timeout": self.timeout,
            "deadline_seconds": self.deadline_seconds,
            "max_attempts": self.max_attempts,
            "retry_backoff": self.retry_backoff,
        }


def resolve_connection(
    *,
    settings: Mapping[str, object] | None = None,
    defaults: Mapping[str, object] | None = None,
    configuration_source: str,
) -> TypeSafeConnection:
    """Resolve the effective connection for one consumer.

    ``settings`` is the consumer's own ``config``; ``defaults`` is the top-level
    ``typesafe:`` block (``TypeSafeConfig.connection_defaults()``). In both, a key
    that is absent — or explicitly ``None`` — is "not configured" and falls
    through to the next source; an explicitly blank value does not, so a blank
    ``api_key`` is reported rather than silently bypassed by the environment.

    ``configuration_source`` names the consumer's settings location (for example
    ``guardrails.provider.config``); it reaches the missing-credential message so
    an operator knows which block to edit. It never carries the credential.
    """
    override = _configured(settings)
    fallback = _configured(defaults)

    api_key_env = _first(override, fallback, "api_key_env", DEFAULT_API_KEY_ENV)
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ValueError("api_key_env must be a non-empty string naming the environment variable that holds the API key")

    if "api_key" in override:
        api_key: object = override["api_key"]
    elif "api_key" in fallback:
        api_key = fallback["api_key"]
    else:
        api_key = os.environ.get(api_key_env)
    if not isinstance(api_key, str) or not api_key:
        raise ValueError(f"TypeSafe requires an API key: pass 'api_key' in {configuration_source} or set the {api_key_env} environment variable")

    base_url = _first(override, fallback, "base_url", DEFAULT_BASE_URL)
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be a non-empty string")

    model = _first(override, fallback, "model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string; TypeSafe returns the version it actually served")

    return TypeSafeConnection(
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        model=model,
        timeout=finite_float("timeout", _first(override, fallback, "timeout", DEFAULT_TIMEOUT), minimum=0.0, exclusive=True),
        deadline_seconds=finite_float("deadline_seconds", _first(override, fallback, "deadline_seconds", DEFAULT_DEADLINE_SECONDS), minimum=0.0, exclusive=True),
        max_attempts=whole_number("max_attempts", _first(override, fallback, "max_attempts", DEFAULT_MAX_ATTEMPTS), minimum=1),
        retry_backoff=finite_float("retry_backoff", _first(override, fallback, "retry_backoff", DEFAULT_RETRY_BACKOFF), minimum=0.0),
    )


def resolve_connection_for_mode(
    *,
    mode: str,
    settings: Mapping[str, object] | None = None,
    defaults: Mapping[str, object] | None = None,
    configuration_source: str,
) -> TypeSafeConnection | None:
    """Resolve a mode-bearing consumer's connection, or ``None`` when it is off.

    ``off`` short-circuits before anything else: no credential lookup, no
    validation, no error. A consumer that is off resolves no class path either —
    reading ``mode`` is the only thing that happens — so a deployment without the
    optional vendor configuration still builds (design §4 rule 4).

    Every other mode resolves exactly as :func:`resolve_connection` does and
    fails at construction when the credential or a value is unusable.
    """
    if mode == MODE_OFF:
        return None
    return resolve_connection(settings=settings, defaults=defaults, configuration_source=configuration_source)


def _configured(settings: Mapping[str, object] | None) -> dict[str, object]:
    """Keep the connection keys this layer owns; ``None`` means "not configured"."""
    if settings is None:
        return {}
    return {key: value for key, value in settings.items() if value is not None and key in CONNECTION_FIELDS}


def typesafe_defaults() -> dict[str, object]:
    """The top-level ``typesafe:`` block, resolved on demand.

    Every consumer passes this as ``resolve_connection(defaults=...)`` so a value
    it does not set falls back to the shared block and then to the built-in
    defaults (design §4 rule 1). Imported lazily so that importing the transport
    layer does not pull in the configuration package.
    """
    from deerflow.config.typesafe_config import get_typesafe_config

    return get_typesafe_config().connection_defaults()


def _first(override: Mapping[str, object], fallback: Mapping[str, object], key: str, default: object) -> object:
    if key in override:
        return override[key]
    if key in fallback:
        return fallback[key]
    return default


__all__ = [
    "CONNECTION_FIELDS",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_BASE_URL",
    "DEFAULT_DEADLINE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MODEL",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_TIMEOUT",
    "ENDPOINT_PATH",
    "MODE_OFF",
    "TypeSafeConnection",
    "resolve_connection",
    "resolve_connection_for_mode",
    "typesafe_defaults",
]
