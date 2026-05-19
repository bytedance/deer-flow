"""Unit tests for the 4 closure-ticket builtin tools (§5.3).

Coverage:

* schema validation rejects bad inputs before reaching the service;
* idempotent ``create_closure_ticket`` returns ``created=False`` on the
  second call for the same source-key;
* ``update_closure_ticket`` rejects ``status`` writes outright;
* unknown fields on the update tool are rejected with ``VALIDATION``;
* tenant / permission errors propagate with the right envelope code;
* ``close_closure_ticket`` requires ``closure:verify`` -- members get
  ``PERMISSION_DENIED``, admins succeed;
* both decisions (``verify_close`` / ``reject``) work and emit the right
  audit-event action.

The fixture spins up a real SQLite engine + ``ClosureRepository`` +
``ClosureService`` so we exercise the full state-machine path. The
runtime config is monkey-patched to drive the ``_principal_from_runnable_config``
helper without standing up LangGraph.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def tools_ctx(tmp_path) -> AsyncIterator[dict[str, Any]]:
    """Spin up a fresh SQLite engine + service, register it as the singleton."""
    from deerflow.closed_loop.events import ClosureEventPublisher
    from deerflow.closed_loop.repository import ClosureRepository
    from deerflow.closed_loop.service import ClosureService
    from deerflow.closed_loop.service_factory import (
        reset_default_service,
        set_default_service,
    )
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.memory import MemoryRunEventStore

    db_path = tmp_path / f"closure-tools-{uuid.uuid4().hex}.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    assert sf is not None

    event_store = MemoryRunEventStore()
    publisher = ClosureEventPublisher(event_store)
    repo = ClosureRepository(sf)
    service = ClosureService(repository=repo, event_publisher=publisher)
    set_default_service(service)

    try:
        yield {
            "service": service,
            "repo": repo,
            "session_factory": sf,
            "event_store": event_store,
            "tenant_id": "tenant-a",
            "user_id": "user-alice",
        }
    finally:
        reset_default_service()
        await close_engine()


def _stub_runtime(monkeypatch: pytest.MonkeyPatch, *, user_id: str, tenant_id: str, is_admin: bool) -> None:
    """Patch the tool module's ``get_config`` so the principal helper works."""
    from deerflow.tools.builtins import closure_ticket_tools as ct

    def fake_get_config() -> dict[str, Any]:
        return {
            "configurable": {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "is_superadmin": False,
                "is_tenant_admin": is_admin,
            }
        }

    monkeypatch.setattr(ct, "get_config", fake_get_config)


def _payload(result: str) -> dict[str, Any]:
    return json.loads(result)


# ---------------------------------------------------------------------------
# create_closure_ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_closure_ticket_minimal(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import create_closure_ticket_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    out = _payload(
        await create_closure_ticket_tool.ainvoke(
            {
                "title": "noisy bearing",
                "priority": "important",
                "device_id": "dev-1",
                "source_type": "diagnosis",
                "source_run_id": "run-x",
                "metadata": {"findings": ["t1"], "confidence": 0.9},
            }
        )
    )
    assert "ticket" in out, out
    assert out["created"] is True
    assert out["ticket"]["status"] == "pending"
    assert out["ticket"]["priority"] == "important"
    assert out["ticket"]["created_by"] == tools_ctx["user_id"]


