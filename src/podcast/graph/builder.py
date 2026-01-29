# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from langgraph.graph import END, START, StateGraph

from src.podcast.graph.audio_mixer_node import audio_mixer_node
from src.podcast.graph.script_writer_node import script_writer_node
from src.podcast.graph.state import PodcastState
from src.podcast.graph.tts_node import tts_node


def build_graph():
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
    return builder.compile()


workflow = build_graph()

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    report_content = open("examples/nanjing_tangbao.md").read()
    final_state = workflow.invoke({"input": report_content})
    for line in final_state["script"].lines:
        print("<M>" if line.speaker == "male" else "<F>", line.text)

    with open("final.mp3", "wb") as f:
        f.write(final_state["output"])
