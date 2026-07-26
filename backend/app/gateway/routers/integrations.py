import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_config, require_admin_user
from deerflow.agents.lead_agent.prompt import refresh_skills_system_prompt_cache_async
from deerflow.config.app_config import AppConfig
from deerflow.integrations.lark_cli import (
    LARK_AUTH_COMPLETE_DEFAULT_WAIT_SECONDS,
    LARK_AUTH_COMPLETE_MAX_WAIT_SECONDS,
    LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS,
    LarkAuthCompleteResult,
    LarkAuthProbe,
    LarkAuthStartResult,
    LarkCliProbe,
    LarkConfigCompleteResult,
    LarkConfigStartResult,
    LarkInstallResult,
    LarkIntegrationStatus,
    complete_lark_auth,
    complete_lark_config,
    get_lark_integration_status,
    install_lark_integration,
    start_lark_auth,
    start_lark_config,
)
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

_ADMIN_REQUIRED_DETAIL = "Admin privileges required to install integrations."


async def _is_admin_user(request: Request) -> bool:
    """Non-raising admin check used to gate host-path disclosure in responses.

    Fails closed: any error (missing middleware state, auth failure) is treated
    as non-admin so host paths are redacted rather than accidentally exposed.
    """
    try:
        await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    except Exception:
        return False
    return True


class LarkCliProbeResponse(BaseModel):
    available: bool = Field(..., description="Whether lark-cli is available to the Gateway, either managed by DeerFlow or on PATH")
    path: str | None = Field(None, description="Resolved lark-cli executable path")
    version: str | None = Field(None, description="lark-cli --version output")
    error: str | None = Field(None, description="Probe failure message")


class LarkAuthProbeResponse(BaseModel):
    status: str = Field(..., description="Auth status: authenticated, not_configured, unavailable, or error")
    message: str | None = Field(None, description="Human-readable status detail")
    user: str | None = Field(None, description="Authenticated Lark/Feishu user display value when available")
    verified: bool = Field(False, description="Whether this status came from a live token verification")


class LarkIntegrationStatusResponse(BaseModel):
    installed: bool = Field(..., description="Whether the managed Lark skill pack is installed")
    version: str = Field(..., description="Installed Lark CLI skill-pack version (from manifest, resolved at install time)")
    manifest_version: str | None = Field(None, description="Installed manifest version")
    latest_available_version: str | None = Field(None, description="Newest larksuite/cli release version available on GitHub, when known")
    runtime_version_mismatch: bool = Field(False, description="Whether the installed skill-pack version differs from the Gateway runtime lark-cli binary")
    app_configured: bool = Field(..., description="Whether lark-cli has app_id/app_secret configured for this user")
    app_id: str | None = Field(None, description="Configured Lark app ID")
    app_brand: str | None = Field(None, description="Configured Lark brand: feishu or lark")
    skills_expected: int = Field(..., description="Number of skills expected in the official pack")
    skills_installed: int = Field(..., description="Number of installed managed Lark skills")
    installed_skills: list[str] = Field(default_factory=list, description="Installed managed Lark skill names")
    enabled_skills: list[str] = Field(default_factory=list, description="Installed Lark skills currently enabled for this user")
    install_path: str = Field(..., description="Host path of the managed Lark skill pack")
    cli: LarkCliProbeResponse
    auth: LarkAuthProbeResponse
    sandbox_runtime_mode: str = Field("none", description="How lark-cli is provisioned into the sandbox: none, gateway-download, or init-container")
    sandbox_runtime_ready: bool = Field(False, description="Whether the sandbox lark-cli runtime is provisioned and usable at chat time")
    sandbox_runtime_detail: str | None = Field(None, description="Human-readable reason when the sandbox runtime is not ready")


class LarkInstallResponse(BaseModel):
    success: bool
    installed_skills: list[str]
    message: str
    status: LarkIntegrationStatusResponse


class LarkAuthStartRequest(BaseModel):
    recommend: bool = Field(default=False, description="Request the official recommended auto-approve scopes")
    domains: list[str] = Field(default_factory=list, description="Optional Lark auth domains, e.g. calendar or docs")
    scope: str | None = Field(default=None, description="Optional explicit OAuth scope string")


class LarkConfigStartRequest(BaseModel):
    brand: str = Field(default="feishu", description="Lark brand to start app registration for: feishu or lark")


