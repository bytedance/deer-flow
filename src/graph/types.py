# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


from dataclasses import field

from langgraph.graph import MessagesState

from src.prompts.planner_model import Plan
from src.rag import Resource


class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""

    # Runtime Variables
    locale: str = "en-US"
    research_topic: str = ""
    clarified_research_topic: str = (
        ""  # Complete/final clarified topic with all clarification rounds
    )
    observations: list[str] = []
    resources: list[Resource] = []
    plan_iterations: int = 0
    current_plan: Plan | str = None
    final_report: str = ""
    auto_accepted_plan: bool = False
    enable_background_investigation: bool = True
    background_investigation_results: str = None

    # Clarification state tracking (disabled by default)
    enable_clarification: bool = (
        False  # Enable/disable clarification feature (default: False)
    )
    clarification_rounds: int = 0
    clarification_history: list[str] = field(default_factory=list)
    is_clarification_complete: bool = False
    max_clarification_rounds: int = (
        3  # Default: 3 rounds (only used when enable_clarification=True)
    )

    # Report editing state (for issue #663 - report modification feature)
    previous_report: str = ""  # Store last generated report for editing
    is_editing_report: bool = False  # Flag indicating we're in report edit mode
    report_edit_context: str = ""  # Extracted user feedback about modifications
    report_sections_to_edit: list[str] = field(default_factory=list)  # List of sections to modify

    # Workflow control
    goto: str = "planner"  # Default next node
