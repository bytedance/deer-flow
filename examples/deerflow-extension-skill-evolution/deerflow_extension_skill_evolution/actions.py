"""Plugin backend actions that drive the guarded managed-mutation pipeline.

Every handler takes ``(payload, ctx)`` where ``ctx.principal`` is the
host-stamped, authenticated caller. The acting owner is **always** the
principal's user id — never a payload field — and ``mutations.py`` requires
it to match the evidence source / proposal / operation owner on every call.
Payloads are validated fail-closed and bounded before reaching the adapter.
"""

from __future__ import annotations

from typing import Any

from deerflow_extension_api import ActionContext

from deerflow_extension_skill_evolution.mutations import ManagedEvolution

_MAX_SOURCE_BYTES = 128


def _user_id(ctx: ActionContext) -> str:
    user_id = getattr(ctx, "principal", None) and getattr(ctx.principal, "user_id", None)
    if not isinstance(user_id, str) or not user_id:
        return ""
    return user_id


def _source(payload: dict[str, Any]) -> Any:
    source = payload.get("source")
    if source is None:
        return None
    if not isinstance(source, dict) or set(source) != {"thread_id", "run_id"}:
        raise ValueError("source must be an object with exactly thread_id and run_id")
    for key in ("thread_id", "run_id"):
        value = source.get(key)
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_SOURCE_BYTES or any(ord(c) < 32 for c in value):
            raise ValueError(f"source.{key} must be a non-empty bounded string")
    return source


def _text(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


class ManagedEvolutionActions:
    """Bound adapter plus fail-closed payload validation for each action."""

    def __init__(self, evolution: ManagedEvolution) -> None:
        self._evolution = evolution

    async def managed_read(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.read(user_id=user_id, source=_source(data), skill_name=_text(data, "skill_name"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    async def managed_stage(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.stage(user_id=user_id, source=_source(data), skill_name=_text(data, "skill_name"), content=_text(data, "content"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    async def managed_check(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.check(user_id=user_id, proposal_id=_text(data, "proposal_id"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    async def managed_propose(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.propose(user_id=user_id, source=_source(data), skill_name=_text(data, "skill_name"), content=_text(data, "content"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    async def managed_publish(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.publish(user_id=user_id, proposal_id=_text(data, "proposal_id"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    async def managed_discard(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.discard(user_id=user_id, proposal_id=_text(data, "proposal_id"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    async def managed_rollback(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        user_id = _user_id(ctx)
        if not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        try:
            data = dict(payload)
            return await self._evolution.rollback(user_id=user_id, operation_id=_text(data, "operation_id"))
        except (ValueError, TypeError):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
