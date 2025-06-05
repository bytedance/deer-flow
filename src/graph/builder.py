# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .types import State
from .nodes import (
    coordinator_node,
    planner_node,
    reporter_node,
    router_node,  
    researcher_node,
    coder_node,
    analyzer_node,
    reader_node,  
    thinker_node,  
)


def _build_base_graph():
    """Build the agent workflow graph with all nodes."""
    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")

    # Core workflow nodes
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("planner", planner_node)
    builder.add_node("router", router_node)  
    
    # Specialized agent nodes
    builder.add_node("analyzer", analyzer_node)
    builder.add_node("coder", coder_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("reader", reader_node) 
    builder.add_node("thinker", thinker_node)  
    
    # Final reporting
    builder.add_node("reporter", reporter_node)
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
