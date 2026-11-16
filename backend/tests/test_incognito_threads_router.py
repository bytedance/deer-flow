"""Incognito thread visibility at the HTTP boundary.

The store-level contract lives in ``test_thread_meta_repo.py`` and
``test_memory_thread_meta_isolation.py``; these tests cover the router:
creation gating, the response flag, and the surfaces that must refuse an
incognito thread (project move, branch, share).
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from test_threads_router import _PermissiveThreadMetaStore, _ThreadTestRunManager

from app.gateway.auth_disabled import AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.routers import shares, threads
from deerflow.config.incognito_config import IncognitoThreadsConfig
from deerflow.persistence.thread_meta.base import THREAD_INCOGNITO_ENDED_METADATA_KEY
from deerflow.persistence.thread_meta.memory import THREADS_NS


def _config(**overrides) -> SimpleNamespace:
    return SimpleNamespace(incognito=IncognitoThreadsConfig(**overrides))


@pytest.fixture(autouse=True)
def _router_config(monkeypatch):
    # The worktree has no config.yaml and these routes only read the
    # incognito block.
    monkeypatch.setattr(threads, "get_config", lambda: _config())


def _build_app(*, auth_source: str = AUTH_SOURCE_SESSION):
    app = make_authed_test_app(auth_source=auth_source)
    app.state.store = InMemoryStore()
    app.state.checkpointer = InMemorySaver()
    app.state.run_manager = _ThreadTestRunManager()
    app.state.thread_store = _PermissiveThreadMetaStore(app.state.store)
    app.include_router(threads.router)
    app.include_router(shares.router)
    return app


def _create(client: TestClient, *, incognito: bool = False, **body) -> str:
    thread_id = body.pop("thread_id", uuid4().hex)
    response = client.post("/api/threads", json={"thread_id": thread_id, "incognito": incognito, **body})
    assert response.status_code == 200, response.text
    return thread_id


def test_incognito_thread_is_hidden_from_search_but_readable_by_id(monkeypatch):
    class _Accessor:
        async def aget(self, config):
            return SimpleNamespace(config={}, values={}, metadata={}, created_at="", tasks=[], next=[])

    async def _fake_accessor(request, **kwargs):
        return _Accessor(), {"configurable": {"thread_id": kwargs["thread_id"]}}

    monkeypatch.setattr(threads, "abuild_checkpoint_state_accessor", _fake_accessor)

    client = TestClient(_build_app())
    secret_id = _create(client, incognito=True)
    visible_id = _create(client)

    listed = client.post("/api/threads/search", json={})
    assert [thread["thread_id"] for thread in listed.json()] == [visible_id]

    fetched = client.get(f"/api/threads/{secret_id}")
    assert fetched.status_code == 200
    assert fetched.json()["incognito"] is True

    ordinary = client.get(f"/api/threads/{visible_id}")
    assert ordinary.json()["incognito"] is False


def test_incognito_create_rejects_project_membership():
    client = TestClient(_build_app())
    response = client.post("/api/threads", json={"thread_id": uuid4().hex, "incognito": True, "project_id": "p1"})

    assert response.status_code == 400
    assert "project" in response.json()["detail"].lower()


def test_incognito_create_requires_a_browser_session():
    client = TestClient(_build_app(auth_source=AUTH_SOURCE_PAT))
    response = client.post("/api/threads", json={"thread_id": uuid4().hex, "incognito": True})

    assert response.status_code == 403


def test_incognito_create_respects_the_operator_switch(monkeypatch):
    monkeypatch.setattr(threads, "get_config", lambda: _config(enabled=False))
    client = TestClient(_build_app())
    response = client.post("/api/threads", json={"thread_id": uuid4().hex, "incognito": True})

    assert response.status_code == 403


def test_idempotent_create_never_converts_visibility():
    client = TestClient(_build_app())
    ordinary_id = _create(client)
    incognito_id = _create(client, incognito=True)

    promote = client.post("/api/threads", json={"thread_id": ordinary_id, "incognito": True})
    demote = client.post("/api/threads", json={"thread_id": incognito_id})

    assert promote.status_code == 409
    assert demote.status_code == 409


def test_metadata_marker_seeds_an_incognito_thread_for_the_sdk_create():
    """The LangGraph SDK's implicit create can only carry metadata.

    On the first submit the SDK creates the thread itself and forwards the
    submit metadata; the browser marks an incognito send there. The Gateway
    must read that marker as the creation intent, otherwise the SDK's create
    sees a visibility mismatch against the REST pre-create and answers 409.
    """
    client = TestClient(_build_app())
    thread_id = uuid4().hex
    body = {"thread_id": thread_id, "metadata": {"incognito": True}}

    created = client.post("/api/threads", json=body)

    assert created.status_code == 200, created.text
    assert created.json()["incognito"] is True
    # The column is the single source of truth; the hint is not re-stored.
    assert "incognito" not in created.json()["metadata"]
    assert [thread["thread_id"] for thread in client.post("/api/threads/search", json={}).json()] == []

    # The SDK repeats its ensure-create while the chat is still lazy.
    again = client.post("/api/threads", json=body)
    assert again.status_code == 200


def test_metadata_marker_never_converts_an_ordinary_thread():
    client = TestClient(_build_app())
    ordinary_id = _create(client)

    response = client.post("/api/threads", json={"thread_id": ordinary_id, "metadata": {"incognito": True}})

    assert response.status_code == 409


def test_move_rejects_incognito_thread():
    client = TestClient(_build_app())
    thread_id = _create(client, incognito=True)

    response = client.post(f"/api/threads/{thread_id}/move", json={"project_id": None})

    assert response.status_code == 409


def test_branch_rejects_incognito_thread():
    client = TestClient(_build_app())
    thread_id = _create(client, incognito=True)

    response = client.post(f"/api/threads/{thread_id}/branches", json={"message_id": "assistant-1"})

    assert response.status_code == 409


def test_share_rejects_incognito_thread():
    client = TestClient(_build_app())
    thread_id = _create(client, incognito=True)

    response = client.post(f"/api/threads/{thread_id}/shares", json={"expires_in_seconds": 3600})

    assert response.status_code == 409


def test_end_endpoint_schedules_the_grace_deadline():
    app = _build_app()
    client = TestClient(app)
    thread_id = _create(client, incognito=True)

    response = client.post(f"/api/threads/{thread_id}/incognito/end")

    assert response.status_code == 204, response.text
    record = app.state.store.get(THREADS_NS, thread_id).value
    assert record["metadata"][THREAD_INCOGNITO_ENDED_METADATA_KEY] is True
    assert record["expires_at"] is not None


def test_end_endpoint_rejects_an_ordinary_thread():
    app = _build_app()
    client = TestClient(app)
    thread_id = _create(client)

    response = client.post(f"/api/threads/{thread_id}/incognito/end")

    assert response.status_code == 409


def test_expired_incognito_thread_is_gone_and_cannot_be_recreated():
    app = _build_app()
    client = TestClient(app)
    thread_id = _create(client, incognito=True)
    # The tombstone the sweep writes before purging data.
    record = dict(app.state.store.get(THREADS_NS, thread_id).value)
    record["status"] = "expired"
    record["display_name"] = None
    app.state.store.put(THREADS_NS, thread_id, record)

    assert client.get(f"/api/threads/{thread_id}").status_code == 404
    assert client.post(f"/api/threads/{thread_id}/incognito/end").status_code == 404
    # The id stays owned by the tombstone: idempotent create must not
    # resurrect the thread as an ordinary one.
    recreated = client.post("/api/threads", json={"thread_id": thread_id})
    assert recreated.status_code == 410
    assert client.post("/api/threads", json={"thread_id": thread_id, "incognito": True}).status_code == 410
