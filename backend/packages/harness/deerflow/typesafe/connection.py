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
error that tells an operator which variable to set. A key that cannot be sent as a
header value — surrounding whitespace from a mounted secret, a non-printable
character — is rejected here instead of leaking into a per-call protocol error
whose message carries the whole ``Bearer`` header.

The two credential settings are resolved per *layer*: the first layer (consumer
``config``, then ``typesafe:``) that sets either one decides the credential, so a
consumer naming an environment variable is not silently overridden by a literal
key written in the shared block.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from deerflow.typesafe.validation import credential_text, finite_float, whole_number

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
    ``api_key`` and ``api_key_env`` are one credential *per layer*: see
    :func:`_resolve_credential`.

    ``configuration_source`` names the consumer's settings location (for example
    ``guardrails.provider.config``); it reaches the missing-credential message so
    an operator knows which block to edit. It never carries the credential.
    """
    override = _configured(settings)
    fallback = _configured(defaults)

    api_key_env = _first(override, fallback, "api_key_env", DEFAULT_API_KEY_ENV)
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ValueError("api_key_env must be a non-empty string naming the environment variable that holds the API key")

    api_key = _resolve_credential(override, fallback, api_key_env)
    if not isinstance(api_key, str) or not api_key:
        raise ValueError(f"TypeSafe requires an API key: pass 'api_key' in {configuration_source} or set the {api_key_env} environment variable")
    # Shape only, and never echoed: a key that cannot travel as a header value is a
    # configuration error here instead of a per-call protocol error whose message
    # carries the whole ``Bearer`` header into the guardrail's exception log.
    api_key = credential_text("api_key", api_key)

    base_url = _validated_base_url(_first(override, fallback, "base_url", DEFAULT_BASE_URL))

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


#: Schemes an endpoint base may use. ``http`` is allowed for any host on purpose:
#: an internal http endpoint is a legitimate deployment, and TLS policy is the
#: operator's. What is rejected is a base that no request could ever use.
_BASE_URL_SCHEMES = frozenset({"http", "https"})


def _resolve_credential(override: Mapping[str, object], fallback: Mapping[str, object], default_env: str) -> object:
    """The credential named by the first layer that sets either credential setting.

    One credential source per layer: a layer that names an environment variable is
    not overridden by a *different* layer's literal key, so a consumer configured
    with ``api_key_env`` keeps reading its own variable even when the shared
    ``typesafe:`` block also sets ``api_key`` (and its endpoint may not accept that
    key at all). Inside one layer ``api_key`` wins over that layer's own
    ``api_key_env``, which is what a standalone provider did. ``None`` from the
    environment stays a missing credential rather than falling back to another
    layer's key, and the built-in ``TYPESAFE_API_KEY`` is consulted only when no
    layer names a credential.
    """
    for layer in (override, fallback):
        if "api_key" in layer:
            return layer["api_key"]
        name = layer.get("api_key_env")
        if isinstance(name, str) and name:
            return os.environ.get(name)
    return os.environ.get(default_env)


def _validated_base_url(value: object) -> str:
    """Return a base URL a request can use, or raise at construction.

    A base that is not ``http(s)``, or that carries a query, fragment, embedded
    credentials, whitespace or a control character, builds fine today and then fails
    on every request: httpx rejects the scheme or the URL per call
    (``UnsupportedProtocol`` / ``InvalidURL``), and the query would be silently
    swallowed into the endpoint path this layer appends. Embedded credentials are
    refused as well because the base URL is published in every consumer's policy
    identity and reaches reason messages.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("base_url must be a non-empty string")
    if any(character.isspace() or ord(character) < 0x21 or ord(character) == 0x7F for character in value):
        raise ValueError("base_url must not contain whitespace or control characters")
    try:
        parts = urlsplit(value)
        parts.port  # a malformed port is a per-request httpx error; fail it here instead
    except ValueError as exc:
        raise ValueError(f"base_url is not a usable URL: {exc}") from None
    if parts.scheme not in _BASE_URL_SCHEMES or not parts.netloc:
        raise ValueError("base_url must be an absolute http:// or https:// URL")
    if parts.query or parts.fragment or "@" in parts.netloc:
        raise ValueError("base_url must not carry a query, fragment or credentials")
    return value


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
