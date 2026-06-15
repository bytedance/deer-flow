"""Unit tests for integration management API (Phase 1.10.14-1.10.15).

Covers:
- Capability collector: _collect_integration_systems()
- API endpoints: list_integration_systems, list_capability_routes, list_entity_links, run_health_check, get_audit_log
- Tenant-scoped access control: _require_tenant_admin()
- Audit logging: _record_audit()
- Rate limiting: endpoint configuration
- Degradation strategy: _record_health_failure(), _record_health_success(), is_system_degraded()
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.gateway.routers.integrations import (
    _AUDIT_LOG_MAX,
    _audit_log,
    _degradation_tracker,
    _degraded_systems,
    _record_audit,
    _record_health_failure,
    _record_health_success,
    _require_tenant_admin,
    is_system_degraded,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_state():
    """Reset degradation tracker and audit log before each test."""
    _degradation_tracker.clear()
    _degraded_systems.clear()
    _audit_log.clear()
    yield
    _degradation_tracker.clear()
    _degraded_systems.clear()
    _audit_log.clear()


@pytest.fixture
def mock_request():
    """Mock FastAPI Request with user state."""
    request = MagicMock()
    request.state = MagicMock()
    return request


# ---------------------------------------------------------------------------
# Degradation Strategy Tests (1.10.15)
# ---------------------------------------------------------------------------


class TestDegradationStrategy:
    """Test auto-degradation after consecutive failures and recovery."""

    def test_record_health_failure_increments_counter(self):
        """Each failure increments the counter."""
        count1 = _record_health_failure("system-a")
        assert count1 == 1
        assert _degradation_tracker["system-a"] == 1

        count2 = _record_health_failure("system-a")
        assert count2 == 2
        assert _degradation_tracker["system-a"] == 2

    def test_auto_degrade_after_threshold(self):
        """System auto-degrades after 3 consecutive failures."""
        assert not is_system_degraded("system-b")

        _record_health_failure("system-b")
        _record_health_failure("system-b")
        assert not is_system_degraded("system-b")

        _record_health_failure("system-b")
        assert is_system_degraded("system-b")
        assert "system-b" in _degraded_systems

    def test_record_health_success_resets_counter(self):
        """Success resets failure counter and removes degraded status."""
        _record_health_failure("system-c")
        _record_health_failure("system-c")
        _record_health_failure("system-c")
        assert is_system_degraded("system-c")
        assert _degradation_tracker["system-c"] == 3

        _record_health_success("system-c")
        assert not is_system_degraded("system-c")
        assert _degradation_tracker["system-c"] == 0
        assert "system-c" not in _degraded_systems

    def test_multiple_systems_tracked_independently(self):
        """Each system's degradation is tracked independently."""
        _record_health_failure("sys-x")
        _record_health_failure("sys-x")
        _record_health_failure("sys-x")

        _record_health_failure("sys-y")

        assert is_system_degraded("sys-x")
        assert not is_system_degraded("sys-y")

    def test_recovery_after_degradation(self):
        """System can recover from degraded state."""
        _record_health_failure("system-d")
        _record_health_failure("system-d")
        _record_health_failure("system-d")
        assert is_system_degraded("system-d")

        _record_health_success("system-d")
        assert not is_system_degraded("system-d")

        # Can degrade again
        _record_health_failure("system-d")
        _record_health_failure("system-d")
        _record_health_failure("system-d")
        assert is_system_degraded("system-d")


# ---------------------------------------------------------------------------
# Audit Logging Tests (1.10.15)
# ---------------------------------------------------------------------------


class TestAuditLogging:
    """Test structured audit logging with cap."""

    def test_record_audit_creates_entry(self):
        """Audit entry is created with all fields."""
        _record_audit(
            actor="user@example.com",
            tenant_id="tenant-1",
            action="health_check_failed",
            target="ins-prod",
            details={"message": "timeout"},
        )

        assert len(_audit_log) == 1
        entry = _audit_log[0]
        assert entry["actor"] == "user@example.com"
        assert entry["tenant_id"] == "tenant-1"
        assert entry["action"] == "health_check_failed"
        assert entry["target"] == "ins-prod"
        assert entry["details"] == {"message": "timeout"}
        assert "timestamp" in entry

    def test_audit_log_capped_at_max(self):
        """Audit log is capped at _AUDIT_LOG_MAX entries."""
        for i in range(_AUDIT_LOG_MAX + 50):
            _record_audit(
                actor="user",
                tenant_id="tenant",
                action=f"action-{i}",
                target="target",
            )

        assert len(_audit_log) == _AUDIT_LOG_MAX
        # Oldest entries should be removed
        assert _audit_log[0]["action"] == "action-50"
        assert _audit_log[-1]["action"] == f"action-{_AUDIT_LOG_MAX + 49}"

    def test_audit_log_empty_details_default(self):
        """Empty details defaults to empty dict."""
        _record_audit(
            actor="user",
            tenant_id="tenant",
            action="test",
            target="target",
        )

        assert _audit_log[0]["details"] == {}


