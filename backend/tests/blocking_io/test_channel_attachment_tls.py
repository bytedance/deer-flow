"""Channel attachment TLS setup must not block the Gateway event loop.

Building ``httpx.AsyncClient`` loads the CA bundle synchronously via
``ssl.create_default_context`` / ``SSLContext.load_verify_locations``. Slack and
Discord used to construct it inline inside ``receive_file``, so a single
attachment download stalled every other coroutine on the same worker. The
constructor now runs in ``asyncio.to_thread``; the async stream and cleanup
still run on the loop. These tests pin the certificate-loading thread explicitly
because the strict blocking-I/O detector cannot see the native loader call.
"""

import asyncio
import ssl
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.channels.discord import DiscordChannel
from app.channels.inbound_files import open_inbound_http_client
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


@pytest.mark.parametrize("extra_cancel", [0, 1])
async def test_cancelled_client_construction_is_closed(extra_cancel):
    """A client built after cancellation must still be closed, not leaked.

    ``asyncio.to_thread`` cannot be cancelled once its worker starts. Without
    shielding and draining, the client built after the caller was cancelled
    would be discarded with no ``aclose()``. Repeated cancellation must not
    abandon the drain either.
    """
    construction_entered = threading.Event()
    release = threading.Event()
    loop_thread = threading.get_ident()
    clients = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            assert threading.get_ident() != loop_thread, "construction must be off the loop"
            construction_entered.set()
            assert release.wait(timeout=10), "construction was never released"
            self.closed = False
            clients.append(self)

        async def aclose(self):
            self.closed = True

    def fake_client_factory(*args, **kwargs):
        return FakeClient(*args, **kwargs)

    with patch.object(httpx, "AsyncClient", fake_client_factory):
        waiter = asyncio.create_task(open_inbound_http_client(timeout=httpx.Timeout(20.0)))
        await asyncio.wait_for(asyncio.to_thread(construction_entered.wait, 10), timeout=10)
        waiter.cancel()
        if extra_cancel:
            await asyncio.sleep(0)  # second cancellation while the drain is running
            waiter.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    assert len(clients) == 1, "exactly one client should have been constructed"
    assert clients[0].closed, "the late client must be closed exactly once"
