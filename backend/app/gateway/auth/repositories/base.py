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

    @abstractmethod
    async def get_users_by_role(self, role: str) -> list[User]:
        """Return every user that holds ``role`` (plan §3 M1-6, RFC §11.1 #8).

        Used by:

        * ``GET /api/enterprise/rbac/users/{id}/role`` reverse look-ups,
        * ``ApprovalRuleEngine._resolve_approvers`` (M3) to find the
          users that can approve a given rule.

        A user "holds" a role when either:

        - ``role`` appears in their ``roles`` JSON list, OR
        - their legacy ``system_role`` maps to the requested role
          (``"admin"`` ↔ ``"admin"``, ``"user"`` ↔ ``"member"``).

        The double-source lookup means M1 routes work both for users
        provisioned through the enterprise RBAC UI (writes ``roles``)
        and for legacy accounts that only have ``system_role``.

        Returns an empty list when the role is unknown — callers are
        expected to ``raise HTTPException(404)`` themselves if that is
        the desired behaviour.
        """
        raise NotImplementedError