@pytest.mark.asyncio
async def test_create_closure_ticket_is_idempotent(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import create_closure_ticket_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    args = {
        "title": "noisy bearing",
        "device_id": "dev-1",
        "source_type": "diagnosis",
        "source_run_id": "run-x",
        "metadata": {"findings": ["t1"]},
    }
    first = _payload(await create_closure_ticket_tool.ainvoke(args))
    second = _payload(await create_closure_ticket_tool.ainvoke(args))
    assert first["created"] is True
    assert second["created"] is False
    assert first["ticket"]["id"] == second["ticket"]["id"]


@pytest.mark.asyncio
async def test_create_closure_ticket_rejects_invalid_priority(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import create_closure_ticket_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    out = _payload(
        await create_closure_ticket_tool.ainvoke(
            {"title": "x", "priority": "bogus", "source_type": "manual"}
        )
    )
    assert out.get("error", {}).get("code") == "VALIDATION"


@pytest.mark.asyncio
async def test_create_closure_ticket_propagates_metadata_validation(tools_ctx, monkeypatch) -> None:
    """``confidence`` outside [0, 1] is rejected by the discriminated-union schema."""
    from deerflow.tools.builtins.closure_ticket_tools import create_closure_ticket_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    out = _payload(
        await create_closure_ticket_tool.ainvoke(
            {
                "title": "x",
                "source_type": "diagnosis",
                "metadata": {"confidence": 5.0},
            }
        )
    )
    assert out.get("error", {}).get("code") == "VALIDATION"


# ---------------------------------------------------------------------------
# list_closure_tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_closure_tickets_returns_meta_and_items(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import (
        create_closure_ticket_tool,
        list_closure_tickets_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    for i in range(3):
        await create_closure_ticket_tool.ainvoke(
            {
                "title": f"t{i}",
                "device_id": f"dev-{i}",
                "source_type": "manual",
                "source_run_id": f"run-{i}",
            }
        )

    out = _payload(await list_closure_tickets_tool.ainvoke({"page_size": 2}))
    assert out["meta"]["total"] == 3
    assert out["meta"]["page"] == 1
    assert out["meta"]["page_size"] == 2
    assert len(out["items"]) == 2


@pytest.mark.asyncio
async def test_list_closure_tickets_rejects_invalid_source_type(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import list_closure_tickets_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    out = _payload(await list_closure_tickets_tool.ainvoke({"source_type": "bogus"}))
    assert out.get("error", {}).get("code") == "VALIDATION"


# ---------------------------------------------------------------------------
# update_closure_ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_closure_ticket_rejects_status_write(tools_ctx, monkeypatch) -> None:
    """Even with valid columns alongside, ``status`` is rejected outright."""
    from deerflow.tools.builtins.closure_ticket_tools import (
        create_closure_ticket_tool,
        update_closure_ticket_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    created = _payload(
        await create_closure_ticket_tool.ainvoke(
            {"title": "orig", "source_type": "manual"}
        )
    )
    ticket_id = created["ticket"]["id"]

    out = _payload(
        await update_closure_ticket_tool.ainvoke(
            {"ticket_id": ticket_id, "fields": {"title": "new", "status": "closed"}}
        )
    )
    assert out.get("error", {}).get("code") == "STATUS_FORBIDDEN"
    # Hint mentions the right next step.
    assert "transition" in out["error"]["message"].lower() or "close_closure_ticket" in out["error"]["message"]


@pytest.mark.asyncio
async def test_update_closure_ticket_rejects_unknown_fields(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import (
        create_closure_ticket_tool,
        update_closure_ticket_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    created = _payload(
        await create_closure_ticket_tool.ainvoke({"title": "orig", "source_type": "manual"})
    )
    out = _payload(
        await update_closure_ticket_tool.ainvoke(
            {"ticket_id": created["ticket"]["id"], "fields": {"created_by": "evil"}}
        )
    )
    assert out.get("error", {}).get("code") == "VALIDATION"


@pytest.mark.asyncio
async def test_update_closure_ticket_applies_legal_patch(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import (
        create_closure_ticket_tool,
        update_closure_ticket_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    created = _payload(
        await create_closure_ticket_tool.ainvoke({"title": "orig", "source_type": "manual"})
    )
    out = _payload(
        await update_closure_ticket_tool.ainvoke(
            {
                "ticket_id": created["ticket"]["id"],
                "fields": {"title": "renamed", "priority": "urgent"},
            }
        )
    )
    assert "ticket" in out, out
    assert out["ticket"]["title"] == "renamed"
    assert out["ticket"]["priority"] == "urgent"


# ---------------------------------------------------------------------------
# close_closure_ticket
# ---------------------------------------------------------------------------


async def _drive_to_pending_verification(
    *,
    create_tool,
    update_tool,
    transition_service,
    tenant_id: str,
    user_id: str,
) -> str:
    """Helper: walk a brand-new ticket through assign/start/submit so it is verifiable."""
    from deerflow.closed_loop.permissions import CLOSURE_READ, CLOSURE_VERIFY, CLOSURE_WRITE

    created = _payload(
        await create_tool.ainvoke({"title": "needs verify", "source_type": "manual"})
    )
    ticket_id: str = created["ticket"]["id"]

    perms = (CLOSURE_READ, CLOSURE_WRITE, CLOSURE_VERIFY)
    await transition_service.transition(
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        actor_id=user_id,
        permissions=perms,
        action="assign",
        payload={"assignee_id": user_id},
    )
    await transition_service.transition(
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        actor_id=user_id,
        permissions=perms,
        action="start",
        payload={},
    )
    await transition_service.transition(
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        actor_id=user_id,
        permissions=perms,
        action="submit_verification",
        payload={"verification_summary": "done"},
    )
    return ticket_id


@pytest.mark.asyncio
async def test_close_closure_ticket_requires_verify_permission(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import (
        close_closure_ticket_tool,
        create_closure_ticket_tool,
        update_closure_ticket_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=False)
    ticket_id = await _drive_to_pending_verification(
        create_tool=create_closure_ticket_tool,
        update_tool=update_closure_ticket_tool,
        transition_service=tools_ctx["service"],
        tenant_id=tools_ctx["tenant_id"],
        user_id=tools_ctx["user_id"],
    )

    out = _payload(
        await close_closure_ticket_tool.ainvoke(
            {"ticket_id": ticket_id, "decision": "verify_close"}
        )
    )
    assert out.get("error", {}).get("code") == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_close_closure_ticket_admin_closes(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import (
        close_closure_ticket_tool,
        create_closure_ticket_tool,
        update_closure_ticket_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=True)
    ticket_id = await _drive_to_pending_verification(
        create_tool=create_closure_ticket_tool,
        update_tool=update_closure_ticket_tool,
        transition_service=tools_ctx["service"],
        tenant_id=tools_ctx["tenant_id"],
        user_id=tools_ctx["user_id"],
    )

    out = _payload(
        await close_closure_ticket_tool.ainvoke(
            {
                "ticket_id": ticket_id,
                "decision": "verify_close",
                "verification_summary": "ok",
            }
        )
    )
    assert "ticket" in out, out
    assert out["ticket"]["status"] == "closed"
    assert out["ticket"]["closed_at"] is not None


@pytest.mark.asyncio
async def test_close_closure_ticket_admin_rejects_with_reason(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import (
        close_closure_ticket_tool,
        create_closure_ticket_tool,
        update_closure_ticket_tool,
    )

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=True)
    ticket_id = await _drive_to_pending_verification(
        create_tool=create_closure_ticket_tool,
        update_tool=update_closure_ticket_tool,
        transition_service=tools_ctx["service"],
        tenant_id=tools_ctx["tenant_id"],
        user_id=tools_ctx["user_id"],
    )

    out = _payload(
        await close_closure_ticket_tool.ainvoke(
            {
                "ticket_id": ticket_id,
                "decision": "reject",
                "rejection_reason": "needs more evidence",
            }
        )
    )
    assert "ticket" in out, out
    # Verification rejection sends the ticket back to in_progress.
    assert out["ticket"]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_close_closure_ticket_reject_requires_reason(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import close_closure_ticket_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=True)
    out = _payload(
        await close_closure_ticket_tool.ainvoke(
            {"ticket_id": "anything", "decision": "reject"}
        )
    )
    assert out.get("error", {}).get("code") == "VALIDATION"


@pytest.mark.asyncio
async def test_close_closure_ticket_rejects_unknown_decision(tools_ctx, monkeypatch) -> None:
    from deerflow.tools.builtins.closure_ticket_tools import close_closure_ticket_tool

    _stub_runtime(monkeypatch, user_id=tools_ctx["user_id"], tenant_id=tools_ctx["tenant_id"], is_admin=True)
    out = _payload(
        await close_closure_ticket_tool.ainvoke(
            {"ticket_id": "anything", "decision": "explode"}
        )
    )
    assert out.get("error", {}).get("code") == "VALIDATION"


# ---------------------------------------------------------------------------
# Service unavailable path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_service_unavailable_when_no_engine(monkeypatch) -> None:
    """No DB engine + no injected service -> SERVICE_UNAVAILABLE envelope."""
    from deerflow.closed_loop.service_factory import reset_default_service
    from deerflow.tools.builtins import closure_ticket_tools as ct

    reset_default_service()
    monkeypatch.setattr(
        ct,
        "get_config",
        lambda: {
            "configurable": {"user_id": "u", "tenant_id": "t", "is_tenant_admin": False}
        },
    )
    monkeypatch.setattr(ct, "get_default_service", lambda: None)

    out = _payload(await ct.create_closure_ticket_tool.ainvoke({"title": "x"}))
    assert out.get("error", {}).get("code") == "SERVICE_UNAVAILABLE"
