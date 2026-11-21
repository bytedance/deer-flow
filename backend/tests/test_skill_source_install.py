from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.gateway import skill_source
from app.gateway.auth.models import User
from app.gateway.authz import AuthContext
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router
from app.gateway.skill_source import (
    PreparedSkillSource,
    SkillSourceError,
    SnapshotFile,
    _fetch_snapshot_payload,
    _parse_snapshot,
    _prepare_snapshot,
    _SourceRateLimiter,
    compute_snapshot_digest,
    parse_skill_source,
)
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.skills.security_scanner import ScanResult
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import SkillCategory

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_SOURCE = "vercel-labs/skills@find-skills"
_SKILL_MD = "---\nname: find-skills\ndescription: Find useful skills.\n---\n\n# Find skills\n"


def _payload(files: list[dict] | None = None, **overrides) -> dict:
    payload = {
        "id": "vercel-labs/skills/find-skills",
        "source": "vercel-labs/skills",
        "slug": "find-skills",
        "hash": "upstream-hash",
        "files": files if files is not None else [{"path": "SKILL.md", "contents": _SKILL_MD}],
    }
    payload.update(overrides)
    return payload


def _config(*, static: bool = False):
    return SimpleNamespace(skill_scan=SimpleNamespace(enabled=static), authorization=AuthorizationConfig(enabled=False))


def _make_user(role: str = "admin") -> User:
    return User(email=f"{role}@example.com", password_hash="x", system_role=role, id=uuid4())


def _make_app(config, *, permissions: list[str] | None = None) -> FastAPI:
    app = FastAPI()
    user = _make_user("admin" if permissions is None else "user")
    granted = ["skills:manage"] if permissions is None else permissions

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.user = user
        request.state.auth = AuthContext(user=user, permissions=granted)
        return await call_next(request)

    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


def _mock_upstream(monkeypatch, handler, constructor_calls: list[dict] | None = None) -> None:
    transport = httpx.MockTransport(handler)

    def _client(**kwargs):
        if constructor_calls is not None:
            constructor_calls.append(kwargs)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(skill_source.httpx, "AsyncClient", _client)


def _success_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_payload())


def test_source_parser_normalizes_and_maps_fixed_api_path():
    parsed = parse_skill_source("Vercel-Labs/Skills@Find-Skills")
    assert parsed.source == "vercel-labs/skills"
    assert parsed.slug == "find-skills"
    assert parsed.id == "vercel-labs/skills/find-skills"
    assert parsed.api_url == "https://skills.sh/api/v1/skills/vercel-labs/skills/find-skills"


@pytest.mark.parametrize(
    "source",
    [
        "",
        "owner/repo",
        "owner/repo@skill@extra",
        "https://owner/repo@skill",
        "owner/repo/name@skill",
        "owner\\repo@skill",
        "owner/repo@skill?x=1",
        "owner/repo@skill#x",
        "owner/repo@bad skill",
        " owner/repo@skill",
        "owner/re..po@skill",
        "-owner/repo@skill",
        "owner-/repo@skill",
        "owner/repo@skill\n",
        "owner/repo@skill\x00",
        "o/r@s" + "x" * 256,
    ],
)
def test_source_parser_rejects_invalid_identifiers(source):
    with pytest.raises(SkillSourceError) as caught:
        parse_skill_source(source)
    assert caught.value.code == "skill_source_invalid"
    assert caught.value.status_code == 400


def test_snapshot_digest_is_unambiguous_order_independent_and_length_sensitive():
    first = [SnapshotFile("a", b"bc"), SnapshotFile("ab", b"c")]
    assert compute_snapshot_digest(first[:1]) != compute_snapshot_digest(first[1:])
    assert compute_snapshot_digest(first) == compute_snapshot_digest(list(reversed(first)))
    assert compute_snapshot_digest(first) != compute_snapshot_digest([SnapshotFile("a", b"b"), SnapshotFile("abc", b"c")])
    assert compute_snapshot_digest(first) != compute_snapshot_digest(first[:1])
    assert compute_snapshot_digest(first) != compute_snapshot_digest([SnapshotFile("a", b"bc"), SnapshotFile("ab", b"c"), SnapshotFile("x", b"")])


