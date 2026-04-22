"""Execution preparation helpers for a single run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from deerflow.runtime.stream_bridge import StreamBridge


@dataclass
class RunBuildArtifacts:
    """Assembled agent runtime pieces for a single run."""

    agent: Any
    runnable_config: dict[str, Any]
    reference_store: Any | None = None


def build_run_artifacts(
    *,
    thread_id: str,
    run_id: str,
    checkpointer: Any | None,
    store: Any | None,
    agent_factory: Any,
    config: dict[str, Any],
    bridge: StreamBridge,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> RunBuildArtifacts:
    """Assemble all components needed for agent execution."""
    runtime = Runtime(context={"thread_id": thread_id}, store=store)
    if "context" in config and isinstance(config["context"], dict):
        config["context"].setdefault("thread_id", thread_id)
    config.setdefault("configurable", {})["__pregel_runtime"] = runtime

    config_callbacks = config.setdefault("callbacks", [])
    if callbacks:
        config_callbacks.extend(callbacks)

    runnable_config = RunnableConfig(**config)
    agent = agent_factory(config=runnable_config)

    if checkpointer is not None:
        agent.checkpointer = checkpointer
    if store is not None:
        agent.store = store

    if interrupt_before:
        agent.interrupt_before_nodes = interrupt_before
    if interrupt_after:
        agent.interrupt_after_nodes = interrupt_after

    return RunBuildArtifacts(
        agent=agent,
        runnable_config=dict(runnable_config),
        reference_store=store,
    )
