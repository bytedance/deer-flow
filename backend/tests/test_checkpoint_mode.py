import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.runtime.checkpoint_mode import (
    CHECKPOINT_MODE_METADATA_KEY,
    CheckpointModeMismatchError,
    aensure_checkpoint_mode_compatible,
    checkpoint_metadata_uses_delta,
    ensure_checkpoint_mode_compatible,
    inject_checkpoint_mode,
)


def test_process_mode_change_requires_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    from deerflow.runtime import checkpoint_mode

    monkeypatch.setattr(checkpoint_mode, "_frozen_checkpoint_channel_mode", None)
    assert checkpoint_mode.freeze_checkpoint_channel_mode("full") == "full"
    with pytest.raises(checkpoint_mode.CheckpointModeReconfigurationError, match="restart"):
        checkpoint_mode.freeze_checkpoint_channel_mode("delta")


def _config() -> dict:
    return {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}


def test_inject_delta_mode_sets_internal_key_and_metadata_marker() -> None:
    config = _config()
    inject_checkpoint_mode(config, "delta")
    assert config["configurable"]["__deerflow_checkpoint_channel_mode"] == "delta"
    assert config["metadata"][CHECKPOINT_MODE_METADATA_KEY] == "delta"


def test_inject_full_mode_does_not_claim_delta_metadata() -> None:
    config = _config()
    inject_checkpoint_mode(config, "full")
    assert config["configurable"]["__deerflow_checkpoint_channel_mode"] == "full"
    assert CHECKPOINT_MODE_METADATA_KEY not in config.get("metadata", {})


def test_sync_full_mode_rejects_delta_marker() -> None:
    saver = MagicMock()
    saver.get_tuple.return_value = SimpleNamespace(
        metadata={CHECKPOINT_MODE_METADATA_KEY: "delta"},
        checkpoint={"channel_values": {}},
    )
    with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
        ensure_checkpoint_mode_compatible(saver, _config(), "full")
    saver.put.assert_not_called()


@pytest.mark.anyio
async def test_async_full_mode_rejects_langgraph_delta_counters() -> None:
    saver = AsyncMock()
    saver.aget_tuple.return_value = SimpleNamespace(
        metadata={"counters_since_delta_snapshot": {"messages": (1, 1)}},
        checkpoint={"channel_values": {}},
    )
    with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
        await aensure_checkpoint_mode_compatible(saver, _config(), "full")
    saver.aput.assert_not_awaited()


@pytest.mark.anyio
async def test_delta_mode_accepts_plain_full_checkpoint() -> None:
    saver = AsyncMock()
    saver.aget_tuple.return_value = SimpleNamespace(
        metadata={},
        checkpoint={"channel_values": {"messages": ["legacy"]}},
    )
    await aensure_checkpoint_mode_compatible(saver, _config(), "delta")


@pytest.mark.anyio
async def test_full_mode_accessor_rejects_real_delta_checkpoint_on_sqlite(tmp_path) -> None:
    """Fail-closed gate against a real saver, not mocks.

    Seeds a delta checkpoint (marker + LangGraph delta counters) into a real
    AsyncSqliteSaver, reopens the thread with a full-mode accessor, and
    asserts every accessor surface raises before state is read or written.
    This is the integration boundary the corruption-prevention design relies
    on; the mock-based tests above cannot catch a wiring regression between
    the accessor, the marker, and a real backend.
    """
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Overwrite

    from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph

    config = _config()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "gate.db")) as saver:
        await saver.setup()
        delta_accessor = CheckpointStateAccessor.bind(build_state_mutation_graph("seed", "delta"), saver, mode="delta")
        await delta_accessor.aupdate(
            config,
            {"messages": Overwrite([HumanMessage(content="hi", id="h1")])},
            as_node="seed",
        )

        # Sanity: the seeded head really is a delta checkpoint.
        seeded = await saver.aget_tuple(config)
        assert checkpoint_metadata_uses_delta(seeded.metadata)

        full_accessor = CheckpointStateAccessor.bind(build_state_mutation_graph("read", "full"), saver, mode="full")
        with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
            await full_accessor.aget(config)
        with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
            await full_accessor.aupdate(config, {"title": "x"}, as_node="read")
        with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
            await full_accessor.ahistory(config)


