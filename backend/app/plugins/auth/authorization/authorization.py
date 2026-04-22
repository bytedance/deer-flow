"""Authorization requirement and policy evaluation helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from app.plugins.auth.authorization.policies import require_thread_owner
from app.plugins.auth.authorization.types import AuthContext


@dataclass(frozen=True)
class PermissionRequirement:
    """Authorization requirement for a single route action."""

    resource: str
    action: str
    owner_check: bool = False
    require_existing: bool = False

    @property
    def permission(self) -> str:
        return f"{self.resource}:{self.action}"


PolicyEvaluator = Callable[[Request, AuthContext, PermissionRequirement, Mapping[str, Any]], Awaitable[None]]


def ensure_authenticated(auth: AuthContext) -> None:
    if not auth.is_authenticated:
        raise HTTPException(status_code=401, detail="Authentication required")


def ensure_capability(auth: AuthContext, requirement: PermissionRequirement) -> None:
    if not auth.has_permission(requirement.resource, requirement.action):
        raise HTTPException(status_code=403, detail=f"Permission denied: {requirement.permission}")


async def evaluate_owner_policy(
    request: Request,
    auth: AuthContext,
    requirement: PermissionRequirement,
    route_params: Mapping[str, Any],
) -> None:
    if not requirement.owner_check:
        return

    thread_id = route_params.get("thread_id")
    if thread_id is None:
        raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

    await require_thread_owner(
        request,
        auth,
        thread_id=thread_id,
        require_existing=requirement.require_existing,
    )


async def evaluate_requirement(
    request: Request,
    auth: AuthContext,
    requirement: PermissionRequirement,
    route_params: Mapping[str, Any],
    *,
    policy_evaluators: tuple[PolicyEvaluator, ...],
) -> None:
    ensure_authenticated(auth)
    ensure_capability(auth, requirement)
    for evaluator in policy_evaluators:
        await evaluator(request, auth, requirement, route_params)


__all__ = [
    "PermissionRequirement",
    "PolicyEvaluator",
    "ensure_authenticated",
    "ensure_capability",
    "evaluate_owner_policy",
    "evaluate_requirement",
]
