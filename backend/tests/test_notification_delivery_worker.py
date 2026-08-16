"""Tests for the notification delivery worker (issue #4254).

The worker consumes the notification outbox written by the scheduled-task
completion hook and pushes each delivery through the owning channel's
proactive send path. It must never touch execution state.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.channels.message_bus import MessageBus
from app.channels.wecom import WeComChannel
from app.scheduler.notification_delivery import NotificationDeliveryWorker, render_notification_text


class FakeDeliveryRepo:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.claims = []
        self.sent = []
        self.failed = []

    async def claim_due_deliveries(self, *, now, limit):
        claimed, self.rows = self.rows[:limit], self.rows[limit:]
        self.claims.append((now, limit))
        return claimed

    async def mark_sent(self, delivery_id):
        self.sent.append(delivery_id)

    async def mark_failed(self, delivery_id, *, error=None):
        self.failed.append((delivery_id, error))


class FakeChannel:
    def __init__(self, *, fail=False):
        self.sent = []
        self.fail = fail

    async def send_notification(self, *, target, text_markdown):
        if self.fail:
            raise RuntimeError("platform rejected the push")
        self.sent.append((target, text_markdown))


def _delivery_row(
    *,
    delivery_id="delivery-1",
    event="run_completed",
    provider="wecom",
    target="GaoZhiChao",
    payload=None,
):
    return {
        "id": delivery_id,
        "task_id": "task-1",
        "task_run_id": "task-run-1",
        "run_id": "run-1",
        "event": event,
        "provider": provider,
        "target": target,
        "owner_user_id": "user-1",
        "status": "sending",
        "payload": payload if payload is not None else {"run_status": "success", "error": None, "task_id": "task-1"},
    }


def _make_worker(repo, channel=None, resolve_run_summary=None):
    channels = {}
    if channel is not None:
        channels["wecom"] = channel
    return NotificationDeliveryWorker(
        delivery_repo=repo,
        resolve_channel=lambda provider: channels.get(provider),
        poll_interval_seconds=5,
        resolve_run_summary=resolve_run_summary,
    )


def test_render_run_completed_text_includes_task_and_run():
    text = render_notification_text(_delivery_row())

    assert "completed" in text.lower()
    assert "task-1" in text
    assert "run-1" in text


def test_render_run_failed_text_includes_error():
    text = render_notification_text(
        _delivery_row(
            event="run_failed",
            payload={"run_status": "failed", "error": "boom", "task_id": "task-1"},
        )
    )

    assert "failed" in text.lower()
    assert "boom" in text


def test_render_truncates_unbounded_error_text():
    text = render_notification_text(
        _delivery_row(
            event="run_failed",
            payload={"run_status": "failed", "error": "x" * 5000, "task_id": "task-1"},
        )
    )

    # The payload snapshot must stay bounded on the wire too.
    assert len(text) < 1000


@pytest.mark.asyncio
async def test_run_once_delivers_claimed_row_and_marks_sent():
    repo = FakeDeliveryRepo([_delivery_row()])
    channel = FakeChannel()
    worker = _make_worker(repo, channel)

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == ["delivery-1"]
    assert repo.failed == []
    assert len(channel.sent) == 1
    target, text = channel.sent[0]
    assert target == "GaoZhiChao"
    assert "task-1" in text


@pytest.mark.asyncio
async def test_run_once_marks_failed_when_channel_is_not_running():
    repo = FakeDeliveryRepo([_delivery_row()])
    worker = _make_worker(repo, channel=None)

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    assert len(repo.failed) == 1
    delivery_id, error = repo.failed[0]
    assert delivery_id == "delivery-1"
    assert "wecom" in error


@pytest.mark.asyncio
async def test_run_once_marks_failed_when_send_raises():
    repo = FakeDeliveryRepo([_delivery_row()])
    worker = _make_worker(repo, FakeChannel(fail=True))

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    delivery_id, error = repo.failed[0]
    assert delivery_id == "delivery-1"
    assert "platform rejected" in error


@pytest.mark.asyncio
async def test_run_once_without_due_rows_is_noop():
    repo = FakeDeliveryRepo([])
    worker = _make_worker(repo, FakeChannel())

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    assert repo.failed == []


@pytest.mark.asyncio
async def test_start_stop_lifecycle():
    repo = FakeDeliveryRepo([])
    worker = _make_worker(repo, FakeChannel())

    await worker.start()
    await worker.stop()
    # Idempotent stop mirrors the scheduler service contract.
    await worker.stop()


# ---------------------------------------------------------------------------
# Result summary enrichment (issue #4254): completed runs carry the agent's
# final answer into the IM push; failed runs keep the error-only skeleton.
# ---------------------------------------------------------------------------


def test_render_includes_result_summary_for_completed_runs():
    text = render_notification_text(_delivery_row(payload={"run_status": "success", "error": None, "task_id": "task-1", "result_summary": "The answer is 42"}))

    assert "The answer is 42" in text


def test_render_truncates_long_result_summary():
    text = render_notification_text(_delivery_row(payload={"run_status": "success", "error": None, "task_id": "task-1", "result_summary": "x" * 5000}))

    # Bounded on the wire: 999 chars of summary + the ellipsis marker.
    result_line = next(line for line in text.splitlines() if line.startswith("Result: "))
    assert len(result_line) == len("Result: ") + 1000
    assert result_line.endswith("\u2026")


def test_render_ignores_result_summary_for_failed_runs():
    text = render_notification_text(
        _delivery_row(
            event="run_failed",
            payload={"run_status": "failed", "error": "boom", "task_id": "task-1", "result_summary": "partial answer"},
        )
    )

    assert "partial answer" not in text


@pytest.mark.asyncio
async def test_delivery_enriches_completed_run_with_summary():
    row = _delivery_row()
    repo = FakeDeliveryRepo([row])
    channel = FakeChannel()
    seen = []

    def resolver(run_id, user_id):
        seen.append((run_id, user_id))
        return "The answer is 42"

    worker = _make_worker(repo, channel, resolve_run_summary=resolver)

    await worker.run_once(now=datetime.now(UTC))

    assert seen == [("run-1", "user-1")]
    assert repo.sent == ["delivery-1"]
    assert "The answer is 42" in channel.sent[0][1]
    # The claimed outbox row itself must not be mutated in place.
    assert "result_summary" not in row["payload"]


@pytest.mark.asyncio
async def test_delivery_supports_async_summary_resolver():
    repo = FakeDeliveryRepo([_delivery_row()])
    channel = FakeChannel()

    async def resolver(run_id, user_id):
        return "async answer"

    worker = _make_worker(repo, channel, resolve_run_summary=resolver)

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == ["delivery-1"]
    assert "async answer" in channel.sent[0][1]


@pytest.mark.asyncio
async def test_delivery_skips_resolver_for_failed_runs():
    repo = FakeDeliveryRepo([_delivery_row(event="run_failed", payload={"run_status": "failed", "error": "boom", "task_id": "task-1"})])
    channel = FakeChannel()
    called = []

    def resolver(run_id, user_id):
        called.append(run_id)
        return "should not appear"

    worker = _make_worker(repo, channel, resolve_run_summary=resolver)

    await worker.run_once(now=datetime.now(UTC))

    assert called == []
    assert repo.sent == ["delivery-1"]


@pytest.mark.asyncio
async def test_delivery_falls_back_to_skeleton_when_resolver_raises():
    repo = FakeDeliveryRepo([_delivery_row()])
    channel = FakeChannel()

    def resolver(run_id, user_id):
        raise RuntimeError("db unavailable")

    worker = _make_worker(repo, channel, resolve_run_summary=resolver)

    await worker.run_once(now=datetime.now(UTC))

    # A summary lookup failure must never block the notification itself.
    assert repo.sent == ["delivery-1"]
    assert repo.failed == []
    assert "task-1" in channel.sent[0][1]


@pytest.mark.asyncio
async def test_delivery_sends_skeleton_when_summary_is_missing():
    repo = FakeDeliveryRepo([_delivery_row()])
    channel = FakeChannel()
    worker = _make_worker(repo, channel, resolve_run_summary=lambda run_id, user_id: None)

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == ["delivery-1"]
    text = channel.sent[0][1]
    assert "task-1" in text
    assert "Result:" not in text


class FakeWsClient:
    def __init__(self, *, errcode=0):
        self.calls = []
        self.errcode = errcode

    async def send_message(self, chatid, body):
        self.calls.append((chatid, body))
        return {"errcode": self.errcode, "errmsg": "ok"}


def _wecom_channel(ws_client=None):
    channel = WeComChannel(bus=MessageBus(), config={})
    channel._ws_client = ws_client
    return channel


@pytest.mark.asyncio
async def test_wecom_send_notification_pushes_markdown():
    ws_client = FakeWsClient()
    channel = _wecom_channel(ws_client)

    await channel.send_notification(target="GaoZhiChao", text_markdown="**done**")

    assert len(ws_client.calls) == 1
    chatid, body = ws_client.calls[0]
    assert chatid == "GaoZhiChao"
    assert body == {"msgtype": "markdown", "markdown": {"content": "**done**"}}


@pytest.mark.asyncio
async def test_wecom_send_notification_raises_on_platform_error():
    ws_client = FakeWsClient(errcode=853000)
    channel = _wecom_channel(ws_client)

    with pytest.raises(RuntimeError, match="853000"):
        await channel.send_notification(target="GaoZhiChao", text_markdown="**done**")


@pytest.mark.asyncio
async def test_wecom_send_notification_raises_when_not_connected():
    channel = _wecom_channel(None)

    with pytest.raises(RuntimeError):
        await channel.send_notification(target="GaoZhiChao", text_markdown="**done**")
