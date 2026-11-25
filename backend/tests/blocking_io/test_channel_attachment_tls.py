"""Channel attachment TLS setup must not block the Gateway event loop.

Building ``httpx.AsyncClient`` loads the CA bundle synchronously via
``ssl.create_default_context`` / ``SSLContext.load_verify_locations``. Slack and
Discord used to construct it inline inside ``receive_file``, so a single
attachment download stalled every other coroutine on the same worker. The
constructor now runs in ``asyncio.to_thread``; the async stream and cleanup
still run on the loop. These tests pin the certificate-loading thread explicitly
because the strict blocking-I/O detector cannot see the native loader call.
"""

import ssl
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import INBOUND_FILE_CONTENT_KEY, InboundMessage, MessageBus
from app.channels.slack import SlackChannel

pytestmark = pytest.mark.asyncio


class _Body(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"data"


async def _assert_tls_off_loop(channel, url_key, url):
    loop_thread = threading.get_ident()
    context_threads = []

    original_create = ssl.create_default_context

    def record_context(*args, **kwargs):
        context_threads.append(threading.get_ident())
        return original_create(*args, **kwargs)

    async def respond(self, request):
        assert threading.get_ident() == loop_thread
        return httpx.Response(200, request=request, stream=_Body())

    message = InboundMessage(
        channel.name,
        "chat",
        "sender",
        "caption",
        files=[{"type": "file", "filename": "report.txt", "size": 4, url_key: url}],
    )
    with (
        patch.object(ssl, "create_default_context", record_context),
        patch.object(httpx.AsyncHTTPTransport, "handle_async_request", respond),
    ):
        result = await channel.receive_file(message, "thread")

    assert context_threads, "the real HTTPX TLS initialization must run"
    assert loop_thread not in context_threads, "TLS setup must run off the event loop"
    assert result.files[0][INBOUND_FILE_CONTENT_KEY] == b"data", "body must be preserved"


@pytest.mark.parametrize("channel_kind", ["slack", "discord"])
async def test_attachment_tls_loading_runs_off_event_loop(channel_kind, tmp_path: Path):
    if channel_kind == "slack":
        channel = SlackChannel(
            MessageBus(),
            {"channel_store": SimpleNamespace(channels_dir=tmp_path)},
        )
        channel._web_client = SimpleNamespace(token="synthetic-token")
        url_key, url = "url_private_download", "https://files.slack.com/files-pri/T/download/report.txt"
    else:
        channel = DiscordChannel(
            MessageBus(),
            {
                "bot_token": "synthetic-token",
                "channel_store": SimpleNamespace(channels_dir=tmp_path),
            },
        )
        url_key, url = "url", "https://cdn.discordapp.com/attachments/1/2/report.txt"

    await _assert_tls_off_loop(channel, url_key, url)
