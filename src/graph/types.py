# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.graph import MessagesState

from src.prompts.planner_model import Plan
from src.rag import Resource


class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""
    # 如果不在此定义即使后面有定义也不会更新，不会报错但是不会有新加的变量
    # Runtime Variables
    locale: str = "zh-CN"
    observations: list[str] = []
    resources: list[Resource] = []
    plan_iterations: int = 0
    current_plan: Plan | str = None
    final_report: str = ""
    auto_accepted_plan: bool = False
    enable_background_investigation: bool = True
    background_investigation_results: str = None
    session_id: str = None
    session_dir: str = None

    current_step_index: int = -1
    file_info: str
    need_image: str = "true"