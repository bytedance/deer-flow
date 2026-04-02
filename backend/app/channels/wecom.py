from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

try:
    import ujson as json

    _json_available = True
except ImportError:
    import json

    _json_available = False

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage

logger = logging.getLogger(__name__)


class WeComHTTPClient:
    """WeCom HTTP API client for sending and updating messages.

    Supports two modes:
    1. Self-built app mode: corpid + corpsecret + agentid
    2. Bot mode: bot_secret (webhook key)
    """

    def __init__(
        self,
        *,
        corpid: str | None = None,
        corpsecret: str | None = None,
        agentid: int | None = None,
        bot_id: str | None = None,
        bot_secret: str | None = None,
    ):
        self.corpid = corpid
        self.corpsecret = corpsecret
        self.agentid = agentid
        self.bot_id = bot_id
        self.bot_secret = bot_secret
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()
        self._base_url = "https://qyapi.weixin.qq.com/cgi-bin"

        # Determine mode: prioritize bot mode if bot_secret is provided
        self._is_bot_mode = bool(bot_secret)
        self._is_app_mode = bool(corpid and corpsecret and agentid is not None)

        if not self._is_bot_mode and not self._is_app_mode:
            raise ValueError("Must provide either (corpid, corpsecret, agentid) or bot_secret")

    async def _get_access_token(self) -> str:
        """Get access token, refresh if expired. Only for app mode."""
        if self._is_bot_mode:
            raise RuntimeError("Bot mode does not use access tokens")

        import aiohttp

        with self._lock:
            if self._access_token and time.time() < self._token_expires_at - 60:
                return self._access_token

            url = f"{self._base_url}/gettoken"
            params = {
                "corpid": self.corpid,
                "corpsecret": self.corpsecret,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    data = await response.json()

            if data.get("errcode") != 0:
                raise RuntimeError(f"Failed to get access token: {data}")

            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + data["expires_in"]
            return self._access_token

    async def send_message(self, touser: str | None = None, toparty: str | None = None, totag: str | None = None, text: str = "", msgtype: str = "markdown") -> str:
        """Send a message and return the message ID."""
        import aiohttp

        if self._is_bot_mode:
            # Bot mode: use webhook endpoint
            url = f"{self._base_url}/webhook/send?key={self.bot_secret}"
            body = {
                "msgtype": msgtype,
            }
            if msgtype == "text":
                body["text"] = {"content": text}
            elif msgtype == "markdown":
                body["markdown"] = {"content": text}
        else:
            # App mode: use message/send endpoint with access token
            access_token = await self._get_access_token()
            url = f"{self._base_url}/message/send?access_token={access_token}"
            body = {
                "msgtype": msgtype,
                "agentid": self.agentid,
            }
            if touser:
                body["touser"] = touser
            if toparty:
                body["toparty"] = toparty
            if totag:
                body["totag"] = totag
            if msgtype == "text":
                body["text"] = {"content": text}
            elif msgtype == "markdown":
                body["markdown"] = {"content": text}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as response:
                data = await response.json()

        if data.get("errcode") != 0:
            raise RuntimeError(f"Failed to send message: {data}")

        return data.get("msgid", str(uuid.uuid4()))

    async def update_message(self, msgid: str, text: str, msgtype: str = "markdown") -> None:
        """Update an existing message. Only supported in app mode."""
        if self._is_bot_mode:
            # Bot mode does not support message updates
            logger.warning("[WeCom] Bot mode does not support message updates, skipping update")
            return

        import aiohttp

        access_token = await self._get_access_token()
        url = f"{self._base_url}/message/update?access_token={access_token}"

        body = {
            "msgid": msgid,
            "msgtype": msgtype,
        }

        if msgtype == "text":
            body["text"] = {"content": text}
        elif msgtype == "markdown":
            body["markdown"] = {"content": text}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as response:
                data = await response.json()

        if data.get("errcode") != 0:
            raise RuntimeError(f"Failed to update message: {data}")


class TTLCache(OrderedDict):
    """Time-to-Live cache that automatically evicts expired entries."""

    def __init__(self, maxsize: int = 1000, ttl: float = 3600.0) -> None:
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._timestamps: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def _evict_expired(self, current_time: float) -> None:
        """Evict all expired entries."""
        expired_keys = []
        for key, timestamp in self._timestamps.items():
            if current_time - timestamp > self.ttl:
                expired_keys.append(key)
            else:
                # Since OrderedDict maintains insertion order, we can break early
                break

        for key in expired_keys:
            super().pop(key, None)
            self._timestamps.pop(key, None)

    def _evict_over_maxsize(self) -> None:
        """Evict oldest entries if over maxsize."""
        while len(self) > self.maxsize:
            oldest_key = next(iter(self))
            super().pop(oldest_key, None)
            self._timestamps.pop(oldest_key, None)

    def __setitem__(self, key: str, value: str) -> None:
        import time

        current_time = time.time()
        with self._lock:
            self._evict_expired(current_time)

            if key in self:
                # Move to end to mark as recently used
                self.move_to_end(key)
                self._timestamps.move_to_end(key)
            else:
                self._evict_over_maxsize()

            super().__setitem__(key, value)
            self._timestamps[key] = current_time

    def __getitem__(self, key: str) -> str:
        import time

        current_time = time.time()
        with self._lock:
            self._evict_expired(current_time)

            value = super().__getitem__(key)
            # Move to end to mark as recently used
            self.move_to_end(key)
            self._timestamps.move_to_end(key)
            return value

    def get(self, key: str, default: str | None = None) -> str | None:
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def pop(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            self._timestamps.pop(key, None)
            return super().pop(key, default)

    def clear(self) -> None:
        with self._lock:
            super().clear()
            self._timestamps.clear()


class WeComChannel(Channel):
    """WeCom (企业微信) IM channel using WebSocket.

    Configuration keys (in ``config.yaml`` under ``channels.wecom``):
        - ``bot_id``: WeCom bot ID (required, for WebSocket and HTTP API bot mode).
        - ``bot_secret``: WeCom bot secret (required, for WebSocket and HTTP API bot mode).
        - ``corpid``: (optional) WeCom corp ID (for HTTP API app mode).
        - ``corpsecret``: (optional) WeCom corp secret (for HTTP API app mode).
        - ``agentid``: (optional) WeCom agent ID (for HTTP API app mode).
        - ``ws_url``: (optional) WebSocket URL, default: wss://openws.work.weixin.qq.com
        - ``heartbeat_interval``: (optional) Heartbeat interval in **seconds** (e.g., 30 for 30 seconds), default: 30 seconds.
           **Backward compatibility**: If value is >= 100, it's treated as milliseconds (old behavior) and converted to seconds.
           **Recommended**: Use seconds (e.g., 30) for clarity.

    The channel uses WebSocket long-connection mode so no public IP is required.
    If ``bot_id`` and ``bot_secret`` are provided (which they always are), it will use
    HTTP API in bot mode for sending/updating messages to support streaming updates.
    If ``corpid``, ``corpsecret``, and ``agentid`` are also provided, it will use
    HTTP API in app mode instead.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="wecom", bus=bus, config=config)
        self._thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None  # Gateway's main loop
        self._ws_loop: asyncio.AbstractEventLoop | None = None  # WebSocket thread's loop
        self._ws: Any = None
        self._background_tasks: set[asyncio.Task] = set()
        self._running_card_ids: dict[str, str] = {}
        self._running_card_tasks: dict[str, asyncio.Task] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_interval: float = 30.0
        self._authenticated = False
        self._msgid_to_req_id: TTLCache = TTLCache(maxsize=1000, ttl=3600.0)
        self._chatid_to_req_id: TTLCache = TTLCache(maxsize=1000, ttl=3600.0)
        # 消息去重缓存：记录每个会话最后发送的内容和时间
        self._last_message: dict[str, tuple[str, float]] = {}
        self._reconnect_delay: float = 3.0
        self._max_reconnect_delay: float = 30.0
        self._ping_frame: str = json.dumps({"cmd": "ping"})
        self._lock = threading.Lock()
        self._http_client: WeComHTTPClient | None = None
        self._source_msgid_to_userid: dict[str, str] = {}
        self._chatid_to_stream_id: dict[str, str] = {}
        self._THINKING_MESSAGE = ""

    async def start(self) -> None:
        if self._running:
            logger.warning("WeCom channel already running, skipping start()")
            return

        self._running = True  # Set early to prevent race conditions

        try:
            import websockets
        except ImportError:
            logger.error("websockets is not installed. Install it with: uv add websockets")
            self._running = False
            return

        self._websockets = websockets

        # Initialize HTTP client if credentials are provided
        # Prioritize bot mode, fallback to app mode
        bot_id = self.config.get("bot_id", "")
        bot_secret = self.config.get("bot_secret", "")
        corpid = self.config.get("corpid", "")
        corpsecret = self.config.get("corpsecret", "")
        agentid = self.config.get("agentid")

        # Try to initialize HTTP client with available credentials
        http_client_kwargs = {}
        if bot_id and bot_secret:
            http_client_kwargs["bot_id"] = bot_id
            http_client_kwargs["bot_secret"] = bot_secret
        if corpid and corpsecret and agentid is not None:
            http_client_kwargs["corpid"] = corpid
            http_client_kwargs["corpsecret"] = corpsecret
            http_client_kwargs["agentid"] = int(agentid)

        if http_client_kwargs:
            try:
                self._http_client = WeComHTTPClient(**http_client_kwargs)
                logger.info("WeCom HTTP API client initialized (streaming updates enabled)")
            except Exception:
                logger.exception("Failed to initialize WeCom HTTP API client")
                self._http_client = None

        bot_id = self.config.get("bot_id", "")
        bot_secret = self.config.get("bot_secret", "")

        if not bot_id or not bot_secret:
            logger.error("WeCom channel requires bot_id and bot_secret")
            self._running = False
            return

        self._main_loop = asyncio.get_event_loop()

        self.bus.subscribe_outbound(self._on_outbound)
        logger.info("WeCom channel subscribed to message bus")

        self._thread = threading.Thread(
            target=self._run_ws,
            args=(bot_id, bot_secret),
            daemon=True,
        )
        self._thread.start()
        logger.info("WeCom channel started")

    def _run_ws(self, bot_id: str, bot_secret: str) -> None:
        """Run the WebSocket client in a dedicated thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ws_loop = loop

        ws_url = self.config.get("ws_url", "wss://openws.work.weixin.qq.com")
        heartbeat_interval_config = self.config.get("heartbeat_interval", 30)

        logger.debug("WeCom configured heartbeat interval: %s", heartbeat_interval_config)

        # Use configured value in seconds, or default to 30
        if isinstance(heartbeat_interval_config, (int, float)):
            heartbeat_interval = float(heartbeat_interval_config)
        else:
            heartbeat_interval = 30.0  # Default 30 seconds

        # Validate heartbeat interval to prevent configuration errors
        if heartbeat_interval < 10.0:
            logger.warning("WeCom heartbeat interval %.1f seconds is too short, using minimum 10 seconds", heartbeat_interval)
            heartbeat_interval = 10.0
        elif heartbeat_interval > 120.0:
            logger.warning("WeCom heartbeat interval %.1f seconds is too long, using maximum 120 seconds (2 minutes)", heartbeat_interval)
            heartbeat_interval = 120.0

        logger.debug("WeCom heartbeat interval after validation: %.2f seconds", heartbeat_interval)

        try:
            loop.run_until_complete(self._ws_main_loop(ws_url, bot_id, bot_secret, heartbeat_interval))
        except Exception:
            if self._running:
                logger.exception("WeCom WebSocket error")

    async def _ws_main_loop(self, ws_url: str, bot_id: str, bot_secret: str, heartbeat_interval: float) -> None:
        """Main WebSocket connection loop."""
        self._heartbeat_interval = heartbeat_interval
        while self._running:
            try:
                logger.info("Connecting to WeCom WebSocket: %s", ws_url)
                async with self._websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
                    self._ws = ws
                    self._authenticated = False
                    self._msgid_to_req_id.clear()
                    self._chatid_to_req_id.clear()
                    self._reconnect_delay = 3.0  # Reset delay on successful connection

                    await self._send_subscribe(bot_id, bot_secret)
                    logger.info("Subscribe frame sent to WeCom")

                    async for message in ws:
                        try:
                            frame = json.loads(message)
                            await self._handle_frame(frame)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON from WeCom: %s", message)
                        except Exception:
                            logger.exception("Error handling WeCom message")
            except self._websockets.exceptions.ConnectionClosed:
                if self._running:
                    logger.warning("WeCom WebSocket disconnected, reconnecting in %.1fs...", self._reconnect_delay)
                    await self._stop_heartbeat()
                    await asyncio.sleep(self._reconnect_delay)
                    # Exponential backoff
                    self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
            except Exception:
                if self._running:
                    logger.exception("WeCom WebSocket error, reconnecting in %.1fs...", self._reconnect_delay)
                    await self._stop_heartbeat()
                    await asyncio.sleep(self._reconnect_delay)
                    # Exponential backoff
                    self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    async def _send_subscribe(self, bot_id: str, bot_secret: str) -> None:
        """Send subscribe (authentication) frame."""
        frame = {
            "cmd": "aibot_subscribe",
            "headers": {
                "req_id": uuid.uuid4().hex,
            },
            "body": {
                "bot_id": bot_id,
                "secret": bot_secret,
            },
        }
        await self._ws.send(json.dumps(frame))

    async def _heartbeat_loop(self, interval: float) -> None:
        """Send periodic heartbeat frames to keep connection alive."""
        logger.debug("WeCom heartbeat loop started with interval: %.3f seconds", interval)
        try:
            while self._running and self._ws:
                # Add jitter: wait interval ± 10% to avoid synchronized heartbeats
                jitter = interval * 0.1
                wait_time = interval + random.uniform(-jitter, jitter)
                actual_wait = max(wait_time, interval * 0.9)  # Ensure at least 90% of interval
                logger.debug("WeCom heartbeat waiting: %.3f seconds", actual_wait)
                await asyncio.sleep(actual_wait)
                if self._ws:
                    try:
                        await self._send_heartbeat()
                    except Exception:
                        logger.debug("Heartbeat failed, connection might be closed")
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Heartbeat loop error")

    async def _send_heartbeat(self) -> None:
        """Send heartbeat frame."""
        await self._ws.send(self._ping_frame)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Sent heartbeat to WeCom")

    async def _stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _handle_frame(self, frame: dict) -> None:
        """Handle incoming WebSocket frame."""
        cmd = frame.get("cmd", "")
        headers = frame.get("headers", {})
        body = frame.get("body", {})
        errcode = frame.get("errcode", 0)
        errmsg = frame.get("errmsg", "")

        if errcode != 0:
            logger.error("WeCom error frame: errcode=%d, errmsg=%s, frame=%s", errcode, errmsg, frame)
            return

        if cmd == "ping":
            await self._handle_ping(headers)
        elif cmd == "aibot_msg_callback":
            await self._handle_message_callback(headers, body)
        elif cmd == "aibot_event_callback":
            await self._handle_event_callback(headers, body)
        elif cmd == "aibot_subscribe":
            await self._handle_subscribe_response(headers, body)
        else:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Unhandled WeCom cmd: %s, frame=%s", cmd, frame)

    async def _handle_ping(self, headers: dict) -> None:
        """Handle ping frame from server."""
        frame = {
            "cmd": "pong",
            "headers": headers,
        }
        await self._ws.send(json.dumps(frame))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Received ping, sent pong to WeCom")

    async def _handle_subscribe_response(self, headers: dict, body: dict) -> None:
        """Handle subscribe response frame."""
        if self._authenticated:
            logger.debug("WeCom authentication response received, already authenticated")
            return
        self._authenticated = True
        logger.info("WeCom authentication successful")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(self._heartbeat_interval))

    async def _handle_message_callback(self, headers: dict, body: dict) -> None:
        """Handle message callback frame."""
        try:
            req_id = headers.get("req_id", "")
            msgid = body.get("msgid", "")
            chatid = body.get("chatid", "")
            chattype = body.get("chattype", "single")
            from_user = body.get("from", {})
            sender_id = from_user.get("userid", "")
            msgtype = body.get("msgtype", "")

            text = ""
            if msgtype == "text":
                text_content = body.get("text", {})
                text = text_content.get("content", "")
            elif msgtype == "mixed":
                mixed_content = body.get("mixed", {})
                msg_item = mixed_content.get("msg_item", mixed_content.get("elements", []))
                text_parts = []
                for item in msg_item:
                    if item.get("msgtype") == "text":
                        text_part = item.get("text", {})
                        text_parts.append(text_part.get("content", ""))
                text = "".join(text_parts)

            text = text.strip()

            logger.info(
                "[WeCom] parsed message: req_id=%s, msgid=%s, chatid=%s, chattype=%s, sender=%s, msgtype=%s, text=%r",
                req_id,
                msgid,
                chatid,
                chattype,
                sender_id,
                msgtype,
                text[:100] if text else "",
            )

            if not text:
                logger.info("[WeCom] empty text, ignoring message")
                return

            if text.startswith("/"):
                msg_type = InboundMessageType.COMMAND
            else:
                msg_type = InboundMessageType.CHAT

            # Use chatid as topic_id for grouping messages in the same conversation
            # This ensures all messages in the same chat appear in the same thread/window
            topic_id = chatid or sender_id

            self._msgid_to_req_id[msgid] = req_id
            # Also store chatid -> req_id mapping for reply messages
            # This is needed because replies use chatid (thread_ts) as the lookup key
            self._chatid_to_req_id[chatid or sender_id] = req_id
            # Store user ID for HTTP API message sending
            self._source_msgid_to_userid[msgid] = sender_id
            self._source_msgid_to_userid[chatid or sender_id] = sender_id

            inbound = self._make_inbound(
                chat_id=chatid or sender_id,
                user_id=sender_id,
                text=text,
                msg_type=msg_type,
                thread_ts=chatid or sender_id,  # Use chatid as thread identifier for conversation continuity
                metadata={"req_id": req_id, "message_id": msgid, "chatid": chatid, "headers": headers, "body": body},
            )
            inbound.topic_id = topic_id

            if self._running and self._main_loop and self._main_loop.is_running():
                logger.info("[WeCom] publishing inbound message to bus (type=%s, msgid=%s)", msg_type.value, msgid)
                fut = asyncio.run_coroutine_threadsafe(self._prepare_inbound(msgid, inbound), self._main_loop)
                fut.add_done_callback(lambda f, mid=msgid: self._log_future_error(f, "prepare_inbound", mid))
            else:
                logger.warning("[WeCom] channel not running, cannot publish inbound message")
        except Exception:
            logger.exception("[WeCom] error processing message callback")

    async def _handle_event_callback(self, headers: dict, body: dict) -> None:
        """Handle event callback frame."""
        try:
            req_id = headers.get("req_id", "")
            msgtype = body.get("msgtype", "")
            event_content = body.get("event", {})
            event_type = event_content.get("eventtype", event_content.get("event_type", ""))

            logger.info(
                "[WeCom] event callback: req_id=%s, msgtype=%s, event_type=%s",
                req_id,
                msgtype,
                event_type,
            )

            if event_type == "enter_chat":
                logger.info("[WeCom] User entered chat")
        except Exception:
            logger.exception("[WeCom] error processing event callback")

    async def _prepare_inbound(self, msg_id: str, inbound: InboundMessage) -> None:
        """Kick off WeCom side effects without delaying inbound dispatch."""
        # 先发布消息，保证消息能正常处理
        await self.bus.publish_inbound(inbound)

        # 然后再尝试发送思考占位符（即使失败也不影响）
        chat_id = inbound.chat_id
        if chat_id and self._ws:
            try:
                stream_id = uuid.uuid4().hex
                self._chatid_to_stream_id[chat_id] = stream_id
                await self._reply_stream(
                    message_id=chat_id,
                    stream_id=stream_id,
                    content=self._THINKING_MESSAGE,
                    finish=False,
                )
                logger.info(
                    "[WeCom] Sent thinking placeholder: chat_id=%s, stream_id=%s",
                    chat_id,
                    stream_id,
                )
            except Exception:
                logger.exception("[WeCom] Failed to send thinking placeholder")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        for task in list(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()
        for task in list(self._running_card_tasks.values()):
            task.cancel()
        self._running_card_tasks.clear()
        await self._stop_heartbeat()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("WeCom channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message back to WeCom (thread-safe)."""
        # Since send() is called from gateway's event loop (different thread than WebSocket),
        # we need to run the actual send logic on the WebSocket thread's event loop.
        ws_loop = self._ws_loop

        try:
            # Check if we're already on the WebSocket thread's loop
            if ws_loop and asyncio.get_running_loop() is ws_loop:
                await self._send_card_message(msg)
                return
        except RuntimeError:
            pass

        # Otherwise, dispatch to the WebSocket thread
        if ws_loop and ws_loop.is_running() and not ws_loop.is_closed():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._send_card_message(msg), ws_loop)
                await asyncio.wrap_future(fut)
            except Exception:
                logger.exception("[WeCom] Failed to send message via WebSocket thread")
        else:
            logger.warning("[WeCom] No WebSocket loop running, cannot send message")

    async def _send_card_message(self, msg: OutboundMessage) -> None:
        """Send or update WeCom message using native streaming format."""
        source_message_id = msg.thread_ts
        if source_message_id:
            # 消息去重检查：对于最终消息，检查3秒内是否发送过相同内容
            if msg.is_final:
                current_time = time.time()
                last_msg = self._last_message.get(source_message_id)
                if last_msg:
                    last_text, last_time = last_msg
                    if last_text == msg.text and current_time - last_time < 3.0:
                        logger.info(
                            "[WeCom] Skipping duplicate final message: source=%s, text_len=%d",
                            source_message_id,
                            len(msg.text),
                        )
                        return

            # 获取或生成 stream_id
            stream_id = self._chatid_to_stream_id.get(source_message_id)
            if not stream_id:
                stream_id = uuid.uuid4().hex
                self._chatid_to_stream_id[source_message_id] = stream_id
                logger.info(
                    "[WeCom] Starting new stream: source=%s, stream_id=%s",
                    source_message_id,
                    stream_id,
                )

            try:
                # 使用原生流式格式发送消息
                await self._reply_stream(
                    message_id=source_message_id,
                    stream_id=stream_id,
                    content=msg.text,
                    finish=msg.is_final,
                )
                logger.info(
                    "[WeCom] Stream message sent: source=%s, stream_id=%s, is_final=%s",
                    source_message_id,
                    stream_id,
                    msg.is_final,
                )
            except Exception:
                if not msg.is_final:
                    raise
                logger.exception(
                    "[WeCom] failed to send stream message for source=%s",
                    source_message_id,
                )

            # 记录最后发送的消息（只记录最终消息）
            if msg.is_final:
                self._last_message[source_message_id] = (msg.text, time.time())
                # 清理 stream_id
                self._chatid_to_stream_id.pop(source_message_id, None)
            return

        await self._create_message(msg.chat_id, msg.text)

    async def _send_frame(self, frame: dict) -> None:
        """Send a frame via WebSocket (thread-safe)."""
        if not self._ws or not self._ws_loop:
            raise RuntimeError("WebSocket not connected")

        frame_json = json.dumps(frame)

        try:
            if asyncio.get_running_loop() is self._ws_loop:
                await self._ws.send(frame_json)
                return
        except RuntimeError:
            pass

        future = asyncio.run_coroutine_threadsafe(self._ws.send(frame_json), self._ws_loop)
        await asyncio.wrap_future(future)

    async def _reply_stream(
        self,
        message_id: str,
        stream_id: str,
        content: str,
        finish: bool = False,
    ) -> str | None:
        """Reply to a message using WeCom native streaming format via WebSocket."""
        if not self._ws:
            return None

        req_id = self._chatid_to_req_id.get(message_id)
        if not req_id:
            req_id = self._msgid_to_req_id.get(message_id)
        if not req_id:
            req_id = uuid.uuid4().hex
            logger.warning(
                "[WeCom] No req_id found for message_id=%s, using new req_id=%s",
                message_id,
                req_id,
            )

        stream_body = {
            "id": stream_id,
            "finish": finish,
            "content": content,
        }

        frame = {
            "cmd": "aibot_respond_msg",
            "headers": {
                "req_id": req_id,
            },
            "body": {
                "msgtype": "stream",
                "stream": stream_body,
            },
        }

        await self._send_frame(frame)
        logger.debug(
            "[WeCom] Sent stream message via WebSocket: message_id=%s, stream_id=%s, finish=%s",
            message_id,
            stream_id,
            finish,
        )
        return message_id

    async def _reply_message(self, message_id: str, text: str, is_update: bool = False) -> str | None:
        """Reply to a message using WebSocket first (most reliable), fallback to HTTP API."""
        # Always prefer WebSocket for replies since we're using WebSocket for receiving
        if self._ws:
            # For WeCom, we always want to use the original user message's req_id
            # This ensures that all replies (initial and updates) use a valid req_id
            # Look up in this order: chatid -> msgid -> fallback
            req_id = self._chatid_to_req_id.get(message_id)
            if not req_id:
                req_id = self._msgid_to_req_id.get(message_id)
            if not req_id:
                req_id = uuid.uuid4().hex
                logger.warning(
                    "[WeCom] No req_id found for message_id=%s, using new req_id=%s",
                    message_id,
                    req_id,
                )

            frame = {
                "cmd": "aibot_respond_msg",
                "headers": {
                    "req_id": req_id,
                },
                "body": {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": text,
                    },
                },
            }

            await self._send_frame(frame)
            logger.debug(
                "[WeCom] Sent message via WebSocket: message_id=%s, req_id=%s, is_update=%s",
                message_id,
                req_id,
                is_update,
            )
            return message_id

        # Fall back to HTTP API only if WebSocket is not available
        if self._http_client:
            user_id = self._source_msgid_to_userid.get(message_id)
            if user_id:
                try:
                    new_msgid = await self._http_client.send_message(touser=user_id, text=text)
                    return new_msgid
                except Exception as e:
                    logger.warning("[WeCom] HTTP API fallback failed: %s", e)

        return None

    async def _create_message(self, chat_id: str, text: str) -> None:
        """Create a new message using aibot_send_msg."""
        if not self._ws:
            return

        frame = {
            "cmd": "aibot_send_msg",
            "headers": {
                "req_id": uuid.uuid4().hex,
            },
            "body": {
                "chatid": chat_id,
                "msgtype": "markdown",
                "markdown": {
                    "content": text,
                },
            },
        }

        await self._send_frame(frame)

    async def _create_running_card(self, source_message_id: str, text: str) -> str | None:
        """Create the running message and cache its message ID when available."""
        try:
            card_id = await self._reply_message(source_message_id, text)
            if card_id:
                self._running_card_ids[source_message_id] = card_id
                logger.info("[WeCom] running message created: source=%s", source_message_id)
            else:
                logger.warning("[WeCom] running message creation returned no message_id for source=%s, subsequent updates will fall back to new replies", source_message_id)
            return card_id
        except Exception as e:
            logger.error("[WeCom] create_running_card failed for msg_id=%s: %s", source_message_id, e)
            # Don't let running card creation failure block message processing
            return None

    def _ensure_running_card_started(self, source_message_id: str, text: str = "Working on it...") -> asyncio.Task | None:
        """Start running-message creation once per source message.

        Note: This method must be called from within the main event loop
        to ensure thread safety.
        """
        running_card_id = self._running_card_ids.get(source_message_id)
        if running_card_id:
            return None

        running_card_task = self._running_card_tasks.get(source_message_id)
        if running_card_task:
            return running_card_task

        # This is now safe because we ensure we're in the main loop
        running_card_task = asyncio.create_task(self._create_running_card(source_message_id, text))
        self._running_card_tasks[source_message_id] = running_card_task
        running_card_task.add_done_callback(lambda done_task, mid=source_message_id: self._finalize_running_card_task(mid, done_task))
        return running_card_task

    def _finalize_running_card_task(self, source_message_id: str, task: asyncio.Task) -> None:
        if self._running_card_tasks.get(source_message_id) is task:
            self._running_card_tasks.pop(source_message_id, None)
        self._log_task_error(task, "create_running_card", source_message_id)

    async def _ensure_running_card(self, source_message_id: str, text: str = "Working on it...") -> str | None:
        """Ensure the in-thread running message exists and track its message ID."""
        running_card_id = self._running_card_ids.get(source_message_id)
        if running_card_id:
            return running_card_id

        running_card_task = self._ensure_running_card_started(source_message_id, text)
        if running_card_task is None:
            return self._running_card_ids.get(source_message_id)
        return await running_card_task

    @staticmethod
    def _log_future_error(fut, name: str, msg_id: str) -> None:
        """Callback for run_coroutine_threadsafe futures to surface errors."""
        try:
            exc = fut.exception()
            if exc:
                logger.error("[WeCom] %s failed for msg_id=%s: %s", name, msg_id, exc)
        except Exception:
            pass

    @staticmethod
    def _log_task_error(task: asyncio.Task, name: str, msg_id: str) -> None:
        """Callback for background asyncio tasks to surface errors."""
        try:
            exc = task.exception()
            if exc:
                logger.error("[WeCom] %s failed for msg_id=%s: %s", name, msg_id, exc)
        except asyncio.CancelledError:
            logger.info("[WeCom] %s cancelled for msg_id=%s", name, msg_id)
        except Exception:
            pass
