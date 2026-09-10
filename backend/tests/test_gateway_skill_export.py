"""Real archive/router contracts; auth is stamped only for this isolated test app."""

import asyncio
import threading
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from app.gateway import skill_export as service
from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills
from deerflow.skills.export import SkillExportArchive
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


@pytest.fixture
def app(tmp_path, monkeypatch):
    from deerflow.config import paths

    monkeypatch.setattr(paths, "_paths", paths.Paths(base_dir=tmp_path / "home"))
    stores = {u: UserScopedSkillStorage(u, host_path=str(tmp_path / "skills")) for u in ("alice", "bob")}
    for u, store in stores.items():
        root = store.get_custom_skill_dir("demo")
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(f"---\nname: demo\ndescription: {u}\n---\n{u}", encoding="utf-8")
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        if request.headers.get("x-role") != "anonymous":
            request.state.user = User(id=uuid4(), email="test@example.com", password_hash="x", system_role=request.headers.get("x-role", "admin"))
        request.state.auth_source = request.headers.get("x-auth-source")
        return await call_next(request)

    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    monkeypatch.setattr(skills, "_get_user_skill_storage", lambda _: stores["alice"])
    app.include_router(skills.router)
    app.state.stores = stores
    return app


def test_manifest_download_and_changed_revision(app):
    with TestClient(app) as client:
        preview = client.get("/api/skills/custom/demo/export-manifest")
        assert preview.status_code == 200, preview.text
        manifest = preview.json()
        assert manifest["can_export"]
        url = "/api/skills/custom/demo/export?expected_revision=" + manifest["revision"]
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["content-disposition"] == 'attachment; filename="demo.skill"'
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert int(response.headers["content-length"]) == len(response.content)
        with ZipFile(BytesIO(response.content)) as archive:
            assert archive.read("demo/SKILL.md").endswith(b"alice")
        (app.state.stores["alice"].get_custom_skill_dir("demo") / "extra.txt").write_bytes(b"new")
        stale = client.get(url)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "skill_changed"
        assert "content-disposition" not in stale.headers
        assert client.get("/api/skills/custom/demo/export").status_code == 422
        assert client.get("/api/skills/custom/demo/export?expected_revision=bad").status_code == 422


@pytest.mark.parametrize("headers,status", [({"x-role": "user"}, 403), ({"x-auth-source": "pat"}, 403), ({"x-role": "anonymous"}, 401)])
def test_auth_before_storage(app, monkeypatch, headers, status):
    monkeypatch.setattr(skills, "_get_user_skill_storage", lambda _: pytest.fail("storage reached without admin"))
    with TestClient(app) as client:
        for suffix in ("export-manifest", "export?expected_revision=" + "a" * 64):
            assert client.get("/api/skills/custom/demo/" + suffix, headers=headers).status_code == status


@pytest.mark.asyncio
async def test_slot_held_until_response_finishes_and_send_failure_closes():
    file = BytesIO(b"zip")
    lease = service.ExportLease.acquire()
    response = service.SkillExportResponse(SkillExportArchive(file, 3), "demo", lease)
    second = service.ExportLease.acquire()
    with pytest.raises(Exception) as error:
        service.ExportLease.acquire()
    assert error.value.status_code == 429

    async def send(_):
        raise OSError("client disconnected")

    async def receive():
        await asyncio.Event().wait()

    try:
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert file.closed
        third = service.ExportLease.acquire()
        third.release()
    finally:
        second.release()
        lease.release()


@pytest.mark.asyncio
async def test_cancel_drains_worker_and_closes_unclaimed_archive():
    started, finish = threading.Event(), threading.Event()
    file = BytesIO(b"zip")

    def work(cancel_event):
        started.set()
        finish.wait(3)
        assert cancel_event.is_set()
        return SkillExportArchive(file, 3)

    task = asyncio.create_task(service.run_export_work(work))
    while not started.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert file.closed
    leases = [service.ExportLease.acquire(), service.ExportLease.acquire()]
    for lease in leases:
        lease.release()


def test_same_name_stays_in_current_user_and_missing_does_not_fall_back(app, monkeypatch):
    with TestClient(app) as client:
        alice = client.get("/api/skills/custom/demo/export-manifest").json()
        monkeypatch.setattr(skills, "_get_user_skill_storage", lambda _: app.state.stores["bob"])
        bob = client.get("/api/skills/custom/demo/export-manifest").json()
        assert bob["revision"] != alice["revision"]
        assert client.get("/api/skills/custom/demo/export?expected_revision=" + alice["revision"]).status_code == 409
        assert client.get("/api/skills/custom/missing/export-manifest").status_code == 404


def test_busy_and_unexpected_errors_keep_safe_response(app, monkeypatch):
    with TestClient(app) as client:
        leases = [service.ExportLease.acquire(), service.ExportLease.acquire()]
        try:
            response = client.get("/api/skills/custom/demo/export-manifest")
            assert response.status_code == 429
            assert response.json()["detail"]["code"] == "skill_export_busy"
        finally:
            for lease in leases:
                lease.release()

        def failure(*args):
            raise OSError("secret content at /host/private/path")

        monkeypatch.setattr(skills, "export_manifest", failure)
        response = client.get("/api/skills/custom/demo/export-manifest")
        assert response.status_code == 500
        assert "secret" not in response.text and "/host/" not in response.text
        leases = [service.ExportLease.acquire(), service.ExportLease.acquire()]
        for lease in leases:
            lease.release()


