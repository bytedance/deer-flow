"""Authentication endpoints for the auth plugin."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.plugins.auth.api.schemas import (
    ChangePasswordRequest,
    InitializeAdminRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    _check_rate_limit,
    _get_client_ip,
    _login_attempts,
    _record_login_failure,
    _record_login_success,
)
from app.plugins.auth.domain.errors import AuthErrorResponse
from app.plugins.auth.domain.jwt import create_access_token
from app.plugins.auth.domain.models import UserResponse
from app.plugins.auth.domain.service import AuthServiceError
from app.plugins.auth.runtime.config_state import get_auth_config
from app.plugins.auth.security.csrf import is_secure_request
from app.plugins.auth.security.dependencies import CurrentAuthService, get_current_user_from_request

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    config = get_auth_config()
    is_https = is_secure_request(request)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=config.token_expiry_days * 24 * 3600 if is_https else None,
    )


@router.post("/login/local", response_model=LoginResponse)
async def login_local(
    request: Request,
    response: Response,
    auth_service: CurrentAuthService,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    client_ip = _get_client_ip(request)
    _check_rate_limit(client_ip)
    try:
        user = await auth_service.login_local(form_data.username, form_data.password)
    except AuthServiceError as exc:
        _record_login_failure(client_ip)
        raise HTTPException(
            status_code=exc.status_code,
            detail=AuthErrorResponse(code=exc.code, message=exc.message).model_dump(),
        ) from exc

    _record_login_success(client_ip)
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)
    return LoginResponse(
        expires_in=get_auth_config().token_expiry_days * 24 * 3600,
        needs_setup=user.needs_setup,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, response: Response, body: RegisterRequest, auth_service: CurrentAuthService):
    try:
        user = await auth_service.register(body.email, body.password)
    except AuthServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=AuthErrorResponse(code=exc.code, message=exc.message).model_dump(),
        ) from exc

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)
    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
    return MessageResponse(message="Successfully logged out")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordRequest,
    auth_service: CurrentAuthService,
):
    user = await get_current_user_from_request(request)
    try:
        user = await auth_service.change_password(
            user,
            current_password=body.current_password,
            new_password=body.new_password,
            new_email=body.new_email,
        )
    except AuthServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=AuthErrorResponse(code=exc.code, message=exc.message).model_dump(),
        ) from exc

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)
    return MessageResponse(message="Password changed successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    user = await get_current_user_from_request(request)
    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, needs_setup=user.needs_setup)


@router.get("/setup-status")
async def setup_status(auth_service: CurrentAuthService):
    return {"needs_setup": await auth_service.get_setup_status()}


@router.post("/initialize", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def initialize_admin(
    request: Request,
    response: Response,
    body: InitializeAdminRequest,
    auth_service: CurrentAuthService,
):
    try:
        user = await auth_service.initialize_admin(body.email, body.password)
    except AuthServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=AuthErrorResponse(code=exc.code, message=exc.message).model_dump(),
        ) from exc

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)
    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role)


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    if provider not in ["github", "google"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported OAuth provider: {provider}")
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OAuth login not yet implemented")


@router.get("/callback/{provider}")
async def oauth_callback(provider: str, code: str, state: str):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OAuth callback not yet implemented")


__all__ = [
    "ChangePasswordRequest",
    "InitializeAdminRequest",
    "LoginResponse",
    "MessageResponse",
    "RegisterRequest",
    "_check_rate_limit",
    "_get_client_ip",
    "_login_attempts",
    "_record_login_failure",
    "_record_login_success",
    "router",
]
