"""Tests for industrial skills telemetry: new event types, adoption funnel, and time-to-value.

Covers tasks from the industrial-intelligence-primary-track change:
- industrial_workflow_completed event tracking
- industrial_template_used event tracking
- industrial_agent_created event tracking
- Adoption funnel computation (5 stages)
- Time-to-value computation (median, p25, p75)
- Summary response shape (no industrial_percentage or by_tier)
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import industrial_skills_telemetry as telemetry_mod
from app.gateway.routers.industrial_skills_telemetry import (
    IndustrialSkillTelemetryEvent,
    IndustrialSkillsMetrics,
    _metrics,
)


def _reset_metrics():
    """Reset the singleton metrics instance."""
    telemetry_mod._metrics = IndustrialSkillsMetrics()


# ===========================================================================
# New Event Types
# ===========================================================================


class TestNewEventTypes:
    def test_workflow_completed_event(self):
        metrics = IndustrialSkillsMetrics()
        metrics.record(
            IndustrialSkillTelemetryEvent(
                type="industrial_workflow_completed",
                workflow_type="diagnosis",
                duration_ms=5000.0,
                user_id="user-1",
                timestamp=time.time() * 1000,
            )
        )
        summary = metrics.summary()
        assert summary["adoption_depth"]["workflow_completions"] == 1

    def test_template_used_event(self):
        metrics = IndustrialSkillsMetrics()
        metrics.record(
            IndustrialSkillTelemetryEvent(
                type="industrial_template_used",
                template_id="tpl_001",
                user_id="user-1",
                timestamp=time.time() * 1000,
            )
        )
        summary = metrics.summary()
        assert summary["adoption_depth"]["template_usage_count"] == 1

    def test_agent_created_event(self):
        metrics = IndustrialSkillsMetrics()
        metrics.record(
            IndustrialSkillTelemetryEvent(
                type="industrial_agent_created",
                user_id="user-1",
                timestamp=time.time() * 1000,
            )
        )
        summary = metrics.summary()
        assert summary["adoption_depth"]["agent_creation_count"] == 1

    def test_multiple_workflow_completions(self):
        metrics = IndustrialSkillsMetrics()
        for i in range(5):
            metrics.record(
                IndustrialSkillTelemetryEvent(
                    type="industrial_workflow_completed",
                    workflow_type="diagnosis",
                    duration_ms=float(1000 + i * 500),
                    user_id=f"user-{i}",
                    timestamp=time.time() * 1000,
                )
            )
        summary = metrics.summary()
        assert summary["adoption_depth"]["workflow_completions"] == 5


# ===========================================================================
# Summary Response Shape
# ===========================================================================


class TestSummaryShape:
    def test_summary_has_adoption_depth(self):
        metrics = IndustrialSkillsMetrics()
        summary = metrics.summary()
        assert "adoption_depth" in summary
        assert "workflow_completions" in summary["adoption_depth"]
        assert "template_usage_count" in summary["adoption_depth"]
        assert "agent_creation_count" in summary["adoption_depth"]

    def test_summary_no_balance_metrics(self):
        """industrial_percentage and by_tier must not appear in summary."""
        metrics = IndustrialSkillsMetrics()
        # Record some invocations
        metrics.record(
            IndustrialSkillTelemetryEvent(
                type="skill_invocation",
                skill_name="vibration-fault-diagnosis",
                skill_tier="core-industrial",
                timestamp=time.time() * 1000,
            )
        )
        summary = metrics.summary()

        # Must not contain old balance-based fields
        assert "industrial_percentage" not in summary.get("skill_invocations", {})
        assert "by_tier" not in summary.get("skill_invocations", {})

    def test_summary_retains_top_skills(self):
        metrics = IndustrialSkillsMetrics()
        metrics.record(
            IndustrialSkillTelemetryEvent(
                type="skill_invocation",
                skill_name="vibration-fault-diagnosis",
                skill_tier="core-industrial",
                timestamp=time.time() * 1000,
            )
        )
        summary = metrics.summary()
        assert "top_skills" in summary["skill_invocations"]
        assert "vibration-fault-diagnosis" in summary["skill_invocations"]["top_skills"]


# ===========================================================================
# Adoption Funnel
# ===========================================================================


class TestAdoptionFunnel:
    def test_empty_funnel(self):
        metrics = IndustrialSkillsMetrics()
        funnel = metrics.adoption_funnel()
        assert funnel["total_users_at_top"] == 0
        for stage in funnel["stages"]:
            assert funnel["stages"][stage] == 0

    def test_funnel_stages(self):
        metrics = IndustrialSkillsMetrics()

        # 10 users start onboarding
        for i in range(10):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="onboarding_started", user_id=f"user-{i}", timestamp=time.time() * 1000
            ))

        # 8 complete onboarding
        for i in range(8):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="onboarding_complete", user_id=f"user-{i}", timestamp=time.time() * 1000
            ))

        # 6 run first workflow
        for i in range(6):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="first_workflow_run", user_id=f"user-{i}", timestamp=time.time() * 1000
            ))

        # 4 complete a workflow
        for i in range(4):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="industrial_workflow_completed",
                user_id=f"user-{i}",
                workflow_type="diagnosis",
                timestamp=time.time() * 1000,
            ))

        # 3 create a template or agent
        for i in range(3):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="industrial_agent_created", user_id=f"user-{i}", timestamp=time.time() * 1000
            ))

        funnel = metrics.adoption_funnel()
        assert funnel["stages"]["onboarding_started"] == 10
        assert funnel["stages"]["onboarding_completed"] == 8
        assert funnel["stages"]["first_workflow_run"] == 6
        assert funnel["stages"]["workflow_completed"] == 4
        assert funnel["stages"]["template_or_agent_created"] == 3

        # Conversion rates relative to first stage
        assert funnel["conversion_rates"]["onboarding_started"] == 100.0
        assert funnel["conversion_rates"]["onboarding_completed"] == 80.0
        assert funnel["conversion_rates"]["first_workflow_run"] == 60.0
        assert funnel["conversion_rates"]["workflow_completed"] == 40.0
        assert funnel["conversion_rates"]["template_or_agent_created"] == 30.0

    def test_funnel_deduplicates_users(self):
        """Same user at same stage counts once."""
        metrics = IndustrialSkillsMetrics()
        for _ in range(5):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="onboarding_started", user_id="user-1", timestamp=time.time() * 1000
            ))
        funnel = metrics.adoption_funnel()
        assert funnel["stages"]["onboarding_started"] == 1


# ===========================================================================
# Time-to-Value
# ===========================================================================


class TestTimeToValue:
    def test_empty_time_to_value(self):
        metrics = IndustrialSkillsMetrics()
        ttv = metrics.time_to_value()
        assert ttv["sample_count"] == 0
        assert ttv["median_ms"] is None

    def test_single_sample(self):
        metrics = IndustrialSkillsMetrics()
        metrics.record(IndustrialSkillTelemetryEvent(
            type="industrial_workflow_completed",
            user_id="user-1",
            duration_ms=5000.0,
            timestamp=time.time() * 1000,
        ))
        ttv = metrics.time_to_value()
        assert ttv["sample_count"] == 1
        assert ttv["median_ms"] == 5000.0

    def test_multiple_samples(self):
        metrics = IndustrialSkillsMetrics()
        durations = [1000, 2000, 3000, 4000, 5000]
        for i, d in enumerate(durations):
            metrics.record(IndustrialSkillTelemetryEvent(
                type="industrial_workflow_completed",
                user_id=f"user-{i}",
                duration_ms=float(d),
                timestamp=time.time() * 1000,
            ))
        ttv = metrics.time_to_value()
        assert ttv["sample_count"] == 5
        assert ttv["median_ms"] == 3000.0
        assert ttv["p25_ms"] == 2000.0
        assert ttv["p75_ms"] == 4000.0
        assert ttv["min_ms"] == 1000.0
        assert ttv["max_ms"] == 5000.0

    def test_workflow_without_duration_not_counted(self):
        """Workflows without duration_ms don't affect time-to-value."""
        metrics = IndustrialSkillsMetrics()
        metrics.record(IndustrialSkillTelemetryEvent(
            type="industrial_workflow_completed",
            user_id="user-1",
            duration_ms=None,
            timestamp=time.time() * 1000,
        ))
        metrics.record(IndustrialSkillTelemetryEvent(
            type="industrial_workflow_completed",
            user_id="user-2",
            duration_ms=3000.0,
            timestamp=time.time() * 1000,
        ))
        ttv = metrics.time_to_value()
        assert ttv["sample_count"] == 1
        assert ttv["median_ms"] == 3000.0


