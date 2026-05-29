"""Integration configuration models.

Pydantic models for tenant-level integration system configuration,
capability routing, and entity linking.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RetryPolicy(BaseModel):
    """Retry configuration for transient failures."""

    max_retries: int = 2
    retry_on_status: list[int] = Field(
        default_factory=lambda: [502, 503, 504],
        description="HTTP status codes that trigger retry",
    )


class IntegrationSystemConfig(BaseModel):
    """Configuration for an external system connection."""

    system_key: str = Field(description="Unique identifier, e.g. 'ins_prod', 'sms_prod'")
    system_type: Literal["ins", "sms", "crm", "erp", "xsy", "custom"] = Field(
        description="Adapter type discriminator"
    )
    display_name: str = Field(description="Human-readable name")
    description: str = ""
    connector_ref: str | None = Field(
        default=None,
        description="Reference to existing tenant connector for transport",
    )
    transport_type: Literal["http", "rpc", "db", "file", "sdk"] = "http"
    base_url: str = Field(description="System base URL")
    base_path: str = ""
    auth_type: Literal["bearer", "api_key", "ins_base", "xsy_oauth2"] = Field(
        description="Authentication method"
    )
    auth_mode: Literal["static", "user_token"] = Field(
        default="static",
        description=(
            "How credentials are resolved for downstream calls. "
            "'static' uses secret_ref (service-to-service). "
            "'user_token' forwards the current user's access_token from the "
            "request cookie via AuthContext.token, falling back to secret_ref "
            "when no token is available (e.g. background tasks)."
        ),
    )
    secret_ref: str | None = Field(
        default=None,
        description="Secret reference: '$ENV_VAR' or 'tenant://secrets/xxx'",
    )
    timeout_seconds: float = 15.0
    max_retries: int = 2
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    priority: int = 100
    enabled: bool = True
    capabilities: list[str] = Field(
        default_factory=list,
        description="Capability keys this system can provide",
    )
    extra_config: dict[str, Any] = Field(default_factory=dict)

    def resolve_secret(self) -> str | None:
        """Resolve secret_ref to actual value.

        Supports:
        - '$ENV_VAR': reads from os.environ
        - 'tenant://secrets/xxx': TODO (phase 2)
        - None: returns None

        Raises:
            IntegrationConfigError: If env var is not set
        """
        if self.secret_ref is None:
            return None

        if self.secret_ref.startswith("$"):
            env_var = self.secret_ref[1:]
            value = os.environ.get(env_var)
            if value is None:
                from deerflow.integrations.errors import IntegrationConfigError

                raise IntegrationConfigError(
                    message=f"Secret not found: {env_var}",
                    system_key=self.system_key,
                )
            return value

        # TODO: tenant://secrets/xxx support in phase 2
        if self.secret_ref.startswith("tenant://"):
            from deerflow.integrations.errors import IntegrationConfigError

            raise IntegrationConfigError(
                message="Tenant secret store not yet implemented",
                system_key=self.system_key,
            )

        # Treat as literal value
        return self.secret_ref


class CapabilityRouteConfig(BaseModel):
    """Configuration for capability routing."""

    capability_key: str = Field(description="Capability identifier, e.g. 'monitoring.trend'")
    primary_system_key: str = Field(description="Authoritative system for this capability")
    enrich_system_keys: list[str] = Field(
        default_factory=list,
        description="Supplementary systems",
    )
    fallback_system_keys: list[str] = Field(
        default_factory=list,
        description="Fallback systems tried on primary failure",
    )
    enabled: bool = True
    timeout_seconds: float = 20.0
    merge_policy: Literal["primary_plus_enrich", "primary_only", "concatenate"] = (
        "primary_plus_enrich"
    )
    partial_failure_policy: Literal["return_partial", "fail_all", "ignore_failures"] = (
        "return_partial"
    )

    @model_validator(mode="after")
    def validate_no_overlap(self) -> "CapabilityRouteConfig":
        """Ensure enrich and fallback don't overlap."""
        overlap = set(self.enrich_system_keys) & set(self.fallback_system_keys)
        if overlap:
            raise ValueError(f"enrich and fallback cannot overlap: {overlap}")
        return self


class EntityLinkEntry(BaseModel):
    """Per-system entity mapping."""

    system_key: str
    remote_id: str
    remote_code: str | None = Field(
        default=None,
        description="Human-readable code in that system",
    )
    is_primary: bool = Field(
        default=False,
        description="Whether this system owns the canonical_id",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Mapping confidence (0.0 to 1.0)",
    )


class EntityLinkConfig(BaseModel):
    """Cross-system entity ID mapping."""

    tenant_id: str
    entity_type: Literal[
        "asset",
        "measurement_point",
        "customer",
        "contract",
        "work_order",
        "inventory_item",
        "spare_part",
    ]
    canonical_id: str = Field(description="Platform-level unified ID")
    display_name: str | None = None
    links: list[EntityLinkEntry] = Field(default_factory=list)
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Overall mapping reliability",
    )
    status: Literal["active", "inactive"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationsConfig(BaseModel):
    """Top-level integrations configuration."""

    enabled: bool = Field(
        default=True,
        description="Global kill switch",
    )
    systems: dict[str, IntegrationSystemConfig] = Field(default_factory=dict)
    routes: dict[str, CapabilityRouteConfig] = Field(default_factory=dict)
    entity_links: list[EntityLinkConfig] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_routes(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Parse routes from simple or full form, and backfill implicit keys."""
        # Inject the dict key as system_key for each system entry so users
        # don't have to repeat it inside the body.
        systems = data.get("systems")
        if isinstance(systems, dict):
            for key, value in systems.items():
                if isinstance(value, dict) and "system_key" not in value:
                    value["system_key"] = key

        # Default tenant_id for entity links that omit it.
        entity_links = data.get("entity_links")
        if isinstance(entity_links, list):
            for link in entity_links:
                if isinstance(link, dict) and "tenant_id" not in link:
                    link["tenant_id"] = "default"

        if "routes" not in data:
            return data

        routes = data["routes"]
        if not isinstance(routes, dict):
            return data

        parsed_routes = {}
        for key, value in routes.items():
            if isinstance(value, str):
                # Simple form: "monitoring.trend": "ins_prod"
                parsed_routes[key] = {
                    "capability_key": key,
                    "primary_system_key": value,
                }
            elif isinstance(value, dict):
                # Full form
                parsed_routes[key] = {
                    "capability_key": key,
                    **value,
                }
            else:
                parsed_routes[key] = value

        data["routes"] = parsed_routes
        return data

    @model_validator(mode="after")
    def validate_route_systems(self) -> "IntegrationsConfig":
        """Ensure all routes reference known systems."""
        system_keys = set(self.systems.keys())
        for route_key, route in self.routes.items():
            if route.primary_system_key not in system_keys:
                raise ValueError(
                    f"Route '{route_key}' references unknown system: {route.primary_system_key}"
                )
            for sys_key in route.enrich_system_keys:
                if sys_key not in system_keys:
                    raise ValueError(
                        f"Route '{route_key}' enrich references unknown system: {sys_key}"
                    )
            for sys_key in route.fallback_system_keys:
                if sys_key not in system_keys:
                    raise ValueError(
                        f"Route '{route_key}' fallback references unknown system: {sys_key}"
                    )
        return self
