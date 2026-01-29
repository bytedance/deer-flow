# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type
from src.prompts.template import get_prompt_template

from .state import PPTState

logger = logging.getLogger(__name__)


def ppt_composer_node(state: PPTState):
    logger.info("Generating ppt content...")
    model = get_llm_by_type(AGENT_LLM_MAP["ppt_composer"])
    ppt_content = model.invoke(
        [
            SystemMessage(content=get_prompt_template("ppt/ppt_composer", locale=state.get("locale", "en-US"))),
            HumanMessage(content=state["input"]),
        ],
    )
    logger.info(f"ppt_content: {ppt_content}")
    # save the ppt content in a temp file
    temp_ppt_file_path = os.path.join(os.getcwd(), f"ppt_content_{uuid.uuid4()}.md")
    with open(temp_ppt_file_path, "w") as f:
        f.write(ppt_content.content)
    return {"ppt_content": ppt_content, "ppt_file_path": temp_ppt_file_path}
