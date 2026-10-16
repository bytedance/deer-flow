import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import memory
from deerflow.agents.memory import MemoryConflictError, MemoryCorruptionError
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem


def _sample_memory(facts: list[dict] | None = None) -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "2026-03-26T12:00:00Z",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": facts or [],
    }


# ── export ─────────────────────────────────────────────────────────────────


def test_export_memory_route_returns_current_memory() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    exported_memory = _sample_memory(facts=[{"id": "fact_export", "content": "User prefers concise responses.", "category": "preference", "confidence": 0.9, "createdAt": "2026-03-20T00:00:00Z", "source": "thread-1"}])

    mock_mgr = MagicMock()
    mock_mgr.get_memory.return_value = exported_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.get("/api/memory/export")
    assert response.status_code == 200
    assert response.json()["facts"] == exported_memory["facts"]


def test_get_memory_route_offloads_manager_call_from_event_loop() -> None:
    event_loop_thread = threading.get_ident()
    called_from: list[int] = []
    manager = MagicMock()

    def get_memory(*, user_id: str) -> dict:
        called_from.append(threading.get_ident())
        return _sample_memory()

    manager.get_memory.side_effect = get_memory
    request = SimpleNamespace()
    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory._resolve_memory_user_id", return_value="user-1"),
    ):
        response = asyncio.run(call_unwrapped(memory.get_memory, request))

    assert response.facts == []
    assert called_from and called_from[0] != event_loop_thread


def test_export_memory_route_preserves_source_error() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    exported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_correction",
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
                "sourceError": "The agent previously suggested npm start.",
            }
        ]
    )

    mock_mgr = MagicMock()
    mock_mgr.get_memory.return_value = exported_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.get("/api/memory/export")
    assert response.status_code == 200
    assert response.json()["facts"][0]["sourceError"] == "The agent previously suggested npm start."


# ── import ─────────────────────────────────────────────────────────────────


def test_import_memory_route_returns_imported_memory() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    imported_memory = _sample_memory(facts=[{"id": "fact_import", "content": "User works on DeerFlow.", "category": "context", "confidence": 0.87, "createdAt": "2026-03-20T00:00:00Z", "source": "manual"}])

    mock_mgr = MagicMock()
    mock_mgr.import_memory.return_value = imported_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.post("/api/memory/import", json=imported_memory)
    assert response.status_code == 200
    assert response.json()["facts"] == imported_memory["facts"]
    assert "agent_name" not in mock_mgr.import_memory.call_args.kwargs


def test_import_route_without_agent_name_persists_default_bucket_markdown(tmp_path) -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    imported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_gateway_import",
                "content": "Gateway imports use the default agent bucket.",
                "category": "context",
                "confidence": 0.9,
                "createdAt": "2026-07-21T00:00:00Z",
                "source": "import",
            }
        ]
    )

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        response = client.post("/api/memory/import", json=imported_memory)

    assert response.status_code == 200
    assert [fact["id"] for fact in response.json()["facts"]] == ["fact_gateway_import"]
    facts_root = tmp_path / "users" / "alice" / "agents" / "__default__" / "facts"
    assert [path.stem for path in facts_root.glob("**/*.md")] == ["fact_gateway_import"]


def test_import_memory_route_preserves_source_error() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    imported_memory = _sample_memory(
        facts=[
            {
                "id": "fact_correction",
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "thread-1",
                "sourceError": "The agent previously suggested npm start.",
            }
        ]
    )

    mock_mgr = MagicMock()
    mock_mgr.import_memory.return_value = imported_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.post("/api/memory/import", json=imported_memory)
    assert response.status_code == 200
    assert response.json()["facts"][0]["sourceError"] == "The agent previously suggested npm start."


