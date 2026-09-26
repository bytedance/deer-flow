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
    ManagedImageGenerationProfile,
    ManagedImageGenerationProfileStore,
    legacy_image_profile,
    resolve_image_generation_profile,
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
        profile, source, managed = resolve_image_generation_profile(get_app_config().sandbox.environment)
    except (ImageConfigurationError, ValueError):
        return _empty_status(ImageConnectionStatus.INVALID_CONFIG)
    if profile is None:
        return _empty_status(ImageConnectionStatus.NOT_CONFIGURED)
    configured = profile.usable()
    generation = configured and bool(managed and managed.verified_generation)
    edit = configured and bool(managed and managed.verified_edit)
    failed_results = {managed.last_generation_result, managed.last_edit_result} if managed else set()
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
    profiles = [item.public() for item in ManagedImageGenerationProfileStore().list()]
    try:
        legacy = legacy_image_profile(get_app_config().sandbox.environment)
    except (ImageConfigurationError, ValueError):
        legacy = None
    if legacy is not None:
        profiles.insert(
            0,
            {
                "name": "server-config",
                "display_name": "Server configuration",
                "source": "config",
                "provider": legacy.provider.value,
                "model": legacy.model,
                "base_url": legacy.base_url,
                "has_api_key": legacy.usable(),
                "enabled": not any(item["enabled"] for item in profiles),
                "verified_generation": False,
                "verified_edit": False,
            },
        )
    return {"profiles": profiles, "status": _status()}


@router.get("/profiles")
async def list_image_profiles(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    try:
        return await asyncio.to_thread(_list_profiles)
    except (ValueError, OSError):
        raise HTTPException(503, "Image profile storage is unavailable") from None


def _save(body: SaveImageProfileRequest) -> dict:
    try:
        return ManagedImageGenerationProfileStore().save(body.config, expected_revision=body.expected_revision).public()
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


@router.post("/profiles/{name}/test/{operation}")
async def test_image_profile(request: Request, name: str, operation: Literal["generation", "edit"], body: TestImageProfileRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_test, name, body, operation)
