# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from src.graph.tools.tool_manager import ToolManager
from .types import State
from .nodes import (
    CoordinatorNode,
    PlannerNode,
    WriterNode,
    CoderNode,  
    InterpreterNode,
    SearcherNode,
    ReaderNode,
    ThinkerNode,
    SupervisorNode,  
    ReporterNode,  
    ReceiverNode
)

import logging

logger = logging.getLogger(__name__)

def _build_base_graph():
    
    # 全局工具管理器实例
    tool_manager = ToolManager()    
    nodes = {
        "coordinator": CoordinatorNode(tool_manager),
        "planner": PlannerNode(tool_manager),
        "writer": WriterNode(tool_manager),
        "coder": CoderNode(tool_manager),
        "interpreter": InterpreterNode(tool_manager),
        "searcher": SearcherNode(tool_manager),
        "reader": ReaderNode(tool_manager),
        # "thinker": ThinkerNode(tool_manager),
        "receiver": ReceiverNode(tool_manager),
        "supervisor": SupervisorNode(tool_manager),
        "reporter": ReporterNode(tool_manager),
    }
    logger.info(f"Initialized {len(nodes)} nodes")

    """Build the agent workflow graph with all nodes."""
    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")

    for node_name, node_instance in nodes.items():
        builder.add_node(node_name, node_instance.execute)
        tool_manager.register_tool(f"call_{node_name}_agent", node_instance.call_params)
        logger.debug(f"Added node: {node_name}")

    builder.add_edge("supervisor", END)
    # 输出统计信息
    stats = tool_manager.get_statistics()
    logger.info(f"Tool initialization complete. Stats: {stats}")

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


def build_graph_from_config(compile_args):
    builder = _build_base_graph()
    return builder.compile(**compile_args)
