"""Auth provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import Request


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> "User | None":
        """Authenticate user with given credentials.

        Returns User if authentication succeeds, None otherwise.
        """
        ...

    @abstractmethod
    async def get_user(self, user_id: str) -> "User | None":
        """Retrieve user by ID."""
        ...

    async def authenticate_request(self, request: Request) -> "User | None":
        """Authenticate directly from an incoming HTTP request.

        Providers may override this optional hook when request-level context
        (for example trusted reverse-proxy headers) is required to resolve the
        current user. The default implementation returns ``None`` so existing
        providers fall back to the credential-based flow unchanged.
        """
        return None


# Import User at runtime to avoid circular imports
from app.gateway.auth.models import User  # noqa: E402