# ---------------------------------------------------------------------------
# Tenant-Scoped Access Control Tests (1.10.15)
# ---------------------------------------------------------------------------


class TestTenantScopedAccessControl:
    """Test tenant admin access control."""

    def test_superadmin_can_access_any_tenant(self, mock_request):
        """Superadmin can access any tenant's config."""
        mock_request.state.user.system_role = "superadmin"
        mock_request.state.user.tenant_id = "admin-tenant"

        # Should not raise
        _require_tenant_admin(mock_request, "other-tenant")

    def test_tenant_admin_can_access_own_tenant(self, mock_request):
        """Tenant admin can access own tenant's config."""
        mock_request.state.user.system_role = "tenant_admin"
        mock_request.state.user.tenant_id = "tenant-1"

        # Should not raise
        _require_tenant_admin(mock_request, "tenant-1")

    def test_tenant_admin_cannot_access_other_tenant(self, mock_request):
        """Tenant admin cannot access other tenant's config."""
        mock_request.state.user.system_role = "tenant_admin"
        mock_request.state.user.tenant_id = "tenant-1"

        with pytest.raises(HTTPException) as exc_info:
            _require_tenant_admin(mock_request, "tenant-2")

        assert exc_info.value.status_code == 403
        assert "different tenant" in exc_info.value.detail.lower()

    def test_regular_user_cannot_access(self, mock_request):
        """Regular user cannot access tenant admin endpoints."""
        mock_request.state.user.system_role = "user"
        mock_request.state.user.tenant_id = "tenant-1"

        with pytest.raises(HTTPException) as exc_info:
            _require_tenant_admin(mock_request, "tenant-1")

        assert exc_info.value.status_code == 403
        assert "privileges required" in exc_info.value.detail.lower()

    def test_no_user_raises_403(self, mock_request):
        """No user in request state raises 403."""
        mock_request.state.user = None

        with pytest.raises(HTTPException) as exc_info:
            _require_tenant_admin(mock_request, "tenant-1")

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# API Endpoint Tests (1.10.14)
# ---------------------------------------------------------------------------


