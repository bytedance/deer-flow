"""Middleware for logging and persisting LLM token usage with rate limiting and async batch writes."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)

# Per-tenant in-memory rate limit counters
_rate_limit_counters: dict[str, dict] = {}


def _get_tenant_counter(tenant_id: str) -> dict:
    now = datetime.now(timezone.utc)
    minute_key = now.strftime("%Y-%m-%dT%H:%M")
    if tenant_id not in _rate_limit_counters:
        _rate_limit_counters[tenant_id] = {"minute_key": minute_key, "calls": 0, "tokens": 0}
    counter = _rate_limit_counters[tenant_id]
    if counter["minute_key"] != minute_key:
        counter["minute_key"] = minute_key
        counter["calls"] = 0
        counter["tokens"] = 0
    return counter


class TokenUsageMiddleware(AgentMiddleware):
    """Logs and optionally persists token usage from model response usage_metadata.

    When cost management is enabled, records are buffered in memory and
    flushed asynchronously in batches to reduce filesystem I/O.
    """

    _BUFFER_FLUSH_SIZE = 50
    _BUFFER_FLUSH_INTERVAL = 5.0

    def __init__(self, storage: object | None = None, calculator: object | None = None) -> None:
        self.storage = storage
        self.calculator = calculator
        self._buffer: deque = deque()
        self._flush_task: asyncio.Task | None = None
        self._started = False

    def _ensure_flush_task(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._periodic_flush())
        except RuntimeError:
            pass

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self._BUFFER_FLUSH_INTERVAL)
            await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        if not self._buffer:
            return
        records = list(self._buffer)
        self._buffer.clear()
        try:
            for record in records:
                self.storage.add_record(record)
            logger.debug("Flushed %d token usage records", len(records))
        except Exception:
            logger.exception("Failed to flush token usage batch (%d records)", len(records))
            self._buffer.extendleft(reversed(records))

    async def shutdown(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_buffer()

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._process_usage(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._process_usage(state, runtime)

    def _check_llm_rate_limit(self, tenant_id: str, total_tokens: int) -> bool:
        """Check LLM-level rate limits. Returns True if allowed, False if exceeded."""
        from deerflow.config.rate_limit_config import get_rate_limit_config

        rl_config = get_rate_limit_config()
        if not rl_config.enabled:
            return True

        counter = _get_tenant_counter(tenant_id)
        counter["calls"] += 1
        counter["tokens"] += total_tokens

        if counter["calls"] > rl_config.llm_calls_per_minute:
            logger.warning("LLM call rate limit exceeded for tenant %s: %d calls", tenant_id, counter["calls"])
            return False

        if counter["tokens"] > rl_config.tokens_per_minute:
            logger.warning("LLM token rate limit exceeded for tenant %s: %d tokens", tenant_id, counter["tokens"])
            return False

        return True

    def _process_usage(self, state: AgentState, runtime: Runtime) -> None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        usage = getattr(last, "usage_metadata", None)
        if not usage:
            return None

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        logger.info(
            "LLM token usage: input=%s output=%s total=%s",
            input_tokens,
            output_tokens,
            total_tokens,
        )

        tenant_id = get_current_tenant_id()

        if not self._check_llm_rate_limit(tenant_id, total_tokens):
            logger.warning("LLM rate limit triggered for tenant %s", tenant_id)

        if self.storage is not None and self.calculator is not None:
            try:
                model_name = getattr(last, "response_metadata", {}).get("model_name", "unknown")
                cost = self.calculator.calculate(model_name, input_tokens, output_tokens)

                thread_id = None
                if runtime is not None:
                    ctx = getattr(runtime, "context", None) or {}
                    if isinstance(ctx, dict):
                        thread_id = ctx.get("thread_id")
                        # Prefer tenant_id from runtime context (set by frontend
                        # via LangGraph Server), falling back to ContextVar which
                        # is only set for Gateway REST API requests.
                        tenant_id = ctx.get("tenant_id", tenant_id)

                from deerflow.cost.storage import UsageRecord

                record = UsageRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    tenant_id=tenant_id,
                    thread_id=thread_id,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost,
                )

                self._ensure_flush_task()
                self._buffer.append(record)
                if len(self._buffer) >= self._BUFFER_FLUSH_SIZE:
                    if self._flush_task is not None:
                        self._flush_task.cancel()
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._flush_buffer())
                    except RuntimeError:
                        pass
            except Exception:
                logger.exception("Failed to buffer token usage record")

        return None
