"""Bounded, authenticated proxy to an operator-configured transcription service."""

import asyncio
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.config.voice_input_config import VoiceInputConfig
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice-input", tags=["voice-input"])
_MAX_RESPONSE_BYTES = 1024 * 1024
_AUDIO_TYPES = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3"}


class TranscriptionResponse(BaseModel):
    text: str


async def _read_audio(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            raise HTTPException(400, "Invalid audio length") from None
        if size < 0:
            raise HTTPException(400, "Invalid audio length")
        if size > limit:
            raise HTTPException(413, "Audio exceeds the size limit")
    audio = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(audio) + len(chunk) > limit:
                    raise HTTPException(413, "Audio exceeds the size limit")
                audio.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "Audio upload timed out") from None
    if not audio:
        raise HTTPException(400, "Audio is required")
    return bytes(audio)


async def _transcribe(audio: bytes, mime: str, config: VoiceInputConfig) -> str:
    headers = {"Accept-Encoding": "identity"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"
    data = {"model": config.model, "response_format": "json"}
    if config.language:
        data["language"] = config.language
    try:
        async with asyncio.timeout(config.timeout_seconds):
            # Load TLS trust before owning HTTP handles, so cancellation during
            # this filesystem work cannot leak a client built in a worker thread.
            verify = await asyncio.to_thread(httpx.create_ssl_context)
            client = httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False, verify=verify)
            try:
                async with client.stream(
                    "POST",
                    f"{config.base_url}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files={"file": (f"recording.{_AUDIO_TYPES[mime]}", audio, mime)},
                ) as response:
                    if not response.is_success:
                        raise HTTPException(502, "Transcription service failed")
                    # A decoder could allocate beyond the limit before yielding a chunk.
                    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                        raise HTTPException(502, "Invalid transcription response")
                    payload = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        if len(payload) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise HTTPException(502, "Invalid transcription response")
                        payload.extend(chunk)
            finally:
                await await_drained(client.aclose())
            result = json.loads(payload)
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise HTTPException(502, "Invalid transcription response")
        text = result["text"].strip()
        if not text:
            raise HTTPException(422, "No speech was detected")
        # JSON escapes can decode to lone surrogates that the API cannot serialize.
        text.encode("utf-8")
        return text
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Transcription service timed out") from None
    except (httpx.HTTPError, ValueError, UnicodeError):
        # Never surface or log provider URLs, credentials, audio or response bodies.
        logger.warning("Voice transcription request failed")
        raise HTTPException(502, "Transcription service failed") from None


@router.post("/transcribe", response_model=TranscriptionResponse, summary="Transcribe Composer Audio")
@require_permission("runs", "create")
async def transcribe_audio(request: Request, config: AppConfig = Depends(get_config)) -> TranscriptionResponse:
    voice = config.voice_input
    if voice is None:
        raise HTTPException(404, "Voice input is disabled")
    mime = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if mime not in _AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio format")
    # Authentication/authorization runs before reading any audio or contacting STT.
    audio = await _read_audio(request, voice.max_audio_bytes)
    return TranscriptionResponse(text=await _transcribe(audio, mime, voice))
