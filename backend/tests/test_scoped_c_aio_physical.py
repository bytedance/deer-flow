"""PROPOSAL ONLY: one real AIO C lifecycle, SQL/ASGI control, no model API."""

import asyncio
import json
import os
import shlex
import subprocess
from contextvars import Context
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case

pytestmark = pytest.mark.skipif(os.environ.get("ECS_C_AIO_PHYSICAL_TEST") != "1", reason="explicit test-owned physical opt-in required")


@pytest.mark.parametrize("executor_engine", ["sqlite"], indirect=True)
def test_scoped_c_aio_capture_stops_exact_container(native_engine, executor_engine, monkeypatch, tmp_path):  # noqa: F811
    import httpx
    from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost, install_native_dispatch
    from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import SCHEMA_REVISION, upgrade_schema
    from fastapi import FastAPI
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from app.gateway import services
    from app.gateway.native_admission import make_native_snapshot
    from app.gateway.run_models import RunCreateRequest
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config.app_config import AppConfig
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    upgrade_schema(executor_engine)
    ledger = JobStore(executor_engine.url.render_as_string(hide_password=False))

    async def scenario(case):
        from deerflow.community.aio_sandbox import aio_sandbox_provider as aio_module
        from deerflow.sandbox import sandbox_provider

        prefix = os.environ["TEST_AIO_PREFIX"]
        image = os.environ["TEST_AIO_IMAGE_ID"]
        evidence = Path(os.environ["TEST_AIO_EVIDENCE"])
        observation = {}
        configuration = AppConfig(
            models=[],
            sandbox=SandboxConfig(
                use="deerflow.community.aio_sandbox:AioSandboxProvider",
                image=image,
                replicas=1,
                hard_capacity=True,
                container_prefix=prefix,
                ownership={"type": "memory"},
                idle_timeout=0,
                bash_command_timeout=30,
            ),
        )
        monkeypatch.setattr(aio_module, "get_app_config", lambda: configuration)
        # Provisioning and physical backend are real. Only configuration wiring
        # is injected, as in test_aio_sandbox_provider. No lifecycle mock here.
        provider = aio_module.AioSandboxProvider()
        monkeypatch.setattr(sandbox_provider, "get_initialized_sandbox_provider", lambda: provider)
        original_labels = provider._backend._sandbox_labels
        monkeypatch.setattr(provider._backend, "_sandbox_labels", lambda sandbox_id: {**original_labels(sandbox_id), "org.deerflow.tenant.owned": prefix})

        def inspect_exact(container_id):
            result = subprocess.run(["docker", "inspect", container_id], capture_output=True, text=True, timeout=10)
            if result.returncode:
                assert "no such object" in result.stderr.lower() or "no such container" in result.stderr.lower(), "Docker inspection unknown"
                return None
            value = json.loads(result.stdout)[0]
            assert value["Id"] == container_id
            return value

        def save_evidence():
            evidence.write_text(json.dumps(observation, sort_keys=True, indent=2))

        def acquire_use_release():
            # to_thread inherits the actual SQL-adopted task's private capture.
            sandbox_id = provider.acquire("pool-native-private", user_id="owner")
            sandbox = provider.get_scoped(sandbox_id, user_id="owner", thread_id="pool-native-private")
            handle = provider.capture_physical(sandbox_id, user_id="owner", thread_id="pool-native-private")
            # Persist acquired identity before any resource/shell assertion.
            observation.update(container_id=handle.container_id, container_name=handle.container_name, sandbox_id=sandbox_id, image_id=image, prefix=prefix, normal_stop_confirmed=False)
            save_evidence()
            physical = inspect_exact(handle.container_id)
            assert physical is not None and physical["State"]["Running"]
            assert physical["Image"] == image
            assert physical["Name"] == "/" + prefix + "-" + sandbox_id
            assert physical["Config"]["Labels"]["org.deerflow.tenant.owned"] == prefix
            assert physical["Config"]["Labels"]["deerflow.role"] == "sandbox"
            assert physical["Config"]["Labels"]["deerflow.sandbox_id"] == sandbox_id
            assert physical["HostConfig"]["NanoCpus"] == 1_000_000_000
            assert physical["HostConfig"]["Memory"] == 1024**3
            bindings = physical["NetworkSettings"]["Ports"]["8080/tcp"]
            assert bindings and all(item["HostIp"] == "127.0.0.1" for item in bindings)
            observation.update(container_id=handle.container_id, container_name=handle.container_name, sandbox_id=sandbox_id, image_id=image, running_before_stop=True, normal_stop_confirmed=False)
            save_evidence()  # Record exact ownership before executing a command.
            marker = "aio-c-" + prefix
            output = sandbox.execute_command("printf '%s' " + shlex.quote(marker) + " > /tmp/scoped-c-marker; cat /tmp/scoped-c-marker", env={})
            assert marker in output
            provider.release(sandbox_id)
            assert sandbox_id in provider._warm_pool
            observation.update(shell_marker=marker, warm_release_running=inspect_exact(handle.container_id)["State"]["Running"])
            save_evidence()
            return handle

        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("pool-native-private", user_id="owner")
        store = RunRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120)
        central = RunManager(store, worker_id="pool-central", run_ownership_config=ownership)
        worker = RunManager(store, worker_id="pool-receiver", run_ownership_config=ownership)
        bridge = MemoryStreamBridge()
        ctx = RunContext(
            checkpointer=MemorySaver(),
            thread_store=threads,
            event_store=DbRunEventStore(case.sf, workspace_required=True),
            workspace_context=case.original,
            app_config=configuration,
        )
        app = FastAPI()
        app.state.run_manager, app.state.run_store, app.state.thread_store, app.state.stream_bridge = central, store, threads, bridge
        request = SimpleNamespace(app=app, url="https://deerflow.example.invalid/")
        node = Node(cpu_millis=2000, memory_mib=2816, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"report"}, kinds={"C"})
        pool = Scheduling(ledger, nodes={"worker": node})
        secret = "native-node-offline-fixture-32-bytes"
        host = NativeDispatchHost(
            app, pool, {"artifact_root": str(tmp_path / "pool-native"), "native_node": "worker", "remote_all": True, "profile": "report", "profiles": {"report": {"cpu_millis": 100, "memory_mib": 64}}}, {"worker": secret}
        )
        install_native_dispatch(app, host)

        async def worker_request(operation, **values):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://native-fixture") as client:
                response = await client.post(
                    f"/api/native-workers/worker/{operation}",
                    headers={"Authorization": "Bearer " + secret},
                    json={"schema_revision": SCHEMA_REVISION, "protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": host.mount_id, "owner": "outbound", **values},
                )
            assert response.status_code == 200, response.text
            return response.json()

        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        owner_token = set_current_user(principal)
        entered, release = asyncio.Event(), asyncio.Event()
        adopted = None
        acquired = []
        try:
            record = await central.create_or_reject("pool-native-private", user_id="owner")
            graph_input = {"messages": [HumanMessage(content="research this synthetic document")]}

            async def snapshot_factory(**transport):
                return await make_native_snapshot(
                    request,
                    record,
                    run_ctx=ctx,
                    body=RunCreateRequest(stream_mode=["values"]),
                    config={"configurable": {"thread_id": record.thread_id}},
                    graph_input=graph_input,
                    admitted_knowledge_scope=None,
                    scope_assistant_id=None,
                    scheduled_task_runtime=None,
                    require_existing_thread=True,
                    **transport,
                )

            from deerflow.skills.projection import ensure_thread_skill_projection
            from deerflow.skills.storage import get_or_new_user_skill_storage

            storage = get_or_new_user_skill_storage("owner", app_config=configuration)
            projection = ensure_thread_skill_projection(storage, "pool-native-private", set())
            assert projection is not None
            fixture_root = Path(os.environ["TEST_AIO_ROOT"]).resolve()
            for category in (projection.public, projection.custom, projection.legacy, projection.integrations):
                assert category.is_dir() and not category.is_symlink()
                assert category.resolve().is_relative_to(fixture_root)
                assert not list(category.iterdir()), "Empty native allowlist must expose no skill files"
            assert await host.admit_native(record, snapshot_factory)
            assert record.ownership_lost
            assert await asyncio.to_thread(pool.claim, "worker", "legacy-owner", kind="C") is None
            assert await asyncio.to_thread(pool.owned, "worker", "outbound", kind="C") == []
            selected = set_current_workspace(case.other)
            try:
                polled = await worker_request("poll")
                envelope = polled["claim"]
                assert envelope is not None and not polled["owned"]
                job = envelope["job"]
                assert job["native"]["run_id"] == record.run_id and job["state"] == "starting" and job["attempt"] == 1
                assert job["workspace_context"] == asdict(case.original) and job["worker_owner"] == "outbound"
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                again = await worker_request("poll")
                assert again["claim"] is None and len(again["owned"]) == 1
                assert again["owned"][0]["job"]["generation"] == job["generation"]
                assert again["owned"][0]["capability"]
                control = await worker_request("get", job_id=job["id"], generation=job["generation"])
                assert not {"native", "spec", "error", "artifact", "workspace_context"}.intersection(control)
                reporter = NativeWorkerHost.__new__(NativeWorkerHost)
                reporter.request = worker_request
                job = await reporter.report(job, {"start_intent": True})
                assert job["start_intent"] and job["native"]["run_id"] == record.run_id
                started = await worker_request("get", job_id=job["id"], generation=job["generation"])
                assert started["start_intent"] and "native" not in started

                class HeldModel(BaseChatModel):
                    @property
                    def _llm_type(self):
                        return "deterministic-native-pool"

                    def _generate(self, *args, **kwargs):
                        raise AssertionError("native pool main must remain asynchronous")

                    async def _agenerate(self, *args, **kwargs):
                        assert get_current_workspace() == case.original
                        acquired.append(await asyncio.to_thread(acquire_use_release))
                        entered.set()
                        await release.wait()
                        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="private pooled research report", usage_metadata={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12}))])

                model = HeldModel()

                async def respond(state, config):
                    return {"messages": [await model.ainvoke(state["messages"], config=config)]}

                builder = StateGraph(MessagesState, context_schema=dict)
                builder.add_node("respond", respond)
                builder.add_edge(START, "respond")
                builder.add_edge("respond", END)
                graph = builder.compile()
                monkeypatch.setattr(services, "get_run_context", lambda request: ctx)
                monkeypatch.setattr(services, "resolve_agent_factory", lambda assistant_id: lambda **kwargs: graph)

                async def owner(*args, **kwargs):
                    return principal

                monkeypatch.setattr(services, "resolve_trusted_internal_owner_for_attribution", owner)
                app.state.run_manager = worker
                reporter.app, reporter.secret, reporter.adoption_lock = app, secret, asyncio.Lock()
                reporter.stop_tasks = {}
                adopted = await reporter.adopt_owned(job, envelope["capability"])
                assert reporter.sandbox_captures[job["id"]].record is adopted
                entered_wait = asyncio.create_task(entered.wait())
                try:
                    done, _ = await asyncio.wait((entered_wait, adopted.task), timeout=180, return_when=asyncio.FIRST_COMPLETED)
                    if adopted.task in done:
                        await adopted.task
                        pytest.fail("Native task ended before AIO acquisition: " + str(adopted.error))
                    assert entered_wait in done, "Cold AIO acquisition exceeded 180s"
                finally:
                    entered_wait.cancel()
                    await asyncio.gather(entered_wait, return_exceptions=True)
                current = await worker_request("get", job_id=job["id"], generation=job["generation"])
                await worker_request("report", job_id=job["id"], generation=job["generation"], changes={"state": "running"}, expected=current)
                running = await worker_request("poll")
                assert running["claim"] is None and len(running["owned"]) == 1
                control = running["owned"][0]
                assert control["capability"] is None and "native" not in control["job"]
                assert control["job"]["id"] == job["id"] and not control["job"]["cancel_requested"]
                release.set()
                await asyncio.wait_for(adopted.task, timeout=20)
                # The real receiver-bound capture observed an actual AIO acquisition.
                reporter.sandbox_captures[job["id"]].execution_drained(adopted)
                handle = acquired[0]
                assert provider._warm_pool[handle.sandbox_id][0].container_id == handle.container_id
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1

                # Fail before destruction once; this is deliberate fault
                # injection, not a claim of real TCP/daemon outage acceptance.
                def unavailable(_info):
                    raise RuntimeError("Injected before Docker STOP")

                with monkeypatch.context() as fault:
                    fault.setattr(provider._backend, "destroy", unavailable)
                    with pytest.raises(RuntimeError, match="STOP remains unconfirmed"):
                        await asyncio.create_task(reporter.stop_owned(job), context=Context())
                assert inspect_exact(handle.container_id)["State"]["Running"]
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                assert not (await asyncio.to_thread(ledger.get, job["id"]))["physical_stopped"]
                assert job["id"] not in reporter.stop_tasks
                observation.update(injected_stop_failed=True, capacity_after_unknown=1, running_after_unknown=True)
                save_evidence()
                # No workspace context here: consume the captured immutable
                # physical identity through the real worker/provider STOP path.
                await asyncio.create_task(reporter.stop_owned(job), context=Context())
                assert inspect_exact(handle.container_id) is None
                assert handle.sandbox_id not in provider._warm_pool
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 1
                observation.update(normal_stop_confirmed=True, missing_exact_id_after_stop=True, capacity_before_report=1)
                save_evidence()
                async with case.sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    events = (await session.scalars(sa.select(RunEventRow).where(RunEventRow.run_id == record.run_id))).all()
                    assert row.status == "success" and row.last_ai_message == "private pooled research report" and row.total_tokens == 12
                    assert events and all(event.workspace_id == case.original.workspace_id and event.user_id == "owner" for event in events)
                    assert any("private pooled research report" in str(event.content) for event in events)
                current = await worker_request("get", job_id=job["id"], generation=job["generation"])
                # Only the confirmed worker STOP permits this real report CAS.
                settled = await worker_request("report", job_id=job["id"], generation=job["generation"], changes={"state": "completed", "physical_stopped": True}, expected=current)
                assert settled["state"] == "completed" and "native" not in settled
                assert (await asyncio.to_thread(pool.node_status, "worker"))["unreleased"] == 0
                settled_poll = await worker_request("poll")
                assert settled_poll["claim"] is None and not settled_poll["owned"]
                observation.update(capacity_after_report=0, native_run_id=record.run_id, native_status="success")
                save_evidence()
                assert get_current_workspace() == case.other
            finally:
                reset_current_workspace(selected)
        finally:
            release.set()
            if adopted is not None and adopted.task is not None and not adopted.task.done():
                adopted.task.cancel()
                try:
                    await adopted.task
                except asyncio.CancelledError:
                    pass
            await worker.stop_heartbeat()
            await central.stop_heartbeat()
            reset_current_user(owner_token)
            # Finally is hygiene, never evidence for normal_stop_confirmed.
            # shutdown is scoped to this provider's unique prefix/owned IDs.
            observation["finally_cleanup_started"] = True
            save_evidence()
            await asyncio.to_thread(provider.shutdown)
            provider.reset()

    try:
        _in_workspace_case(native_engine, scenario)
    finally:
        ledger.engine.dispose()
