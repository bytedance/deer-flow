"""Unit tests for integration config models (Task 1.1.8).

Covers:
- IntegrationSystemConfig validation, defaults, secret resolution
- CapabilityRouteConfig validation (simple form, full form, overlap check)
- EntityLinkConfig validation, confidence bounds
- IntegrationsConfig route parsing, system validation
- RetryPolicy defaults
- connector_ref field
"""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from deerflow.integrations.config import (
    CapabilityRouteConfig,
    EntityLinkConfig,
    EntityLinkEntry,
    IntegrationSystemConfig,
    IntegrationsConfig,
    RetryPolicy,
)
from deerflow.integrations.errors import IntegrationConfigError


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_retries == 2
        assert p.retry_on_status == [502, 503, 504]

    def test_custom(self):
        p = RetryPolicy(max_retries=5, retry_on_status=[500])
        assert p.max_retries == 5
        assert p.retry_on_status == [500]


# ---------------------------------------------------------------------------
# IntegrationSystemConfig
# ---------------------------------------------------------------------------


class TestIntegrationSystemConfig:
    def _base(self, **overrides):
        defaults = {
            "system_key": "ins_prod",
            "system_type": "ins",
            "display_name": "InS Production",
            "base_url": "http://ins.example.com",
            "auth_type": "bearer",
        }
        defaults.update(overrides)
        return IntegrationSystemConfig(**defaults)

    def test_minimal_fields(self):
        c = self._base()
        assert c.system_key == "ins_prod"
        assert c.system_type == "ins"
        assert c.base_url == "http://ins.example.com"
        assert c.auth_type == "bearer"

    def test_defaults(self):
        c = self._base()
        assert c.description == ""
        assert c.connector_ref is None
        assert c.transport_type == "http"
        assert c.base_path == ""
        assert c.secret_ref is None
        assert c.timeout_seconds == 15.0
        assert c.max_retries == 2
        assert c.priority == 100
        assert c.enabled is True
        assert c.capabilities == []
        assert c.extra_config == {}

    def test_invalid_system_type(self):
        with pytest.raises(ValidationError):
            self._base(system_type="unknown_type")

    def test_invalid_transport_type(self):
        with pytest.raises(ValidationError):
            self._base(transport_type="grpc")

    def test_invalid_auth_type(self):
        with pytest.raises(ValidationError):
            self._base(auth_type="oauth2")

    def test_connector_ref_field(self):
        c = self._base(connector_ref="ins_http_main")
        assert c.connector_ref == "ins_http_main"

    def test_capabilities_list(self):
        c = self._base(capabilities=["asset.catalog", "monitoring.trend"])
        assert c.capabilities == ["asset.catalog", "monitoring.trend"]

    def test_extra_config(self):
        c = self._base(extra_config={"factory_id": "F001"})
        assert c.extra_config["factory_id"] == "F001"

    def test_crm_system_type(self):
        c = self._base(system_type="crm", auth_type="api_key")
        assert c.system_type == "crm"

    def test_erp_system_type(self):
        c = self._base(system_type="erp", auth_type="api_key")
        assert c.system_type == "erp"


class TestSecretResolution:
    def test_resolve_env_var(self):
        c = IntegrationSystemConfig(
            system_key="test",
            system_type="ins",
            display_name="Test",
            base_url="http://test",
            auth_type="bearer",
            secret_ref="$MY_SECRET",
        )
        with patch.dict(os.environ, {"MY_SECRET": "token123"}):
            assert c.resolve_secret() == "token123"

    def test_resolve_missing_env_raises(self):
        c = IntegrationSystemConfig(
            system_key="test",
            system_type="ins",
            display_name="Test",
            base_url="http://test",
            auth_type="bearer",
            secret_ref="$NONEXISTENT_VAR_XYZ",
        )
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(IntegrationConfigError, match="Secret not found"):
                c.resolve_secret()

    def test_resolve_none_ref(self):
        c = IntegrationSystemConfig(
            system_key="test",
            system_type="ins",
            display_name="Test",
            base_url="http://test",
            auth_type="bearer",
            secret_ref=None,
        )
        assert c.resolve_secret() is None

    def test_resolve_tenant_ref_not_implemented(self):
        c = IntegrationSystemConfig(
            system_key="test",
            system_type="ins",
            display_name="Test",
            base_url="http://test",
            auth_type="bearer",
            secret_ref="tenant://secrets/my_key",
        )
        with pytest.raises(IntegrationConfigError, match="not yet implemented"):
            c.resolve_secret()

    def test_resolve_literal_value(self):
        c = IntegrationSystemConfig(
            system_key="test",
            system_type="ins",
            display_name="Test",
            base_url="http://test",
            auth_type="bearer",
            secret_ref="literal-api-key",
        )
        assert c.resolve_secret() == "literal-api-key"


