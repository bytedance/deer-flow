"""Industrial skills telemetry API endpoints.

Tracks adoption depth for industrial intelligence:
- Workflow completions (industrial_workflow_completed)
- Template usage (industrial_template_used)
- Agent creation (industrial_agent_created)
- Onboarding completion
- Skill invocations
- Adoption funnel (5 stages)
- Time-to-value metrics
"""

from __future__ import annotations

import logging
import statistics
import threading
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["industrial-skills-telemetry"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class IndustrialSkillTelemetryEvent(BaseModel):
    type: str
    skill_name: str | None = None
    skill_tier: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    from_tier: str | None = None
    to_tier: str | None = None
    count: int | None = None
    template_id: str | None = None
    workflow_type: str | None = None
    stage: str | None = None
    duration_ms: float | None = None
    timestamp: float


class IndustrialSkillTelemetryBatch(BaseModel):
    events: list[IndustrialSkillTelemetryEvent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Adoption Funnel Stages
# ---------------------------------------------------------------------------

FUNNEL_STAGES = [
    "onboarding_started",
    "onboarding_completed",
    "first_workflow_run",
    "workflow_completed",
    "template_or_agent_created",
]


# ---------------------------------------------------------------------------
# Metrics Aggregation
# ---------------------------------------------------------------------------


class IndustrialSkillsMetrics:
    """In-memory aggregation for industrial skills telemetry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Skill invocation counts by tier
        self.invocations_by_tier: dict[str, int] = defaultdict(int)
        self.invocations_by_skill: dict[str, int] = defaultdict(int)

        # Onboarding metrics
        self.onboarding_complete_count: int = 0
        self.onboarding_skip_count: int = 0

        # Tier change metrics (admin actions)
        self.tier_change_count: int = 0
        self.batch_tier_change_count: int = 0
        self.skills_promoted_to_industrial: int = 0
        self.skills_demoted_to_foundation: int = 0

        # Adoption depth metrics (replaces balance-based metrics)
        self.workflow_completions: int = 0
        self.template_usage_count: int = 0
        self.industrial_agents_created: int = 0

        # Adoption funnel: stage -> user_ids
        self._funnel_users: dict[str, set[str]] = defaultdict(set)

        # Time-to-value: list of durations in ms (onboarding start to first workflow complete)
        self._time_to_value_samples: list[float] = []

        # Daily tracking (for trend analysis)
        self.daily_invocations: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, event: IndustrialSkillTelemetryEvent) -> None:
        with self._lock:
            user_id = event.user_id or "anonymous"

            if event.type == "skill_invocation":
                if event.skill_tier:
                    self.invocations_by_tier[event.skill_tier] += 1
                if event.skill_name:
                    self.invocations_by_skill[event.skill_name] += 1

                # Track daily
                day = datetime.fromtimestamp(event.timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                tier_key = event.skill_tier or "unknown"
                self.daily_invocations[day][tier_key] += 1

            elif event.type == "onboarding_complete":
                self.onboarding_complete_count += 1
                self._funnel_users["onboarding_completed"].add(user_id)

            elif event.type == "onboarding_skip":
                self.onboarding_skip_count += 1

            elif event.type == "onboarding_started":
                self._funnel_users["onboarding_started"].add(user_id)

            elif event.type == "tier_change":
                self.tier_change_count += 1
                if event.to_tier == "core-industrial":
                    self.skills_promoted_to_industrial += 1
                elif event.to_tier == "foundation":
                    self.skills_demoted_to_foundation += 1

            elif event.type == "batch_tier_change":
                self.batch_tier_change_count += 1
                count = event.count or 0
                if event.to_tier == "core-industrial":
                    self.skills_promoted_to_industrial += count
                elif event.to_tier == "foundation":
                    self.skills_demoted_to_foundation += count

            elif event.type == "industrial_agent_created":
                self.industrial_agents_created += 1
                self._funnel_users["template_or_agent_created"].add(user_id)

            elif event.type == "industrial_workflow_completed":
                self.workflow_completions += 1
                self._funnel_users["workflow_completed"].add(user_id)
                if event.duration_ms is not None:
                    self._time_to_value_samples.append(event.duration_ms)

            elif event.type == "industrial_template_used":
                self.template_usage_count += 1
                self._funnel_users["template_or_agent_created"].add(user_id)

            elif event.type == "first_workflow_run":
                self._funnel_users["first_workflow_run"].add(user_id)

    def summary(self) -> dict:
        with self._lock:
            total_invocations = sum(self.invocations_by_tier.values())

            total_onboarding = self.onboarding_complete_count + self.onboarding_skip_count
            onboarding_completion_rate = (
                (self.onboarding_complete_count / total_onboarding * 100) if total_onboarding > 0 else 0
            )

            return {
                "skill_invocations": {
                    "total": total_invocations,
                    "top_skills": dict(
                        sorted(
                            self.invocations_by_skill.items(),
                            key=lambda x: x[1],
                            reverse=True,
                        )[:10]
                    ),
                },
                "onboarding": {
                    "complete_count": self.onboarding_complete_count,
                    "skip_count": self.onboarding_skip_count,
                    "completion_rate": round(onboarding_completion_rate, 2),
                },
                "adoption_depth": {
                    "workflow_completions": self.workflow_completions,
                    "template_usage_count": self.template_usage_count,
                    "agent_creation_count": self.industrial_agents_created,
                },
                "tier_management": {
                    "individual_changes": self.tier_change_count,
                    "batch_changes": self.batch_tier_change_count,
                    "promoted_to_industrial": self.skills_promoted_to_industrial,
                    "demoted_to_foundation": self.skills_demoted_to_foundation,
                },
                "daily_trend": dict(
                    sorted(self.daily_invocations.items(), reverse=True)[:7]
                ),
            }

    def adoption_funnel(self) -> dict:
        """Compute adoption funnel: count unique users at each stage."""
        with self._lock:
            funnel = {}
            for stage in FUNNEL_STAGES:
                funnel[stage] = len(self._funnel_users.get(stage, set()))

            # Compute conversion rates relative to first stage
            first_stage_count = funnel.get("onboarding_started", 0)
            conversion_rates = {}
            for stage in FUNNEL_STAGES:
                count = funnel[stage]
                rate = (count / first_stage_count * 100) if first_stage_count > 0 else 0
                conversion_rates[stage] = round(rate, 2)

            return {
                "stages": funnel,
                "conversion_rates": conversion_rates,
                "total_users_at_top": first_stage_count,
            }

    def time_to_value(self) -> dict:
        """Compute time-to-value statistics from duration samples."""
        with self._lock:
            samples = list(self._time_to_value_samples)
            if not samples:
                return {
                    "sample_count": 0,
                    "median_ms": None,
                    "p25_ms": None,
                    "p75_ms": None,
                    "min_ms": None,
                    "max_ms": None,
                }

            sorted_samples = sorted(samples)
            n = len(sorted_samples)

            median = statistics.median(sorted_samples)
            p25 = sorted_samples[max(0, n // 4)]
            p75 = sorted_samples[min(n - 1, (3 * n) // 4)]

            return {
                "sample_count": n,
                "median_ms": round(median, 2),
                "p25_ms": round(p25, 2),
                "p75_ms": round(p75, 2),
                "min_ms": round(sorted_samples[0], 2),
                "max_ms": round(sorted_samples[-1], 2),
            }


# Singleton metrics instance
_metrics = IndustrialSkillsMetrics()


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@router.post("/telemetry/industrial-skills", status_code=204)
async def record_industrial_skills_telemetry(batch: IndustrialSkillTelemetryBatch):
    """Record industrial skills telemetry events.

    Supported event types:
    - skill_invocation: Skill was invoked
    - onboarding_started: User started onboarding
    - onboarding_complete: User completed onboarding
    - onboarding_skip: User skipped onboarding
    - tier_change: Individual skill tier changed
    - batch_tier_change: Batch skill tier change
    - industrial_agent_created: Industrial agent was created
    - industrial_workflow_completed: Industrial workflow completed
    - industrial_template_used: Industrial template was used
    - first_workflow_run: User ran their first workflow
    """
    for event in batch.events:
        _metrics.record(event)

    logger.debug(
        "Recorded %d industrial skills telemetry events",
        len(batch.events),
    )


@router.get("/telemetry/industrial-skills/summary")
async def get_industrial_skills_telemetry_summary():
    """Get aggregated industrial skills telemetry metrics.

    Returns adoption depth metrics:
    - Workflow completions
    - Template usage count
    - Agent creation count
    - Onboarding completion rate
    - Tier management actions
    - Daily invocation trends
    """
    return _metrics.summary()


@router.get("/telemetry/industrial-skills/adoption-funnel")
async def get_adoption_funnel():
    """Get adoption funnel metrics.

    Returns the 5-stage adoption funnel with user counts and conversion rates:
    1. onboarding_started
    2. onboarding_completed
    3. first_workflow_run
    4. workflow_completed
    5. template_or_agent_created
    """
    return _metrics.adoption_funnel()


@router.get("/telemetry/industrial-skills/time-to-value")
async def get_time_to_value():
    """Get time-to-value statistics.

    Returns median, 25th percentile, and 75th percentile durations
    from onboarding start to first workflow completion.
    """
    return _metrics.time_to_value()


@router.post("/telemetry/industrial-skills/reset", status_code=204)
async def reset_industrial_skills_telemetry():
    """Reset all industrial skills telemetry counters.

    Primarily for testing purposes.
    """
    global _metrics
    _metrics = IndustrialSkillsMetrics()
    logger.info("Industrial skills telemetry reset")