@pytest.mark.asyncio
async def test_oidc_header_is_reread_and_client_ignores_environment(monkeypatch):
    requests: list[httpx.Request] = []
    constructors: list[dict] = []

    def _handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    _mock_upstream(monkeypatch, _handler, constructors)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "first-token")
    await _fetch_snapshot_payload(parse_skill_source(_SOURCE), "user-1")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "rotated-token")
    await _fetch_snapshot_payload(parse_skill_source(_SOURCE), "user-1")

    assert [request.headers["authorization"] for request in requests] == ["Bearer first-token", "Bearer rotated-token"]
    assert all(str(request.url) == parse_skill_source(_SOURCE).api_url for request in requests)
    assert len(constructors) == 2
    assert all(call["trust_env"] is False and call["follow_redirects"] is False for call in constructors)
    assert all(call["timeout"].connect == 3 and call["timeout"].read == 15 for call in constructors)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "http_status"),
    [(401, "skill_source_auth_failed", 503), (403, "skill_source_auth_failed", 503), (404, "skill_source_not_found", 404), (500, "skill_source_unavailable", 503)],
)
async def test_upstream_status_errors_are_structured(monkeypatch, status, code, http_status):
    _mock_upstream(monkeypatch, lambda request: httpx.Response(status, text="secret upstream body"))
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    with pytest.raises(SkillSourceError) as caught:
        await _fetch_snapshot_payload(parse_skill_source(_SOURCE), "user-1")
    assert (caught.value.status_code, caught.value.code) == (http_status, code)
    assert "secret upstream body" not in caught.value.message


@pytest.mark.asyncio
async def test_upstream_retry_after_is_validated_and_forwarded(monkeypatch):
    retry = "Wed, 21 Nov 2026 12:00:00 GMT"
    _mock_upstream(monkeypatch, lambda request: httpx.Response(429, headers={"Retry-After": retry}))
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    with pytest.raises(SkillSourceError) as caught:
        await _fetch_snapshot_payload(parse_skill_source(_SOURCE), "user-1")
    assert caught.value.code == "skill_source_rate_limited"
    assert caught.value.retry_after == retry


@pytest.mark.asyncio
async def test_network_failure_maps_to_unavailable(monkeypatch):
    def _timeout(request):
        raise httpx.ConnectTimeout("slow upstream", request=request)

    _mock_upstream(monkeypatch, _timeout)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    with pytest.raises(SkillSourceError) as caught:
        await _fetch_snapshot_payload(parse_skill_source(_SOURCE), "user-1")
    assert caught.value.status_code == 503
    assert caught.value.code == "skill_source_unavailable"


@pytest.mark.asyncio
async def test_streaming_response_aborts_above_twelve_mib(monkeypatch):
    _mock_upstream(monkeypatch, lambda request: httpx.Response(200, content=b"x" * (12 * 1024 * 1024 + 1)))
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    with pytest.raises(SkillSourceError) as caught:
        await _fetch_snapshot_payload(parse_skill_source(_SOURCE), "user-1")
    assert caught.value.code == "skill_source_snapshot_unusable"
    assert "12 MiB" in caught.value.message


def test_snapshot_numeric_limits_and_identity_are_checked_before_install():
    reference = parse_skill_source(_SOURCE)
    with pytest.raises(SkillSourceError, match="too many files"):
        _parse_snapshot(reference, _payload(files=[{"path": f"{index}.txt", "contents": ""} for index in range(257)]))
    with pytest.raises(SkillSourceError, match="1 MiB"):
        _parse_snapshot(reference, _payload(files=[{"path": "large.txt", "contents": "x" * (1024 * 1024 + 1)}]))
    with pytest.raises(SkillSourceError, match="8 MiB"):
        _parse_snapshot(reference, _payload(files=[{"path": f"{index}.txt", "contents": "x" * (1024 * 1024)} for index in range(9)]))
    with pytest.raises(SkillSourceError, match="identity"):
        _parse_snapshot(reference, _payload(slug="other"))
    with pytest.raises(SkillSourceError, match="identity"):
        _parse_snapshot(reference, _payload(id="vercel-labs/skills/FIND-SKILLS"))
    accepted, _ = _parse_snapshot(reference, _payload(files=[{"path": f"{index}.txt", "contents": "x" * (1024 * 1024)} for index in range(8)]))
    assert sum(len(file.content) for file in accepted) == 8 * 1024 * 1024
    # GitHub owner/repository casing is insignificant; the slug is not.
    files, _ = _parse_snapshot(reference, _payload(source="Vercel-Labs/Skills", id="Vercel-Labs/Skills/find-skills"))
    assert files[0].path == "SKILL.md"


