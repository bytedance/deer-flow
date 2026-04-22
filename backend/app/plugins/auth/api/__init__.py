"""HTTP API layer for the auth plugin."""

from app.plugins.auth.api.router import (
    ChangePasswordRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    router,
)

__all__ = [
    "ChangePasswordRequest",
    "LoginResponse",
    "MessageResponse",
    "RegisterRequest",
    "router",
]
