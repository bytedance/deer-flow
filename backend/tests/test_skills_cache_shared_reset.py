"""Cross-replica invalidation of the skills prompt caches.

``SkillStorage.load_skills()`` rescans disk and re-reads ``extensions_config.json``
on every call, so the only state that can go stale between Gateway replicas is
the prompt layer in ``deerflow.agents.lead_agent.prompt``: the global
enabled-skills cache, the per-``(app_config, user_id)`` cache and the rendered
``<skill_system>`` LRU. Every skill mutation handled by one replica therefore
publishes ``.<extensions config>.skills-cache-reset.json`` beside the shared
config; every other replica compares that marker's signature (throttled to one
stat per second) before serving a cached entry.

The prompt-layer tests play "process B" with the real module state and
"process A" by writing the marker directly, the way another replica would.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

import deerflow.config.shared_reset_marker as shared_reset_marker_module
from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router
from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.extensions_config import ExtensionsConfig, reset_extensions_config
from deerflow.config.file_signature import get_config_signature
from deerflow.config.paths import Paths
from deerflow.config.shared_reset_marker import SharedResetMarkerTracker
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import Skill

_PROCESS_MESSAGE = "Skill caches invalidated; subsequent runs in this Gateway process will rescan the latest skills."


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _reset_prompt_cache_state() -> None:
    prompt_module._get_cached_skills_prompt_section.cache_clear()
    with prompt_module._enabled_skills_lock:
        prompt_module._enabled_skills_cache = None
        prompt_module._enabled_skills_by_config_cache.clear()
        prompt_module._enabled_skills_refresh_active = False
        prompt_module._enabled_skills_refresh_version = 0
        prompt_module._enabled_skills_refresh_event.clear()
        prompt_module._enabled_skills_refresh_waiters.clear()
    prompt_module._skills_cache_reset_tracker.reset()


@pytest.fixture()
def shared_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """One extensions config shared by every simulated replica, plus a fake clock."""
    config_path = tmp_path / "shared" / "extensions_config.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    reset_extensions_config()
    clock = _Clock()
    monkeypatch.setattr(prompt_module, "_skills_cache_reset_tracker", SharedResetMarkerTracker(prompt_module.SKILLS_CACHE_RESET_MARKER, clock=clock))
    _reset_prompt_cache_state()
    try:
        yield SimpleNamespace(path=config_path, clock=clock, marker=prompt_module.SKILLS_CACHE_RESET_MARKER)
    finally:
        _reset_prompt_cache_state()
        reset_extensions_config()


def _marker_path(shared) -> Path:
    return shared.marker.path_for(shared.path)


def _marker_payload(shared) -> dict:
    return json.loads(_marker_path(shared).read_text(encoding="utf-8"))


def _write_public_skill(root: Path, name: str, description: str) -> None:
    skill_dir = root / "public" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n", encoding="utf-8")


def _skills_config(skills_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: skills_root),
        skill_evolution=SimpleNamespace(enabled=False, moderation_model_name=None),
    )


def _install_prompt_storage(monkeypatch: pytest.MonkeyPatch, skills_root: Path) -> LocalSkillStorage:
    storage = LocalSkillStorage(host_path=str(skills_root))
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda **_kwargs: storage)
    monkeypatch.setattr(prompt_module, "get_or_new_user_skill_storage", lambda _user_id, **_kwargs: storage)
    return storage


# --------------------------------------------------------------------------- #
# Prompt layer: replica B observes a marker written by replica A
# --------------------------------------------------------------------------- #


def test_peer_global_reset_invalidates_per_config_cache_and_prompt_section(shared_config, monkeypatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_public_skill(skills_root, "changed-skill", "old description")
    _install_prompt_storage(monkeypatch, skills_root)
    config = _skills_config(skills_root)

    before = prompt_module.get_enabled_skills_for_config(config, user_id="alice")
    assert before[0].description == "old description"
    assert "old description" in prompt_module.get_skills_prompt_section(app_config=config, user_id="alice")
    assert prompt_module._get_cached_skills_prompt_section.cache_info().currsize == 1

    # Replica A: the skill changed on the shared volume and A published a reset.
    _write_public_skill(skills_root, "changed-skill", "new description")
    shared_config.marker.publish(shared_config.path)

    # Inside the throttle window B keeps serving its cache (bounded staleness).
    assert prompt_module.get_enabled_skills_for_config(config, user_id="alice")[0].description == "old description"

    shared_config.clock.advance(1.0)
    after = prompt_module.get_enabled_skills_for_config(config, user_id="alice")
    assert after[0].description == "new description"
    assert prompt_module._get_cached_skills_prompt_section.cache_info().currsize == 0
    assert "new description" in prompt_module.get_skills_prompt_section(app_config=config, user_id="alice")


def test_peer_user_scoped_reset_invalidates_only_that_user(shared_config, monkeypatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_public_skill(skills_root, "changed-skill", "old description")
    _install_prompt_storage(monkeypatch, skills_root)
    config = _skills_config(skills_root)

    assert prompt_module.get_enabled_skills_for_config(config, user_id="alice")[0].description == "old description"
    assert prompt_module.get_enabled_skills_for_config(config, user_id="bob")[0].description == "old description"

    _write_public_skill(skills_root, "changed-skill", "new description")
    shared_config.marker.publish(shared_config.path, user_id="alice")
    shared_config.clock.advance(1.0)

    assert prompt_module.get_enabled_skills_for_config(config, user_id="alice")[0].description == "new description"
    # Mirrors invalidate_user_skill_cache(): the other user's entry is untouched.
    assert prompt_module.get_enabled_skills_for_config(config, user_id="bob")[0].description == "old description"
    with prompt_module._enabled_skills_lock:
        assert (id(config), "bob") in prompt_module._enabled_skills_by_config_cache


def test_peer_global_reset_refreshes_the_global_enabled_skills_cache(shared_config, monkeypatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_public_skill(skills_root, "cached-skill", "old description")
    storage = _install_prompt_storage(monkeypatch, skills_root)
    old_skills = storage.load_skills(enabled_only=True)
    _write_public_skill(skills_root, "cached-skill", "new description")
    new_skills = storage.load_skills(enabled_only=True)
    monkeypatch.setattr(prompt_module, "_load_enabled_skills_sync", lambda: list(new_skills))
    with prompt_module._enabled_skills_lock:
        prompt_module._enabled_skills_cache = list(old_skills)

    assert prompt_module.get_cached_enabled_skills()[0].description == "old description"

    shared_config.marker.publish(shared_config.path)
    shared_config.clock.advance(1.0)

    first_after = prompt_module.get_cached_enabled_skills()
    assert prompt_module._enabled_skills_refresh_event.wait(timeout=5), "the reset must start the off-loop refresh"
    assert prompt_module.get_cached_enabled_skills()[0].description == "new description"
    # The last-known-good list is served while the refresh runs.
    assert first_after[0].description in {"old description", "new description"}


def test_prompt_lookups_stat_the_marker_at_most_once_per_second(shared_config, monkeypatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_public_skill(skills_root, "a-skill", "description")
    _install_prompt_storage(monkeypatch, skills_root)
    config = _skills_config(skills_root)
    shared_config.marker.publish(shared_config.path)
    reads: list[Path] = []
    original = shared_reset_marker_module.read_config_with_signature

    def _counting_read(path: Path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(shared_reset_marker_module, "read_config_with_signature", _counting_read)

    prompt_module.get_enabled_skills_for_config(config, user_id="alice")
    prompt_module.get_enabled_skills_for_config(config, user_id="alice")
    prompt_module.get_skills_prompt_section(app_config=config, user_id="alice")
    assert reads == [_marker_path(shared_config)]

    shared_config.clock.advance(1.0)
    prompt_module.get_enabled_skills_for_config(config, user_id="alice")
    assert len(reads) == 2


def test_publish_skills_cache_reset_without_config_path_is_process_local(shared_config, monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "resolve_shared_config_path", lambda: None)

    assert prompt_module.publish_skills_cache_reset() is None
    assert not _marker_path(shared_config).exists()


def test_publish_skills_cache_reset_writes_marker_without_invalidating_the_publisher(shared_config, monkeypatch, tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_public_skill(skills_root, "a-skill", "description")
    _install_prompt_storage(monkeypatch, skills_root)
    config = _skills_config(skills_root)
    prompt_module.get_enabled_skills_for_config(config, user_id="alice")

    generation = prompt_module.publish_skills_cache_reset(user_id="alice")

    assert generation is not None
    assert _marker_payload(shared_config) == {
        "version": 1,
        "generation": generation,
        "previous_generation": None,
        "published_at": _marker_payload(shared_config)["published_at"],
        "user_id": "alice",
    }
    shared_config.clock.advance(1.0)
    prompt_module.get_enabled_skills_for_config(config, user_id="alice")
    with prompt_module._enabled_skills_lock:
        assert (id(config), "alice") in prompt_module._enabled_skills_by_config_cache, "the publishing process already refreshed itself"


# --------------------------------------------------------------------------- #
# Router: every mutation publishes the marker; reload reports its scope
# --------------------------------------------------------------------------- #


def _make_admin_user() -> User:
    return User(email="admin-shared-reset@example.com", password_hash="x", system_role="admin", id=uuid4())


def _make_test_app(config) -> FastAPI:
    if not hasattr(config, "authorization"):
        config.authorization = AuthorizationConfig(enabled=False)
    app = make_authed_test_app(user_factory=_make_admin_user)
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


def _skill_content(name: str, description: str = "Demo skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


async def _allow_scan(*_args, **_kwargs):
    from deerflow.skills.security_scanner import ScanResult

    return ScanResult(decision="allow", reason="ok")


def _user_custom_dir(base_dir: Path, user_id: str = "default") -> Path:
    return base_dir / "users" / user_id / "skills" / "custom"


@pytest.fixture()
def custom_skill_app(shared_config, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """An admin app whose caller owns one editable custom skill on disk."""
    skills_root = tmp_path / "skills"
    custom_dir = _user_custom_dir(tmp_path) / "demo-skill"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text(_skill_content("demo-skill"), encoding="utf-8")
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: skills_root, container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    monkeypatch.setattr(skills_router, "scan_skill_content", _allow_scan)
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    events: list[tuple[str, str | None]] = []

    async def _refresh(user_id: str) -> None:
        events.append(("refresh", user_id))

    real_publish = skills_router.publish_skills_cache_reset

    def _publish(*, user_id=None):
        events.append(("publish", user_id))
        return real_publish(user_id=user_id)

    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skills_router, "publish_skills_cache_reset", _publish)
    return SimpleNamespace(app=_make_test_app(config), config=config, events=events, custom_dir=custom_dir, skills_root=skills_root, base_dir=tmp_path)


def test_custom_skill_edit_publishes_user_scoped_marker_after_local_refresh(shared_config, custom_skill_app) -> None:
    assert not _marker_path(shared_config).exists()

    with TestClient(custom_skill_app.app) as client:
        response = client.put("/api/skills/custom/demo-skill", json={"content": _skill_content("demo-skill", "Edited skill")})

    assert response.status_code == 200, response.text
    assert custom_skill_app.events == [("refresh", "default"), ("publish", "default")]
    assert _marker_payload(shared_config)["user_id"] == "default"


def test_custom_skill_rollback_publishes_marker(shared_config, custom_skill_app) -> None:
    with TestClient(custom_skill_app.app) as client:
        assert client.put("/api/skills/custom/demo-skill", json={"content": _skill_content("demo-skill", "Edited skill")}).status_code == 200
        after_edit = get_config_signature(_marker_path(shared_config))
        response = client.post("/api/skills/custom/demo-skill/rollback", json={"history_index": -1})

    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Demo skill"
    assert get_config_signature(_marker_path(shared_config)) != after_edit
    assert custom_skill_app.events[-2:] == [("refresh", "default"), ("publish", "default")]


def test_custom_skill_delete_publishes_marker(shared_config, custom_skill_app) -> None:
    with TestClient(custom_skill_app.app) as client:
        response = client.delete("/api/skills/custom/demo-skill")

    assert response.status_code == 200, response.text
    assert not (custom_skill_app.custom_dir / "SKILL.md").exists()
    assert custom_skill_app.events == [("refresh", "default"), ("publish", "default")]
    assert _marker_payload(shared_config)["user_id"] == "default"


def test_archive_install_publishes_marker(shared_config, custom_skill_app, monkeypatch, tmp_path: Path) -> None:
    archive = tmp_path / "install-skill.skill"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("install-skill/SKILL.md", _skill_content("install-skill"))
    storage = UserScopedSkillStorage("default", host_path=str(custom_skill_app.skills_root))
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: storage)
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _allow_scan)
    monkeypatch.setattr(skills_router, "resolve_thread_virtual_path", lambda thread_id, path: archive)

    with TestClient(custom_skill_app.app) as client:
        response = client.post("/api/skills/install", json={"thread_id": "thread-1", "path": "mnt/user-data/outputs/install-skill.skill"})

    assert response.status_code == 200, response.text
    assert (_user_custom_dir(custom_skill_app.base_dir) / "install-skill").exists()
    assert custom_skill_app.events == [("refresh", "default"), ("publish", "default")]
    assert _marker_payload(shared_config)["user_id"] == "default"


def test_archive_upload_publishes_marker(shared_config, custom_skill_app, monkeypatch) -> None:
    class _Storage:
        async def ainstall_skill_from_archive(self, archive_path: Path) -> dict:
            return {"success": True, "skill_name": "uploaded-skill", "message": "Skill installed successfully"}

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: _Storage())

    with TestClient(custom_skill_app.app) as client:
        response = client.post("/api/skills/install/upload", files={"archive": ("uploaded-skill.skill", b"skill archive bytes", "application/octet-stream")})

    assert response.status_code == 200, response.text
    assert custom_skill_app.events == [("refresh", "default"), ("publish", "default")]
    assert _marker_payload(shared_config)["user_id"] == "default"


def test_public_skill_toggle_publishes_global_marker(shared_config, monkeypatch) -> None:
    def _load_skills(*, enabled_only: bool):
        enabled = ExtensionsConfig.from_file(str(shared_config.path)).skills.get("public-skill", SimpleNamespace(enabled=True)).enabled
        skill = Skill(
            name="public-skill",
            description="Description for public-skill",
            license="MIT",
            skill_dir=Path("/tmp/public-skill"),
            skill_file=Path("/tmp/public-skill/SKILL.md"),
            relative_path=Path("public-skill"),
            category="public",
            enabled=enabled,
        )
        return [] if enabled_only and not enabled else [skill]

    events: list[tuple[str, str | None]] = []
    real_publish = skills_router.publish_skills_cache_reset

    def _publish(*, user_id=None):
        events.append(("publish", user_id))
        return real_publish(user_id=user_id)

    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: SimpleNamespace(load_skills=_load_skills))
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr(skills_router, "clear_skills_system_prompt_cache", lambda: events.append(("clear", None)))
    monkeypatch.setattr(skills_router, "publish_skills_cache_reset", _publish)

    with TestClient(_make_test_app(SimpleNamespace())) as client:
        response = client.put("/api/skills/public-skill", json={"enabled": False})

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert json.loads(shared_config.path.read_text(encoding="utf-8"))["skills"]["public-skill"]["enabled"] is False
    assert events == [("clear", None), ("publish", None)]
    assert "user_id" not in _marker_payload(shared_config)


def test_custom_skill_toggle_publishes_user_scoped_marker(shared_config, monkeypatch) -> None:
    from deerflow.skills.storage import user_scoped_skill_storage as uss_module

    enabled_state = {"value": True}

    class _FakeUserScopedStorage:
        def load_skills(self, *, enabled_only: bool = False):
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
            return [] if enabled_only and not skill.enabled else [skill]

        def set_skill_enabled_state(self, name: str, enabled: bool) -> None:
            enabled_state["value"] = enabled

    events: list[tuple[str, str | None]] = []

    async def _refresh(user_id: str) -> None:
        events.append(("refresh", user_id))

    real_publish = skills_router.publish_skills_cache_reset

    def _publish(*, user_id=None):
        events.append(("publish", user_id))
        return real_publish(user_id=user_id)

    monkeypatch.setattr(uss_module, "UserScopedSkillStorage", _FakeUserScopedStorage)
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: _FakeUserScopedStorage())
    monkeypatch.setattr(skills_router, "get_effective_user_id", lambda: "default")
    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skills_router, "publish_skills_cache_reset", _publish)

    with TestClient(_make_test_app(SimpleNamespace())) as client:
        response = client.put("/api/skills/demo-skill", json={"enabled": False})

    assert response.status_code == 200, response.text
    assert events == [("refresh", "default"), ("publish", "default")]
    assert _marker_payload(shared_config)["user_id"] == "default"


def _make_reload_app() -> FastAPI:
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: "/tmp/skills", container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    app = make_authed_test_app(user_factory=_make_admin_user)
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


def test_reload_publishes_marker_and_reports_shared_config_scope(shared_config, monkeypatch) -> None:
    events: list[str] = []

    async def _refresh() -> None:
        events.append("refresh")

    real_publish = skills_router.publish_skills_cache_reset

    def _publish(*, user_id=None):
        events.append("publish")
        return real_publish(user_id=user_id)

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skills_router, "publish_skills_cache_reset", _publish)

    with TestClient(_make_reload_app()) as client:
        first = client.post("/api/skills/reload")
        first_signature = get_config_signature(_marker_path(shared_config))
        second = client.post("/api/skills/reload")

    assert first.status_code == 200, first.text
    assert first.json()["success"] is True
    assert first.json()["scope"] == "shared_config"
    assert "shared config directory" in first.json()["message"]
    assert events == ["refresh", "publish", "refresh", "publish"]
    assert second.status_code == 200
    assert get_config_signature(_marker_path(shared_config)) != first_signature
    assert "user_id" not in _marker_payload(shared_config)


def test_reload_without_config_path_falls_back_to_process_scope(shared_config, monkeypatch) -> None:
    async def _refresh() -> None:
        return None

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(prompt_module, "resolve_shared_config_path", lambda: None)

    with TestClient(_make_reload_app()) as client:
        response = client.post("/api/skills/reload")

    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "scope": "process", "message": _PROCESS_MESSAGE}
    assert not _marker_path(shared_config).exists()


def test_reload_marker_publication_failure_is_a_generic_server_error(shared_config, monkeypatch) -> None:
    """A 200 must never mean that only the handling process was refreshed."""

    async def _refresh() -> None:
        return None

    def _failing_publish(*, user_id=None):
        raise OSError("read-only volume at /srv/company/minio")

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _refresh)
    monkeypatch.setattr(skills_router, "publish_skills_cache_reset", _failing_publish)

    with TestClient(_make_reload_app()) as client:
        response = client.post("/api/skills/reload")

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to invalidate skills cache."}
    assert "/srv/company/minio" not in response.text
