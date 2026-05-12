"""Auth provider abstraction."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantSelectionRequired:
    """Result when multiple tenants match — authenticate()'s third return value."""

    tenants: tuple[dict, ...]


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> "User | TenantSelectionRequired | None":
        """Authenticate user with given credentials.

        Returns:
            User — authentication succeeded
            TenantSelectionRequired — password correct but matches multiple tenants
            None — authentication failed
        """
        raise NotImplementedError

    @abstractmethod
    async def get_user(self, user_id: str) -> "User | None":
        """Retrieve user by ID."""
        raise NotImplementedError


# Import User at runtime to avoid circular imports
from app.gateway.auth.models import User  # noqa: E402
