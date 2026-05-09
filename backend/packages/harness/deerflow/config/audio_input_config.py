"""Audio input configuration for browser speech and audio file transcription."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


def _default_audio_mime_types() -> list[str]:
    return [
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/x-m4a",
        "audio/aac",
        "audio/flac",
    ]


def _default_supported_locales() -> list[str]:
    return ["zh-CN", "en-US"]


class AudioInputProviderConfig(BaseModel):
    """Provider configuration for audio transcription."""

    use: str = Field(
        default="deerflow.audio.providers.openai:OpenAITranscriptionProvider",
        description="Class path to the audio transcription provider implementation",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific configuration values",
    )


class AudioInputConfig(BaseModel):
    """Configuration for chat audio input features."""

    enabled: bool = Field(default=False, description="Enable audio input support")
    microphone_enabled: bool = Field(
        default=True,
        description="Enable browser microphone speech recognition entry points",
    )
    file_transcription_enabled: bool = Field(
        default=False,
        description="Enable audio file upload transcription",
    )
    default_locale: str = Field(
        default="zh-CN",
        description="Default locale to pass to transcription providers",
    )
    supported_locales: list[str] = Field(
        default_factory=_default_supported_locales,
        description="Locales accepted by the gateway audio endpoint",
    )
    accepted_mime_types: list[str] = Field(
        default_factory=_default_audio_mime_types,
        description="Accepted MIME types for uploaded audio files",
    )
    max_file_size: int = Field(
        default=25 * 1024 * 1024,
        description="Maximum audio file size in bytes",
    )
    provider: AudioInputProviderConfig = Field(
        default_factory=AudioInputProviderConfig,
        description="Transcription provider configuration",
    )


_audio_input_config: AudioInputConfig | None = None


def get_audio_input_config() -> AudioInputConfig:
    """Return the active audio input configuration singleton."""
    global _audio_input_config
    if _audio_input_config is None:
        _audio_input_config = AudioInputConfig()
    return _audio_input_config


def load_audio_input_config_from_dict(data: dict | None) -> AudioInputConfig:
    """Load audio input configuration from a dictionary."""
    global _audio_input_config
    _audio_input_config = AudioInputConfig.model_validate(data or {})
    return _audio_input_config


def reset_audio_input_config() -> None:
    """Reset the audio input configuration singleton."""
    global _audio_input_config
    _audio_input_config = None
