"""Scripted graph, real Gateway/worker/SQL acceptance for self-stop crash recovery.

No model, channel, or external provider is called. A SQLite backup taken after
the real stop tool commits represents the disk state left by a hard crash;
the original worker is then released and cleaned up normally.
"""

import asyncio
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.gateway import services
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.persistence.scheduled_tasks.model import TERMINAL_RUN_STATUSES
from deerflow.runtime.user_context import DEFAULT_USER_ID
from deerflow.tools.scheduled_tasks import stop_scheduled_task


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as original, sqlite3.connect(destination) as snapshot:
        original.backup(snapshot)


def _config(database_dir: Path, skills_dir: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "database": {"backend": "sqlite", "sqlite_dir": str(database_dir)},
            "scheduler": {"enabled": True, "tool_enabled": True, "poll_interval_seconds": 300},
            "memory": {"enabled": False, "token_counting": "char"},
            "run_events": {"backend": "db"},
            "skills": {"path": str(skills_dir)},
        }
    )


@pytest.mark.no_auto_user
def test_fresh_gateway_boot_recovers_self_stop_once_after_running_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda *args, **kwargs: ExtensionsConfig())
    live_dir, recovery_dir = tmp_path / "live", tmp_path / "recovered"
    set_app_config(_config(live_dir, tmp_path / "skills"))
    # Import after the isolated configuration is installed. Both apps below use
    # create_app's actual middleware and lifespan, including startup recovery.
    from app.gateway.app import create_app

    apps = []
    stop_written = threading.Event()
    release = {}
    executions = []

    def graph_factory(config):
        async def request_stop(state):
            executions.append(config["configurable"]["thread_id"])
            return {"messages": [AIMessage(content="", tool_calls=[{"id": "own-stop", "name": "stop_scheduled_task", "args": {}, "type": "tool_call"}])]}

        async def wait_after_stop(state):
            receipt = next(message for message in reversed(state["messages"]) if isinstance(message, ToolMessage))
            result = json.loads(receipt.content)
            assert result.get("stop_requested") is True, result
            release["event"] = asyncio.Event()
            stop_written.set()
            await release["event"].wait()
            return {"messages": [AIMessage(content="Requested my schedule to stop.")], "title": "Stop recovery fixture"}

        graph = StateGraph(get_thread_state_schema("full"))
        graph.add_node("request_stop", request_stop)
        graph.add_node("tools", ToolNode([stop_scheduled_task]))
        graph.add_node("wait_after_stop", wait_after_stop)
        graph.add_edge(START, "request_stop")
        graph.add_edge("request_stop", "tools")
        graph.add_edge("tools", "wait_after_stop")
        graph.add_edge("wait_after_stop", END)
        return graph.compile(checkpointer=apps[-1].state.checkpointer)

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _assistant_id=None: graph_factory)
    task_id = "task-stop-crash"
    due = datetime.now(UTC) + timedelta(hours=1)
    old_record = None
    evidence = {}
    try:
        app = create_app()
        apps.append(app)
        with TestClient(app) as client:
            origin_response = client.post("/api/threads", json={})
            assert origin_response.status_code == 200, origin_response.text
            origin = origin_response.json()["thread_id"]

            async def admit_and_dispatch():
                await app.state.scheduled_task_repo.create(
                    task_id=task_id,
                    user_id=DEFAULT_USER_ID,
                    thread_id=None,
                    origin_thread_id=origin,
                    context_mode="fresh_thread_per_run",
                    assistant_id=None,
                    title="Stop recovery fixture",
                    prompt="The work is done; stop this schedule.",
                    schedule_type="interval",
                    schedule_spec={"every_seconds": 3600},
                    timezone="UTC",
                    next_run_at=due,
                )
                await app.state.scheduled_task_service.run_once(now=due)

            client.portal.call(admit_and_dispatch)
            try:
                assert stop_written.wait(timeout=10), "The real stop tool did not reach the durable receipt barrier"

                async def capture_running_snapshot():
                    parent = await app.state.scheduled_task_repo.get(task_id, user_id=DEFAULT_USER_ID)
                    history = await app.state.scheduled_task_run_repo.list_by_task(task_id)
                    assert len(history) == 1
                    occurrence = history[0]
                    durable = await app.state.run_store.get(occurrence["run_id"], user_id=DEFAULT_USER_ID)
                    assert durable["status"] == "running"
                    assert occurrence["status"] == "running"
                    assert occurrence["stop_requested_run_id"] == occurrence["run_id"]
                    assert parent["status"] == "enabled"
                    await asyncio.to_thread(_sqlite_backup, live_dir / "deerflow.db", recovery_dir / "deerflow.db")
                    record = await app.state.run_manager.get(occurrence["run_id"], user_id=DEFAULT_USER_ID)
                    return record, occurrence

                old_record, old_occurrence = client.portal.call(capture_running_snapshot)
                evidence["snapshot"] = {"run_status": "running", "occurrence_status": old_occurrence["status"], "stop_requested_run_id": old_occurrence["stop_requested_run_id"]}
            finally:

                async def release_original_worker():
                    if "event" in release:
                        release["event"].set()
                    if old_record is not None and old_record.task is not None:
                        await asyncio.wait_for(old_record.task, timeout=10)

                client.portal.call(release_original_worker)
        assert old_record is not None
        assert old_record.status.value == "success"

        set_app_config(_config(recovery_dir, tmp_path / "skills"))
        recovered_app = create_app()
        apps.append(recovered_app)
        with TestClient(recovered_app) as client:
            paused_response = client.get(f"/api/scheduled-tasks/{task_id}")
            assert paused_response.status_code == 200, paused_response.text
            paused = paused_response.json()
            assert paused["status"] == "paused"
            assert paused["last_error"] == f"stopped by the agent in run {old_record.run_id}"
            assert paused["run_count"] == 1

            async def check_recovered_history_and_late_callback():
                history = await recovered_app.state.scheduled_task_run_repo.list_by_task(task_id)
                assert len(history) == 1
                assert history[0]["status"] in TERMINAL_RUN_STATUSES
                await recovered_app.state.scheduled_task_service.run_once(now=due + timedelta(days=1))
                assert len(await recovered_app.state.scheduled_task_run_repo.list_by_task(task_id)) == 1
                await recovered_app.state.scheduled_task_service.handle_run_completion(old_record)
                # The GET response adds derived run state to the stored row.
                stored = {key: value for key, value in paused.items() if key not in {"automatic_runs_used", "active_run_status"}}
                assert await recovered_app.state.scheduled_task_repo.get(task_id, user_id=DEFAULT_USER_ID) == stored
                assert await recovered_app.state.scheduled_task_run_repo.list_by_task(task_id) == history
                return history[0]

            recovered_occurrence = client.portal.call(check_recovered_history_and_late_callback)
            assert len(executions) == 1, "Recovered paused work was dispatched again"
            resumed_response = client.post(f"/api/scheduled-tasks/{task_id}/resume")
            assert resumed_response.status_code == 200, resumed_response.text
            assert resumed_response.json()["status"] == "enabled"

            async def replay_old_completion_after_resume():
                await recovered_app.state.scheduled_task_service.handle_run_completion(old_record)
                current = await recovered_app.state.scheduled_task_repo.get(task_id, user_id=DEFAULT_USER_ID)
                assert current["status"] == "enabled"
                assert current["run_count"] == 1
                return current

            restored = client.portal.call(replay_old_completion_after_resume)
            evidence["recovery"] = {
                "task_status": paused["status"],
                "occurrence_status": recovered_occurrence["status"],
                "run_count": paused["run_count"],
                "dispatch_count": len(executions),
                "after_resume_and_old_callback": restored["status"],
            }
        print("Gateway stop recovery evidence: " + json.dumps(evidence, sort_keys=True))
    finally:
        reset_app_config()
