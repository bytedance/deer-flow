"""Unit tests for the Jira channel."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.channels.jira import JIRA_CHAT_ID, JiraChannel
from app.channels.message_bus import InboundMessageType, MessageBus


@pytest.fixture()
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture()
def jira_config() -> dict:
    return {
        "sse_url": "http://example.com/sse",
        "bot_account_id": "abc123",
        "allowed_labels": ["anna"],
    }


@pytest.fixture()
def channel(bus: MessageBus, jira_config: dict) -> JiraChannel:
    return JiraChannel(bus=bus, config=jira_config)


def _make_comment_payload(
    *,
    mention_account_id: str = "abc123",
    issue_key: str = "TEST-1",
    comment_body: str | None = None,
) -> dict:
    if comment_body is None:
        comment_body = f"Hey [~accountid:{mention_account_id}] can you take a look?"
    return {
        "timestamp": 1700000000000,
        "webhookEvent": "comment_created",
        "comment": {
            "id": "10001",
            "body": comment_body,
            "updateAuthor": {
                "accountId": "user-456",
                "displayName": "Alice",
                "emailAddress": "alice@example.com",
            },
            "author": {
                "accountId": "user-456",
                "displayName": "Alice",
            },
            "created": "2023-11-14T00:00:00.000+0000",
            "updated": "2023-11-14T00:00:00.000+0000",
        },
        "issue": {
            "id": "1001",
            "key": issue_key,
            "fields": {
                "summary": "Fix login bug",
                "status": {"name": "In Progress", "id": "3", "description": "Work in progress"},
                "assignee": {
                    "accountId": "abc123",
                    "displayName": "Bot",
                },
            },
        },
    }


def _make_issue_payload(
    *,
    issue_key: str = "TEST-2",
    issue_type: str = "Task",
    labels: list[str] | None = None,
    status: str = "Open",
) -> dict:
    if labels is None:
        labels = ["Anna"]
    return {
        "timestamp": 1700000000000,
        "webhookEvent": "jira:issue_created",
        "user": {"accountId": "user-789", "displayName": "Bob"},
        "issue": {
            "id": "1002",
            "key": issue_key,
            "fields": {
                "summary": "Implement new feature",
                "description": "Please implement the new feature as described.",
                "issuetype": {"name": issue_type, "id": "10001"},
                "status": {"name": status, "id": "1"},
                "priority": {"name": "High"},
                "labels": labels,
                "assignee": {"accountId": "abc123", "displayName": "Bot"},
                "reporter": {
                    "accountId": "user-789",
                    "displayName": "Bob",
                    "emailAddress": "bob@example.com",
                },
            },
        },
    }


class TestJiraChannelInit:
    def test_defaults(self, bus: MessageBus) -> None:
        ch = JiraChannel(bus=bus, config={"sse_url": "http://x", "bot_account_id": "id1"})
        assert ch.name == "jira"
        assert ch._sse_url == "http://x"
        assert ch._bot_account_id == "id1"
        assert ch._allowed_labels == []

    def test_custom_labels(self, bus: MessageBus) -> None:
        ch = JiraChannel(bus=bus, config={"sse_url": "http://x", "bot_account_id": "id1", "allowed_labels": ["Bot", "AI"]})
        assert ch._allowed_labels == ["bot", "ai"]


class TestJiraChannelStart:
    @pytest.mark.anyio
    async def test_start_missing_sse_url(self, bus: MessageBus) -> None:
        ch = JiraChannel(bus=bus, config={"bot_account_id": "id1"})
        await ch.start()
        assert not ch._running

    @pytest.mark.anyio
    async def test_start_missing_bot_account_id(self, bus: MessageBus) -> None:
        ch = JiraChannel(bus=bus, config={"sse_url": "http://x"})
        await ch.start()
        assert not ch._running

    @pytest.mark.anyio
    async def test_start_and_stop(self, channel: JiraChannel) -> None:
        with patch.object(channel, "_sse_loop", new_callable=AsyncMock):
            await channel.start()
            assert channel._running
            assert channel._task is not None

            await channel.stop()
            assert not channel._running
            assert channel._task is None


class TestCommentEvent:
    @pytest.mark.anyio
    async def test_comment_with_mention_publishes(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_comment_payload()

        channel._handle_comment_event(payload)
        # asyncio.ensure_future schedules the coroutine — give it a tick
        await asyncio.sleep(0)

        bus.publish_inbound.assert_called_once()
        msg = bus.publish_inbound.call_args[0][0]
        assert msg.channel_name == "jira"
        assert msg.chat_id == JIRA_CHAT_ID
        assert msg.topic_id == "TEST-1"
        assert msg.user_id == "user-456"
        assert msg.msg_type == InboundMessageType.CHAT
        assert "Fix login bug" in msg.text
        assert "Alice" in msg.text

    @pytest.mark.anyio
    async def test_comment_without_mention_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_comment_payload(comment_body="Just a regular comment")

        channel._handle_comment_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()

    @pytest.mark.anyio
    async def test_comment_missing_comment_field(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_comment_payload()
        del payload["comment"]

        channel._handle_comment_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()


class TestCommentEventADF:
    """Tests for ADF (Atlassian Document Format) comment bodies."""

    @pytest.mark.anyio
    async def test_adf_body_with_mention_publishes(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_comment_payload()
        # Replace string body with ADF object containing a mention node
        payload["comment"]["body"] = {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "mention", "attrs": {"id": "abc123", "text": "@Bot"}},
                        {"type": "text", "text": " please take a look"},
                    ],
                }
            ],
        }

        channel._handle_comment_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_called_once()
        msg = bus.publish_inbound.call_args[0][0]
        assert "please take a look" in msg.text

    @pytest.mark.anyio
    async def test_adf_body_without_mention_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_comment_payload()
        payload["comment"]["body"] = {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Just a regular comment"},
                    ],
                }
            ],
        }

        channel._handle_comment_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()


class TestIssueEvent:
    @pytest.mark.anyio
    async def test_matching_issue_publishes(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload()

        channel._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_called_once()
        msg = bus.publish_inbound.call_args[0][0]
        assert msg.channel_name == "jira"
        assert msg.chat_id == JIRA_CHAT_ID
        assert msg.topic_id == "TEST-2"
        assert msg.user_id == "user-789"
        assert "Implement new feature" in msg.text
        assert "Task Assignment" in msg.text

    @pytest.mark.anyio
    async def test_non_task_type_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload(issue_type="Bug")

        channel._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()

    @pytest.mark.anyio
    async def test_missing_label_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload(labels=["other"])

        channel._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()

    @pytest.mark.anyio
    async def test_empty_allowed_labels_matches_all(self, bus: MessageBus) -> None:
        ch = JiraChannel(bus=bus, config={"sse_url": "http://x", "bot_account_id": "abc123", "allowed_labels": []})
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload(labels=["anything"])

        ch._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_called_once()

    @pytest.mark.anyio
    async def test_not_assigned_to_bot_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload()
        payload["issue"]["fields"]["assignee"] = {"accountId": "someone-else", "displayName": "Human"}

        channel._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()

    @pytest.mark.anyio
    async def test_unassigned_issue_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload()
        payload["issue"]["fields"]["assignee"] = None

        channel._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()

    @pytest.mark.anyio
    async def test_non_open_status_skipped(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        payload = _make_issue_payload(status="In Progress")

        channel._handle_issue_event(payload)
        await asyncio.sleep(0)

        bus.publish_inbound.assert_not_called()


class TestJiraEventDispatch:
    def test_dispatch_ping(self, channel: JiraChannel) -> None:
        # Should not raise
        channel._dispatch_event("ping", "keep-alive")

    def test_dispatch_unknown_event(self, channel: JiraChannel) -> None:
        # Should not raise
        channel._dispatch_event("unknown_type", "{}")

    def test_dispatch_invalid_json(self, channel: JiraChannel) -> None:
        # Should not raise (logs error)
        channel._dispatch_event("jira", "not-json")

    @pytest.mark.anyio
    async def test_dispatch_routes_comment(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        import json

        payload = _make_comment_payload()
        channel._dispatch_event("jira", json.dumps(payload))
        await asyncio.sleep(0)

        bus.publish_inbound.assert_called_once()

    @pytest.mark.anyio
    async def test_dispatch_routes_issue(self, channel: JiraChannel, bus: MessageBus) -> None:
        bus.publish_inbound = AsyncMock()
        import json

        payload = _make_issue_payload()
        channel._dispatch_event("jira", json.dumps(payload))
        await asyncio.sleep(0)

        bus.publish_inbound.assert_called_once()


class TestSendNoop:
    @pytest.mark.anyio
    async def test_send_is_noop(self, channel: JiraChannel) -> None:
        from app.channels.message_bus import OutboundMessage

        msg = OutboundMessage(channel_name="jira", chat_id="jira:mentions", thread_id="t1", text="hello")
        # Should not raise
        await channel.send(msg)
