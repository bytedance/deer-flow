from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    enabled: bool = Field(default=False)
    multi_instance: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_runs: int = Field(default=3, ge=1, le=32)
    queue_timeout_seconds: int = Field(default=3600, ge=60, le=604800)
    min_once_delay_seconds: int = Field(default=60, ge=1, le=86400)
    recursion_limit: int = Field(
        default=1000,
        ge=1,
        description=(
            "LangGraph recursion_limit for scheduler-launched runs. Read at dispatch "
            "time (not captured into ScheduledTaskService). The default matches the "
            "web UI's interactive budget (1000) so scheduled and interactive runs "
            "behave identically out of the box. Values above "
            "AppConfig.max_recursion_limit are clamped."
        ),
    )
