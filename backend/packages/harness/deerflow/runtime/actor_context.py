"""Request/task-scoped actor context for runtime-facing user isolation.

This module defines a runtime-owned context bridge that lower layers can
depend on without importing the auth plugin. The app/auth boundary maps
``request.user`` into :class:`ActorContext` and binds it before entering
runtime-facing code.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ActorContext:
    user_id: str | None = None
    # Future extension points:
    # subject_id: str | None = None
    # tenant_id: str | None = None
    # scopes: frozenset[str] = frozenset()
    # auth_source: str | None = None


_current_actor: Final[ContextVar[ActorContext | None]] = ContextVar(
    "deerflow_actor_context",
    default=None,
)


def bind_actor_context(actor: ActorContext) -> Token[ActorContext | None]:
    """Bind the current actor for this async task."""

    return _current_actor.set(actor)


def reset_actor_context(token: Token[ActorContext | None]) -> None:
    """Restore the actor context captured by ``token``."""

    _current_actor.reset(token)


def get_actor_context() -> ActorContext | None:
    """Return the current actor context, or ``None`` if unset."""

    return _current_actor.get()


def require_actor_context() -> ActorContext:
    """Return the current actor context, or raise if unset."""

    actor = _current_actor.get()
    if actor is None:
        raise RuntimeError("runtime accessed without actor context")
    return actor


DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    """Return the effective user id, or ``DEFAULT_USER_ID`` if unset."""

    actor = _current_actor.get()
    if actor is None or actor.user_id is None:
        return DEFAULT_USER_ID
    return str(actor.user_id)


class _AutoSentinel:
    """Singleton marker meaning 'resolve user_id from actor context'."""

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<AUTO>"


AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    """Resolve a repository ``user_id`` argument against the current actor."""

    if isinstance(value, _AutoSentinel):
        actor = _current_actor.get()
        if actor is None or actor.user_id is None:
            raise RuntimeError(
                f"{method_name} called with user_id=AUTO but no actor context is set; "
                "pass an explicit user_id, bind ActorContext at the app/runtime boundary, "
                "or opt out with user_id=None for migration/CLI paths."
            )
        return str(actor.user_id)
    return value


__all__ = [
    "AUTO",
    "ActorContext",
    "DEFAULT_USER_ID",
    "bind_actor_context",
    "get_actor_context",
    "get_effective_user_id",
    "require_actor_context",
    "reset_actor_context",
    "resolve_user_id",
]
