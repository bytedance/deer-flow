# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import inspect
import logging
from typing import Any, Callable, List, Optional

from langchain.agents import create_agent as langchain_create_agent
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from ..config.agents import AGENT_LLM_MAP
from ..llms.llm import get_llm_by_type
from ..prompts import apply_prompt_template
from .tool_interceptor import wrap_tools_with_interceptor

logger = logging.getLogger(__name__)


class DynamicPromptMiddleware(AgentMiddleware):
    """Middleware to apply dynamic prompt template before model invocation.
    
    This middleware prepends a system message with the rendered prompt template
    to the messages list before the model is called.
    """
    
    def __init__(self, prompt_template: str, locale: str = "en-US"):
        self.prompt_template = prompt_template
        self.locale = locale
    
    def before_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        """Apply prompt template and prepend system message to messages."""
        try:
            # Get the rendered messages including system prompt from template
            rendered_messages = apply_prompt_template(
                self.prompt_template, state, locale=self.locale
            )
            # The first message is the system prompt, extract it
            if rendered_messages and len(rendered_messages) > 0:
                system_message = rendered_messages[0]
                # Prepend system message to existing messages
                return {"messages": [system_message]}
            return None
        except Exception as e:
            logger.error(
                f"Failed to apply prompt template in before_model: {e}",
                exc_info=True
            )
            return None

    async def abefore_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        """Async version of before_model."""
        return self.before_model(state, runtime)


class PreModelHookMiddleware(AgentMiddleware):
    """Middleware to execute a pre-model hook before model invocation.
    
    This middleware wraps the legacy pre_model_hook callable and executes it
    as part of the middleware chain.
    """
    
    def __init__(self, pre_model_hook: Callable):
        self._pre_model_hook = pre_model_hook
    
    def before_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        """Execute the pre-model hook."""
        if not self._pre_model_hook:
            return None
        
        try:
            result = self._pre_model_hook(state, runtime)
            return result
        except Exception as e:
            logger.error(
                f"Pre-model hook execution failed in before_model: {e}",
                exc_info=True
            )
            return None

    async def abefore_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        """Async version of before_model."""
        if not self._pre_model_hook:
            return None
        
        try:
            # Check if the hook is async
            if inspect.iscoroutinefunction(self._pre_model_hook):
                result = await self._pre_model_hook(state, runtime)
            else:
                # Run synchronous hook in thread pool to avoid blocking event loop
                result = await asyncio.to_thread(self._pre_model_hook, state, runtime)
            return result
        except Exception as e:
            logger.error(
                f"Pre-model hook execution failed in abefore_model: {e}",
                exc_info=True
            )
            return None


# Create agents using configured LLM types
def create_agent(
    agent_name: str,
    agent_type: str,
    tools: list,
    prompt_template: str,
    pre_model_hook: callable = None,
    interrupt_before_tools: Optional[List[str]] = None,
    locale: str = "en-US",
):
    """Factory function to create agents with consistent configuration.

    Args:
        agent_name: Name of the agent
        agent_type: Type of agent (researcher, coder, etc.)
        tools: List of tools available to the agent
        prompt_template: Name of the prompt template to use
        pre_model_hook: Optional hook to preprocess state before model invocation
        interrupt_before_tools: Optional list of tool names to interrupt before execution
        locale: Language locale for prompt template selection (e.g., en-US, zh-CN)

    Returns:
        A configured agent graph
    """
    logger.debug(
        f"Creating agent '{agent_name}' of type '{agent_type}' "
        f"with {len(tools)} tools and template '{prompt_template}'"
    )
    
    # Wrap tools with interrupt logic if specified
    processed_tools = tools
    if interrupt_before_tools:
        logger.info(
            f"Creating agent '{agent_name}' with tool-specific interrupts: {interrupt_before_tools}"
        )
        logger.debug(f"Wrapping {len(tools)} tools for agent '{agent_name}'")
        processed_tools = wrap_tools_with_interceptor(tools, interrupt_before_tools)
        logger.debug(f"Agent '{agent_name}' tool wrapping completed")
    else:
        logger.debug(f"Agent '{agent_name}' has no interrupt-before-tools configured")

    if agent_type not in AGENT_LLM_MAP:
        logger.warning(
            f"Agent type '{agent_type}' not found in AGENT_LLM_MAP. "
            f"Falling back to default LLM type 'basic' for agent '{agent_name}'. "
            "This may indicate a configuration issue."
        )
    llm_type = AGENT_LLM_MAP.get(agent_type, "basic")
    logger.debug(f"Agent '{agent_name}' using LLM type: {llm_type}")
    
    logger.debug(f"Creating agent '{agent_name}' with locale: {locale}")
    
    # Build middleware list
    # Use closure to capture locale from the workflow state instead of relying on
    # agent state.get("locale"), which doesn't have the locale field
    # See: https://github.com/bytedance/deer-flow/issues/743
    middleware = [DynamicPromptMiddleware(prompt_template, locale)]
    
    # Add pre-model hook middleware if provided
    if pre_model_hook:
        middleware.append(PreModelHookMiddleware(pre_model_hook))
    
    agent = langchain_create_agent(
        name=agent_name,
        model=get_llm_by_type(llm_type),
        tools=processed_tools,
        middleware=middleware,
    )
    logger.info(f"Agent '{agent_name}' created successfully")
    
    return agent
