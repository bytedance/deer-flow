"""User repository interface for abstracting database operations."""

from abc import ABC, abstractmethod

from app.gateway.auth.models import User


class LastAdminRemainsError(RuntimeError):
    """Raised when a role write would demote the last remaining admin.

    Bootstrap lockout protection: raised inside the same serialized
    transaction that would perform the write, so the check-then-act window
    that two concurrent demotions could race through is closed.
    """


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
            Created User with ID assigned. ``email`` is the canonical
            (lowercase) stored form, which may differ in case from what was
            passed in -- implementations mutate the input ``user`` in place
            to reflect this rather than returning a fresh object.

        Raises:
            ValueError: If email already exists
        """
        raise NotImplementedError

    @abstractmethod
    async def create_first_admin(self, user: User) -> User | None:
        """Create *user* as the first admin, atomically.

        Implementations must read the admin count and insert in one
        serialized transaction: a count-then-create pair lets two concurrent
        first-boot requests both find an empty system.

        Returns:
            The created User, or None if an admin already exists.

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
    async def update_system_role(self, user_id: str, system_role: str) -> User:
        """Assign a user's system role as a single-column, serialized write.

        Origin: admin role-assignment API (RFC #4063 / #3462 gap 2). Distinct
        from :meth:`update_user` on purpose — role mutations and credential
        writes are field-scoped against each other, so a password change
        holding a stale account snapshot can never restore a revoked role,
        and a role change can never overwrite credentials.

        Raises:
            UserNotFoundError: the target row does not exist.
            LastAdminRemainsError: the write would demote the only remaining
                admin (the count and the write share one serialized
                transaction — two concurrent demotions cannot both pass).
        """
        raise NotImplementedError

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
    async def count_users(self) -> int:
        """Return total number of registered users."""
        raise NotImplementedError

    @abstractmethod
    async def list_user_ids(self) -> list[str]:
        """Return every registered user ID in deterministic creation order."""
        raise NotImplementedError

    @abstractmethod
    async def list_users(self) -> list[User]:
        """Return all users ordered by creation (oldest first).

        Origin: admin user-list surface (RFC #4063 / #3462 gap 2). Volume is
        bounded by the deployment's user base; pagination can be added when a
        real deployment needs it.
        """
        raise NotImplementedError

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
