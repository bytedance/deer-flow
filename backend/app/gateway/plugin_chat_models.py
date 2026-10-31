"""User-bound, bounded chat-model access for authenticated plugin page actions.

This is separate from operator-granted background ModelInvoker roles. Browser
calls use the same model factory and model:use check as conversation requests.
No provider credentials or configurable endpoints cross the extension contract.
"""

from __future__ import annotations

import asyncio
import math
import weakref
from dataclasses import replace
from typing import Any

from deerflow_extension_api import ModelInvocationFailed, ModelInvocationRequest, ModelInvocationResult, ModelInvocationUnauthorized, ModelInvocationUnavailable
from fastapi import HTTPException

from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_SESSION
from app.gateway.authz import authorize_model_use


class _UserChatModelInvoker:
    def __init__(self, user: Any, app_config: Any, delegate: Any) -> None:
        self._user = user
        self._config = app_config
        self._delegate = delegate
        self._closed = False
        self._tasks: set[asyncio.Task] = set()

    def close(self) -> None:
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()
        self._delegate.close()

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        if self._closed:
            raise ModelInvocationUnavailable("Chat model capability has stopped")
        if not isinstance(request, ModelInvocationRequest):
            raise ModelInvocationFailed("Expected ModelInvocationRequest")
        timeout = request.timeout_seconds
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ModelInvocationFailed("timeout_seconds must be finite and positive")
        timeout = min(timeout, 120) if timeout is not None else 120
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            # Include the ordinary user-authorization check in the deadline.
            async with asyncio.timeout(timeout):
                return await self._invoke(request)
        except TimeoutError:
            raise ModelInvocationFailed("Chat model invocation timed out") from None
        finally:
            self._tasks.discard(task)

    async def _invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        if not isinstance(request, ModelInvocationRequest) or request.model_role is not None:
            raise ModelInvocationFailed("Chat model calls accept model_name, not plugin roles")
        name = request.model_name
        if name is None:
            name = self._config.models[0].name if self._config.models else None
        if not isinstance(name, str) or not name or self._config.get_model_config(name) is None:
            raise ModelInvocationUnavailable("Configured chat model is unavailable")
        try:
            await asyncio.to_thread(authorize_model_use, self._user, name, is_internal=False, app_config=self._config)
        except HTTPException as exc:
            if exc.status_code == 403:
                raise ModelInvocationUnauthorized("Chat model is not available to this user") from None
            raise ModelInvocationUnavailable("Chat model authorization is unavailable") from None
        return await self._delegate.invoke(replace(request, model_role=name, model_name=None))


class PluginChatModelRuntime:
    """One Gateway lifetime; budgets are shared per installed plugin namespace."""

    def __init__(self) -> None:
        self._budgets: dict[str, Any] = {}
        self._handles: weakref.WeakSet = weakref.WeakSet()
        self._closed = False

    def for_user(self, user: Any, namespace: str, app_config: Any) -> _UserChatModelInvoker:
        from deerflow.extensions.model_access import ModelInvocationBudget, ModelInvocationGrant
        from deerflow.extensions.model_invocation import HostModelInvoker

        if self._closed:
            raise ModelInvocationUnavailable("Chat model capability has stopped")
        roles = {model.name: model.name for model in app_config.models}
        if not roles:
            raise ModelInvocationUnavailable("No chat models are configured")
        grant = ModelInvocationGrant(roles=roles, timeout_seconds=120)
        budget = self._budgets.get(namespace)
        if budget is None:
            budget = ModelInvocationBudget(grant.max_concurrency)
            self._budgets[namespace] = budget
        delegate = HostModelInvoker(f"plugin-chat:{namespace}:{user.id}", grant, budget, app_config)
        handle = _UserChatModelInvoker(user, app_config, delegate)
        self._handles.add(handle)
        return handle

    async def bind(self, request: Any, namespace: str) -> _UserChatModelInvoker | None:
        # Trusted auth provenance only. Auth-disabled local deployments use
        # the same default user as ordinary conversation requests.
        if getattr(request.state, "auth_source", None) not in {AUTH_SOURCE_SESSION, AUTH_SOURCE_AUTH_DISABLED} or self._closed:
            return None
        from deerflow_extension_api.auth import resolve_principal

        from app.gateway.deps import get_optional_user_from_request
        from deerflow.config import get_app_config

        principal = resolve_principal(request)
        if principal is None or principal.is_internal:
            return None
        user = await get_optional_user_from_request(request)
        if user is None or str(user.id) != principal.user_id:
            return None
        config = await asyncio.to_thread(get_app_config)
        if not config.models:
            return None
        return self.for_user(user, namespace, config)

    def close(self) -> None:
        self._closed = True
        for handle in tuple(self._handles):
            handle.close()
