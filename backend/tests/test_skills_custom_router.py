import errno
import json
import stat
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router
from app.gateway.routers import uploads as uploads_router
from deerflow.skills.security_static_scanner import StaticScannerError
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import Skill


def _make_admin_user() -> User:
    from uuid import uuid4

    return User(email="admin-test@example.com", password_hash="x", system_role="admin", id=uuid4())


def _skill_content(name: str, description: str = "Demo skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


async def _async_scan(decision: str, reason: str):
    from deerflow.skills.security_scanner import ScanResult

    return ScanResult(decision=decision, reason=reason)


def _make_skill(name: str, *, enabled: bool) -> Skill:
    skill_dir = Path(f"/tmp/{name}")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category="public",
        enabled=enabled,
    )


def _make_test_app(config) -> FastAPI:
    app = make_authed_test_app(user_factory=_make_admin_user)
    app.state.config = config  # kept for any startup-style reads
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


def _make_skill_archive(tmp_path: Path, name: str, content: str | None = None) -> Path:
    archive = tmp_path / f"{name}.skill"
    skill_content = content or _skill_content(name)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", skill_content)
    return archive


def _make_skill_archive_bytes(name: str, content: str | None = None) -> bytes:
    buffer = BytesIO()
    skill_content = content or _skill_content(name)
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", skill_content)
        zf.writestr(f"{name}/references/guide.md", "# Guide\n")
    return buffer.getvalue()


def _user_custom_dir(base_dir: Path, user_id: str = "default") -> Path:
    """Helper to locate the per-user custom skills dir for test assertions."""
    return base_dir / "users" / user_id / "skills" / "custom"


def test_install_skill_archive_runs_security_scan(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    archive = _make_skill_archive(tmp_path, "archive-skill")
    scan_calls = []
    refresh_calls = []

    async def _scan(content, *, executable, location, app_config=None, static_findings=None):
        from deerflow.skills.security_scanner import ScanResult

        scan_calls.append({"content": content, "executable": executable, "location": location})
        return ScanResult(decision="allow", reason="ok")

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    # Monkeypatch paths BEFORE constructing UserScopedSkillStorage,
    # because __init__ calls get_paths() to resolve _user_custom_root.
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    # Use UserScopedSkillStorage so install goes to user-level dir
    storage = UserScopedSkillStorage("default", host_path=str(skills_root))
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr(skills_router, "resolve_thread_virtual_path", lambda thread_id, path: archive)
    # Monkeypatch _get_user_skill_storage to return our test storage
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: storage)
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")

    app = _make_test_app(config)

    with TestClient(app) as client:
        response = client.post("/api/skills/install", json={"thread_id": "thread-1", "path": "mnt/user-data/outputs/archive-skill.skill"})

    assert response.status_code == 200
    assert response.json()["skill_name"] == "archive-skill"
    # UserScopedSkillStorage installs to user-level dir
    user_custom = _user_custom_dir(tmp_path, "default")
    assert (user_custom / "archive-skill" / "SKILL.md").exists()
    assert scan_calls == [
        {
            "content": _skill_content("archive-skill"),
            "executable": False,
            "location": "archive-skill/SKILL.md",
        }
    ]
    assert refresh_calls == [("refresh", "default")]


