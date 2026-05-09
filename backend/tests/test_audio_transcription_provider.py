from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.audio.providers.base import AudioTranscriptionProviderError
from deerflow.audio.providers.openai import OpenAITranscriptionProvider


class _AsyncClientContext:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_openai_provider_posts_multipart_and_returns_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFdemo")

    response = MagicMock()
    response.is_success = True
    response.json.return_value = {
        "text": "你好世界",
        "language": "zh",
        "duration": 1.25,
        "segments": [{"start": 0, "end": 1.25}],
    }

    client = MagicMock()
    client.post = AsyncMock(return_value=response)

    monkeypatch.setattr(
        "deerflow.audio.providers.openai.httpx.AsyncClient",
        lambda timeout: _AsyncClientContext(client),
    )

    provider = OpenAITranscriptionProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="gpt-4o-mini-transcribe",
    )

    result = asyncio.run(provider.transcribe(audio_path, locale="zh-CN"))

    assert result.transcript == "你好世界"
    assert result.language == "zh"
    assert result.duration_ms == 1250
    assert result.segments == [{"start": 0, "end": 1.25}]

    post_call = client.post.await_args
    assert post_call.args[0] == "https://example.test/v1/audio/transcriptions"
    assert post_call.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert post_call.kwargs["data"] == {
        "model": "gpt-4o-mini-transcribe",
        "language": "zh-CN",
    }

    uploaded_file = post_call.kwargs["files"]["file"]
    assert uploaded_file[0] == "sample.wav"
    assert uploaded_file[2].startswith("audio/")


def test_openai_provider_wraps_non_success_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"ID3demo")

    response = MagicMock()
    response.is_success = False
    response.json.return_value = {
        "error": {"message": "quota exceeded"},
    }
    response.text = "quota exceeded"
    response.reason_phrase = "Bad Request"

    client = MagicMock()
    client.post = AsyncMock(return_value=response)

    monkeypatch.setattr(
        "deerflow.audio.providers.openai.httpx.AsyncClient",
        lambda timeout: _AsyncClientContext(client),
    )

    provider = OpenAITranscriptionProvider(api_key="test-key")

    with pytest.raises(AudioTranscriptionProviderError, match="quota exceeded"):
        asyncio.run(provider.transcribe(audio_path, locale="en-US"))
