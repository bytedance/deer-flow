"""Lazy singletons for enterprise resources (plan M1-7 / M2-8, RFC §9.3).

Each helper constructs its target on first use and caches the result so
repeated calls in a single process — typically from
``app/gateway/app.py`` ``lifespan`` and FastAPI route handlers — return
the same instance without redundant initialisation.

State is intentionally **module-global**. FastAPI's ``Depends`` chain
calls these factories from many places (lifespan, routes, tests); a
class-instance pattern would force every caller to thread a context
object. The trade-off is that tests must reset the cache explicitly via
:func:`_reset_for_tests`.

All factories are **defensive about config**: if the relevant
sub-module is disabled, they raise ``RuntimeError`` (or HTTP 503 for
request-time deps) so a buggy router cannot silently bypass the
operator's intent.

M2 audit deps
=============

The audit router needs the same :class:`AuditStorage` /
:class:`AuditSigner` that the agent middleware writes to — reading
from a different engine would create a split-brain where the router
can't see middleware-written rows. We therefore route through the
process-wide singletons in
:mod:`deerflow.enterprise.middlewares` (``get_audit_storage`` /
``get_audit_signer``), which in turn pull their session factory from
:func:`deerflow.enterprise.persistence.database.get_enterprise_session_factory`.
For that to work the same :class:`EnterpriseDatabase` instance must be
registered process-wide via :func:`set_enterprise_database` — which
:func:`get_enterprise_db` does on first call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from deerflow.config.app_config import get_app_config
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import AuditStorage
from deerflow.enterprise.config import AuditConfig, EnterpriseConfig
from deerflow.enterprise.middlewares import (
    get_audit_signer as _get_audit_signer_singleton,
)
from deerflow.enterprise.middlewares import (
    get_audit_storage as _get_audit_storage_singleton,
)
from deerflow.enterprise.persistence.database import EnterpriseDatabase, set_enterprise_database
from deerflow.enterprise.rbac.repository import (
    PostgresRbacRepository,
    RbacRepository,
    SqliteRbacRepository,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from deerflow.enterprise.rbac.permission_provider import RbacPermissionProvider


logger = logging.getLogger(__name__)


# ── Module-global singletons ────────────────────────────────────────────

_enterprise_db: EnterpriseDatabase | None = None
_rbac_repo: RbacRepository | None = None
_rbac_checker: RbacPermissionProvider | None = None


def get_enterprise_config() -> EnterpriseConfig:
    """Return the enterprise sub-tree of the resolved :class:`AppConfig`.

    Wrapped in its own helper so call sites do not need to chain through
    ``get_app_config().enterprise`` — easier to mock in tests.
    """
    return get_app_config().enterprise


async def get_enterprise_db() -> EnterpriseDatabase:
    """Initialise (once) and return the enterprise SQLAlchemy engine wrapper.

    The runtime ``init()`` only does a ``SELECT 1`` liveness check;
    schema management lives in Alembic (plan §9.4). This is safe to
    call from both ``lifespan`` and request handlers — only the first
    call pays the cost.

    Also registers the instance via
    :func:`set_enterprise_database` so M2's audit middleware singletons
    (``get_audit_storage`` / ``get_audit_signer`` in
    :mod:`deerflow.enterprise.middlewares`) resolve through the same
    engine and session factory.
    """
    global _enterprise_db
    if _enterprise_db is None:
        config = get_enterprise_config()
        if not config.enabled:
            raise RuntimeError(
                "get_enterprise_db() called with enterprise.enabled=false; callers must guard on config before requesting enterprise resources.",
            )
        _enterprise_db = EnterpriseDatabase(config.database)
        await _enterprise_db.init()
        set_enterprise_database(_enterprise_db)
        logger.info("Enterprise database initialised: %s", config.database.url)
    return _enterprise_db


async def get_rbac_repo() -> RbacRepository:
    """Return the :class:`RbacRepository` singleton.

    Selects ``PostgresRbacRepository`` when the configured DB URL points
    at PostgreSQL, otherwise ``SqliteRbacRepository``. Both share the
    same implementation today (see
    ``deerflow.enterprise.rbac.repository`` for the reasoning) — the
    branch is a placeholder for backend-specific tuning in later
    milestones.
    """
    global _rbac_repo
    if _rbac_repo is None:
        db = await get_enterprise_db()
        url = db._config.url  # noqa: SLF001 - intentional internal read
        if url.startswith(("postgresql", "postgres+", "postgresql+")):
            _rbac_repo = PostgresRbacRepository(db.session_factory)
        else:
            _rbac_repo = SqliteRbacRepository(db.session_factory)
    return _rbac_repo


async def get_rbac_checker() -> RbacPermissionProvider:
    """Build (once) and return the :class:`RbacPermissionProvider` singleton.

    NOTE: this factory does **not** call
    ``app.gateway.authz.set_permission_provider`` — wiring is the
    caller's responsibility (``lifespan`` does it in M1-9). Keeping
    wiring out of the factory means tests can construct a checker
    without mutating module-global state.
    """
    global _rbac_checker
    if _rbac_checker is None:
        from deerflow.enterprise.rbac.permission_provider import RbacPermissionProvider

        config = get_enterprise_config()
        if not config.rbac.enabled:
            raise RuntimeError(
                "get_rbac_checker() called with enterprise.rbac.enabled=false; callers must guard on config before requesting RBAC services.",
            )
        repo = await get_rbac_repo()
        _rbac_checker = RbacPermissionProvider(config.rbac, repo)
    return _rbac_checker


# ── M2 audit request-time deps (FastAPI ``Depends``) ───────────────────


def get_audit_config(request: Request) -> AuditConfig:
    """Return the active :class:`AuditConfig`.

    Raises 503 when audit is administratively disabled rather than 404
    — the route exists in the router table, the *feature* is off. A
    503 lets monitoring distinguish "feature off" from "route missing".
    """
    config = request.app.state.config.enterprise
    if not config.enabled or not config.audit.enabled:
        raise HTTPException(status_code=503, detail="Audit subsystem is disabled")
    return config.audit


def get_audit_storage(request: Request) -> AuditStorage:
    """Return the shared :class:`AuditStorage` singleton."""
    audit = get_audit_config(request)
    return _get_audit_storage_singleton(audit)


def get_audit_signer(request: Request) -> AuditSigner | None:
    """Return the shared :class:`AuditSigner` singleton (may be ``None``)."""
    audit = get_audit_config(request)
    return _get_audit_signer_singleton(audit)


def _reset_for_tests() -> None:
    """Clear every cached singleton — call from pytest fixtures only.

    Production code must never call this. Tests need it to avoid state
    bleed between cases that exercise different configurations.
    """
    global _enterprise_db, _rbac_repo, _rbac_checker
    _enterprise_db = None
    _rbac_repo = None
    _rbac_checker = None
    set_enterprise_database(None)


__all__ = [
    "_reset_for_tests",
    "get_audit_config",
    "get_audit_signer",
    "get_audit_storage",
    "get_enterprise_config",
    "get_enterprise_db",
    "get_rbac_checker",
    "get_rbac_repo",
]
