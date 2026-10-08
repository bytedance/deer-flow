"""Resolve and hold the Gateway's login throttle store.

The auth router counts failed local logins through a
:class:`~deerflow.persistence.login_throttle.LoginThrottleStore`. Which
implementation backs it is decided once per process from
``auth.local.throttle_storage`` and ``database.backend``
(:func:`deerflow.config.auth_config.resolve_login_throttle_storage`):

- ``db`` (the ``auto`` result whenever an application database exists) —
  :class:`SqlLoginThrottleStore` over the shared ``login_throttle`` table, so
  every Gateway replica using that database enforces one lockout per IP;
- ``memory`` — :class:`MemoryLoginThrottleStore`, the historical per-process
  dict; under several replicas an attacker gets N × ``max_login_attempts``
  guesses, which ``app.gateway.deps._validate_login_throttle_storage`` warns
  about at startup.

``langgraph_runtime`` installs the store right after the persistence engine
is initialised, mirroring ``get_local_provider``'s process-level cache. A bare
app that never ran that lifespan (tests, embedded routers) resolves lazily on
the first throttle call from the live config. Tests swap the store through
:func:`install_login_throttle_store` / :func:`reset_login_throttle_store`.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from deerflow.config.auth_config import LocalAuthConfig, resolve_login_throttle_storage
from deerflow.persistence.login_throttle import LoginThrottleStore, MemoryLoginThrottleStore, SqlLoginThrottleStore

logger = logging.getLogger(__name__)

_store: LoginThrottleStore | None = None
_install_lock = threading.Lock()


def resolve_login_throttle_store(config: Any | None, *, session_factory: Any | None) -> LoginThrottleStore:
    """Build the store ``config`` asks for, given the (possibly absent) ORM session factory.

    Never raises for a missing database: the login endpoint must keep
    throttling, so an unsatisfiable ``db`` request degrades to the in-process
    counter with a warning instead of failing every login.
    """
    local = getattr(getattr(config, "auth", None), "local", None)
    selector = getattr(local, "throttle_storage", LocalAuthConfig.model_fields["throttle_storage"].default)
    selector_value = str(getattr(selector, "value", selector))
    database_backend = getattr(getattr(config, "database", None), "backend", None)
    resolved = resolve_login_throttle_storage(selector, database_backend)
    if resolved == "memory":
        if selector_value == "db":
            logger.warning(
                "auth.local.throttle_storage=db requires database.backend to be 'sqlite' or 'postgres' (got %r). Falling back to the in-process login throttle counter: lockouts are per Gateway process and are not shared across replicas.",
                database_backend,
            )
        return MemoryLoginThrottleStore()
    if session_factory is None:
        logger.warning(
            "auth.local.throttle_storage=%s resolved to the shared database table, but no persistence engine is initialised. Falling back to the in-process login throttle counter for this process.",
            selector_value,
        )
        return MemoryLoginThrottleStore()
    logger.info("auth.local.throttle_storage=%s resolved to the shared login_throttle table (database.backend=%s); login lockouts are enforced across every Gateway replica using this database.", selector_value, database_backend)
    return SqlLoginThrottleStore(session_factory)


def installed_login_throttle_store() -> LoginThrottleStore | None:
    """The store installed for this process, or ``None`` before startup / after reset."""
    return _store


def install_login_throttle_store(store: LoginThrottleStore) -> None:
    """Make ``store`` the process-wide login throttle store (startup and test hook)."""
    global _store
    _store = store


def reset_login_throttle_store() -> None:
    """Forget the installed store so the next throttle call resolves afresh."""
    global _store
    _store = None


def resolve_and_install_from_live_config() -> LoginThrottleStore:
    """Lazy fallback for apps without the Gateway lifespan: resolve from ``get_app_config()``.

    Synchronous and blocking (it reads ``config.yaml``); the router calls it
    through ``asyncio.to_thread``. Only ``FileNotFoundError`` falls back to the
    ``LocalAuthConfig`` defaults, matching ``_login_throttle_policy``: a
    malformed config propagates rather than silently picking a store. Racing
    resolvers keep the first installed store.
    """
    from deerflow.config.app_config import get_app_config
    from deerflow.persistence.engine import get_session_factory

    with _install_lock:
        if _store is not None:
            return _store
        try:
            config: Any = get_app_config()
        except FileNotFoundError:
            config = None
        store = resolve_login_throttle_store(config, session_factory=get_session_factory())
        install_login_throttle_store(store)
        return store
