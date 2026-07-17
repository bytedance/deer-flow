"""Provider factory — resolves and constructs the configured AuthorizationProvider.

This is the single entry point for creating an authorization provider from
``AuthorizationConfig``. It does not cache instances (Phase 1B resolves once
per agent build and passes the same instance to Layer 1 and Layer 2).
"""

from __future__ import annotations

from deerflow.authz.provider import AuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.reflection import resolve_variable


def resolve_authorization_provider(
    config: AuthorizationConfig,
) -> AuthorizationProvider | None:
    """Resolve the authorization provider from config.

    Returns:
        A constructed ``AuthorizationProvider`` instance, or ``None`` if
        authorization is disabled.

    Raises:
        ValueError: If ``enabled`` is True but no provider is configured,
            or if the class path is invalid / construction fails / the
            instance does not satisfy the ``AuthorizationProvider`` Protocol.
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
    try:
        instance = provider_cls(**kwargs)
    except Exception as err:
        raise ValueError(f"Failed to construct authorization provider '{class_path}': {err}") from err

    if not isinstance(instance, AuthorizationProvider):
        raise ValueError(f"Authorization provider '{class_path}' does not satisfy the AuthorizationProvider Protocol")

    return instance