def test_uploaded_skill_archive_installs_sandbox_readable_tree(monkeypatch, tmp_path):
    home = tmp_path / "home"
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    refresh_calls = []

    async def _scan(*args, **kwargs):
        from deerflow.skills.security_scanner import ScanResult

        return ScanResult(decision="allow", reason="ok")

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    from deerflow.config.paths import Paths

    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
        uploads=SimpleNamespace(auto_convert_documents=False),
    )
    provider = SimpleNamespace(uses_thread_data_mounts=True)

    # Monkeypatch paths BEFORE constructing UserScopedSkillStorage
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setattr(uploads_router, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)

    # Use UserScopedSkillStorage
    storage = UserScopedSkillStorage("default", host_path=str(skills_root))
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: storage)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")

    app = make_authed_test_app(user_factory=_make_admin_user)
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(uploads_router.router)
    app.include_router(skills_router.router)

    thread_id = "thread-uploaded-skill"
    archive_bytes = _make_skill_archive_bytes("uploaded-skill")

    with TestClient(app) as client:
        upload_response = client.post(
            f"/api/threads/{thread_id}/uploads",
            files=[("files", ("uploaded-skill.skill", archive_bytes, "application/octet-stream"))],
        )
        assert upload_response.status_code == 200
        uploaded_file = upload_response.json()["files"][0]
        uploaded_path = Path(uploaded_file["path"])
        assert uploaded_path.is_file()

        install_response = client.post("/api/skills/install", json={"thread_id": thread_id, "path": uploaded_file["virtual_path"]})

    assert install_response.status_code == 200
    assert install_response.json()["skill_name"] == "uploaded-skill"
    installed_dir = _user_custom_dir(tmp_path, "default") / "uploaded-skill"
    nested_dir = installed_dir / "references"
    assert stat.S_IMODE(installed_dir.stat().st_mode) & 0o055 == 0o055
    assert stat.S_IMODE(nested_dir.stat().st_mode) & 0o055 == 0o055
    assert stat.S_IMODE((installed_dir / "SKILL.md").stat().st_mode) & 0o044 == 0o044
    assert stat.S_IMODE((nested_dir / "guide.md").stat().st_mode) & 0o044 == 0o044
    assert refresh_calls == [("refresh", "default")]


def test_install_skill_archive_security_scan_block_returns_400(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    archive = _make_skill_archive(tmp_path, "blocked-skill")
    refresh_calls = []

    async def _scan(*args, **kwargs):
        from deerflow.skills.security_scanner import ScanResult

        return ScanResult(decision="block", reason="prompt injection")

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    from deerflow.config.paths import Paths

    # Monkeypatch paths BEFORE constructing UserScopedSkillStorage
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    storage = UserScopedSkillStorage("default", host_path=str(skills_root))
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr(skills_router, "resolve_thread_virtual_path", lambda thread_id, path: archive)
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: storage)
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")

    app = _make_test_app(config)

    with TestClient(app) as client:
        response = client.post("/api/skills/install", json={"thread_id": "thread-1", "path": "mnt/user-data/outputs/blocked-skill.skill"})

    assert response.status_code == 400
    assert "Security scan blocked skill 'blocked-skill': prompt injection" in response.json()["detail"]
    assert not (_user_custom_dir(tmp_path, "default") / "blocked-skill").exists()
    assert refresh_calls == []


