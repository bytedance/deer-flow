"""Auth-plugin bridge from request user to runtime actor context."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import Request

from deerflow.runtime.actor_context import ActorContext, bind_actor_context, reset_actor_context


def resolve_request_user_id(request: Request) -> str | None:
    scope = getattr(request, "scope", None)
    user = scope.get("user") if isinstance(scope, dict) else None
    if user is None:
        state = getattr(request, "state", None)
        state_vars = vars(state) if state is not None and hasattr(state, "__dict__") else {}
        user = state_vars.get("user")
    user_id = getattr(user, "id", None)
    if user_id is None:
        return None
    return str(user_id)


@contextmanager
def bind_request_actor_context(request: Request):
    token = bind_actor_context(ActorContext(user_id=resolve_request_user_id(request)))
    try:
        yield
    finally:
        reset_actor_context(token)


@contextmanager
def bind_user_actor_context(user_id: str | None):
    token = bind_actor_context(ActorContext(user_id=str(user_id) if user_id is not None else None))
    try:
        yield
    finally:
        reset_actor_context(token)


__all__ = ["bind_request_actor_context", "bind_user_actor_context", "resolve_request_user_id"]
