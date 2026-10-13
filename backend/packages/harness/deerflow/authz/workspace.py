"""Workspace identity passed by trusted admission code, never deserialized from clients.

This module validates in-process shape and actor binding. It does not resolve
membership or authorize a resource: Gateway's membership resolver must recheck
workspace state, membership and policy versions before constructing the value.
The executor's signed transport must perform its own reauthorization on receipt.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace_id: str
    actor_user_id: str
    membership_version: int
    policy_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, str):
            raise ValueError("workspace_id must be a canonical UUID")
        try:
            canonical = str(UUID(self.workspace_id))
        except ValueError as exc:
            raise ValueError("workspace_id must be a canonical UUID") from exc
        if canonical != self.workspace_id:
            raise ValueError("workspace_id must be a canonical UUID")
        if not isinstance(self.actor_user_id, str) or not self.actor_user_id or len(self.actor_user_id) > 64 or self.actor_user_id.strip() != self.actor_user_id:
            raise ValueError("actor_user_id must be a nonempty native user identifier")
        if any(ord(character) < 32 or ord(character) == 127 for character in self.actor_user_id):
            raise ValueError("actor_user_id contains control characters")
        for version in (self.membership_version, self.policy_version):
            if type(version) is not int or version < 1:
                raise ValueError("workspace versions must be positive integers")


_current_workspace: ContextVar[WorkspaceContext | None] = ContextVar("deerflow_current_workspace", default=None)


def set_current_workspace(context: WorkspaceContext) -> Token[WorkspaceContext | None]:
    """Bind a resolver-produced context; restore the returned token in finally."""
    if type(context) is not WorkspaceContext:
        raise TypeError("workspace context must be resolved by trusted admission")
    return _current_workspace.set(context)


def reset_current_workspace(token: Token[WorkspaceContext | None]) -> None:
    _current_workspace.reset(token)


def get_current_workspace() -> WorkspaceContext | None:
    return _current_workspace.get()


def require_current_workspace(*, actor_user_id: str, enabled: bool) -> WorkspaceContext | None:
    """Enforce actor binding; enabled must come from operator/runtime state.

    Legacy mode returns None only without a bound workspace. This function is
    not a configuration downgrade gate; activation must be enforced at startup.
    """
    context = _current_workspace.get()
    if context is None:
        if enabled:
            raise PermissionError("workspace context is required")
        return None
    if context.actor_user_id != actor_user_id:
        raise PermissionError("workspace actor does not match authenticated user")
    return context
