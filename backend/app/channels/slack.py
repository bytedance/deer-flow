"""Slack channel — connects via Socket Mode (no public IP needed)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter

from app.channels.base import Channel
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

_slack_md_converter = SlackMarkdownConverter()


def _escape_slack_text(text: str) -> str:
    """Escape Slack's reserved characters (``&``, ``<``, ``>``) in raw message text,
    except a ``>`` at the very start of a line -- Slack's own blockquote marker.

    Slack requires callers to replace these with their HTML entity equivalents
    (``&amp;``, ``&lt;``, ``&gt;``) before sending message text -- an unescaped
    ``<...>`` triggers Slack's own mention/link syntax (e.g. ``<@USERID>``,
    ``<http://url|label>``). See:
    https://api.slack.com/reference/surfaces/formatting#escaping

    This MUST run before ``_slack_md_converter.convert()``, not after: the
    converter emits its own mrkdwn link syntax (``<url|label>``) for real
    markdown links, and that generated syntax must reach Slack unescaped.
    Escaping the raw input first -- and leaving the converter's own output
    alone -- satisfies both requirements. ``html.escape(..., quote=False)``
    replaces ``&`` before ``<``/``>``, so the entities it introduces are never
    re-escaped.

    Only ``&`` and ``<`` neutralize Slack's ``<...>`` mention/link syntax; a
    ``>`` is special to Slack only at the start of a line, where the mrkdwn
    converter passes it through unchanged as a blockquote marker. Escaping
    every ``>`` would turn a quoted line into visible ``&gt;`` text instead of
    a rendered blockquote, so a line-leading ``>`` is restored to a literal
    ``>`` after escaping; a ``>`` anywhere else in the text still escapes.
    """
    escaped = html.escape(text, quote=False)
    return re.sub(r"(?m)^&gt;", ">", escaped)


def _normalize_allowed_users(allowed_users: Any) -> set[str]:
    if allowed_users is None:
        return set()
    if isinstance(allowed_users, str):
        values = [allowed_users]
    elif isinstance(allowed_users, list | tuple | set):
        values = allowed_users
    else:
        logger.warning(
            "Slack allowed_users should be a list of Slack user IDs or a single Slack user ID string; treating %s as one string value",
            type(allowed_users).__name__,
        )
        values = [allowed_users]
    return {str(user_id) for user_id in values if str(user_id)}


def _strip_leading_slack_bot_mention(text: str, bot_user_id: str | None) -> str:
    if not bot_user_id:
        return text
    if not text.startswith("<@"):
        return text
    end = text.find(">")
    if end <= 2:
        return text
    mentioned_user_id = text[2:end].split("|", 1)[0].lstrip("!")
    if mentioned_user_id != bot_user_id:
        return text
    return text[end + 1 :].lstrip()


class SlackChannel(Channel):
    """Slack IM channel using Socket Mode (WebSocket, no public IP).

    Configuration keys (in ``config.yaml`` under ``channels.slack``):
        - ``bot_token``: Slack Bot User OAuth Token (xoxb-...).
        - ``app_token``: Slack App-Level Token (xapp-...) for Socket Mode.
        - ``allowed_users``: (optional) List of allowed Slack user IDs, or a
          single Slack user ID string as shorthand. Empty = allow all. Other
          scalar values are treated as a single string with a warning.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="slack", bus=bus, config=config)
        self._socket_client = None
        self._web_client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._allowed_users = _normalize_allowed_users(config.get("allowed_users", []))
        self._web_client_factory = config.get("web_client_factory")
        self._connection_web_clients: dict[str, tuple[str, Any]] = {}
        configured_bot_user_id = config.get("bot_user_id")
        self._bot_user_id = str(configured_bot_user_id).lstrip("@") if configured_bot_user_id else None

    async def start(self) -> None:
        if self._running:
            return

        try:
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError:
            logger.error("slack-sdk is not installed. Install it with: uv add slack-sdk")
            return

        self._SocketModeResponse = SocketModeResponse
        if self._web_client_factory is None:
            self._web_client_factory = WebClient

        bot_token = self.config.get("bot_token", "")
        app_token = self.config.get("app_token", "")

        if self.config.get("event_delivery") == "http":
            logger.error("Slack HTTP Events mode is not supported by this channel adapter; use Socket Mode with app_token")
            return

        if not bot_token or not app_token:
            logger.error("Slack channel requires bot_token and app_token")
            return

        await self._initialize_operator_web_client(str(bot_token))
        self._socket_client = SocketModeClient(
            app_token=app_token,
            web_client=self._web_client,
        )
        self._loop = asyncio.get_event_loop()

        self._socket_client.socket_mode_request_listeners.append(self._on_socket_event)

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # Start socket mode in background thread
        asyncio.get_event_loop().run_in_executor(None, self._socket_client.connect)
        logger.info("Slack channel started")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._socket_client:
            self._socket_client.close()
            self._socket_client = None
        logger.info("Slack channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        web_client = await self._get_web_client_for_message(msg)
        if not web_client:
            return

        kwargs: dict[str, Any] = {
            "channel": msg.chat_id,
            "text": _slack_md_converter.convert(_escape_slack_text(msg.text)),
        }
        if msg.thread_ts:
            kwargs["thread_ts"] = msg.thread_ts

        async def post_message() -> None:
            await asyncio.to_thread(web_client.chat_postMessage, **kwargs)
            # Add a completion reaction to the thread root
            if msg.thread_ts:
                await asyncio.to_thread(
                    self._add_reaction_with_client,
                    web_client,
                    msg.chat_id,
                    msg.thread_ts,
                    "white_check_mark",
                )

        try:
            await self._send_with_retry(
                post_message,
                max_retries=_max_retries,
                log_prefix="[Slack]",
            )
        except Exception:
            # Add failure reaction on error
            if msg.thread_ts:
                try:
                    await asyncio.to_thread(
                        self._add_reaction_with_client,
                        web_client,
                        msg.chat_id,
                        msg.thread_ts,
                        "x",
                    )
                except Exception:
                    pass
            raise

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        web_client = await self._get_web_client_for_message(msg)
        if not web_client:
            return False

        try:
            kwargs: dict[str, Any] = {
                "channel": msg.chat_id,
                "file": str(attachment.actual_path),
                "filename": attachment.filename,
                "title": attachment.filename,
            }
            if msg.thread_ts:
                kwargs["thread_ts"] = msg.thread_ts

            await asyncio.to_thread(web_client.files_upload_v2, **kwargs)
            logger.info("[Slack] file uploaded: %s to channel=%s", attachment.filename, msg.chat_id)
            return True
        except Exception:
            logger.exception("[Slack] failed to upload file: %s", attachment.filename)
            return False

    # -- internal ----------------------------------------------------------

    async def _initialize_operator_web_client(self, bot_token: str) -> None:
        self._web_client = self._web_client_factory(token=bot_token)
        if self._bot_user_id is not None:
            return
        try:
            auth_info = await asyncio.to_thread(self._web_client.auth_test)
            user_id = auth_info.get("user_id") if isinstance(auth_info, dict) else None
            if user_id is None:
                auth_get = getattr(auth_info, "get", None)
                user_id = auth_get("user_id") if callable(auth_get) else None
            if isinstance(user_id, str) and user_id:
                self._bot_user_id = user_id
        except Exception:
            logger.warning("[Slack] failed to resolve bot user id; app mention text may include the bot mention", exc_info=True)

    async def _get_web_client_for_message(self, msg: OutboundMessage):
        if msg.connection_id and self._connection_repo is not None:
            credentials = await self._connection_repo.get_credentials(msg.connection_id)
            access_token = credentials.get("access_token") if credentials else None
            if not access_token:
                return self._web_client
            # WebClient keeps its own HTTP session and rate-limit state, so
            # reuse one per connection until its token changes.
            cached = self._connection_web_clients.get(msg.connection_id)
            if cached is not None and cached[0] == access_token:
                return cached[1]
            if self._web_client_factory is None:
                from slack_sdk import WebClient

                self._web_client_factory = WebClient
            web_client = self._web_client_factory(token=access_token)
            self._connection_web_clients[msg.connection_id] = (access_token, web_client)
            return web_client
        return self._web_client

    @staticmethod
    def _add_reaction_with_client(web_client, channel_id: str, timestamp: str, emoji: str) -> None:
        try:
            web_client.reactions_add(
                channel=channel_id,
                timestamp=timestamp,
                name=emoji,
            )
        except Exception as exc:
            if "already_reacted" not in str(exc):
                logger.warning("[Slack] failed to add reaction %s: %s", emoji, exc)

    def _add_reaction(self, channel_id: str, timestamp: str, emoji: str) -> None:
        """Add an emoji reaction to a message (best-effort, non-blocking)."""
        if not self._web_client:
            return
        self._add_reaction_with_client(self._web_client, channel_id, timestamp, emoji)

    def _send_running_reply(self, channel_id: str, thread_ts: str) -> None:
        """Send a 'Working on it......' reply in the thread (called from SDK thread)."""
        if not self._web_client:
            return
        try:
            self._web_client.chat_postMessage(
                channel=channel_id,
                text=":hourglass_flowing_sand: Working on it...",
                thread_ts=thread_ts,
            )
            logger.info("[Slack] 'Working on it...' reply sent in channel=%s, thread_ts=%s", channel_id, thread_ts)
        except Exception:
            logger.exception("[Slack] failed to send running reply in channel=%s", channel_id)

    def _on_socket_event(self, client, req) -> None:
        """Called by slack-sdk for each Socket Mode event."""
        try:
            # Acknowledge the event
            response = self._SocketModeResponse(envelope_id=req.envelope_id)
            client.send_socket_mode_response(response)

            event_type = req.type
            if event_type != "events_api":
                return

            if self._bot_user_id is None:
                authorization = next((item for item in req.payload.get("authorizations", []) if isinstance(item, dict)), None)
                user_id = authorization.get("user_id") if authorization else None
                if isinstance(user_id, str) and user_id:
                    self._bot_user_id = user_id

            event = req.payload.get("event", {})
            etype = event.get("type", "")

            # Handle message events (DM or @mention)
            if etype in ("message", "app_mention"):
                self._handle_message_event(
                    event,
                    team_id=req.payload.get("team_id") or req.payload.get("team") or event.get("team"),
                )

        except Exception:
            logger.exception("Error processing Slack event")

    def _handle_message_event(self, event: dict, *, team_id: str | None = None) -> None:
        # Ignore bot messages
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id = event.get("user", "")

        text = event.get("text", "").strip()
        if event.get("type") == "app_mention":
            text = _strip_leading_slack_bot_mention(text, self._bot_user_id)
        if not text:
            return

        connect_code = self._pending_connect_code(text)
        if connect_code:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._bind_connection_from_connect_code(
                        event=event,
                        team_id=str(team_id or ""),
                        code=connect_code,
                    ),
                    self._loop,
                )
            return

        # Check allowed users after connect-code handling so browser-initiated
        # binding can bootstrap a new external identity.
        if self._allowed_users and user_id not in self._allowed_users:
            logger.debug("Ignoring message from non-allowed user: %s", user_id)
            return

        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")

        if is_known_channel_command(text):
            msg_type = InboundMessageType.COMMAND
        else:
            msg_type = InboundMessageType.CHAT

        # topic_id: use thread_ts as the topic identifier.
        # For threaded messages, thread_ts is the root message ts (shared topic).
        # For non-threaded messages, thread_ts is the message's own ts (new topic).
        inbound = self._make_inbound(
            chat_id=channel_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            metadata={
                # team_id is already resolved (payload team_id/team, else event team) by the caller.
                "team_id": team_id,
                "message_id": event.get("ts"),
                "client_msg_id": event.get("client_msg_id"),
            },
        )
        inbound.topic_id = thread_ts

        if self._loop and self._loop.is_running():
            # Acknowledge with an eyes reaction
            self._add_reaction(channel_id, event.get("ts", thread_ts), "eyes")
            # Send "running" reply first (fire-and-forget from SDK thread)
            self._send_running_reply(channel_id, thread_ts)
            if self._connection_repo is None:
                asyncio.run_coroutine_threadsafe(self.bus.publish_inbound(inbound), self._loop)
            else:
                asyncio.run_coroutine_threadsafe(self._publish_inbound_with_connection(inbound, team_id=team_id), self._loop)

    async def _publish_inbound_with_connection(self, inbound, *, team_id: str | None = None) -> None:
        inbound = await self._attach_connection_identity(inbound, team_id=team_id)
        await self.bus.publish_inbound(inbound)

    async def _attach_connection_identity(self, inbound, *, team_id: str | None = None):
        workspace_id = str(team_id or inbound.metadata.get("team_id") or "")
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="slack",
            workspace_id=workspace_id,
        )

    async def _bind_connection_from_connect_code(self, *, event: dict, team_id: str, code: str) -> bool:
        if self._connection_repo is None or not code:
            return False

        channel_id = str(event.get("channel") or "")
        thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
        state = await self._connection_repo.consume_oauth_state(provider="slack", state=code)
        if state is None:
            await self._post_connection_reply(channel_id, "Slack connection code is invalid or expired.", thread_ts)
            return True

        user_id = str(event.get("user") or "")
        if not user_id or not team_id:
            await self._post_connection_reply(channel_id, "Slack connection could not be completed from this message.", thread_ts)
            return True

        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="slack",
            external_account_id=user_id,
            workspace_id=team_id,
            metadata={
                "team_id": team_id,
                "channel_id": channel_id,
            },
            status="connected",
        )
        await self._post_connection_reply(channel_id, "Slack connected to DeerFlow.", thread_ts)
        return True

    async def _post_connection_reply(self, channel_id: str, text: str, thread_ts: str | None = None) -> None:
        if not self._web_client or not channel_id:
            return
        kwargs: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        try:
            await asyncio.to_thread(self._web_client.chat_postMessage, **kwargs)
        except Exception:
            logger.exception("[Slack] failed to send connection reply in channel=%s", channel_id)