def test_official_contents_field_is_required():
    files, _ = _parse_snapshot(parse_skill_source(_SOURCE), _payload())
    assert files[0].content.decode("utf-8") == _SKILL_MD

    with pytest.raises(SkillSourceError) as caught:
        _parse_snapshot(parse_skill_source(_SOURCE), _payload(files=[{"path": "SKILL.md", "content": _SKILL_MD}]))
    assert caught.value.status_code == 422
    assert caught.value.code == "skill_source_snapshot_unusable"
    assert "contents" in caught.value.message


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "", "contents": "x"}], "must name a file"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "dir/", "contents": "x"}], "must name a file"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "nested/SKILL.md", "contents": _SKILL_MD}], "nested SKILL.md"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "scripts/run.sh:ads", "contents": "echo ok"}], "unsafe member path"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "scripts/CON.txt", "contents": "x"}], "portable to Windows"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "scripts/name. ", "contents": "x"}], "portable to Windows"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "a", "contents": "x"}, {"path": "a/b", "contents": "x"}], "conflict"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "scripts/run", "contents": "\x7fELFpayload"}], "executable binary"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "../escape", "contents": "x"}], "unsafe member path"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "/absolute", "contents": "x"}], "absolute"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "bad\x00name", "contents": "x"}], "NUL"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "x" * 256, "contents": "x"}], "segment is too long"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "/".join(["x"] * 35), "contents": "x"}], "too deep"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "/".join(["x" * 60] * 20), "contents": "x"}], "path is too long"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD}, {"path": "a//b", "contents": "x"}, {"path": "a/b", "contents": "y"}], "conflicting member paths"),
        ([{"path": "SKILL.md", "contents": _SKILL_MD.replace("description:", "unknown: 1\ndescription:")}], "Unexpected key"),
        ([{"path": "README.md", "contents": "missing root"}], "SKILL.md not found"),
    ],
)
def test_inspect_preflight_rejects_unsafe_or_incompatible_snapshots(files, message, tmp_path, monkeypatch):
    counter = iter(range(100))

    def _mkdtemp(prefix):
        path = tmp_path / f"source-{next(counter)}"
        path.mkdir()
        return str(path)

    monkeypatch.setattr(skill_source.tempfile, "mkdtemp", _mkdtemp)
    with pytest.raises(SkillSourceError) as caught:
        _prepare_snapshot(parse_skill_source(_SOURCE), _payload(files=files), app_config=_config())
    assert caught.value.code == "skill_source_snapshot_unusable"
    assert message in caught.value.message
    assert not (tmp_path / "source-0").exists()


def test_inspect_static_scan_returns_findings_and_cleans_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_source.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    payload = _payload(
        files=[
            {"path": "SKILL.md", "contents": _SKILL_MD},
            {"path": "scripts/run.py", "contents": "exec(user_input)\n"},
        ]
    )
    with pytest.raises(SkillSourceError) as caught:
        _prepare_snapshot(parse_skill_source(_SOURCE), payload, app_config=_config(static=True))
    assert caught.value.code == "skill_source_snapshot_unusable"
    assert any(finding["rule_id"] == "python-dynamic-exec" for finding in caught.value.findings)
    assert not tmp_path.exists()


