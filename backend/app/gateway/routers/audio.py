"""Gateway router for audio input capabilities and transcription uploads."""

import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.audio.providers import (
    AudioTranscriptionProviderError,
    AudioTranscriptionResult,
    build_audio_transcription_provider,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.uploads.manager import (
    UnsafeUploadPathError,
    ensure_uploads_dir,
    normalize_filename,
    open_upload_file_no_symlink,
    upload_artifact_url,
    upload_virtual_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])

UPLOAD_CHUNK_SIZE = 8192


class AudioTranscriptionFileInfo(BaseModel):
    filename: str
    size: int
    path: str
    virtual_path: str
    artifact_url: str


class AudioTranscriptionResponse(BaseModel):
    success: bool
    transcript: str
    language: str | None = None
    duration_ms: int | None = None
    file: AudioTranscriptionFileInfo | None = None


class AudioInputConfigResponse(BaseModel):
    enabled: bool
    microphone_enabled: bool
    file_transcription_enabled: bool
    default_locale: str
    supported_locales: list[str]
    accepted_mime_types: list[str]
    max_file_size: int


def _is_audio_transcription_enabled(config: AppConfig) -> bool:
    audio_config = config.audio_input
    return audio_config.enabled and audio_config.file_transcription_enabled


def _resolve_audio_locale(
    config: AppConfig,
    locale: str | None,
) -> str | None:
    requested_locale = locale or config.audio_input.default_locale
    if requested_locale not in config.audio_input.supported_locales:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported locale: {requested_locale}",
        )
    return requested_locale


def _validate_audio_upload(
    *,
    config: AppConfig,
    file: UploadFile,
) -> None:
    content_type = (file.content_type or "").strip().lower().split(";")[0].strip()
    accepted_types = {mime.lower() for mime in config.audio_input.accepted_mime_types}
    if content_type not in accepted_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio MIME type: {content_type or 'unknown'}",
        )


async def _write_audio_upload_file(
    file: UploadFile,
    *,
    uploads_dir: os.PathLike[str] | str,
    display_filename: str,
    max_file_size: int,
) -> tuple[os.PathLike[str] | str, int]:
    file_size = 0
    try:
        file_path, file_handle = open_upload_file_no_symlink(
            uploads_dir,
            display_filename,
        )
    except UnsafeUploadPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            file_size += len(chunk)
            if file_size > max_file_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file too large: {display_filename}",
                )
            file_handle.write(chunk)
    except Exception:
        file_handle.close()
        try:
            os.unlink(file_path)
        except FileNotFoundError:
            pass
        raise
    else:
        file_handle.close()
    return file_path, file_size


def _build_transcription_response(
    *,
    thread_id: str,
    filename: str,
    file_size: int,
    result: AudioTranscriptionResult,
) -> AudioTranscriptionResponse:
    sandbox_uploads = get_paths().sandbox_uploads_dir(
        thread_id,
        user_id=get_effective_user_id(),
    )
    return AudioTranscriptionResponse(
        success=True,
        transcript=result.transcript,
        language=result.language,
        duration_ms=result.duration_ms,
        file=AudioTranscriptionFileInfo(
            filename=filename,
            size=file_size,
            path=str(sandbox_uploads / filename),
            virtual_path=upload_virtual_path(filename),
            artifact_url=upload_artifact_url(thread_id, filename),
        ),
    )


@router.get("/api/audio/config", response_model=AudioInputConfigResponse)
async def get_audio_input_config(
    config: AppConfig = Depends(get_config),
) -> AudioInputConfigResponse:
    """Return the public audio input capabilities that the frontend can use."""
    audio_config = config.audio_input
    return AudioInputConfigResponse(
        enabled=audio_config.enabled,
        microphone_enabled=audio_config.microphone_enabled,
        file_transcription_enabled=audio_config.file_transcription_enabled,
        default_locale=audio_config.default_locale,
        supported_locales=list(audio_config.supported_locales),
        accepted_mime_types=list(audio_config.accepted_mime_types),
        max_file_size=audio_config.max_file_size,
    )


@router.post(
    "/api/threads/{thread_id}/audio/transcriptions",
    response_model=AudioTranscriptionResponse,
)
@require_permission("threads", "write", owner_check=True, require_existing=False)
async def transcribe_audio_file(
    thread_id: str,
    request: Request,
    file: UploadFile = File(...),
    locale: str | None = Form(default=None),
    attach_original: bool = Form(default=False),
    config: AppConfig = Depends(get_config),
) -> AudioTranscriptionResponse:
    """Transcribe an uploaded audio file into editable text."""
    file_path = None
    file_size = 0
    keep_original = False
    try:
        if not _is_audio_transcription_enabled(config):
            raise HTTPException(status_code=404, detail="Audio file transcription is disabled")
        if not file.filename:
            raise HTTPException(status_code=400, detail="No audio file provided")

        _validate_audio_upload(config=config, file=file)
        resolved_locale = _resolve_audio_locale(config, locale)

        try:
            uploads_dir = ensure_uploads_dir(thread_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        original_filename = normalize_filename(file.filename)
        provider = build_audio_transcription_provider(config.audio_input)
        file_path, file_size = await _write_audio_upload_file(
            file,
            uploads_dir=uploads_dir,
            display_filename=original_filename,
            max_file_size=config.audio_input.max_file_size,
        )
        result = await provider.transcribe(file_path, locale=resolved_locale)

        if attach_original:
            sandbox_provider = get_sandbox_provider()
            if not getattr(sandbox_provider, "uses_thread_data_mounts", False):
                sandbox_id = sandbox_provider.acquire(thread_id)
                sandbox = sandbox_provider.get(sandbox_id)
                if sandbox is None:
                    raise HTTPException(status_code=500, detail="Failed to acquire sandbox")
                sandbox.update_file(
                    upload_virtual_path(original_filename),
                    file_path.read_bytes(),
                )
            keep_original = True
            return _build_transcription_response(
                thread_id=thread_id,
                filename=original_filename,
                file_size=file_size,
                result=result,
            )

        return AudioTranscriptionResponse(
            success=True,
            transcript=result.transcript,
            language=result.language,
            duration_ms=result.duration_ms,
        )
    except AudioTranscriptionProviderError as exc:
        logger.warning("Audio transcription failed for thread %s: %s", thread_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await file.close()
        if file_path is not None and not keep_original:
            try:
                os.unlink(file_path)
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning(
                    "Failed to delete temporary audio upload after transcription: %s",
                    file_path,
                    exc_info=True,
                )
