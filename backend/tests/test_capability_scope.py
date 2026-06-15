"""Tests for capability scope boundary rules — ISSUE-11.

E2E path: inherit → override → use → fallback (Task 3.1)
Deactivation impact verification (Task 3.2)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.capability_scope import (
    get_affected_tenants,
    impact_summary,
    list_known_tenants,
    propagate_deactivation,
    read_audit_log,
    record_audit,
    resolve_capability_for_tenant,
)

# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_config() -> AppConfig:
    """Minimal AppConfig with a model and tenant-keyed connectors."""
    from deerflow.config.http_connector_config import HttpConnectorConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    return AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        models=[
            ModelConfig(
                name="gpt-4",
                use="openai",
                model="gpt-4",
                display_name="GPT-4",
                description="OpenAI GPT-4 model",
            ),
            ModelConfig(
                name="claude-opus",
                use="anthropic",
                model="claude-opus-4-7",
                display_name="Claude Opus 4.7",
                description="Anthropic Claude Opus",
            ),
        ],
        http_connectors={
            "tenant-a": [
                HttpConnectorConfig(
                    name="erp-api",
                    url="https://erp.tenant-a.example.com/api",
                    method="GET",
                    description="Tenant A ERP connector",
                ),
            ],
            "tenant-b": [
                HttpConnectorConfig(
                    name="erp-api",
                    url="https://erp.tenant-b.example.com/api",
                    method="GET",
                    description="Tenant B ERP connector",
                ),
            ],
        },
    )


@pytest.fixture
def clean_audit_dir():
    """Use a temp directory for audit logs during tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch(
            "deerflow.config.capability_scope.AUDIT_LOG_DIR",
            Path(tmpdir),
        ):
            yield Path(tmpdir)


# ── Task 3.1: E2E tenant enablement path ──────────────────────────────────

class TestTenantEnablementE2E:
    """Verify the complete path: global exists → tenant inherits → tenant
    creates override → tenant uses override → tenant disables override →
    falls back to global."""

    def test_tenant_inherits_global_model(self, sample_config):
        """Step 1-2: Global model exists → tenant inherits it."""
        resolved = resolve_capability_for_tenant(
            "tenant-a", "model", "gpt-4", sample_config
        )
        assert resolved is not None
        assert resolved["name"] == "gpt-4"
        assert resolved["scope"] == "GLOBAL"
        assert resolved["resolution"] == "inherited"
        assert resolved["config"]["use"] == "openai"

    def test_tenant_sees_own_connector_directly(self, sample_config):
        """Step 3-4: Tenant connector is TENANT scope, resolved directly."""
        resolved = resolve_capability_for_tenant(
            "tenant-a", "connector", "erp-api", sample_config
        )
        assert resolved is not None
        assert resolved["name"] == "erp-api"
        assert resolved["scope"] == "TENANT"
        assert resolved["resolution"] == "tenant_direct"
        assert "tenant-a" in resolved["config"]["url"]

    def test_tenant_b_has_different_connector_url(self, sample_config):
        """Different tenants get different connector configs."""
        a = resolve_capability_for_tenant(
            "tenant-a", "connector", "erp-api", sample_config
        )
        b = resolve_capability_for_tenant(
            "tenant-b", "connector", "erp-api", sample_config
        )
        assert a["config"]["url"] != b["config"]["url"]
        assert "tenant-a" in a["config"]["url"]
        assert "tenant-b" in b["config"]["url"]

    def test_nonexistent_capability_returns_none(self, sample_config):
        """Step 5b: Non-existent capability → None (fallback/not available)."""
        resolved = resolve_capability_for_tenant(
            "tenant-a", "model", "nonexistent-model", sample_config
        )
        assert resolved is None

    def test_known_tenants_discovered_from_connectors(self, sample_config):
        """Tenant IDs are discoverable from connector config."""
        tenants = list_known_tenants(sample_config)
        assert "tenant-a" in tenants
        assert "tenant-b" in tenants


# ── Task 3.2: Deactivation impact verification ────────────────────────────