def test_install_skill_archive_static_scan_block_returns_findings(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    archive = _make_skill_archive(
        tmp_path,
        "static-blocked-skill",
        "---\nname: static-blocked-skill\ndescription: Static blocked skill\n---\n\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAtestonlytestonlytestonly\n-----END RSA PRIVATE KEY-----\n",
    )
    refresh_calls = []
    llm_calls = []

    async def _scan(*args, **kwargs):
        from deerflow.skills.security_scanner import ScanResult

        llm_calls.append({"args": args, "kwargs": kwargs})
        return ScanResult(decision="allow", reason="ok")

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

    storage = LocalSkillStorage(host_path=str(skills_root))
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr(skills_router, "resolve_thread_virtual_path", lambda thread_id, path: archive)
    monkeypatch.setattr(skills_router, "get_or_new_user_skill_storage", lambda user_id, **kw: storage)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)

    app = _make_test_app(config)

    with TestClient(app) as client:
        response = client.post("/api/skills/install", json={"thread_id": "thread-1", "path": "mnt/user-data/outputs/static-blocked-skill.skill"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["skill_name"] == "static-blocked-skill"
    assert detail["findings"][0]["rule_id"] == "secret-private-key"
    assert llm_calls == []
    assert refresh_calls == []
    assert not (skills_root / "custom" / "static-blocked-skill").exists()


def test_custom_skills_router_lifecycle(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    from deerflow.config.paths import Paths

    # Create a skill in user-level custom dir
    user_custom = _user_custom_dir(tmp_path, "default")
    custom_dir = user_custom / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")

    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", lambda *args, **kwargs: _async_scan("allow", "ok"))
    refresh_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_effective_user_id", lambda: "default")

    app = _make_test_app(config)

    with TestClient(app) as client:
        response = client.get("/api/skills/custom")
        assert response.status_code == 200
        assert response.json()["skills"][0]["name"] == "demo-skill"

        get_response = client.get("/api/skills/custom/demo-skill")
        assert get_response.status_code == 200
        assert "# demo-skill" in get_response.json()["content"]

        update_response = client.put(
            "/api/skills/custom/demo-skill",
            json={"content": _skill_content("demo-skill", "Edited skill")},
        )
        assert update_response.status_code == 200
        assert update_response.json()["description"] == "Edited skill"
        assert stat.S_IMODE((custom_dir / "SKILL.md").stat().st_mode) & 0o044 == 0o044

        history_response = client.get("/api/skills/custom/demo-skill/history")
        assert history_response.status_code == 200
        assert history_response.json()["history"][-1]["action"] == "human_edit"

        rollback_response = client.post("/api/skills/custom/demo-skill/rollback", json={"history_index": -1})
        assert rollback_response.status_code == 200
        assert rollback_response.json()["description"] == "Demo skill"
        assert stat.S_IMODE((custom_dir / "SKILL.md").stat().st_mode) & 0o044 == 0o044
        assert refresh_calls == [("refresh", "default"), ("refresh", "default")]


def test_custom_skill_update_static_scan_failure_blocks_edit_before_llm(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    from deerflow.config.paths import Paths

    custom_dir = _user_custom_dir(tmp_path, "default") / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    original_content = _skill_content("demo-skill")
    (custom_dir / "SKILL.md").write_text(original_content, encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    refresh_calls = []
    llm_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    async def _scan(*args, **kwargs):
        llm_calls.append({"args": args, "kwargs": kwargs})
        return await _async_scan("allow", "ok")

    def _broken_static_scan(skill_dir, *, skill_name=None, app_config=None):
        raise StaticScannerError("native scanner unavailable")

    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_effective_user_id", lambda: "default")
    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", _scan)
    monkeypatch.setattr("app.gateway.routers.skills.enforce_static_scan", _broken_static_scan)

    app = _make_test_app(config)

    with TestClient(app) as client:
        response = client.put(
            "/api/skills/custom/demo-skill",
            json={"content": _skill_content("demo-skill", "Edited skill")},
        )

    assert response.status_code == 400
    assert "Static security scan failed" in response.json()["detail"]
    assert "native scanner unavailable" in response.json()["detail"]
    assert llm_calls == []
    assert refresh_calls == []
    assert (custom_dir / "SKILL.md").read_text(encoding="utf-8") == original_content


def test_custom_skill_rollback_blocked_by_scanner(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    from deerflow.config.paths import Paths

    user_custom = _user_custom_dir(tmp_path, "default")
    custom_dir = user_custom / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    original_content = _skill_content("demo-skill")
    edited_content = _skill_content("demo-skill", "Edited skill")
    (custom_dir / "SKILL.md").write_text(edited_content, encoding="utf-8")

    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    # Write history file directly for the rollback test
    storage = UserScopedSkillStorage("default", host_path=str(skills_root))
    history_file = storage.get_skill_history_file("demo-skill")
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(
        '{"action":"human_edit","prev_content":' + json.dumps(original_content) + ',"new_content":' + json.dumps(edited_content) + "}\n",
        encoding="utf-8",
    )

    async def _refresh(user_id: str):
        return None

    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_effective_user_id", lambda: "default")

    async def _scan(*args, **kwargs):
        from deerflow.skills.security_scanner import ScanResult

        return ScanResult(decision="block", reason="unsafe rollback")

    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", _scan)

    app = _make_test_app(config)

    with TestClient(app) as client:
        rollback_response = client.post("/api/skills/custom/demo-skill/rollback", json={"history_index": -1})
        assert rollback_response.status_code == 400
        assert "unsafe rollback" in rollback_response.json()["detail"]

        history_response = client.get("/api/skills/custom/demo-skill/history")
        assert history_response.status_code == 200
        assert history_response.json()["history"][-1]["scanner"]["decision"] == "block"


def test_custom_skill_delete_preserves_history_and_allows_restore(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    from deerflow.config.paths import Paths

    user_custom = _user_custom_dir(tmp_path, "default")
    custom_dir = user_custom / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    original_content = _skill_content("demo-skill")
    (custom_dir / "SKILL.md").write_text(original_content, encoding="utf-8")

    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", lambda *args, **kwargs: _async_scan("allow", "ok"))
    refresh_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_effective_user_id", lambda: "default")

    app = _make_test_app(config)

    with TestClient(app) as client:
        delete_response = client.delete("/api/skills/custom/demo-skill")
        assert delete_response.status_code == 200
        assert not (custom_dir / "SKILL.md").exists()

        history_response = client.get("/api/skills/custom/demo-skill/history")
        assert history_response.status_code == 200
        assert history_response.json()["history"][-1]["action"] == "human_delete"

        rollback_response = client.post("/api/skills/custom/demo-skill/rollback", json={"history_index": -1})
        assert rollback_response.status_code == 200
        assert rollback_response.json()["description"] == "Demo skill"
        assert (custom_dir / "SKILL.md").read_text(encoding="utf-8") == original_content
        assert refresh_calls == [("refresh", "default"), ("refresh", "default")]


def test_custom_skill_delete_continues_when_history_write_is_readonly(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    from deerflow.config.paths import Paths

    user_custom = _user_custom_dir(tmp_path, "default")
    custom_dir = user_custom / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    refresh_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    def _readonly_history(*args, **kwargs):
        raise OSError(errno.EROFS, "Read-only file system", str(user_custom / ".history"))

    monkeypatch.setattr("deerflow.skills.storage.user_scoped_skill_storage.UserScopedSkillStorage.append_history", _readonly_history)
    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_effective_user_id", lambda: "default")

    app = _make_test_app(config)

    with TestClient(app) as client:
        delete_response = client.delete("/api/skills/custom/demo-skill")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"success": True}
    assert not custom_dir.exists()
    assert refresh_calls == [("refresh", "default")]


def test_custom_skill_delete_fails_when_skill_dir_removal_fails(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    from deerflow.config.paths import Paths

    user_custom = _user_custom_dir(tmp_path, "default")
    custom_dir = user_custom / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    refresh_calls = []

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    def _fail_rmtree(*args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", str(custom_dir))

    monkeypatch.setattr("deerflow.skills.storage.local_skill_storage.shutil.rmtree", _fail_rmtree)
    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_effective_user_id", lambda: "default")

    app = _make_test_app(config)

    with TestClient(app) as client:
        delete_response = client.delete("/api/skills/custom/demo-skill")

    assert delete_response.status_code == 500
    assert "Failed to delete custom skill" in delete_response.json()["detail"]
    assert custom_dir.exists()
    assert refresh_calls == []


def test_update_skill_refreshes_prompt_cache_before_return(monkeypatch, tmp_path):
    config_path = tmp_path / "extensions_config.json"
    enabled_state = {"value": True}
    refresh_calls = []
    per_user_writes: list[tuple[str, bool]] = []

    def _load_skills(*, enabled_only: bool):
        # Use a CUSTOM skill so the router takes the per-user cache invalidation
        # branch (PUBLIC skills clear the cache for all users via
        # ``clear_skills_system_prompt_cache`` — see
        # ``test_public_skill_toggle_clears_all_users_cache``).
        skill = Skill(
            name="demo-skill",
            description="Description for demo-skill",
            license="MIT",
            skill_dir=Path("/tmp/demo-skill"),
            skill_file=Path("/tmp/demo-skill/SKILL.md"),
            relative_path=Path("demo-skill"),
            category="custom",
            enabled=enabled_state["value"],
        )
        if enabled_only and not skill.enabled:
            return []
        return [skill]

    def _set_skill_enabled_state(name: str, enabled: bool) -> None:
        per_user_writes.append((name, enabled))
        enabled_state["value"] = enabled

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    # Mock storage must be a UserScopedSkillStorage instance so the
    # router takes the per-user ``set_skill_enabled_state`` branch.
    # We patch the symbol on the storage module because the router
    # function imports ``UserScopedSkillStorage`` lazily from there.
    from deerflow.skills.storage import user_scoped_skill_storage as uss_module

    class _FakeUserScopedStorage:
        def __init__(self, *args, **kwargs) -> None:
            self._load = _load_skills
            self._write = _set_skill_enabled_state

        def load_skills(self, *, enabled_only: bool = False):
            return self._load(enabled_only=enabled_only)

        def set_skill_enabled_state(self, name: str, enabled: bool) -> None:
            self._write(name, enabled)

    monkeypatch.setattr(uss_module, "UserScopedSkillStorage", _FakeUserScopedStorage)
    # The router also calls ``isinstance(storage, UserScopedSkillStorage)``
    # against the symbol it imported; monkeypatch the symbol on the
    # storage module so the isinstance check accepts our mock.
    monkeypatch.setattr("deerflow.skills.storage.user_scoped_skill_storage.UserScopedSkillStorage", _FakeUserScopedStorage)
    mock_storage = _FakeUserScopedStorage()
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: mock_storage)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda config_path=None: config_path))
    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)

    app = _make_test_app(SimpleNamespace())

    with TestClient(app) as client:
        response = client.put("/api/skills/demo-skill", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert refresh_calls == [("refresh", "default")]
    # CUSTOM skills write to per-user state (not extensions_config.json).
    assert per_user_writes == [("demo-skill", False)]
    assert not config_path.exists() or json.loads(config_path.read_text(encoding="utf-8")) == {"mcpServers": {}, "skills": {}}


def test_public_skill_toggle_clears_all_users_cache(monkeypatch, tmp_path):
    """P2-5: toggling a PUBLIC skill must invalidate the prompt cache for
    every user, because PUBLIC state lives in the global
    ``extensions_config.json`` and a per-user ``refresh_*`` call would
    leave the other users' cached enabled state stale.
    """
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(json.dumps({"mcpServers": {}, "skills": {"public-skill": {"enabled": True}}}), encoding="utf-8")
    clear_calls = []
    refresh_calls = []
    load_calls = {"n": 0}

    def _load_skills(*, enabled_only: bool):
        from deerflow.config.extensions_config import ExtensionsConfig
        from deerflow.skills.types import Skill

        # The router re-loads after the toggle so the response reflects
        # the new state. The second call therefore reads the on-disk
        # JSON, which the PUBLIC branch has just rewritten.
        load_calls["n"] += 1
        if load_calls["n"] >= 2:
            on_disk = ExtensionsConfig.from_file(config_path)
            current_enabled = on_disk.skills["public-skill"].enabled
        else:
            current_enabled = True

        skill = Skill(
            name="public-skill",
            description="Description for public-skill",
            license="MIT",
            skill_dir=Path("/tmp/public-skill"),
            skill_file=Path("/tmp/public-skill/SKILL.md"),
            relative_path=Path("public-skill"),
            category="public",
            enabled=current_enabled,
        )
        if enabled_only and not skill.enabled:
            return []
        return [skill]

    def _clear():
        clear_calls.append("clear")

    async def _refresh(user_id: str):
        refresh_calls.append(("refresh", user_id))

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: SimpleNamespace(load_skills=_load_skills))
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    # ``resolve_config_path()`` is called with no args inside the router
    # to discover where to write; point it at the temp file.
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda config_path=None: config_path if config_path is not None else config_path))

    # Re-bind the staticmethod to actually default to config_path when
    # called with no args. ``staticmethod`` is a descriptor, so we wrap
    # with a callable that always returns the test path.
    def _resolve(_config_path=None):
        return config_path

    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(_resolve))
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: __import__("deerflow.config.extensions_config", fromlist=["ExtensionsConfig"]).ExtensionsConfig.from_file(config_path))
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)
    monkeypatch.setattr("app.gateway.routers.skills.clear_skills_system_prompt_cache", _clear)
    monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _refresh)

    app = _make_test_app(SimpleNamespace())

    with TestClient(app) as client:
        response = client.put("/api/skills/public-skill", json={"enabled": False})

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    # PUBLIC skills must hit the global cache-clear branch, not per-user refresh.
    assert clear_calls == ["clear"]
    assert refresh_calls == []
    # The global state file must reflect the toggle.
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["skills"]["public-skill"]["enabled"] is False