class LarkConfigStartResponse(BaseModel):
    verification_url: str = Field(..., description="URL the user should open in a browser to configure the Lark app")
    device_code: str = Field(..., description="Device code used by config/complete after browser approval")
    expires_in: int | None = Field(None, description="Seconds before the configuration URL expires")
    interval: int | None = Field(None, description="Suggested polling interval from Lark")
    user_code: str | None = Field(None, description="Optional user code shown by Lark")
    brand: str = Field(..., description="Brand used for this app registration flow")


class LarkConfigCompleteRequest(BaseModel):
    device_code: str = Field(..., description="Device code returned by config/start")
    brand: str = Field(default="feishu", description="Brand returned by config/start")
    interval: int | None = Field(default=None, description="Polling interval returned by config/start")
    expires_in: int | None = Field(default=None, description="Expiration returned by config/start")


class LarkConfigCompleteResponse(BaseModel):
    success: bool
    message: str
    status: LarkIntegrationStatusResponse


class LarkAuthStartResponse(BaseModel):
    verification_url: str = Field(..., description="URL the user should open in a browser to authorize")
    device_code: str = Field(..., description="Device code used by the complete endpoint after browser approval")
    expires_in: int | None = Field(None, description="Seconds before the authorization URL expires")
    user_code: str | None = Field(None, description="Optional user code shown by Lark")
    hint: str | None = Field(None, description="Optional guidance returned by lark-cli")


class LarkAuthCompleteRequest(BaseModel):
    device_code: str = Field(..., description="Device code returned by auth/start")
    wait_timeout_seconds: int = Field(
        default=LARK_AUTH_COMPLETE_DEFAULT_WAIT_SECONDS,
        ge=LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS,
        le=LARK_AUTH_COMPLETE_MAX_WAIT_SECONDS,
        description="Maximum seconds for this device-code poll; automatic UI polling uses a shorter wait",
    )


class LarkAuthCompleteResponse(BaseModel):
    success: bool
    message: str
    status: LarkIntegrationStatusResponse


def _cli_probe_to_response(probe: LarkCliProbe) -> LarkCliProbeResponse:
    return LarkCliProbeResponse(
        available=probe.available,
        path=probe.path,
        version=probe.version,
        error=probe.error,
    )


def _auth_probe_to_response(probe: LarkAuthProbe) -> LarkAuthProbeResponse:
    return LarkAuthProbeResponse(
        status=probe.status,
        message=probe.message,
        user=probe.user,
        verified=probe.verified,
    )


def _status_to_response(status: LarkIntegrationStatus, *, include_host_paths: bool = True) -> LarkIntegrationStatusResponse:
    cli = _cli_probe_to_response(status.cli)
    if not include_host_paths:
        # Host filesystem paths (Gateway layout) are admin-only info; redact them
        # for non-admin callers of the otherwise non-gated status/complete routes.
        cli = cli.model_copy(update={"path": None})
    return LarkIntegrationStatusResponse(
        installed=status.installed,
        version=status.version,
        manifest_version=status.manifest_version,
        latest_available_version=status.latest_available_version,
        runtime_version_mismatch=status.runtime_version_mismatch,
        app_configured=status.app_configured,
        app_id=status.app_id,
        app_brand=status.app_brand,
        skills_expected=status.skills_expected,
        skills_installed=status.skills_installed,
        installed_skills=list(status.installed_skills),
        enabled_skills=list(status.enabled_skills),
        install_path=status.install_path if include_host_paths else "",
        cli=cli,
        auth=_auth_probe_to_response(status.auth),
        sandbox_runtime_mode=status.sandbox_runtime_mode,
        sandbox_runtime_ready=status.sandbox_runtime_ready,
        sandbox_runtime_detail=status.sandbox_runtime_detail,
    )


def _install_to_response(result: LarkInstallResult) -> LarkInstallResponse:
    return LarkInstallResponse(
        success=result.success,
        installed_skills=list(result.installed_skills),
        message=result.message,
        status=_status_to_response(result.status),
    )


def _config_start_to_response(result: LarkConfigStartResult) -> LarkConfigStartResponse:
    return LarkConfigStartResponse(
        verification_url=result.verification_url,
        device_code=result.device_code,
        expires_in=result.expires_in,
        interval=result.interval,
        user_code=result.user_code,
        brand=result.brand,
    )


