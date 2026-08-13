"""Route-level regressions for standalone LangGraph Studio assistants."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def studio_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[httpx.Client]:
    """Run the locked dev server with a tiny graph and DeerFlow's real auth."""
    runtime_dir = tmp_path_factory.mktemp("langgraph-studio-routes")
    (runtime_dir / "graph.py").write_text(
        """
from langgraph.graph import END, START, StateGraph

builder = StateGraph(dict)
builder.add_node("noop", lambda state: {})
builder.add_edge(START, "noop")
builder.add_edge("noop", END)
graph = builder.compile()
""".lstrip(),
        encoding="utf-8",
    )
    (runtime_dir / "auth_shim.py").write_text(
        "from app.gateway.langgraph_auth import auth\nfrom app.gateway.langgraph_studio import langgraph_app\n",
        encoding="utf-8",
    )
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
    log_path = runtime_dir / "server.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(BACKEND_DIR), env.get("PYTHONPATH")]))
    env["LANGSMITH_LANGGRAPH_API_VARIANT"] = "local_dev"
    executable = Path(sys.executable).with_name("langgraph")
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                str(executable),
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
        deadline = time.monotonic() + 45
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
    assert response.status_code == 403, response.text
    assert "version rollback" in response.json()["detail"].lower()