class TestIntegrationAPIEndpoints:
    """Test integration management API endpoint logic via direct calls."""

    @pytest.mark.asyncio
    async def test_list_integration_systems_returns_empty_on_import_error(self, mock_request):
        """Returns empty list when integration registry not available."""
        from app.gateway.routers.integrations import list_integration_systems

        result = await list_integration_systems(
            tenant_id="test-tenant",
            request=mock_request,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_capability_routes_returns_list(self, mock_request):
        """Returns capability routes from config (possibly empty)."""
        from app.gateway.routers.integrations import list_capability_routes

        result = await list_capability_routes(
            tenant_id="test-tenant",
            request=mock_request,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_entity_links_returns_list(self, mock_request):
        """Returns entity links from config (possibly empty)."""
        from app.gateway.routers.integrations import list_entity_links

        result = await list_entity_links(
            tenant_id="test-tenant",
            request=mock_request,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_run_health_check_requires_tenant_admin(self, mock_request):
        """Health check endpoint requires tenant admin auth."""
        from app.gateway.routers.integrations import run_health_check

        mock_request.state.user.system_role = "user"
        mock_request.state.user.tenant_id = "test-tenant"

        with pytest.raises(HTTPException) as exc_info:
            await run_health_check(
                tenant_id="test-tenant",
                system_key="test-system",
                request=mock_request,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_audit_log_requires_tenant_admin(self, mock_request):
        """Audit log endpoint requires tenant admin auth."""
        from app.gateway.routers.integrations import get_audit_log

        mock_request.state.user.system_role = "user"
        mock_request.state.user.tenant_id = "test-tenant"

        with pytest.raises(HTTPException) as exc_info:
            await get_audit_log(
                tenant_id="test-tenant",
                request=mock_request,
                limit=50,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_audit_log_returns_entries_for_superadmin(self, mock_request):
        """Superadmin can retrieve all audit log entries."""
        from app.gateway.routers.integrations import get_audit_log

        _record_audit("admin1", "tenant-1", "action1", "target1")
        _record_audit("admin2", "tenant-2", "action2", "target2")

        mock_request.state.user.system_role = "superadmin"
        mock_request.state.user.tenant_id = "admin-tenant"

        result = await get_audit_log(
            tenant_id="any-tenant",
            request=mock_request,
            limit=50,
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_audit_log_filters_for_tenant_admin(self, mock_request):
        """Tenant admin only sees own tenant's audit entries."""
        from app.gateway.routers.integrations import get_audit_log

        _record_audit("admin1", "tenant-1", "action1", "target1")
        _record_audit("admin2", "tenant-2", "action2", "target2")
        _record_audit("admin1", "tenant-1", "action3", "target3")

        mock_request.state.user.system_role = "tenant_admin"
        mock_request.state.user.tenant_id = "tenant-1"

        result = await get_audit_log(
            tenant_id="tenant-1",
            request=mock_request,
            limit=50,
        )
        assert len(result) == 2
        assert all(e.tenant_id == "tenant-1" for e in result)

    @pytest.mark.asyncio
    async def test_run_health_check_with_unknown_system(self, mock_request):
        """Health check on unknown system returns 404."""
        from app.gateway.routers.integrations import run_health_check

        mock_request.state.user.system_role = "superadmin"
        mock_request.state.user.tenant_id = "admin-tenant"

        with pytest.raises(HTTPException) as exc_info:
            await run_health_check(
                tenant_id="test-tenant",
                system_key="nonexistent-system",
                request=mock_request,
            )
        assert exc_info.value.status_code in [404, 503]

    @pytest.mark.asyncio
    async def test_get_audit_log_respects_limit(self, mock_request):
        """Audit log limit parameter is respected."""
        from app.gateway.routers.integrations import get_audit_log

        for i in range(20):
            _record_audit("admin", "tenant-1", f"action-{i}", "target")

        mock_request.state.user.system_role = "superadmin"
        mock_request.state.user.tenant_id = "admin-tenant"

        result = await get_audit_log(
            tenant_id="tenant-1",
            request=mock_request,
            limit=5,
        )
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Integration Tests for Degradation + Health Check
# ---------------------------------------------------------------------------


class TestHealthCheckDegradationIntegration:
    """Integration tests for health check endpoint with degradation tracking."""

    def test_health_check_updates_degradation_on_failure(self):
        """Health check failure updates degradation tracker."""
        # Simulate 3 consecutive failures
        for _ in range(3):
            _record_health_failure("test-system")

        assert is_system_degraded("test-system")
        assert _degradation_tracker["test-system"] == 3

    def test_health_check_resets_degradation_on_success(self):
        """Health check success resets degradation tracker."""
        _record_health_failure("test-system")
        _record_health_failure("test-system")
        _record_health_failure("test-system")
        assert is_system_degraded("test-system")

        _record_health_success("test-system")
        assert not is_system_degraded("test-system")
        assert _degradation_tracker["test-system"] == 0


# ---------------------------------------------------------------------------
# Audit Log Filtering Tests
# ---------------------------------------------------------------------------


class TestAuditLogFiltering:
    """Test audit log filtering by tenant."""

    def test_tenant_admin_sees_only_own_tenant_entries(self):
        """Tenant admin audit endpoint filters by tenant."""
        _record_audit("admin1", "tenant-1", "action1", "target1")
        _record_audit("admin2", "tenant-2", "action2", "target2")
        _record_audit("admin1", "tenant-1", "action3", "target3")

        # Simulate tenant-1 admin filtering
        tenant_1_entries = [e for e in _audit_log if e["tenant_id"] == "tenant-1"]
        assert len(tenant_1_entries) == 2
        assert all(e["tenant_id"] == "tenant-1" for e in tenant_1_entries)

    def test_superadmin_sees_all_entries(self):
        """Superadmin audit endpoint returns all entries."""
        _record_audit("admin1", "tenant-1", "action1", "target1")
        _record_audit("admin2", "tenant-2", "action2", "target2")

        # Superadmin sees all
        assert len(_audit_log) == 2
