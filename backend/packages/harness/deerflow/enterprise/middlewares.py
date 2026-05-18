"""Enterprise agent-middleware composition.

Wired into the lead agent via
``deerflow.agents.lead_agent.agent._build_middlewares(custom_middlewares=...)``
through ``_make_lead_agent``. When ``enterprise.enabled=False`` (default),
the factory short-circuits and returns ``[]`` so callers can unconditionally
extend the middleware chain without paying any cost.

Storage / signer singletons
===========================

M2 materialises the :class:`AuditMiddleware` here, which means this
module is responsible for instantiating the :class:`AuditStorage` and
:class:`AuditSigner` it depends on. We keep two module-level singletons
keyed by their config so:

* The lead-agent factory can call ``get_enterprise_middlewares`` once
  per agent creation without paying the SQLAlchemy engine setup cost
  every time.
* The gateway router layer (``app.enterprise.routers.audit``) can pull
  the same instances via ``get_audit_storage`` / ``get_audit_signer``
  (M2-8) so middleware-written events are visible to the read API
  without a second engine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from deerflow.enterprise.config import AuditConfig, EnterpriseConfig
from deerflow.reflection import resolve_class

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.enterprise.audit.signer import AuditSigner
    from deerflow.enterprise.audit.storage import AuditStorage

logger = logging.getLogger(__name__)


# Module-level singletons. Keyed implicitly by the active
# AuditConfig — process-wide config is a stable input in DeerFlow, so a
# pair of nullables is the simplest correct cache.
_audit_storage: AuditStorage | None = None
_audit_signer: AuditSigner | None = None


def _build_audit_storage(audit: AuditConfig) -> AuditStorage:
    """Resolve and instantiate the configured ``AuditStorage`` class.

    ``audit.storage.use`` is a ``module.path:ClassName`` string handled
    by :func:`deerflow.reflection.resolver.resolve_class`. We import the
    base class lazily to avoid pulling SQLAlchemy at module load when
    enterprise is off.
    """
    from deerflow.enterprise.audit.storage import AuditStorage as _Base
    from deerflow.enterprise.persistence.database import get_enterprise_session_factory

    storage_cls = resolve_class(audit.storage.use, _Base)
    return storage_cls(get_enterprise_session_factory())


def _build_audit_signer(audit: AuditConfig) -> AuditSigner | None:
    """Build the HMAC signer iff a key is configured.

    ``None`` is a valid return: the config validator already warned
    that signatures are disabled in this case, and the middleware
    treats a missing signer as "append unsigned".
    """
    if not audit.sign_key:
        return None
    from deerflow.enterprise.audit.signer import AuditSigner

    return AuditSigner(audit.sign_key)


def get_audit_storage(audit: AuditConfig) -> AuditStorage:
    """Return the process-wide audit storage singleton."""
    global _audit_storage
    if _audit_storage is None:
        _audit_storage = _build_audit_storage(audit)
    return _audit_storage


def get_audit_signer(audit: AuditConfig) -> AuditSigner | None:
    """Return the process-wide audit signer singleton (may be ``None``)."""
    global _audit_signer
    if _audit_signer is None and audit.sign_key:
        _audit_signer = _build_audit_signer(audit)
    return _audit_signer


def reset_audit_singletons() -> None:
    """Drop cached storage/signer (used by tests across config swaps)."""
    global _audit_storage, _audit_signer
    _audit_storage = None
    _audit_signer = None


def get_enterprise_middlewares(config: EnterpriseConfig) -> list[AgentMiddleware]:
    """Build the enterprise agent-middleware chain for the current config.

    Args:
        config: The resolved :class:`EnterpriseConfig` from ``AppConfig``.

    Returns:
        Ordered list of :class:`AgentMiddleware` instances ready to be
        injected before :class:`ClarificationMiddleware`. Empty when
        ``config.enabled`` is false.
    """
    middlewares: list[AgentMiddleware] = []
    if not config.enabled:
        return middlewares

    if config.audit.enabled:
        from deerflow.enterprise.audit.middleware import AuditMiddleware

        storage = get_audit_storage(config.audit)
        signer = get_audit_signer(config.audit)
        middlewares.append(AuditMiddleware(config.audit, storage, signer))

    return middlewares


__all__ = [
    "get_audit_signer",
    "get_audit_storage",
    "get_enterprise_middlewares",
    "reset_audit_singletons",
]
