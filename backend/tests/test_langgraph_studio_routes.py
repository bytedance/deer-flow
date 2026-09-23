"""Route-level regressions for standalone LangGraph Studio assistants."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from deerflow.mcp_scope import mcp_session_scope_key

BACKEND_DIR = Path(__file__).resolve().parents[1]

_GRAPH_SOURCE = """
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import ToolNode
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from mcp.types import CallToolResult, TextContent

from deerflow.mcp import tools as mcp_tools


class _FakePool:
    async def get_session(self, _server_name, scope_key, _connection):
        return object()


_POOL = _FakePool()
mcp_tools.get_session_pool = lambda: _POOL


async def _unused_probe():
    raise AssertionError("the pooled wrapper must replace this implementation")


async def _call_remote(
    _session,
    _pool,
    *,
    scope_key,
    **_kwargs,
):
    return CallToolResult(
        content=[TextContent(type="text", text=scope_key)],
    )


mcp_tools.call_pooled_session_tool = _call_remote
pooled_probe = mcp_tools._make_session_pool_tool(
    StructuredTool(
        name="probe",
        description="Return the standalone run's pooled MCP session scope.",
        args_schema={"type": "object", "properties": {}},
        coroutine=_unused_probe,
    ),
    "test-server",
    {"transport": "streamable_http", "url": "http://unused.invalid/mcp"},
)

builder = StateGraph(MessagesState, context_schema=dict)


def request_probe(_state, runtime: Runtime):
    assert runtime.context["preserved_context_probe"] == "kept"
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "probe",
                        "args": {},
                        "id": "probe-call",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }


builder.add_node("request_probe", request_probe)
builder.add_node("tools", ToolNode([pooled_probe]))
builder.add_edge(START, "request_probe")
builder.add_edge("request_probe", "tools")
builder.add_edge("tools", END)
graph = builder.compile()
""".lstrip()

_CURRENT_AUTH_SHIM = """
from app.gateway.langgraph_auth import auth
from app.gateway.langgraph_studio import langgraph_app
""".lstrip()

_LEGACY_AUTH_SHIM = """
from fastapi import FastAPI
from langgraph_sdk import Auth

auth = Auth()

@auth.authenticate
async def authenticate(request):
    return "langgraph-studio-user"

@auth.on
async def legacy_owner_filter(ctx, value):
    metadata = value.setdefault("metadata", {})
    metadata["user_id"] = ctx.user.identity
    return {"user_id": ctx.user.identity}

langgraph_app = FastAPI()
""".lstrip()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_scope(
    client: httpx.Client,
    thread_id: str,
    *,
    context: dict | None = None,
    if_not_exists: str | None = None,
) -> str:
    payload = {
        "assistant_id": "test_graph",
        "input": {"messages": []},
        "context": {"preserved_context_probe": "kept", **(context or {})},
    }
    if if_not_exists is not None:
        payload["if_not_exists"] = if_not_exists
    response = client.post(
        f"/threads/{thread_id}/runs/wait",
        json=payload,
    )
    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assert messages[-1]["type"] == "tool"
    assert messages[-1]["status"] == "success"
    return messages[-1]["content"][0]["text"]


def _run_stateless_scope(client: httpx.Client, run_id: str) -> str:
    response = client.post(
        "/runs/wait",
        json={
            "assistant_id": "test_graph",
            "run_id": run_id,
            "input": {"messages": []},
            "context": {"preserved_context_probe": "kept"},
        },
    )
    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assert messages[-1]["type"] == "tool"
    assert messages[-1]["status"] == "success"
    return messages[-1]["content"][0]["text"]


@contextmanager
def _running_studio_server(
    runtime_dir: Path,
    *,
    auth_source: str,
) -> Iterator[httpx.Client]:
    """Run the locked dev server against one persistent runtime directory."""
    (runtime_dir / "graph.py").write_text(_GRAPH_SOURCE, encoding="utf-8")
    (runtime_dir / "auth_shim.py").write_text(auth_source, encoding="utf-8")
    config_path = runtime_dir / "langgraph.json"
    config_path.write_text(
        json.dumps(
            {
                "python_version": "3.12",
                "dependencies": [str(BACKEND_DIR)],
                "graphs": {"test_graph": "./graph.py:graph"},
                "auth": {"path": "./auth_shim.py:auth"},
                "http": {"app": "./auth_shim.py:langgraph_app"},
                "env": {
                    "AUTH_JWT_SECRET": "test-secret-key-for-langgraph-route-tests-min-32",
                    "DEER_FLOW_AUTH_DISABLED": "1",
                    "LANGSMITH_TRACING": "false",
                },
            }
        ),
        encoding="utf-8",
    )

    port = _free_port()
    log_path = runtime_dir / f"server-{uuid4()}.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(BACKEND_DIR), env.get("PYTHONPATH")]))
    env["LANGSMITH_LANGGRAPH_API_VARIANT"] = "local_dev"
    executable = shutil.which(
        "langgraph",
        path=os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]),
    )
    if executable is None:
        pytest.fail("langgraph executable is unavailable; install the backend development dependencies before running Studio route tests")
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                executable,
                "dev",
                "--config",
                str(config_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-browser",
                "--no-reload",
            ],
            cwd=runtime_dir,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 90
        last_error: Exception | None = None
        while time.monotonic() < deadline and process.poll() is None:
            try:
                response = httpx.get(
                    f"{base_url}/ok",
                    timeout=1,
                    trust_env=False,
                )
                if response.status_code == 200:
                    break
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.1)
        else:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            pytest.fail(f"LangGraph dev server failed to start ({last_error!r}).\n{log_path.read_text(encoding='utf-8')}")

        client = httpx.Client(
            base_url=base_url,
            headers={"x-auth-scheme": "langsmith"},
            timeout=10,
            trust_env=False,
        )
        try:
            yield client
        finally:
            client.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture(scope="module")
def studio_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[httpx.Client]:
    """Run the locked dev server with a tiny graph and DeerFlow's real auth."""
    runtime_dir = tmp_path_factory.mktemp("langgraph-studio-routes")
    with _running_studio_server(
        runtime_dir,
        auth_source=_CURRENT_AUTH_SHIM,
    ) as client:
        yield client


