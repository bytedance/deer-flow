"""Pushes scheduled-job results to IM channels via the shared MessageBus.

Zero-footprint design: this module does **not** modify ``app/channels/``.
It only consumes the existing ``MessageBus.publish_outbound`` pub/sub
API. Each IM platform's ``Channel.send()`` is the actual transmitter;
we just route the right ``OutboundMessage`` to the bus.

Source-channel format (parsed by ``parse_source_channel``):

- ``"web"``                                     → in-app notification
- ``"im:dingtalk:group:<chat_id>"``             → DingTalk group
- ``"im:dingtalk:p2p:<staff_id>"``              → DingTalk DM
- ``"im:feishu:group:<chat_id>"``               → Feishu group
- ``"im:feishu:p2p:<user_id>"``                 → Feishu DM
- ``"im:slack:<channel_id>"``                   → Slack channel
- ``"im:telegram:<chat_id>"``                   → Telegram chat
- ``"im:discord:<channel_id>"``                 → Discord channel

When the parsed platform is unknown or the bus is missing, the pusher
logs and degrades gracefully — never blocks the scheduler.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.channels.message_bus import OutboundMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source-channel parsing
# ---------------------------------------------------------------------------


def parse_source_channel(source: str) -> tuple[str | None, str | None, str | None]:
    """Split ``"im:<platform>:<conv>:<chat_id>"`` into a 3-tuple.

    Returns ``(platform, conversation_type, chat_id)``. For non-IM
    sources (e.g. ``"web"``) returns ``(None, None, None)``.
    """
    if not source or source == "web":
        return None, None, None
    if not source.startswith("im:"):
        logger.warning("unrecognised source_channel: %r", source)
        return None, None, None

    parts = source.split(":", 3)
    if len(parts) < 4:
        logger.warning("malformed im source_channel: %r", source)
        return None, None, None

    # parts = ["im", platform, conv_type, chat_id]
    _, platform, conv_type, chat_id = parts
    return platform, conv_type, chat_id


# ---------------------------------------------------------------------------
# Bus protocol (for test injection)
# ---------------------------------------------------------------------------


class _BusLike(Protocol):
    """Minimal protocol IMPusher needs from MessageBus."""

    async def publish_outbound(self, msg: OutboundMessage) -> None: ...


# ---------------------------------------------------------------------------
# IMPusher
# ---------------------------------------------------------------------------


class IMPusher:
    """Routes scheduled-job results to IM channels via the shared bus.

    Construct once at Gateway lifespan startup with the running
    ChannelService's bus. When the bus is None (channels disabled) the
    pusher logs and no-ops — never raises.
    """

    def __init__(self, bus: _BusLike | None) -> None:
        self._bus = bus

    async def push(
        self,
        *,
        job: dict[str, Any],
        thread_id: str,
        result_text: str,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        """Build an OutboundMessage and publish it.

        Behaviour:

        - ``source_channel == "web"`` → no-op (in-app sink handles it)
        - bus is None → log and return (channels disabled in this deploy)
        - parse error → log and return
        - publish raises → log and swallow (do not block the scheduler)
        """
        source = job.get("source_channel", "web")
        platform, conv_type, chat_id = parse_source_channel(source)
        if platform is None:
            # Not an IM push target — the in-app sink handles Web notifications
            return

        if self._bus is None:
            logger.info(
                "im_pusher skipped (no bus): job=%s platform=%s chat=%s",
                job.get("id"),
                platform,
                chat_id,
            )
            return

        text = self._compose_message(
            job_name=job.get("name", "scheduled task"),
            result_text=result_text,
            status=status,
            error_msg=error_msg,
        )
        if not text:
            return

        outbound = self._build_outbound(
            platform=platform,
            conv_type=conv_type,
            chat_id=chat_id or "",
            thread_id=thread_id,
            text=text,
            owner_user_id=job.get("user_id"),
            job_id=job.get("id"),
        )

        try:
            await self._bus.publish_outbound(outbound)
        except Exception:
            logger.exception(
                "im_pusher publish failed: job=%s platform=%s",
                job.get("id"),
                platform,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _compose_message(
        *,
        job_name: str,
        result_text: str,
        status: str,
        error_msg: str | None,
    ) -> str:
        """Format the human-readable message that goes to the IM chat."""
        if status == "ok":
            body = result_text.strip() if result_text else "(no output)"
            return f"📋 {job_name}\n\n{body}"
        if status in ("error", "timeout"):
            return f"⚠️ {job_name} failed ({status}): {error_msg or 'unknown error'}"
        if status == "skipped":
            return f"⏭️ {job_name} skipped: {error_msg or 'no reason'}"
        # Unknown status — best-effort log
        return f"{job_name}: {status}"

    @staticmethod
    def _build_outbound(
        *,
        platform: str,
        conv_type: str | None,
        chat_id: str,
        thread_id: str,
        text: str,
        owner_user_id: str | None,
        job_id: str | None,
    ) -> OutboundMessage:
        """Build the OutboundMessage, applying per-platform metadata.

        Per-platform notes (from inspecting each ``Channel.send()``):

        - **dingtalk**: needs ``metadata["conversation_type"]`` set to
          ``"group"`` or ``"p2p"`` to route correctly. ``chat_id`` is the
          group conversation id (group) or staff_id (p2p).
        - **feishu / slack / telegram / discord / wecom / wechat**: route
          purely off ``chat_id`` (no metadata required). Future platform-
          specific tweaks should be added here as needed.
        """
        metadata: dict[str, Any] = {}
        if platform == "dingtalk" and conv_type:
            metadata["conversation_type"] = conv_type

        # Stable thread_id required by OutboundMessage schema; if the job
        # produced a fresh thread per run, use that. The IM channels use
        # this for audit / reply-threading but not for delivery routing.
        return OutboundMessage(
            channel_name=platform,
            chat_id=chat_id,
            thread_id=thread_id,
            text=text,
            metadata=metadata,
            owner_user_id=owner_user_id,
        )
