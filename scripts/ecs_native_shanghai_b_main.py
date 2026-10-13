"""One owned two-ECS B infrastructure path using the accepted deterministic ToolNode entry.

No model/provider/Agent loop. The real authenticated API creates the thread before
this oneoff; SQL reads its authoritative owner/incarnation without creating tables.
The worker resident is the only Docker job executor. Notification loops are held by
the existing mcp_tasks.enabled=false fixture configuration on both native peers.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import ssl

import httpx
from types import SimpleNamespace
import uuid

from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.mcp_tasks.service import McpTaskService
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import get_paths
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskSubmitRequest
from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import reset_current_user, set_current_user
from ecs_executor.job_store import JobStore


async def main():
    request = json.load(sys.stdin)
    assert set(request) == {"owner", "thread_id"}
    owner = str(uuid.UUID(request["owner"]))
    thread = request["thread_id"]
    assert thread.startswith("native-b-820d7a3429d9-")
    assert (
        os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"]
        == "/run/fixture/b-extensions.json"
    )
    native = json.loads(Path(os.environ["DEER_FLOW_CONFIG_PATH"]).read_text())
    assert native["mcp_tasks"]["enabled"] is False
    engine = create_async_engine(os.environ["ECS_NATIVE_METADATA_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        row = await session.scalar(
            select(ThreadMetaRow).where(
                ThreadMetaRow.thread_id == thread, ThreadMetaRow.user_id == owner
            )
        )
        assert row is not None and row.incarnation
        incarnation = row.incarnation
    repository = McpTaskRepository(sessions)
    registry = McpTaskDriverRegistry()
    registry.register(
        "ordinary-tools",
        OrdinaryMcpTaskDriver(McpTaskToolCaller(ExtensionsConfig.from_file())),
    )
    service = McpTaskService(
        repository=repository,
        drivers=registry,
        poll_interval_seconds=1,
        lease_seconds=30,
        max_concurrent_polls=1,
    )
    ledger = JobStore(os.environ["ECS_EXECUTOR_DATABASE_URL"])
    script = "sleep 20; printf cloud-worker-file > /output/result.txt; printf cloud-worker-stdout"
    source = get_paths().sandbox_uploads_dir(thread, user_id=owner) / "program.sh"
    source.parent.mkdir(parents=True, exist_ok=True)
    assert not source.exists() and not source.is_symlink()
    source.write_text(script)
    submitted = []
    fixture_run = "fixture-run-" + uuid.uuid4().hex

    @tool
    async def execute(request_key: str) -> str:
        """Submit one real ordinary MCP B job through the native persistent task service."""
        value = await service.submit(
            driver_name="ordinary-tools",
            request=TaskSubmitRequest(
                user_id=owner,
                thread_id=thread,
                thread_incarnation=incarnation,
                run_id=fixture_run,
                tool_call_id=request_key,
                server_name="ecs",
                task_name="execution",
                arguments={
                    "request_key": request_key,
                    "profile": "small",
                    "argv": ["sh", "/inputs/program.sh"],
                    "input_refs": {
                        "program.sh": {
                            "path": "uploads/program.sh",
                            "sha256": hashlib.sha256(script.encode()).hexdigest(),
                        }
                    },
                },
                driver_data={
                    "submit_tool": "submit",
                    "status_tool": "status",
                    "cancel_tool": "cancel",
                },
            ),
        )
        submitted.append(value)
        return value["id"]

    graph = StateGraph(MessagesState, context_schema=dict)
    graph.add_node("tools", ToolNode([execute], handle_tool_errors=False))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    token = set_current_user(SimpleNamespace(id=owner))
    try:
        key = "cloud-b-" + uuid.uuid4().hex
        await graph.compile().ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "execute",
                                "args": {"request_key": key},
                                "id": key,
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            },
            context={
                "user_id": owner,
                "thread_id": thread,
                "thread_incarnation": incarnation,
                "run_id": fixture_run,
            },
        )
        row = submitted[-1]
        job = row["remote_task_id"]
        assert ledger.get(job)["state"] == "staged"
        print(
            json.dumps(
                {
                    "b_stage": "native_persisted",
                    "task_id": row["id"],
                    "job_id": job,
                    "thread_id": thread,
                    "incarnation": incarnation,
                    "models_called": False,
                }
            ),
            flush=True,
        )
        for _ in range(150):
            await service.run_once(now=datetime.now(UTC) + timedelta(seconds=2))
            tracked = await repository.get(
                row["id"],
                user_id=owner,
                thread_id=thread,
                thread_incarnation=incarnation,
            )
            assert tracked and tracked["status"] not in {"failed", "cancelled"}
            if tracked["status"] == "completed":
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError(
                "Owned B main did not complete within bound; work retained"
            )
        for _ in range(30):
            physical = ledger.get(job)
            if (
                physical.get("physical_stopped") is True
                and physical.get("cleanup_pending") is False
            ):
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError(
                "Owned B physical completion uncertain; reservation retained"
            )
        assert physical["attempt"] == 1 and physical["node_id"] == "native-820d7a3429d9"
        outputs = get_paths().sandbox_outputs_dir(thread, user_id=owner)
        assert any(
            p.is_file() and not p.is_symlink() and p.read_text() == "cloud-worker-file"
            for p in outputs.rglob("result.txt")
        )
        async with httpx.AsyncClient(
            verify=ssl.create_default_context(cafile="/run/operator/ca.crt"),
            trust_env=False,
            timeout=30,
        ) as client:
            response = await client.get(
                "https://192.168.0.190:2026/execution/artifacts/" + job,
                headers={"Authorization": "Bearer " + os.environ["ECS_OWNER_TOKEN"]},
            )
            assert response.status_code == 200
            artifact = response.json()
            assert (
                artifact["stdout"] == "cloud-worker-stdout"
                and artifact["exit_code"] == 0
            )
        print(
            json.dumps(
                {
                    "b_main": "PASS",
                    "task_id": row["id"],
                    "job_id": job,
                    "attempt": 1,
                    "node_id": physical["node_id"],
                    "native_status": tracked["status"],
                    "physical_stopped": True,
                    "control_file_read": True,
                    "models_called": False,
                    "scope": "infrastructure_only",
                }
            )
        )
    finally:
        reset_current_user(token)
        ledger.engine.dispose()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit(
            "Owned B main failed; work retained, private details withheld"
        ) from None