# ---------------------------------------------------------------------------
# CapabilityRouteConfig
# ---------------------------------------------------------------------------


class TestCapabilityRouteConfig:
    def test_minimal(self):
        r = CapabilityRouteConfig(
            capability_key="monitoring.trend",
            primary_system_key="ins_prod",
        )
        assert r.capability_key == "monitoring.trend"
        assert r.primary_system_key == "ins_prod"
        assert r.enrich_system_keys == []
        assert r.fallback_system_keys == []
        assert r.enabled is True
        assert r.merge_policy == "primary_plus_enrich"
        assert r.partial_failure_policy == "return_partial"

    def test_full_form(self):
        r = CapabilityRouteConfig(
            capability_key="asset.overview",
            primary_system_key="ins_prod",
            enrich_system_keys=["sms_prod"],
            fallback_system_keys=["ins_backup"],
            merge_policy="primary_plus_enrich",
            partial_failure_policy="return_partial",
        )
        assert r.enrich_system_keys == ["sms_prod"]
        assert r.fallback_system_keys == ["ins_backup"]

    def test_enrich_fallback_overlap_rejected(self):
        with pytest.raises(ValidationError, match="cannot overlap"):
            CapabilityRouteConfig(
                capability_key="test.cap",
                primary_system_key="sys1",
                enrich_system_keys=["sys2"],
                fallback_system_keys=["sys2"],
            )

    def test_invalid_merge_policy(self):
        with pytest.raises(ValidationError):
            CapabilityRouteConfig(
                capability_key="test",
                primary_system_key="sys1",
                merge_policy="invalid_policy",
            )

    def test_invalid_partial_failure_policy(self):
        with pytest.raises(ValidationError):
            CapabilityRouteConfig(
                capability_key="test",
                primary_system_key="sys1",
                partial_failure_policy="invalid_policy",
            )

    def test_disabled_route(self):
        r = CapabilityRouteConfig(
            capability_key="test",
            primary_system_key="sys1",
            enabled=False,
        )
        assert r.enabled is False


# ---------------------------------------------------------------------------
# EntityLinkConfig
# ---------------------------------------------------------------------------


class TestEntityLinkConfig:
    def test_minimal(self):
        el = EntityLinkConfig(
            tenant_id="t1",
            entity_type="asset",
            canonical_id="asset:t1:pump-001",
        )
        assert el.tenant_id == "t1"
        assert el.entity_type == "asset"
        assert el.canonical_id == "asset:t1:pump-001"
        assert el.links == []
        assert el.confidence == 1.0
        assert el.status == "active"

    def test_with_links(self):
        el = EntityLinkConfig(
            tenant_id="t1",
            entity_type="asset",
            canonical_id="asset:t1:pump-001",
            links=[
                EntityLinkEntry(
                    system_key="ins_prod",
                    remote_id="INS-001",
                    remote_code="PUMP-001",
                    is_primary=True,
                ),
                EntityLinkEntry(
                    system_key="sms_prod",
                    remote_id="SMS-001",
                    confidence=0.92,
                ),
            ],
        )
        assert len(el.links) == 2
        assert el.links[0].is_primary is True
        assert el.links[1].confidence == 0.92

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            EntityLinkConfig(
                tenant_id="t1",
                entity_type="asset",
                canonical_id="c1",
                confidence=1.5,
            )
        with pytest.raises(ValidationError):
            EntityLinkConfig(
                tenant_id="t1",
                entity_type="asset",
                canonical_id="c1",
                confidence=-0.1,
            )

    def test_entity_link_entry_confidence_bounds(self):
        with pytest.raises(ValidationError):
            EntityLinkEntry(system_key="s1", remote_id="r1", confidence=2.0)

    def test_crm_entity_types(self):
        for et in ("customer", "contract"):
            el = EntityLinkConfig(
                tenant_id="t1", entity_type=et, canonical_id="c1"
            )
            assert el.entity_type == et

    def test_erp_entity_types(self):
        for et in ("work_order", "inventory_item", "spare_part"):
            el = EntityLinkConfig(
                tenant_id="t1", entity_type=et, canonical_id="c1"
            )
            assert el.entity_type == et

    def test_invalid_entity_type(self):
        with pytest.raises(ValidationError):
            EntityLinkConfig(
                tenant_id="t1", entity_type="invalid", canonical_id="c1"
            )


