import asyncio
import logging
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import BinaryIO, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.gateway.deps import get_config, require_admin_user
from app.gateway.path_utils import resolve_thread_virtual_path
from deerflow.agents.lead_agent.prompt import clear_skills_system_prompt_cache, refresh_skills_system_prompt_cache_async, refresh_user_skills_system_prompt_cache_async
from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import (
    ExtensionsConfig,
    SkillStateConfig,
    atomic_write_extensions_config,
    extensions_config_file_lock,
    extensions_config_write_lock,
    get_extensions_config,
    reload_extensions_config,
)
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.skills import Skill
from deerflow.skills.installer import SkillAlreadyExistsError, SkillSecurityScanError
from deerflow.skills.security_scanner import scan_skill_content
from deerflow.skills.security_static_scanner import (
    StaticFinding,
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
)
from deerflow.skills.storage import SkillStorage, get_or_new_user_skill_storage
from deerflow.skills.types import SKILL_MD_FILE, SkillCategory
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["skills"])

_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage skills."
_MAX_SKILL_ARCHIVE_UPLOAD_BYTES = 100 * 1024 * 1024
_MAX_SKILL_ARCHIVE_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
_UPLOAD_COPY_CHUNK_BYTES = 1024 * 1024


class _SkillArchiveUploadTooLargeError(MultiPartException):
    """Abort multipart parsing while Starlette can still close spool files."""


class _BoundedSkillArchiveMultiPartParser(MultiPartParser):
    """Apply a byte limit to file parts before Starlette writes them to disk."""

    def __init__(self, headers: Headers, stream: AsyncGenerator[bytes, None], *, max_file_bytes: int) -> None:
        super().__init__(headers, stream, max_files=1, max_fields=0)
        self._max_file_bytes = max_file_bytes
        self._current_file_bytes = 0

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._current_file_bytes = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self._current_file_bytes += end - start
            if self._current_file_bytes > self._max_file_bytes:
                raise _SkillArchiveUploadTooLargeError(_skill_archive_upload_limit_message())
        super().on_part_data(data, start, end)


class SkillResponse(BaseModel):
    """Response model for skill information."""

    name: str = Field(..., description="Name of the skill")
    description: str = Field(..., description="Description of what the skill does")
    license: str | None = Field(None, description="License information")
    category: SkillCategory = Field(..., description="Category of the skill (public, custom, or legacy)")
    enabled: bool = Field(default=True, description="Whether this skill is enabled")
    editable: bool = Field(default=False, description="Whether this skill can be edited/deleted (true only for custom)")


class SkillsListResponse(BaseModel):
    """Response model for listing all skills."""

    skills: list[SkillResponse]


class SkillUpdateRequest(BaseModel):
    """Request model for updating a skill."""

    enabled: bool = Field(..., description="Whether to enable or disable the skill")


class SkillInstallRequest(BaseModel):
    """Request model for installing a skill from a .skill file."""

    thread_id: ThreadId = Field(..., description="The thread ID where the .skill file is located")
    path: str = Field(..., description="Virtual path to the .skill file (e.g., mnt/user-data/outputs/my-skill.skill)")


class SkillInstallResponse(BaseModel):
    """Response model for skill installation."""

    success: bool = Field(..., description="Whether the installation was successful")
    skill_name: str = Field(..., description="Name of the installed skill")
    message: str = Field(..., description="Installation result message")


class SkillReloadResponse(BaseModel):
    """Response model for process-local skill cache invalidation."""

    success: bool = Field(..., description="Whether the skill caches were invalidated")
    scope: Literal["process"] = Field(..., description="Reload scope; only the current Gateway process is affected")
    message: str = Field(..., description="Human-readable reload status")


class CustomSkillContentResponse(SkillResponse):
    content: str = Field(..., description="Raw SKILL.md content")


class CustomSkillUpdateRequest(BaseModel):
    content: str = Field(..., description="Replacement SKILL.md content")


class CustomSkillHistoryResponse(BaseModel):
    history: list[dict]


class SkillRollbackRequest(BaseModel):
    history_index: int = Field(default=-1, description="History entry index to restore from, defaulting to the latest change.")


def _skill_to_response(skill: Skill) -> SkillResponse:
    """Convert a Skill object to a SkillResponse."""
    return SkillResponse(
        name=skill.name,
        description=skill.description,
        license=skill.license,
        category=skill.category,
        enabled=skill.enabled,
        editable=skill.category == SkillCategory.CUSTOM,
    )


