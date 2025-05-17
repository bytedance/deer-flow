# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
from langgraph.graph import END, START, StateGraph

from src.config.storage import _create_checkpointer_from_config
from src.ppt.graph.ppt_composer_node import ppt_composer_node
from src.ppt.graph.ppt_generator_node import ppt_generator_node
from src.ppt.graph.state import PPTState


def _build_base_graph():
    """Build and return the ppt workflow graph."""
    # build state graph
    builder = StateGraph(PPTState)
    builder.add_node("ppt_composer", ppt_composer_node)
    builder.add_node("ppt_generator", ppt_generator_node)
    builder.add_edge(START, "ppt_composer")
    builder.add_edge("ppt_composer", "ppt_generator")
    builder.add_edge("ppt_generator", END)
    return builder


async def build_graph_with_memory():
    """Build and return the agent workflow graph with memory."""
    # Get appropriate storage from configuration file
    memory = await _create_checkpointer_from_config()

    # build state graph
    builder = _build_base_graph()
    return builder.compile(checkpointer=memory)


workflow = None

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    async def main():
        global workflow
        workflow = await build_graph_with_memory()

        config = {"configurable": {"thread_id": "test"}}

        report_content = open("examples/nanjing_tangbao.md").read()
        final_state = await workflow.ainvoke({"input": report_content}, config=config)
        return final_state

    final_state = asyncio.run(main())
