# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from langchain.schema import HumanMessage, SystemMessage

from src.config.agents import AgentConfiguration
from src.llms.llm import get_llm_by_type
from src.prose.graph.state import ProseState
from src.prompts.template import get_prompt_template

logger = logging.getLogger(__name__)


def prose_improve_node(state: ProseState):
    logger.info("Generating prose improve content...")
    model = get_llm_by_type(AgentConfiguration.AGENT_LLM_MAP["prose_writer"])
    prose_content = model.invoke(
        [
            SystemMessage(content=get_prompt_template("prose/prose_improver")),
            HumanMessage(content=f"The existing text is: {state['content']}"),
        ],
    )
    logger.info(f"prose_content: {prose_content}")
    return {"output": prose_content.content}
