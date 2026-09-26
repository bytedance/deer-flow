"""Operator grants and service lifetime binding; no provider imports at startup."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelInvocationGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    roles: dict[str, str] = Field(min_length=1, description="Logical role to configured model name")
    max_concurrency: int = Field(default=2, ge=1, le=64)
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_input_chars: int = Field(default=262144, ge=1, le=1048576)
    max_output_chars: int = Field(default=65536, ge=1, le=1048576)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, roles):
        if any(not value or value != value.strip() for pair in roles.items() for value in pair):
            raise ValueError("Role and model names must be nonempty without surrounding whitespace")
        return roles


class ExtensionHostAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_invocation: ModelInvocationGrant | None = None


class ModelInvocationScope:
    """One install() owns one budget, even if it registers multiple services."""

    def __init__(self, source: str, grant: ModelInvocationGrant):
        self.source = source
        self.grant = grant.model_copy(deep=True)
        self.budget: ModelInvocationBudget | None = None

    def bind(self, app_config: Any):
        from deerflow.extensions.model_invocation import HostModelInvoker

        if self.budget is None:
            self.budget = ModelInvocationBudget(self.grant.max_concurrency)
        return HostModelInvoker(self.source, self.grant, self.budget, app_config)


class ModelInvocationBudget:
    """Loop-owned admission shared by every service in one installation."""

    def __init__(self, concurrency: int):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.capacity = 2 * concurrency
        self.admitted = 0
        # Strong references keep abandoned, shielded provider work alive.
        self.workers: set[asyncio.Task] = set()

    def retain(self, task):
        self.workers.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task):
        self.workers.discard(task)
        if not task.cancelled():
            task.exception()  # Consume abandoned failures without exposing provider text.


class ModelInvocationService:
    """Host adapter keeps capability revocation paired with service cleanup."""

    def __init__(self, service: Any, scope: ModelInvocationScope):
        self.service = service
        self.scope = scope
        self.invoker = None

    async def start(self, deps):
        raise RuntimeError("Granted services must be started through the host lifecycle")

    async def start_with_host(self, deps, app_config):
        self.invoker = self.scope.bind(app_config)
        try:
            await self.service.start(replace(deps, model_invoker=self.invoker))
        except BaseException:
            # Includes host cancellation: start() may already have spawned calls.
            self.invoker.close()
            raise

    async def stop(self):
        if self.invoker is not None:
            self.invoker.close()
        await self.service.stop()
