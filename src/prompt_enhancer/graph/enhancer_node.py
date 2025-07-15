# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import re

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

        # Extract content from response
        response_content = response.content.strip()
        logger.debug(f"Response content: {response_content}")

        # Try to extract content from XML tags first
        xml_match = re.search(
            r"<enhanced_prompt>(.*?)</enhanced_prompt>", response_content, re.DOTALL
        )

        if xml_match:
            # Extract content from XML tags and clean it up
            enhanced_prompt = xml_match.group(1).strip()
            logger.debug("Successfully extracted enhanced prompt from XML tags")
        else:
            # Fallback to original logic if no XML tags found
            enhanced_prompt = response_content
            logger.warning("No XML tags found in response, using fallback parsing")

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
