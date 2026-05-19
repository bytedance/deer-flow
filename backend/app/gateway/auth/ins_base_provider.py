"""ins-base-rpc authentication provider.

Integrates with the Java ins-base-rpc microservice for user login,
token authentication, and token refresh.
"""

from __future__ import annotations

import logging
from uuid import uuid4

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
    lower = username.lower()
    if lower == "superadmin":
        return "superadmin"
    if lower == "admin":
        return "tenant_admin"
    return "user"


class InsBaseAuthProvider(AuthProvider):
    """Authentication provider backed by the ins-base-rpc Java microservice.

    Login flow:
      1. RSA-encrypt username and password using configured public key
      2. Call ins-base-rpc /auth/login with encrypted credentials
      3. Call ins-base-rpc /auth/authentication to get user info with orgId
      4. Resolve tenant_id from orgId via parent org chain lookup

    Authentication flow:
      1. Call ins-base-rpc /auth/authentication with the token
      2. Resolve tenant_id from orgId in the user info

    Refresh flow:
      1. Call ins-base-rpc /auth/refresh with the refresh token
      2. Return new token
    """

    def __init__(self, rpc_client: RpcClient | None = None, tenant_repo=None):
        self._rpc_client = rpc_client
        self._tenant_repo = tenant_repo

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

    def _extract_org_id(self, user_data: dict) -> str:
        """Extract orgId from ins-base user data.

        Tries user.org.orgId first, then user.orgId.
        """
        org = user_data.get("org") or {}
        org_id = org.get("orgId") if isinstance(org, dict) else None
        if org_id is not None:
            return str(org_id)
        return str(user_data.get("orgId", "0"))

    async def _resolve_tenant_id(self, org_id: str) -> str:
        """Resolve tenant_id from org_id.

        - orgId == "0" → "default"
        - orgId != "0" → call getAllParentOrg, find orgType==13 node,
          get-or-create tenant in database.
        - RPC failure or no factory found → raise RuntimeError
        """
        if org_id == "0":
            return "default"

        from deerflow.rpc.ins_base_org_service import InsBaseOrgServiceClient

        try:
            org_client = InsBaseOrgServiceClient(rpc_client=self._rpc_client)
            parent_orgs = await org_client.get_all_parent_org(int(org_id))
        except Exception as e:
            logger.exception("getAllParentOrg RPC call failed for orgId=%s", org_id)
            raise RuntimeError(f"获取组织信息失败，无法完成登录") from e

        factory_org_id = None
        for org in parent_orgs:
            if org.get("orgType") == 13:
                factory_org_id = str(org.get("orgId", ""))
                break

        if not factory_org_id:
            raise RuntimeError(
                f"未找到所属工厂（orgType=13），无法确定租户，请联系管理员"
            )

        if self._tenant_repo is None:
            logger.warning("Tenant repository not available, using factory orgId as tenant_id=%s", factory_org_id)
            return factory_org_id

        return await self._get_or_create_tenant(factory_org_id)

    async def _get_or_create_tenant(self, tenant_id: str) -> str:
        """Get existing tenant or create a new one with zero limits."""
        existing = await self._tenant_repo.get(tenant_id)
        if existing is not None:
            return tenant_id

        from datetime import UTC, datetime

        from deerflow.config.tenant_storage import TenantConfig

        config = TenantConfig(
            tenant_id=tenant_id,
            name=f"工厂-{tenant_id}",
            created_at=datetime.now(UTC).isoformat(),
            is_active=True,
            daily_quota_usd=0,
            monthly_quota_usd=0,
        )
        try:
            await self._tenant_repo.create(config)
            logger.info("Auto-created tenant %s from factory org", tenant_id)
        except ValueError:
            existing = await self._tenant_repo.get(tenant_id)
            if existing is not None:
                return tenant_id
            raise

        return tenant_id

    async def authenticate(self, credentials: dict):
        """Authenticate with RSA-encrypted username and password via ins-base-rpc.

        After login, calls /auth/authentication to get user info with orgId,
        then resolves tenant_id from the organization chain.

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

        # Resolve tenant_id from user's orgId by calling authentication endpoint
        tenant_id = "default"
        if token:
            auth_response = await self._auth_service.authenticate(token)
            if auth_response.get("code") == 200:
                user_data = auth_response.get("user") or auth_response.get("data", {}).get("user") or {}
                org_id = self._extract_org_id(user_data)
                tenant_id = await self._resolve_tenant_id(org_id)

        user = type(
            "InsBaseUser",
            (),
            {
                "id": uuid4(),
                "email": f"{username}@ins-base",
                "password_hash": None,
                "system_role": _map_system_role(username),
                "needs_setup": False,
                "token_version": 0,
                "tenant_id": tenant_id,
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
        # ins-base returns user/permissions at root level, not nested under "data"
        user_data = data.get("user") or response.get("user") or {}
        permissions = data.get("permissions") or response.get("permissions") or []

        # Extract the real user identifier from ins-base response data.
        # The Java API may use either "userId" or "id" in the user_data dict.
        # The raw token (user_id parameter) is only used as a last resort
        # since it contains dots / special chars that violate the user_id
        # filesystem-path validation in deerflow/config/paths.py.
        #
        # As an additional fallback, decode the JWT token payload without
        # signature verification — the ins-base API has already validated
        # the token. The token itself carries {"id": 1, ...} in its claims.
        token_user_id = user_id
        try:
            import jwt as pyjwt
            token_payload = pyjwt.decode(user_id, options={"verify_signature": False})
            token_user_id = str(
                token_payload.get("id")
                or token_payload.get("sub")
                or user_id
            )
        except Exception:
            pass

        real_user_id = str(
            user_data.get("userId")
            or user_data.get("id")
            or data.get("userId")
            or data.get("id")
            or token_user_id
        )

        # Resolve tenant_id from orgId
        org_id = self._extract_org_id(user_data)
        tenant_id = await self._resolve_tenant_id(org_id)

        user = type(
            "InsBaseUser",
            (),
            {
                "id": real_user_id,
                "email": user_data.get("email", f"user@{real_user_id}"),
                "password_hash": None,
                "system_role": _map_system_role(user_data.get("userName", "")),
                "needs_setup": False,
                "token_version": 0,
                "tenant_id": tenant_id,
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
