"""Pydantic models for DeerFlow Enterprise configuration.

Mirrors RFC §3.2. The schema is intentionally tolerant — when
``enterprise.enabled`` is ``False`` (the default), every sub-section is
ignored at runtime, so users can drop the whole ``enterprise:`` block from
``config.yaml`` without losing functionality.

The ``EnterpriseConfig.model_validator(mode="after")`` enforces the
illegal / degenerate combinations called out in the plan §8.2 matrix:

- Illegal (fail-fast, raises ``ValueError``):
  * ``approval.enabled=true`` + ``rbac.enabled=false``
    Approver resolution needs ``User.roles``; without RBAC the engine has
    no role data to look up and every ticket would be unanswerable.
  * ``approval.enabled=true`` + ``audit.enabled=false``
    Approval is a compliance feature; suppressing audit breaks the
    auditable-chain guarantee the workflow exists to provide.

- Warning (allowed but loud, emits ``logger.warning``):
  * ``oidc.enabled=true`` + ``rbac.enabled=false`` — OIDC writes
    ``user.roles`` but nothing consumes them.
  * ``enabled=false`` + any sub-module ``enabled=true`` — the sub-module
    is silently inert; surface it to the operator.
"""

from __future__ import annotations

import logging
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class RbacConfig(BaseModel):
    """Role-Based Access Control configuration."""

    enabled: bool = Field(default=False, description="Enable enterprise RBAC permission resolution")
    default_role: str = Field(
        default="member",
        description="Default role assigned to users without an explicit role (e.g. OIDC JIT provisioning)",
    )
    role_permissions: dict[str, list[str]] | None = Field(
        default=None,
        description="Override default role->permissions mapping. None falls back to DEFAULT_ROLE_PERMISSIONS in M1.",
    )

    model_config = ConfigDict(extra="forbid")


class AuditStorageConfig(BaseModel):
    """Audit storage backend selector."""

    use: str = Field(
        default="deerflow.enterprise.audit.storage:SqliteAuditStorage",
        description="Class path of the AuditStorage implementation (resolved by reflection in M2)",
    )

    model_config = ConfigDict(extra="allow")


class AuditConfig(BaseModel):
    """Audit log configuration."""

    enabled: bool = Field(default=False, description="Enable audit middleware and storage")
    storage: AuditStorageConfig = Field(default_factory=AuditStorageConfig, description="Audit storage backend")
    retention_days: int = Field(default=2555, description="Retention window in days (default ~7 years for SOX-style requirements)")
    sign_key: str | None = Field(default=None, description="HMAC sign key for tamper-evident events. Required when enabled=true.")

    model_config = ConfigDict(extra="forbid")


class ApprovalRuleConfig(BaseModel):
    """One declarative approval rule (M3 will consume this)."""

    id: str = Field(description="Unique rule identifier")
    name: str = Field(description="Human-readable rule name")
    action_type: str = Field(description='Action namespace, e.g. "sandbox:command" or "data:export"')
    condition: str | None = Field(default=None, description="Optional restricted-AST expression evaluated against tool input")
    approver_roles: list[str] = Field(default_factory=list, description="Roles allowed to approve this rule")
    urgency: str = Field(default="normal", description="One of normal/urgent/critical")
    deadline_hours: int = Field(default=24, description="Auto-expire window in hours")
    min_approvals: int = Field(default=1, description="Number of distinct approvers required")
    enabled: bool = Field(default=True, description="Per-rule enable flag")

    model_config = ConfigDict(extra="forbid")


class ApprovalNotifierConfig(BaseModel):
    """Notifier plug-in entry."""

    use: str = Field(description="Class path of the ApprovalNotifier implementation")

    model_config = ConfigDict(extra="allow")


class ApprovalConfig(BaseModel):
    """Human-in-the-loop approval workflow configuration."""

    enabled: bool = Field(default=False, description="Enable approval workflow")
    rules: list[ApprovalRuleConfig] = Field(default_factory=list, description="Declarative approval rules")
    notifiers: list[ApprovalNotifierConfig] = Field(default_factory=list, description="Notifier chain (web/feishu/wecom in M3)")
    timeout_check_interval_seconds: int = Field(default=60, description="Background timeout checker poll interval")

    model_config = ConfigDict(extra="forbid")


class OIDCRoleMappingConfig(BaseModel):
    """OIDC claim -> role mapping."""

    claim_field: str = Field(default="groups", description="Name of the ID-token claim that carries role data")
    mappings: dict[str, str] = Field(default_factory=dict, description="claim value -> internal role id")
    default_role: str = Field(default="member", description="Fallback role when no mapping matches")

    model_config = ConfigDict(extra="forbid")


