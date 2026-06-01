"""Qwen3-ASR audio transcription provider via DashScope multimodal API.

Usage in config.yaml:
  provider:
    use: deerflow.audio.providers.qwen_asr:QwenASRTranscriptionProvider
    config:
      model: qwen3-asr-flash
      api_key: your-dashscope-api-key
      base_url: https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from .base import AudioTranscriptionProviderError, AudioTranscriptionResult


class QwenASRTranscriptionProvider:
    """Transcribe audio using Qwen3-ASR via DashScope multimodal-generation API."""

    def __init__(
        self,
        *,
        model: str = "qwen3-asr-flash",
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        timeout_s: float = 120.0,
        **_kwargs: Any,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("QwenASRTranscriptionProvider requires an api_key")
        self._endpoint = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def transcribe(
        self,
        file_path: Path,
        *,
        locale: str | None = None,
    ) -> AudioTranscriptionResult:
        content_type = mimetypes.guess_type(file_path.name)[0] or "audio/wav"
        audio_bytes = file_path.read_bytes()

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        data_uri = f"data:{content_type};base64,{b64}"

        body: dict[str, Any] = {
            "model": self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"audio": data_uri}],
                    }
                ],
            },
            "parameters": {},
        }

        if locale:
            lang = locale.split("-")[0]
            body["parameters"]["asr_options"] = {"language": lang}

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    self._endpoint,
                    headers=self._headers(),
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise AudioTranscriptionProviderError(
                f"Qwen3-ASR transcription request failed: {exc}",
            ) from exc

        if not response.is_success:
            try:
                error_payload = response.json()
                error_msg = error_payload.get("message") or error_payload.get("detail", response.text)
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

        try:
            content_parts = payload["output"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AudioTranscriptionProviderError(
                "Qwen3-ASR returned unexpected response format",
            ) from exc

        transcript = "".join(
            part.get("text", "") for part in content_parts if isinstance(part, dict)
        ).strip()

        if not transcript:
            raise AudioTranscriptionProviderError(
                "Qwen3-ASR returned empty transcript",
            )

        usage = payload.get("usage", {})
        duration_ms = None
        seconds = usage.get("seconds")
        if seconds is not None:
            try:
                duration_ms = int(float(seconds) * 1000)
            except (TypeError, ValueError):
                pass

        return AudioTranscriptionResult(
            transcript=transcript,
            language=locale,
            duration_ms=duration_ms,
            segments=[],
            raw_response=payload,
        )