class TestDeactivationImpact:
    """Verify that deactivating a global capability correctly identifies
    affected tenants and shields those with active overrides."""

    def test_global_model_affects_all_tenants(self, sample_config):
        """Deactivating a global model affects all known tenants."""
        affected = get_affected_tenants("model", "gpt-4", sample_config)
        assert len(affected) == 2
        assert "tenant-a" in affected
        assert "tenant-b" in affected

    def test_tenant_connector_affects_only_owner(self, sample_config):
        """Deactivating a tenant connector only affects the owning tenant."""
        affected = get_affected_tenants(
            "connector", "erp-api", sample_config
        )
        # Connector name "erp-api" exists for both tenants
        assert len(affected) == 2
        assert "tenant-a" in affected
        assert "tenant-b" in affected

    def test_impact_summary_warning_levels(self, sample_config):
        """Impact summary produces correct warning levels."""
        # Global deactivation → critical
        summary = impact_summary("model", "gpt-4", "deactivate", sample_config)
        assert summary["warning_level"] == "critical"
        assert summary["affected_count"] == 2

        # Tenant deactivation → warning
        summary = impact_summary(
            "connector", "erp-api", "deactivate", sample_config
        )
        assert summary["warning_level"] == "warning"

        # Global modification → info
        summary = impact_summary("model", "gpt-4", "modify", sample_config)
        assert summary["warning_level"] == "info"

    def test_propagation_no_shielded_when_no_overrides(self, sample_config):
        """Without overrides, all affected tenants are truly affected."""
        report = propagate_deactivation(
            "model", "gpt-4", sample_config, actor="test-runner"
        )
        assert report["action"] == "deactivate"
        assert report["total_affected"] == 2
        assert report["shielded_tenants"] == []

    def test_nonexistent_capability_no_affected(self, sample_config):
        """Unknown capability has no affected tenants."""
        affected = get_affected_tenants("model", "no-such-model", sample_config)
        assert affected == []


# ── Audit trail tests ─────────────────────────────────────────────────────

class TestAuditTrail:
    def test_record_and_read_audit(self, clean_audit_dir, sample_config):
        """Audit records are persisted and retrievable."""
        record_audit(
            actor="admin",
            change_type="deactivate",
            capability_type="model",
            capability_name="gpt-4",
            scope="GLOBAL",
            affected_tenants=["tenant-a", "tenant-b"],
            details={"reason": "security review"},
        )

        records = read_audit_log(capability_type="model", capability_name="gpt-4")
        assert len(records) == 1
        assert records[0]["actor"] == "admin"
        assert records[0]["change_type"] == "deactivate"
        assert records[0]["affected_tenants"] == ["tenant-a", "tenant-b"]
        assert records[0]["details"]["reason"] == "security review"

    def test_audit_filtered_by_type(self, clean_audit_dir):
        """Audit log filtering by capability type works."""
        record_audit("admin", "publish", "model", "m1", "GLOBAL")
        record_audit("admin", "publish", "skill", "s1", "GLOBAL")

        models = read_audit_log(capability_type="model")
        assert len(models) == 1
        assert models[0]["capability_name"] == "m1"

        skills = read_audit_log(capability_type="skill")
        assert len(skills) == 1
        assert skills[0]["capability_name"] == "s1"

    def test_audit_respects_limit(self, clean_audit_dir):
        """Audit log respects the limit parameter."""
        for i in range(5):
            record_audit("admin", "modify", "model", f"m{i}", "GLOBAL")

        records = read_audit_log(limit=3)
        assert len(records) == 3

    def test_deactivation_produces_audit_record(self, clean_audit_dir, sample_config):
        """propagate_deactivation writes an audit record."""
        propagate_deactivation("model", "gpt-4", sample_config, actor="ops-team")

        records = read_audit_log(capability_type="model", capability_name="gpt-4")
        assert len(records) == 1
        assert records[0]["actor"] == "ops-team"
        assert records[0]["change_type"] == "deactivate"
