"""Unit tests for canonical models immutability, provenance, queries (Task 1.2.8)."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from deerflow.integrations.models.asset import Asset, AssetContext, MeasurementPoint
from deerflow.integrations.models.provenance import PartialFailure, Provenance
from deerflow.integrations.models.queries import (
    AlarmHistoryQuery,
    AssetCatalogQuery,
    AssetContextQuery,
    AssetOverviewQuery,
    HealthAssessmentQuery,
    TrendQuery,
    WaveformQuery,
)


class TestModelImmutability:
    def test_asset_frozen(self):
        a = Asset(asset_id="A1", asset_code="AC1", asset_name="Pump", asset_type="pump", status="active")
        with pytest.raises(FrozenInstanceError):
            a.asset_id = "A2"

    def test_asset_context_frozen(self):
        a = Asset(asset_id="A1", asset_code="AC1", asset_name="P", asset_type="t", status="s")
        ctx = AssetContext(asset=a)
        with pytest.raises(FrozenInstanceError):
            ctx.asset = a

    def test_measurement_point_frozen(self):
        mp = MeasurementPoint(
            point_id="MP1", point_code="V1", point_name="Vib", point_type="vibration"
        )
        with pytest.raises(FrozenInstanceError):
            mp.point_id = "MP2"

    def test_provenance_frozen(self):
        p = Provenance(
            source_system_key="ins",
            source_system_type="ins",
            capability_key="test.cap",
            fetched_at=datetime.now(),
        )
        with pytest.raises(FrozenInstanceError):
            p.source_system_key = "sms"


class TestProvenance:
    def test_defaults(self):
        p = Provenance(
            source_system_key="ins",
            source_system_type="ins",
            capability_key="test.cap",
            fetched_at=datetime.now(),
        )
        assert p.query_params == {}
        assert p.transform_steps == ()
        assert p.source_metadata == {}

    def test_with_transform(self):
        p = Provenance(
            source_system_key="ins",
            source_system_type="ins",
            capability_key="test.cap",
            fetched_at=datetime.now(),
        )
        p2 = p.with_transform("flatten_response")
        assert p2.transform_steps == ("flatten_response",)
        assert p.transform_steps == ()  # original unchanged

    def test_with_transform_chaining(self):
        p = Provenance(
            source_system_key="ins",
            source_system_type="ins",
            capability_key="test.cap",
            fetched_at=datetime.now(),
        )
        p2 = p.with_transform("step1").with_transform("step2")
        assert p2.transform_steps == ("step1", "step2")


class TestPartialFailure:
    def test_creation(self):
        pf = PartialFailure(
            system_key="sms_prod",
            capability_key="health.assessment",
            error_type="IntegrationTimeoutError",
            error_message="Timeout after 15s",
            timestamp=datetime.now(),
        )
        assert pf.system_key == "sms_prod"
        assert pf.error_type == "IntegrationTimeoutError"

    def test_frozen(self):
        pf = PartialFailure(
            system_key="s",
            capability_key="c",
            error_type="e",
            error_message="m",
            timestamp=datetime.now(),
        )
        with pytest.raises(FrozenInstanceError):
            pf.system_key = "other"


class TestQueryDefaults:
    def test_asset_catalog_query(self):
        q = AssetCatalogQuery(tenant_id="t1")
        assert q.tenant_id == "t1"
        assert q.asset_types == ()
        assert q.status is None
        assert q.search_text == ""
        assert q.limit == 100
        assert q.offset == 0

    def test_asset_context_query(self):
        q = AssetContextQuery(tenant_id="t1", asset_id="A1")
        assert q.asset_id == "A1"
        assert q.include_children is True
        assert q.include_measurement_points is True

    def test_asset_overview_query(self):
        q = AssetOverviewQuery(tenant_id="t1", asset_id="A1")
        assert q.include_health_assessment is True
        assert q.include_recent_alarms is True

    def test_trend_query(self):
        from datetime import timedelta
        now = datetime.now()
        q = TrendQuery(tenant_id="t1", asset_id="A1", measurement_point_id="MP1",
                       start_time=now - timedelta(days=7), end_time=now)
        assert q.start_time is not None
        assert q.end_time is not None

    def test_waveform_query(self):
        q = WaveformQuery(tenant_id="t1", asset_id="A1", measurement_point_id="MP1")
        assert q.tenant_id == "t1"

    def test_alarm_history_query(self):
        q = AlarmHistoryQuery(tenant_id="t1", asset_id="A1")
        assert q.limit == 100

    def test_health_assessment_query(self):
        q = HealthAssessmentQuery(tenant_id="t1", asset_id="A1")
        assert q.tenant_id == "t1"
