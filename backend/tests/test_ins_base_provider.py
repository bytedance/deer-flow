"""Tests for InsBaseAuthProvider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.auth.ins_base_provider import InsBaseAuthProvider, RpcNotConfiguredError


@pytest.fixture(scope="module")
def rsa_public_key():
    """Generate a real RSA public key for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


@pytest.fixture
def mock_rpc_client():
    """Create a mock RPC client."""
    client = MagicMock()
    client.call_raw = AsyncMock()
    return client


@pytest.fixture
def provider(mock_rpc_client, rsa_public_key):
    """Create an InsBaseAuthProvider with a mock RPC client and real RSA key."""
    with (
        patch("app.gateway.auth.ins_base_provider.get_auth_config") as mock_config,
        patch("deerflow.rpc.ins_base_auth_service.get_rpc_client", return_value=mock_rpc_client),
    ):
        cfg = MagicMock()
        cfg.rsa_public_key = rsa_public_key
        mock_config.return_value = cfg
        yield InsBaseAuthProvider()


class TestInsBaseAuthProvider:
    """Tests for InsBaseAuthProvider."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self, provider, mock_rpc_client):
        """Successful login returns a user-like object with token and default tenant."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "msg": "登录成功",
            "data": {
                "token": "mock-jwt-token",
                "refresh": "mock-refresh-token",
            },
            "token": "mock-jwt-token",
            "refresh": "mock-refresh-token",
        }

        result = await provider.authenticate({"username": "testuser", "password": "testpass"})

        assert result is not None
        assert str(result.tenant_id) == "default"
        assert result.ins_base_token == "mock-jwt-token"
        assert result.ins_base_refresh == "mock-refresh-token"
        assert mock_rpc_client.call_raw.called

    @pytest.mark.asyncio
    async def test_authenticate_success_admin_role(self, provider, mock_rpc_client):
        """Username 'superadmin' gets superadmin role."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "data": {"token": "t1", "refresh": "r1"},
            "token": "t1",
            "refresh": "r1",
        }

        result = await provider.authenticate({"username": "superadmin", "password": "pass"})

        assert result is not None
        assert result.system_role == "superadmin"

    @pytest.mark.asyncio
    async def test_authenticate_success_tenant_admin_role(self, provider, mock_rpc_client):
        """Username 'admin' gets tenant_admin role."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "data": {"token": "t1", "refresh": "r1"},
            "token": "t1",
            "refresh": "r1",
        }

        result = await provider.authenticate({"username": "admin", "password": "pass"})

        assert result is not None
        assert result.system_role == "tenant_admin"

    @pytest.mark.asyncio
    async def test_authenticate_success_user_role(self, provider, mock_rpc_client):
        """Normal username gets user role."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "data": {"token": "t1", "refresh": "r1"},
            "token": "t1",
            "refresh": "r1",
        }

        result = await provider.authenticate({"username": "zhangsan", "password": "pass"})

        assert result is not None
        assert result.system_role == "user"

    @pytest.mark.asyncio
    async def test_authenticate_failure(self, provider, mock_rpc_client):
        """Failed login raises RuntimeError."""
        mock_rpc_client.call_raw.return_value = {
            "code": 500,
            "msg": "登录失败",
        }

        with pytest.raises(RuntimeError, match="登录失败"):
            await provider.authenticate({"username": "testuser", "password": "testpass"})

    @pytest.mark.asyncio
    async def test_authenticate_empty_credentials(self, provider, mock_rpc_client):
        """Empty credentials return None without calling RPC."""
        result = await provider.authenticate({"username": "", "password": "testpass"})
        assert result is None

        result = await provider.authenticate({"username": "testuser", "password": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_rpc_error(self, provider, mock_rpc_client):
        """RPC error raises RuntimeError."""
        mock_rpc_client.call_raw.side_effect = Exception("Connection refused")

        with pytest.raises(RuntimeError, match="登录服务调用失败"):
            await provider.authenticate({"username": "testuser", "password": "testpass"})

    @pytest.mark.asyncio
    async def test_get_user_success(self, provider, mock_rpc_client):
        """Successful authentication returns user with permissions."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "data": {
                "user": {
                    "userId": 12345,
                    "email": "user@example.com",
                },
                "permissions": ["read", "write"],
            },
        }

        result = await provider.get_user("valid-token")

        assert result is not None
        assert str(result.tenant_id) == "default"
        assert "read" in result.ins_base_permissions
        assert mock_rpc_client.call_raw.called

    @pytest.mark.asyncio
    async def test_get_user_role_mapping(self, provider, mock_rpc_client):
        """get_user maps username from ins-base data to system_role."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "data": {
                "user": {
                    "userId": 1,
                    "username": "superadmin",
                },
                "permissions": [],
            },
        }

        result = await provider.get_user("token")

        assert result is not None
        assert result.system_role == "superadmin"

    @pytest.mark.asyncio
    async def test_get_user_invalid_token(self, provider, mock_rpc_client):
        """Invalid token returns None."""
        mock_rpc_client.call_raw.return_value = {
            "code": 401,
            "msg": "无效token",
        }

        result = await provider.get_user("invalid-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_empty_token(self, provider):
        """Empty token returns None without calling RPC."""
        result = await provider.get_user("")
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, provider, mock_rpc_client):
        """Successful refresh returns new token."""
        mock_rpc_client.call_raw.return_value = {
            "code": 200,
            "data": {
                "token": "new-jwt-token",
            },
            "token": "new-jwt-token",
        }

        result = await provider.refresh_token("valid-refresh")

        assert result == "new-jwt-token"
        assert mock_rpc_client.call_raw.called

    @pytest.mark.asyncio
    async def test_refresh_token_failure(self, provider, mock_rpc_client):
        """Failed refresh returns None."""
        mock_rpc_client.call_raw.return_value = {
            "code": 401,
            "msg": "无效refresh",
        }

        result = await provider.refresh_token("invalid-refresh")
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token_empty(self, provider):
        """Empty refresh token returns None."""
        result = await provider.refresh_token("")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_rpc_client_configured(self, rsa_public_key):
        """Raises RuntimeError when RPC client is not configured."""
        with (
            patch("app.gateway.auth.ins_base_provider.get_auth_config") as mock_config,
            patch("deerflow.rpc.ins_base_auth_service.get_rpc_client", return_value=None),
        ):
            cfg = MagicMock()
            cfg.rsa_public_key = rsa_public_key
            mock_config.return_value = cfg
            p = InsBaseAuthProvider()
            with pytest.raises(RpcNotConfiguredError):
                await p.authenticate({"username": "u", "password": "p"})

    @pytest.mark.asyncio
    async def test_no_rsa_key_configured(self, mock_rpc_client):
        """Raises error when RSA key is not configured."""
        with (
            patch("app.gateway.auth.ins_base_provider.get_auth_config") as mock_config,
            patch("deerflow.rpc.ins_base_auth_service.get_rpc_client", return_value=mock_rpc_client),
        ):
            cfg = MagicMock()
            cfg.rsa_public_key = ""
            mock_config.return_value = cfg
            p = InsBaseAuthProvider()
            with pytest.raises(ValueError, match="RSA public key is not configured"):
                await p.authenticate({"username": "u", "password": "p"})

    @pytest.mark.asyncio
    async def test_count_users(self, provider):
        """count_users returns 0 for ins-base provider."""
        assert await provider.count_users() == 0

    @pytest.mark.asyncio
    async def test_create_user_not_supported(self, provider):
        """create_user raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await provider.create_user("test@example.com", "password")
