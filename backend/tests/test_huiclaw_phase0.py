"""HUIClaw Phase 0: ThreadState checkpoint roundtrip + config `huiclaw:` acceptance."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig


def test_huiclaw_fields_roundtrip_through_memory_checkpointer_async_path() -> None:
    """P0-1: non-None huiclaw_* survives LangGraph MemorySaver after async invoke (serde path)."""

    async def passthrough(_state: ThreadState) -> dict:
        return {}

    async def _run() -> None:
        graph = StateGraph(ThreadState)
        graph.add_node("n", passthrough)
        graph.add_edge(START, "n")
        graph.add_edge("n", END)
        app = graph.compile(checkpointer=MemorySaver())

        cfg = {"configurable": {"thread_id": "huiclaw-phase0-checkpoint-test"}}
        initial: dict = {
            "messages": [HumanMessage(content="ping")],
            "artifacts": [],
            "viewed_images": {},
            "huiclaw_persona": {"name": "test", "style": "formal"},
            "huiclaw_lifecycle_state": "active",
            "huiclaw_persona_version": "1.0.0",
        }
        await app.ainvoke(initial, cfg)
        st = await app.aget_state(cfg)
        assert st.values.get("huiclaw_persona") == {"name": "test", "style": "formal"}
        assert st.values.get("huiclaw_lifecycle_state") == "active"
        assert st.values.get("huiclaw_persona_version") == "1.0.0"

    asyncio.run(_run())


def test_app_config_accepts_huiclaw_top_level_key() -> None:
    """P0-2: AppConfig uses extra='allow'; huiclaw: is preserved for future HUIClaw modules."""
    cfg = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [],
            "tools": [],
            "tool_groups": [],
            "huiclaw": {"enabled": False},
        }
    )
    dumped = cfg.model_dump()
    assert dumped.get("huiclaw") == {"enabled": False}


def test_thread_state_sync_invoke_roundtrip() -> None:
    """Sync path also persists huiclaw fields (sanity check)."""

    def passthrough(_state: ThreadState) -> dict:
        return {}

    graph = StateGraph(ThreadState)
    graph.add_node("n", passthrough)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)
    app = graph.compile(checkpointer=MemorySaver())

    cfg = {"configurable": {"thread_id": "huiclaw-phase0-sync"}}
    initial: dict = {
        "messages": [HumanMessage(content="ping")],
        "artifacts": [],
        "viewed_images": {},
        "huiclaw_persona": {"name": "sync", "style": "brief"},
    }
    app.invoke(initial, cfg)
    st = app.get_state(cfg)
    assert st.values.get("huiclaw_persona") == {"name": "sync", "style": "brief"}
