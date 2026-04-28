import errno
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import skills as skills_router
from deerflow.skills.manager import get_skill_history_file
from deerflow.skills.types import Skill


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


def test_custom_skills_router_lifecycle(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    custom_dir = skills_root / "custom" / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.manager.get_app_config", lambda: config)
    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", lambda *args, **kwargs: _async_scan("allow", "ok"))
    refresh_calls = []

    async def _refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)

    app = FastAPI()
    app.include_router(skills_router.router)

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

        history_response = client.get("/api/skills/custom/demo-skill/history")
        assert history_response.status_code == 200
        assert history_response.json()["history"][-1]["action"] == "human_edit"

        rollback_response = client.post("/api/skills/custom/demo-skill/rollback", json={"history_index": -1})
        assert rollback_response.status_code == 200
        assert rollback_response.json()["description"] == "Demo skill"
        assert refresh_calls == ["refresh", "refresh"]


def test_custom_skill_rollback_blocked_by_scanner(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    custom_dir = skills_root / "custom" / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    original_content = _skill_content("demo-skill")
    edited_content = _skill_content("demo-skill", "Edited skill")
    (custom_dir / "SKILL.md").write_text(edited_content, encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.manager.get_app_config", lambda: config)
    get_skill_history_file("demo-skill").write_text(
        '{"action":"human_edit","prev_content":' + json.dumps(original_content) + ',"new_content":' + json.dumps(edited_content) + "}\n",
        encoding="utf-8",
    )

    async def _refresh():
        return None

    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)

    async def _scan(*args, **kwargs):
        from deerflow.skills.security_scanner import ScanResult

        return ScanResult(decision="block", reason="unsafe rollback")

    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", _scan)

    app = FastAPI()
    app.include_router(skills_router.router)

    with TestClient(app) as client:
        rollback_response = client.post("/api/skills/custom/demo-skill/rollback", json={"history_index": -1})
        assert rollback_response.status_code == 400
        assert "unsafe rollback" in rollback_response.json()["detail"]

        history_response = client.get("/api/skills/custom/demo-skill/history")
        assert history_response.status_code == 200
        assert history_response.json()["history"][-1]["scanner"]["decision"] == "block"


def test_custom_skill_delete_preserves_history_and_allows_restore(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    custom_dir = skills_root / "custom" / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    original_content = _skill_content("demo-skill")
    (custom_dir / "SKILL.md").write_text(original_content, encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.manager.get_app_config", lambda: config)
    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", lambda *args, **kwargs: _async_scan("allow", "ok"))
    refresh_calls = []

    async def _refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)

    app = FastAPI()
    app.include_router(skills_router.router)

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
        assert refresh_calls == ["refresh", "refresh"]


def test_custom_skill_delete_continues_when_history_write_is_readonly(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    custom_dir = skills_root / "custom" / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.manager.get_app_config", lambda: config)
    refresh_calls = []

    async def _refresh():
        refresh_calls.append("refresh")

    def _readonly_history(*args, **kwargs):
        raise OSError(errno.EROFS, "Read-only file system", str(skills_root / "custom" / ".history"))

    monkeypatch.setattr("app.gateway.routers.skills.append_history", _readonly_history)
    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)

    app = FastAPI()
    app.include_router(skills_router.router)

    with TestClient(app) as client:
        delete_response = client.delete("/api/skills/custom/demo-skill")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"success": True}
    assert not custom_dir.exists()
    assert refresh_calls == ["refresh"]


def test_custom_skill_delete_fails_when_skill_dir_removal_fails(monkeypatch, tmp_path):
    skills_root = tmp_path / "skills"
    custom_dir = skills_root / "custom" / "demo-skill"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.manager.get_app_config", lambda: config)
    refresh_calls = []

    async def _refresh():
        refresh_calls.append("refresh")

    def _fail_rmtree(*args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", str(custom_dir))

    monkeypatch.setattr("app.gateway.routers.skills.shutil.rmtree", _fail_rmtree)
    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)

    app = FastAPI()
    app.include_router(skills_router.router)

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

    def _load_skills(*, enabled_only: bool):
        skill = _make_skill("demo-skill", enabled=enabled_state["value"])
        if enabled_only and not skill.enabled:
            return []
        return [skill]

    async def _refresh():
        refresh_calls.append("refresh")
        enabled_state["value"] = False

    monkeypatch.setattr("app.gateway.routers.skills.load_skills", _load_skills)
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda: config_path))
    monkeypatch.setattr("app.gateway.routers.skills.refresh_skills_system_prompt_cache_async", _refresh)

    app = FastAPI()
    app.include_router(skills_router.router)

    with TestClient(app) as client:
        response = client.put("/api/skills/demo-skill", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert refresh_calls == ["refresh"]
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"mcpServers": {}, "skills": {"demo-skill": {"enabled": False}}}
