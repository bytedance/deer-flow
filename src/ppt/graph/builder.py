# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.graph import END, START, StateGraph

from src.ppt.graph.ppt_composer_node import ppt_composer_node
from src.ppt.graph.ppt_generator_node import ppt_generator_node
from src.ppt.graph.state import PPTState


def build_graph():
    """Build and return the ppt workflow graph."""
    # build state graph
    builder = StateGraph(PPTState)
    builder.add_node("ppt_composer", ppt_composer_node)
    builder.add_node("ppt_generator", ppt_generator_node)
    builder.add_edge(START, "ppt_composer")
    builder.add_edge("ppt_composer", "ppt_generator")
    builder.add_edge("ppt_generator", END)
    return builder.compile()


workflow = build_graph()

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    report_content = open("examples/nanjing_tangbao.md").read()
    final_state = workflow.invoke({"input": report_content})
