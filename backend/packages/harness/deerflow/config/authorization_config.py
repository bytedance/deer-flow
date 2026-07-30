"""Configuration for fine-grained resource authorization.

When enabled, a pluggable :class:`~deerflow.authz.provider.AuthorizationProvider`
becomes the policy brain for resource-level authorization, enforced at two
layers: assembly-time capability filtering (tools the agent can never see) and
run-time execution deny (reuses :class:`~deerflow.guardrails.middleware.GuardrailMiddleware`
via an adapter). Default ``enabled: false`` preserves today's behavior where
every authenticated user has access to all tools, models, skills, and sandbox.
"""

from pydantic import BaseModel, Field


class AuthorizationProviderConfig(BaseModel):
    """Configuration for an authorization provider."""

    use: str = Field(description="Class path (e.g. 'deerflow.authz.rbac:RbacAuthorizationProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class AuthorizationConfig(BaseModel):
    """Configuration for fine-grained resource authorization.

    Mirrors :class:`~deerflow.config.guardrails_config.GuardrailsConfig` in
    shape: a provider loaded by class path, a fail-closed default, and a
    live-reloadable singleton.
    """

    enabled: bool = Field(default=False, description="Enable fine-grained authorization")
    fail_closed: bool = Field(default=True, description="Block access if the provider errors or identity is unresolved")
    default_role: str = Field(default="user", description="Role applied when user_role is None (e.g. unbound IM channels)")
    provider: AuthorizationProviderConfig | None = Field(default=None, description="Authorization provider configuration")


_authorization_config: AuthorizationConfig | None = None


def get_authorization_config() -> AuthorizationConfig:
    """Get the authorization config, returning defaults if not loaded."""
    global _authorization_config
    if _authorization_config is None:
        _authorization_config = AuthorizationConfig()
    return _authorization_config


def load_authorization_config_from_dict(data: dict) -> AuthorizationConfig:
    """Load authorization config from a dict (called during AppConfig loading)."""
    global _authorization_config
    _authorization_config = AuthorizationConfig.model_validate(data)
    return _authorization_config


def reset_authorization_config() -> None:
    """Reset the cached config instance. Used in tests to prevent singleton leaks."""
    global _authorization_config
    _authorization_config = None
