# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Literal

# Define available LLM types
LLMType = Literal["basic", "reasoning", "vision", "gemini"]

# Define agent-LLM mapping
AGENT_LLM_MAP: dict[str, LLMType] = {
    "coordinator": "gemini",
    "planner": "gemini",
    "researcher": "gemini",
    "coder": "gemini",
    "reporter": "gemini",
    "podcast_script_writer": "bageminisic",
    "ppt_composer": "gemini",
    "prose_writer": "gemini",
    "prompt_enhancer": "gemini",
}