def test_clear_memory_routes_persistent_write_through_mutation_drain() -> None:
    manager = MagicMock()
    manager.clear_memory.return_value = _sample_memory()
    calls: list[tuple] = []

    async def drained(action, func, expected_errors=(), /, *args, **kwargs):
        calls.append((func, expected_errors, args, kwargs))
        assert isinstance(expected_errors, tuple)
        return func(*args, **kwargs)

    request = SimpleNamespace()
    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory._resolve_memory_user_id", return_value="user-1"),
        patch("app.gateway.routers.memory.run_drained_write", side_effect=drained),
    ):
        asyncio.run(call_unwrapped(memory.clear_memory, request))

    expected_errors = (NotImplementedError, MemoryConflictError, MemoryCorruptionError, OSError)
    assert calls == [(manager.clear_memory, expected_errors, (), {"user_id": "user-1"})]


# ── clear ──────────────────────────────────────────────────────────────────


def test_clear_memory_route_returns_cleared_memory() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.clear_memory.return_value = _sample_memory()
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.delete("/api/memory")
    assert response.status_code == 200
    assert response.json()["facts"] == []
    assert "agent_name" not in mock_mgr.clear_memory.call_args.kwargs


# ── fact CRUD (normal / error) ─────────────────────────────────────────────


