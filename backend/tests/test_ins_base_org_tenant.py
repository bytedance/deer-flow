"""Tests for ins_base org-based tenant resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.tenant_storage import TenantConfig


class FakeTenantRepo:
    """Fake tenant repository for testing get-or-create logic."""

    def __init__(self, existing_tenants: dict[str, TenantConfig] | None = None):
        self._tenants = existing_tenants or {}
        self._create_calls: list[TenantConfig] = []

    async def get(self, tenant_id: str) -> TenantConfig | None:
        return self._tenants.get(tenant_id)

    async def create(self, config: TenantConfig) -> TenantConfig:
        if config.tenant_id in self._tenants:
            raise ValueError(f"Tenant {config.tenant_id!r} already exists")
        self._tenants[config.tenant_id] = config
        self._create_calls.append(config)
        return config


def _make_provider(rpc_client=None, tenant_repo=None):
    """Create an InsBaseAuthProvider instance."""
    from app.gateway.auth.ins_base_provider import InsBaseAuthProvider

    return InsBaseAuthProvider(rpc_client=rpc_client, tenant_repo=tenant_repo)


class TestExtractOrgId:
    """Tests for _extract_org_id."""

    def test_org_id_from_nested_org(self):
        provider = _make_provider()
        user_data = {"org": {"orgId": 5}, "orgId": 3}
        assert provider._extract_org_id(user_data) == "5"

    def test_org_id_from_flat(self):
        provider = _make_provider()
        user_data = {"orgId": 7}
        assert provider._extract_org_id(user_data) == "7"

    def test_org_id_missing_defaults_to_zero(self):
        provider = _make_provider()
        assert provider._extract_org_id({}) == "0"

    def test_org_id_empty_org_dict(self):
        provider = _make_provider()
        user_data = {"org": {}}
        assert provider._extract_org_id(user_data) == "0"


class TestResolveTenantId:
    """Tests for _resolve_tenant_id."""

    @pytest.mark.asyncio
    async def test_org_id_zero_returns_default(self):
        provider = _make_provider()
        result = await provider._resolve_tenant_id("0")
        assert result == "default"

    @pytest.mark.asyncio
    async def test_factory_found_in_parent_orgs(self):
        parent_orgs = [
            {"orgId": 1, "orgType": 10, "orgName": "集团"},
            {"orgId": 5, "orgType": 13, "orgName": "工厂A"},
            {"orgId": 9, "orgType": 13, "orgName": "工厂B"},
        ]
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider(tenant_repo=FakeTenantRepo())
            result = await provider._resolve_tenant_id("5")
            assert result == "5"

    @pytest.mark.asyncio
    async def test_no_factory_raises_error(self):
        parent_orgs = [
            {"orgId": 1, "orgType": 10, "orgName": "集团"},
            {"orgId": 2, "orgType": 20, "orgName": "部门"},
        ]
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider()
            with pytest.raises(RuntimeError, match="未找到所属工厂"):
                await provider._resolve_tenant_id("5")

    @pytest.mark.asyncio
    async def test_rpc_failure_raises_error(self):
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(side_effect=RuntimeError("network error"))

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider()
            with pytest.raises(RuntimeError, match="获取组织信息失败"):
                await provider._resolve_tenant_id("5")

    @pytest.mark.asyncio
    async def test_tenant_already_exists(self):
        existing = TenantConfig(
            tenant_id="5",
            name="已有工厂",
            created_at=datetime.now(UTC).isoformat(),
            daily_quota_usd=100,
            monthly_quota_usd=1000,
        )
        repo = FakeTenantRepo({"5": existing})

        parent_orgs = [{"orgId": 5, "orgType": 13}]
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider(tenant_repo=repo)
            result = await provider._resolve_tenant_id("5")
            assert result == "5"
            assert len(repo._create_calls) == 0

    @pytest.mark.asyncio
    async def test_tenant_not_exists_auto_creates(self):
        repo = FakeTenantRepo()

        parent_orgs = [{"orgId": 5, "orgType": 13}]
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider(tenant_repo=repo)
            result = await provider._resolve_tenant_id("5")
            assert result == "5"
            assert len(repo._create_calls) == 1
            created = repo._create_calls[0]
            assert created.tenant_id == "5"
            assert created.name == "工厂-5"
            assert created.daily_quota_usd == 0
            assert created.monthly_quota_usd == 0
            assert created.is_active is True

    @pytest.mark.asyncio
    async def test_concurrent_creation_is_idempotent(self):
        """Simulate concurrent creation: first create fails with ValueError."""
        existing = TenantConfig(
            tenant_id="5",
            name="并发创建的工厂",
            created_at=datetime.now(UTC).isoformat(),
        )

        class ConcurrentFakeRepo(FakeTenantRepo):
            async def create(self, config):
                if config.tenant_id in self._tenants:
                    raise ValueError(f"Tenant {config.tenant_id!r} already exists")
                return await super().create(config)

        repo = ConcurrentFakeRepo({"5": existing})

        parent_orgs = [{"orgId": 5, "orgType": 13}]
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider(tenant_repo=repo)
            result = await provider._resolve_tenant_id("5")
            assert result == "5"
            assert len(repo._create_calls) == 0

    @pytest.mark.asyncio
    async def test_no_tenant_repo_uses_factory_id_directly(self):
        parent_orgs = [{"orgId": 5, "orgType": 13}]
        mock_client = MagicMock()
        mock_client.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_client,
        ):
            provider = _make_provider(tenant_repo=None)
            result = await provider._resolve_tenant_id("5")
            assert result == "5"


class TestGetUserTenantResolution:
    """Tests for tenant resolution in get_user()."""

    @pytest.mark.asyncio
    async def test_get_user_resolves_tenant_from_org_id(self):
        auth_response = {
            "code": 200,
            "permissions": ["*:*:*"],
            "user": {
                "userId": "1",
                "userName": "testUser",
                "orgId": "0",
                "org": {"orgId": "5", "authFlag": True},
            },
        }
        mock_auth = MagicMock()
        mock_auth.authenticate = AsyncMock(return_value=auth_response)

        parent_orgs = [{"orgId": 5, "orgType": 13, "orgName": "测试工厂"}]
        mock_org = MagicMock()
        mock_org.get_all_parent_org = AsyncMock(return_value=parent_orgs)

        with patch(
            "app.gateway.auth.ins_base_provider.InsBaseAuthServiceClient",
            return_value=mock_auth,
        ), patch(
            "deerflow.rpc.ins_base_org_service.InsBaseOrgServiceClient",
            return_value=mock_org,
        ):
            provider = _make_provider(tenant_repo=FakeTenantRepo())
            user = await provider.get_user("test-token")
            assert user is not None
            assert user.tenant_id == "5"

    @pytest.mark.asyncio
    async def test_get_user_org_id_zero_uses_default(self):
        auth_response = {
            "code": 200,
            "permissions": ["*:*:*"],
            "user": {
                "userId": "1",
                "userName": "superAdmin",
                "orgId": "0",
                "org": {"orgId": "0", "authFlag": True},
            },
        }
        mock_auth = MagicMock()
        mock_auth.authenticate = AsyncMock(return_value=auth_response)

        with patch(
            "app.gateway.auth.ins_base_provider.InsBaseAuthServiceClient",
            return_value=mock_auth,
        ):
            provider = _make_provider()
            user = await provider.get_user("test-token")
            assert user is not None
            assert user.tenant_id == "default"
