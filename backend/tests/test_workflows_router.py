"""Tests for durable workflow read endpoints."""

import asyncio

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import workflows
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.workflows.store.memory import MemoryWorkflowStore


def _make_client(
    store: MemoryWorkflowStore,
    *,
    run_event_store: MemoryRunEventStore | None = None,
    run_store: MemoryRunStore | None = None,
) -> TestClient:
    app = make_authed_test_app()
    app.state.workflow_store = store
    app.state.run_event_store = run_event_store or MemoryRunEventStore()
    app.state.run_store = run_store or MemoryRunStore()
    app.include_router(workflows.router)
    return TestClient(app)


def test_list_and_get_workflows():
    store = MemoryWorkflowStore()
    asyncio.run(
        store.create_or_get(
            workflow_id="wf-api-1",
            source_type="api",
            source="dashboard",
            status="running",
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
        )
    )
    asyncio.run(
        store.create_or_get(
            workflow_id="wf-channel-1",
            source_type="channel",
            source="slack",
            status="received",
            user_id="bob",
        )
    )

    with _make_client(store) as client:
        listed = client.get("/api/workflows", params={"status": "running", "source_type": "api"}).json()
        loaded = client.get("/api/workflows/wf-api-1").json()

    assert [row["workflow_id"] for row in listed["data"]] == ["wf-api-1"]
    assert loaded["workflow_id"] == "wf-api-1"
    assert loaded["thread_id"] == "thread-1"
    assert loaded["run_id"] == "run-1"


def test_list_workflow_events_and_missing_workflow():
    store = MemoryWorkflowStore()
    asyncio.run(store.create_or_get(workflow_id="wf-events", source_type="api"))
    asyncio.run(
        store.append_event(
            "wf-events",
            event_type="workflow.received",
            content={"source": "dashboard"},
        )
    )
    asyncio.run(
        store.append_event(
            "wf-events",
            event_type="workflow.bound",
            thread_id="thread-1",
            run_id="run-1",
        )
    )

    with _make_client(store) as client:
        events = client.get("/api/workflows/wf-events/events", params={"event_type": "workflow.bound"}).json()
        missing = client.get("/api/workflows/missing/events")

    assert events["workflow"]["workflow_id"] == "wf-events"
    assert [event["event_type"] for event in events["events"]] == ["workflow.bound"]
    assert events["events"][0]["seq"] == 2
    assert missing.status_code == 404


def test_workflow_by_run_and_timeline_merges_run_events():
    workflow_store = MemoryWorkflowStore()
    run_event_store = MemoryRunEventStore()
    run_store = MemoryRunStore()
    asyncio.run(
        workflow_store.create_or_get(
            workflow_id="wf-trace",
            source_type="api",
            source="/api/runs/wait",
            status="succeeded",
            thread_id="thread-1",
            run_id="run-1",
        )
    )
    asyncio.run(
        workflow_store.append_event(
            "wf-trace",
            event_type="workflow.received",
            created_at="2026-06-26T00:00:00+00:00",
        )
    )
    asyncio.run(
        workflow_store.append_event(
            "wf-trace",
            event_type="workflow.succeeded",
            thread_id="thread-1",
            run_id="run-1",
            created_at="2026-06-26T00:00:02+00:00",
        )
    )
    asyncio.run(
        run_event_store.put(
            thread_id="thread-1",
            run_id="run-1",
            event_type="messages",
            category="message",
            content={"role": "assistant", "content": "done"},
            created_at="2026-06-26T00:00:01+00:00",
        )
    )
    asyncio.run(run_store.put("run-1", thread_id="thread-1", status="success"))

    with _make_client(workflow_store, run_event_store=run_event_store, run_store=run_store) as client:
        by_run = client.get("/api/workflows/by-run/run-1").json()
        timeline = client.get("/api/workflows/wf-trace/timeline").json()

    assert by_run["workflow_id"] == "wf-trace"
    assert timeline["workflow"]["workflow_id"] == "wf-trace"
    assert timeline["run"]["run_id"] == "run-1"
    assert [event["kind"] for event in timeline["timeline"]] == [
        "workflow_event",
        "run_event",
        "workflow_event",
    ]
    assert [event["event_type"] for event in timeline["timeline"]] == [
        "workflow.received",
        "messages",
        "workflow.succeeded",
    ]
