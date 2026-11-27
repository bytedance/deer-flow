"""Scripted graph, real Gateway/worker/SQL acceptance for self-stop crash recovery.

No model, channel, or external provider is called. A SQLite backup taken after
the real stop tool commits represents the disk state left by a hard crash;
the original worker is then released and cleaned up normally.
"""

import asyncio
import importlib.util
import json
import sqlite3
import sys
import threading
import time
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
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


def _tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name, "type": "tool_call"}])


class _ScheduledReportModel(FakeMessagesListChatModel):
    schemas: dict = {}
    system_prompts: list[str] = []

    def bind_tools(self, tools, **kwargs):
        self.schemas.update({tool.name: convert_to_openai_tool(tool)["function"]["parameters"] for tool in tools})
        return self

    def _generate(self, messages, *args, **kwargs):
        self.system_prompts.extend(str(message.content) for message in messages if message.type == "system")
        if not self.responses:
            if any("There is no human available" in prompt and "smallest reasonable assumption" in prompt for prompt in self.system_prompts):
                self.responses = [
                    _tool_call("write_file", path="/mnt/user-data/outputs/monthly.csv", content="month,total\n2026-11,42\n"),
                    AIMessage(content="Report saved. Assumption: use the reporting month from the schedule."),
                ]
            else:
                self.responses = [AIMessage(content="Which month should I use?")]
        return super()._generate(messages, *args, **kwargs)


def _await_result(read, condition):
    for _ in range(300):
        result = read()
        if condition(result):
            return result
        time.sleep(0.1)
    pytest.fail(f"Run did not reach the expected state: {result!r}")


@pytest.fixture
def report_executor(monkeypatch):
    from deerflow import subagents
    from deerflow.subagents import batch_service

    task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

    # conftest loads a stub to break lightweight unit-test imports. Use the
    # production executor and reconnect its existing import sites here.
    name = "deerflow.subagents.executor"
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(subagents, "executor", module, raising=False)
    for target in (subagents, batch_service, task_tool_module):
        for attr in (
            "SubagentExecutor",
            "SubagentStatus",
            "cleanup_background_task",
            "force_cleanup_background_task",
            "get_background_task_result",
            "request_cancel_background_task",
            "run_on_isolated_subagent_loop",
        ):
            if hasattr(target, attr):
                monkeypatch.setattr(target, attr, getattr(module, attr))
    try:
        yield module
    finally:
        module._shutdown_isolated_subagent_loop()


