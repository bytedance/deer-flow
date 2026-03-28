"""DingTalk channel — connects via Stream Push WebSocket (no public IP needed)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.parse
from typing import Any

import httpx

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

# DingTalk API endpoints
DINGTALK_API_BASE = "https://api.dingtalk.com"
DINGTALK_AUTH_BASE = "https://oapi.dingtalk.com"


class DingTalkChannel(Channel):
    """DingTalk IM channel using Stream Push (WebSocket, no public IP).

    Configuration keys (in ``config.yaml`` under ``channels.dingtalk``):
        - ``app_key``: DingTalk app key (AppKey).
        - ``app_secret``: DingTalk app secret (AppSecret).
        - ``allowed_users``: (optional) List of allowed DingTalk user IDs. Empty = allow all.

    The channel uses DingTalk Stream Push (WebSocket) so no public IP is required.

    Message flow:
        1. User sends a message → bot adds reaction (if supported)
        2. Bot replies in thread: "Working on it..."
        3. Agent processes the message and returns a result
        4. Bot replies in thread with the result
        5. Bot adds completion reaction

    Setup:
        1. Create an app on DingTalk Open Platform (https://open.dingtalk.com/)
        2. Enable "Stream Push" capability for the app
        3. Add permissions: `im:message`, `im:message.p2p_msg:readonly`, `im:chat:readonly`
        4. Subscribe to message events
        5. Set `DINGTALK_APP_KEY` and `DINGTALK_APP_SECRET` in `.env`
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="dingtalk", bus=bus, config=config)
        self._thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._allowed_users: set[str] = set(config.get("allowed_users", []))
        self._ws_client = None
        self._background_tasks: set[asyncio.Task] = set()
        # Track running status messages for each conversation
        self._running_messages: dict[str, str] = {}
        # Lock for token refresh
        self._token_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            return

        app_key = self.config.get("app_key", "")
        app_secret = self.config.get("app_secret", "")

        if not app_key or not app_secret:
            logger.error("DingTalk channel requires app_key and app_secret")
            return

        self._app_key = app_key
        self._app_secret = app_secret
        self._main_loop = asyncio.get_event_loop()

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # Start Stream Push client in a dedicated thread
        self._thread = threading.Thread(
            target=self._run_stream_push,
            args=(app_key, app_secret),
            daemon=True,
        )
        self._thread.start()
        logger.info("DingTalk channel started")

    def _run_stream_push(self, app_key: str, app_secret: str) -> None:
        """Run DingTalk Stream Push client in a dedicated thread."""
        try:
            # Try to use the official dingtalk-stream SDK
            try:
                from dingtalk_stream import AckMessage, DingTalkStreamClient, Event, EventAck

                self._run_official_stream_client(app_key, app_secret)
            except ImportError:
                logger.warning("dingtalk-stream not installed, falling back to custom WebSocket client")
                self._run_custom_ws_client(app_key, app_secret)
        except Exception:
            if self._running:
                logger.exception("DingTalk Stream Push error")

    def _run_official_stream_client(self, app_key: str, app_secret: str) -> None:
        """Run the official dingtalk-stream SDK client."""
        from dingtalk_stream import AckMessage, DingTalkStreamClient, Event, EventAck

        def on_message(event: Event) -> EventAck:
            """Handle incoming message from Stream Push."""
            try:
                # Schedule the async handler on the main loop
                if self._main_loop and self._main_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._handle_message_event(event),
                        self._main_loop,
                    )
                    # Wait for the result with a timeout
                    future.result(timeout=30)
                return EventAck.SUCCESS
            except Exception:
                logger.exception("Error handling DingTalk message event")
                return EventAck.FAILURE

        # Create and start the Stream Push client
        client = DingTalkStreamClient(app_key, app_secret)
        client.register_message_handler(on_message)

        # This call blocks until the connection is closed
        client.start()

    def _run_custom_ws_client(self, app_key: str, app_secret: str) -> None:
        """Fallback: Run a custom WebSocket client for Stream Push."""
        import asyncio
        import json

        import websockets

        async def connect_stream():
            """Connect to DingTalk Stream Push WebSocket."""
            # Get the WebSocket URL
            ws_url = await self._get_stream_url(app_key, app_secret)
            if not ws_url:
                logger.error("Failed to get DingTalk Stream Push URL")
                return

            async with websockets.connect(ws_url) as ws:
                logger.info("[DingTalk] Connected to Stream Push WebSocket")
                async for message in ws:
                    if not self._running:
                        break
                    try:
                        data = json.loads(message)
                        await self._handle_ws_message(data, ws)
                    except Exception:
                        logger.exception("Error processing WebSocket message")

        # Run the async WebSocket connection
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(connect_stream())
        finally:
            loop.close()

    async def _get_stream_url(self, app_key: str, app_secret: str) -> str | None:
        """Get the WebSocket URL for Stream Push."""
        try:
            async with httpx.AsyncClient() as client:
                # Get access token first
                token = await self._get_access_token()
                if not token:
                    return None

                # Register for Stream Push
                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/gateway/connections/openapi/registrations",
                    headers={"x-acs-dingtalk-access-token": token},
                    json={
                        "client_id": app_key,
                        "client_secret": app_secret,
                        "subscription": {
                            "type": "EVENT_CALL_BACK",
                            "events": ["im.message.receive_v1"],
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data.get("endpoint")
        except Exception:
            logger.exception("Failed to get DingTalk Stream Push URL")
            return None

    async def _handle_ws_message(self, data: dict, ws) -> None:
        """Handle a WebSocket message from DingTalk Stream Push."""
        try:
            msg_type = data.get("type")
            if msg_type == "EVENT":
                event = data.get("data", {})
                await self._handle_message_event_raw(event)
                # Acknowledge the event
                await ws.send(json.dumps({"type": "ACK", "id": data.get("id")}))
        except Exception:
            logger.exception("Error handling WebSocket message")

    async def _handle_message_event(self, event) -> None:
        """Handle a message event from the official SDK."""
        try:
            # Extract message data from the event
            event_data = json.loads(event.data) if isinstance(event.data, str) else event.data
            await self._handle_message_event_raw(event_data)
        except Exception:
            logger.exception("Error handling message event from SDK")

    async def _handle_message_event_raw(self, event_data: dict) -> None:
        """Handle raw message event data."""
        try:
            message = event_data.get("message", {})
            sender = event_data.get("sender", {})
            chat = event_data.get("chat", {})

            chat_id = chat.get("chatId", "")
            user_id = sender.get("userId", "")
            msg_id = message.get("messageId", "")

            # Check allowed users
            if self._allowed_users and user_id not in self._allowed_users:
                logger.debug("[DingTalk] Ignoring message from non-allowed user: %s", user_id)
                return

            # Parse message content
            content_type = message.get("msgType", "")
            content = message.get("content", {})

            if content_type == "text":
                text = content.get("content", "").strip()
            elif content_type == "richText":
                # Rich text messages
                text = self._parse_rich_text(content)
            elif content_type == "picture":
                text = "[Image]"
            elif content_type == "file":
                text = f"[File: {content.get('fileName', 'unknown')}]"
            else:
                text = f"[{content_type}]"

            if not text:
                logger.info("[DingTalk] Empty text content, ignoring message")
                return

            logger.info(
                "[DingTalk] parsed message: chat_id=%s, msg_id=%s, sender=%s, text=%r",
                chat_id,
                msg_id,
                user_id,
                text[:100] if text else "",
            )

            # Determine message type
            if text.startswith("/"):
                msg_type = InboundMessageType.COMMAND
            else:
                msg_type = InboundMessageType.CHAT

            # topic_id: use conversation ID for thread grouping
            # For 1-on-1 chats, use chat_id; for group chats, use the message's conversationId
            topic_id = chat_id

            inbound = self._make_inbound(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                msg_type=msg_type,
                thread_ts=msg_id,
                metadata={"message_id": msg_id, "chat_type": chat.get("chatType", "single")},
            )
            inbound.topic_id = topic_id

            # Send running reply
            await self._send_running_reply(chat_id, msg_id)

            # Publish to the message bus
            logger.info("[DingTalk] publishing inbound message to bus (type=%s, msg_id=%s)", msg_type.value, msg_id)
            await self.bus.publish_inbound(inbound)

        except Exception:
            logger.exception("Error handling DingTalk message event")

    def _parse_rich_text(self, content: dict) -> str:
        """Parse DingTalk rich text content into plain text."""
        text_parts = []
        rich_text_parts = content.get("richTextContent", [])
        for part in rich_text_parts:
            part_type = part.get("type", "")
            if part_type == "text":
                text_parts.append(part.get("text", ""))
            elif part_type == "mention":
                text_parts.append(part.get("text", ""))
            elif part_type == "link":
                text_parts.append(part.get("text", ""))
        return " ".join(text_parts).strip()

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        for task in list(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._ws_client = None
        logger.info("DingTalk channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        """Send a message to DingTalk."""
        if not msg.text:
            return

        token = await self._get_access_token()
        if not token:
            logger.error("[DingTalk] No access token available")
            return

        logger.info(
            "[DingTalk] sending reply: chat_id=%s, thread_ts=%s, text_len=%d",
            msg.chat_id,
            msg.thread_ts,
            len(msg.text),
        )

        last_exc: Exception | None = None
        for attempt in range(_max_retries):
            try:
                if msg.thread_ts:
                    # Reply in thread
                    await self._reply_message(token, msg.chat_id, msg.thread_ts, msg.text, msg.is_final)
                else:
                    # Send new message
                    await self._send_message(token, msg.chat_id, msg.text)

                # Clear running message tracking on final message
                if msg.is_final and msg.thread_ts:
                    self._running_messages.pop(msg.thread_ts, None)

                return
            except Exception as exc:
                last_exc = exc
                if attempt < _max_retries - 1:
                    delay = 2**attempt
                    logger.warning(
                        "[DingTalk] send failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        _max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("[DingTalk] send failed after %d attempts: %s", _max_retries, last_exc)
        raise last_exc

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """Send a file attachment to DingTalk."""
        if not attachment:
            return False

        token = await self._get_access_token()
        if not token:
            logger.warning("[DingTalk] No access token for file upload")
            return False

        # DingTalk file size limits
        if attachment.size > 20 * 1024 * 1024:  # 20MB limit
            logger.warning("[DingTalk] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        try:
            if attachment.is_image:
                return await self._send_image(token, msg.chat_id, attachment, msg.thread_ts)
            else:
                return await self._send_file(token, msg.chat_id, attachment, msg.thread_ts)
        except Exception:
            logger.exception("[DingTalk] failed to upload/send file: %s", attachment.filename)
            return False

    # -- DingTalk API methods -----------------------------------------------

    async def _get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary."""
        async with self._token_lock:
            now = time.time()
            # Refresh if token is expired or will expire in the next 5 minutes
            if self._access_token and now < self._token_expires_at - 300:
                return self._access_token

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{DINGTALK_AUTH_BASE}/gettoken",
                        params={"appkey": self._app_key, "appsecret": self._app_secret},
                    )
                    response.raise_for_status()
                    data = response.json()
                    if data.get("errcode", 0) != 0:
                        logger.error("[DingTalk] Failed to get access token: %s", data)
                        return None

                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 7200)
                    self._token_expires_at = now + expires_in
                    logger.info("[DingTalk] Access token refreshed, expires in %d seconds", expires_in)
                    return self._access_token
            except Exception:
                logger.exception("[DingTalk] Error getting access token")
                return None

    async def _send_message(self, token: str, chat_id: str, text: str) -> None:
        """Send a text message to a chat."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/robot/oToMessages/batchSend",
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                json={
                    "msgKey": "sampleText",
                    "msgParam": json.dumps({"content": text}),
                    "receiveUserIds": [chat_id],
                },
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "0":
                logger.warning("[DingTalk] Message send returned non-zero code: %s", data)

    async def _reply_message(
        self, token: str, chat_id: str, msg_id: str, text: str, is_final: bool
    ) -> None:
        """Reply to a message in thread."""
        # Check if we have a running message to update
        running_msg_id = self._running_messages.get(msg_id)

        async with httpx.AsyncClient() as client:
            if running_msg_id and not is_final:
                # Update existing running message (if supported)
                # DingTalk doesn't support message updates, so we just send a new message
                pass

            # Send reply
            response = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                headers={
                    "x-acs-dingtalk-access-token": token,
                    "Content-Type": "application/json",
                },
                json={
                    "msgKey": "sampleText",
                    "msgParam": json.dumps({"content": text}),
                    "openConversationId": chat_id,
                    "replyToMsgId": msg_id,
                },
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "0":
                logger.warning("[DingTalk] Reply send returned non-zero code: %s", data)

    async def _send_running_reply(self, chat_id: str, msg_id: str) -> None:
        """Send a 'Working on it...' reply."""
        token = await self._get_access_token()
        if not token:
            return

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                    headers={
                        "x-acs-dingtalk-access-token": token,
                        "Content-Type": "application/json",
                    },
                    json={
                        "msgKey": "sampleText",
                        "msgParam": json.dumps({"content": "⏳ Working on it..."}),
                        "openConversationId": chat_id,
                        "replyToMsgId": msg_id,
                    },
                )
                response.raise_for_status()
                data = response.json()
                logger.info("[DingTalk] 'Working on it...' reply sent in chat=%s", chat_id)

                # Track the running message ID if returned
                if data.get("code") == "0" and data.get("processQueryKeys"):
                    self._running_messages[msg_id] = data["processQueryKeys"][0]
        except Exception:
            logger.exception("[DingTalk] failed to send running reply in chat=%s", chat_id)

    async def _send_image(
        self, token: str, chat_id: str, attachment: ResolvedAttachment, reply_to: str | None
    ) -> bool:
        """Send an image to DingTalk."""
        try:
            # Upload the image first
            media_id = await self._upload_media(token, attachment.actual_path, "image")
            if not media_id:
                return False

            async with httpx.AsyncClient() as client:
                body = {
                    "msgKey": "sampleImageMsg",
                    "msgParam": json.dumps({"photoURL": media_id}),
                    "openConversationId": chat_id,
                }
                if reply_to:
                    body["replyToMsgId"] = reply_to

                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                    headers={
                        "x-acs-dingtalk-access-token": token,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                success = data.get("code") == "0"
                if success:
                    logger.info("[DingTalk] image sent: %s to chat=%s", attachment.filename, chat_id)
                return success
        except Exception:
            logger.exception("[DingTalk] failed to send image")
            return False

    async def _send_file(
        self, token: str, chat_id: str, attachment: ResolvedAttachment, reply_to: str | None
    ) -> bool:
        """Send a file to DingTalk."""
        try:
            # Upload the file first
            media_id = await self._upload_media(token, attachment.actual_path, "file")
            if not media_id:
                return False

            async with httpx.AsyncClient() as client:
                body = {
                    "msgKey": "sampleFileMsg",
                    "msgParam": json.dumps({
                        "fileUrl": media_id,
                        "fileName": attachment.filename,
                        "fileSize": attachment.size,
                    }),
                    "openConversationId": chat_id,
                }
                if reply_to:
                    body["replyToMsgId"] = reply_to

                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                    headers={
                        "x-acs-dingtalk-access-token": token,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
                success = data.get("code") == "0"
                if success:
                    logger.info("[DingTalk] file sent: %s to chat=%s", attachment.filename, chat_id)
                return success
        except Exception:
            logger.exception("[DingTalk] failed to send file")
            return False

    async def _upload_media(self, token: str, file_path, media_type: str) -> str | None:
        """Upload media to DingTalk and return the media_id."""
        try:
            async with httpx.AsyncClient() as client:
                with open(file_path, "rb") as f:
                    response = await client.post(
                        f"{DINGTALK_API_BASE}/v1.0/files/upload",
                        headers={
                            "x-acs-dingtalk-access-token": token,
                        },
                        files={"file": f},
                        data={"type": media_type},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return data.get("mediaId")
        except Exception:
            logger.exception("[DingTalk] failed to upload media")
            return None

    def _track_background_task(self, task: asyncio.Task, *, name: str, msg_id: str) -> None:
        """Keep a strong reference to fire-and-forget tasks and surface errors."""
        self._background_tasks.add(task)
        task.add_done_callback(
            lambda done_task, task_name=name, mid=msg_id: self._finalize_background_task(
                done_task, task_name, mid
            )
        )

    def _finalize_background_task(self, task: asyncio.Task, name: str, msg_id: str) -> None:
        self._background_tasks.discard(task)
        self._log_task_error(task, name, msg_id)

    @staticmethod
    def _log_task_error(task: asyncio.Task, name: str, msg_id: str) -> None:
        """Callback for background asyncio tasks to surface errors."""
        try:
            exc = task.exception()
            if exc:
                logger.error("[DingTalk] %s failed for msg_id=%s: %s", name, msg_id, exc)
        except asyncio.CancelledError:
            logger.info("[DingTalk] %s cancelled for msg_id=%s", name, msg_id)
        except Exception:
            pass