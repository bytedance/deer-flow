"""Middleware for injecting custom_fields from config into agent state."""

import logging
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class CustomFieldsMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    custom_fields: NotRequired[dict[str, Any] | None]


class CustomFieldsMiddleware(AgentMiddleware[CustomFieldsMiddlewareState]):
    """Inject custom_fields from config.configurable into agent state.

    Reads custom_fields from config.configurable and writes them
    to state so tools can access them via runtime.state["custom_fields"].
    """

    state_schema = CustomFieldsMiddlewareState

    @override
    def before_agent(self, state: CustomFieldsMiddlewareState, runtime: Runtime) -> dict | None:
        config = get_config()
        custom_fields = config.get("configurable", {}).get("custom_fields")
        if custom_fields is None:
            return None
        return {"custom_fields": custom_fields}
