"""User repository interface for abstracting database operations."""

from abc import ABC, abstractmethod

from app.gateway.auth.models import User


class UserNotFoundError(LookupError):
    """Raised when a user repository operation targets a non-existent row.

    Subclass of :class:`LookupError` so callers that already catch
    ``LookupError`` for "missing entity" can keep working unchanged,
    while specific call sites can pin to this class to distinguish
    "concurrent delete during update" from other lookups.
    """


class UserRepository(ABC):
    """Abstract interface for user data storage.

    Implement this interface to support different storage backends
    (SQLite)
    """

    @abstractmethod
    async def create_user(self, user: User) -> User:
        """Create a new user.

        Args:
            user: User object to create

        Returns:
            Created User with ID assigned

        Raises:
            ValueError: If email already exists
        """
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID.

        Args:
            user_id: User UUID as string

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email.

        Args:
            email: User email address

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def update_user(self, user: User) -> User:
        """Update an existing user.

        Args:
            user: User object with updated fields

        Returns:
            Updated User

        Raises:
            UserNotFoundError: If no row exists for ``user.id``. This is
                a hard failure (not a no-op) so callers cannot mistake a
                concurrent-delete race for a successful update.
        """
        raise NotImplementedError

    @abstractmethod
    async def count_users(self, tenant_id: str | None = None) -> int:
        """Return total number of registered users, optionally filtered by tenant."""
        raise NotImplementedError

    @abstractmethod
    async def count_admin_users(self) -> int:
        """Return number of users with system_role == 'admin'."""
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        """Get user by OAuth provider and ID.

        Args:
            provider: OAuth provider name (e.g. 'github', 'google')
            oauth_id: User ID from the OAuth provider

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_email_and_tenant(self, email: str, tenant_id: str) -> User | None:
        """Get user by email within a specific tenant.

        Args:
            email: User email address
            tenant_id: Tenant ID to scope the lookup

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def list_users(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[User]:
        """List users in a tenant with pagination.

        Args:
            tenant_id: Tenant ID to filter by
            limit: Max users to return
            offset: Pagination offset

        Returns:
            List of User objects
        """
        raise NotImplementedError

    @abstractmethod
    async def delete_user(self, user_id: str) -> bool:
        """Delete a user by ID.

        Args:
            user_id: User UUID as string

        Returns:
            True if the user was deleted, False if not found
        """
        raise NotImplementedError
