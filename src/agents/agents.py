# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import List, Optional

from langgraph.prebuilt import create_react_agent

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type
from src.prompts import apply_prompt_template
from src.agents.tool_interceptor import wrap_tools_with_interceptor

logger = logging.getLogger(__name__)


# Create agents using configured LLM types
def create_agent(
    agent_name: str,
    agent_type: str,
    tools: list,
    prompt_template: str,
    pre_model_hook: callable = None,
    interrupt_before_tools: Optional[List[str]] = None,
):
    """Factory function to create agents with consistent configuration.

    Args:
        agent_name: Name of the agent
        agent_type: Type of agent (researcher, coder, etc.)
        tools: List of tools available to the agent
        prompt_template: Name of the prompt template to use
        pre_model_hook: Optional hook to preprocess state before model invocation
        interrupt_before_tools: Optional list of tool names to interrupt before execution

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

    llm_type = AGENT_LLM_MAP.get(agent_type, "basic")
    logger.debug(f"Agent '{agent_name}' using LLM type: {llm_type}")
    
    logger.debug(f"Creating ReAct agent '{agent_name}'")
    agent = create_react_agent(
        name=agent_name,
        model=get_llm_by_type(llm_type),
        tools=processed_tools,
        prompt=lambda state: apply_prompt_template(
            prompt_template, state, locale=state.get("locale", "en-US")
        ),
        pre_model_hook=pre_model_hook,
    )
    logger.info(f"Agent '{agent_name}' created successfully")
    
    return agent