def _static_scan_http_detail(error: StaticScanBlockedError) -> dict:
    return {
        "message": str(error),
        "skill_name": error.skill_name,
        "findings": error.findings,
    }


async def _scan_static_skill_markdown_or_raise(skill_name: str, content: str, *, app_config: AppConfig) -> list[StaticFinding]:
    def _scan_markdown() -> list[StaticFinding]:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / skill_name
            skill_dir.mkdir(parents=True)
            (skill_dir / SKILL_MD_FILE).write_text(content, encoding="utf-8")
            return enforce_static_scan(skill_dir, skill_name=skill_name, app_config=app_config)

    try:
        return await asyncio.to_thread(_scan_markdown)
    except StaticScanBlockedError as e:
        raise HTTPException(status_code=400, detail=_static_scan_http_detail(e)) from e
    except StaticScannerError as e:
        raise HTTPException(status_code=400, detail=f"Static security scan failed for skill '{skill_name}': {e}") from e


def _get_user_skill_storage(config: AppConfig) -> SkillStorage:
    """Return a user-scoped skill storage for custom skill operations.

    Uses the effective user_id from the request context (set by auth middleware).
    For public skill reads, the global singleton storage is still used.
    """
    return get_or_new_user_skill_storage(get_effective_user_id(), app_config=config)


def _copy_uploaded_skill_archive(source: BinaryIO) -> Path:
    """Copy an uploaded archive to a bounded temporary file off the event loop."""
    destination: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="deerflow-skill-", suffix=".skill", delete=False) as target:
            destination = Path(target.name)
            total = 0
            while chunk := source.read(_UPLOAD_COPY_CHUNK_BYTES):
                total += len(chunk)
                if total > _MAX_SKILL_ARCHIVE_UPLOAD_BYTES:
                    raise _SkillArchiveUploadTooLargeError(_skill_archive_upload_limit_message())
                target.write(chunk)
        return destination
    except Exception:
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise


def _skill_archive_upload_limit_message() -> str:
    return f"Skill archive exceeds the {_MAX_SKILL_ARCHIVE_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit"


async def _bounded_skill_archive_request_stream(request: Request) -> AsyncGenerator[bytes, None]:
    """Reject oversized multipart bodies while they are still being received."""
    request_limit = _MAX_SKILL_ARCHIVE_UPLOAD_BYTES + _MAX_SKILL_ARCHIVE_MULTIPART_OVERHEAD_BYTES
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > request_limit:
            raise _SkillArchiveUploadTooLargeError(_skill_archive_upload_limit_message())

    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > request_limit:
            raise _SkillArchiveUploadTooLargeError(_skill_archive_upload_limit_message())
        yield chunk


async def _parse_skill_archive_form(request: Request) -> FormData:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.partition(";")[0].strip().casefold()
    if media_type != "multipart/form-data":
        raise HTTPException(status_code=422, detail="Expected a multipart form upload")

    parser = _BoundedSkillArchiveMultiPartParser(
        request.headers,
        _bounded_skill_archive_request_stream(request),
        max_file_bytes=_MAX_SKILL_ARCHIVE_UPLOAD_BYTES,
    )
    return await parser.parse()


async def _install_skill_archive(archive_path: Path, config: AppConfig) -> SkillInstallResponse:
    try:
        result = await _get_user_skill_storage(config).ainstall_skill_from_archive(archive_path)
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return SkillInstallResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SkillAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SkillSecurityScanError as e:
        if e.findings:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(e),
                    "skill_name": e.skill_name,
                    "findings": e.findings,
                },
            ) from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to install skill: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to install skill: {str(e)}") from e


@router.get(
    "/skills",
    response_model=SkillsListResponse,
    summary="List All Skills",
    description="Retrieve a list of all available skills from both public and custom directories.",
)
async def list_skills(config: AppConfig = Depends(get_config)) -> SkillsListResponse:
    try:
        # Use user-scoped storage: loads public (global) + custom (user-level + fallback)
        skills = _get_user_skill_storage(config).load_skills(enabled_only=False)
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error(f"Failed to load skills: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load skills: {str(e)}")


