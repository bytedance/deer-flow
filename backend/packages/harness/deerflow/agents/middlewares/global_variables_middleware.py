"""Middleware for injecting global variables into the system prompt."""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.global_variables_config import get_global_variables_config
from deerflow.global_variables.prompt_injector import build_prompt_section, replace_template_variables

logger = logging.getLogger(__name__)


class GlobalVariablesMiddlewareState(AgentState):
    pass


class GlobalVariablesMiddleware(AgentMiddleware[GlobalVariablesMiddlewareState]):
    """Middleware that injects global variables into the system prompt at runtime."""

    state_schema = GlobalVariablesMiddlewareState

    @override
    def before_model(self, state: GlobalVariablesMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject global variables into the system prompt before model invocation.

        Two injection modes:
        1. Template replacement: Replace {{variable_name}} placeholders in system prompt
        2. Legacy block injection: Append <global_variables> block (if injection_enabled)
        """
        config = get_global_variables_config()
        if not config.enabled:
            return None

        thread_id = runtime.context.get("thread_id") if runtime.context else None

        messages = state.get("messages", [])
        if not messages:
            return None

        from langchain_core.messages import SystemMessage

        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        if not system_messages:
            return None

        original = system_messages[0].content
        if not isinstance(original, str):
            return None

        updated = original

        # Phase 2: Template replacement - replace {{variable_name}} in system prompt
        updated = replace_template_variables(updated, thread_id=thread_id)

        # Phase 1 (legacy): Append global variables block
        if config.injection_enabled:
            gv_section = build_prompt_section(thread_id=thread_id)
            if gv_section and "<global_variables>" not in updated:
                updated = updated + "\n\n" + gv_section

        if updated != original:
            system_messages[0].content = updated

        return None
