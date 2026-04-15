"""Discord channel integration using discord.py."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

_DISCORD_MAX_MESSAGE_LEN = 2000


class DiscordChannel(Channel):
    """Discord bot channel.

    Configuration keys (in ``config.yaml`` under ``channels.discord``):
        - ``bot_token``: Discord Bot token.
        - ``allowed_guilds``: (optional) List of allowed Discord guild IDs. Empty = allow all.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="discord", bus=bus, config=config)
        self._bot_token = str(config.get("bot_token", "")).strip()
        self._allowed_guilds: set[int] = set()
        for guild_id in config.get("allowed_guilds", []):
            try:
                self._allowed_guilds.add(int(guild_id))
            except (TypeError, ValueError):
                continue

        self._client = None
        self._thread: threading.Thread | None = None
        self._discord_loop: asyncio.AbstractEventLoop | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._discord_module = None

    async def start(self) -> None:
        if self._running:
            return

        try:
            import discord
        except ImportError:
            logger.error("discord.py is not installed. Install it with: uv add discord.py")
            return

        if not self._bot_token:
            logger.error("Discord channel requires bot_token")
            return

        intents = discord.Intents.default()
        intents.messages = True
        intents.guilds = True
        intents.message_content = True

        client = discord.Client(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self._client = client
        self._discord_module = discord
        self._main_loop = asyncio.get_event_loop()

        @client.event
        async def on_message(message) -> None:
            await self._on_message(message)

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        self._thread = threading.Thread(target=self._run_client, daemon=True)
        self._thread.start()
        logger.info("Discord channel started")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)

        if self._client and self._discord_loop and self._discord_loop.is_running():
            close_future = asyncio.run_coroutine_threadsafe(self._client.close(), self._discord_loop)
            try:
                await asyncio.wait_for(asyncio.wrap_future(close_future), timeout=10)
            except TimeoutError:
                logger.warning("[Discord] client close timed out after 10s")
            except Exception:
                logger.exception("[Discord] error while closing client")

        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

        self._client = None
        self._discord_loop = None
        self._discord_module = None
        logger.info("Discord channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        target = await self._resolve_target(msg)
        if target is None:
            logger.error("[Discord] target not found for chat_id=%s thread_ts=%s", msg.chat_id, msg.thread_ts)
            return

        text = msg.text or ""
        for chunk in self._split_text(text):
            send_future = asyncio.run_coroutine_threadsafe(target.send(chunk), self._discord_loop)
            await asyncio.wrap_future(send_future)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        target = await self._resolve_target(msg)
        if target is None:
            logger.error("[Discord] target not found for file upload chat_id=%s thread_ts=%s", msg.chat_id, msg.thread_ts)
            return False

        if self._discord_module is None:
            return False

        try:
            fp = open(str(attachment.actual_path), "rb")  # noqa: SIM115
            file = self._discord_module.File(fp, filename=attachment.filename)
            send_future = asyncio.run_coroutine_threadsafe(target.send(file=file), self._discord_loop)
            await asyncio.wrap_future(send_future)
            logger.info("[Discord] file uploaded: %s", attachment.filename)
            return True
        except Exception:
            logger.exception("[Discord] failed to upload file: %s", attachment.filename)
            return False

    async def _on_message(self, message) -> None:
        if not self._running or not self._client:
            return

        if message.author.bot:
            return

        if self._client.user and message.author.id == self._client.user.id:
            return

        guild = message.guild
        if self._allowed_guilds:
            if guild is None or guild.id not in self._allowed_guilds:
                return

        text = (message.content or "").strip()
        if not text:
            return

        if self._discord_module is None:
            return

        if isinstance(message.channel, self._discord_module.Thread):
            chat_id = str(message.channel.parent_id or message.channel.id)
            thread_id = str(message.channel.id)
        else:
            thread = await self._create_thread(message)
            if thread is None:
                return
            chat_id = str(message.channel.id)
            thread_id = str(thread.id)

        msg_type = InboundMessageType.COMMAND if text.startswith("/") else InboundMessageType.CHAT
        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=str(message.author.id),
            text=text,
            msg_type=msg_type,
            thread_ts=thread_id,
            metadata={
                "guild_id": str(guild.id) if guild else None,
                "channel_id": str(message.channel.id),
                "message_id": str(message.id),
            },
        )
        inbound.topic_id = thread_id

        if self._main_loop and self._main_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.bus.publish_inbound(inbound), self._main_loop)
            future.add_done_callback(lambda f: logger.exception("[Discord] publish_inbound failed", exc_info=f.exception()) if f.exception() else None)

    def _run_client(self) -> None:
        self._discord_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._discord_loop)
        try:
            self._discord_loop.run_until_complete(self._client.start(self._bot_token))
        except Exception:
            if self._running:
                logger.exception("Discord client error")
        finally:
            try:
                if self._client and not self._client.is_closed():
                    self._discord_loop.run_until_complete(self._client.close())
            except Exception:
                logger.exception("Error during Discord shutdown")

    async def _create_thread(self, message):
        try:
            thread_name = f"deerflow-{message.author.display_name}-{message.id}"[:100]
            return await message.create_thread(name=thread_name)
        except Exception:
            logger.exception("[Discord] failed to create thread for message=%s (threads may be disabled or missing permissions)", message.id)
            try:
                await message.channel.send("Could not create a thread for your message. Please check that threads are enabled in this channel.")
            except Exception:
                pass
            return None

    async def _resolve_target(self, msg: OutboundMessage):
        if not self._client or not self._discord_loop:
            return None

        target_ids: list[str] = []
        if msg.thread_ts:
            target_ids.append(msg.thread_ts)
        if msg.chat_id and msg.chat_id not in target_ids:
            target_ids.append(msg.chat_id)

        for raw_id in target_ids:
            target = await self._get_channel_or_thread(raw_id)
            if target is not None:
                return target
        return None

    async def _get_channel_or_thread(self, raw_id: str):
        if not self._client or not self._discord_loop:
            return None

        try:
            target_id = int(raw_id)
        except (TypeError, ValueError):
            return None

        get_future = asyncio.run_coroutine_threadsafe(self._fetch_channel(target_id), self._discord_loop)
        try:
            return await asyncio.wrap_future(get_future)
        except Exception:
            logger.exception("[Discord] failed to resolve target id=%s", raw_id)
            return None

    async def _fetch_channel(self, target_id: int):
        if not self._client:
            return None

        channel = self._client.get_channel(target_id)
        if channel is not None:
            return channel

        try:
            return await self._client.fetch_channel(target_id)
        except Exception:
            return None

    @staticmethod
    def _split_text(text: str) -> list[str]:
        if not text:
            return [""]

        chunks: list[str] = []
        remaining = text
        while len(remaining) > _DISCORD_MAX_MESSAGE_LEN:
            split_at = remaining.rfind("\n", 0, _DISCORD_MAX_MESSAGE_LEN)
            if split_at <= 0:
                split_at = _DISCORD_MAX_MESSAGE_LEN
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        if remaining:
            chunks.append(remaining)

        return chunks