# ---------------------------------------------------------------------------
# IntegrationsConfig
# ---------------------------------------------------------------------------


class TestIntegrationsConfig:
    def test_minimal(self):
        c = IntegrationsConfig()
        assert c.enabled is True
        assert c.systems == {}
        assert c.routes == {}
        assert c.entity_links == []

    def test_disabled(self):
        c = IntegrationsConfig(enabled=False)
        assert c.enabled is False

    def test_simple_route_parsing(self):
        c = IntegrationsConfig(
            systems={
                "ins_prod": IntegrationSystemConfig(
                    system_key="ins_prod",
                    system_type="ins",
                    display_name="InS",
                    base_url="http://ins.test",
                    auth_type="bearer",
                ),
            },
            routes={
                "monitoring.trend": "ins_prod",
            },
        )
        route = c.routes["monitoring.trend"]
        assert isinstance(route, CapabilityRouteConfig)
        assert route.primary_system_key == "ins_prod"
        assert route.capability_key == "monitoring.trend"

    def test_full_route_parsing(self):
        c = IntegrationsConfig(
            systems={
                "ins_prod": IntegrationSystemConfig(
                    system_key="ins_prod",
                    system_type="ins",
                    display_name="InS",
                    base_url="http://ins.test",
                    auth_type="bearer",
                ),
                "sms_prod": IntegrationSystemConfig(
                    system_key="sms_prod",
                    system_type="sms",
                    display_name="Sms",
                    base_url="http://sms.test",
                    auth_type="api_key",
                ),
            },
            routes={
                "asset.overview": {
                    "primary_system_key": "ins_prod",
                    "enrich_system_keys": ["sms_prod"],
                    "merge_policy": "primary_plus_enrich",
                },
            },
        )
        route = c.routes["asset.overview"]
        assert route.primary_system_key == "ins_prod"
        assert route.enrich_system_keys == ["sms_prod"]

    def test_route_references_unknown_system_rejected(self):
        with pytest.raises(ValidationError, match="unknown system"):
            IntegrationsConfig(
                systems={},
                routes={
                    "test.cap": "nonexistent_system",
                },
            )

    def test_route_enrich_unknown_system_rejected(self):
        with pytest.raises(ValidationError, match="unknown system"):
            IntegrationsConfig(
                systems={
                    "ins_prod": IntegrationSystemConfig(
                        system_key="ins_prod",
                        system_type="ins",
                        display_name="InS",
                        base_url="http://ins.test",
                        auth_type="bearer",
                    ),
                },
                routes={
                    "test.cap": {
                        "primary_system_key": "ins_prod",
                        "enrich_system_keys": ["nonexistent"],
                    },
                },
            )

    def test_route_fallback_unknown_system_rejected(self):
        with pytest.raises(ValidationError, match="unknown system"):
            IntegrationsConfig(
                systems={
                    "ins_prod": IntegrationSystemConfig(
                        system_key="ins_prod",
                        system_type="ins",
                        display_name="InS",
                        base_url="http://ins.test",
                        auth_type="bearer",
                    ),
                },
                routes={
                    "test.cap": {
                        "primary_system_key": "ins_prod",
                        "fallback_system_keys": ["nonexistent"],
                    },
                },
            )
