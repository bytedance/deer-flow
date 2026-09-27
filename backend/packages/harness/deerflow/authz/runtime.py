"""Provider factory — discovers and constructs the configured provider.

The two-phase API lets async callers offload class-path discovery/import while
constructing loop-affine providers on their running event loop. The synchronous
``resolve_authorization_provider`` convenience function composes both phases.
Instances are not cached (Phase 1B resolves once per agent build and passes the
same instance to Layer 1 and Layer 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deerflow.authz.provider import AuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.reflection import resolve_variable


@dataclass(frozen=True, slots=True)
class AuthorizationProviderSpec:
    """A discovered provider class and its constructor inputs."""

    class_path: str
    provider_cls: type[Any]
    kwargs: dict[str, Any]


def resolve_authorization_provider_spec(
    config: AuthorizationConfig,
) -> AuthorizationProviderSpec | None:
    """Discover a provider class without constructing the provider.

    Returns:
        Constructor inputs for the configured provider, or ``None`` if
        authorization is disabled. This discovery phase may import a custom
        module and is safe to offload from an async event loop.

    Raises:
        ValueError: If ``enabled`` is True but no provider is configured,
            or if the class path is invalid.
    """
    if not config.enabled:
        return None

    if config.provider is None:
        raise ValueError("authorization.enabled is true but no provider is configured; set authorization.provider.use to a class path")

    class_path = config.provider.use
    try:
        provider_cls = resolve_variable(class_path, expected_type=type)
    except (ImportError, ValueError) as err:
        raise ValueError(f"Failed to resolve authorization provider class '{class_path}': {err}") from err

    kwargs = dict(config.provider.config) if config.provider.config else {}
    return AuthorizationProviderSpec(class_path=class_path, provider_cls=provider_cls, kwargs=kwargs)


def construct_authorization_provider(
    spec: AuthorizationProviderSpec | None,
    config: AuthorizationConfig,
) -> AuthorizationProvider | None:
    """Construct and validate a previously discovered provider spec."""
    if spec is None:
        return None

    try:
        instance = spec.provider_cls(**spec.kwargs)
    except Exception as err:
        raise ValueError(f"Failed to construct authorization provider '{spec.class_path}': {err}") from err

    if not isinstance(instance, AuthorizationProvider):
        raise ValueError(f"Authorization provider '{spec.class_path}' does not satisfy the AuthorizationProvider Protocol")

    from deerflow.authz.rbac import RbacAuthorizationProvider

    if isinstance(instance, RbacAuthorizationProvider):
        try:
            instance.validate_role(config.default_role, field="authorization.default_role")
        except ValueError as err:
            raise ValueError(f"Invalid authorization default_role for provider '{spec.class_path}': {err}") from err

    return instance


def resolve_authorization_provider(
    config: AuthorizationConfig,
) -> AuthorizationProvider | None:
    """Discover, construct, and validate the configured provider synchronously."""
    return construct_authorization_provider(resolve_authorization_provider_spec(config), config)
