# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Literal

# Define available LLM types
LLMType = Literal["basic", "reasoning", "vision"]

# Define agent-LLM mapping
AGENT_LLM_MAP: dict[str, LLMType] = {
    "coordinator": "basic",
    "planner": "basic", 
    "router": "basic",
    "analyzer": "basic",
    "coder": "basic",
    "researcher": "basic",
    "reader": "vision",
    "thinker": "reasoning",
    "reporter": "basic",
}