"""Tests for the notification delivery worker (issue #4254).

The worker consumes the notification outbox written by the scheduled-task
completion hook and pushes each delivery through the owning channel's
proactive send path. It must never touch execution state.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.channels.base import ChannelUnavailable
from app.channels.message_bus import MessageBus
from app.channels.wecom import WeComChannel
from app.scheduler.notification_delivery import NotificationDeliveryWorker, redact_egress_text, render_notification_text


class FakeDeliveryRepo:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.claims = []
        self.sent = []
        self.failed = []
        self.resets = []
        self.events = []

    async def reset_stale_sending_rows(self, *, now, timeout):
        self.resets.append((now, timeout))
        self.events.append("reset")
        return 0

    async def claim_due_deliveries(self, *, now, limit):
        claimed, self.rows = self.rows[:limit], self.rows[limit:]
        self.claims.append((now, limit))
        self.events.append("claim")
        return claimed

    async def mark_sent(self, delivery_id):
        self.sent.append(delivery_id)

    async def mark_failed(self, delivery_id, *, error=None, count_attempt=True):
        self.failed.append((delivery_id, error, count_attempt))


class FakeChannel:
    def __init__(self, *, fail=False, unavailable=False, running=True):
        self.sent = []
        self.fail = fail
        self.unavailable = unavailable
        self.is_running = running

    async def send_notification(self, *, target, text_markdown):
        if self.unavailable:
            raise ChannelUnavailable("channel transport down")
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


def test_render_prefers_task_title_over_id():
    text = render_notification_text(_delivery_row(payload={"run_status": "success", "error": None, "task_id": "task-1", "task_title": "Daily digest"}))

    assert "Daily digest" in text
    task_line = next(line for line in text.splitlines() if line.startswith("Task:"))
    assert "task-1" not in task_line


def test_render_run_failed_text_does_not_forward_raw_error():
    secret = "sk-" + ("x" * 40)
    text = render_notification_text(
        _delivery_row(
            event="run_failed",
            payload={"run_status": "failed", "error": secret, "task_id": "task-1"},
        )
    )

    assert "failed" in text.lower()
    assert secret not in text
    assert "workspace" in text.lower()
    assert "Error:" not in text


def test_render_truncates_unbounded_error_text():
    text = render_notification_text(
        _delivery_row(
            event="run_failed",
            payload={"run_status": "failed", "error": "x" * 5000, "task_id": "task-1"},
        )
    )

    assert len(text) < 1000
    assert "Error:" not in text


def test_redact_egress_text_scrubs_seeded_secret():
    secret = "sk-" + ("S" * 40)
    redacted = redact_egress_text(f"answer used {secret} here")

    assert secret not in redacted
    assert "[redacted]" in redacted


def test_redact_egress_text_scrubs_entire_pem_block():
    pem_body = "ABCDEFSECRETKEYBODY"
    pem = "-----BEGIN PRIVATE KEY-----\n" + pem_body + "\n-----END PRIVATE KEY-----"
    redacted = redact_egress_text(f"key follows\n{pem}\nend")

    assert pem_body not in redacted
    assert "BEGIN PRIVATE KEY" not in redacted
    assert "END PRIVATE KEY" not in redacted
    assert "[redacted]" in redacted


def test_render_redacts_entire_pem_block_in_result_summary():
    pem_body = "ABCDEFSECRETKEYBODY"
    pem = "-----BEGIN PRIVATE KEY-----\n" + pem_body + "\n-----END PRIVATE KEY-----"
    text = render_notification_text(_delivery_row(payload={"run_status": "success", "error": None, "task_id": "task-1", "result_summary": pem}))

    assert pem_body not in text
    assert "END PRIVATE KEY" not in text
    assert "[redacted]" in text


def test_render_redacts_secret_in_result_summary():
    secret = "ghp_" + ("a" * 36)
    text = render_notification_text(_delivery_row(payload={"run_status": "success", "error": None, "task_id": "task-1", "result_summary": f"token={secret}"}))

    assert secret not in text
    assert "[redacted]" in text


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
    delivery_id, error, count_attempt = repo.failed[0]
    assert delivery_id == "delivery-1"
    assert "wecom" in error
    # A channel that is simply not running must not burn the retry budget:
    # the row comes back on a flat long backoff until the channel returns.
    assert count_attempt is False


@pytest.mark.asyncio
async def test_run_once_parks_when_registered_channel_reports_not_running():
    repo = FakeDeliveryRepo([_delivery_row()])
    worker = _make_worker(repo, FakeChannel(running=False))

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    _, error, count_attempt = repo.failed[0]
    assert "not running" in error
    assert count_attempt is False


@pytest.mark.asyncio
async def test_run_once_parks_without_counting_channel_unavailable():
    repo = FakeDeliveryRepo([_delivery_row()])
    worker = _make_worker(repo, FakeChannel(unavailable=True))

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    delivery_id, error, count_attempt = repo.failed[0]
    assert delivery_id == "delivery-1"
    assert "transport down" in error
    assert count_attempt is False


@pytest.mark.asyncio
async def test_run_once_marks_failed_when_send_raises():
    repo = FakeDeliveryRepo([_delivery_row()])
    worker = _make_worker(repo, FakeChannel(fail=True))

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    delivery_id, error, count_attempt = repo.failed[0]
    assert delivery_id == "delivery-1"
    assert "platform rejected" in error
    # A real send error does count against the retry budget.
    assert count_attempt is True


@pytest.mark.asyncio
async def test_stop_cancels_when_poller_exceeds_timeout():
    repo = FakeDeliveryRepo([])
    worker = NotificationDeliveryWorker(
        delivery_repo=repo,
        resolve_channel=lambda _provider: None,
        poll_interval_seconds=60,
        stop_timeout_seconds=0.05,
    )

    async def _hang_forever():
        await asyncio.Event().wait()

    worker._stop.clear()
    worker._task = asyncio.create_task(_hang_forever())

    await worker.stop()

    assert worker._task is None


@pytest.mark.asyncio
async def test_run_once_without_due_rows_is_noop():
    repo = FakeDeliveryRepo([])
    worker = _make_worker(repo, FakeChannel())

    await worker.run_once(now=datetime.now(UTC))

    assert repo.sent == []
    assert repo.failed == []


# ---------------------------------------------------------------------------
# Crash recovery (review follow-up): a row exploding mid-delivery must not
# strand the rest of the batch in "sending", and rows orphaned between claim
# and the final status write come back through the stale reset.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_recovers_stale_sending_rows_before_claiming():
    repo = FakeDeliveryRepo([_delivery_row()])
    worker = _make_worker(repo, FakeChannel())
    now = datetime.now(UTC)

    await worker.run_once(now=now)

    assert repo.events == ["reset", "claim"]
    assert repo.resets[0][0] == now


@pytest.mark.asyncio
async def test_run_once_isolates_crashes_so_rest_of_batch_still_delivers():
    """Replay the reviewer's worst case: row one crashes even its own
    mark_failed (e.g. the DB blip that killed the status write), which used
    to abort the loop and strand every following claimed row in
    ``sending``."""

    class ExplodingRepo(FakeDeliveryRepo):
        async def mark_failed(self, delivery_id, *, error=None):
            if delivery_id == "delivery-1":
                raise RuntimeError("db gone")
            await super().mark_failed(delivery_id, error=error)

    class TargetFailChannel(FakeChannel):
        async def send_notification(self, *, target, text_markdown):
            if target == "GaoZhiChao":
                raise RuntimeError("platform rejected")
            await super().send_notification(target=target, text_markdown=text_markdown)

    repo = ExplodingRepo(
        [
            _delivery_row(delivery_id="delivery-1"),
            _delivery_row(delivery_id="delivery-2", target="bob"),
        ]
    )
    worker = _make_worker(repo, TargetFailChannel())

    await worker.run_once(now=datetime.now(UTC))

    # Row one is left for the stale reset to recover; row two must not be
    # sacrificed with it.
    assert repo.sent == ["delivery-2"]
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
    channel._running = True
    channel._ws_transport_up = ws_client is not None
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
    channel._running = True

    with pytest.raises(ChannelUnavailable, match="not connected"):
        await channel.send_notification(target="GaoZhiChao", text_markdown="**done**")


@pytest.mark.asyncio
async def test_wecom_send_notification_wraps_transport_errors_as_unavailable():
    class BrokenWsClient:
        async def send_message(self, chatid, body):
            raise ConnectionError("websocket closed")

    channel = _wecom_channel(BrokenWsClient())
    channel._ws_transport_up = False  # single probe; no retry/sleep storm

    with pytest.raises(ChannelUnavailable, match="transport unavailable"):
        await channel.send_notification(target="GaoZhiChao", text_markdown="**done**")

    assert channel._ws_transport_up is False


@pytest.mark.asyncio
async def test_wecom_send_notification_propagates_deterministic_errors():
    class InvalidTargetWsClient:
        async def send_message(self, chatid, body):
            raise ValueError("invalid target")

    channel = _wecom_channel(InvalidTargetWsClient())

    with pytest.raises(ValueError, match="invalid target"):
        await channel.send_notification(target="GaoZhiChao", text_markdown="**done**")
