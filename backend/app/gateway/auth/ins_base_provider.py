"""ins-base-rpc authentication provider.

Integrates with the Java ins-base-rpc microservice for user login,
token authentication, and token refresh.
"""

import logging
from uuid import UUID, uuid4

from app.gateway.auth.providers import AuthProvider
from app.gateway.auth.rsa_utils import rsa_encrypt
from deerflow.config.auth_config import get_auth_config
from deerflow.rpc.ins_base_auth_service import InsBaseAuthServiceClient
from deerflow.rpc.rpc_client import RpcClient

logger = logging.getLogger(__name__)


class RpcNotConfiguredError(Exception):
    """Raised when the RPC client is not configured."""


def _map_system_role(username: str) -> str:
    """Map username to system_role.

    - "superadmin" → "superadmin"
    - "admin" → "tenant_admin"
    - anything else → "user"
    """
    if username == "superadmin":
        return "superadmin"
    if username == "admin":
        return "tenant_admin"
    return "user"


class InsBaseAuthProvider(AuthProvider):
    """Authentication provider backed by the ins-base-rpc Java microservice.

    Login flow:
      1. RSA-encrypt username and password using configured public key
      2. Call ins-base-rpc /auth/login with encrypted credentials
      3. Map the response to a local User model with tenant "default"

    Authentication flow:
      1. Call ins-base-rpc /auth/authentication with the token
      2. Return user info and permissions

    Refresh flow:
      1. Call ins-base-rpc /auth/refresh with the refresh token
      2. Return new token
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc_client = rpc_client

    @property
    def _auth_service(self) -> InsBaseAuthServiceClient:
        try:
            return InsBaseAuthServiceClient(rpc_client=self._rpc_client)
        except RuntimeError as e:
            raise RpcNotConfiguredError(str(e)) from e

    def _get_rsa_key(self) -> str:
        config = get_auth_config()
        if not config.rsa_public_key:
            raise ValueError(
                "RSA public key is not configured. Set auth.rsa_public_key in config.yaml."
            )
        return config.rsa_public_key

    async def authenticate(self, credentials: dict):
        """Authenticate with RSA-encrypted username and password via ins-base-rpc.

        Args:
            credentials: dict with keys "username" and "password".

        Returns:
            User on success, None on failure.

        Raises:
            RpcNotConfiguredError: If ins-base-rpc is not configured.
            ValueError: If RSA public key is not configured.
        """
        username = credentials.get("username", "")
        password = credentials.get("password", "")

        if not username or not password:
            return None

        rsa_key = self._get_rsa_key()
        encoded_user = rsa_encrypt(username, rsa_key)
        encoded_pass = rsa_encrypt(password, rsa_key)

        try:
            response = await self._auth_service.login(encoded_user, encoded_pass)
        except RpcNotConfiguredError:
            raise
        except Exception as e:
            logger.exception("ins-base-rpc /auth/login call failed")
            raise RuntimeError(f"登录服务调用失败: {e}") from e

        code = response.get("code", 0)
        if code != 200:
            msg = response.get("msg", "登录失败")
            raise RuntimeError(msg)

        data = response.get("data") or {}
        token = data.get("token") or response.get("token")
        refresh_token = data.get("refresh") or response.get("refresh")

        # Map to local User model with default tenant
        user_id = uuid4()
        user = type(
            "InsBaseUser",
            (),
            {
                "id": user_id,
                "email": f"{username}@ins-base",
                "password_hash": None,
                "system_role": _map_system_role(username),
                "needs_setup": False,
                "token_version": 0,
                "tenant_id": "default",
                "ins_base_token": token or "",
                "ins_base_refresh": refresh_token or "",
            },
        )()
        return user

    async def get_user(self, user_id: str):
        """Authenticate a token via ins-base-rpc /auth/authentication.

        Note: user_id is the ins-base token itself, not a local user ID,
        since all user management lives on the Java side.

        Returns a dict-like user object with token-based identity.
        """
        if not user_id:
            return None

        try:
            response = await self._auth_service.authenticate(user_id)
        except Exception as e:
            logger.exception("ins-base-rpc /auth/authentication call failed")
            return None

        code = response.get("code", 0)
        if code != 200:
            logger.warning(
                "ins-base-rpc /auth/authentication failed: code=%s msg=%s",
                code,
                response.get("msg", ""),
            )
            return None

        data = response.get("data") or {}
        user_data = data.get("user") or {}
        permissions = data.get("permissions") or []
        # Extract the real userId from ins-base response data instead of
        # using the raw token string as the identity.  The token is opaque
        # and contains dots / special chars that violate the user_id
        # filesystem-path validation in deerflow/config/paths.py.
        real_user_id = str(user_data.get("userId", user_id))

        user = type(
            "InsBaseUser",
            (),
            {
                "id": real_user_id,
                "email": user_data.get("email", f"user@{real_user_id}"),
                "password_hash": None,
                "system_role": _map_system_role(user_data.get("username", "")),
                "needs_setup": False,
                "token_version": 0,
                "tenant_id": "default",
                "ins_base_permissions": permissions,
                "ins_base_user_data": user_data,
            },
        )()
        return user

    async def refresh_token(self, refresh_token: str) -> str | None:
        """Refresh an access token via ins-base-rpc /auth/refresh.

        Args:
            refresh_token: The refresh token string.

        Returns:
            New access token string, or None on failure.
        """
        if not refresh_token:
            return None

        try:
            response = await self._auth_service.refresh(refresh_token)
        except Exception as e:
            logger.exception("ins-base-rpc /auth/refresh call failed")
            return None

        code = response.get("code", 0)
        if code != 200:
            logger.warning(
                "ins-base-rpc /auth/refresh failed: code=%s msg=%s",
                code,
                response.get("msg", ""),
            )
            return None

        data = response.get("data") or {}
        new_token = data.get("token") or response.get("token")
        return str(new_token) if new_token else None

    async def count_users(self) -> int:
        """Return total number of users - not supported for ins-base provider."""
        return 0

    async def count_admin_users(self) -> int:
        """Return total number of admin users - not supported for ins-base provider."""
        return 0

    async def update_user(self, user) -> None:
        """Update user - not supported for ins-base provider."""
        pass

    async def create_user(self, email: str, password: str | None = None, **kwargs):
        """Create user is not supported - registration is handled on the Java side."""
        raise NotImplementedError("User registration is managed by ins-base-rpc, not available locally")
