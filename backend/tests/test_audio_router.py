from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.gateway.routers import audio
from deerflow.audio.providers.base import (
    AudioTranscriptionProviderError,
    AudioTranscriptionResult,
)
from deerflow.config.audio_input_config import AudioInputConfig


class FakeUploadFile:
    def __init__(
        self,
        filename: str,
        content_type: str,
        chunks: list[bytes],
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self._chunks = list(chunks)
        self.closed = False

    async def read(self, size: int | None = None) -> bytes:
        if size is None:
            raise AssertionError("audio uploads must be read with an explicit chunk size")
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def close(self) -> None:
        self.closed = True


def call_unwrapped(decorated: Callable, /, *args, **kwargs):
    fn = decorated
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn(*args, **kwargs)


def _audio_config(**overrides) -> SimpleNamespace:
    return SimpleNamespace(
        audio_input=AudioInputConfig(
            enabled=True,
            file_transcription_enabled=True,
            **overrides,
        )
    )


def _open_regular_upload_path(uploads_dir: Path, filename: str):
    file_path = uploads_dir / filename
    return file_path, file_path.open("wb")


def test_transcribe_audio_file_rejects_when_feature_disabled() -> None:
    file = FakeUploadFile("clip.mp3", "audio/mpeg", [b"demo"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                audio.transcribe_audio_file,
                "thread-1",
                request=MagicMock(),
                file=file,
                locale=None,
                attach_original=False,
                config=SimpleNamespace(audio_input=AudioInputConfig()),
            )
        )

    assert exc_info.value.status_code == 404
    assert file.closed is True


def test_get_audio_input_config_returns_public_capabilities() -> None:
    result = asyncio.run(
        call_unwrapped(
            audio.get_audio_input_config,
            config=_audio_config(
                microphone_enabled=False,
                supported_locales=["en-US"],
                accepted_mime_types=["audio/webm"],
                max_file_size=1024,
            ),
        )
    )

    assert result.enabled is True
    assert result.microphone_enabled is False
    assert result.file_transcription_enabled is True
    assert result.default_locale == "zh-CN"
    assert result.supported_locales == ["en-US"]
    assert result.accepted_mime_types == ["audio/webm"]
    assert result.max_file_size == 1024


def test_transcribe_audio_file_rejects_unsupported_mime_type() -> None:
    file = FakeUploadFile("notes.txt", "text/plain", [b"nope"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            call_unwrapped(
                audio.transcribe_audio_file,
                "thread-1",
                request=MagicMock(),
                file=file,
                locale="zh-CN",
                attach_original=False,
                config=_audio_config(),
            )
        )

    assert exc_info.value.status_code == 415
    assert file.closed is True


def test_transcribe_audio_file_returns_transcript_and_cleans_temp_file(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True)

    file = FakeUploadFile("clip.mp3", "audio/mpeg", [b"hello", b" world"])
    provider = MagicMock()
    provider.transcribe = AsyncMock(
        return_value=AudioTranscriptionResult(
            transcript="transcribed text",
            language="zh-CN",
            duration_ms=2200,
        )
    )

    with (
        patch.object(audio, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(audio, "build_audio_transcription_provider", return_value=provider),
        patch.object(audio, "open_upload_file_no_symlink", side_effect=_open_regular_upload_path),
    ):
        result = asyncio.run(
            call_unwrapped(
                audio.transcribe_audio_file,
                "thread-1",
                request=MagicMock(),
                file=file,
                locale=None,
                attach_original=False,
                config=_audio_config(default_locale="zh-CN"),
            )
        )

    assert result.success is True
    assert result.transcript == "transcribed text"
    assert result.language == "zh-CN"
    assert result.duration_ms == 2200
    assert result.file is None
    assert file.closed is True
    assert not (uploads_dir / "clip.mp3").exists()

    transcribe_call = provider.transcribe.await_args
    assert transcribe_call.args[0].name == "clip.mp3"
    assert transcribe_call.kwargs["locale"] == "zh-CN"


def test_transcribe_audio_file_can_keep_original_and_sync_to_sandbox(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True)

    file = FakeUploadFile("clip.webm", "audio/webm", [b"webm-bytes"])
    provider = MagicMock()
    provider.transcribe = AsyncMock(
        return_value=AudioTranscriptionResult(
            transcript="transcribed text",
            language="en-US",
            duration_ms=1400,
        )
    )

    sandbox = MagicMock()
    sandbox_provider = MagicMock()
    sandbox_provider.uses_thread_data_mounts = False
    sandbox_provider.acquire.return_value = "sandbox-1"
    sandbox_provider.get.return_value = sandbox

    fake_paths = MagicMock()
    fake_paths.sandbox_uploads_dir.return_value = Path("/mnt/user-data/uploads")

    with (
        patch.object(audio, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(audio, "build_audio_transcription_provider", return_value=provider),
        patch.object(audio, "get_sandbox_provider", return_value=sandbox_provider),
        patch.object(audio, "get_paths", return_value=fake_paths),
        patch.object(audio, "open_upload_file_no_symlink", side_effect=_open_regular_upload_path),
    ):
        result = asyncio.run(
            call_unwrapped(
                audio.transcribe_audio_file,
                "thread-1",
                request=MagicMock(),
                file=file,
                locale="en-US",
                attach_original=True,
                config=_audio_config(default_locale="zh-CN"),
            )
        )

    assert result.success is True
    assert result.file is not None
    assert result.file.filename == "clip.webm"
    assert result.file.virtual_path == "/mnt/user-data/uploads/clip.webm"
    assert (uploads_dir / "clip.webm").read_bytes() == b"webm-bytes"
    sandbox_provider.acquire.assert_called_once_with("thread-1")
    sandbox.update_file.assert_called_once_with(
        "/mnt/user-data/uploads/clip.webm",
        b"webm-bytes",
    )


def test_transcribe_audio_file_cleans_up_failed_transcriptions(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True)

    file = FakeUploadFile("clip.wav", "audio/wav", [b"wav-bytes"])
    provider = MagicMock()
    provider.transcribe = AsyncMock(
        side_effect=AudioTranscriptionProviderError("provider offline")
    )

    with (
        patch.object(audio, "ensure_uploads_dir", return_value=uploads_dir),
        patch.object(audio, "build_audio_transcription_provider", return_value=provider),
        patch.object(audio, "open_upload_file_no_symlink", side_effect=_open_regular_upload_path),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                call_unwrapped(
                    audio.transcribe_audio_file,
                    "thread-1",
                    request=MagicMock(),
                    file=file,
                    locale="zh-CN",
                    attach_original=True,
                    config=_audio_config(),
                )
            )

    assert exc_info.value.status_code == 502
    assert not (uploads_dir / "clip.wav").exists()
    assert file.closed is True
