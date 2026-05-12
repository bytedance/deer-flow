"""Request-scoped user context for user-based authorization.

This module holds a :class:`~contextvars.ContextVar` that the gateway's
auth middleware sets after a successful authentication. Repository
methods read the contextvar via a sentinel default parameter, letting
routers stay free of ``user_id`` boilerplate.

Three-state semantics for the repository ``user_id`` parameter (the
consumer side of this module lives in ``deerflow.persistence.*``):

- ``_AUTO`` (module-private sentinel, default): read from contextvar;
  raise :class:`RuntimeError` if unset.
- Explicit ``str``: use the provided value, overriding contextvar.
- Explicit ``None``: no WHERE clause — used only by migration scripts
  and admin CLIs that intentionally bypass isolation.

Dependency direction
--------------------
``persistence`` (lower layer) reads from this module; ``gateway.auth``
(higher layer) writes to it. ``CurrentUser`` is defined here as a
:class:`typing.Protocol` so that ``persistence`` never needs to import
the concrete ``User`` class from ``gateway.auth.models``. Any object
with an ``.id: str`` attribute structurally satisfies the protocol.

Asyncio semantics
-----------------
``ContextVar`` is task-local under asyncio, not thread-local. Each
FastAPI request runs in its own task, so the context is naturally
isolated. ``asyncio.create_task`` and ``asyncio.to_thread`` inherit the
parent task's context, which is typically the intended behaviour; if
a background task must *not* see the foreground user, wrap it with
``contextvars.copy_context()`` to get a clean copy.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    """Structural type for the current authenticated user.

    Any object with an ``.id: str`` attribute satisfies this protocol.
    Concrete implementations live in ``app.gateway.auth.models.User``.
    """

    id: str


_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    """Set the current user for this async task.

    Returns a reset token that should be passed to
    :func:`reset_current_user` in a ``finally`` block to restore the
    previous context.
    """
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    """Restore the context to the state captured by ``token``."""
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or ``None`` if unset.

    Safe to call in any context. Used by code paths that can proceed
    without a user (e.g. migration scripts, public endpoints).
    """
    return _current_user.get()


def require_current_user() -> CurrentUser:
    """Return the current user, or raise :class:`RuntimeError`.

    Used by repository code that must not be called outside a
    request-authenticated context. The error message is phrased so
    that a caller debugging a stack trace can locate the offending
    code path.
    """
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user


# ---------------------------------------------------------------------------
# Effective user_id helpers (filesystem isolation)
# ---------------------------------------------------------------------------

DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    """Return the current user's id as a string, or DEFAULT_USER_ID if unset.

    Unlike :func:`require_current_user` this never raises — it is designed
    for filesystem-path resolution where a valid user bucket is always needed.
    """
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


def resolve_runtime_user_id(runtime: object | None) -> str:
    """Single source of truth for a tool/middleware's effective user_id.

    Resolution order (most authoritative first):
      1. ``runtime.context["user_id"]`` — set by ``inject_authenticated_user_context``
         in the gateway from the auth-validated ``request.state.user``. This is
         the only source that survives boundaries where the contextvar may have
         been lost (background tasks scheduled outside the request task,
         worker pools that don't copy_context, future cross-process drivers).
      2. The ``_current_user`` ContextVar — set by the auth middleware at
         request entry. Reliable for in-task work; copied by ``asyncio``
         child tasks and by ``ContextThreadPoolExecutor``.
      3. ``DEFAULT_USER_ID`` — last-resort fallback so unauthenticated
         CLI / migration / test paths keep working without raising.

    Tools that persist user-scoped state (custom agents, memory, uploads)
    MUST call this instead of ``get_effective_user_id()`` directly so they
    benefit from the runtime.context channel that ``setup_agent`` already
    relies on.
    """
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_user_id()


# ---------------------------------------------------------------------------
# Sentinel-based user_id resolution
# ---------------------------------------------------------------------------
#
# Repository methods accept a ``user_id`` keyword-only argument that
# defaults to ``AUTO``. The three possible values drive distinct
# behaviours; see the docstring on :func:`resolve_user_id`.


class _AutoSentinel:
    """Singleton marker meaning 'resolve user_id from contextvar'."""

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
    """Resolve the user_id parameter passed to a repository method.

    Three-state semantics:

    - :data:`AUTO` (default): read from contextvar; raise
      :class:`RuntimeError` if no user is in context. This is the
      common case for request-scoped calls.
    - Explicit ``str``: use the provided id verbatim, overriding any
      contextvar value. Useful for tests and admin-override flows.
    - Explicit ``None``: no filter — the repository should skip the
      user_id WHERE clause entirely. Reserved for migration scripts
      and CLI tools that intentionally bypass isolation.
    """
    if isinstance(value, _AutoSentinel):
        user = _current_user.get()
        if user is None:
            raise RuntimeError(f"{method_name} called with user_id=AUTO but no user context is set; pass an explicit user_id, set the contextvar via auth middleware, or opt out with user_id=None for migration/CLI paths.")
        # Coerce to ``str`` at the boundary: ``User.id`` is typed as
        # ``UUID`` for the API surface, but the persistence layer
        # stores ``user_id`` as ``String(64)`` and aiosqlite cannot
        # bind a raw UUID object to a VARCHAR column ("type 'UUID' is
        # not supported"). Honour the documented return type here
        # rather than ripple a type change through every caller.
        return str(user.id)
    return value
