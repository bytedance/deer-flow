# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.prebuilt import create_react_agent

from src.prompts import apply_prompt_template
from src.llms.llm import get_llm_by_type
from src.config.agents import AGENT_LLM_MAP
from src.tools import google_image_tool, google_speech_tool

# Create agents using configured LLM types
def create_agent(agent_name: str, agent_type: str, tools: list, prompt_template: str):
    """Factory function to create agents with consistent configuration."""
    return create_react_agent(
        name=agent_name,
        model=get_llm_by_type(AGENT_LLM_MAP[agent_type]),
        tools=tools,
        prompt=lambda state: apply_prompt_template(prompt_template, state),
    )

image_agent = create_agent(
    agent_name="ImageAgent",
    agent_type="image",               
    tools=[google_image_tool],       
    prompt_template="image_agent",    
)

speech_agent = create_agent(
    agent_name="SpeechAgent",
    agent_type="speech",
    tools=[google_speech_tool],
    prompt_template="speech_agent",
)