@pytest.mark.asyncio
async def test_local_user_and_concurrency_limits_reject_without_queuing():
    limiter = _SourceRateLimiter()
    for _ in range(20):
        await limiter.acquire("user-1")
        limiter.release()
    with pytest.raises(SkillSourceError) as caught:
        await limiter.acquire("user-1")
    assert caught.value.code == "skill_source_rate_limited"
    assert caught.value.retry_after is not None
    local_http = skills_router._source_http_exception(caught.value)
    assert local_http.headers["Retry-After"] == caught.value.retry_after
    from app.gateway.csrf_middleware import CORS_EXPOSED_HEADERS

    assert "Retry-After" in CORS_EXPOSED_HEADERS

    other = _SourceRateLimiter()
    for _ in range(4):
        await other.acquire("user-2")
    with pytest.raises(SkillSourceError) as caught:
        await other.acquire("user-3")
    assert caught.value.retry_after == "1"
    for _ in range(4):
        other.release()


@pytest.mark.asyncio
async def test_source_limiter_prunes_stale_users_and_releases_on_cancellation(monkeypatch):
    limiter = _SourceRateLimiter()
    now = 0.0
    monkeypatch.setattr(skill_source.time, "monotonic", lambda: now)
    await limiter.acquire("stale-user")
    limiter.release()
    now = 61.0
    await limiter.acquire("new-user")
    limiter.release()
    assert "stale-user" not in limiter._requests

    monkeypatch.setattr(skill_source, "_source_rate_limiter", limiter)
    started = asyncio.Event()

    async def hold():
        async with skill_source._upstream_request_slot("cancel-user"):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert limiter._active == 0


def test_source_routes_envelope_missing_credentials_and_denied_permission(monkeypatch):
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    with TestClient(_make_app(_config())) as client:
        response = client.post("/api/skills/install/source/inspect", json={"source": _SOURCE})
        invalid = client.post("/api/skills/install/source/inspect", json={"source": "https://github.com/owner/repo@skill"})
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "skill_source_not_configured", "message": "This deployment does not have skills.sh credentials."}
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "skill_source_invalid"

    called = False

    def _unexpected(request):
        nonlocal called
        called = True
        return httpx.Response(500)

    _mock_upstream(monkeypatch, _unexpected)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    with TestClient(_make_app(_config(), permissions=[])) as client:
        denied = client.post("/api/skills/install/source/inspect", json={"source": _SOURCE})
        denied_install = client.post(
            "/api/skills/install/source",
            json={"source": _SOURCE, "expected_snapshot_digest": "0" * 64},
        )
    assert denied.status_code == 403
    assert denied_install.status_code == 403
    assert called is False


def test_denied_role_cannot_reach_any_owned_lifecycle_handler():
    with TestClient(_make_app(_config(), permissions=[])) as client:
        requests = [
            client.post("/api/skills/install", json={"thread_id": "t", "path": "mnt/user-data/x.skill"}),
            client.post("/api/skills/install/upload", files={"archive": ("x.skill", b"zip", "application/zip")}),
            client.get("/api/skills/custom/demo"),
            client.put("/api/skills/custom/demo", json={"content": _SKILL_MD}),
            client.delete("/api/skills/custom/demo"),
            client.get("/api/skills/custom/demo/history"),
            client.post("/api/skills/custom/demo/rollback", json={"history_index": -1}),
            client.get("/api/skills/custom/demo/export-manifest"),
            client.get("/api/skills/custom/demo/export", params={"expected_revision": "a" * 64}),
            client.put("/api/skills/demo", json={"enabled": False}),
        ]
    assert [response.status_code for response in requests] == [403] * len(requests)


def test_manage_permission_does_not_authorize_public_toggle(monkeypatch):
    skill = SimpleNamespace(name="public-skill", category=SkillCategory.PUBLIC)
    storage = SimpleNamespace(load_skills=lambda *, enabled_only: [skill])
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda config: storage)
    with TestClient(_make_app(_config(), permissions=["skills:manage"])) as client:
        response = client.put("/api/skills/public-skill", json={"enabled": False})
        diagnostics = client.get("/api/skills/diagnostics/custom")
    assert response.status_code == 403
    assert diagnostics.status_code == 403


