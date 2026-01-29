# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from ...config.agents import AGENT_LLM_MAP
from ...llms.llm import get_llm_by_type
from ...prompts.template import get_prompt_template
from ...prose.graph.state import ProseState

logger = logging.getLogger(__name__)


def prose_fix_node(state: ProseState):
    logger.info("Generating prose fix content...")
    model = get_llm_by_type(AGENT_LLM_MAP["prose_writer"])
    prose_content = model.invoke(
        [
            SystemMessage(content=get_prompt_template("prose/prose_fix")),
            HumanMessage(content=f"The existing text is: {state['content']}"),
        ],
    )
    logger.info(f"prose_content: {prose_content}")
    return {"output": prose_content.content}
