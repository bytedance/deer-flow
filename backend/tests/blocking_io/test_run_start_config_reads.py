"""Regression anchors: starting a run must read the live config off the loop.

``start_run`` needs the hot-reloaded ``AppConfig`` for the run context, the
recursion limits, the model allowlist and the approval switch. Each inline
``get_app_config()`` stats and hashes ``config.yaml`` and
``extensions_config.json`` and reparses them after an edit, so the run start
builds its context, and with it one config snapshot, in a worker and reuses it.
Run inputs and scheduled dispatch, which start or feed runs, are covered too.

The runs go through the real host → ``start_run`` → worker path against real
config files, and assert values only the file on disk provides (the recursion
limit, the model allowlist), so an anchor cannot pass because the read was
skipped.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from blockbuster import BlockingError
from deerflow_extension_api.agent_runs import AgentRunError
from test_extension_agent_runs import host, runtime  # noqa: F401  (fixtures)

import app.gateway.services as services  # the runtime fixture imports it lazily; import before the gate
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.extensions_config import reset_extensions_config

pytestmark = pytest.mark.asyncio

_CONFIG_YAML = """sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
recursion_limit: 37
scheduler:
  recursion_limit: 23
models:
  - name: allowed
    use: langchain_openai:ChatOpenAI
    model: allowed
"""


def _write_configs(directory: Path) -> tuple[Path, Path]:
    config_path = directory / "config.yaml"
    extensions_path = directory / "extensions_config.json"
    config_path.write_text(_CONFIG_YAML, encoding="utf-8")
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return config_path, extensions_path


@pytest_asyncio.fixture
async def runs(runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    config_path, extensions_path = await asyncio.to_thread(_write_configs, tmp_path)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    # Replace the fixture's injected config with the files on disk, and load
    # them once off the loop: each run start then pays the per-call revalidation.
    reset_app_config()
    reset_extensions_config()
    await asyncio.to_thread(get_app_config)
    built: list[dict] = []
    build_run_config = services.build_run_config

    def recording_build_run_config(*args, **kwargs):
        built.append(build_run_config(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(services, "build_run_config", recording_build_run_config)
    agent_runs, _, _, entered, _ = runtime
    try:
        yield agent_runs, built, entered
    finally:
        reset_extensions_config()


async def _start(agent_runs, thread_id: str, **kwargs) -> None:
    thread = await agent_runs.create_thread(thread_id=thread_id)
    run = await agent_runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "hi"}]}, **kwargs)
    assert (await agent_runs.wait(thread_id=thread, run_id=run.run_id, timeout=5)).status == "success"


async def test_run_start_reads_the_config_off_the_loop(runs) -> None:
    agent_runs, built, _ = runs
    await _start(agent_runs, "config-read-plain")

    assert {config["recursion_limit"] for config in built} == {37}


async def test_run_start_with_a_model_reads_the_allowlist_off_the_loop(runs) -> None:
    agent_runs, built, _ = runs
    await _start(agent_runs, "config-read-model", context={"model_name": "allowed"})
    assert {config["recursion_limit"] for config in built} == {37}

    thread = await agent_runs.create_thread(thread_id="config-read-unknown-model")
    with pytest.raises(AgentRunError) as rejected:
        await agent_runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "hi"}]}, context={"model_name": "missing"})
    assert rejected.value.status_code == 400


async def test_resuming_a_paused_run_reads_the_config_off_the_loop(runs) -> None:
    agent_runs, built, _ = runs
    thread = await agent_runs.create_thread(thread_id="config-read-resume")
    first = await agent_runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "approve"}]})
    assert (await agent_runs.wait(thread_id=thread, run_id=first.run_id, timeout=5)).status == "waiting_for_input"

    resumed = await agent_runs.resume(thread_id=thread, resume="yes")
    assert (await agent_runs.wait(thread_id=thread, run_id=resumed.run_id, timeout=5)).status == "success"
    assert {config["recursion_limit"] for config in built} == {37}


async def test_run_input_submission_does_not_load_the_config_on_the_loop(runs) -> None:
    agent_runs, _, entered = runs
    thread = await agent_runs.create_thread(thread_id="config-read-input")
    run = await agent_runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "wait"}]})
    await asyncio.wait_for(entered.wait(), timeout=5)

    # Loading the config inline in the capability check surfaces as a 503.
    accepted = await agent_runs.send_input(thread_id=thread, run_id=run.run_id, text="more", mode="queue", request_id="one")
    assert accepted["status"] == "pending"
    assert accepted["target_run_id"] == run.run_id
    await agent_runs.cancel(thread_id=thread, run_id=run.run_id)


async def test_scheduled_dispatch_reads_the_recursion_limit_off_the_loop(runs, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    async def fake_start_run(body, thread_id, request, **_kwargs):
        captured.append(body.config)
        return SimpleNamespace(run_id="run-1", thread_id=thread_id)

    monkeypatch.setattr(services, "start_run", fake_start_run)
    await services.launch_scheduled_thread_run(
        thread_id="scheduled-thread",
        assistant_id="lead_agent",
        prompt="Run in background",
        app=SimpleNamespace(state=SimpleNamespace()),
        owner_user_id="user-1",
    )

    assert captured == [{"recursion_limit": 23}]


async def test_blocking_probe_inline_run_config_read_actually_trips_the_gate(runs) -> None:
    """Meta-check: loading the same config inline on the loop is caught by the gate."""
    with pytest.raises(BlockingError):
        get_app_config()
