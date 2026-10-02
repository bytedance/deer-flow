"""Adapt the normal Gateway run routes to a revocable extension capability."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

from deerflow_extension_api.agent_runs import AgentRun, AgentRunError
from fastapi import HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_SESSION, get_auth_disabled_user, is_auth_disabled
from app.gateway.authz import AuthContext, resolve_route_permissions
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.utils.thread_id import ThreadId

_THREAD_ID = TypeAdapter(ThreadId)


def _json_object(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        raw = json.dumps(dict(value), allow_nan=False)
        if len(raw.encode()) > 256 * 1024:
            raise ValueError("payload too large")
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise AgentRunError(422, "Agent run input must be a JSON object of at most 256 KiB") from exc


def _view(response) -> AgentRun:
    return AgentRun(response.thread_id, response.run_id, response.status, response.assistant_id, response.stop_reason)


class GatewayAgentRunsHost:
    """One app lifetime; never retain an HTTP Request or its credentials."""

    def __init__(self, app, *, load_user: Callable[[str], Awaitable[Any]] | None):
        self.app = app
        self.load_user = load_user
        self.active = True

    def close(self) -> None:
        self.active = False

    def bind(self, request: Request):
        user = getattr(request.state, "user", None)
        auth = getattr(request.state, "auth", None)
        if user is None or auth is None or not auth.is_authenticated or str(auth.user.id) != str(user.id):
            raise PermissionError("Agent run control requires an authenticated user")
        source = getattr(request.state, "auth_source", None)
        # PAT revocation and internal-owner delegation need separate durable
        # grants. Never turn either into an unrestricted session capability.
        if source not in (AUTH_SOURCE_SESSION, AUTH_SOURCE_AUTH_DISABLED):
            return None
        return _BoundAgentRuns(self, str(user.id), user.token_version, source, frozenset(auth.permissions))


class _BoundAgentRuns:
    def __init__(self, host, user_id: str, token_version: int, source: str, permissions: frozenset[str]):
        self._host = host
        self._user_id = user_id
        self._token_version = token_version
        self._source = source
        self._permissions = permissions

    @asynccontextmanager
    async def _request(self, permission: str, thread_id: str | None = None):
        if not self._host.active:
            raise AgentRunError(503, "Agent run host unavailable")
        if self._source == AUTH_SOURCE_AUTH_DISABLED:
            user = get_auth_disabled_user() if is_auth_disabled() else None
        else:
            user = await self._host.load_user(self._user_id) if self._host.load_user is not None else None
        if user is None or str(user.id) != self._user_id or user.token_version != self._token_version or user.needs_setup:
            raise AgentRunError(403, "Agent run authorization revoked")
        permissions = self._permissions.intersection(await resolve_route_permissions(user, is_internal=False))
        if permission not in permissions:
            raise AgentRunError(403, f"Permission denied: {permission}")
        if not self._host.active:
            raise AgentRunError(503, "Agent run host unavailable")
        request = Request({"type": "http", "app": self._host.app, "method": "POST", "path": "/api/threads", "headers": [], "query_string": b"", "state": {}})
        request.state.user = user
        request.state.auth_source = self._source
        request.state.auth = AuthContext(user, list(permissions))
        token = set_current_user(user)
        try:
            if thread_id is not None:
                _THREAD_ID.validate_python(thread_id)
                # Read routes historically accept untracked legacy threads.
                # The delegated handle requires a live owned/shared row too.
                store = self._host.app.state.thread_store
                if not await store.check_access(thread_id, self._user_id, require_existing=True):
                    raise AgentRunError(404, "Thread not found")
            yield request
        except HTTPException as exc:
            raise AgentRunError(exc.status_code, str(exc.detail)) from exc
        except ValidationError as exc:
            raise AgentRunError(422, "Invalid Agent run request") from exc
        finally:
            reset_current_user(token)

    async def create_thread(self, *, assistant_id="lead_agent", thread_id=None, metadata=None) -> str:
        from app.gateway.routers.threads import ThreadCreateRequest, create_thread

        async with self._request("threads:write") as request:
            response = await create_thread(ThreadCreateRequest(assistant_id=assistant_id, thread_id=thread_id, metadata=_json_object(metadata) or {}), request)
            return response.thread_id

    async def _start(self, *, thread_id, input=None, resume=None, context=None, idempotency_key=None):
        from app.gateway.routers.thread_runs import create_run
        from app.gateway.run_models import RunCreateRequest
        from app.gateway.services import resolve_thread_assistant_id

        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200):
            raise AgentRunError(422, "Idempotency key must contain 1 to 200 characters")
        # Copy inputs before the first await; plugin tasks cannot mutate admitted data.
        run_input = _json_object(input)
        run_context = _json_object(context)
        command = _json_object({"resume": resume}) if resume is not None else None
        if run_context is not None and any(key in run_context for key in ("agent_name", "is_bootstrap")):
            raise AgentRunError(422, "Agent identity is bound to the thread")
        async with self._request("runs:create", thread_id) as request:
            assistant_id = await resolve_thread_assistant_id(request, thread_id, fail_closed=True)
            body = RunCreateRequest(assistant_id=assistant_id, input=run_input, command=command, context=run_context, on_disconnect="continue")
            response = await create_run(thread_id, body, request, idempotency_key=f"extension:{idempotency_key}" if idempotency_key is not None else None)
            return _view(response)

    async def start(self, *, thread_id, input, context=None, idempotency_key=None) -> AgentRun:
        return await self._start(thread_id=thread_id, input=input, context=context, idempotency_key=idempotency_key)

    async def resume(self, *, thread_id, resume, idempotency_key=None) -> AgentRun:
        if resume is None:
            raise AgentRunError(422, "An explicit interrupt response is required")
        return await self._start(thread_id=thread_id, resume=resume, idempotency_key=idempotency_key)

    async def get(self, *, thread_id, run_id) -> AgentRun:
        from app.gateway.routers.thread_runs import get_run

        async with self._request("runs:read", thread_id) as request:
            return _view(await get_run(thread_id, run_id, request))

    async def get_state(self, *, thread_id) -> dict[str, Any]:
        from app.gateway.routers.threads import get_thread_state

        async with self._request("threads:read", thread_id) as request:
            return (await get_thread_state(thread_id, request)).model_dump(mode="json")

    async def cancel(self, *, thread_id, run_id) -> None:
        from app.gateway.routers.thread_runs import cancel_run

        async with self._request("runs:cancel", thread_id) as request:
            await cancel_run(thread_id, run_id, request, wait=False, action="interrupt")

    async def wait(self, *, thread_id, run_id, timeout=60) -> AgentRun:
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise AgentRunError(422, "Wait timeout must be between 0 and 3600 seconds")
        async with asyncio.timeout(timeout):
            while True:
                run = await self.get(thread_id=thread_id, run_id=run_id)
                if run.status not in ("pending", "running"):
                    return run
                await asyncio.sleep(0.25)