class TestMultiUserSkillIsolation:
    """End-to-end integration tests verifying per-user skill isolation
    through the HTTP router → _get_user_skill_storage → filesystem chain.

    These tests simulate two distinct users (alice and bob) calling the
    same API endpoints and verify that each user's skills are completely
    isolated: alice cannot see/edit/delete bob's skills and vice versa.
    """

    @staticmethod
    def _setup_two_user_env(monkeypatch, tmp_path, skills_root):
        """Shared setup: patch paths and create two UserScopedSkillStorage instances."""
        from deerflow.config.paths import Paths

        monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
        monkeypatch.setattr("deerflow.config.paths._paths", None)

        alice_storage = UserScopedSkillStorage("alice", host_path=str(skills_root))
        bob_storage = UserScopedSkillStorage("bob", host_path=str(skills_root))

        config = SimpleNamespace(
            skills=SimpleNamespace(
                get_skills_path=lambda: skills_root,
                container_path="/mnt/skills",
                use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
            ),
            skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
        )
        return alice_storage, bob_storage, config

    def test_alice_skill_not_visible_to_bob_via_list_api(self, monkeypatch, tmp_path):
        """Alice installs a skill; Bob's /api/skills listing does not include it."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        alice_storage, bob_storage, config = self._setup_two_user_env(monkeypatch, tmp_path, skills_root)

        # Alice creates a skill directly in her per-user directory
        alice_custom = _user_custom_dir(tmp_path, "alice")
        skill_dir = alice_custom / "alice-secret-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(_skill_content("alice-secret-skill"), encoding="utf-8")

        # Alice's listing includes her skill
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: alice_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
        alice_app = _make_test_app(config)

        with TestClient(alice_app) as client:
            alice_response = client.get("/api/skills")
            alice_skills = alice_response.json()["skills"]
            alice_custom_skills = [s for s in alice_skills if s["category"] == "custom"]
            assert len(alice_custom_skills) == 1
            assert alice_custom_skills[0]["name"] == "alice-secret-skill"

        # Bob's listing does NOT include Alice's skill
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: bob_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "bob")
        bob_app = _make_test_app(config)

        with TestClient(bob_app) as client:
            bob_response = client.get("/api/skills")
            bob_skills = bob_response.json()["skills"]
            bob_custom_skills = [s for s in bob_skills if s["category"] == "custom"]
            assert len(bob_custom_skills) == 0

    def test_bob_cannot_read_alice_skill_via_get_api(self, monkeypatch, tmp_path):
        """Bob cannot GET /api/skills/custom/alice-secret-skill — 404."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        alice_storage, _, config = self._setup_two_user_env(monkeypatch, tmp_path, skills_root)

        alice_custom = _user_custom_dir(tmp_path, "alice")
        skill_dir = alice_custom / "alice-secret-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(_skill_content("alice-secret-skill"), encoding="utf-8")

        # Simulate Bob's request context
        bob_storage = UserScopedSkillStorage("bob", host_path=str(skills_root))
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: bob_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "bob")
        bob_app = _make_test_app(config)

        with TestClient(bob_app) as client:
            bob_get_response = client.get("/api/skills/custom/alice-secret-skill")
            assert bob_get_response.status_code == 404

        # Alice can still read it
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: alice_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
        alice_app = _make_test_app(config)

        with TestClient(alice_app) as client:
            alice_get_response = client.get("/api/skills/custom/alice-secret-skill")
            assert alice_get_response.status_code == 200
            assert "# alice-secret-skill" in alice_get_response.json()["content"]

    def test_bob_cannot_delete_alice_skill(self, monkeypatch, tmp_path):
        """Bob cannot DELETE /api/skills/custom/alice-secret-skill — 404."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        alice_storage, _, config = self._setup_two_user_env(monkeypatch, tmp_path, skills_root)

        alice_custom = _user_custom_dir(tmp_path, "alice")
        skill_dir = alice_custom / "alice-secret-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(_skill_content("alice-secret-skill"), encoding="utf-8")

        bob_storage = UserScopedSkillStorage("bob", host_path=str(skills_root))
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: bob_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "bob")
        monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", lambda uid: None)
        bob_app = _make_test_app(config)

        with TestClient(bob_app) as client:
            bob_delete_response = client.delete("/api/skills/custom/alice-secret-skill")
            assert bob_delete_response.status_code == 404

        # Alice's skill file still exists
        assert (skill_dir / "SKILL.md").exists()

    def test_alice_cannot_edit_bob_skill_via_update_api(self, monkeypatch, tmp_path):
        """Alice cannot PUT /api/skills/custom/bob-skill — 404."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        _, bob_storage, config = self._setup_two_user_env(monkeypatch, tmp_path, skills_root)

        bob_custom = _user_custom_dir(tmp_path, "bob")
        skill_dir = bob_custom / "bob-priv-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(_skill_content("bob-priv-skill"), encoding="utf-8")

        alice_storage = UserScopedSkillStorage("alice", host_path=str(skills_root))
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: alice_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
        monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", lambda *a, **kw: _async_scan("allow", "ok"))
        monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", lambda uid: None)
        alice_app = _make_test_app(config)

        with TestClient(alice_app) as client:
            alice_update_response = client.put(
                "/api/skills/custom/bob-priv-skill",
                json={"content": _skill_content("bob-priv-skill", "Hacked by alice")},
            )
            assert alice_update_response.status_code == 404

        # Bob's skill content is unchanged
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == _skill_content("bob-priv-skill")

    def test_two_users_install_same_skill_name_independently(self, monkeypatch, tmp_path):
        """Both users install a skill named 'my-workflow' — they are stored separately."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        alice_storage, bob_storage, config = self._setup_two_user_env(monkeypatch, tmp_path, skills_root)

        # Both users create a skill with the same name but different content
        alice_custom = _user_custom_dir(tmp_path, "alice")
        alice_dir = alice_custom / "my-workflow"
        alice_dir.mkdir(parents=True, exist_ok=True)
        (alice_dir / "SKILL.md").write_text(_skill_content("my-workflow", "Alice's version"), encoding="utf-8")

        bob_custom = _user_custom_dir(tmp_path, "bob")
        bob_dir = bob_custom / "my-workflow"
        bob_dir.mkdir(parents=True, exist_ok=True)
        (bob_dir / "SKILL.md").write_text(_skill_content("my-workflow", "Bob's version"), encoding="utf-8")

        # Alice sees her version
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: alice_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
        alice_app = _make_test_app(config)

        with TestClient(alice_app) as client:
            alice_skills = client.get("/api/skills").json()["skills"]
            alice_custom_skills = [s for s in alice_skills if s["category"] == "custom"]
            assert len(alice_custom_skills) == 1
            assert alice_custom_skills[0]["name"] == "my-workflow"

            alice_content = client.get("/api/skills/custom/my-workflow").json()["content"]
            assert "Alice's version" in alice_content

        # Bob sees his version
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: bob_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "bob")
        bob_app = _make_test_app(config)

        with TestClient(bob_app) as client:
            bob_skills = client.get("/api/skills").json()["skills"]
            bob_custom_skills = [s for s in bob_skills if s["category"] == "custom"]
            assert len(bob_custom_skills) == 1
            assert bob_custom_skills[0]["name"] == "my-workflow"

            bob_content = client.get("/api/skills/custom/my-workflow").json()["content"]
            assert "Bob's version" in bob_content

    def test_skill_response_includes_editable_field(self, monkeypatch, tmp_path):
        """SkillResponse.editable is true for CUSTOM, false for PUBLIC and LEGACY."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        # Create a public skill
        public_dir = skills_root / "public" / "deep-research"
        public_dir.mkdir(parents=True, exist_ok=True)
        (public_dir / "SKILL.md").write_text(_skill_content("deep-research", "Built-in skill"), encoding="utf-8")

        # Create a global custom skill (LEGACY fallback for users without per-user dir)
        global_custom_dir = skills_root / "custom" / "legacy-shared-skill"
        global_custom_dir.mkdir(parents=True, exist_ok=True)
        (global_custom_dir / "SKILL.md").write_text(_skill_content("legacy-shared-skill", "Legacy shared skill"), encoding="utf-8")

        # Create a per-user custom skill
        from deerflow.config.paths import Paths

        monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
        monkeypatch.setattr("deerflow.config.paths._paths", None)

        alice_storage = UserScopedSkillStorage("alice", host_path=str(skills_root))
        alice_custom = _user_custom_dir(tmp_path, "alice")
        alice_dir = alice_custom / "alice-custom-skill"
        alice_dir.mkdir(parents=True, exist_ok=True)
        (alice_dir / "SKILL.md").write_text(_skill_content("alice-custom-skill"), encoding="utf-8")

        config = SimpleNamespace(
            skills=SimpleNamespace(
                get_skills_path=lambda: skills_root,
                container_path="/mnt/skills",
                use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
            ),
            skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
        )
        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: alice_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
        monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
        monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)

        app = _make_test_app(config)

        with TestClient(app) as client:
            response = client.get("/api/skills")
            skills = response.json()["skills"]

            # PUBLIC skill: editable=false
            public_skill = next(s for s in skills if s["name"] == "deep-research")
            assert public_skill["category"] == "public"
            assert public_skill["editable"] is False

            # CUSTOM skill: editable=true
            custom_skill = next(s for s in skills if s["name"] == "alice-custom-skill")
            assert custom_skill["category"] == "custom"
            assert custom_skill["editable"] is True

    def test_toggle_enabled_accepted_for_custom_skill(self, monkeypatch, tmp_path):
        """PUT /api/skills/<custom-skill> with {enabled: false} returns 200.

        All skill categories (public, custom, legacy) can be toggled via
        extensions_config.  CUSTOM skills default to enabled, but users may
        disable them temporarily without deleting.
        """
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        from deerflow.config.paths import Paths

        monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
        monkeypatch.setattr("deerflow.config.paths._paths", None)

        alice_storage = UserScopedSkillStorage("alice", host_path=str(skills_root))
        alice_custom = _user_custom_dir(tmp_path, "alice")
        alice_dir = alice_custom / "alice-custom-skill"
        alice_dir.mkdir(parents=True, exist_ok=True)
        (alice_dir / "SKILL.md").write_text(_skill_content("alice-custom-skill"), encoding="utf-8")

        config = SimpleNamespace(
            skills=SimpleNamespace(
                get_skills_path=lambda: skills_root,
                container_path="/mnt/skills",
                use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
            ),
            skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
        )

        async def _noop_async(user_id: str) -> None:
            pass

        monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: alice_storage)
        monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "alice")
        monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
        monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)
        monkeypatch.setattr("app.gateway.routers.skills.refresh_user_skills_system_prompt_cache_async", _noop_async)

        app = _make_test_app(config)

        with TestClient(app) as client:
            response = client.put("/api/skills/alice-custom-skill", json={"enabled": False})
            assert response.status_code == 200
            assert response.json()["enabled"] is False