@pytest.mark.asyncio
async def test_client_disconnect_signals_worker_and_preserves_user_context():
    from contextvars import ContextVar

    from starlette.requests import Request

    owner = ContextVar("export_test_owner", default="wrong")
    token = owner.set("alice")
    started = threading.Event()
    disconnected = asyncio.Event()

    def work(cancel):
        assert owner.get() == "alice"
        started.set()
        assert cancel.wait(3)
        raise RuntimeError("cancelled")

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    task = asyncio.create_task(service.run_export_work(work, Request({"type": "http"}, receive)))
    try:
        while not started.is_set():
            await asyncio.sleep(0.01)
        disconnected.set()
        with pytest.raises(service.ExportClientDisconnected):
            await task
        leases = [service.ExportLease.acquire(), service.ExportLease.acquire()]
        for lease in leases:
            lease.release()
    finally:
        owner.reset(token)


def test_export_upload_roundtrip_uses_existing_scanner_and_rejects_conflict(app, monkeypatch):
    """Actual public skill, production routes/scanner; only remote model decision stubbed."""
    import shutil
    from pathlib import Path

    from deerflow.skills.security_scanner import ScanResult

    source = Path(__file__).resolve().parents[2] / "skills/public/data-analysis"
    alice = app.state.stores["alice"]
    bob = app.state.stores["bob"]
    shutil.copytree(source, alice.get_custom_skill_dir("data-analysis"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    scanned = []

    async def scan(content, *, executable, location, **kwargs):
        scanned.append(location)
        return ScanResult(decision="allow", reason="Offline remote-model stub")

    async def refresh(_):
        pass

    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", scan)
    monkeypatch.setattr(skills, "refresh_user_skills_system_prompt_cache_async", refresh)
    with TestClient(app) as client:
        manifest = client.get("/api/skills/custom/data-analysis/export-manifest").json()
        archive = client.get("/api/skills/custom/data-analysis/export?expected_revision=" + manifest["revision"])
        assert archive.status_code == 200
        monkeypatch.setattr(skills, "_get_user_skill_storage", lambda _: bob)
        response = client.post("/api/skills/install/upload", files={"archive": ("data-analysis.skill", archive.content, "application/zip")})
        assert response.status_code == 200, response.text
        assert scanned, "Exported files must not bypass the normal import scanner"
        for path in source.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                assert (bob.get_custom_skill_dir("data-analysis") / path.relative_to(source)).read_bytes() == path.read_bytes()
        conflict = client.post("/api/skills/install/upload", files={"archive": ("data-analysis.skill", archive.content, "application/zip")})
        assert conflict.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["export-manifest", "export?expected_revision=" + "a" * 64])
async def test_disconnect_exits_router_without_asgi_error(app, monkeypatch, suffix):
    started = threading.Event()

    def work(*args):
        started.set()
        assert args[-1].wait(3)
        raise RuntimeError("worker cancelled")

    async def receive():
        while not started.is_set():
            await asyncio.sleep(0.001)
        return {"type": "http.disconnect"}

    async def admin(*args, **kwargs):
        pass

    monkeypatch.setattr(skills, "require_admin_user", admin)
    monkeypatch.setattr(skills, "export_manifest", work)
    monkeypatch.setattr(skills, "build_skill_export", work)
    plain_app = FastAPI()
    plain_app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    plain_app.include_router(skills.router)
    path, _, query = ("/api/skills/custom/demo/" + suffix).partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1", "method": "GET", "scheme": "http", "path": path, "query_string": query.encode(), "headers": []}
    messages = []

    async def send(message):
        messages.append(message)

    await plain_app(scope, receive, send)
    assert messages[0]["status"] == 204
    leases = [service.ExportLease.acquire(), service.ExportLease.acquire()]
    for lease in leases:
        lease.release()


@pytest.mark.asyncio
async def test_stalled_transfer_has_deadline_and_releases_archive_and_slot(monkeypatch):
    monkeypatch.setattr(service, "TRANSFER_TIMEOUT_SECONDS", 0.02, raising=False)
    file = BytesIO(b"zip")
    lease = service.ExportLease.acquire()
    response = service.SkillExportResponse(SkillExportArchive(file, 3), "demo", lease)
    body_started = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            body_started.set()
            await asyncio.Event().wait()

    async def receive():
        await asyncio.Event().wait()

    task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
    try:
        await asyncio.wait_for(body_started.wait(), 1)
        with pytest.raises(ClientDisconnect):
            await asyncio.wait_for(asyncio.shield(task), 0.5)
        assert file.closed
        leases = [service.ExportLease.acquire(), service.ExportLease.acquire()]
        for acquired in leases:
            acquired.release()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_manifest_openapi_has_nested_response_contract(app):
    schema = app.openapi()
    response = schema["paths"]["/api/skills/custom/{skill_name}/export-manifest"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    model = schema["components"]["schemas"][response["$ref"].rsplit("/", 1)[-1]]
    assert set(model["required"]) == {"skill_name", "revision", "can_export", "file_count", "directory_count", "total_bytes", "files", "requirements", "warnings", "blockers"}
    for field in ("files", "warnings", "blockers"):
        assert "$ref" in model["properties"][field]["items"]
    assert "$ref" in model["properties"]["requirements"]
