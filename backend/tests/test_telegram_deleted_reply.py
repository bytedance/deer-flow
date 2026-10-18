"""Offline Bot API simulations exercising real Telegram SDK serialization."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from telegram import Bot
from telegram.error import BadRequest, NetworkError
from telegram.request import BaseRequest

from app.channels import telegram as telegram_module
from app.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment
from app.channels.telegram import TelegramChannel


class _BotApiRequest(BaseRequest):
    @property
    def read_timeout(self):
        return 5

    def __init__(self):
        self.messages = {42}  # The inbound user message.
        self.calls = []
        self.next_id = 100

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        parameters = request_data.parameters if request_data else {}
        self.calls.append((endpoint, parameters))
        if endpoint == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "Test", "username": "test_bot"}
        else:
            reply = parameters.get("reply_parameters", {})
            if reply.get("message_id") not in self.messages and reply and not reply.get("allow_sending_without_reply"):
                return 400, json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: message to be replied not found"}).encode()
            if endpoint == "editMessageText" and parameters["message_id"] not in self.messages:
                return 400, json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: message to edit not found"}).encode()
            message_id = parameters.get("message_id", self.next_id)
            self.next_id += 1
            self.messages.add(message_id)
            result = {
                "message_id": message_id,
                "date": 0,
                "chat": {"id": parameters["chat_id"], "type": "private" if parameters["chat_id"] > 0 else "supergroup"},
                "text": parameters.get("text", ""),
            }
        return 200, json.dumps({"ok": True, "result": result}).encode()


@pytest_asyncio.fixture
async def telegram_channel():
    request = _BotApiRequest()
    async with Bot("123:test-token", request=request, get_updates_request=request) as bot:
        channel = TelegramChannel(MessageBus(), {"bot_token": "123:test-token"})
        channel._application = SimpleNamespace(bot=bot)
        yield channel, request


def _reply(chat_id="12345", **kwargs):
    return OutboundMessage(channel_name="telegram", chat_id=chat_id, thread_id="thread", text="Complete answer", **kwargs)


@pytest.mark.asyncio
async def test_private_final_reply_survives_chat_history_cleared_during_run(telegram_channel):
    channel, request = telegram_channel
    await channel.send(_reply())
    old_reply = channel._last_bot_message["12345"]
    await channel._send_running_reply("12345", 42)
    assert channel._stream_messages["12345:42"]["message_id"] in request.messages

    # Clearing history removes both the prior reply and the in-flight preview.
    request.messages.clear()
    before = len(request.calls)
    await channel.send(_reply(thread_ts="42"))

    assert [endpoint for endpoint, _ in request.calls[before:]] == ["editMessageText", "sendMessage"]
    assert request.calls[-1][1]["reply_parameters"]["message_id"] == old_reply
    assert channel._last_bot_message["12345"] in request.messages
    assert "12345:42" not in channel._stream_messages


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", ["12345", "-12345"])
@pytest.mark.parametrize("stage", ["running", "initial_stream", "replacement_stream"])
async def test_deleted_inbound_target_is_optional_only_for_private_previews(telegram_channel, monkeypatch, chat_id, stage):
    channel, request = telegram_channel
    key = f"{chat_id}:42"
    monkeypatch.setattr(telegram_module, "_monotonic", lambda: 10.0)
    if stage == "replacement_stream":
        await channel.send(_reply(chat_id, thread_ts="42", is_final=False))
        assert channel._stream_messages[key]["message_id"] in request.messages
        monkeypatch.setattr(telegram_module, "_monotonic", lambda: 20.0)

    # Deletion removes the inbound target and, when present, the preview too.
    request.messages.clear()
    before = len(request.calls)
    if stage == "running":
        await channel._send_running_reply(chat_id, 42)
    else:
        await channel.send(OutboundMessage(channel_name="telegram", chat_id=chat_id, thread_id="thread", thread_ts="42", text="Updated preview", is_final=False))

    expected_calls = ["editMessageText", "sendMessage"] if stage == "replacement_stream" else ["sendMessage"]
    assert [endpoint for endpoint, _ in request.calls[before:]] == expected_calls
    reply = request.calls[-1][1]["reply_parameters"]
    assert reply["message_id"] == 42
    state = channel._stream_messages.get(key)
    if int(chat_id) > 0:
        assert reply["allow_sending_without_reply"] is True
        assert state is not None and state["message_id"] in request.messages
        assert state["last_text"] == ("Working on it..." if stage == "running" else "Updated preview")
    else:
        assert not reply.get("allow_sending_without_reply")
        assert state is None or state["message_id"] not in request.messages


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", ["12345", "-12345"])
@pytest.mark.parametrize("stage", ["running", "initial_stream"])
async def test_existing_inbound_target_remains_attached_to_preview(telegram_channel, chat_id, stage):
    channel, request = telegram_channel
    if stage == "running":
        await channel._send_running_reply(chat_id, 42)
    else:
        await channel.send(_reply(chat_id, thread_ts="42", is_final=False))
    assert request.calls[-1][1]["reply_parameters"]["message_id"] == 42
    assert channel._stream_messages[f"{chat_id}:42"]["message_id"] in request.messages


@pytest.mark.asyncio
@pytest.mark.parametrize("is_image", [False, True])
@pytest.mark.parametrize("chat_id", ["12345", "-12345"])
async def test_deleted_file_reply_target_is_optional_only_in_private_chat(telegram_channel, tmp_path, is_image, chat_id):
    channel, request = telegram_channel
    await channel.send(_reply(chat_id))
    request.messages.clear()
    file_path = tmp_path / "output.bin"
    file_path.write_bytes(b"offline attachment")
    attachment = ResolvedAttachment("/mnt/user-data/outputs/output.bin", file_path, file_path.name, "image/png" if is_image else "application/octet-stream", file_path.stat().st_size, is_image)
    before = len(request.calls)

    assert await channel.send_file(_reply(chat_id), attachment) is (int(chat_id) > 0)

    assert [endpoint for endpoint, _ in request.calls[before:]] == ["sendPhoto" if is_image else "sendDocument"]
    assert (channel._last_bot_message[chat_id] in request.messages) is (int(chat_id) > 0)
    if int(chat_id) < 0:
        assert not request.calls[-1][1]["reply_parameters"].get("allow_sending_without_reply")


@pytest.mark.asyncio
async def test_existing_private_reply_keeps_its_reply_target(telegram_channel):
    channel, request = telegram_channel
    await channel.send(_reply())
    previous_id = channel._last_bot_message["12345"]
    await channel.send(_reply())
    assert request.calls[-1][1]["reply_parameters"]["message_id"] == previous_id


@pytest.mark.asyncio
async def test_group_missing_reply_is_not_silently_rerouted(telegram_channel):
    channel, request = telegram_channel
    await channel.send(_reply("-12345"))
    previous_id = channel._last_bot_message["-12345"]
    request.messages.clear()
    before = len(request.calls)

    with pytest.raises(BadRequest, match="(?i)message to be replied not found"):
        await channel.send(_reply("-12345"), _max_retries=1)

    assert len(request.calls) == before + 1
    assert request.calls[-1][1]["reply_parameters"] == {"message_id": previous_id}


@pytest.mark.asyncio
async def test_network_failure_does_not_add_a_replyless_resend(telegram_channel, monkeypatch):
    channel, request = telegram_channel
    await channel.send(_reply())
    previous_id = channel._last_bot_message["12345"]
    calls = []

    async def fail_request(url, method, request_data=None, **kwargs):
        calls.append(request_data.parameters)
        raise NetworkError("Ambiguous transport failure")

    monkeypatch.setattr(request, "do_request", fail_request)
    with pytest.raises(NetworkError, match="Ambiguous transport failure"):
        await channel.send(_reply(), _max_retries=1)
    assert len(calls) == 1
    assert calls[0]["reply_parameters"]["message_id"] == previous_id
    assert channel._last_bot_message["12345"] == previous_id
