"""Opening the isolated saver must leave the Gateway loop responsive."""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest


@pytest.mark.asyncio
async def test_checkpoint_peer_lifetime_does_not_block_gateway_loop(monkeypatch, tmp_path):
    import deerflow.agents.thread_state  # noqa: F401
    import deerflow.subagents as package
    from deerflow.config.app_config import AppConfig
    from deerflow.runtime.checkpointer.async_provider import make_checkpointer
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime

    monkeypatch.delitem(sys.modules, "deerflow.subagents.executor", raising=False)
    monkeypatch.delattr(package, "executor", raising=False)
    executor = importlib.import_module("deerflow.subagents.executor")
    config = AppConfig.model_validate(
        {
            "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)},
            "subagent_runtime": {"checkpoint_enabled": True},
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        }
    )
    try:
        async with make_checkpointer(config) as saver:
            async with subagent_checkpoint_runtime(config, saver) as runtime:
                assert runtime.loop is not asyncio.get_running_loop()
                assert runtime.saver is not saver
                await saver.setup()
            assert runtime.closed
    finally:
        await asyncio.to_thread(executor._shutdown_isolated_subagent_loop)
        if getattr(package, "executor", None) is executor:
            delattr(package, "executor")
