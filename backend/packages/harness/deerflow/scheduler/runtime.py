"""Host-bound scheduler authority for one lead-agent run.

The Gateway supplies this capability after authenticating the owner and binding
the originating conversation or current occurrence. Neither persisted messages
nor tool arguments can supply that authority.
"""

from typing import Any, Final, Literal, Protocol

SCHEDULER_CAPABILITY_CONTEXT_KEY: Final[str] = "__scheduler_capability"
SchedulerCapabilityMode = Literal["interactive", "scheduled"]


class SchedulerRunCapability(Protocol):
    @property
    def mode(self) -> SchedulerCapabilityMode: ...

    async def manage(self, *, action: str, request: dict[str, Any]) -> dict[str, Any]: ...

    async def stop_current_schedule(self) -> dict[str, Any]: ...


def scheduler_tools_enabled(app_config: Any) -> bool:
    """Require both operator switches, including for already assembled tools."""
    scheduler = getattr(app_config, "scheduler", None)
    return bool(getattr(scheduler, "enabled", False) and getattr(scheduler, "tool_enabled", False))


def is_scheduler_capability(capability: Any) -> bool:
    """Distinguish a host operation object from serialized display data."""
    return getattr(capability, "mode", None) in ("interactive", "scheduled") and callable(getattr(capability, "manage", None)) and callable(getattr(capability, "stop_current_schedule", None))
