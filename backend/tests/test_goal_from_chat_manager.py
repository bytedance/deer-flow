"""IM manager handling of ``/goal from-chat`` (the #7050 first slice).

The manager branch differs from the existing ``set`` branch in one deliberate
way: ``set`` starts the run silently because the user typed the objective
themselves, but ``from-chat`` synthesizes it, so the user must be shown what
was saved. On success the manager publishes a ``from_chat_saved`` confirmation
carrying the objective, then replaces the message text with that objective and
hands it to ``_handle_chat`` so exactly one run starts through the ordinary
path, and returns ``None`` (the run's own streaming output follows).

The pins here: the confirmation-then-single-run success path, the reply
mapping for each Gateway outcome, the no-thread short circuit, that a
saved-but-not-started run is reported honestly rather than silently, and that
a failed confirmation card does not strand the saved objective.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus
from app.channels.store import JsonChannelStore


def _run(coro):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _msg(text: str) -> InboundMessage:
    return InboundMessage(
        channel_name="feishu",
        chat_id="C1",
        user_id="U1",
        text=text,
        msg_type=InboundMessageType.COMMAND,
    )


def _make_manager(monkeypatch, *, thread_id: str | None = "t-1", respond=None) -> tuple[ChannelManager, list[httpx.Request]]:
    """A manager whose goal HTTP calls hit ``respond`` (an httpx.MockTransport handler)."""
    bus = MessageBus()
    store = JsonChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
    manager = ChannelManager(bus=bus, store=store, gateway_url="http://gateway:8001")

    async def _lookup(msg):
        return thread_id

    monkeypatch.setattr(manager, "_lookup_thread_id", _lookup)

    calls: list[httpx.Request] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return respond(request) if respond else httpx.Response(200, json={"goal": {"objective": "x", "status": "active"}})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.channels.manager.httpx.AsyncClient",
        lambda *a, **kw: real_async_client(*a, transport=httpx.MockTransport(_respond), **kw),
    )
    return manager, calls


def _captured_replies(manager: ChannelManager) -> list:
    replies = []
    manager.bus.subscribe_outbound(AsyncMock(side_effect=replies.append))
    return replies


def test_from_chat_success_confirms_objective_then_starts_one_run(monkeypatch):
    objective = "Reconcile vendors A and B, excluding C, until every discrepancy is explained."
    manager, calls = _make_manager(monkeypatch, respond=lambda r: httpx.Response(200, json={"goal": {"objective": objective, "status": "active"}}))
    replies = _captured_replies(manager)
    chat = AsyncMock()
    monkeypatch.setattr(manager, "_handle_chat", chat)

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    # reply is None: the run's own streaming output follows, like the set branch.
    assert result is None
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/api/threads/t-1/goal/from-chat"
    # The synthesized objective is shown to the user before the run starts.
    assert len(replies) == 1
    assert objective in replies[0].text
    chat.assert_awaited_once()
    started = chat.await_args.args[0]
    assert started.text == objective
    assert started.msg_type == InboundMessageType.CHAT
    assert chat.await_args.kwargs == {"bound_identity_checked": True}


def test_from_chat_confirmation_card_failure_still_starts_the_run(monkeypatch):
    """The goal is already saved; a failed confirmation card must not strand it."""
    objective = "Ship the reconciliation."
    manager, _ = _make_manager(monkeypatch, respond=lambda r: httpx.Response(200, json={"goal": {"objective": objective, "status": "active"}}))
    chat = AsyncMock()
    monkeypatch.setattr(manager, "_handle_chat", chat)
    publish = AsyncMock(side_effect=RuntimeError("feishu send failed"))
    monkeypatch.setattr(manager, "_publish_progress_update", publish)

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    # The card failed, but the run still starts with the saved objective.
    assert result is None
    publish.assert_awaited_once()
    chat.assert_awaited_once()
    assert chat.await_args.args[0].text == objective


def test_from_chat_guidance_is_forwarded(monkeypatch):
    manager, calls = _make_manager(monkeypatch, respond=lambda r: httpx.Response(200, json={"goal": {"objective": "Ship it.", "status": "active"}}))
    _captured_replies(manager)
    monkeypatch.setattr(manager, "_handle_chat", AsyncMock())

    _run(manager._handle_goal_command(_msg("/goal from-chat focus on the vendor total"), "from-chat focus on the vendor total"))

    assert calls[0].url.path == "/api/threads/t-1/goal/from-chat"
    assert json.loads(calls[0].content) == {"guidance": "focus on the vendor total"}


def test_from_chat_waits_past_the_checkpoint_timeout_for_synthesis(monkeypatch):
    # The Gateway answers this route only after an LLM synthesis call; the
    # shared 10s budget used by the other /goal calls fired mid-save in the
    # live Feishu run, so the manager reported failure for a goal that was
    # saved seconds later.
    manager, calls = _make_manager(monkeypatch, respond=lambda r: httpx.Response(200, json={"goal": {"objective": "Ship it.", "status": "active"}}))
    _captured_replies(manager)
    monkeypatch.setattr(manager, "_handle_chat", AsyncMock())

    _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    timeout = calls[0].extensions["timeout"]
    assert timeout["read"] >= 60
    # A dead Gateway must still fail the connection quickly.
    assert timeout["connect"] <= 10


def test_other_goal_requests_keep_the_short_timeout(monkeypatch):
    manager, calls = _make_manager(monkeypatch)

    _run(manager._goal_request("get", "t-1", headers={}))

    assert calls[0].extensions["timeout"]["read"] == 10


def test_from_chat_timeout_reply_says_the_save_may_still_finish(monkeypatch):
    def _timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    manager, _ = _make_manager(monkeypatch, respond=_timeout)
    _captured_replies(manager)
    chat = AsyncMock()
    monkeypatch.setattr(manager, "_handle_chat", chat)

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    # The Gateway may save the goal after the manager stops waiting: the reply
    # must not claim a plain failure, and no second run may start.
    assert "may still finish" in result
    assert "check with /goal" in result
    chat.assert_not_awaited()


def test_from_chat_no_thread_short_circuits_without_http(monkeypatch):
    manager, calls = _make_manager(monkeypatch, thread_id=None)
    _captured_replies(manager)
    chat = AsyncMock()
    monkeypatch.setattr(manager, "_handle_chat", chat)

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    assert result == "No conversation yet. Send a message first, then ask /goal from-chat."
    assert calls == []
    chat.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        pytest.param(409, {"detail": "Thread has a run in flight. Set the goal after the run finishes."}, "A task is still running. Wait for it to finish before changing the goal.", id="busy"),
        pytest.param(422, {"detail": {"code": "unclear"}}, "I couldn't form a clear goal from this conversation. Try adding a hint, e.g. /goal from-chat focus on the vendor totals.", id="unclear"),
        pytest.param(422, {"detail": {"code": "no_context"}}, "There is no conversation content to build a goal from yet. Discuss the task first, or set it directly with /goal <objective>.", id="no-context"),
        pytest.param(422, {"detail": {"code": "pending_clarification"}}, "The assistant is still waiting for your answer in this conversation. Reply to it first, then retry /goal from-chat.", id="pending-clarification"),
        pytest.param(502, {"detail": {"code": "synthesis_failed"}}, "Failed to compose the goal from the conversation. Try again, or set it directly with /goal <objective>.", id="synthesis-failed"),
        pytest.param(500, {"detail": "Failed to set thread goal"}, "Failed to compose the goal from the conversation. Try again, or set it directly with /goal <objective>.", id="server-error"),
    ],
)
def test_from_chat_error_paths_reply_and_never_start_a_run(monkeypatch, status, payload, expected):
    manager, calls = _make_manager(monkeypatch, respond=lambda r: httpx.Response(status, json=payload))
    replies = _captured_replies(manager)
    chat = AsyncMock()
    monkeypatch.setattr(manager, "_handle_chat", chat)

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    assert result == expected
    chat.assert_not_awaited()
    assert replies == []  # an error reply is returned, not published as a confirmation


def test_from_chat_unclear_never_echoes_a_leaked_reason(monkeypatch):
    # Even if the Gateway (wrongly) put a reason in the body, the manager's
    # fixed reply must not carry model-generated text back to the user.
    manager, _ = _make_manager(monkeypatch, respond=lambda r: httpx.Response(422, json={"detail": {"code": "unclear", "reason": "sk-secret provider note"}}))
    _captured_replies(manager)
    monkeypatch.setattr(manager, "_handle_chat", AsyncMock())

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    assert "sk-secret" not in result and "provider note" not in result


def test_from_chat_saved_but_run_not_started_is_reported(monkeypatch):
    manager, _ = _make_manager(monkeypatch, respond=lambda r: httpx.Response(200, json={"goal": {"objective": "Ship it.", "status": "active"}}))
    replies = _captured_replies(manager)
    monkeypatch.setattr(manager, "_handle_chat", AsyncMock(side_effect=RuntimeError("admission rejected")))

    result = _run(manager._handle_goal_command(_msg("/goal from-chat"), "from-chat"))

    # The confirmation was already published; the returned reply must say the
    # run did not start rather than claim a fresh failure or stay silent.
    assert len(replies) == 1 and "Ship it." in replies[0].text
    assert result is not None and "did not start" in result


def test_from_chat_zh_locale_confirmation_is_chinese(monkeypatch):
    objective = "核对供应商 A 和 B，排除 C，直到每条差异都有解释。"
    manager, _ = _make_manager(monkeypatch, respond=lambda r: httpx.Response(200, json={"goal": {"objective": objective, "status": "active"}}))
    replies = _captured_replies(manager)
    monkeypatch.setattr(manager, "_reply_locale", SimpleNamespace(locale_for=AsyncMock(return_value="zh-CN")))
    monkeypatch.setattr(manager, "_handle_chat", AsyncMock())

    _run(manager._handle_goal_command(replace(_msg("/goal from-chat"), owner_user_id="owner-zh"), "from-chat"))

    assert len(replies) == 1
    assert replies[0].text.startswith("已从对话设置目标：")
    assert objective in replies[0].text
