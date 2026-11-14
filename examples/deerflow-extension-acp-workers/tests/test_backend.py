"""Adapter registration and captured-config outcome mapping."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deerflow_extension_acp_workers import install
from deerflow_extension_acp_workers.backend import ACPWorkerBackend
from deerflow.acp.transport import ACPOutcome
from deerflow.config.acp_config import ACPAgentConfig
from deerflow.subagents.worker_backends import (
    WorkerExecution,
    WorkerPlan,
    freeze_config,
)


def test_install_reports_unsupported_hosts():
    class Registry:
        def worker_backend(self, name, provider):
            return False

    with pytest.raises(RuntimeError, match="does not support"):
        install(Registry(), {})


def test_bind_captures_only_referenced_agent():
    backend = ACPWorkerBackend()
    app = SimpleNamespace(
        acp_agents={"coder": ACPAgentConfig(command="acp", description="Coder")}
    )
    bound = freeze_config(backend.bind("worker", {"agent": "coder"}, app))
    app.acp_agents["coder"].command = "changed"
    assert bound["launch"]["command"] == "acp"
    with pytest.raises(ValueError):
        backend.bind("worker", {"agent": "coder", "command": "other"}, app)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,text,status,cap",
    [
        ("end_turn", "Error: valid text", "completed", None),
        ("end_turn", "", "completed", None),
        ("refusal", "declined", "failed", None),
        ("cancelled", "", "cancelled", None),
        ("max_tokens", "partial", "completed", "backend_capped"),
        ("max_turn_requests", "", "failed", "backend_capped"),
    ],
)
async def test_outcomes_keep_external_usage_separate(
    monkeypatch, reason, text, status, cap
):
    calls = []

    async def transport(agent, config, prompt, **kwargs):
        calls.append((agent, config.command, kwargs["mcp_servers"]))
        return ACPOutcome(text=text, stop_reason=reason, usage={"total_tokens": 42})

    monkeypatch.setattr("deerflow_extension_acp_workers.backend.invoke_acp", transport)
    plan = WorkerPlan(
        "worker",
        "acp",
        "Test",
        30,
        freeze_config(
            {
                "agent": "coder",
                "launch": ACPAgentConfig(
                    command="captured", description="Test"
                ).model_dump(),
            }
        ),
    )
    outcome = await ACPWorkerBackend().execute(
        plan,
        WorkerExecution("execution", "work", "/workspace/execution", lambda text: None),
    )
    assert outcome.status == status and outcome.stop_reason == cap
    assert outcome.external_usage == {"total_tokens": 42}
    assert outcome.token_usage_records is None and outcome.tool_receipts is None
    assert calls == [("coder", "captured", [])]