def test_source_inspect_response_and_changed_install_cleanup(monkeypatch, tmp_path):
    constructors: list[dict] = []
    _mock_upstream(monkeypatch, _success_handler, constructors)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    monkeypatch.setattr(skill_source.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    installer = AsyncMock()
    monkeypatch.setattr(skills_router, "_install_skill_archive", installer)

    with TestClient(_make_app(_config())) as client:
        preview = client.post("/api/skills/install/source/inspect", json={"source": _SOURCE})
        assert preview.status_code == 200, preview.text
        assert preview.json()["source"] == _SOURCE
        assert preview.json()["source_url"] == "https://skills.sh/vercel-labs/skills/find-skills"
        assert preview.json()["skill_name"] == "find-skills"
        assert preview.json()["file_count"] == 1
        assert len(preview.json()["snapshot_digest"]) == 64
        assert "content" not in preview.text
        assert not tmp_path.exists()

        # Recreate the temporary directory for the second fetch.
        tmp_path.mkdir()
        changed = client.post("/api/skills/install/source", json={"source": _SOURCE, "expected_snapshot_digest": "0" * 64})
    assert changed.json()["detail"]["code"] == "skill_source_changed"
    assert installer.await_count == 0
    assert not tmp_path.exists()


def test_source_install_preserves_scanner_findings_and_cleans_archive(monkeypatch, tmp_path):
    _mock_upstream(monkeypatch, _success_handler)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    monkeypatch.setattr(skill_source.tempfile, "mkdtemp", lambda prefix: str(tmp_path))

    async def _blocked(archive_path, config):
        assert archive_path.suffix == ".skill"
        assert archive_path.is_file()
        raise HTTPException(400, detail={"message": "Content scan blocked the skill", "findings": [{"rule_id": "content-rule"}]})

    monkeypatch.setattr(skills_router, "_install_skill_archive", _blocked)
    with TestClient(_make_app(_config())) as client:
        preview = client.post("/api/skills/install/source/inspect", json={"source": _SOURCE})
        tmp_path.mkdir()
        response = client.post(
            "/api/skills/install/source",
            json={"source": _SOURCE, "expected_snapshot_digest": preview.json()["snapshot_digest"]},
        )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "skill_security_scan_failed"
    assert response.json()["detail"]["findings"] == [{"rule_id": "content-rule"}]
    assert not tmp_path.exists()


@pytest.mark.asyncio
async def test_cancelled_snapshot_preparation_cleans_worker_result(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    original = skill_source._prepare_snapshot

    def _slow_prepare(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(skill_source, "_prepare_snapshot", _slow_prepare)
    monkeypatch.setattr(skill_source, "_fetch_snapshot_payload", AsyncMock(return_value=_payload()))
    monkeypatch.setattr(skill_source.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    task = asyncio.create_task(skill_source.prepare_skill_source(_SOURCE, user_id="user-1", app_config=_config()))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not tmp_path.exists()


@pytest.mark.asyncio
async def test_cancellation_after_drained_install_finishes_and_cleans_archive(monkeypatch, tmp_path):
    from deerflow.utils.file_io import await_drained

    archive = tmp_path / "snapshot.skill"
    await asyncio.to_thread(archive.touch)
    prepared = PreparedSkillSource(
        reference=parse_skill_source(_SOURCE),
        archive_path=archive,
        temporary_root=tmp_path,
        snapshot_digest="a" * 64,
        upstream_hash=None,
        file_count=1,
        total_bytes=len(_SKILL_MD.encode()),
        skill_name="find-skills",
        description="Find useful skills.",
    )
    monkeypatch.setattr(skills_router, "prepare_skill_source", AsyncMock(return_value=prepared))
    started = asyncio.Event()
    release = asyncio.Event()
    completed = False

    async def _install(archive_path, config):
        assert archive_path.suffix == ".skill"

        async def _persist():
            nonlocal completed
            started.set()
            await release.wait()
            completed = True
            return skills_router.SkillInstallResponse(success=True, skill_name="find-skills", message="installed")

        return await await_drained(_persist())

    monkeypatch.setattr(skills_router, "_install_skill_archive", _install)
    user = _make_user()
    request = Request({"type": "http", "headers": [], "state": {}})
    request.state.user = user
    request.state.auth = AuthContext(user=user, permissions=["skills:manage"])
    body = skills_router.SkillSourceInstallRequest(source=_SOURCE, expected_snapshot_digest="a" * 64)
    task = asyncio.create_task(skills_router.install_skill_from_source(request, body, _config()))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed is True
    assert not await asyncio.to_thread(tmp_path.exists)


def test_source_limits_stay_stricter_than_archive_installer_limits():
    import inspect

    from deerflow.skills.installer import safe_extract_skill_archive

    parameters = inspect.signature(safe_extract_skill_archive).parameters
    assert skill_source.SOURCE_FILE_COUNT_LIMIT == 256
    assert skill_source.SOURCE_TOTAL_BYTES_LIMIT == 8 * 1024 * 1024
    assert parameters["max_total_size"].default == 512 * 1024 * 1024
    assert parameters["max_entries"].default == 4096


def test_real_source_install_scans_and_supports_complete_owned_lifecycle(monkeypatch, tmp_path):
    from deerflow.config.paths import Paths

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    source = "vercel-labs/skills@external-skill"
    skill_md = "---\nname: external-skill\ndescription: External lifecycle fixture.\n---\n\n# External skill\n"
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    storage = UserScopedSkillStorage("default", host_path=str(skills_root))
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
        skill_scan=SimpleNamespace(enabled=False),
        authorization=AuthorizationConfig(enabled=False),
    )
    scan_calls = []

    async def _scan(content, *, executable, location, app_config=None, static_findings=None):
        scan_calls.append(location)
        return ScanResult(decision="allow", reason="ok")

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)
    monkeypatch.setattr(skills_router, "scan_skill_content", _scan)
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", AsyncMock())
    monkeypatch.setattr(skills_router, "_publish_skills_cache_reset", AsyncMock())
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")
    (tmp_path / "extensions.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions.json"))
    _mock_upstream(
        monkeypatch,
        lambda _request: httpx.Response(
            200,
            json=_payload(
                id="vercel-labs/skills/external-skill",
                slug="external-skill",
                files=[{"path": "SKILL.md", "contents": skill_md}],
            ),
        ),
    )

    with TestClient(_make_app(config, permissions=["skills:manage"])) as client:
        preview = client.post("/api/skills/install/source/inspect", json={"source": source})
        assert preview.status_code == 200, preview.text
        assert scan_calls == [], "Preview performs deterministic/static gates, not the content scan"
        installed = client.post(
            "/api/skills/install/source",
            json={"source": source, "expected_snapshot_digest": preview.json()["snapshot_digest"]},
        )
        assert installed.status_code == 200, installed.text
        assert scan_calls == ["external-skill/SKILL.md"]
        installed_file = storage.get_custom_skill_dir("external-skill") / "SKILL.md"
        assert installed_file.read_text(encoding="utf-8") == skill_md

        assert client.get("/api/skills/custom/external-skill").status_code == 200
        edited = skill_md + "\nEdited by the owner.\n"
        assert client.put("/api/skills/custom/external-skill", json={"content": edited}).status_code == 200
        history = client.get("/api/skills/custom/external-skill/history")
        assert history.status_code == 200
        assert history.json()["history"][-1]["action"] == "human_edit"
        assert client.post("/api/skills/custom/external-skill/rollback", json={"history_index": -1}).status_code == 200
        disabled = client.put("/api/skills/external-skill", json={"enabled": False})
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["enabled"] is False
        manifest = client.get("/api/skills/custom/external-skill/export-manifest")
        assert manifest.status_code == 200, manifest.text
        exported = client.get("/api/skills/custom/external-skill/export", params={"expected_revision": manifest.json()["revision"]})
        assert exported.status_code == 200, exported.text
        assert client.delete("/api/skills/custom/external-skill").json() == {"success": True}
        assert not installed_file.exists()
