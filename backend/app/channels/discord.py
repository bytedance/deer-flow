"""Discord channel integration using discord.py."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
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
        - ``mention_only``: (optional) If true, only respond when the bot is mentioned.
        - ``allowed_channels``: (optional) List of channel IDs where messages are always accepted
          (even when mention_only is true). Use for channels where you want the bot to respond
          without mentions. Empty = mention_only applies everywhere.
        - ``thread_mode``: (optional) If true, group a channel conversation into a thread.
          Default: same as ``mention_only``.
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
        self._mention_only: bool = bool(config.get("mention_only", False))
        self._thread_mode: bool = config.get("thread_mode", self._mention_only)
        self._allowed_channels: set[str] = set()
        for channel_id in config.get("allowed_channels", []):
            self._allowed_channels.add(str(channel_id))

        # Session tracking: channel_id -> Discord thread_id (in-memory, persisted to JSON).
        # Uses a dedicated JSON file separate from ChannelStore, which maps IM
        # conversations to DeerFlow thread IDs — a different concern.
        self._active_threads: dict[str, str] = {}
        # Reverse-lookup set for O(1) thread ID checks (avoids O(n) scan of _active_threads.values()).
        self._active_thread_ids: set[str] = set()
        # Lock protecting _active_threads and the JSON file from concurrent access.
        # _run_client (Discord loop thread) and the main thread both read/write.
        self._thread_store_lock = threading.Lock()
        store = config.get("channel_store")
        if store is not None:
            self._thread_store_path = store._path.parent / "discord_threads.json"
        else:
            self._thread_store_path = Path.home() / ".deer-flow" / "channels" / "discord_threads.json"

        # Typing indicator management
        self._typing_tasks: dict[str, asyncio.Task] = {}

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
        self._load_active_threads()
        logger.info("Discord channel started")

    def _load_active_threads(self) -> None:
        """Restore Discord thread mappings from the dedicated JSON file on startup."""
        with self._thread_store_lock:
            try:
                if not self._thread_store_path.exists():
                    logger.debug("[Discord] no thread mappings file at %s", self._thread_store_path)
                    return
                data = json.loads(self._thread_store_path.read_text())
                self._active_threads.clear()
                self._active_thread_ids.clear()
                for channel_id, thread_id in data.items():
                    self._active_threads[channel_id] = thread_id
                    self._active_thread_ids.add(thread_id)
                if self._active_threads:
                    logger.info("[Discord] restored %d thread mappings from %s", len(self._active_threads), self._thread_store_path)
            except Exception:
                logger.exception("[Discord] failed to load thread mappings")

    def _save_thread(self, channel_id: str, thread_id: str) -> None:
        """Persist a Discord thread mapping to the dedicated JSON file."""
        with self._thread_store_lock:
            try:
                data: dict[str, str] = {}
                if self._thread_store_path.exists():
                    data = json.loads(self._thread_store_path.read_text())
                old_id = data.get(channel_id)
                data[channel_id] = thread_id
                # Update reverse-lookup set
                if old_id:
                    self._active_thread_ids.discard(old_id)
                self._active_thread_ids.add(thread_id)
                self._thread_store_path.parent.mkdir(parents=True, exist_ok=True)
                self._thread_store_path.write_text(json.dumps(data, indent=2))
            except Exception:
                logger.exception("[Discord] failed to save thread mapping for channel %s", channel_id)

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)

        # Cancel all active typing indicator tasks
        for target_id, task in list(self._typing_tasks.items()):
            if not task.done():
                task.cancel()
            logger.debug("[Discord] cancelled typing task for target %s", target_id)
        self._typing_tasks.clear()

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
        # Stop typing indicator once we're sending the response
        stop_future = asyncio.run_coroutine_threadsafe(self._stop_typing(msg.chat_id, msg.thread_ts), self._discord_loop)
        await asyncio.wrap_future(stop_future)

        target = await self._resolve_target(msg)
        if target is None:
            logger.error("[Discord] target not found for chat_id=%s thread_ts=%s", msg.chat_id, msg.thread_ts)
            return

        text = msg.text or ""
        for chunk in self._split_text(text):
            send_future = asyncio.run_coroutine_threadsafe(target.send(chunk), self._discord_loop)
            await asyncio.wrap_future(send_future)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        stop_future = asyncio.run_coroutine_threadsafe(self._stop_typing(msg.chat_id, msg.thread_ts), self._discord_loop)
        await asyncio.wrap_future(stop_future)

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

    async def _start_typing(self, channel, chat_id: str, thread_ts: str | None = None) -> None:
        """Starts a loop to send periodic typing indicators."""
        target_id = thread_ts or chat_id
        if target_id in self._typing_tasks:
            return  # Already typing for this target

        async def _typing_loop():
            try:
                while True:
                    try:
                        await channel.trigger_typing()
                    except Exception:
                        pass
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(_typing_loop())
        self._typing_tasks[target_id] = task

    async def _stop_typing(self, chat_id: str, thread_ts: str | None = None) -> None:
        """Stops the typing loop for a specific target."""
        target_id = thread_ts or chat_id
        task = self._typing_tasks.pop(target_id, None)
        if task and not task.done():
            task.cancel()
            logger.debug("[Discord] stopped typing indicator for target %s", target_id)

    async def _add_reaction(self, message) -> None:
        """Add a checkmark reaction to acknowledge the message was received."""
        try:
            await message.add_reaction("✅")
        except Exception:
            logger.debug("[Discord] failed to add reaction to message %s", message.id, exc_info=True)

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

        # Determine whether the bot is mentioned in this message
        user = self._client.user if self._client else None
        if user:
            bot_mention = user.mention  # <@ID>
            alt_mention = f"<@!{user.id}>"  # <@!ID> (ping variant)
            standard_mention = f"<@{user.id}>"
        else:
            bot_mention = None
            alt_mention = None
            standard_mention = ""
        has_mention = (bot_mention and bot_mention in message.content) or (alt_mention and alt_mention in message.content) or (standard_mention and standard_mention in message.content)

        # Strip mention from text for processing
        if has_mention:
            text = text.replace(bot_mention or "", "").replace(alt_mention or "", "").replace(standard_mention or "", "").strip()
            # Don't return early if text is empty — still process the mention (e.g., create thread)

        # --- Determine thread/channel routing and typing target ---
        thread_id = None
        chat_id = None
        typing_target = None  # The Discord object to type into

        if isinstance(message.channel, self._discord_module.Thread):
            # --- Message already inside a thread ---
            thread_obj = message.channel
            thread_id = str(thread_obj.id)
            chat_id = str(thread_obj.parent_id or thread_obj.id)
            typing_target = thread_obj

            # If this is a known active thread, process normally
            if thread_id in self._active_thread_ids:
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
                self._publish(inbound)
                # Start typing indicator in the thread
                if typing_target:
                    asyncio.create_task(self._start_typing(typing_target, chat_id, thread_id))
                asyncio.create_task(self._add_reaction(message))
                return

            # Thread not tracked (orphaned) — create new thread and handle below
            logger.debug("[Discord] message in orphaned thread %s, will create new thread", thread_id)
            thread_id = None
            typing_target = None

        # At this point we're guaranteed to be in a channel, not a thread
        # (the Thread case is handled above). Apply mention_only for all
        # non-thread messages — no special case needed.
        channel_id = str(message.channel.id)

        # Check if there's an active thread for this channel
        if channel_id in self._active_threads:
            # respect mention_only: if enabled, only process messages that mention the bot
            # (unless the channel is in allowed_channels)
            # Messages within a thread are always allowed through (continuation).
            # At this code point we know the message is in a channel, not a thread
            # (Thread case handled above), so always apply the check.
            if self._mention_only and not has_mention and channel_id not in self._allowed_channels:
                logger.debug("[Discord] skipping no-@ message in channel %s (not in thread)", channel_id)
                return
            # mention_only + fresh @ → create new thread instead of routing to existing one
            if self._mention_only and has_mention:
                thread_obj = await self._create_thread(message)
                if thread_obj is not None:
                    target_thread_id = str(thread_obj.id)
                    self._active_threads[channel_id] = target_thread_id
                    self._save_thread(channel_id, target_thread_id)
                    thread_id = target_thread_id
                    chat_id = channel_id
                    typing_target = thread_obj
                    logger.info("[Discord] created new thread %s in channel %s on mention (replacing existing thread)", target_thread_id, channel_id)
                else:
                    logger.info("[Discord] thread creation failed in channel %s, falling back to channel replies", channel_id)
                    thread_id = channel_id
                    chat_id = channel_id
                    typing_target = message.channel
            else:
                # Existing session → route to the existing thread
                target_thread_id = self._active_threads[channel_id]
                logger.debug("[Discord] routing message in channel %s to existing thread %s", channel_id, target_thread_id)
                thread_id = target_thread_id
                chat_id = channel_id
                typing_target = await self._get_channel_or_thread(target_thread_id)
        elif self._mention_only and not has_mention and channel_id not in self._allowed_channels:
            # Not mentioned and not in an allowed channel → skip
            logger.debug("[Discord] skipping message without mention in channel %s", channel_id)
            return
        elif self._mention_only and has_mention:
            # First mention in this channel → create thread
            thread_obj = await self._create_thread(message)
            if thread_obj is not None:
                target_thread_id = str(thread_obj.id)
                self._active_threads[channel_id] = target_thread_id
                self._save_thread(channel_id, target_thread_id)
                thread_id = target_thread_id
                chat_id = channel_id
                typing_target = thread_obj  # Type into the new thread
                logger.info("[Discord] created thread %s in channel %s for user %s", target_thread_id, channel_id, message.author.display_name)
            else:
                # Fallback: thread creation failed (disabled/permissions), reply in channel
                logger.info("[Discord] thread creation failed in channel %s, falling back to channel replies", channel_id)
                thread_id = channel_id
                chat_id = channel_id
                typing_target = message.channel  # Type into the channel
        elif self._thread_mode:
            # thread_mode but mention_only is False → create thread anyway for conversation grouping
            thread_obj = await self._create_thread(message)
            if thread_obj is None:
                # Thread creation failed (disabled/permissions), fall back to channel replies
                logger.info("[Discord] thread creation failed in channel %s, falling back to channel replies", channel_id)
                thread_id = channel_id
                chat_id = channel_id
                typing_target = message.channel  # Type into the channel
            else:
                target_thread_id = str(thread_obj.id)
                self._active_threads[channel_id] = target_thread_id
                self._save_thread(channel_id, target_thread_id)
                thread_id = target_thread_id
                chat_id = channel_id
                typing_target = thread_obj  # Type into the new thread
        else:
            # No threading — reply directly in channel
            thread_id = channel_id
            chat_id = channel_id
            typing_target = message.channel  # Type into the channel

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

        # Start typing indicator in the correct target (thread or channel)
        if typing_target:
            asyncio.create_task(self._start_typing(typing_target, chat_id, thread_id))

        self._publish(inbound)
        asyncio.create_task(self._add_reaction(message))

    def _publish(self, inbound) -> None:
        """Publish an inbound message to the main event loop."""
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
            if self._discord_module is None:
                return None

            # Only TextChannel (type 0) and NewsChannel (type 10) support threads
            channel_type = message.channel.type
            if channel_type not in (
                self._discord_module.ChannelType.text,
                self._discord_module.ChannelType.news,
            ):
                logger.info(
                    "[Discord] channel type %s (%s) does not support threads",
                    channel_type.value,
                    channel_type.name,
                )
                return None

            thread_name = f"deerflow-{message.author.display_name}-{message.id}"[:100]
            return await message.create_thread(name=thread_name)
        except self._discord_module.errors.HTTPException as exc:
            if exc.code == 50024:
                logger.info(
                    "[Discord] cannot create thread in channel %s (error code 50024): %s",
                    message.channel.id,
                    channel_type.name if (channel_type := message.channel.type) else "unknown",
                )
            else:
                logger.exception(
                    "[Discord] failed to create thread for message=%s (HTTPException %s)",
                    message.id,
                    exc.code,
                )
            return None
        except Exception:
            logger.exception("[Discord] failed to create thread for message=%s (threads may be disabled or missing permissions)", message.id)
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
