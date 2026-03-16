"""FastAPI middleware for injecting user context into requests.

This middleware extracts the user_id from JWT token (via HttpOnly cookie or Authorization header)
and injects it into the request state for use in downstream endpoints and LangGraph operations.

This ensures thread-level user isolation in multi-tenant mode.
"""

from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.auth.jwt import decode_access_token, get_jwt_secret
from app.gateway.auth.models import AuthenticationError


class UserContextMiddleware(BaseHTTPMiddleware):
    """Middleware to inject user context into request state.

    Extracts user_id from JWT token (cookie or Authorization header) and
    stores it in request.state.user_id for use in downstream endpoints.

    In multi-tenant mode, this ensures thread-level user isolation.
    In single-tenant mode, uses the default user ID from config.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """Process request and inject user context.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware or route handler

        Returns:
            HTTP response from downstream handler
        """
        # Try to get user_id from Authorization header first
        auth_header = request.headers.get("Authorization", "")
        user_id = None

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            try:
                token_data = decode_access_token(token, secret_key=get_jwt_secret())
                user_id = token_data.user_id
            except AuthenticationError:
                # Invalid token - continue without user context
                pass

        # If no user_id from header, try HttpOnly cookie
        if user_id is None:
            access_token = request.cookies.get("access_token")
            if access_token:
                try:
                    token_data = decode_access_token(access_token, secret_key=get_jwt_secret())
                    user_id = token_data.user_id
                except AuthenticationError:
                    # Invalid token - continue without user context
                    pass

        # Store user_id in request state for downstream use
        request.state.user_id = user_id

        return await call_next(request)


def get_user_id_from_request(request: Request) -> str | None:
    """Extract user_id from request state (set by middleware).

    Args:
        request: FastAPI request object

    Returns:
        User ID if authenticated, None otherwise
    """
    return getattr(request.state, "user_id", None)
