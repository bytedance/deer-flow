"""Industrial skills telemetry API endpoints.

Tracks usage metrics for industrial vs foundation skills,
onboarding completion rates, and skill tier distribution.
"""

from __future__ import annotations

import logging
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
    timestamp: float


class IndustrialSkillTelemetryBatch(BaseModel):
    events: list[IndustrialSkillTelemetryEvent] = Field(default_factory=list)


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

        # Daily tracking (for trend analysis)
        self.daily_invocations: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, event: IndustrialSkillTelemetryEvent) -> None:
        with self._lock:
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

            elif event.type == "onboarding_skip":
                self.onboarding_skip_count += 1

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

    def summary(self) -> dict:
        with self._lock:
            total_invocations = sum(self.invocations_by_tier.values())
            industrial_count = self.invocations_by_tier.get("core-industrial", 0)
            foundation_count = self.invocations_by_tier.get("foundation", 0)

            industrial_percentage = (
                (industrial_count / total_invocations * 100) if total_invocations > 0 else 0
            )

            total_onboarding = self.onboarding_complete_count + self.onboarding_skip_count
            onboarding_completion_rate = (
                (self.onboarding_complete_count / total_onboarding * 100) if total_onboarding > 0 else 0
            )

            return {
                "skill_invocations": {
                    "total": total_invocations,
                    "by_tier": dict(self.invocations_by_tier),
                    "industrial_percentage": round(industrial_percentage, 2),
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


# Singleton metrics instance
_metrics = IndustrialSkillsMetrics()


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@router.post("/telemetry/industrial-skills", status_code=204)
async def record_industrial_skills_telemetry(batch: IndustrialSkillTelemetryBatch):
    """Record industrial skills telemetry events."""
    for event in batch.events:
        _metrics.record(event)

    logger.debug(
        "Recorded %d industrial skills telemetry events",
        len(batch.events),
    )


@router.get("/telemetry/industrial-skills/summary")
async def get_industrial_skills_telemetry_summary():
    """Get aggregated industrial skills telemetry metrics.

    Returns usage statistics including:
    - Skill invocation counts by tier (industrial vs foundation)
    - Industrial skills usage percentage
    - Onboarding completion rate
    - Tier management actions (promotions/demotions)
    - Daily invocation trends (last 7 days)
    """
    return _metrics.summary()


@router.post("/telemetry/industrial-skills/reset", status_code=204)
async def reset_industrial_skills_telemetry():
    """Reset all industrial skills telemetry counters.

    Primarily for testing purposes.
    """
    global _metrics
    _metrics = IndustrialSkillsMetrics()
    logger.info("Industrial skills telemetry reset")