class OIDCConfig(BaseModel):
    """OIDC single sign-on configuration."""

    enabled: bool = Field(default=False, description="Enable OIDC authentication")
    issuer: str | None = Field(default=None, description="IdP issuer URL (used for OIDC discovery)")
    client_id: str | None = Field(default=None, description="OAuth2 client ID registered with the IdP")
    client_secret: str | None = Field(default=None, description="OAuth2 client secret")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        description="OIDC scopes requested at authorization time",
    )
    redirect_uri: str | None = Field(default=None, description="Absolute callback URL registered with the IdP")
    role_mapping: OIDCRoleMappingConfig = Field(default_factory=OIDCRoleMappingConfig, description="claim -> role mapping")
    auto_provision: bool = Field(default=True, description="Create new local users on first OIDC login")
    jwks_cache_ttl_seconds: int = Field(default=600, description="JWKS cache TTL in seconds")

    model_config = ConfigDict(extra="forbid")


class EnterpriseAuthConfig(BaseModel):
    """Aggregator for authentication sub-modules."""

    oidc: OIDCConfig = Field(default_factory=OIDCConfig, description="OIDC single sign-on configuration")

    model_config = ConfigDict(extra="forbid")


class EnterpriseDatabaseConfig(BaseModel):
    """Connection settings for the enterprise SQLAlchemy engine.

    Defaults to a local SQLite file so the package is usable out of the box
    once ``enterprise.enabled=true``. Production deployments override this
    with a PostgreSQL DSN.
    """

    url: str = Field(default="sqlite+aiosqlite:///./enterprise.db", description="Async SQLAlchemy URL")
    echo: bool = Field(default=False, description="Echo SQL to logs (debug only)")
    pool_size: int = Field(default=5, description="Connection pool size for non-SQLite backends")

    model_config = ConfigDict(extra="forbid")


class EnterpriseConfig(BaseModel):
    """Top-level enterprise configuration block.

    All sub-modules default to disabled; loading the package has zero
    behavioural impact unless the operator opts in.
    """

    enabled: bool = Field(default=False, description="Master switch for the enterprise extension")
    rbac: RbacConfig = Field(default_factory=RbacConfig, description="RBAC configuration")
    audit: AuditConfig = Field(default_factory=AuditConfig, description="Audit configuration")
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig, description="Approval workflow configuration")
    auth: EnterpriseAuthConfig = Field(default_factory=EnterpriseAuthConfig, description="Authentication add-ons (OIDC)")
    database: EnterpriseDatabaseConfig = Field(default_factory=EnterpriseDatabaseConfig, description="Enterprise database connection")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_combinations(self) -> Self:
        """Enforce the legality matrix from plan §8.2.

        Illegal combinations raise ``ValueError`` (which becomes a fatal
        startup error in FastAPI's lifespan), degenerate combinations log
        a warning so the operator notices the silent inert state.
        """

        if self.enabled:
            if self.approval.enabled and not self.rbac.enabled:
                raise ValueError("Invalid enterprise configuration: approval.enabled=true requires rbac.enabled=true because ApprovalRuleEngine resolves approvers by role. Either disable approval.enabled or enable rbac.enabled.")
            if self.approval.enabled and not self.audit.enabled:
                raise ValueError("Invalid enterprise configuration: approval.enabled=true requires audit.enabled=true so approval decisions can be recorded for compliance. Either disable approval.enabled or enable audit.enabled.")

            if self.auth.oidc.enabled and not self.rbac.enabled:
                logger.warning(
                    "Enterprise config warning: oidc.enabled=true with rbac.enabled=false — OIDC will write user.roles but no downstream consumer reads them.",
                )
            if self.audit.enabled and not self.audit.sign_key:
                logger.warning(
                    "Enterprise config warning: audit.enabled=true but audit.sign_key is empty — events will be appended without HMAC signatures (tamper detection disabled).",
                )

        else:
            sub_enabled = []
            if self.rbac.enabled:
                sub_enabled.append("rbac")
            if self.audit.enabled:
                sub_enabled.append("audit")
            if self.approval.enabled:
                sub_enabled.append("approval")
            if self.auth.oidc.enabled:
                sub_enabled.append("auth.oidc")
            if sub_enabled:
                logger.warning(
                    "Enterprise config warning: enterprise.enabled=false but the following sub-modules are enabled and will be ignored: %s",
                    ", ".join(sub_enabled),
                )

        return self


__all__ = [
    "ApprovalConfig",
    "ApprovalNotifierConfig",
    "ApprovalRuleConfig",
    "AuditConfig",
    "AuditStorageConfig",
    "EnterpriseAuthConfig",
    "EnterpriseConfig",
    "EnterpriseDatabaseConfig",
    "OIDCConfig",
    "OIDCRoleMappingConfig",
    "RbacConfig",
]
