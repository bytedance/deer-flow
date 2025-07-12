# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from langchain.schema import HumanMessage

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type
from src.prompts.template import apply_prompt_template
from src.prompt_enhancer.graph.state import PromptEnhancerState

logger = logging.getLogger(__name__)


def prompt_enhancer_node(state: PromptEnhancerState):
    """Node that enhances user prompts using AI analysis."""
    logger.info("Enhancing user prompt...")

    model = get_llm_by_type(AGENT_LLM_MAP["prompt_enhancer"])

    try:

        # Create messages with context if provided
        context_info = ""
        if state.get("context"):
            context_info = f"\n\nAdditional context: {state['context']}"

        original_prompt_message = HumanMessage(
            content=f"Please enhance this prompt:{context_info}\n\nOriginal prompt: {state['prompt']}"
        )

        messages = apply_prompt_template(
            "prompt_enhancer/prompt_enhancer",
            {
                "messages": [original_prompt_message],
                "report_style": state.get("report_style"),
            },
        )

        # Get the response from the model
        response = model.invoke(messages)

        # Clean up the response - remove any extra formatting or comments
        enhanced_prompt = response.content.strip()

        # Remove common prefixes that might be added by the model
        prefixes_to_remove = [
            "Enhanced Prompt:",
            "Enhanced prompt:",
            "Here's the enhanced prompt:",
            "Here is the enhanced prompt:",
            "**Enhanced Prompt**:",
            "**Enhanced prompt**:",
        ]

        for prefix in prefixes_to_remove:
            if enhanced_prompt.startswith(prefix):
                enhanced_prompt = enhanced_prompt[len(prefix) :].strip()
                break

        logger.info("Prompt enhancement completed successfully")
        logger.debug(f"Enhanced prompt: {enhanced_prompt}")
        return {"output": enhanced_prompt}
    except Exception as e:
        logger.error(f"Error in prompt enhancement: {str(e)}")
        return {"output": state["prompt"]}
