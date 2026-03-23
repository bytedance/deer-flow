"""
Authentication endpoints for DeerFlow multi-tenancy.

Provides user registration, login, and token management.
When multi_tenant.enabled is false, these endpoints are still available
but unauthenticated API requests use user_id="default".
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.gateway.auth import UserRole, create_access_token, get_optional_user, hash_password, verify_password
from app.gateway.auth.models import TokenData
from app.gateway.users import UserStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

# Singleton user store
_user_store: UserStore | None = None


def get_user_store() -> UserStore:
    """Get the singleton UserStore instance."""
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store


def create_token_for_user(user: dict) -> str:
    """Create a JWT access token for a user.

    Args:
        user: User dict with user_id, email, and role fields.

    Returns:
        JWT access token string.
    """
    return create_access_token(
        data={
            "sub": user["user_id"],
            "email": user["email"],
            "role": user["role"],
        },
    )


# Request/Response Models
class RegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")
    role: UserRole = Field(default=UserRole.USER, description="User role")


class LoginRequest(BaseModel):
    """User login request."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class TokenResponse(BaseModel):
    """Authentication token response."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    user_id: str = Field(..., description="User ID (UUID as string)")
    email: str = Field(..., description="User email")
    role: UserRole = Field(..., description="User role")


class UserInfoResponse(BaseModel):
    """Current user information."""

    user_id: str = Field(..., description="User ID (UUID as string)")
    email: str = Field(..., description="User email")
    role: UserRole = Field(..., description="User role")
    quota_limits: dict = Field(..., description="Resource quota limits")


# Endpoints
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, response: Response) -> TokenResponse:
    """Register a new user.

    Creates a new user account and returns a JWT access token.
    The password is hashed before storage.
    Sets the JWT token in an HttpOnly cookie for enhanced security.

    Args:
        req: Registration request with email and password
        response: FastAPI Response object for setting cookies

    Returns:
        TokenResponse with JWT token and user info

    Raises:
        HTTPException: If email is already registered
    """
    store = get_user_store()

    # Check if user already exists
    if store.get_by_email(req.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user with UUID as primary key
    user_id = uuid4()
    hashed = hash_password(req.password)

    try:
        user = store.create(
            user_id=user_id,
            email=req.email,
            hashed_password=hashed,
            role=req.role,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    # Generate token
    token = create_token_for_user(user)

    # Set HttpOnly cookie for enhanced security (RFC-001 compliant)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,  # RFC-001 compliant: requires HTTPS in production
        samesite="lax",
        max_age=60 * 24 * 7,  # 7 days
        path="/",
    )

    logger.info("User registered: %s (%s)", user_id, req.email)
    return TokenResponse(
        access_token=token,
        user_id=str(user_id),
        email=req.email,
        role=user["role"],
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, response: Response) -> TokenResponse:
    """Authenticate a user and return a JWT token.

    Validates the user's credentials and returns a JWT access token
    if authentication succeeds.
    Sets the JWT token in an HttpOnly cookie for enhanced security.

    Args:
        req: Login request with email and password
        response: FastAPI Response object for setting cookies

    Returns:
        TokenResponse with JWT token and user info

    Raises:
        HTTPException: If credentials are invalid
    """
    store = get_user_store()
    user = store.get_by_email(req.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(req.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Generate token
    token = create_token_for_user(user)

    # Set HttpOnly cookie for enhanced security (RFC-001 compliant)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,  # RFC-001 compliant: requires HTTPS in production
        samesite="lax",
        max_age=60 * 24 * 7,  # 7 days
        path="/",
    )

    logger.info("User logged in: %s (%s)", user["user_id"], req.email)
    return TokenResponse(
        access_token=token,
        user_id=user["user_id"],
        email=user["email"],
        role=user["role"],
    )


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    current_user: TokenData = Depends(get_optional_user),
) -> UserInfoResponse:
    """Get information about the currently authenticated user.

    Returns user information including quota limits.
    If no authentication is provided, returns the default user.

    Args:
        current_user: Current user from JWT token (optional)

    Returns:
        UserInfoResponse with user details
    """
    store = get_user_store()
    user = store.get_by_id(current_user.user_id)

    if user:
        return UserInfoResponse(
            user_id=user["user_id"],
            email=user["email"],
            role=user["role"],
            quota_limits=user.get("quota_limits", {}),
        )

    # Return default user info if not found
    return UserInfoResponse(
        user_id=current_user.user_id,
        email=current_user.email or "default@example.com",
        role=current_user.role,
        quota_limits={},
    )


@router.post("/logout")
async def logout(
    response: Response,
    current_user: TokenData = Depends(get_optional_user),
) -> dict[str, str]:
    """Logout the current user.

    Clears the HttpOnly cookie containing the JWT token.
    Note: Since JWT tokens are stateless, the token remains valid until
    it expires. This endpoint is provided for API completeness and client-side
    token cleanup. In production with token revocation, you would maintain
    a blacklist of revoked tokens.

    Args:
        response: FastAPI Response object for clearing cookies
        current_user: Current user from JWT token

    Returns:
        Success message
    """
    # Clear the HttpOnly cookie
    response.delete_cookie(
        key="access_token",
        path="/",
    )

    logger.info("User logged out: %s", current_user.user_id)
    return {"message": "Successfully logged out"}