@pytest.mark.no_auto_user
@pytest.mark.parametrize(
    ("trigger", "delegation", "arguments"),
    [
        ("automatic", None, {}),
        ("manual", None, {}),
        ("automatic", "task", {}),
        ("manual", "task", {}),
        ("automatic", "batch_task", {}),
        ("manual", "batch_task", {"continuation": None, "legacy_extra": True}),
        ("manual", "batch_task", {"continuation": ""}),
        ("manual", "batch_task", {"continuation": "Publish the report"}),
        ("interactive", "batch_task", {"continuation": "Publish the report"}),
        ("interactive", "ask_clarification", {}),
    ],
)
def test_gateway_scheduled_subagent_contract(tmp_path, monkeypatch, trigger, delegation, arguments, report_executor):
    from app.gateway import deps
    from app.gateway.app import create_app
    from deerflow.agents.lead_agent import agent as lead_agent
    from deerflow.config import paths
    from deerflow.sandbox.local.local_sandbox import LocalSandbox

    execute_command = LocalSandbox.execute_command

    def execute_without_remote_probe(self, command, *args, **kwargs):
        # A local file check must work without GNU filesystem utilities.
        if (kwargs.get("env") or {}).get("_DEERFLOW_SIZE_PROBE"):
            raise OSError("Remote file probe is unavailable on this local host")
        return execute_command(self, command, *args, **kwargs)

    monkeypatch.setattr(LocalSandbox, "execute_command", execute_without_remote_probe)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "0")
    monkeypatch.setenv("AUTH_JWT_SECRET", "local-scheduled-report-test-secret")
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda *args, **kwargs: ExtensionsConfig())
    monkeypatch.setattr(paths, "_paths", None)
    monkeypatch.setattr(deps, "_cached_local_provider", None)
    monkeypatch.setattr(deps, "_cached_repo", None)
    config = AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline", "api_key": "unused"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "tools": [{"name": "write_file", "group": "file:write", "use": "deerflow.sandbox.tools:write_file_tool"}],
            "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path / "db")},
            "scheduler": {"enabled": True, "poll_interval_seconds": 300, "min_once_delay_seconds": 1},
            "subagent_batches": {"enabled": True, "poll_interval_seconds": 0.1},
            "memory": {"enabled": False},
            "title": {"enabled": False},
            "summarization": {"enabled": False},
            "skills": {"path": str(tmp_path / "skills")},
            "subagents": {"custom_agents": {"reporter": {"description": "Monthly reports", "system_prompt": "Generate the monthly report.", "disallowed_tools": [], "skills": []}}},
        }
    )
    criterion = "file:/mnt/user-data/outputs/monthly.csv non-empty"
    prompt = "Generate a CSV report. No month was supplied; the schedule normally reports November 2026."
    if delegation == "task":
        call = _tool_call("task", description="Monthly report", prompt=prompt, subagent_type="reporter", acceptance_criteria=[criterion])
    elif delegation == "batch_task":
        call = _tool_call("batch_task", title="Monthly report", items=[{"key": "report", "prompt": prompt, "acceptance_criteria": [criterion]}], subagent_type="reporter", **arguments)
    elif delegation == "ask_clarification":
        call = _tool_call("ask_clarification", question="Which month?", clarification_type="missing_info")
    else:
        call = AIMessage(content="Run completed without delegation.")
    lead = _ScheduledReportModel(responses=[call, AIMessage(content="Lead turn complete."), AIMessage(content="Follow-up published.")])
    child = _ScheduledReportModel(responses=[AIMessage(content="Finished interactive work.")] if trigger == "interactive" else [])
    child_builds = []

    def child_model(**kwargs):
        child_builds.append(child)
        return child

    monkeypatch.setattr(lead_agent, "create_chat_model", lambda *args, **kwargs: lead)
    monkeypatch.setattr(report_executor, "create_chat_model", child_model)
    set_app_config(config)
    try:
        app = create_app()
        with ExitStack() as clients:
            client = clients.enter_context(TestClient(app))
            recover_batch = trigger == "automatic" and delegation == "batch_task"
            if recover_batch:
                client.portal.call(app.state.subagent_batch_service.stop)

            def request(method, url, **kwargs):
                response = client.request(method, url, **kwargs)
                assert response.is_success, response.text
                return response.json()

            request("POST", "/api/v1/auth/register", json={"email": "reporter@example.com", "password": "local-report-fixture-strong-372!"})
            client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
            if trigger == "interactive":
                thread_id = request("POST", "/api/threads", json={})["thread_id"]
                thread_url = f"/api/threads/{thread_id}"
                request("POST", f"{thread_url}/runs/wait", json={"assistant_id": "lead_agent", "input": {"messages": [{"role": "user", "content": prompt}]}, "context": {"subagent_enabled": True}})
            else:
                due = datetime.now(UTC) + timedelta(minutes=2)
                task_id = request(
                    "POST", "/api/scheduled-tasks", json={"title": "Monthly report", "prompt": prompt, "schedule_type": "once", "schedule_spec": {"run_at": due.isoformat()}, "timezone": "UTC", "subagent_enabled": delegation is not None}
                )["id"]
                task_url = f"/api/scheduled-tasks/{task_id}"
                assert request("GET", task_url)["subagent_enabled"] is (delegation is not None)
                if trigger == "manual":
                    request("POST", f"{task_url}/trigger")
                else:

                    async def tick():
                        await app.state.scheduled_task_service.run_once(now=due + timedelta(seconds=1))

                    client.portal.call(tick)
                history = _await_result(lambda: request("GET", f"{task_url}/runs"), lambda rows: rows and rows[0]["status"] in TERMINAL_RUN_STATUSES)
                assert history[0]["status"] == "success", history
                thread_url = f"/api/threads/{history[0]['thread_id']}"
            if delegation is None:
                assert not {"task", "batch_task", "ask_clarification"} & lead.schemas.keys()
                assert not child_builds
                return
            assert delegation in lead.schemas
            messages = request("GET", f"{thread_url}/state")["values"]["messages"]
            receipt = next(message for message in messages if message.get("tool_call_id") == delegation)
            if delegation == "ask_clarification":
                assert receipt["artifact"]["human_input"]["question"] == "Which month?"
                return
            if delegation == "batch_task":
                assert ("continuation" in lead.schemas["batch_task"]["properties"]) is (trigger == "interactive")
                batch_url = f"{thread_url}/subagent-batches"
                batches = request("GET", batch_url)
                if trigger != "interactive" and arguments.get("continuation") is not None:
                    expected = "must contain 1 to 4000 characters" if not arguments["continuation"] else "requires its originating Agent run authority"
                    assert expected in receipt["content"]
                    assert batches == []
                    return
                assert len(batches) == 1, receipt
                batch_url = f"{batch_url}/{batches[0]['id']}"
                if recover_batch:
                    assert request("GET", f"{batch_url}/items")[0]["status"] in {"queued", "pending"}
                    assert not child_builds
                    clients.close()
                    monkeypatch.setattr(deps, "_cached_local_provider", None)
                    monkeypatch.setattr(deps, "_cached_repo", None)
                    client = clients.enter_context(TestClient(create_app()))
                    request("POST", "/api/v1/auth/login/local", data={"username": "reporter@example.com", "password": "local-report-fixture-strong-372!"})
                    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
                items = _await_result(lambda: request("GET", f"{batch_url}/items"), lambda rows: rows and rows[0]["status"] in {"succeeded", "failed", "cancelled"})
                assert items[0]["status"] == "succeeded", items
                if trigger == "interactive":
                    batch = _await_result(lambda: request("GET", batch_url), lambda row: row["continuation_status"] not in {"pending", "dispatching"})
                    assert batch["continuation_status"] == "dispatched", batch
                    follow_up_url = f"{thread_url}/runs/{batch['continuation_run_id']}"
                    follow_up = _await_result(lambda: request("GET", follow_up_url), lambda run: run["status"] not in {"pending", "running"})
                    assert follow_up["status"] == "success", follow_up
                    assert len(request("GET", f"{thread_url}/subagent-batches")) == 1
                    assert "ask_clarification" in child.schemas
                    return
                verdict = items[0]["acceptance_verdict"]
            else:
                assert receipt["additional_kwargs"]["subagent_status"] == "completed", receipt
                verdict = receipt["additional_kwargs"]["subagent_acceptance_verdict"]
            assert "ask_clarification" not in child.schemas
            assert any("There is no human available" in message for message in child.system_prompts)
            assert verdict["all_hold"], verdict
            assert [path.read_text(encoding="utf-8") for path in (tmp_path / "home").rglob("monthly.csv")] == ["month,total\n2026-11,42\n"]
    finally:
        reset_app_config()
