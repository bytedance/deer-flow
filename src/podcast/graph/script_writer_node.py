# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type
from src.prompts.template import get_prompt_template

from ..types import Script
from .state import PodcastState

logger = logging.getLogger(__name__)


def script_writer_node(state: PodcastState):
    logger.info("Generating script for podcast...")
    model = get_llm_by_type(
        AGENT_LLM_MAP["podcast_script_writer"]
    ).with_structured_output(Script, method="json_mode")
    script = model.invoke(
        [
            SystemMessage(content=get_prompt_template("podcast/podcast_script_writer")),
            HumanMessage(content=state["input"]),
        ],
    )
    print(script)
    return {"script": script, "audio_chunks": []}
