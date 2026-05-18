"""Tests for :class:`AuditMiddleware` lifecycle and tool-call hooks (plan M2-5).

The middleware is exercised in isolation against an in-memory
``AuditStorage`` fake. The contract we care about is:

* every lifecycle hook produces exactly one event,
* mapped tool calls are appended after the handler returns,
* whitelisted tool calls produce zero events,
* exceptions from the handler are recorded as ``AGENT_TASK_ERROR`` and
  then re-raised so upstream error middleware still sees them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.middleware import AuditMiddleware
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import AuditQueryFilter, AuditStorage
from deerflow.enterprise.config import AuditConfig


class _InMemoryStorage(AuditStorage):
    """Tiny ``AuditStorage`` for tests; collects events in a list."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def query(self, filters: AuditQueryFilter) -> list[AuditEvent]:  # pragma: no cover
        return list(self.events)

    async def count(self, filters: AuditQueryFilter) -> int:  # pragma: no cover
        return len(self.events)

    async def verify_integrity(self, signer, filters=None) -> bool:  # pragma: no cover
        return all(signer.verify(e) for e in self.events)


def _make_middleware(*, with_signer: bool = True) -> tuple[AuditMiddleware, _InMemoryStorage]:
    storage = _InMemoryStorage()
    signer = AuditSigner("k") if with_signer else None
    cfg = AuditConfig(enabled=True, sign_key="k" if with_signer else None)
    return AuditMiddleware(cfg, storage, signer), storage


def _make_runtime(thread_id: str = "t1", user_id: str = "alice") -> Any:
    return SimpleNamespace(context={"thread_id": thread_id, "user_id": user_id}, config={})


def _tool_call_request(name: str = "bash", args: dict | None = None) -> Any:
    return SimpleNamespace(
        tool_call={"name": name, "id": "call-1", "args": args or {}},
        runtime=_make_runtime(),
    )


@pytest.mark.asyncio
async def test_abefore_agent_emits_started_event():
    mw, storage = _make_middleware()
    await mw.abefore_agent(state={}, runtime=_make_runtime())
    assert [e.event_type for e in storage.events] == [AuditEventType.AGENT_TASK_STARTED]
    assert storage.events[0].user_id == "alice"
    assert storage.events[0].resource == "thread:t1"


@pytest.mark.asyncio
async def test_aafter_agent_emits_completed_event():
    mw, storage = _make_middleware()
    await mw.aafter_agent(state={}, runtime=_make_runtime())
    assert [e.event_type for e in storage.events] == [AuditEventType.AGENT_TASK_COMPLETED]


@pytest.mark.asyncio
async def test_awrap_tool_call_audits_bash_as_sandbox_command():
    mw, storage = _make_middleware()

    async def handler(req):
        return ToolMessage(content="ok", tool_call_id="call-1", name="bash")

    result = await mw.awrap_tool_call(_tool_call_request("bash"), handler)
    assert isinstance(result, ToolMessage)
    assert len(storage.events) == 1
    assert storage.events[0].event_type == AuditEventType.SANDBOX_COMMAND_EXECUTED
    assert storage.events[0].action == "bash"


@pytest.mark.asyncio
async def test_awrap_tool_call_skips_whitelisted_tools():
    """Whitelisted read-only tools must not write any audit row."""
    mw, storage = _make_middleware()

    async def handler(req):
        return ToolMessage(content="ok", tool_call_id="call-1", name="ls")

    await mw.awrap_tool_call(_tool_call_request("ls"), handler)
    assert storage.events == []


@pytest.mark.asyncio
async def test_awrap_tool_call_records_mcp_server():
    mw, storage = _make_middleware()

    async def handler(req):
        return ToolMessage(content="ok", tool_call_id="call-1", name="mcp:figma:get_file")

    await mw.awrap_tool_call(_tool_call_request("mcp:figma:get_file"), handler)
    assert len(storage.events) == 1
    assert storage.events[0].event_type == AuditEventType.TOOL_INVOKED
    assert storage.events[0].details.get("mcp_server") == "figma"


@pytest.mark.asyncio
async def test_awrap_tool_call_emits_error_and_reraises():
    """Handler exceptions produce AGENT_TASK_ERROR and propagate."""
    mw, storage = _make_middleware()

    async def handler(req):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await mw.awrap_tool_call(_tool_call_request("bash"), handler)

    assert len(storage.events) == 1
    assert storage.events[0].event_type == AuditEventType.AGENT_TASK_ERROR
    assert storage.events[0].details.get("error_class") == "RuntimeError"


@pytest.mark.asyncio
async def test_events_are_signed_when_signer_configured():
    """Each emitted event carries a non-empty HMAC signature."""
    mw, storage = _make_middleware(with_signer=True)
    await mw.abefore_agent(state={}, runtime=_make_runtime())
    assert storage.events[0].signature is not None
    assert len(storage.events[0].signature) == 64


@pytest.mark.asyncio
async def test_events_unsigned_when_no_signer():
    """Without a signer events are appended unsigned (warning already emitted at config validation)."""
    mw, storage = _make_middleware(with_signer=False)
    await mw.abefore_agent(state={}, runtime=_make_runtime())
    assert storage.events[0].signature is None


@pytest.mark.asyncio
async def test_storage_failure_does_not_kill_agent_loop(caplog):
    """A storage exception is logged but swallowed — the run keeps going."""

    class _BrokenStorage(_InMemoryStorage):
        async def append(self, event: AuditEvent) -> None:
            raise OSError("disk full")

    cfg = AuditConfig(enabled=True, sign_key="k")
    mw = AuditMiddleware(cfg, _BrokenStorage(), AuditSigner("k"))
    # Must NOT raise — only log.
    await mw.abefore_agent(state={}, runtime=_make_runtime())
    assert any("audit append failed" in r.message for r in caplog.records)