@router.post(
    "/skills/install",
    response_model=SkillInstallResponse,
    summary="Install Skill",
    description="Install a skill from a .skill file (ZIP archive) located in the thread's user-data directory.",
)
async def install_skill(request: Request, body: SkillInstallRequest, config: AppConfig = Depends(get_config)) -> SkillInstallResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_file_path = resolve_thread_virtual_path(body.thread_id, body.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await _install_skill_archive(skill_file_path, config)


@router.post(
    "/skills/install/upload",
    response_model=SkillInstallResponse,
    summary="Upload and Install Skill",
    description="Upload a local .skill archive and install it for the current user.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["archive"],
                        "properties": {"archive": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_and_install_skill(
    request: Request,
    config: AppConfig = Depends(get_config),
) -> SkillInstallResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    form: FormData | None = None
    temporary_path: Path | None = None
    try:
        form = await _parse_skill_archive_form(request)
        archive = form.get("archive")
        if not isinstance(archive, UploadFile):
            raise HTTPException(status_code=422, detail="Multipart field 'archive' must contain a file")

        filename = archive.filename or ""
        if not filename.casefold().endswith(".skill"):
            raise HTTPException(status_code=400, detail="Skill archive filename must end with .skill")

        await archive.seek(0)
        temporary_path = await asyncio.to_thread(_copy_uploaded_skill_archive, archive.file)
        return await _install_skill_archive(temporary_path, config)
    except _SkillArchiveUploadTooLargeError as e:
        raise HTTPException(status_code=413, detail=e.message) from e
    except MultiPartException as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    finally:
        if form is not None:
            await form.close()
        if temporary_path is not None:
            await asyncio.to_thread(temporary_path.unlink, missing_ok=True)


@router.post(
    "/skills/reload",
    response_model=SkillReloadResponse,
    summary="Reload Skills",
    description=("Invalidate skill prompt caches for all users in the current Gateway process. Subsequent runs rescan the configured skill directories; running tasks and other Gateway processes are unaffected."),
)
async def reload_skills(request: Request) -> SkillReloadResponse:
    """Invalidate process-local skill prompt caches after external file changes."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        await refresh_skills_system_prompt_cache_async()
    except Exception as exc:
        logger.exception("Failed to invalidate skills cache")
        raise HTTPException(status_code=500, detail="Failed to invalidate skills cache.") from exc

    return SkillReloadResponse(
        success=True,
        scope="process",
        message="Skill caches invalidated; subsequent runs in this Gateway process will rescan the latest skills.",
    )


@router.get("/skills/custom", response_model=SkillsListResponse, summary="List Custom Skills")
async def list_custom_skills(config: AppConfig = Depends(get_config)) -> SkillsListResponse:
    """List only user-owned custom skills (SkillCategory.CUSTOM).

    Legacy shared skills (SkillCategory.LEGACY) are NOT included here —
    they are read-only and appear in the full ``list_skills`` endpoint.
    The frontend should use ``list_skills`` to display all available
    skills including legacy ones.
    """
    try:
        skills = [skill for skill in _get_user_skill_storage(config).load_skills(enabled_only=False) if skill.category == SkillCategory.CUSTOM]
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error("Failed to list custom skills: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list custom skills: {str(e)}")


@router.get("/skills/custom/{skill_name}", response_model=CustomSkillContentResponse, summary="Get Custom Skill Content")
async def get_custom_skill(skill_name: str, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    return await _read_custom_skill_response(skill_name, config)


async def _read_custom_skill_response(skill_name: str, config: AppConfig) -> CustomSkillContentResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        skills = storage.load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name and s.category == SkillCategory.CUSTOM), None)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        return CustomSkillContentResponse(**_skill_to_response(skill).model_dump(), content=storage.read_custom_skill(skill_name))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get custom skill: {str(e)}")


@router.put("/skills/custom/{skill_name}", response_model=CustomSkillContentResponse, summary="Edit Custom Skill")
async def update_custom_skill(skill_name: str, body: CustomSkillUpdateRequest, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        storage.ensure_custom_skill_is_editable(skill_name)
        storage.validate_skill_markdown_content(skill_name, body.content)
        static_findings = await _scan_static_skill_markdown_or_raise(skill_name, body.content, app_config=config)
        scan = await scan_skill_content(body.content, executable=False, location=f"{skill_name}/{SKILL_MD_FILE}", app_config=config, static_findings=static_findings)
        if scan.decision == "block":
            raise HTTPException(status_code=400, detail=f"Security scan blocked the edit: {scan.reason}")
        prev_content = storage.read_custom_skill(skill_name)
        await asyncio.to_thread(storage.write_custom_skill, skill_name, SKILL_MD_FILE, body.content)
        await asyncio.to_thread(
            storage.append_history,
            skill_name,
            {
                "action": "human_edit",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": prev_content,
                "new_content": body.content,
                "scanner": {"decision": scan.decision, "reason": scan.reason, "static_findings": static_findings},
            },
        )
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return await _read_custom_skill_response(skill_name, config)
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to update custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update custom skill: {str(e)}")


@router.delete("/skills/custom/{skill_name}", summary="Delete Custom Skill")
async def delete_custom_skill(skill_name: str, request: Request, config: AppConfig = Depends(get_config)) -> dict[str, bool]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        storage = _get_user_skill_storage(config)
        await asyncio.to_thread(
            storage.delete_custom_skill,
            skill_name,
            history_meta={
                "action": "human_delete",
                "author": "human",
                "thread_id": None,
                "file_path": SKILL_MD_FILE,
                "prev_content": None,
                "new_content": None,
                "scanner": {"decision": "allow", "reason": "Deletion requested."},
            },
        )
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to delete custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete custom skill: {str(e)}")


@router.get("/skills/custom/{skill_name}/history", response_model=CustomSkillHistoryResponse, summary="Get Custom Skill History")
async def get_custom_skill_history(skill_name: str, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillHistoryResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")

        def _read_history() -> list[dict] | None:
            # Worker thread: storage construction, the existence probes, and the
            # history-file read are blocking filesystem IO that must stay off the
            # event loop. None signals 404 to the caller.
            storage = _get_user_skill_storage(config)
            if not storage.custom_skill_exists(skill_name) and not storage.get_skill_history_file(skill_name).exists():
                return None
            return storage.read_history(skill_name)

        history = await asyncio.to_thread(_read_history)
        if history is None:
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        return CustomSkillHistoryResponse(history=history)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to read history for %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read history: {str(e)}")


@router.post("/skills/custom/{skill_name}/rollback", response_model=CustomSkillContentResponse, summary="Rollback Custom Skill")
async def rollback_custom_skill(skill_name: str, body: SkillRollbackRequest, request: Request, config: AppConfig = Depends(get_config)) -> CustomSkillContentResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        storage = _get_user_skill_storage(config)
        if not storage.custom_skill_exists(skill_name) and not storage.get_skill_history_file(skill_name).exists():
            raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found")
        history = storage.read_history(skill_name)
        if not history:
            raise HTTPException(status_code=400, detail=f"Custom skill '{skill_name}' has no history")
        record = history[body.history_index]
        target_content = record.get("prev_content")
        if target_content is None:
            raise HTTPException(status_code=400, detail="Selected history entry has no previous content to roll back to")
        storage.validate_skill_markdown_content(skill_name, target_content)
        static_findings = await _scan_static_skill_markdown_or_raise(skill_name, target_content, app_config=config)
        scan = await scan_skill_content(target_content, executable=False, location=f"{skill_name}/{SKILL_MD_FILE}", app_config=config, static_findings=static_findings)
        skill_file = storage.get_custom_skill_file(skill_name)
        current_content = skill_file.read_text(encoding="utf-8") if skill_file.exists() else None
        history_entry = {
            "action": "rollback",
            "author": "human",
            "thread_id": None,
            "file_path": SKILL_MD_FILE,
            "prev_content": current_content,
            "new_content": target_content,
            "rollback_from_ts": record.get("ts"),
            "scanner": {"decision": scan.decision, "reason": scan.reason, "static_findings": static_findings},
        }
        if scan.decision == "block":
            await asyncio.to_thread(storage.append_history, skill_name, history_entry)
            raise HTTPException(status_code=400, detail=f"Rollback blocked by security scanner: {scan.reason}")
        await asyncio.to_thread(storage.write_custom_skill, skill_name, SKILL_MD_FILE, target_content)
        await asyncio.to_thread(storage.append_history, skill_name, history_entry)
        await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())
        return await _read_custom_skill_response(skill_name, config)
    except HTTPException:
        raise
    except IndexError:
        raise HTTPException(status_code=400, detail="history_index is out of range")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to roll back custom skill %s: %s", skill_name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to roll back custom skill: {str(e)}")


@router.get(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Get Skill Details",
    description="Retrieve detailed information about a specific skill by its name.",
)
async def get_skill(skill_name: str, config: AppConfig = Depends(get_config)) -> SkillResponse:
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")
        skills = _get_user_skill_storage(config).load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        return _skill_to_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get skill: {str(e)}")


def _write_extensions_skill_state(
    storage: SkillStorage,
    skill_name: str,
    enabled: bool,
    *,
    rebuild_public_projection: bool,
) -> None:
    """Read-modify-write a skill's enabled state in the shared extensions_config.json.

    Blocking filesystem IO: always call this via ``asyncio.to_thread``. It takes
    the public projection lock before the process-local and cross-process
    extensions config locks. The first keeps the enabled-only view synchronized
    across workers; the latter two prevent this router and the MCP router from
    interleaving writes to the shared file. All locks are held by the worker, so
    request cancellation cannot release them while the write or projection
    rebuild is still running.
    """
    from contextlib import nullcontext

    from deerflow.skills.projection import skill_projection_mutation
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

    removal_names = (skill_name,) if not enabled else ()
    projection_update = skill_projection_mutation(storage, "public", remove_names=removal_names) if rebuild_public_projection and isinstance(storage, LocalSkillStorage) else nullcontext()
    config_path = ExtensionsConfig.resolve_config_path()
    if config_path is None:
        config_path = Path.cwd().parent / "extensions_config.json"
        logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

    with projection_update:
        with extensions_config_write_lock, extensions_config_file_lock(config_path):
            # The projection lock is cross-process, but the singleton cache is
            # not. Existing files are therefore re-read under the lock; a new
            # file starts from a deep snapshot of the cached defaults.
            extensions_config = ExtensionsConfig.from_file(config_path) if config_path.exists() else get_extensions_config().model_copy(deep=True)
            extensions_config.skills[skill_name] = SkillStateConfig(enabled=enabled)

            config_data = extensions_config.to_file_dict()
            atomic_write_extensions_config(config_path, config_data)

            logger.info(f"Skills configuration updated and saved to: {config_path}")
            reload_extensions_config()


@router.put(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Update Skill",
    description="Update a skill's enabled status by modifying the extensions_config.json file.",
)
async def update_skill(skill_name: str, body: SkillUpdateRequest, request: Request, config: AppConfig = Depends(get_config)) -> SkillResponse:
    # Enabling/disabling a skill writes the shared extensions_config.json and
    # refreshes the system prompt for every tenant, so it is a global mutation
    # (there is no per-user skill state). Guard it as admin-only like the other
    # global config writes, matching the MCP router.
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        skill_name = skill_name.replace("\r\n", "").replace("\n", "")

        def _load_storage_and_skills() -> tuple[SkillStorage, list[Skill]]:
            # Worker thread: storage construction and skill enumeration both walk
            # the filesystem.
            storage = _get_user_skill_storage(config)
            return storage, storage.load_skills(enabled_only=False)

        storage, skills = await asyncio.to_thread(_load_storage_and_skills)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        # PUBLIC skills → global extensions_config.json (shared state).
        # CUSTOM / LEGACY skills → per-user _skill_states.json (isolated state)
        # so that two users with same-named custom skills can toggle independently.
        if skill.category == SkillCategory.PUBLIC:
            await asyncio.to_thread(
                _write_extensions_skill_state,
                storage,
                skill_name,
                body.enabled,
                rebuild_public_projection=True,
            )
        else:
            # CUSTOM / LEGACY: write per-user state
            from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

            if isinstance(storage, UserScopedSkillStorage):
                await asyncio.to_thread(storage.set_skill_enabled_state, skill_name, body.enabled)
            else:
                # Fallback for non-user-scoped storage (unlikely in practice):
                # same shared-file RMW as the PUBLIC branch, without a public
                # projection rebuild for this non-public skill.
                await asyncio.to_thread(
                    _write_extensions_skill_state,
                    storage,
                    skill_name,
                    body.enabled,
                    rebuild_public_projection=False,
                )

        # PUBLIC skill enabled state lives in the global extensions_config.json
        # and affects every user, so the prompt cache for ALL users must be
        # invalidated. CUSTOM/LEGACY skill state is per-user so only that
        # user's cache needs to be dropped.
        if skill.category == SkillCategory.PUBLIC:
            # clear_skills_system_prompt_cache is sync; run it in a worker
            # thread to avoid blocking the event loop. The lock inside it is
            # cheap, but the async drop also keeps the test mock surface
            # consistent (tests patch the async variant).
            await asyncio.to_thread(clear_skills_system_prompt_cache)
        else:
            await refresh_user_skills_system_prompt_cache_async(get_effective_user_id())

        def _reload_skills() -> list[Skill]:
            return _get_user_skill_storage(config).load_skills(enabled_only=False)

        skills = await asyncio.to_thread(_reload_skills)
        updated_skill = next((s for s in skills if s.name == skill_name), None)

        if updated_skill is None:
            raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_name}' after update")

        logger.info(f"Skill '{skill_name}' enabled status updated to {body.enabled}")
        return _skill_to_response(updated_skill)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")
