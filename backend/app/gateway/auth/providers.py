"""Auth provider abstraction."""

from abc import ABC, abstractmethod


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


# Import User at runtime to avoid circular imports
from app.gateway.auth.models import User  # noqa: E402
