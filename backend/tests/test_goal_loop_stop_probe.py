"""The standalone reproduction also exercises the real runtime in CI."""

import socket

import pytest

from scripts.benchmark.goal_loop_stop import run_case


@pytest.mark.asyncio
async def test_goal_stands_down_after_the_native_loop_guard_hard_stop(monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("This controlled regression must not use the network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    result = await run_case()
    assert result["run_error"] is None
    assert result["run_stop_reason"] == "loop_capped"
    assert result["lead_model_calls"] == result["guard_hard_limit"] == 5
    assert result["tool_executions"] == 4
    assert result["goal_evaluator_calls"] == 1
    assert result["goal_status"] == "active"
    assert result["goal_continuations"] == 0
    assert result["stand_down_reason"] == "loop_capped"
    assert result["provider_requests"] == 0
