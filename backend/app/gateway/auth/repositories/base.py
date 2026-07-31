"""User repository interface for abstracting database operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.gateway.auth.models import SystemRole, User


class UserNotFoundError(LookupError):
    """Raised when a user repository operation targets a non-existent row.

    Subclass of :class:`LookupError` so callers that already catch
    ``LookupError`` for "missing entity" can keep working unchanged,
    while specific call sites can pin to this class to distinguish
    "concurrent delete during update" from other lookups.
    """


class LastAdminError(RuntimeError):
    """Raised when a role change would remove the final administrator."""


class AdminRoleRequiredError(PermissionError):
    """Raised when the transaction actor is no longer an administrator."""


@dataclass(frozen=True)
class UserRoleChange:
    """Result of an atomic, security-sensitive user role update."""

    user: User
    previous_role: SystemRole
    changed: bool


class UserRepository(ABC):
    """Abstract interface for user data storage.

    Implement this interface to support the shared SQLAlchemy storage backends
    (SQLite and PostgreSQL).
    """

    @abstractmethod
    async def create_user(self, user: User) -> User:
        """Create a new user.

        Args:
            user: User object to create

        Returns:
            Created User with ID assigned. ``email`` is the canonical
            (lowercase) stored form, which may differ in case from what was
            passed in -- implementations mutate the input ``user`` in place
            to reflect this rather than returning a fresh object.

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
            Updated User. ``email`` is the canonical (lowercase) stored
            form -- implementations mutate the input ``user`` in place to
            reflect this rather than returning a fresh object.

        Raises:
            UserNotFoundError: If no row exists for ``user.id``. This is
                a hard failure (not a no-op) so callers cannot mistake a
                concurrent-delete race for a successful update.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_users(self, *, offset: int, limit: int) -> tuple[list[User], int]:
        """Return a stable page of users and the total user count."""
        raise NotImplementedError

    @abstractmethod
    async def change_user_role(
        self,
        *,
        actor_id: str,
        user_id: str,
        system_role: SystemRole,
    ) -> UserRoleChange:
        """Atomically change a role, revoke sessions, and protect the last admin.

        Implementations must serialize all role changes across processes and
        re-check ``actor_id`` under that serialization boundary.
        """
        raise NotImplementedError

    @abstractmethod
    async def count_users(self) -> int:
        """Return total number of registered users."""
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
