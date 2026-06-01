"""Qwen3-ASR transcription provider for self-hosted vLLM OpenAI-compatible API.

Usage in config.yaml:
  provider:
    use: deerflow.audio.providers.qwen_asr_openai_compat:QwenASROpenAICompatProvider
    config:
      model: Qwen3-ASR-1.7B
      api_key: $VLLM_API_KEY
      base_url: http://localhost:8000/v1
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from .base import AudioTranscriptionProviderError, AudioTranscriptionResult


class QwenASROpenAICompatProvider:
    """Transcribe audio via self-hosted Qwen3-ASR using OpenAI-compatible /audio/transcriptions."""

    def __init__(
        self,
        *,
        model: str = "Qwen3-ASR-1.7B",
        api_key: str | None = None,
        base_url: str = "http://localhost:8000/v1",
        timeout_s: float = 120.0,
        **_kwargs: Any,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("VLLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("QwenASROpenAICompatProvider requires an api_key")
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def transcribe(
        self,
        file_path: Path,
        *,
        locale: str | None = None,
    ) -> AudioTranscriptionResult:
        endpoint = f"{self._base_url}/audio/transcriptions"
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        data: dict[str, str] = {
            "model": self._model,
            "response_format": "json",
        }
        if locale:
            data["language"] = locale.split("-")[0]

        try:
            with file_path.open("rb") as file_handle:
                files = {
                    "file": (
                        file_path.name,
                        file_handle,
                        content_type,
                    )
                }
                async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                    response = await client.post(
                        endpoint,
                        headers=self._headers(),
                        data=data,
                        files=files,
                    )
        except httpx.HTTPError as exc:
            raise AudioTranscriptionProviderError(
                f"Qwen3-ASR transcription request failed: {exc}",
            ) from exc

        if not response.is_success:
            try:
                error_payload = response.json()
                error_msg = error_payload.get("error", {}).get("message", response.text)
            except ValueError:
                error_msg = response.text or response.reason_phrase
            raise AudioTranscriptionProviderError(
                f"Qwen3-ASR transcription failed: {error_msg}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AudioTranscriptionProviderError(
                "Qwen3-ASR returned invalid JSON response",
            ) from exc

        if not isinstance(payload, dict):
            raise AudioTranscriptionProviderError(
                "Qwen3-ASR returned unexpected response format",
            )

        transcript = payload.get("text") or payload.get("transcript") or ""
        if not isinstance(transcript, str) or not transcript.strip():
            raise AudioTranscriptionProviderError(
                "Qwen3-ASR returned empty transcript",
            )

        language = payload.get("language")
        duration_ms = None
        raw_duration = payload.get("duration")
        if raw_duration is not None:
            try:
                duration_ms = int(float(raw_duration) * 1000)
            except (TypeError, ValueError):
                pass

        # vLLM may nest duration under usage.seconds
        if duration_ms is None:
            usage = payload.get("usage")
            if isinstance(usage, dict):
                usage_seconds = usage.get("seconds")
                if usage_seconds is not None:
                    try:
                        duration_ms = int(float(usage_seconds) * 1000)
                    except (TypeError, ValueError):
                        pass

        segments = payload.get("segments", [])
        return AudioTranscriptionResult(
            transcript=transcript.strip(),
            language=language if isinstance(language, str) else None,
            duration_ms=duration_ms,
            segments=segments if isinstance(segments, list) else [],
            raw_response=payload,
        )