@pytest.mark.parametrize("requested_created_by", [None, "system"])
def test_studio_create_then_get_and_search_assistant(
    studio_client: httpx.Client,
    requested_created_by: str | None,
):
    """Ordinary and forged create payloads stay Studio-owned and readable."""
    assistant_id = str(uuid4())
    label = f"route-test-{assistant_id}"
    metadata = {"label": label}
    if requested_created_by is not None:
        metadata["created_by"] = requested_created_by

    response = studio_client.post(
        "/assistants",
        json={
            "assistant_id": assistant_id,
            "graph_id": "test_graph",
            "metadata": metadata,
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["metadata"]["created_by"] == "user"
    assert created["metadata"]["user_id"] == "langgraph-studio-user"

    response = studio_client.get(f"/assistants/{assistant_id}")
    assert response.status_code == 200, response.text
    assert response.json()["assistant_id"] == assistant_id

    response = studio_client.post(
        "/assistants/search",
        json={"metadata": {"label": label}},
    )
    assert response.status_code == 200, response.text
    assert [item["assistant_id"] for item in response.json()] == [assistant_id]


def test_studio_can_get_and_search_registered_system_assistant(
    studio_client: httpx.Client,
):
    """The registered graph remains discoverable alongside Studio-owned rows."""
    response = studio_client.post(
        "/assistants/search",
        json={"graph_id": "test_graph", "metadata": {"created_by": "system"}},
    )
    assert response.status_code == 200, response.text
    registered = response.json()
    assert len(registered) == 1

    assistant_id = registered[0]["assistant_id"]
    response = studio_client.get(f"/assistants/{assistant_id}")
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["created_by"] == "system"


def test_studio_registered_graph_supplies_server_owned_mcp_incarnation(
    studio_client: httpx.Client,
):
    thread_id = str(uuid4())
    response = studio_client.post(
        "/threads",
        json={
            "thread_id": thread_id,
            "metadata": {"thread_incarnation": "attacker"},
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    incarnation = created["metadata"]["thread_incarnation"]
    assert incarnation != "attacker"
    expected_scope = mcp_session_scope_key(
        user_id="langgraph-studio-user",
        thread_id=thread_id,
        thread_incarnation=incarnation,
    )
    assert (
        _run_scope(
            studio_client,
            thread_id,
            context={
                "thread_incarnation": "attacker",
                "__deerflow_thread_incarnation_metadata_guard": False,
                "user_id": "attacker",
                "thread_id": "attacker",
                "run_id": "attacker",
            },
        )
        == expected_scope
    )
    assert _run_scope(studio_client, thread_id) == expected_scope

    response = studio_client.patch(
        f"/threads/{thread_id}",
        json={"metadata": {"thread_incarnation": "attacker"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["thread_incarnation"] == incarnation
    assert _run_scope(studio_client, thread_id) == expected_scope

    response = studio_client.delete(f"/threads/{thread_id}")
    assert response.status_code == 204, response.text
    response = studio_client.post(
        "/threads",
        json={
            "thread_id": thread_id,
            "metadata": {"thread_incarnation": "attacker"},
        },
    )
    assert response.status_code == 200, response.text
    replacement_incarnation = response.json()["metadata"]["thread_incarnation"]
    assert replacement_incarnation not in {"attacker", incarnation}
    assert _run_scope(studio_client, thread_id) == mcp_session_scope_key(
        user_id="langgraph-studio-user",
        thread_id=thread_id,
        thread_incarnation=replacement_incarnation,
    )


def test_studio_implicit_thread_creation_persists_mcp_incarnation(
    studio_client: httpx.Client,
):
    thread_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=6) as executor:
        scopes = list(
            executor.map(
                lambda _index: _run_scope(
                    studio_client,
                    thread_id,
                    context={"thread_incarnation": "attacker"},
                    if_not_exists="create",
                ),
                range(6),
            )
        )
    assert len(set(scopes)) == 1
    scope = scopes[0]

    response = studio_client.get(f"/threads/{thread_id}")
    assert response.status_code == 200, response.text
    incarnation = response.json()["metadata"]["thread_incarnation"]
    assert incarnation != "attacker"
    assert scope == mcp_session_scope_key(
        user_id="langgraph-studio-user",
        thread_id=thread_id,
        thread_incarnation=incarnation,
    )
    assert _run_scope(studio_client, thread_id) == scope


def test_studio_implicit_thread_creation_preserves_searchable_metadata(
    studio_client: httpx.Client,
):
    thread_id = str(uuid4())
    project_tag = f"project-{uuid4()}"
    payload = {
        "assistant_id": "test_graph",
        "input": {"messages": []},
        "if_not_exists": "create",
        "context": {"preserved_context_probe": "kept"},
        "metadata": {
            "title": "Run title",
            "project_tag": project_tag,
            "user_id": "attacker",
            "thread_incarnation": "attacker",
            "__deerflow_thread_incarnation_metadata_guard": False,
        },
        "config": {
            "metadata": {
                "title": "Config title",
                "config_tag": "retained",
                "user_id": "config-attacker",
                "thread_incarnation": "config-attacker",
                "__deerflow_thread_incarnation_metadata_guard": False,
            },
        },
    }
    response = studio_client.post(f"/threads/{thread_id}/runs/wait", json=payload)
    assert response.status_code == 200, response.text
    tool_message = response.json()["messages"][-1]
    assert tool_message["status"] == "success"

    response = studio_client.get(f"/threads/{thread_id}")
    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert metadata["title"] == "Run title"
    assert metadata["project_tag"] == project_tag
    assert metadata["config_tag"] == "retained"
    assert metadata["user_id"] == "langgraph-studio-user"
    assert metadata["thread_incarnation"] not in {"attacker", "config-attacker"}
    assert "__deerflow_thread_incarnation_metadata_guard" not in metadata
    assert tool_message["content"][0]["text"] == mcp_session_scope_key(
        user_id="langgraph-studio-user",
        thread_id=thread_id,
        thread_incarnation=metadata["thread_incarnation"],
    )

    response = studio_client.post("/threads/search", json={"metadata": {"project_tag": project_tag}})
    assert response.status_code == 200, response.text
    assert [thread["thread_id"] for thread in response.json()] == [thread_id]

    # A later run must not overwrite the existing thread's creation metadata.
    payload["metadata"]["title"] = "Later run title"
    payload["metadata"]["project_tag"] = "later-project"
    response = studio_client.post(f"/threads/{thread_id}/runs/wait", json=payload)
    assert response.status_code == 200, response.text
    response = studio_client.get(f"/threads/{thread_id}")
    assert response.status_code == 200, response.text
    assert response.json()["metadata"] == metadata


def test_studio_stateless_runs_get_distinct_mcp_scopes(
    studio_client: httpx.Client,
):
    first_run_id = str(uuid4())
    second_run_id = str(uuid4())

    first_scope = _run_stateless_scope(studio_client, first_run_id)
    second_scope = _run_stateless_scope(studio_client, second_run_id)

    assert first_scope != second_scope
    assert mcp_session_scope_key(
        user_id="langgraph-studio-user",
        thread_id="default",
        thread_incarnation=None,
    ) not in {first_scope, second_scope}


def test_studio_legacy_thread_uses_explicit_legacy_scope_without_backfill(
    tmp_path: Path,
):
    thread_id = str(uuid4())
    with _running_studio_server(
        tmp_path,
        auth_source=_LEGACY_AUTH_SHIM,
    ) as legacy_client:
        response = legacy_client.post(
            "/threads",
            json={"thread_id": thread_id, "metadata": {"legacy": True}},
        )
        assert response.status_code == 200, response.text
        assert "thread_incarnation" not in response.json()["metadata"]

    with _running_studio_server(
        tmp_path,
        auth_source=_CURRENT_AUTH_SHIM,
    ) as current_client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            scopes = list(
                executor.map(
                    lambda _index: _run_scope(current_client, thread_id),
                    range(2),
                )
            )
        assert len(set(scopes)) == 1
        scope = scopes[0]
        response = current_client.get(f"/threads/{thread_id}")
        assert response.status_code == 200, response.text
        assert "thread_incarnation" not in response.json()["metadata"]
        assert scope == mcp_session_scope_key(
            user_id="langgraph-studio-user",
            thread_id=thread_id,
            thread_incarnation=None,
        )
        assert _run_scope(current_client, thread_id) == scope


def test_studio_update_cannot_forge_system_provenance(
    studio_client: httpx.Client,
):
    assistant_id = str(uuid4())
    response = studio_client.post(
        "/assistants",
        json={"assistant_id": assistant_id, "graph_id": "test_graph"},
    )
    assert response.status_code == 200, response.text

    response = studio_client.patch(
        f"/assistants/{assistant_id}",
        json={"metadata": {"created_by": "system", "updated": True}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["metadata"] == {
        "created_by": "user",
        "updated": True,
        "user_id": "langgraph-studio-user",
    }

    response = studio_client.post(
        f"/assistants/{assistant_id}/latest",
        json={"version": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
    assert response.json()["metadata"]["created_by"] == "user"

    response = studio_client.post(
        f"/assistants/{assistant_id}/latest",
        json={"version": 2},
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["metadata"]["created_by"] == "user"


def test_non_studio_auth_disabled_principal_can_select_older_and_newer_versions(
    studio_client: httpx.Client,
):
    """Exercise non-Studio owner scoping without claiming JWT-path coverage."""
    assistant_id = str(uuid4())
    with httpx.Client(
        base_url=studio_client.base_url,
        timeout=10,
        trust_env=False,
    ) as client:
        response = client.post(
            "/assistants",
            json={"assistant_id": assistant_id, "graph_id": "test_graph"},
        )
        assert response.status_code == 200, response.text
        owner_id = response.json()["metadata"]["user_id"]
        assert owner_id != "langgraph-studio-user"

        response = client.patch(
            f"/assistants/{assistant_id}",
            json={"metadata": {"revision": 2}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 2

        for version in (1, 2):
            response = client.post(
                f"/assistants/{assistant_id}/latest",
                json={"version": version},
            )
            assert response.status_code == 200, response.text
            assert response.json()["version"] == version
            assert response.json()["metadata"] == {
                **({"revision": 2} if version == 2 else {}),
                "created_by": "user",
                "user_id": owner_id,
            }


def test_persisted_legacy_assistants_survive_cross_version_restart(
    tmp_path: Path,
):
    """Old forged rows are repaired before the locked runtime can purge them."""
    assistant_ids = [str(uuid4()) for _ in range(4)]

    with _running_studio_server(
        tmp_path,
        auth_source=_LEGACY_AUTH_SHIM,
    ) as legacy_client:
        for assistant_id in assistant_ids:
            response = legacy_client.post(
                "/assistants",
                json={
                    "assistant_id": assistant_id,
                    "graph_id": "test_graph",
                    "metadata": {
                        "created_by": "system",
                        "legacy": assistant_id,
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["metadata"]["created_by"] == "system"

            response = legacy_client.patch(
                f"/assistants/{assistant_id}",
                json={
                    "metadata": {
                        "created_by": "system",
                        "legacy": assistant_id,
                        "revision": 2,
                    }
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["version"] == 2

    assert (tmp_path / ".langgraph_api" / ".langgraph_ops.pckl").is_file()

    with _running_studio_server(
        tmp_path,
        auth_source=_CURRENT_AUTH_SHIM,
    ) as repaired_client:
        for assistant_id in assistant_ids:
            response = repaired_client.get(f"/assistants/{assistant_id}")
            assert response.status_code == 200, response.text
            assert response.json()["metadata"] == {
                "created_by": "user",
                "legacy": assistant_id,
                "revision": 2,
                "user_id": "langgraph-studio-user",
            }

            response = repaired_client.post(
                f"/assistants/{assistant_id}/versions",
                json={"limit": 10},
            )
            assert response.status_code == 200, response.text
            versions = response.json()
            assert {item["version"] for item in versions} == {1, 2}
            assert all(item["metadata"]["created_by"] == "user" for item in versions)

            response = repaired_client.post(
                f"/assistants/{assistant_id}/latest",
                json={"version": 1},
            )
            assert response.status_code == 200, response.text
            assert response.json()["metadata"]["created_by"] == "user"

            response = repaired_client.post(
                f"/assistants/{assistant_id}/latest",
                json={"version": 2},
            )
            assert response.status_code == 200, response.text
            assert response.json()["metadata"]["created_by"] == "user"
