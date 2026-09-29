"""Administrator-managed image providers and safe readiness projection."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.gateway.deps import require_admin_user
from app.gateway.image_generation_probe import probe_image_profile
from deerflow.config.app_config import get_app_config
from deerflow.config.image_generation import (
    ImageConfigurationError,
    ImageConnectionStatus,
    ImageGenerationDefaultStore,
    ManagedImageGenerationProfile,
    ManagedImageGenerationProfileStore,
    ServerImageProbeStore,
    image_profile_choice_needed,
    image_profile_container_identity,
    image_profile_identity,
    resolve_image_generation_profile,
    resolve_server_image_profile,
    saved_image_generation_source,
)

router = APIRouter(prefix="/api/image-generation", tags=["image-generation"])
_ADMIN = "Admin privileges are required to manage image generation."


class SaveImageProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: ManagedImageGenerationProfile
    expected_revision: str | None = None


class TestImageProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str


class TestServerImageProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_identity: str


class SetImageDefaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["managed", "sandbox_environment"]
    target_identity: str
    expected_revision: str | None = None


def _empty_status(status: ImageConnectionStatus) -> dict:
    return {
        "status": status,
        "source": None,
        "provider": None,
        "model": None,
        "has_api_key": False,
        "supports_generation": False,
        "supports_edit": False,
    }


def _status() -> dict:
    try:
        profile, source, managed = resolve_image_generation_profile(get_app_config().image_generation_environment)
    except (ImageConfigurationError, ValueError):
        return _empty_status(ImageConnectionStatus.INVALID_CONFIG)
    if profile is None:
        return _empty_status(ImageConnectionStatus.NOT_CONFIGURED)
    configured = profile.usable()
    results = ServerImageProbeStore().results(profile) if source == "sandbox_environment" else {}
    generation = configured and (bool(managed and managed.verified_generation) or results.get("generation") == "success")
    edit = configured and (bool(managed and managed.verified_edit) or results.get("edit") == "success")
    failed_results = {managed.last_generation_result, managed.last_edit_result} if managed else set(results.values())
    if not configured or "authentication_failed" in failed_results or "provider_rejected" in failed_results:
        status = ImageConnectionStatus.INVALID_CONFIG
    elif "unreachable" in failed_results:
        status = ImageConnectionStatus.UNREACHABLE
    elif generation and edit:
        status = ImageConnectionStatus.READY
    else:
        status = ImageConnectionStatus.CONFIGURED_UNVERIFIED
    return {
        "status": status,
        "source": source,
        "provider": profile.provider.value,
        "model": profile.model,
        "has_api_key": configured,
        "supports_generation": generation,
        "supports_edit": edit,
    }


@router.get("/status")
async def image_generation_status(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_status)


def _list_profiles() -> dict:
    stored_profiles = ManagedImageGenerationProfileStore().list()
    profiles = [{**item.public(), "identity": image_profile_identity(item)} for item in stored_profiles]
    try:
        legacy = resolve_server_image_profile(get_app_config())
    except (ImageConfigurationError, ValueError):
        legacy = None
    status = _status()
    current_default = ImageGenerationDefaultStore().read()
    status["default_revision"] = current_default.revision if current_default else None
    status["default_active"] = current_default is not None and saved_image_generation_source(get_app_config().image_generation_environment) == current_default.source
    choice_required = legacy is not None and image_profile_choice_needed(get_app_config().image_generation_environment)
    status["choice_required"] = choice_required
    managed_selected = status["source"] == "managed"
    for item in profiles:
        item["selected"] = managed_selected and item["enabled"] and not choice_required
        item["conflict"] = item["enabled"] and choice_required
    if legacy is not None:
        results = ServerImageProbeStore().results(legacy)
        profiles.insert(
            0,
            {
                "name": "server-config",
                "display_name": "Server configuration",
                "source": "config",
                "provider": legacy.provider.value,
                "model": legacy.model,
                "identity": image_profile_identity(legacy),
                "base_url": legacy.base_url,
                "has_api_key": legacy.usable(),
                "enabled": not any(item["enabled"] for item in profiles),
                "selected": status["source"] == "sandbox_environment" and not choice_required,
                "conflict": choice_required,
                "verified_generation": results.get("generation") == "success",
                "verified_edit": results.get("edit") == "success",
                "last_generation_result": results.get("generation"),
                "last_edit_result": results.get("edit"),
            },
        )
    return {"profiles": profiles, "status": status}


def _set_default(body: SetImageDefaultRequest) -> dict:
    try:
        saved = ImageGenerationDefaultStore().save(
            body.source,
            target_identity=body.target_identity,
            expected_revision=body.expected_revision,
            environment=get_app_config().image_generation_environment,
        )
        return {"revision": saved.revision}
    except FileExistsError:
        raise HTTPException(409, "Image model default changed; reload before saving") from None
    except ImageConfigurationError as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, OSError):
        raise HTTPException(503, "Image model default is unavailable") from None


@router.put("/profiles/default")
async def set_image_default(request: Request, body: SetImageDefaultRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_set_default, body)


@router.get("/profiles")
async def list_image_profiles(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    try:
        return await asyncio.to_thread(_list_profiles)
    except (ValueError, OSError):
        raise HTTPException(503, "Image profile storage is unavailable") from None


def _save(body: SaveImageProfileRequest) -> dict:
    try:
        store = ManagedImageGenerationProfileStore()
        try:
            legacy = resolve_server_image_profile(get_app_config())
            server_model = f"{legacy.provider.value}:{legacy.model}" if legacy is not None else None
        except (ImageConfigurationError, ValueError):
            legacy = None
            server_model = None
        same_server_settings = (
            legacy is not None
            and legacy.usable()
            and (
                legacy.provider,
                legacy.model,
                legacy.base_url,
                legacy.size,
            )
            == (
                body.config.provider,
                body.config.model,
                body.config.base_url,
                body.config.size,
            )
        )
        if same_server_settings and not any(item.name == body.config.name for item in store.list()):
            raise HTTPException(409, "This image provider, model, endpoint, and size are already configured by the server")
        profile = body.config.model_copy(update={"server_model_at_enable": server_model})
        return store.save(profile, expected_revision=body.expected_revision).public()
    except FileNotFoundError:
        raise HTTPException(404, "Image profile no longer exists") from None
    except FileExistsError:
        raise HTTPException(409, "Image profile changed; reload before saving") from None
    except ImageConfigurationError as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, OSError):
        raise HTTPException(503, "Image profile storage is unavailable") from None


@router.put("/profiles")
async def save_image_profile(request: Request, body: SaveImageProfileRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_save, body)


def _test(name: str, body: TestImageProfileRequest, operation: Literal["generation", "edit"]) -> dict:
    store = ManagedImageGenerationProfileStore()
    try:
        profile = next((item for item in store.list() if item.name == name), None)
    except (ValueError, OSError):
        raise HTTPException(503, "Image profile storage is unavailable") from None
    if profile is None:
        raise HTTPException(404, "Image profile no longer exists")
    if profile.revision != body.expected_revision:
        raise HTTPException(409, "Image profile changed; reload before testing")
    result = probe_image_profile(profile, operation)
    if result not in {"missing_api_key", "invalid_operation"}:
        try:
            store.record_test(name, body.expected_revision, operation, result)
        except FileExistsError:
            raise HTTPException(409, "Image profile changed during the test; reload before retrying") from None
        except (ValueError, OSError):
            raise HTTPException(503, "Image profile storage is unavailable") from None
    return {"ok": result == "success", "message": result}


def _test_server(body: TestServerImageProfileRequest, operation: Literal["generation", "edit"]) -> dict:
    try:
        profile = resolve_server_image_profile(get_app_config())
        if profile is None:
            raise HTTPException(404, "Server image profile is not configured")
        if image_profile_identity(profile) != body.expected_identity:
            raise HTTPException(409, "Server image profile changed; reload before testing")
        result = probe_image_profile(profile, operation)
        current = resolve_server_image_profile(get_app_config())
        if current is None or image_profile_container_identity(current) != image_profile_container_identity(profile):
            raise HTTPException(409, "Server image profile changed during the test; reload before retrying")
        if result not in {"missing_api_key", "invalid_operation"}:
            ServerImageProbeStore().record(profile, operation, result)
        return {"ok": result == "success", "message": result}
    except HTTPException:
        raise
    except (ImageConfigurationError, ValueError, OSError):
        raise HTTPException(503, "Server image profile is unavailable") from None


@router.post("/server/test/{operation}")
async def test_server_image_profile(request: Request, operation: Literal["generation", "edit"], body: TestServerImageProfileRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_test_server, body, operation)


@router.post("/profiles/{name}/test/{operation}")
async def test_image_profile(request: Request, name: str, operation: Literal["generation", "edit"], body: TestImageProfileRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_test, name, body, operation)
