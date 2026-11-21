"""Transcription constructs TLS off-loop and uses async transport on-loop."""

import json
import ssl
import threading

import httpx
import pytest

from app.gateway.routers.voice_input import _transcribe
from deerflow.config.voice_input_config import VoiceInputConfig


@pytest.mark.asyncio
async def test_transcription_does_not_block_on_tls_or_network(monkeypatch):
    loop_thread = threading.get_ident()
    original = ssl.create_default_context
    contexts = []
    requests = []

    def create_context(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        contexts.append(True)
        return original(*args, **kwargs)

    async def send(_transport, request):
        assert threading.get_ident() == loop_thread
        requests.append(await request.aread())
        return httpx.Response(200, content=json.dumps({"text": "spoken task"}).encode())

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    text = await _transcribe(b"audio", "audio/webm", VoiceInputConfig(base_url="https://speech.example/v1", model="stt-test"))
    assert text == "spoken task"
    assert contexts and len(requests) == 1