def _config_complete_to_response(result: LarkConfigCompleteResult, *, include_host_paths: bool = True) -> LarkConfigCompleteResponse:
    return LarkConfigCompleteResponse(
        success=result.success,
        message=result.message,
        status=_status_to_response(result.status, include_host_paths=include_host_paths),
    )


def _auth_start_to_response(result: LarkAuthStartResult) -> LarkAuthStartResponse:
    return LarkAuthStartResponse(
        verification_url=result.verification_url,
        device_code=result.device_code,
        expires_in=result.expires_in,
        user_code=result.user_code,
        hint=result.hint,
    )


def _auth_complete_to_response(result: LarkAuthCompleteResult, *, include_host_paths: bool = True) -> LarkAuthCompleteResponse:
    return LarkAuthCompleteResponse(
        success=result.success,
        message=result.message,
        status=_status_to_response(result.status, include_host_paths=include_host_paths),
    )


@router.get("/lark/status", response_model=LarkIntegrationStatusResponse, summary="Get Lark/Feishu Integration Status")
async def get_lark_status(request: Request, config: AppConfig = Depends(get_config)) -> LarkIntegrationStatusResponse:
    try:
        status = await asyncio.to_thread(get_lark_integration_status, get_effective_user_id(), config, check_latest=True, check_runtime=True)
        return _status_to_response(status, include_host_paths=await _is_admin_user(request))
    except Exception as e:
        logger.error("Failed to get Lark integration status: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get Lark integration status.")


@router.post("/lark/install", response_model=LarkInstallResponse, summary="Install Lark/Feishu Skill Pack")
async def install_lark(request: Request, config: AppConfig = Depends(get_config)) -> LarkInstallResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        result = await asyncio.to_thread(install_lark_integration, get_effective_user_id(), config)
        await refresh_skills_system_prompt_cache_async()
        return _install_to_response(result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to install Lark integration: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to install Lark integration.")


@router.post("/lark/config/start", response_model=LarkConfigStartResponse, summary="Start Lark/Feishu App Configuration")
async def start_lark_app_config(body: LarkConfigStartRequest) -> LarkConfigStartResponse:
    try:
        result = await asyncio.to_thread(
            start_lark_config,
            get_effective_user_id(),
            brand=body.brand,
        )
        return _config_start_to_response(result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.error("Failed to start Lark connection setup: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start Lark connection setup.")


@router.post("/lark/config/complete", response_model=LarkConfigCompleteResponse, summary="Complete Lark/Feishu App Configuration")
async def complete_lark_app_config(request: Request, body: LarkConfigCompleteRequest, config: AppConfig = Depends(get_config)) -> LarkConfigCompleteResponse:
    try:
        result = await asyncio.to_thread(
            complete_lark_config,
            get_effective_user_id(),
            config,
            device_code=body.device_code,
            brand=body.brand,
            interval=body.interval,
            expires_in=body.expires_in,
        )
        return _config_complete_to_response(result, include_host_paths=await _is_admin_user(request))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.error("Failed to complete Lark connection setup: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to complete Lark connection setup.")


@router.post("/lark/auth/start", response_model=LarkAuthStartResponse, summary="Start Lark/Feishu Browser Authorization")
async def start_lark_browser_auth(body: LarkAuthStartRequest) -> LarkAuthStartResponse:
    try:
        result = await asyncio.to_thread(
            start_lark_auth,
            get_effective_user_id(),
            domains=tuple(body.domains),
            scope=body.scope,
            recommend=body.recommend,
        )
        return _auth_start_to_response(result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.error("Failed to start Lark authorization: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start Lark authorization.")


@router.post("/lark/auth/complete", response_model=LarkAuthCompleteResponse, summary="Complete Lark/Feishu Browser Authorization")
async def complete_lark_browser_auth(request: Request, body: LarkAuthCompleteRequest, config: AppConfig = Depends(get_config)) -> LarkAuthCompleteResponse:
    try:
        result = await asyncio.to_thread(
            complete_lark_auth,
            get_effective_user_id(),
            config,
            device_code=body.device_code,
            wait_timeout_seconds=body.wait_timeout_seconds,
        )
        return _auth_complete_to_response(result, include_host_paths=await _is_admin_user(request))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        logger.error("Failed to complete Lark authorization: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to complete Lark authorization.")
