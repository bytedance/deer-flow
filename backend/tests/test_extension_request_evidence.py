"""Request evidence access through real contributed routes and host auth."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from deerflow_extension_api import InvalidRunEvidenceCursor, require_run_evidence_reader, resolve_run_evidence_reader
from fastapi import APIRouter, HTTPException, Request

from deerflow.extensions.run_evidence import StoreRunEvidenceReader, StoreRunEvidenceReaderFactory
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest.fixture
def evidence_app(monkeypatch):
    import app.gateway.app as app_module
    import deerflow.extensions as extensions
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.extensions.registry import ExtensionRegistry

    monkeypatch.setattr(app_module, "get_app_config", lambda: AppConfig(sandbox=SandboxConfig(use="test")))
    monkeypatch.setattr("app.gateway.auth_middleware.is_auth_disabled", lambda: False)

    async def authenticate(request):
        return SimpleNamespace(id=request.cookies["access_token"], system_role="admin")

    async def permissions(user, **kwargs):
        return [] if user.id == "denied" else ["runs:read"]

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", authenticate)
    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", permissions)
    router = APIRouter()

    @router.get("/api/evidence-test")
    async def evidence(request: Request, thread_id: str = "thread-a", run_id: str = "run-a", cursor: str | None = None):
        try:
            reader = require_run_evidence_reader(request)
            await asyncio.sleep(0)
            status = await reader.get_run_status(thread_id=thread_id, run_id=run_id)
            events = await reader.list_run_events(thread_id=thread_id, run_id=run_id, after_seq=None, limit=10)
            changed = await reader.list_changed_runs(cursor=cursor, limit=10)
            return {"status": asdict(status) if status else None, "events": asdict(events), "changed": asdict(changed)}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except NotImplementedError as exc:
            raise HTTPException(503, str(exc)) from exc
        except InvalidRunEvidenceCursor as exc:
            raise HTTPException(400, str(exc)) from exc

    registry = ExtensionRegistry()
    with registry.attributed_to("evidence:install"):
        registry.routers((router,))
    monkeypatch.setattr(extensions, "load_extensions", lambda plugins: (registry.build(), []))
    app = app_module.create_app()
    app.state.run_store = MemoryRunStore()
    app.state.run_event_store = MemoryRunEventStore()
    app.state.run_evidence_reader_factory = StoreRunEvidenceReaderFactory(app.state.run_store, app.state.run_event_store)
    yield app
    extensions.reset_loaded_extensions()
    extensions.reset_runtime_diagnostics()


@pytest.mark.parametrize("state", [SimpleNamespace(), SimpleNamespace(user=SimpleNamespace(id="a", system_role="admin"))])
def test_resolver_rejects_missing_auth_context(evidence_app, state):
    request = SimpleNamespace(app=evidence_app, state=state)
    with pytest.raises(PermissionError):
        require_run_evidence_reader(request)


def test_resolver_failure_does_not_return_a_global_reader():
    def fail(request):
        raise RuntimeError("resolver failed")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(deerflow_extension_run_evidence_reader_resolver=fail)))
    with pytest.raises(RuntimeError, match="resolver failed"):
        resolve_run_evidence_reader(request)


@pytest.mark.asyncio
async def test_route_scope_cursor_and_concurrent_requests(evidence_app):
    app = evidence_app
    for owner in ("a", "b"):
        await app.state.run_store.put(f"run-{owner}", thread_id=f"thread-{owner}", user_id=owner)
        await app.state.run_event_store.put(thread_id=f"thread-{owner}", run_id=f"run-{owner}", event_type="test", category="message", content=owner)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:

        async def read(owner, **params):
            return await client.get("/api/evidence-test", headers={"cookie": f"access_token={owner}"}, params=params)

        a, b = await asyncio.gather(read("a", user_id="b"), read("b"))
        assert a.status_code == b.status_code == 200
        assert a.json()["status"]["run_id"] == "run-a"
        assert a.json()["events"]["items"][0]["content"] == "a"
        assert [item["run_id"] for item in b.json()["changed"]["items"]] == ["run-b"]
        assert b.json()["status"] is None
        assert b.json()["events"]["items"] == []
        missing = await read("b", run_id="missing")
        assert missing.json() == b.json()
        assert (await read("b", cursor=a.json()["changed"]["next_cursor"])).status_code == 400
        assert (await read("denied")).status_code == 403
        assert (await client.get("/api/evidence-test")).status_code == 401
        del app.state.run_evidence_reader_factory
        assert (await read("a")).status_code == 503

    global_reader = StoreRunEvidenceReader(app.state.run_store, app.state.run_event_store)
    assert len((await global_reader.list_changed_runs(cursor=None, limit=10)).items) == 2