# ===========================================================================
# API Endpoints
# ===========================================================================


class TestTelemetryEndpoints:
    def setup_method(self):
        _reset_metrics()

    def test_post_telemetry_events(self):
        _reset_metrics()
        app = FastAPI()
        app.include_router(telemetry_mod.router)

        with TestClient(app) as client:
            resp = client.post(
                "/api/telemetry/industrial-skills",
                json={
                    "events": [
                        {
                            "type": "industrial_workflow_completed",
                            "workflow_type": "diagnosis",
                            "duration_ms": 5000,
                            "user_id": "user-1",
                            "timestamp": time.time() * 1000,
                        },
                        {
                            "type": "industrial_template_used",
                            "template_id": "tpl_001",
                            "user_id": "user-1",
                            "timestamp": time.time() * 1000,
                        },
                    ]
                },
            )
            assert resp.status_code == 204

        summary = telemetry_mod._metrics.summary()
        assert summary["adoption_depth"]["workflow_completions"] == 1
        assert summary["adoption_depth"]["template_usage_count"] == 1

    def test_adoption_funnel_endpoint(self):
        _reset_metrics()
        app = FastAPI()
        app.include_router(telemetry_mod.router)

        with TestClient(app) as client:
            resp = client.get("/api/telemetry/industrial-skills/adoption-funnel")
            assert resp.status_code == 200
            data = resp.json()
            assert "stages" in data
            assert "conversion_rates" in data

    def test_time_to_value_endpoint(self):
        _reset_metrics()
        app = FastAPI()
        app.include_router(telemetry_mod.router)

        with TestClient(app) as client:
            resp = client.get("/api/telemetry/industrial-skills/time-to-value")
            assert resp.status_code == 200
            data = resp.json()
            assert "sample_count" in data
            assert "median_ms" in data
