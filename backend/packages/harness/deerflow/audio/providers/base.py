"""Common audio transcription provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from deerflow.config.audio_input_config import AudioInputConfig, get_audio_input_config
from deerflow.reflection.resolvers import resolve_variable


@dataclass(slots=True)
class AudioTranscriptionResult:
    transcript: str
    language: str | None = None
    duration_ms: int | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None


class AudioTranscriptionProviderError(RuntimeError):
    """Raised when a transcription provider request fails."""


@runtime_checkable
class AudioTranscriptionProvider(Protocol):
    async def transcribe(
        self,
        file_path: Path,
        *,
        locale: str | None = None,
    ) -> AudioTranscriptionResult: ...


def build_audio_transcription_provider(
    config: AudioInputConfig | None = None,
) -> AudioTranscriptionProvider:
    """Instantiate the configured audio transcription provider."""
    resolved_config = config or get_audio_input_config()
    provider_path = resolved_config.provider.use.strip()
    if not provider_path:
        raise ValueError("audio_input.provider.use must not be empty")

    provider_cls = resolve_variable(provider_path)
    provider = provider_cls(**resolved_config.provider.config)
    if not isinstance(provider, AudioTranscriptionProvider):
        if not hasattr(provider, "transcribe"):
            raise TypeError(
                f"Configured audio provider {provider_path!r} does not implement transcribe()",
            )
    return provider
