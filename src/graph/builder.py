# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from src.prompts.planner_model import StepType

from .types import State
from .nodes import (
    coordinator_node,
    planner_node,
    reporter_node,
    research_team_node,
    researcher_node,
    coder_node,
    human_feedback_node,
    background_investigation_node,
    process_images_node, # Added process_images_node
)


import logging # Add logging import
logger = logging.getLogger(__name__) # Add logger

def continue_to_running_research_team(state: State) -> str: # Return type changed for clarity
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        logger.warning("No current plan or steps found in research_team, directing to planner.")
        return "planner"

    if all(step.execution_res for step in current_plan.steps):
        logger.info("All research steps completed, proceeding to image processing.")
        return "process_images" # All steps done, go to image processing

    next_step_type = "planner" # Default if next step type is unclear
    for step in current_plan.steps:
        if not step.execution_res: # Find first unexecuted step
            if step.step_type == StepType.RESEARCH:
                next_step_type = "researcher"
            elif step.step_type == StepType.PROCESSING:
                next_step_type = "coder"
            else:
                logger.warning(f"Unknown or missing step_type for unexecuted step: {step.title}. Defaulting to planner.")
                next_step_type = "planner"
            break
    logger.info(f"Next step in research_team determined as: {next_step_type}")
    return next_step_type


def _build_base_graph():
    """Build and return the base state graph with all nodes and edges."""
    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("background_investigator", background_investigation_node)
    builder.add_node("planner", planner_node)
    builder.add_node("reporter", reporter_node)
    builder.add_node("research_team", research_team_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("coder", coder_node)
    builder.add_node("human_feedback", human_feedback_node)
    builder.add_node("process_images", process_images_node) # Added process_images node
    builder.add_edge("background_investigator", "planner")

    # Conditional edges from research_team
    # If research steps are not done, continue to researcher or coder
    # If research steps are done, go to process_images
    builder.add_conditional_edges(
        "research_team",
        continue_to_running_research_team, # This function will need adjustment
        {
            "planner": "process_images", # If planner is returned (meaning done or error), go to image processing
            "researcher": "researcher",
            "coder": "coder",
            # Add a specific "process_images" target if continue_to_running_research_team can return it
        },
    )
    builder.add_edge("process_images", "reporter") # New edge
    builder.add_edge("reporter", END)
    return builder


def build_graph_with_memory():
    """Build and return the agent workflow graph with memory."""
    # use persistent memory to save conversation history
    # TODO: be compatible with SQLite / PostgreSQL
    memory = MemorySaver()

    # build state graph
    builder = _build_base_graph()
    return builder.compile(checkpointer=memory)


def build_graph():
    """Build and return the agent workflow graph without memory."""
    # build state graph
    builder = _build_base_graph()
    return builder.compile()


graph = build_graph()
