from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router
from deerflow.skills.installer import SkillAlreadyExistsError, SkillSecurityScanError
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


def _make_user(system_role: str) -> User:
    return User(
        email=f"{system_role}-skill-upload@example.com",
        password_hash="x",
        system_role=system_role,
        id=uuid4(),
    )


def _make_app(*, system_role: str, config: object) -> FastAPI:
    app = make_authed_test_app(user_factory=lambda: _make_user(system_role))
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


def _admin_request() -> Request:
    return Request(
        {
            "type": "http",
            "headers": [],
            "state": {"user": _make_user("admin")},
        }
    )


class _RecordingStorage:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.archive_paths: list[Path] = []
        self.archive_bytes: list[bytes] = []

    async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
        path = Path(archive_path)
        assert path.exists()
        self.archive_paths.append(path)
        self.archive_bytes.append(path.read_bytes())
        if self.error is not None:
            raise self.error
        return {
            "success": True,
            "skill_name": "demo-skill",
            "message": "Skill 'demo-skill' installed successfully",
        }


@pytest.fixture
def config() -> SimpleNamespace:
    return SimpleNamespace()


def _install(client: TestClient, *, filename: str = "demo.skill", content: bytes = b"archive"):
    return client.post(
        "/api/skills/install/upload",
        files={"file": (filename, content, "application/octet-stream")},
    )


def _skill_archive_bytes(name: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: Uploaded test skill\n---\n\n# Test\n",
        )
    return buffer.getvalue()


def test_upload_install_uses_current_user_storage(monkeypatch, tmp_path):
    from deerflow.config.paths import Paths
    from deerflow.skills.security_scanner import ScanResult

    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    storage = UserScopedSkillStorage("alice", host_path=str(skills_root))
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    refresh_calls: list[str] = []

    async def _allow_scan(*args, **kwargs):
        return ScanResult(decision="allow", reason="ok")

    async def _refresh(user_id: str) -> None:
        refresh_calls.append(user_id)

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _allow_scan)

    with TestClient(_make_app(system_role="admin", config=config)) as client:
        response = _install(
            client,
            filename="uploaded-skill.skill",
            content=_skill_archive_bytes("uploaded-skill"),
        )

    assert response.status_code == 200
    assert response.json()["skill_name"] == "uploaded-skill"
    assert (tmp_path / "users" / "alice" / "skills" / "custom" / "uploaded-skill" / "SKILL.md").exists()
    assert refresh_calls == ["alice"]


def test_upload_install_writes_random_temporary_archive_refreshes_cache_and_cleans_up(monkeypatch, config):
    storage = _RecordingStorage()
    refresh_calls: list[str] = []

    async def _refresh(user_id: str) -> None:
        refresh_calls.append(user_id)

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)

    with TestClient(_make_app(system_role="admin", config=config)) as client:
        response = _install(client, content=b"uploaded-skill-archive")

    assert response.status_code == 200
    assert response.json()["skill_name"] == "demo-skill"
    assert storage.archive_bytes == [b"uploaded-skill-archive"]
    assert len(storage.archive_paths) == 1
    temp_path = storage.archive_paths[0]
    assert temp_path.name.startswith("skill-upload-")
    assert temp_path.suffix == ".skill"
    assert "alice" not in temp_path.name
    assert not temp_path.exists()
    assert refresh_calls == ["alice"]


def test_upload_install_rejects_non_admin_before_reading_file(monkeypatch, config):
    storage = _RecordingStorage()
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)

    with TestClient(_make_app(system_role="user", config=config)) as client:
        response = _install(client)

    assert response.status_code == 403
    assert storage.archive_paths == []


def test_upload_install_rejects_non_skill_extension(monkeypatch, config):
    storage = _RecordingStorage()
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)

    with TestClient(_make_app(system_role="admin", config=config)) as client:
        response = _install(client, filename="demo.zip")

    assert response.status_code == 400
    assert storage.archive_paths == []


def test_upload_install_rejects_oversized_archive_and_cleans_up(monkeypatch, config):
    storage = _RecordingStorage()
    created_paths: list[Path] = []
    original_named_temporary_file = skills_router.tempfile.NamedTemporaryFile

    def _recording_named_temporary_file(*args, **kwargs):
        handle = original_named_temporary_file(*args, **kwargs)
        created_paths.append(Path(handle.name))
        return handle

    monkeypatch.setattr(skills_router, "SKILL_UPLOAD_MAX_BYTES", 4)
    monkeypatch.setattr(skills_router.tempfile, "NamedTemporaryFile", _recording_named_temporary_file)
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)

    with TestClient(_make_app(system_role="admin", config=config)) as client:
        response = _install(client, content=b"12345")

    assert response.status_code == 413
    assert storage.archive_paths == []
    assert len(created_paths) == 1
    assert not created_paths[0].exists()


@pytest.mark.asyncio
async def test_upload_install_cleans_up_when_request_is_cancelled(monkeypatch, config):
    created_paths: list[Path] = []
    read_started = asyncio.Event()
    original_prepare = skills_router._prepare_skill_upload_temp

    def _recording_prepare():
        upload_temp = original_prepare()
        created_paths.append(upload_temp.path)
        return upload_temp

    class _InterruptedUpload:
        filename = "cancelled.skill"

        async def read(self, _size: int) -> bytes:
            read_started.set()
            await asyncio.Future()
            return b""

    monkeypatch.setattr(skills_router, "_prepare_skill_upload_temp", _recording_prepare)
    task = asyncio.create_task(
        skills_router.upload_and_install_skill(
            _admin_request(),
            _InterruptedUpload(),  # type: ignore[arg-type]
            config,
        )
    )
    await read_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(created_paths) == 1
    assert not created_paths[0].exists()


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (ValueError("Invalid .skill archive"), 400, "Invalid .skill archive"),
        (
            SkillSecurityScanError(
                "Skill security scan failed",
                skill_name="unsafe-skill",
                findings=[{"rule_id": "danger", "message": "unsafe"}],
            ),
            400,
            "Skill security scan failed",
        ),
        (SkillAlreadyExistsError("Skill already exists"), 409, "Skill already exists"),
    ],
)
def test_upload_install_maps_installer_errors_and_cleans_up(
    monkeypatch,
    config,
    error: Exception,
    expected_status: int,
    expected_detail: str,
):
    storage = _RecordingStorage(error=error)

    async def _refresh(_user_id: str) -> None:
        raise AssertionError("failed installs must not refresh the cache")

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: storage)
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)

    with TestClient(_make_app(system_role="admin", config=config)) as client:
        response = _install(client)

    assert response.status_code == expected_status
    detail = response.json()["detail"]
    if isinstance(detail, dict):
        assert detail["message"] == expected_detail
    else:
        assert detail == expected_detail
    assert len(storage.archive_paths) == 1
    assert not storage.archive_paths[0].exists()
