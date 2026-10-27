"""Optional AIO startup owned by the same lease as its agent execution."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage

from deerflow.authz.sandbox_authz import authorize_sandbox_execution_async, safe_app_config_async
from deerflow.config import get_app_config
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.acquire_serialization import AcquireSerializerClosed
from deerflow.sandbox.exceptions import SandboxAuthorizationError
from deerflow.sandbox.lease import (
    SANDBOX_PREWARM_CONTEXT_KEY,
    SandboxLeaseManager,
    get_sandbox_lease_manager,
    run_sync_lifecycle_operation,
    sandbox_lease_owner,
    sandbox_prewarm_cleanup_registered,
)
from deerflow.sandbox.sandbox_provider import SandboxProvider, get_initialized_sandbox_provider, get_sandbox_provider
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"```")
_URL_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>]+")
_PATH_RE = re.compile(r"(?:^|[\s`\"'(])(?:~/(?:[\w.-]+/)*[\w.-]+|/(?:[\w.-]+)(?:/[\w.-]+)*|[A-Za-z]:\\)")
_COMMAND_RE = re.compile(
    r"^\s*(?:\$\s+\S|python(?:3)?\s+(?:-[cmV]\b|\S+\.py\b)|"
    r"(?:pip|pip3)\s+(?:install|list|show|freeze|check)\b|"
    r"git\s+(?:status|diff|log|show|clone|checkout|switch|fetch|pull|push|commit|add|branch)\b|"
    r"(?:npm|pnpm)\s+(?:run|install|test|build|exec|add)\b|"
    r"uv\s+(?:run|sync|pip|add|lock|venv)\b|"
    r"pytest(?:\s+(?:-|\S+[/\\.]|tests\b)|\s*$)|make\s+(?:test|check|build|install|dev)\b|"
    r"docker\s+(?:run|build|compose|ps|logs|exec|inspect)\b|kubectl\s+(?:get|describe|logs|exec|apply)\b)",
    re.MULTILINE,
)
_TRACEBACK_RE = re.compile(r"(?:Traceback \(most recent call last\)|^\s*File [\"'].+[\"'], line \d+)", re.MULTILINE)

# Identity keyed and bounded by live speculative handles. A lock, rather than an
# asyncio semaphore, also covers the isolated subagent loop. No provider IO runs
# under it. Real tool acquisitions never queue behind this optional budget.
_permit_lock = threading.Lock()
_permits: dict[int, tuple[SandboxProvider, int]] = {}


def _take_permit(provider: SandboxProvider, limit: int) -> bool:
    with _permit_lock:
        entry = _permits.get(id(provider))
        count = entry[1] if entry is not None and entry[0] is provider else 0
        if count >= limit:
            return False
        _permits[id(provider)] = provider, count + 1
        return True


def _message_text(message: HumanMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(block["text"] for block in content if isinstance(block, dict) and isinstance(block.get("text"), str))


def should_prewarm_sandbox(state: dict[str, Any]) -> bool:
    """Predict only explicit code/command/path signals in the latest user turn."""
    messages = state.get("messages")
    if not isinstance(messages, list):
        return False
    message = next((item for item in reversed(messages) if isinstance(item, HumanMessage)), None)
    if message is None:
        return False
    text = _URL_RE.sub("", _message_text(message))
    return bool(_CODE_FENCE_RE.search(text) or _PATH_RE.search(text) or _COMMAND_RE.search(text) or _TRACEBACK_RE.search(text))


@dataclass
class SandboxPrewarm:
    owner_id: str
    thread_id: str
    user_id: str
    context: dict[str, Any]
    task: asyncio.Task[str | None] = field(init=False)
    provider: SandboxProvider | None = None
    manager: SandboxLeaseManager | None = None
    claimed: bool = False
    closed: bool = False
    _permit: bool = False
    _cleanup_task: asyncio.Task[None] | None = None

    def _return_permit(self) -> None:
        if self.provider is None:
            return
        with _permit_lock:
            if not self._permit:
                return
            self._permit = False
            entry = _permits.get(id(self.provider))
            if entry is not None and entry[0] is self.provider:
                if entry[1] == 1:
                    del _permits[id(self.provider)]
                else:
                    _permits[id(self.provider)] = self.provider, entry[1] - 1

    async def acquire(self) -> str | None:
        ready = False
        try:
            config = self.context.get("app_config")
            if config is None:
                config = await asyncio.to_thread(get_app_config)
            sandbox = config.sandbox
            if not getattr(sandbox, "prewarm", False) or not sandbox.use.endswith(":AioSandboxProvider"):
                return None
            # Startup policy is run-scoped, but authorization must be fresh;
            # claiming later does not replace the ordinary tool's fresh gate.
            await authorize_sandbox_execution_async(context=self.context, app_config=await safe_app_config_async())
            self.provider = get_initialized_sandbox_provider()
            if self.provider is None:
                # Only AIO opts in here; its constructor performs filesystem and
                # backend setup, so keep that work off the model's event loop.
                self.provider = await run_sync_lifecycle_operation(get_sandbox_provider)
            self.manager = get_sandbox_lease_manager(self.provider)
            limit = getattr(sandbox, "prewarm_max_concurrent", 1)
            if not _take_permit(self.provider, limit):
                logger.debug("Sandbox prewarm skipped: speculative budget occupied")
                return None
            self._permit = True
            sandbox_id = await self.manager.acquire_async(self.owner_id, self.thread_id, user_id=self.user_id)
            ready = True
            return sandbox_id
        except SandboxAuthorizationError:
            logger.debug("Sandbox prewarm skipped: sandbox execution denied")
            return None
        except Exception:
            logger.info("Sandbox prewarm unavailable; normal tool acquisition remains authoritative", exc_info=True)
            return None
        finally:
            if not ready:
                self._return_permit()

    async def claim(self, provider: SandboxProvider) -> str | None:
        if self.closed:
            return None
        sandbox_id = await asyncio.shield(self.task)
        if self.closed or sandbox_id is None:
            return None
        if self.provider is not provider:
            await self.close()
            return None
        self.claimed = True
        self._return_permit()
        return sandbox_id

    async def _cleanup(self) -> None:
        try:
            if not self.task.done():
                self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass  # The manager reconciles any provider result before this.
            finally:
                if self.manager is not None:
                    try:
                        await self.manager.release_async(self.owner_id)
                    except AcquireSerializerClosed:
                        if get_initialized_sandbox_provider() is self.provider:
                            raise
                        # Provider reset/shutdown already detached its manager.
                        # That lifecycle owns its remaining clients; raw release
                        # here could close a sibling still using the old provider.
                        logger.debug("Prewarm provider detached; its lifecycle owns final cleanup")
        finally:
            self._return_permit()
            # A closed marker prevents repeated speculation in goal continuations
            # without retaining the authorization/config snapshot indefinitely.
            self.context.clear()

    async def close(self) -> None:
        self.closed = True
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup(), name=f"sandbox-prewarm-cleanup:{self.owner_id}")
        # after_agent and the execution finally may both arrive here. Keep the
        # same task reachable through repeated cancellation and reentrant cleanup.
        await await_drained(self._wait_for_cleanup())

    async def _wait_for_cleanup(self) -> None:
        assert self._cleanup_task is not None
        await asyncio.shield(self._cleanup_task)


def start_sandbox_prewarm(state: dict[str, Any], runtime: Any) -> None:
    """Start at most one optional acquisition within an admitted async run."""
    context = getattr(runtime, "context", None)
    if not sandbox_prewarm_cleanup_registered(context) or SANDBOX_PREWARM_CONTEXT_KEY in context or state.get("sandbox") is not None:
        return
    owner_id = sandbox_lease_owner(context)
    thread_id = context.get("thread_id")
    if owner_id is None or not isinstance(thread_id, str) or not thread_id or not should_prewarm_sandbox(state):
        return
    snapshot = dict(context)
    handle = SandboxPrewarm(owner_id, thread_id, resolve_runtime_user_id(runtime), snapshot)
    handle.task = asyncio.create_task(handle.acquire(), name=f"sandbox-prewarm:{owner_id}")
    context[SANDBOX_PREWARM_CONTEXT_KEY] = handle


async def claim_sandbox_prewarm(runtime: Any, *, provider: SandboxProvider) -> str | None:
    context = getattr(runtime, "context", None)
    handle = context.get(SANDBOX_PREWARM_CONTEXT_KEY) if isinstance(context, dict) else None
    if not isinstance(handle, SandboxPrewarm):
        return None
    if handle.owner_id != sandbox_lease_owner(context) or handle.thread_id != context.get("thread_id") or handle.user_id != resolve_runtime_user_id(runtime):
        return None
    return await handle.claim(provider)


async def close_sandbox_prewarm_context(context: Any) -> None:
    handle = context.get(SANDBOX_PREWARM_CONTEXT_KEY) if isinstance(context, dict) else None
    if isinstance(handle, SandboxPrewarm):
        await handle.close()


async def close_sandbox_prewarm(runtime: Any) -> None:
    await close_sandbox_prewarm_context(getattr(runtime, "context", None))
