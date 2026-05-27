"""ins-base-rpc authentication provider.

Integrates with the Java ins-base-rpc microservice for user login,
token authentication, and token refresh.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from app.gateway.auth.providers import AuthProvider
from app.gateway.auth.rsa_utils import rsa_encrypt
from deerflow.config.auth_config import get_auth_config
from deerflow.rpc.ins_base_auth_service import InsBaseAuthServiceClient
from deerflow.rpc.rpc_client import RpcClient, RpcConnectionError, RpcTimeoutError

logger = logging.getLogger(__name__)

# Short TTL cache for token-based authentication results.
# Each authenticated request hits ins-base /auth/authentication +
# /org/getAllParentOrg + a tenant lookup. Without caching, every API call
# from the frontend (including 30-60s polls) re-runs the full chain.
# A short TTL keeps the perceived freshness while collapsing bursts.
_TOKEN_CACHE_TTL_SECONDS = 60.0
_TENANT_CACHE_TTL_SECONDS = 300.0
_TOKEN_CACHE_MAX_SIZE = 4096
_TENANT_CACHE_MAX_SIZE = 4096


class RpcNotConfiguredError(Exception):
    """Raised when the RPC client is not configured."""


class AuthProviderUnavailableError(Exception):
    """Raised when the ins-base upstream auth service is unavailable."""


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

    def __init__(self, rpc_client: RpcClient | None = None, tenant_repo=None, session_factory=None):
        self._rpc_client = rpc_client
        self._tenant_repo = tenant_repo
        self._session_factory = session_factory
        # token -> (expires_at, user_object)
        self._user_cache: dict[str, tuple[float, object]] = {}
        # org_id -> (expires_at, tenant_id)
        self._tenant_cache: dict[str, tuple[float, str]] = {}

    def _cache_get(self, cache: dict[str, tuple[float, object]], key: str):
        entry = cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            cache.pop(key, None)
            return None
        return value

    def _cache_set(
        self,
        cache: dict,
        key: str,
        value,
        ttl: float,
        max_size: int,
    ) -> None:
        if len(cache) >= max_size:
            # Drop the oldest insertion-order entry; dict preserves insertion order.
            try:
                oldest_key = next(iter(cache))
                cache.pop(oldest_key, None)
            except StopIteration:
                pass
        cache[key] = (time.monotonic() + ttl, value)

    def invalidate_token(self, token: str) -> None:
        """Drop a cached token entry (e.g., after refresh / logout)."""
        if token:
            self._user_cache.pop(token, None)

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

        Results are cached in-memory for ``_TENANT_CACHE_TTL_SECONDS`` to
        avoid hammering the org RPC + DB on every authenticated request.
        """
        if org_id == "0":
            return "default"

        cached = self._cache_get(self._tenant_cache, org_id)
        if cached is not None:
            return cached  # type: ignore[return-value]

        from deerflow.rpc.ins_base_org_service import InsBaseOrgServiceClient

        try:
            org_client = InsBaseOrgServiceClient(rpc_client=self._rpc_client)
            parent_orgs = await org_client.get_all_parent_org(int(org_id))
        except (RpcConnectionError, RpcTimeoutError) as e:
            logger.exception("getAllParentOrg RPC transport failed for orgId=%s", org_id)
            raise AuthProviderUnavailableError("ins-base organization service unavailable") from e
        except Exception as e:
            logger.exception("getAllParentOrg RPC call failed for orgId=%s", org_id)
            raise RuntimeError(f"获取组织信息失败，无法完成登录") from e

        factory_org_id = None
        factory_org_name = None
        for org in parent_orgs:
            if org.get("orgType") == 13:
                factory_org_id = str(org.get("orgId", ""))
                factory_org_name = org.get("orgName") or None
                break

        if not factory_org_id:
            raise RuntimeError(
                f"未找到所属工厂（orgType=13），无法确定租户，请联系管理员"
            )

        if self._tenant_repo is None and self._session_factory is not None:
            sf = self._session_factory()
            if sf is not None:
                from deerflow.persistence.tenant import TenantRepository

                self._tenant_repo = TenantRepository(sf)
                logger.info("_resolve_tenant_id: lazy-created TenantRepository from session_factory")

        if self._tenant_repo is None:
            logger.error(
                "_resolve_tenant_id: tenant_repo is None, session_factory=%s, sf_result=%s. Returning factory orgId without DB persistence!",
                self._session_factory,
                self._session_factory() if self._session_factory else "N/A",
            )
            self._cache_set(
                self._tenant_cache,
                org_id,
                factory_org_id,
                _TENANT_CACHE_TTL_SECONDS,
                _TENANT_CACHE_MAX_SIZE,
            )
            return factory_org_id

        tenant_id = await self._get_or_create_tenant(factory_org_id, factory_org_name)
        self._cache_set(
            self._tenant_cache,
            org_id,
            tenant_id,
            _TENANT_CACHE_TTL_SECONDS,
            _TENANT_CACHE_MAX_SIZE,
        )
        return tenant_id

    async def _get_or_create_tenant(self, tenant_id: str, org_name: str | None = None) -> str:
        """Get existing tenant or create a new one with zero limits."""
        existing = await self._tenant_repo.get(tenant_id)
        if existing is not None:
            logger.debug("_get_or_create_tenant: tenant %s already exists in DB", tenant_id)
            return tenant_id

        from datetime import UTC, datetime

        from deerflow.config.tenant_storage import TenantConfig

        name = org_name or f"工厂-{tenant_id}"
        config = TenantConfig(
            tenant_id=tenant_id,
            name=name,
            created_at=datetime.now(UTC).isoformat(),
            is_active=True,
            daily_quota_usd=0,
            monthly_quota_usd=0,
        )
        logger.info("_get_or_create_tenant: creating tenant %s (name=%s)...", tenant_id, name)
        try:
            await self._tenant_repo.create(config)
            logger.info("_get_or_create_tenant: tenant %s created successfully", tenant_id)
        except ValueError:
            logger.warning("_get_or_create_tenant: tenant %s already exists (ValueError from create)", tenant_id)
            existing = await self._tenant_repo.get(tenant_id)
            if existing is not None:
                return tenant_id
            raise
        except Exception:
            logger.exception("_get_or_create_tenant: FAILED to create tenant %s", tenant_id)
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
        except (RpcConnectionError, RpcTimeoutError) as e:
            logger.exception("ins-base-rpc /auth/login transport failed")
            raise AuthProviderUnavailableError("ins-base authentication service unavailable") from e
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
            try:
                auth_response = await self._auth_service.authenticate(token)
            except (RpcConnectionError, RpcTimeoutError) as e:
                logger.exception("ins-base-rpc /auth/authentication transport failed during login")
                raise AuthProviderUnavailableError("ins-base authentication service unavailable") from e
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

        Results are memoised in a short-TTL in-memory cache so bursty
        frontend traffic (parallel API calls + 30-60s polling) doesn't
        trigger an authentication RPC + org lookup + DB hit on every
        single request.
        """
        if not user_id:
            return None

        cached = self._cache_get(self._user_cache, user_id)
        if cached is not None:
            return cached

        try:
            response = await self._auth_service.authenticate(user_id)
        except (RpcConnectionError, RpcTimeoutError) as e:
            logger.exception("ins-base-rpc /auth/authentication transport failed")
            raise AuthProviderUnavailableError("ins-base authentication service unavailable") from e
        except RpcNotConfiguredError as e:
            raise AuthProviderUnavailableError("ins-base RPC client not configured") from e
        except Exception as e:
            logger.exception("ins-base-rpc /auth/authentication call failed with unexpected error")
            raise AuthProviderUnavailableError(
                f"ins-base authentication returned unexpected error: {e}"
            ) from e

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
        self._cache_set(
            self._user_cache,
            user_id,
            user,
            _TOKEN_CACHE_TTL_SECONDS,
            _TOKEN_CACHE_MAX_SIZE,
        )
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
