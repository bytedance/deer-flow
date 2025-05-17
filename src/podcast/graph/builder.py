# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
from langgraph.graph import END, START, StateGraph

from src.config.storage import _create_checkpointer_from_config
from src.podcast.graph.audio_mixer_node import audio_mixer_node
from src.podcast.graph.script_writer_node import script_writer_node
from src.podcast.graph.state import PodcastState
from src.podcast.graph.tts_node import tts_node


def _build_base_graph():
    """Build and return the podcast workflow graph."""
    # build state graph
    builder = StateGraph(PodcastState)
    builder.add_node("script_writer", script_writer_node)
    builder.add_node("tts", tts_node)
    builder.add_node("audio_mixer", audio_mixer_node)
    builder.add_edge(START, "script_writer")
    builder.add_edge("script_writer", "tts")
    builder.add_edge("tts", "audio_mixer")
    builder.add_edge("audio_mixer", END)
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

        for line in final_state["script"].lines:
            print("<M>" if line.speaker == "male" else "<F>", line.paragraph)

        with open("final.mp3", "wb") as f:
            f.write(final_state["output"])

        return final_state

    asyncio.run(main())
