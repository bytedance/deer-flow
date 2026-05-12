"""Local email/password authentication provider."""

import logging

from app.gateway.auth.models import User
from app.gateway.auth.password import hash_password_async, needs_rehash, verify_password_async
from app.gateway.auth.providers import AuthProvider, TenantSelectionRequired
from app.gateway.auth.repositories.base import UserRepository

logger = logging.getLogger(__name__)

_MAX_TENANT_VERIFY = 10


class LocalAuthProvider(AuthProvider):
    """Email/password authentication provider using local database."""

    def __init__(self, repository: UserRepository):
        self._repo = repository

    async def authenticate(self, credentials: dict) -> User | TenantSelectionRequired | None:
        """Authenticate with email and password.

        When tenant_id is "default" or missing, auto-detects the user's tenant
        by querying all users with the given email across all tenants.
        """
        email = credentials.get("email")
        password = credentials.get("password")
        tenant_id = credentials.get("tenant_id", "default")

        if not email or not password:
            return None

        if tenant_id != "default":
            return await self._authenticate_explicit(email, password, tenant_id)

        return await self._authenticate_auto_detect(email, password)

    async def _authenticate_explicit(self, email: str, password: str, tenant_id: str) -> User | None:
        user = await self._repo.get_user_by_email_and_tenant(email, tenant_id)
        if user is None or user.password_hash is None:
            return None
        if not await verify_password_async(password, user.password_hash):
            return None
        await self._maybe_rehash(user, password)
        return user

    async def _authenticate_auto_detect(self, email: str, password: str) -> User | TenantSelectionRequired | None:
        users = await self._repo.get_users_by_email(email)
        if not users:
            return None

        # Cap verification to prevent bcrypt DoS; verify a subset then return full list
        candidates = users[:_MAX_TENANT_VERIFY] if len(users) > _MAX_TENANT_VERIFY else users

        if len(candidates) == 1:
            user = candidates[0]
            if user.password_hash and await verify_password_async(password, user.password_hash):
                await self._maybe_rehash(user, password)
                return user
            return None

        matched = []
        for u in candidates:
            if u.password_hash and await verify_password_async(password, u.password_hash):
                matched.append(u)

        if len(matched) == 0:
            return None
        if len(matched) == 1:
            await self._maybe_rehash(matched[0], password)
            return matched[0]

        # Multiple password matches — return full tenant list for selection
        tenant_list = tuple({"tenant_id": u.tenant_id, "email": u.email} for u in matched)
        return TenantSelectionRequired(tenant_list)

    async def _maybe_rehash(self, user: User, password: str) -> None:
        if needs_rehash(user.password_hash):
            try:
                user.password_hash = await hash_password_async(password)
                await self._repo.update_user(user)
            except Exception:
                logger.warning("Failed to rehash password for user %s; login will still succeed", user.email, exc_info=True)

    async def get_user(self, user_id: str) -> User | None:
        """Get user by ID."""
        return await self._repo.get_user_by_id(user_id)

    async def create_user(self, email: str, password: str | None = None, system_role: str = "user", needs_setup: bool = False, tenant_id: str = "default") -> User:
        """Create a new local user.

        Args:
            email: User email address
            password: Plain text password (will be hashed)
            system_role: Role to assign ("superadmin", "tenant_admin", or "user")
            needs_setup: If True, user must complete setup on first login
            tenant_id: Tenant the user belongs to

        Returns:
            Created User instance
        """
        password_hash = await hash_password_async(password) if password else None
        user = User(
            email=email,
            password_hash=password_hash,
            system_role=system_role,
            needs_setup=needs_setup,
            tenant_id=tenant_id,
        )
        return await self._repo.create_user(user)

    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        """Get user by OAuth provider and ID."""
        return await self._repo.get_user_by_oauth(provider, oauth_id)

    async def count_users(self) -> int:
        """Return total number of registered users."""
        return await self._repo.count_users()

    async def count_admin_users(self) -> int:
        """Return number of admin users."""
        return await self._repo.count_admin_users()

    async def update_user(self, user: User) -> User:
        """Update an existing user."""
        return await self._repo.update_user(user)

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email."""
        return await self._repo.get_user_by_email(email)

    async def count_users_by_tenant(self, tenant_id: str) -> int:
        """Return number of users in a tenant."""
        return await self._repo.count_users(tenant_id=tenant_id)

    async def list_users(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[User]:
        """List users in a tenant."""
        return await self._repo.list_users(tenant_id, limit=limit, offset=offset)

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user by ID. Returns True if deleted, False if not found."""
        return await self._repo.delete_user(user_id)
