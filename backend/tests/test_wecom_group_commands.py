"""WeCom group commands addressed to the bot run as commands.

WeCom leaves the bot mention in group text (``@RobotA /new``), so classifying
the raw text made every addressed command a chat turn. Feishu (#4229) and
DingTalk (#4724) strip a leading mention on the command path for the same
reason; WeCom was left out because the mention had not been confirmed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus
from app.channels.wecom import WeComChannel

pytestmark = pytest.mark.asyncio


def _channel(bus: MessageBus) -> WeComChannel:
    channel = WeComChannel(bus=bus, config={})
    channel._ws_client = SimpleNamespace(reply=AsyncMock(), reply_stream=AsyncMock(), send_message=AsyncMock())
    return channel


async def _receive(bus: MessageBus, channel: WeComChannel, content: str, *, msgid: str = "m1") -> InboundMessage:
    body = {
        "aibotid": "bot-1",
        "chattype": "group",
        "chatid": "wr-team",
        "msgid": msgid,
        "from": {"userid": "alice"},
        "msgtype": "text",
        "text": {"content": content},
    }
    await channel._on_ws_text({"body": body})
    return bus.get_inbound_nowait()


async def test_group_command_with_leading_mention_runs_as_command():
    bus = MessageBus()
    channel = _channel(bus)

    message = await _receive(bus, channel, "@RobotA /new")

    assert message.msg_type == InboundMessageType.COMMAND
    assert message.text == "/new"


async def test_group_chat_with_leading_mention_keeps_the_mention():
    bus = MessageBus()
    channel = _channel(bus)

    message = await _receive(bus, channel, "@RobotA hello robot")

    assert message.msg_type == InboundMessageType.CHAT
    assert message.text == "@RobotA hello robot"


async def test_group_slash_text_after_mention_stays_chat():
    """Only registered commands are commands; a path keeps its mention."""
    bus = MessageBus()
    channel = _channel(bus)

    message = await _receive(bus, channel, "@RobotA /tmp/report.csv")

    assert message.msg_type == InboundMessageType.CHAT
    assert message.text == "@RobotA /tmp/report.csv"
