"""QQ Open Platform text channel over an outbound WebSocket connection."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import ssl
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.channels.base import Channel
from app.channels.commands import extract_connect_code, is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
API_URL = "https://api.sgroup.qq.com"
GROUP_AND_C2C_EVENT = 1 << 25
# Conservative adapter budget, not a claim about the platform's maximum.
MAX_TEXT_BYTES = 4000
C2C_MAX_REPLIES = 4
GROUP_MAX_REPLIES = 5
TIMESTAMP_WARNING_INTERVAL = 60.0
MAX_CACHED_MESSAGES = 2048
INBOUND_BUFFER_SIZE = 64
START_TIMEOUT = 30.0
RECONNECT_DELAY = 1.0
TRUNCATION_MARKER = "\n[Reply truncated; see DeerFlow for the full response.]"


class QQAPIError(RuntimeError):
    """A sanitized provider failure, safe for shared channel error logging."""


def validate_gateway_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        valid = (
            parsed.scheme == "wss" and (host == "api.bot.qq.com" or host == "sgroup.qq.com" or host.endswith(".sgroup.qq.com")) and parsed.port in (None, 443) and parsed.username is None and parsed.password is None and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise QQAPIError("QQ returned an untrusted gateway URL")
    return url


class _GatewayConnect(connect):
    def process_redirect(self, exc: Exception) -> Exception:
        # Never forward Identify credentials through a redirected socket.
        return QQAPIError("QQ gateway redirects are not supported")


@dataclass
class _ReplyContext:
    path: str
    expires_at: float
    max_replies: int
    sequence: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class QQChannel(Channel):
    def __init__(self, bus: MessageBus, config: dict[str, Any]):
        super().__init__("qq", bus, config)
        self._app_id = str(config.get("app_id") or "").strip()
        self._client_secret = str(config.get("client_secret") or "").strip()
        self._allowed_users = set(config.get("allowed_users") or [])
        self._api_url = "https://sandbox.api.sgroup.qq.com" if config.get("sandbox", False) else API_URL
        self._http: httpx.AsyncClient | None = None
        self._ssl: ssl.SSLContext | None = None
        self._access_token = ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._listener: asyncio.Task | None = None
        self._worker: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._authenticated = asyncio.Event()
        self._events: asyncio.Queue = asyncio.Queue(maxsize=INBOUND_BUFFER_SIZE)
        self._session_id: str | None = None
        self._sequence: int | None = None
        self._bot_id = ""
        self._replies: OrderedDict[tuple[str, str], _ReplyContext] = OrderedDict()
        self._next_timestamp_warning_at = 0.0

    @property
    def is_running(self) -> bool:
        return bool(self._running and self._ready.is_set() and self._listener and not self._listener.done())

    async def _setup_transport(self) -> None:
        # Both SSL trust loading and httpx initialization can read local files.
        self._ssl = await asyncio.to_thread(ssl.create_default_context)
        if self._http is None:
            self._http = await asyncio.to_thread(httpx.AsyncClient, timeout=15.0, follow_redirects=False, trust_env=False)

    async def start(self) -> None:
        if self.is_running:
            return
        if self._listener is not None:
            raise QQAPIError("QQ channel startup is already in progress")
        if not self._app_id or not self._client_secret:
            raise QQAPIError("QQ requires app_id and client_secret")
        try:
            await await_drained(self._setup_transport())
            self._running = True
            self._ready.clear()
            self.bus.subscribe_outbound(self._on_outbound)
            self._worker = asyncio.create_task(self._consume_events(), name="qq-inbound")
            self._listener = asyncio.create_task(self._listen(), name="qq-websocket")
            await asyncio.wait_for(self._ready.wait(), timeout=START_TIMEOUT)
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        await await_drained(self._stop())

    async def _stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        tasks = [task for task in (self._listener, self._worker) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._listener = self._worker = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._ready.clear()
        self._session_id = None
        self._authenticated.clear()
        self._sequence = None
        self._access_token = ""
        self._token_expires_at = 0.0
        self._events = asyncio.Queue(maxsize=INBOUND_BUFFER_SIZE)
        self._replies.clear()
        self._next_timestamp_warning_at = 0.0

    async def _get_access_token(self) -> str:
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            if self._http is None:
                raise QQAPIError("QQ HTTP transport is not available")
            try:
                response = await self._http.post(
                    TOKEN_URL,
                    json={"appId": self._app_id, "clientSecret": self._client_secret},
                )
                response.raise_for_status()
                payload = response.json()
                token = payload["access_token"]
                lifetime = float(payload["expires_in"])
                if not isinstance(token, str) or not token or not math.isfinite(lifetime) or lifetime <= 0:
                    raise ValueError
            except Exception:
                raise QQAPIError("QQ access token request failed") from None
            self._access_token = token
            self._token_expires_at = time.monotonic() + lifetime - min(60, lifetime / 10)
            return token

    async def _api_request(self, method: str, path: str, **kwargs: Any) -> dict:
        for attempt in range(2):
            token = await self._get_access_token()
            try:
                response = await self._http.request(
                    method,
                    self._api_url + path,
                    headers={
                        "Authorization": f"QQBot {token}",
                        "X-Union-Appid": self._app_id,
                    },
                    **kwargs,
                )
            except Exception:
                # An ambiguous timeout must not trigger another passive reply.
                raise QQAPIError("QQ API transport failed") from None
            if response.status_code == 401 and attempt == 0:
                if token == self._access_token:
                    self._token_expires_at = 0
                continue
            if not response.is_success:
                raise QQAPIError(f"QQ API request failed (HTTP {response.status_code})")
            try:
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("code", 0) not in (
                    0,
                    None,
                ):
                    raise ValueError
                return payload
            except (ValueError, TypeError):
                raise QQAPIError("QQ API returned an invalid response") from None
        raise QQAPIError("QQ API authentication failed")

    async def _listen(self) -> None:
        delay = RECONNECT_DELAY
        try:
            while self._running:
                try:
                    gateway = await self._api_request("GET", "/gateway")
                    url = validate_gateway_url(gateway.get("url", ""))
                    await self._run_connection(url)
                    delay = RECONNECT_DELAY
                except asyncio.CancelledError:
                    raise
                except ConnectionClosed as exc:
                    code = exc.rcvd.code if exc.rcvd is not None else None
                    # 4009 explicitly permits Resume; rejected authentication,
                    # sessions and sequence numbers require a fresh Identify.
                    if code in range(4000, 4009):
                        self._session_id = None
                        self._sequence = None
                    if code == 4004:
                        self._token_expires_at = 0
                    logger.warning("[qq] gateway closed; reconnecting (code=%s)", code)
                except Exception:
                    # Provider exceptions may contain tokens or raw frames.
                    logger.warning("[qq] gateway connection interrupted; reconnecting")
                if self._running:
                    await asyncio.sleep(delay)
                    delay = min(max(delay * 2, RECONNECT_DELAY), 30.0)
        finally:
            self._running = False

    async def _run_connection(self, url: str) -> None:
        self._authenticated.clear()
        async with _GatewayConnect(
            url,
            ssl=self._ssl if url.startswith("wss:") else None,
            proxy=None,
            ping_interval=None,
            open_timeout=15,
            close_timeout=5,
            max_size=256 * 1024,
        ) as socket:
            hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            interval = float(hello.get("d", {}).get("heartbeat_interval", 0)) / 1000
            if hello.get("op") != 10 or not math.isfinite(interval) or interval <= 0:
                raise QQAPIError("QQ gateway sent an invalid HELLO")
            token = await self._get_access_token()
            if self._session_id is not None and self._sequence is not None:
                auth = {
                    "op": 6,
                    "d": {
                        "token": f"QQBot {token}",
                        "session_id": self._session_id,
                        "seq": self._sequence,
                    },
                }
            else:
                auth = {
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": GROUP_AND_C2C_EVENT,
                        "shard": [0, 1],
                    },
                }
            await socket.send(json.dumps(auth))
            ack = asyncio.Event()
            ack.set()
            heartbeat = asyncio.create_task(self._heartbeat(socket, interval, ack), name="qq-heartbeat")
            reader = asyncio.create_task(self._read_frames(socket, ack), name="qq-reader")
            try:
                done, _ = await asyncio.wait((heartbeat, reader), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                heartbeat.cancel()
                reader.cancel()
                await asyncio.gather(heartbeat, reader, return_exceptions=True)

    async def _heartbeat(self, socket: Any, interval: float, ack: asyncio.Event) -> None:
        # QQ must finish Identify/Resume before the first periodic heartbeat.
        # Sending a null sequence immediately after Identify isn't acknowledged
        # by the live gateway, even though permissive test servers accept it.
        await asyncio.wait_for(self._authenticated.wait(), timeout=15)
        while True:
            if not ack.is_set():
                raise QQAPIError("QQ heartbeat acknowledgement timed out")
            ack.clear()
            await socket.send(json.dumps({"op": 1, "d": self._sequence}))
            await asyncio.sleep(interval)

    async def _read_frames(self, socket: Any, ack: asyncio.Event) -> None:
        async for raw in socket:
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                continue
            op = frame.get("op")
            if op == 11:
                ack.set()
            elif op == 1:
                await socket.send(json.dumps({"op": 1, "d": self._sequence}))
            elif op == 7:
                return
            elif op == 9:
                if frame.get("d") is not True:
                    self._session_id = None
                    self._sequence = None
                self._token_expires_at = 0
                return
            elif op == 0:
                sequence = frame.get("s")
                if isinstance(sequence, int) and not isinstance(sequence, bool):
                    self._sequence = sequence
                kind = frame.get("t")
                if kind == "READY":
                    data = frame.get("d") or {}
                    session = data.get("session_id")
                    if not isinstance(session, str) or not session:
                        raise QQAPIError("QQ gateway sent an invalid READY")
                    self._session_id = session
                    self._bot_id = str((data.get("user") or {}).get("id") or "")
                    self._authenticated.set()
                    self._ready.set()
                elif kind == "RESUMED":
                    self._authenticated.set()
                    self._ready.set()
                elif kind in ("C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"):
                    try:
                        self._events.put_nowait(frame)
                    except asyncio.QueueFull:
                        logger.warning("[qq] inbound buffer full; dropping message")

    async def _consume_events(self) -> None:
        while True:
            frame = await self._events.get()
            try:
                await self._handle_inbound(frame)
            except Exception:
                logger.warning("[qq] inbound message handling failed")
            finally:
                self._events.task_done()

    async def _handle_inbound(self, frame: dict) -> None:
        kind = frame.get("t")
        if kind not in ("C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"):
            return
        data = frame.get("d")
        if not isinstance(data, dict) or not isinstance(data.get("author"), dict):
            return
        group = kind == "GROUP_AT_MESSAGE_CREATE"
        sender = data["author"].get("member_openid" if group else "user_openid")
        target = data.get("group_openid") if group else sender
        message_id, text = data.get("id"), data.get("content")
        if not all(isinstance(value, str) and value for value in (sender, target, message_id, text)):
            return
        text = text.strip()
        if group and self._bot_id:
            for mention in (f"<@!{self._bot_id}>", f"<@{self._bot_id}>"):
                if text.startswith(mention):
                    text = text[len(mention) :].strip()
                    break
        if not text:
            return
        scope = "group" if group else "c2c"
        chat_id = f"{scope}:{target}"
        workspace = f"{self._app_id}:group:{target}" if group else f"{self._app_id}:c2c"
        now = time.monotonic()
        window = 300 if group else 3600
        timestamp = data.get("timestamp")
        if timestamp is not None:
            try:
                created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    raise ValueError
                window -= max(0, time.time() - created.timestamp())
            except (TypeError, ValueError, AttributeError, OverflowError):
                # The window is advisory; QQ enforces expiry server-side.
                # Unknown timestamp formats must not silently disable intake.
                if now >= self._next_timestamp_warning_at:
                    logger.warning("[qq] message timestamp invalid or missing timezone; using full passive reply window")
                    self._next_timestamp_warning_at = now + TIMESTAMP_WARNING_INTERVAL
        if window <= 0:
            return
        code = self._pending_connect_code(text)
        # Binding codes are always control traffic, even without a repository.
        if extract_connect_code(text) and code is None:
            return
        if not code and self._allowed_users and sender not in self._allowed_users:
            return
        key = (chat_id, message_id)
        self._replies.setdefault(
            key,
            _ReplyContext(
                f"/v2/{'groups' if group else 'users'}/{quote(target, safe='')}/messages",
                now + window,
                GROUP_MAX_REPLIES if group else C2C_MAX_REPLIES,
            ),
        )
        if len(self._replies) > MAX_CACHED_MESSAGES:
            expired = [key for key, context in self._replies.items() if context.expires_at <= now]
            for expired_key in expired:
                del self._replies[expired_key]
        while len(self._replies) > MAX_CACHED_MESSAGES:
            self._replies.popitem(last=False)
        if code:
            state = await self._connection_repo.consume_oauth_state(provider="qq", state=code)
            reply = "QQ connection code is invalid or expired."
            if state is not None:
                await self._connection_repo.upsert_connection(
                    owner_user_id=state["owner_user_id"],
                    provider="qq",
                    external_account_id=sender,
                    workspace_id=workspace,
                    metadata={"chat_type": scope},
                    status="connected",
                )
                reply = "QQ connected to DeerFlow."
            await self.send(
                OutboundMessage(
                    channel_name="qq",
                    chat_id=chat_id,
                    thread_id="",
                    thread_ts=message_id,
                    text=reply,
                )
            )
            return
        inbound = self._make_inbound(
            chat_id,
            sender,
            text,
            msg_type=InboundMessageType.COMMAND if is_known_channel_command(text) else InboundMessageType.CHAT,
            thread_ts=message_id,
            metadata={"message_id": message_id},
        )
        inbound.topic_id = f"{self._app_id}:{sender}"
        inbound.workspace_id = workspace
        reservation = self._reserve_inbound(inbound)
        if reservation is None:
            return
        try:
            await attach_connection_identity(
                inbound,
                repo=self._connection_repo,
                provider="qq",
                workspace_id=workspace,
            )
            self._commit_reserved_inbound(reservation, inbound)
        finally:
            reservation.release()

    async def send(self, msg: OutboundMessage) -> None:
        if not msg.is_final or not msg.text:
            return
        context = self._replies.get((msg.chat_id, msg.thread_ts))
        if context is None:
            raise QQAPIError("QQ requires an unexpired source message for a passive reply")
        async with context.lock:
            remaining = context.max_replies - context.sequence
            if remaining <= 0:
                raise QQAPIError("QQ passive reply quota exhausted")
            raw = msg.text.encode("utf-8")
            for index in range(remaining):
                if context.expires_at <= time.monotonic():
                    raise QQAPIError("QQ passive reply window expired")
                if index == remaining - 1 and len(raw) > MAX_TEXT_BYTES:
                    marker = TRUNCATION_MARKER.encode("utf-8")
                    chunk = raw[: max(0, MAX_TEXT_BYTES - len(marker))].decode("utf-8", errors="ignore") + TRUNCATION_MARKER
                    raw = b""
                else:
                    chunk = raw[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
                    raw = raw[len(chunk.encode("utf-8")) :]
                # Spend the sequence before I/O: a timeout may still deliver.
                context.sequence += 1
                await self._api_request(
                    "POST",
                    context.path,
                    json={
                        "msg_type": 0,
                        "content": chunk,
                        "msg_id": msg.thread_ts,
                        "msg_seq": context.sequence,
                    },
                )
                if not raw:
                    break