def test_create_memory_fact_route_returns_updated_memory() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    updated_memory = _sample_memory(facts=[{"id": "fact_new", "content": "User prefers concise code reviews.", "category": "preference", "confidence": 0.88, "createdAt": "2026-03-20T00:00:00Z", "source": "manual"}])

    mock_mgr = MagicMock()
    mock_mgr.create_fact.return_value = (updated_memory, "fact_new")
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.post("/api/memory/facts", json={"content": "User prefers concise code reviews.", "category": "preference", "confidence": 0.88})
    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_scoped_memory_read_and_fact_crud_preserve_requested_agent_name() -> None:
    """The gateway must not remap a case-sensitive remote backend identity."""
    app = make_authed_test_app()
    app.include_router(memory.router)
    selected_memory = _sample_memory(
        facts=[
            {
                "id": "fact_shared-id",
                "content": "Research agent preference",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )
    manager = MagicMock()
    manager.supports_agent_scoped_management = True
    manager.get_memory.return_value = selected_memory
    manager.create_fact.return_value = (selected_memory, "fact_shared-id")
    manager.update_fact.return_value = selected_memory
    manager.delete_fact.return_value = _sample_memory()

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        fetched = client.get("/api/memory?agent_name=Research-Agent")
        created = client.post(
            "/api/memory/facts?agent_name=Research-Agent",
            json={"content": "Research agent preference"},
        )
        updated = client.patch(
            "/api/memory/facts/fact_shared-id?agent_name=Research-Agent",
            json={"confidence": 0.95},
        )
        deleted = client.delete("/api/memory/facts/fact_shared-id?agent_name=Research-Agent")

    assert fetched.status_code == 200
    assert created.status_code == 200
    assert updated.status_code == 200
    assert deleted.status_code == 200
    manager.get_memory.assert_called_once_with(user_id="alice", agent_name="Research-Agent")
    assert manager.create_fact.call_args.kwargs["agent_name"] == "Research-Agent"
    assert manager.update_fact.call_args.kwargs["agent_name"] == "Research-Agent"
    assert manager.delete_fact.call_args.kwargs["agent_name"] == "Research-Agent"


def test_scoped_import_and_clear_preserve_requested_agent_name() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    selected_memory = _sample_memory()
    manager = MagicMock()
    manager.supports_agent_scoped_management = True
    manager.import_memory.return_value = selected_memory
    manager.clear_memory.return_value = selected_memory

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        imported = client.post("/api/memory/import?agent_name=Research-Agent", json=selected_memory)
        cleared = client.delete("/api/memory?agent_name=Research-Agent")

    assert imported.status_code == 200
    assert cleared.status_code == 200
    assert manager.import_memory.call_args.kwargs == {"user_id": "alice", "agent_name": "Research-Agent"}
    assert manager.clear_memory.call_args.kwargs == {"user_id": "alice", "agent_name": "Research-Agent"}


def test_scoped_fact_import_preserves_shared_summaries(tmp_path) -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    shared_memory = _sample_memory()
    shared_memory["user"]["workContext"] = {
        "summary": "Shared work context",
        "updatedAt": "2026-09-30T00:00:00Z",
    }
    shared_memory["history"]["recentMonths"] = {
        "summary": "Shared recent history",
        "updatedAt": "2026-09-30T00:00:00Z",
    }
    manager.import_memory(shared_memory, user_id="alice")
    fact_only_import = {
        "facts": [
            {
                "id": "fact-agent-a",
                "content": "Agent A preference",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-09-30T00:00:00Z",
                "source": "import",
            }
        ]
    }

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/memory/import?agent_name=agent-a",
            json=fact_only_import,
        )

    assert response.status_code == 200
    imported = response.json()
    assert [fact["id"] for fact in imported["facts"]] == ["fact-agent-a"]
    assert imported["user"]["workContext"]["summary"] == "Shared work context"
    assert imported["history"]["recentMonths"]["summary"] == "Shared recent history"


def test_scoped_import_export_and_clear_are_isolated_between_agent_buckets(tmp_path) -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    agent_a = _sample_memory(
        facts=[
            {
                "id": "fact-agent-a",
                "content": "Agent A preference",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "import",
            }
        ]
    )
    agent_b = _sample_memory(
        facts=[
            {
                "id": "fact-agent-b",
                "content": "Agent B preference",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "import",
            }
        ]
    )

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        assert client.post("/api/memory/import?agent_name=agent-a", json=agent_a).status_code == 200
        assert client.post("/api/memory/import?agent_name=agent-b", json=agent_b).status_code == 200
        exported_a = client.get("/api/memory/export?agent_name=agent-a")
        cleared_a = client.delete("/api/memory?agent_name=agent-a")
        exported_b = client.get("/api/memory/export?agent_name=agent-b")

    assert [fact["id"] for fact in exported_a.json()["facts"]] == ["fact-agent-a"]
    assert cleared_a.status_code == 200
    assert cleared_a.json()["facts"] == []
    assert [fact["id"] for fact in exported_b.json()["facts"]] == ["fact-agent-b"]


def test_scoped_management_rejects_backend_without_scope_capability() -> None:
    """A backend that ignores agent_name must not silently expose the default bucket."""
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = MagicMock()
    manager.supports_agent_scoped_management = False

    with patch("app.gateway.routers.memory.get_memory_manager", return_value=manager):
        with TestClient(app) as client:
            read_response = client.get("/api/memory?agent_name=research-agent")
            import_response = client.post("/api/memory/import?agent_name=research-agent", json=_sample_memory())
            clear_response = client.delete("/api/memory?agent_name=research-agent")

    assert read_response.status_code == 501
    assert import_response.status_code == 501
    assert clear_response.status_code == 501
    assert "agent-scoped management" in read_response.json()["detail"]
    manager.get_memory.assert_not_called()
    manager.import_memory.assert_not_called()
    manager.clear_memory.assert_not_called()


def test_scoped_memory_read_rejects_malformed_agent_name() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = MagicMock()
    manager.supports_agent_scoped_management = True

    with patch("app.gateway.routers.memory.get_memory_manager", return_value=manager):
        with TestClient(app) as client:
            response = client.get("/api/memory?agent_name=../other-user")

    assert response.status_code == 422
    manager.get_memory.assert_not_called()


def test_scoped_reload_fallback_reads_the_same_agent_bucket() -> None:
    """A backend without reload support must not lose scope on read fallback."""
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = MagicMock()
    manager.supports_agent_scoped_management = True
    manager.reload_memory.side_effect = NotImplementedError("no cache")
    manager.get_memory.return_value = _sample_memory()

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        response = client.post("/api/memory/reload?agent_name=Research-Agent")

    assert response.status_code == 200
    manager.reload_memory.assert_called_once_with(user_id="alice", agent_name="Research-Agent")
    manager.get_memory.assert_called_once_with(user_id="alice", agent_name="Research-Agent")


def test_create_memory_fact_route_maps_conflict_to_409() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.create_fact.side_effect = MemoryConflictError("stale write")

    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.post("/api/memory/facts", json={"content": "fact"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Memory changed concurrently; reload and retry."


def test_create_memory_fact_route_maps_duplicate_to_409() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.create_fact.side_effect = ValueError("Duplicate fact")

    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.post("/api/memory/facts", json={"content": "fact"})

    assert response.status_code == 409
    assert response.json()["detail"] == "A fact with the same content already exists."


def test_get_memory_route_maps_corruption_to_stable_500() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.get_memory.side_effect = MemoryCorruptionError("private path and parser detail")

    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.get("/api/memory")

    assert response.status_code == 500
    assert response.json()["detail"] == "Stored memory data is corrupted."


def test_delete_memory_fact_route_returns_updated_memory() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    updated_memory = _sample_memory(facts=[{"id": "fact_keep", "content": "User likes Python", "category": "preference", "confidence": 0.9, "createdAt": "2026-03-20T00:00:00Z", "source": "thread-1"}])

    mock_mgr = MagicMock()
    mock_mgr.delete_fact.return_value = updated_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.delete("/api/memory/facts/fact_delete")
    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_delete_memory_fact_route_returns_404_for_missing_fact() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.delete_fact.side_effect = KeyError("fact_missing")
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.delete("/api/memory/facts/fact_missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "Memory fact 'fact_missing' not found."


def test_update_memory_fact_route_returns_updated_memory() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    updated_memory = _sample_memory(facts=[{"id": "fact_edit", "content": "User prefers spaces", "category": "workflow", "confidence": 0.91, "createdAt": "2026-03-20T00:00:00Z", "source": "manual"}])

    mock_mgr = MagicMock()
    mock_mgr.update_fact.return_value = updated_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.patch("/api/memory/facts/fact_edit", json={"content": "User prefers spaces", "category": "workflow", "confidence": 0.91})
    assert response.status_code == 200
    assert response.json()["facts"] == updated_memory["facts"]


def test_settings_fact_crud_without_agent_name_uses_default_agent(tmp_path) -> None:
    """The current Settings API sends no agent_name; it must remain usable."""
    app = make_authed_test_app()
    app.include_router(memory.router)
    memory_path = tmp_path / "users" / "alice" / "memory.json"
    memory_path.parent.mkdir(parents=True)
    legacy = _sample_memory(
        facts=[
            {
                "id": "fact_legacy",
                "content": "Legacy global fact",
                "category": "context",
                "confidence": 0.9,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )
    memory_path.write_text(json.dumps(legacy), encoding="utf-8")
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        fetched = client.get("/api/memory")
        assert fetched.status_code == 200
        assert [fact["content"] for fact in fetched.json()["facts"]] == ["Legacy global fact"]

        exported = client.get("/api/memory/export")
        assert exported.status_code == 200
        assert [fact["content"] for fact in exported.json()["facts"]] == ["Legacy global fact"]

        created = client.post("/api/memory/facts", json={"content": "Project uses Python", "category": "context", "confidence": 0.8})
        assert created.status_code == 200
        assert all(isinstance(fact["source"], str) for fact in created.json()["facts"])
        fact_id = next(fact["id"] for fact in created.json()["facts"] if fact["content"] == "Project uses Python")

        updated = client.patch(f"/api/memory/facts/{fact_id}", json={"content": "Project uses Python 3.12"})
        assert updated.status_code == 200
        assert updated.json()["facts"][0]["content"] == "Project uses Python 3.12"

        deleted = client.delete(f"/api/memory/facts/{fact_id}")
        assert deleted.status_code == 200
        assert [fact["id"] for fact in deleted.json()["facts"]] == ["fact_legacy"]

        deleted_legacy = client.delete("/api/memory/facts/fact_legacy")
        assert deleted_legacy.status_code == 200
        assert deleted_legacy.json()["facts"] == []

    facts_root = tmp_path / "users" / "alice" / "agents" / "__default__" / "facts"
    assert facts_root.exists()
    assert not list(facts_root.glob("**/*.md"))
    assert "facts" not in json.loads(memory_path.read_text(encoding="utf-8"))


def test_scoped_fact_mutation_does_not_cross_agent_bucket_with_same_fact_id(
    tmp_path,
) -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    shared_id = "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"
    agent_a = _sample_memory(
        facts=[
            {
                "id": shared_id,
                "content": "Agent A original",
                "category": "context",
                "confidence": 0.8,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )
    agent_b = _sample_memory(
        facts=[
            {
                "id": shared_id,
                "content": "Agent B original",
                "category": "context",
                "confidence": 0.8,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )
    manager.import_memory(agent_a, user_id="alice", agent_name="agent-a")
    manager.import_memory(agent_b, user_id="alice", agent_name="agent-b")

    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        response = client.patch(
            f"/api/memory/facts/{shared_id}?agent_name=agent-a",
            json={"content": "Agent A updated"},
        )

    assert response.status_code == 200
    assert manager.get_memory(user_id="alice", agent_name="agent-a")["facts"][0]["content"] == "Agent A updated"
    assert manager.get_memory(user_id="alice", agent_name="agent-b")["facts"][0]["content"] == "Agent B original"


def test_update_memory_fact_route_preserves_omitted_fields() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    updated_memory = _sample_memory(facts=[{"id": "fact_edit", "content": "User prefers spaces", "category": "preference", "confidence": 0.8, "createdAt": "2026-03-20T00:00:00Z", "source": "manual"}])

    mock_mgr = MagicMock()
    mock_mgr.update_fact.return_value = updated_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.patch("/api/memory/facts/fact_edit", json={"content": "User prefers spaces"})
    assert response.status_code == 200
    # The router calls _require_capability("update_fact") -> getattr(mgr, "update_fact")
    # which returns mock_mgr.update_fact (a MagicMock).  Then the call is
    #   update_fact(fact_id=..., content=..., category=..., confidence=..., user_id=...)
    mock_mgr.update_fact.assert_called_once()
    call_kwargs = mock_mgr.update_fact.call_args.kwargs
    assert call_kwargs.get("fact_id") == "fact_edit"
    assert call_kwargs.get("content") == "User prefers spaces"
    assert call_kwargs.get("category") is None
    assert call_kwargs.get("confidence") is None
    assert "user_id" in call_kwargs
    assert response.json()["facts"] == updated_memory["facts"]


def test_update_memory_fact_route_returns_404_for_missing_fact() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.update_fact.side_effect = KeyError("fact_missing")
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.patch("/api/memory/facts/fact_missing", json={"content": "User prefers spaces", "category": "workflow", "confidence": 0.91})
    assert response.status_code == 404
    assert response.json()["detail"] == "Memory fact 'fact_missing' not found."


def test_update_memory_fact_route_returns_specific_error_for_invalid_confidence() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    mock_mgr = MagicMock()
    mock_mgr.update_fact.side_effect = ValueError("confidence")
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with TestClient(app) as client:
            response = client.patch("/api/memory/facts/fact_edit", json={"content": "User prefers spaces", "confidence": 0.91})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid confidence value; must be between 0 and 1."


# ── bound-owner (internal caller) ──────────────────────────────────────────


def _internal_owner_request(owner_user_id: str) -> SimpleNamespace:
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    return SimpleNamespace(
        headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: owner_user_id},
        state=SimpleNamespace(user=SimpleNamespace(id=DEFAULT_USER_ID, system_role=INTERNAL_SYSTEM_ROLE)),
    )


def test_get_memory_honors_bound_owner_header() -> None:
    seen: dict[str, str] = {}

    def fake_get_memory(*, user_id: str) -> dict:
        seen["user_id"] = user_id
        return _sample_memory(facts=[{"id": "f", "content": "owner fact", "category": "context", "confidence": 0.9, "createdAt": "", "source": "owner"}])

    mock_mgr = MagicMock()
    mock_mgr.get_memory.side_effect = fake_get_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        response = asyncio.run(call_unwrapped(memory.get_memory, _internal_owner_request("owner-1")))
    assert seen["user_id"] == "owner-1"
    assert response.facts[0].content == "owner fact"


def test_get_memory_sanitizes_unsafe_owner_header() -> None:
    from deerflow.config.paths import make_safe_user_id

    raw_owner = "feishu|ou_AbC/123"
    seen: dict[str, str] = {}

    def fake_get_memory(*, user_id: str) -> dict:
        seen["user_id"] = user_id
        return _sample_memory()

    mock_mgr = MagicMock()
    mock_mgr.get_memory.side_effect = fake_get_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        asyncio.run(call_unwrapped(memory.get_memory, _internal_owner_request(raw_owner)))
    expected = make_safe_user_id(raw_owner)
    assert seen["user_id"] == expected
    assert seen["user_id"] != raw_owner


def test_get_memory_falls_back_to_effective_user_for_browser_requests() -> None:
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    seen: dict[str, str] = {}

    def fake_get_memory(*, user_id: str) -> dict:
        seen["user_id"] = user_id
        return _sample_memory()

    browser_request = SimpleNamespace(
        headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
        state=SimpleNamespace(user=SimpleNamespace(id="real-user", system_role="user")),
    )

    mock_mgr = MagicMock()
    mock_mgr.get_memory.side_effect = fake_get_memory
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        with patch("app.gateway.routers.memory.get_effective_user_id", return_value="real-user"):
            asyncio.run(call_unwrapped(memory.get_memory, browser_request))
    assert seen["user_id"] == "real-user"


def _browser_request_with_spoofed_owner_header() -> SimpleNamespace:
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME

    return SimpleNamespace(
        headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
        state=SimpleNamespace(user=SimpleNamespace(id="real-user", system_role="user")),
    )


def test_clear_memory_scopes_destructive_write_to_bound_owner() -> None:
    seen: dict[str, str] = {}

    def fake_clear(*, user_id: str) -> dict:
        seen["user_id"] = user_id
        return _sample_memory()

    mock_mgr = MagicMock()
    mock_mgr.clear_memory.side_effect = fake_clear
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        asyncio.run(call_unwrapped(memory.clear_memory, _internal_owner_request("owner-1")))
        assert seen["user_id"] == "owner-1"

        with patch("app.gateway.routers.memory.get_effective_user_id", return_value="real-user"):
            asyncio.run(call_unwrapped(memory.clear_memory, _browser_request_with_spoofed_owner_header()))
        assert seen["user_id"] == "real-user"


def test_import_memory_scopes_overwrite_to_bound_owner() -> None:
    seen: dict[str, str] = {}
    payload = memory.MemoryResponse(**_sample_memory())

    def fake_import(_data: dict, *, user_id: str) -> dict:
        seen["user_id"] = user_id
        return _sample_memory()

    mock_mgr = MagicMock()
    mock_mgr.import_memory.side_effect = fake_import
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=mock_mgr):
        asyncio.run(call_unwrapped(memory.import_memory, payload, _internal_owner_request("owner-1")))
        assert seen["user_id"] == "owner-1"

        with patch("app.gateway.routers.memory.get_effective_user_id", return_value="real-user"):
            asyncio.run(call_unwrapped(memory.import_memory, payload, _browser_request_with_spoofed_owner_header()))
        assert seen["user_id"] == "real-user"


# ── unsupported-backend 501s ────────────────────────────────────────────────
# A minimal backend (only add + get_context) inherits the tier-2/tier-3 default
# raise for get_memory / clear_memory / import_memory / reload_memory. Before
# the contract change these were @abstractmethod (every backend implemented
# them, so the endpoints could never raise); now the endpoints catch
# NotImplementedError -> 501 so an unsupported backend gets a clean "not
# supported" instead of a raw 500 (there is no global NotImplementedError
# handler, so an uncaught raise is a 500).


def _unsupported_manager() -> MagicMock:
    """Mock a minimal backend: read/manage ops raise NotImplementedError."""
    mock_mgr = MagicMock()
    mock_mgr.get_memory.side_effect = NotImplementedError("get_memory not supported")
    mock_mgr.clear_memory.side_effect = NotImplementedError("clear_memory not supported")
    mock_mgr.import_memory.side_effect = NotImplementedError("import_memory not supported")
    mock_mgr.reload_memory.side_effect = NotImplementedError("reload_memory not supported")
    return mock_mgr


def test_get_memory_route_returns_501_for_unsupported_backend() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=_unsupported_manager()):
        with TestClient(app) as client:
            response = client.get("/api/memory")
    assert response.status_code == 501
    assert "not supported" in response.json()["detail"]


def test_export_memory_route_returns_501_for_unsupported_backend() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=_unsupported_manager()):
        with TestClient(app) as client:
            response = client.get("/api/memory/export")
    assert response.status_code == 501


def test_memory_status_route_returns_501_for_unsupported_backend() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    cfg = SimpleNamespace(
        enabled=True,
        mode="middleware",
        injection_enabled=True,
        shutdown_flush_timeout_seconds=30.0,
        manager_class="minimal",
        backend_config={},
    )
    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=_unsupported_manager()),
        patch("app.gateway.routers.memory.get_memory_config", return_value=cfg),
    ):
        with TestClient(app) as client:
            response = client.get("/api/memory/status")
    assert response.status_code == 501


def test_clear_memory_route_returns_501_for_unsupported_backend() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=_unsupported_manager()):
        with TestClient(app) as client:
            response = client.delete("/api/memory")
    assert response.status_code == 501


def test_import_memory_route_returns_501_for_unsupported_backend() -> None:
    app = make_authed_test_app()
    app.include_router(memory.router)
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=_unsupported_manager()):
        with TestClient(app) as client:
            response = client.post("/api/memory/import", json=_sample_memory())
    assert response.status_code == 501


def test_reload_memory_route_returns_501_when_read_also_unsupported() -> None:
    """reload falls back to get_memory; if both raise (minimal backend), the
    fallback surfaces 501 instead of a raw 500 from the uncaught raise."""
    app = make_authed_test_app()
    app.include_router(memory.router)
    with patch("app.gateway.routers.memory.get_memory_manager", return_value=_unsupported_manager()):
        with TestClient(app) as client:
            response = client.post("/api/memory/reload")
    assert response.status_code == 501


def test_import_blank_fact_returns_400_without_replacing_saved_memory(tmp_path):
    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    before = manager.import_memory(_sample_memory(facts=[{"id": "keep", "content": "Saved preference"}]), user_id="alice")
    payload = _sample_memory(facts=[{**before["facts"][0], "content": "   "}])
    app = make_authed_test_app()
    app.include_router(memory.router)
    with (
        patch("app.gateway.routers.memory.get_memory_manager", return_value=manager),
        patch("app.gateway.routers.memory.get_effective_user_id", return_value="alice"),
        TestClient(app) as client,
    ):
        response = client.post("/api/memory/import", json=payload)
    assert response.status_code == 400
    assert manager.get_memory(user_id="alice") == before
