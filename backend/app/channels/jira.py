"""Jira channel — listens to a Jira webhook SSE endpoint for @mentions and task assignments."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage

logger = logging.getLogger(__name__)

JIRA_CHAT_ID = "jira:mentions"

# Maximum backoff delay (seconds) for SSE reconnection
_MAX_BACKOFF = 60


class JiraChannel(Channel):
    """Jira IM channel that listens for webhook events via SSE.

    Configuration keys (in ``config.yaml`` under ``channels.jira``):
        - ``sse_url``: URL of the Jira webhook SSE endpoint.
        - ``bot_account_id``: Jira account ID to watch for @mentions.
        - ``allowed_labels``: (optional) Labels to match for task assignment events (default: ``["anna"]``).
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="jira", bus=bus, config=config)
        self._sse_url: str = config.get("sse_url", "")
        self._bot_account_id: str = config.get("bot_account_id", "")
        self._allowed_labels: list[str] = [label.lower() for label in config.get("allowed_labels", [])]
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return

        if not self._sse_url:
            logger.error("Jira channel requires sse_url")
            return

        if not self._bot_account_id:
            logger.error("Jira channel requires bot_account_id")
            return

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)
        self._task = asyncio.create_task(self._sse_loop())
        logger.info("Jira channel started (sse_url=%s)", self._sse_url)

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Jira channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        # No-op: agent replies via acli inside the sandbox.
        logger.debug("[Jira] send no-op (agent replies via acli): chat_id=%s, text_len=%d", msg.chat_id, len(msg.text))

    # -- SSE connection --------------------------------------------------------

    async def _sse_loop(self) -> None:
        """Connect to the SSE endpoint and process events, with auto-reconnect."""
        import httpx

        backoff = 1
        while self._running:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=None, write=30, pool=30)) as client:
                    async with client.stream("GET", self._sse_url, headers={"Accept": "text/event-stream"}) as response:
                        response.raise_for_status()
                        logger.info("[Jira] SSE connected to %s", self._sse_url)
                        backoff = 1  # reset on successful connection

                        event_type = ""
                        data_lines: list[str] = []

                        async for line in response.aiter_lines():
                            if not self._running:
                                return

                            if line.startswith("event:"):
                                event_type = line[len("event:"):].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[len("data:"):].strip())
                            elif line == "":
                                # Empty line = end of event
                                if event_type and data_lines:
                                    data = "\n".join(data_lines)
                                    self._dispatch_event(event_type, data)
                                event_type = ""
                                data_lines = []

            except asyncio.CancelledError:
                return
            except Exception as exc:
                if not self._running:
                    return
                logger.warning("[Jira] SSE error, reconnecting in %ds: %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    def _dispatch_event(self, event_type: str, data: str) -> None:
        """Route an SSE event to the appropriate handler."""
        if event_type == "ping":
            logger.debug("[Jira] SSE ping: %s", data)
            return

        if event_type == "jira":
            try:
                payload = json.loads(data)
                self._handle_jira_event(payload)
            except json.JSONDecodeError:
                logger.error("[Jira] failed to parse event data: %s", data[:200])
            except Exception:
                logger.exception("[Jira] error handling jira event")
        else:
            logger.debug("[Jira] ignoring event type: %s", event_type)

    # -- event handlers --------------------------------------------------------

    def _handle_jira_event(self, payload: dict[str, Any]) -> None:
        webhook_event = payload.get("webhookEvent", "")

        if webhook_event in ("comment_created", "comment_updated"):
            self._handle_comment_event(payload)
        elif webhook_event in ("jira:issue_updated", "jira:issue_created"):
            self._handle_issue_event(payload)
        else:
            logger.debug("[Jira] ignoring unhandled webhookEvent: %s", webhook_event)

    def _handle_comment_event(self, payload: dict[str, Any]) -> None:
        comment = payload.get("comment")
        issue = payload.get("issue", {})

        if not comment:
            logger.warning("[Jira] comment event missing comment field")
            return

        body = comment.get("body", "")
        if f"[~accountid:{self._bot_account_id}]" not in body:
            logger.debug("[Jira] bot not mentioned in comment on %s, skipping", issue.get("key", "?"))
            return

        fields = issue.get("fields", {})
        author = comment.get("updateAuthor") or comment.get("author", {})
        assignee = fields.get("assignee")
        status = fields.get("status", {})
        issue_key = issue.get("key", "UNKNOWN")

        logger.info("[Jira] bot mentioned in comment on %s by %s", issue_key, author.get("displayName", "?"))

        lines: list[str] = [
            "Jira Comment Notification",
            "========================",
            f"Issue: {issue_key} - {fields.get('summary', '')}",
            f"Issue ID: {issue.get('id', '')}",
            f"Status: {status.get('name', '')} (id: {status.get('id', '')}) - {status.get('description', 'No description')}",
        ]

        if assignee:
            email_part = f", email: {assignee['emailAddress']}" if assignee.get("emailAddress") else ""
            lines.append(f"Assignee: {assignee.get('displayName', '')} (accountId: {assignee.get('accountId', '')}{email_part})")
        else:
            lines.append("Assignee: Unassigned")

        lines.append("")
        email_part = f", email: {author['emailAddress']}" if author.get("emailAddress") else ""
        lines.append(f"Comment by: {author.get('displayName', '')} (accountId: {author.get('accountId', '')}{email_part})")
        lines.append("---")
        lines.append(body)
        lines.append("---")
        lines.append("")
        lines.append("Reply instructions:")
        lines.append(f"- Issue key: {issue_key}")
        lines.append(f"- Commenter accountId: {author.get('accountId', '')}")
        lines.append(f"- Commenter displayName: {author.get('displayName', '')}")
        lines.append('- Write an ADF JSON file with a mention node and your response, then post with: acli jira workitem comment create --key "{issueKey}" --body-file /tmp/jira-reply.json')
        lines.append("- See your CLAUDE.md for the exact ADF template")

        content = "\n".join(lines)
        timestamp = datetime.fromtimestamp(payload.get("timestamp", 0) / 1000, tz=timezone.utc).isoformat()

        inbound = self._make_inbound(
            chat_id=JIRA_CHAT_ID,
            user_id=author.get("accountId", "unknown"),
            text=content,
            msg_type=InboundMessageType.CHAT,
            metadata={"jira_event": "comment", "issue_key": issue_key, "comment_id": comment.get("id", "")},
        )
        inbound.topic_id = issue_key

        asyncio.ensure_future(self.bus.publish_inbound(inbound))

    def _handle_issue_event(self, payload: dict[str, Any]) -> None:
        issue = payload.get("issue", {})
        fields = issue.get("fields", {})
        issue_key = issue.get("key", "UNKNOWN")

        is_task = (fields.get("issuetype", {}).get("name", "")).lower() == "task"
        labels = [label.lower() for label in (fields.get("labels") or [])]
        has_matching_label = not self._allowed_labels or any(label in labels for label in self._allowed_labels)
        is_open = (fields.get("status", {}).get("name", "")).lower() == "open"

        if not is_task or not has_matching_label or not is_open:
            logger.debug(
                "[Jira] issue %s does not match criteria (type=%s, labels=%s, status=%s), skipping",
                issue_key,
                fields.get("issuetype", {}).get("name"),
                fields.get("labels"),
                fields.get("status", {}).get("name"),
            )
            return

        logger.info("[Jira] task assigned: %s - %s", issue_key, fields.get("summary", ""))

        assignee = fields.get("assignee")
        reporter = fields.get("reporter")
        status = fields.get("status", {})
        timestamp = datetime.fromtimestamp(payload.get("timestamp", 0) / 1000, tz=timezone.utc).isoformat()

        lines: list[str] = [
            "Jira Task Assignment",
            "====================",
            "You have been assigned a new Jira task to handle.",
            "",
            f"Issue: {issue_key} - {fields.get('summary', '')}",
            f"Issue ID: {issue.get('id', '')}",
            f"Type: {fields.get('issuetype', {}).get('name', '')}",
            f"Status: {status.get('name', '')}",
            f"Priority: {fields.get('priority', {}).get('name', 'Unknown')}",
            f"Labels: {', '.join(fields.get('labels') or [])}",
        ]

        if assignee:
            lines.append(f"Assignee: {assignee.get('displayName', '')} (accountId: {assignee.get('accountId', '')})")

        if reporter:
            email_part = f", email: {reporter['emailAddress']}" if reporter.get("emailAddress") else ""
            lines.append(f"Reporter: {reporter.get('displayName', '')} (accountId: {reporter.get('accountId', '')}{email_part})")

        description = fields.get("description")
        if description:
            lines.extend(["", "Description:", "---", description, "---"])

        lines.extend(["", 'Follow the "Handle Task Assignment" skill in your CLAUDE.md to process this ticket.'])

        content = "\n".join(lines)

        sender = payload.get("user") or reporter or {"accountId": "system", "displayName": "Jira"}

        inbound = self._make_inbound(
            chat_id=JIRA_CHAT_ID,
            user_id=sender.get("accountId", "system"),
            text=content,
            msg_type=InboundMessageType.CHAT,
            metadata={"jira_event": "issue", "issue_key": issue_key},
        )
        inbound.topic_id = issue_key

        asyncio.ensure_future(self.bus.publish_inbound(inbound))
