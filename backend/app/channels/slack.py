"""Slack channel — connects via Socket Mode (no public IP needed)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from markdown_to_mrkdwn import SlackMarkdownConverter

from app.channels.allowed_users import parse_allowed_users, parse_string_or_int_user_id
from app.channels.base import Channel, ChannelStopTimeout
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import (
    INBOUND_FILE_CONTENT_KEY,
    InboundMessage,
    InboundMessageType,
    InboundReservation,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)
from deerflow.uploads.manager import is_upload_staging_file, normalize_filename

logger = logging.getLogger(__name__)
SLACK_STOP_TIMEOUT_SECONDS = 5.0
# Match the manager's URL download ceiling. Slack workspace limits may be higher;
# this keeps a single upload from exhausting Gateway memory.
SLACK_MAX_INBOUND_FILE_BYTES = 50 * 1024 * 1024
# Cap total in-memory bytes for one file_share message (N files × per-file max).
SLACK_MAX_INBOUND_MESSAGE_BYTES = SLACK_MAX_INBOUND_FILE_BYTES
# Private download URLs are Slack-hosted; gate Bearer fetches to this suffix.
SLACK_ALLOWED_FILE_HOST_SUFFIXES = frozenset({"files.slack.com"})
# User-authored subtypes we still want to turn into chat turns. Everything else
# (edits, deletes, joins, bot_message, thread_broadcast, …) stays ignored so we
# do not double-fire or treat platform noise as a user message.
_SLACK_ACCEPTED_MESSAGE_SUBTYPES = frozenset({"file_share"})

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


def _parse_allowed_users(allowed_users: Any) -> frozenset[str] | None:
    """Parse Slack user IDs with the shared fail-closed allowlist semantics."""
    return parse_allowed_users(
        allowed_users,
        parse_user_id=parse_string_or_int_user_id,
        logger=logger,
        channel_name="Slack",
        expected_id="a Slack user ID such as U123456",
        warn_on_scalar_separators=True,
    )


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


def _unescape_slack_text(text: str) -> str:
    """Decode the three entities Slack escapes in message text.

    Slack sends a user-typed ``&``, ``<`` and ``>`` as ``&amp;``, ``&lt;`` and
    ``&gt;`` so that raw ``<...>`` always marks a control sequence (mention,
    link). ``&amp;`` is decoded last so an escaped entity is decoded only once.
    """
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


class SlackChannel(Channel):
    """Slack IM channel using Socket Mode (WebSocket, no public IP).

    Configuration keys (in ``config.yaml`` under ``channels.slack``):
        - ``bot_token``: Slack Bot User OAuth Token (xoxb-...).
        - ``app_token``: Slack App-Level Token (xapp-...) for Socket Mode.
        - ``allowed_users``: (optional) List of allowed Slack user IDs, or a
          single Slack user ID as shorthand. Unset, empty or blank = allow
          all. A non-empty value without a valid ID denies everyone.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="slack", bus=bus, config=config)
        self._socket_client = None
        self._socket_connect_future: asyncio.Future[None] | None = None
        self._socket_close_task: asyncio.Task[None] | None = None
        self._web_client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._allowed_users = _parse_allowed_users(config.get("allowed_users"))
        self._web_client_factory = config.get("web_client_factory")
        self._connection_web_clients: dict[str, tuple[str, Any]] = {}
        configured_bot_user_id = config.get("bot_user_id")
        self._bot_user_id = str(configured_bot_user_id).lstrip("@") if configured_bot_user_id else None

    async def start(self) -> None:
        if self._running:
            return
        if self._socket_client is not None or self._socket_close_task is not None:
            # A timed-out or cancelled stop still owns its SDK work. Reuse its
            # bounded wait rather than replacing a client that can still dial.
            await self.stop()

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

        self._open_threadsafe_future_intake()
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # Start socket mode in a background thread.
        # ``_connect_socket_mode`` logs startup failures. Retain the future so
        # stop() can wait for an in-flight dial before closing its socket.
        socket_client = self._socket_client
        self._socket_connect_future = asyncio.get_event_loop().run_in_executor(None, self._connect_socket_mode, socket_client)
        logger.info("Slack channel started")

    def _connect_socket_mode(self, socket_client: Any) -> None:
        """Connect one start attempt's Socket Mode client if it is still current.

        Mirrors the Telegram and Discord channels, whose background threads log
        their errors instead of letting them vanish with the thread.
        """
        if not self._running or socket_client is not self._socket_client:
            return
        try:
            socket_client.connect()
        except Exception:
            logger.exception("[Slack] Socket Mode connection failed; the channel will not receive events")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        await self._close_and_drain_threadsafe_futures()
        # The SDK can publish a session after close() if connect() is already
        # waiting for its URL. One owned task drains that connect and then
        # closes off-loop. A timeout or cancellation keeps it available for
        # retry; cancelling an executor future would not stop its thread.
        if self._socket_close_task is None and self._socket_client is not None:
            self._socket_close_task = asyncio.create_task(self._close_socket_client(self._socket_client, self._socket_connect_future))
        close_task = self._socket_close_task
        if close_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(close_task), timeout=SLACK_STOP_TIMEOUT_SECONDS)
            except TimeoutError as exc:
                if close_task.done():
                    close_task.result()
                else:
                    raise ChannelStopTimeout("Slack Socket Mode cleanup is still running") from exc
            finally:
                if close_task.done() and self._socket_close_task is close_task:
                    self._socket_close_task = None
        logger.info("Slack channel stopped")

    async def _close_socket_client(self, socket_client: Any, connect_future: asyncio.Future[None] | None) -> None:
        if connect_future is not None:
            await asyncio.shield(connect_future)
        await asyncio.to_thread(socket_client.close)
        if self._socket_client is socket_client:
            self._socket_client = None
        if self._socket_connect_future is connect_future:
            self._socket_connect_future = None

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

    async def _web_client_for_connection(self, connection_id: str | None):
        """Resolve a WebClient for *connection_id*, falling back to the operator client.

        WebClient keeps its own HTTP session and rate-limit state, so reuse one
        per connection until its token changes. Shared by outbound sends and
        inbound private-file downloads so the cache cannot drift.
        """
        if connection_id and self._connection_repo is not None:
            credentials = await self._connection_repo.get_credentials(connection_id)
            access_token = credentials.get("access_token") if credentials else None
            if not access_token:
                return self._web_client
            cached = self._connection_web_clients.get(connection_id)
            if cached is not None and cached[0] == access_token:
                return cached[1]
            if self._web_client_factory is None:
                from slack_sdk import WebClient

                self._web_client_factory = WebClient
            web_client = self._web_client_factory(token=access_token)
            self._connection_web_clients[connection_id] = (access_token, web_client)
            return web_client
        return self._web_client

    async def _get_web_client_for_message(self, msg: OutboundMessage):
        return await self._web_client_for_connection(msg.connection_id)

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
        if not self._running:
            return
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
        # Ignore bot traffic and platform subtypes we do not handle as chat.
        # file_share is a user upload (optional caption + files[]) and must not
        # be dropped just because Slack sets subtype.
        subtype = event.get("subtype")
        if event.get("bot_id") or (subtype and subtype not in _SLACK_ACCEPTED_MESSAGE_SUBTYPES):
            return

        user_id = event.get("user", "")

        text = event.get("text", "").strip()
        if event.get("type") == "app_mention":
            text = _strip_leading_slack_bot_mention(text, self._bot_user_id)
        # Decode after mention stripping: a real mention is a raw <@...>, while
        # a user-typed "<@...>" arrives as &lt;@...&gt; and must stay text.
        text = _unescape_slack_text(text)
        files = self._extract_inbound_files(event)
        if not text and not files:
            return

        connect_code = self._pending_connect_code(text)
        if connect_code:
            if self._loop and self._loop.is_running():
                scheduled = self._submit_threadsafe_coroutine(
                    self._bind_connection_from_connect_code(
                        event=event,
                        team_id=str(team_id or ""),
                        code=connect_code,
                    ),
                    self._loop,
                    name="bind_connection",
                    msg_id=event.get("ts"),
                )
                if not scheduled:
                    logger.info("[Slack] main loop stopped before channel connection bind could be scheduled")
            return

        # Check allowed users after connect-code handling so browser-initiated
        # binding can bootstrap a new external identity.
        if self._allowed_users is not None and user_id not in self._allowed_users:
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
            files=files,
            metadata={
                # team_id is already resolved (payload team_id/team, else event team) by the caller.
                "team_id": team_id,
                "message_id": event.get("ts"),
                "client_msg_id": event.get("client_msg_id"),
            },
        )
        inbound.topic_id = thread_ts

        if self._loop and self._loop.is_running():
            reservation = self._reserve_inbound(inbound)
            if reservation is None:
                return
            # Acknowledge with an eyes reaction
            self._add_reaction(channel_id, event.get("ts", thread_ts), "eyes")
            # Send "running" reply first (fire-and-forget from SDK thread)
            self._send_running_reply(channel_id, thread_ts)
            try:
                if self._connection_repo is None:
                    # Reservation bounds callbacks scheduled from the SDK
                    # thread; no coroutine/Future waits for queue capacity.
                    self._loop.call_soon_threadsafe(self._commit_reserved_inbound, reservation, inbound)
                else:
                    scheduled = self._submit_threadsafe_coroutine(
                        self._publish_inbound_with_connection(inbound, reservation=reservation, team_id=team_id),
                        self._loop,
                        name="publish_inbound",
                        msg_id=event.get("ts", thread_ts),
                        reservation=reservation,
                    )
                    if not scheduled:
                        logger.info("[Slack] main loop stopped before reserved inbound could be scheduled")
            except RuntimeError:
                reservation.release()
                logger.info("[Slack] main loop stopped before reserved inbound could be scheduled")

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        """Download inbound Slack file_share attachments for the shared upload pipeline.

        Slack private download URLs require the bot token in an Authorization
        header, so this adapter never hands those URLs to the generic HTTP
        reader. Bytes cross to ``ChannelManager`` through
        ``INBOUND_FILE_CONTENT_KEY`` (same shape as Telegram).
        """
        del thread_id, user_id
        if not msg.files:
            return msg

        web_client = await self._get_web_client_for_inbound(msg)
        token = getattr(web_client, "token", None) if web_client is not None else None
        if not isinstance(token, str) or not token:
            notice = "[Slack attachment unavailable: bot token missing]"
            msg.text = f"{msg.text}\n\n{notice}" if msg.text else notice
            msg.files = []
            return msg

        materialized: list[dict[str, Any]] = []
        unavailable: list[str] = []
        materialized_bytes = 0

        for file_info in msg.files:
            if not isinstance(file_info, dict):
                continue

            filename = self._safe_inbound_filename(file_info.get("filename"), "attachment")
            declared_size = self._file_size(file_info.get("size"))
            if declared_size is not None and declared_size > SLACK_MAX_INBOUND_FILE_BYTES:
                logger.warning("[Slack] inbound file exceeds download limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the download limit)")
                continue
            if declared_size is not None and materialized_bytes + declared_size > SLACK_MAX_INBOUND_MESSAGE_BYTES:
                logger.warning("[Slack] inbound message exceeds aggregate download limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the message download limit)")
                continue

            url = file_info.get("url_private_download")
            if not isinstance(url, str) or not url.strip():
                logger.error("[Slack] cannot download inbound file without url_private_download: %s", filename)
                unavailable.append(f"{filename} (download unavailable)")
                continue

            url = url.strip()
            if not self._is_allowed_private_file_url(url):
                logger.warning("[Slack] inbound file URL host is not allowlisted, skipping: %s", filename)
                unavailable.append(f"{filename} (download unavailable)")
                continue

            remaining_budget = SLACK_MAX_INBOUND_MESSAGE_BYTES - materialized_bytes
            per_file_cap = min(SLACK_MAX_INBOUND_FILE_BYTES, remaining_budget)
            if per_file_cap <= 0:
                logger.warning("[Slack] inbound message aggregate download budget exhausted, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the message download limit)")
                continue

            try:
                content = await self._download_private_file(url, token, max_bytes=per_file_cap)
            except Exception as exc:
                logger.error(
                    "[Slack] failed to download inbound file %s: %s",
                    filename,
                    type(exc).__name__,
                )
                unavailable.append(f"{filename} (download failed)")
                continue

            if content is None:
                # Stream aborted for size; encoding refusals raise above.
                unavailable.append(f"{filename} (exceeds the download limit)")
                continue

            if len(content) > SLACK_MAX_INBOUND_FILE_BYTES:
                logger.warning("[Slack] downloaded inbound file exceeds limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the download limit)")
                continue
            if materialized_bytes + len(content) > SLACK_MAX_INBOUND_MESSAGE_BYTES:
                logger.warning("[Slack] downloaded inbound file exceeds aggregate message limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the message download limit)")
                continue

            materialized.append(
                {
                    "type": "image" if file_info.get("type") == "image" else "file",
                    "filename": filename,
                    "mime_type": file_info.get("mime_type") if isinstance(file_info.get("mime_type"), str) else "application/octet-stream",
                    "size": len(content),
                    INBOUND_FILE_CONTENT_KEY: content,
                }
            )
            materialized_bytes += len(content)

        msg.files = materialized
        if unavailable:
            notice = f"[Slack attachment unavailable: {', '.join(unavailable)}]"
            msg.text = f"{msg.text}\n\n{notice}" if msg.text else notice
        return msg

    async def _get_web_client_for_inbound(self, msg: InboundMessage):
        """Resolve the WebClient whose token can fetch private Slack files."""
        return await self._web_client_for_connection(msg.connection_id)

    @classmethod
    def _is_allowed_private_file_url(cls, url: str) -> bool:
        """Gate Bearer downloads to https://*.files.slack.com (and the bare host)."""
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        if parsed.scheme != "https":
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        return any(host == suffix or host.endswith(f".{suffix}") for suffix in SLACK_ALLOWED_FILE_HOST_SUFFIXES)

    async def _download_private_file(self, url: str, token: str, *, max_bytes: int = SLACK_MAX_INBOUND_FILE_BYTES) -> bytes | None:
        """Stream a Slack private file URL with Bearer auth; never log the URL.

        Returns ``None`` only when the streamed body exceeds *max_bytes*.
        A non-identity ``Content-Encoding`` raises so callers can report
        ``(download failed)`` instead of a misleading size-limit notice.
        """
        chunks: list[bytes] = []
        total = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            async with client.stream(
                "GET",
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                response.raise_for_status()
                encoding = (response.headers.get("content-encoding") or "").strip().lower()
                if encoding and encoding != "identity":
                    logger.warning(
                        "[Slack] inbound file response uses Content-Encoding %r, dropping before decode",
                        encoding,
                    )
                    raise RuntimeError(f"unsupported content-encoding: {encoding}")
                async for chunk in response.aiter_raw():
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning(
                            "[Slack] inbound file exceeds %d bytes download limit, dropping",
                            max_bytes,
                        )
                        return None
                    chunks.append(chunk)
        return b"".join(chunks)

    @classmethod
    def _extract_inbound_files(cls, event: dict) -> list[dict[str, Any]]:
        """Build token-free file descriptors from a Slack message event."""
        raw_files = event.get("files")
        if not isinstance(raw_files, list):
            return []

        files: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_files):
            if not isinstance(raw, dict):
                continue
            download_url = raw.get("url_private_download") or raw.get("url_private")
            if not isinstance(download_url, str) or not download_url.strip():
                continue
            file_id = raw.get("id")
            mime_type = raw.get("mimetype")
            if not isinstance(mime_type, str) or not mime_type:
                mime_type = "application/octet-stream"
            fallback = f"slack-file-{file_id if isinstance(file_id, str) and file_id else index}.bin"
            filename = cls._safe_inbound_filename(raw.get("name") or raw.get("title"), fallback)
            is_image = mime_type.startswith("image/") or str(raw.get("filetype") or "").lower() in {
                "png",
                "jpg",
                "jpeg",
                "gif",
                "webp",
                "bmp",
            }
            files.append(
                {
                    "type": "image" if is_image else "file",
                    "file_id": file_id if isinstance(file_id, str) else None,
                    "filename": filename,
                    "mime_type": mime_type,
                    "size": cls._file_size(raw.get("size")),
                    # Private URL only — Authorization is attached in receive_file.
                    "url_private_download": download_url.strip(),
                }
            )
        return files

    @staticmethod
    def _safe_inbound_filename(value: Any, fallback: str) -> str:
        if not isinstance(value, str):
            return fallback
        try:
            candidate = normalize_filename(value.strip())
        except (UnicodeError, ValueError):
            return fallback
        if is_upload_staging_file(candidate) or any(ord(char) < 32 for char in candidate):
            return fallback
        return candidate

    @staticmethod
    def _file_size(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float) and value.is_integer() and value >= 0:
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    async def _publish_inbound_with_connection(
        self,
        inbound,
        *,
        reservation: InboundReservation,
        team_id: str | None = None,
    ) -> None:
        try:
            inbound = await self._attach_connection_identity(inbound, team_id=team_id)
            self._commit_reserved_inbound(reservation, inbound)
        finally:
            reservation.release()

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
