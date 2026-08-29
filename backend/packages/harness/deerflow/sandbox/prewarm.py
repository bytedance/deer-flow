"""Opportunistic AIO sandbox startup for likely tool-using turns."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage

from deerflow.config import get_app_config
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.sandbox_provider import SandboxProvider, get_sandbox_provider

logger = logging.getLogger(__name__)

_CONTEXT_KEY = "__deerflow_sandbox_prewarm"
_CODE_FENCE_RE = re.compile(r"```")
_PATH_RE = re.compile(r"(?<!\w)(?:~/(?:[\w.-]+/)*[\w.-]+|/(?:[\w.-]+)(?:/[\w.-]+)*|[A-Za-z]:\\)")
_COMMAND_RE = re.compile(r"^\s*(?:\$\s+|(?:python(?:3)?|pip|git|npm|pnpm|uv|pytest|make|docker|kubectl)\b)", re.MULTILINE)
_TRACEBACK_RE = re.compile(r"(?:Traceback \(most recent call last\)|^\s*File [\"'].+[\"'], line \d+|\b(?:Error|Exception):)", re.MULTILINE)


def _message_text(message: HumanMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(block.get("text", "") for block in content if isinstance(block, dict) and isinstance(block.get("text"), str))


def should_prewarm_sandbox(state: dict[str, Any]) -> bool:
    """Return whether the current user turn has a strong sandbox-use signal."""
    messages = state.get("messages")
    if not isinstance(messages, list):
        return False
    message = next((item for item in reversed(messages) if isinstance(item, HumanMessage)), None)
    if message is None:
        return False
    text = _message_text(message)
    return bool(_CODE_FENCE_RE.search(text) or _PATH_RE.search(text) or _COMMAND_RE.search(text) or _TRACEBACK_RE.search(text))


def _is_aio_prewarm_enabled() -> bool:
    sandbox = get_app_config().sandbox
    return bool(getattr(sandbox, "prewarm", False) and sandbox.use.endswith(":AioSandboxProvider"))


@dataclass
class SandboxPrewarm:
    task: asyncio.Task[str]
    provider: SandboxProvider
    claimed: bool = False
    closed: bool = False

    async def claim(self) -> str | None:
        if self.closed:
            return None
        self.claimed = True
        try:
            return await asyncio.shield(self.task)
        except Exception:
            # Prewarming is only a latency optimization. The normal acquire path
            # remains authoritative when an opportunistic startup fails.
            logger.info("Sandbox prewarm failed; falling back to normal acquisition", exc_info=True)
            return None

    def close(self) -> None:
        self.closed = True
        if self.claimed:
            return
        if self.task.done():
            self._release_unused()
        else:
            self.task.add_done_callback(lambda _: self._release_unused())

    def _release_unused(self) -> None:
        if self.claimed or not self.task.done() or self.task.cancelled():
            return
        try:
            sandbox_id = self.task.result()
        except Exception:
            return

        async def release() -> None:
            try:
                await asyncio.to_thread(self.provider.release, sandbox_id)
            except Exception:
                logger.warning("Could not release unused prewarmed sandbox %s", sandbox_id, exc_info=True)

        asyncio.create_task(release())


def start_sandbox_prewarm(state: dict[str, Any], runtime: Any) -> None:
    """Start one non-blocking AIO acquire for this run when configured."""
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict) or _CONTEXT_KEY in context:
        return
    if not should_prewarm_sandbox(state) or not _is_aio_prewarm_enabled():
        return
    thread_id = context.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        return
    provider = get_sandbox_provider()
    task = asyncio.create_task(provider.acquire_async(thread_id, user_id=resolve_runtime_user_id(runtime)))
    context[_CONTEXT_KEY] = SandboxPrewarm(task=task, provider=provider)


async def claim_sandbox_prewarm(runtime: Any) -> str | None:
    context = getattr(runtime, "context", None)
    prewarm = context.get(_CONTEXT_KEY) if isinstance(context, dict) else None
    return await prewarm.claim() if isinstance(prewarm, SandboxPrewarm) else None


def close_sandbox_prewarm(runtime: Any) -> None:
    context = getattr(runtime, "context", None)
    prewarm = context.pop(_CONTEXT_KEY, None) if isinstance(context, dict) else None
    if isinstance(prewarm, SandboxPrewarm):
        prewarm.close()