def test_yaml_mode_change_is_rejected_when_graph_is_reconstructed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deerflow.agents.lead_agent import agent as lead_agent
    from deerflow.config.app_config import reset_app_config
    from deerflow.runtime import checkpoint_mode

    config_path = tmp_path / "config.yaml"

    def write_config(mode: str) -> None:
        config_path.write_text(
            "\n".join(
                (
                    "sandbox:",
                    "  use: deerflow.sandbox.local.provider:LocalSandboxProvider",
                    "database:",
                    f"  checkpoint_channel_mode: {mode}",
                )
            )
            + "\n",
            encoding="utf-8",
        )

    write_config("full")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(checkpoint_mode, "_frozen_checkpoint_channel_mode", None)
    monkeypatch.setattr(lead_agent, "_make_lead_agent", lambda config, *, app_config: object())
    reset_app_config()
    try:
        lead_agent.make_lead_agent({"configurable": {}})

        write_config("delta")
        future_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (future_mtime, future_mtime))

        with pytest.raises(checkpoint_mode.CheckpointModeReconfigurationError, match="restart"):
            lead_agent.make_lead_agent({"configurable": {}})
    finally:
        reset_app_config()


@pytest.mark.asyncio
async def test_gateway_runtime_rejects_mode_different_from_frozen_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from app.gateway.deps import langgraph_runtime
    from deerflow.runtime import checkpoint_mode

    @asynccontextmanager
    async def resource(_config):
        yield object()

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        checkpoint_mode,
        "_frozen_checkpoint_channel_mode",
        "full",
    )
    monkeypatch.setattr(
        "deerflow.runtime.checkpointer.async_provider.make_checkpointer",
        resource,
    )
    monkeypatch.setattr("deerflow.runtime.make_stream_bridge", resource)
    monkeypatch.setattr("deerflow.runtime.make_store", resource)
    monkeypatch.setattr(
        "deerflow.persistence.engine.init_engine_from_config",
        noop,
    )
    monkeypatch.setattr("deerflow.persistence.engine.close_engine", noop)
    monkeypatch.setattr(
        "deerflow.persistence.engine.get_session_factory",
        lambda: None,
    )
    monkeypatch.setattr(
        "deerflow.runtime.events.store.make_run_event_store",
        lambda _config: object(),
    )
    monkeypatch.setattr(
        "deerflow.persistence.thread_meta.make_thread_store",
        lambda _session_factory, _store: object(),
    )
    startup_config = SimpleNamespace(
        database=SimpleNamespace(
            backend="memory",
            checkpoint_channel_mode="delta",
        ),
        run_events=None,
    )

    with pytest.raises(
        checkpoint_mode.CheckpointModeReconfigurationError,
        match="restart",
    ):
        async with langgraph_runtime(FastAPI(), startup_config):
            pass


def test_direct_langgraph_request_cannot_select_delta_in_full_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deerflow.agents.lead_agent import agent as lead_agent
    from deerflow.config.app_config import AppConfig
    from deerflow.runtime import checkpoint_mode
    from deerflow.runtime.checkpoint_mode import INTERNAL_CHECKPOINT_MODE_KEY

    app_config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local.provider:LocalSandboxProvider"},
            "database": {"checkpoint_channel_mode": "full"},
        }
    )
    config = {
        "configurable": {
            INTERNAL_CHECKPOINT_MODE_KEY: "delta",
        }
    }
    monkeypatch.setattr(checkpoint_mode, "_frozen_checkpoint_channel_mode", None)
    monkeypatch.setattr(lead_agent, "get_app_config", lambda: app_config)
    monkeypatch.setattr(
        lead_agent,
        "_make_lead_agent",
        lambda config, *, app_config: object(),
    )

    lead_agent.make_lead_agent(config)

    assert checkpoint_mode._frozen_checkpoint_channel_mode == "full"
    assert config["configurable"][INTERNAL_CHECKPOINT_MODE_KEY] == "full"
    assert CHECKPOINT_MODE_METADATA_KEY not in config["metadata"]


def test_gateway_runtime_app_config_can_supply_its_frozen_internal_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deerflow.agents.lead_agent import agent as lead_agent
    from deerflow.config.app_config import AppConfig
    from deerflow.runtime import checkpoint_mode
    from deerflow.runtime.checkpoint_mode import INTERNAL_CHECKPOINT_MODE_KEY

    reloaded_app_config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local.provider:LocalSandboxProvider"},
            "database": {"checkpoint_channel_mode": "delta"},
        }
    )
    config = {
        "configurable": {
            INTERNAL_CHECKPOINT_MODE_KEY: "full",
        },
        "context": {"app_config": reloaded_app_config},
    }
    monkeypatch.setattr(
        checkpoint_mode,
        "_frozen_checkpoint_channel_mode",
        "full",
    )
    monkeypatch.setattr(
        lead_agent,
        "_make_lead_agent",
        lambda config, *, app_config: object(),
    )

    lead_agent.make_lead_agent(config)

    assert config["configurable"][INTERNAL_CHECKPOINT_MODE_KEY] == "full"
    assert CHECKPOINT_MODE_METADATA_KEY not in config["metadata"]
