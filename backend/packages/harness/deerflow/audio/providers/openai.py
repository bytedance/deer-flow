"""OpenAI-compatible audio transcription provider."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

from .base import AudioTranscriptionProviderError, AudioTranscriptionResult


def _error_detail_from_response(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
    return response.text or response.reason_phrase


def _normalize_duration_ms(payload: dict[str, Any]) -> int | None:
    if "duration_ms" in payload:
        try:
            return int(payload["duration_ms"])
        except (TypeError, ValueError):
            return None

    raw_duration = payload.get("duration")
    if raw_duration is None:
        return None

    try:
        return int(float(raw_duration) * 1000)
    except (TypeError, ValueError):
        return None


class OpenAITranscriptionProvider:
    """Transcribe audio via an OpenAI-compatible `/audio/transcriptions` API."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini-transcribe",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 60.0,
        organization: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("OpenAITranscriptionProvider requires an api_key")
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._organization = organization

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._organization:
            headers["OpenAI-Organization"] = self._organization
        return headers

    async def transcribe(
        self,
        file_path: Path,
        *,
        locale: str | None = None,
    ) -> AudioTranscriptionResult:
        endpoint = f"{self._base_url}/audio/transcriptions"
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        data: dict[str, str] = {"model": self._model}
        if locale:
            data["language"] = locale

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
                f"Audio transcription request failed: {exc}",
            ) from exc

        if not response.is_success:
            raise AudioTranscriptionProviderError(
                f"Audio transcription request failed: {_error_detail_from_response(response)}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AudioTranscriptionProviderError(
                "Audio transcription provider returned invalid JSON",
            ) from exc

        if not isinstance(payload, dict):
            raise AudioTranscriptionProviderError(
                "Audio transcription provider returned an unexpected response payload",
            )

        transcript = payload.get("text") or payload.get("transcript") or ""
        if not isinstance(transcript, str) or not transcript.strip():
            raise AudioTranscriptionProviderError(
                "Audio transcription provider returned an empty transcript",
            )

        raw_segments = payload.get("segments")
        segments = raw_segments if isinstance(raw_segments, list) else []
        language = payload.get("language")
        normalized_language = language if isinstance(language, str) else None

        return AudioTranscriptionResult(
            transcript=transcript.strip(),
            language=normalized_language,
            duration_ms=_normalize_duration_ms(payload),
            segments=[segment for segment in segments if isinstance(segment, dict)],
            raw_response=payload,
        )
