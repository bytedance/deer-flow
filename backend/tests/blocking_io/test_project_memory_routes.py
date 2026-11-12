"""Every project-memory route offloads its synchronous repository work."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
import test_project_memory as memory_tests
from _router_auth_helpers import call_unwrapped

from app.gateway.routers import projects
from deerflow.config.projects_config import ProjectsConfig


@pytest.fixture
def repo(tmp_path):
    yield from memory_tests.repo.__wrapped__(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "set_enabled", "delete", "promote"])
async def test_memory_routes_keep_repository_io_off_the_loop(repo, tmp_path, monkeypatch, operation):
    await asyncio.to_thread(repo.apply, "p1", "u1", "t1", 0, {"newFacts": [memory_tests.fact()]})
    state = await asyncio.to_thread(repo.get, "p1", "u1")
    fact_id = state["facts"][0]["id"]
    marker = tmp_path / "repository-io.txt"
    await asyncio.to_thread(marker.write_text, "worker read", encoding="utf-8")
    loop_thread = threading.get_ident()
    original = getattr(repo, operation)
    calls = []

    def observed(*args, **kwargs):
        # The strict detector catches this real read if either offload is removed.
        assert marker.read_text(encoding="utf-8") == "worker read"
        assert threading.get_ident() != loop_thread
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, operation, observed)
    monkeypatch.setattr(projects, "get_project_memory_repository", lambda: repo)
    monkeypatch.setattr(projects, "get_effective_user_id", lambda: "u1")
    monkeypatch.setattr(projects, "_projects_config", ProjectsConfig)
    request = SimpleNamespace()
    if operation == "get":
        result = await call_unwrapped(projects.get_project_memory, "p1", request)
        assert result.facts[0].id == fact_id
    elif operation == "set_enabled":
        result = await call_unwrapped(projects.patch_project_memory, "p1", projects.ProjectMemoryPatch(enabled=False), request)
        assert result.enabled is False
    elif operation == "delete":
        result = await call_unwrapped(projects.delete_project_memory, "p1", fact_id, request)
        assert result.facts == []
    else:
        result = await call_unwrapped(projects.promote_project_memory, "p1", fact_id, projects.ProjectMemoryPromotion(expected_instructions=""), request)
        assert result.instructions == "- Reports exclude tax"
        assert result.memory.facts == []
    assert len(calls) == 1
    assert calls[0][:2] == ("p1", "u1")
