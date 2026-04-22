"""Config-driven route authorization injection for the auth plugin."""

from app.plugins.auth.injection.registry_loader import (
    RoutePolicyRegistry,
    RoutePolicySpec,
    load_route_policy_registry,
)
from app.plugins.auth.injection.route_injector import install_route_guards
from app.plugins.auth.injection.validation import validate_route_policy_registry

__all__ = [
    "RoutePolicyRegistry",
    "RoutePolicySpec",
    "install_route_guards",
    "load_route_policy_registry",
    "validate_route_policy_registry",
]
