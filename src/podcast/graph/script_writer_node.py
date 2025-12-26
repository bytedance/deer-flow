# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging

import openai
from langchain_core.messages import HumanMessage, SystemMessage

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type
from src.prompts.template import get_prompt_template
from src.utils.json_utils import repair_json_output

from ..types import Script
from .state import PodcastState

logger = logging.getLogger(__name__)


def script_writer_node(state: PodcastState):
    logger.info("Generating script for podcast...")
    base_model = get_llm_by_type(AGENT_LLM_MAP["podcast_script_writer"])

    messages = [
        SystemMessage(content=get_prompt_template("podcast/podcast_script_writer")),
        HumanMessage(content=state["input"]),
    ]

    try:
        # Try structured output with json_mode first
        model = base_model.with_structured_output(Script, method="json_mode")
        script = model.invoke(messages)
    except openai.BadRequestError as e:
        # Fall back for models that don't support json_object (e.g., Kimi K2)
        if "json_object" in str(e).lower():
            logger.warning(
                f"Model doesn't support json_mode, falling back to prompting: {e}"
            )
            response = base_model.invoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            script_dict = json.loads(repair_json_output(content))
            script = Script.model_validate(script_dict)
        else:
            raise

    print(script)
    return {"script": script, "audio_chunks": []}
