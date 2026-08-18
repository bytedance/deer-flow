from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    enabled: bool = Field(default=False)
    multi_instance: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_runs: int = Field(default=3, ge=1, le=32)
    min_once_delay_seconds: int = Field(default=60, ge=1, le=86400)
    recursion_limit: int = Field(
        default=100,
        ge=1,
        description=(
            "LangGraph recursion_limit for scheduler-launched runs. Read at dispatch "
            "time (not captured into ScheduledTaskService). Clamped by "
            "AppConfig.max_recursion_limit. The web UI sends 1000 for interactive "
            "chat; raise this to match for long scheduled jobs."
        ),
    )
