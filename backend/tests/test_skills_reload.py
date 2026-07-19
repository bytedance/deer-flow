from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import anyio
import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router
from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

_SUCCESS_RESPONSE = {
    "success": True,
    "scope": "process",
    "message": "Skill caches invalidated; subsequent runs in this Gateway process will rescan the latest skills.",
}


def _make_app(*, system_role: str) -> FastAPI:
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: "/tmp/skills", container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-reload-test@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


def _write_skill(root: Path, name: str, description: str) -> None:
    skill_dir = root / "public" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )


def _reset_prompt_cache_state() -> None:
    prompt_module._get_cached_skills_prompt_section.cache_clear()
    with prompt_module._enabled_skills_lock:
        prompt_module._enabled_skills_cache = None
        prompt_module._enabled_skills_by_config_cache.clear()
        prompt_module._enabled_skills_refresh_active = False
        prompt_module._enabled_skills_refresh_version = 0
        prompt_module._enabled_skills_refresh_event.clear()
        prompt_module._enabled_skills_refresh_waiters.clear()


def test_admin_can_reload_skills(monkeypatch) -> None:
    calls = 0

    async def _refresh() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _refresh)
    app = _make_app(system_role="admin")

    with TestClient(app) as client:
        response = client.post("/api/skills/reload")

    assert response.status_code == 200
    assert response.json() == _SUCCESS_RESPONSE
    assert calls == 1


def test_reload_failure_returns_generic_error(monkeypatch) -> None:
    async def _refresh() -> None:
        raise RuntimeError("private mount failed at /srv/company/minio")

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _refresh)
    app = _make_app(system_role="admin")

    with TestClient(app) as client:
        response = client.post("/api/skills/reload")

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to invalidate skills cache."}
    assert "/srv/company/minio" not in response.text


def test_reload_worker_failure_returns_500_preserves_last_good_cache_and_can_retry(monkeypatch, tmp_path: Path) -> None:
    _write_skill(tmp_path, "cached-skill", "last known good description")
    storage = LocalSkillStorage(host_path=str(tmp_path))
    last_good_skills = storage.load_skills(enabled_only=True)

    _write_skill(tmp_path, "cached-skill", "recovered description")
    recovered_skills = storage.load_skills(enabled_only=True)
    load_count = 0

    def _load_enabled_skills():
        nonlocal load_count
        load_count += 1
        if load_count == 1:
            raise PermissionError("mounted skills unavailable at /srv/company/minio")
        return recovered_skills

    monkeypatch.setattr(prompt_module, "_load_enabled_skills_sync", _load_enabled_skills)
    _reset_prompt_cache_state()
    with prompt_module._enabled_skills_lock:
        prompt_module._enabled_skills_cache = last_good_skills

    try:
        app = _make_app(system_role="admin")
        with TestClient(app) as client:
            failed_response = client.post("/api/skills/reload")

            assert failed_response.status_code == 500
            assert failed_response.json() == {"detail": "Failed to invalidate skills cache."}
            assert "mounted skills unavailable" not in failed_response.text
            assert "/srv/company/minio" not in failed_response.text

            with prompt_module._enabled_skills_lock:
                assert prompt_module._enabled_skills_cache == last_good_skills
                assert prompt_module._enabled_skills_refresh_active is False

            recovered_response = client.post("/api/skills/reload")

        assert recovered_response.status_code == 200
        assert recovered_response.json() == _SUCCESS_RESPONSE
        with prompt_module._enabled_skills_lock:
            assert prompt_module._enabled_skills_cache == recovered_skills
    finally:
        _reset_prompt_cache_state()


def test_reload_invalidates_all_user_caches_and_rescans_external_changes(monkeypatch, tmp_path: Path) -> None:
    _write_skill(tmp_path, "changed-skill", "old description")
    _write_skill(tmp_path, "removed-skill", "removed description")

    storage = LocalSkillStorage(host_path=str(tmp_path))
    config = SimpleNamespace(
        skills=SimpleNamespace(
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
            get_skills_path=lambda: tmp_path,
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda **_kwargs: storage)
    monkeypatch.setattr(prompt_module, "get_or_new_user_skill_storage", lambda _user_id, **_kwargs: storage)
    _reset_prompt_cache_state()

    try:
        alice_before = prompt_module.get_enabled_skills_for_config(config, user_id="alice")
        bob_before = prompt_module.get_enabled_skills_for_config(config, user_id="bob")
        assert {skill.name for skill in alice_before} == {"changed-skill", "removed-skill"}
        assert {skill.name for skill in bob_before} == {"changed-skill", "removed-skill"}

        _write_skill(tmp_path, "changed-skill", "new description")
        _write_skill(tmp_path, "added-skill", "added description")
        (tmp_path / "public" / "removed-skill" / "SKILL.md").unlink()

        anyio.run(prompt_module.refresh_skills_system_prompt_cache_async)

        with prompt_module._enabled_skills_lock:
            assert prompt_module._enabled_skills_by_config_cache == {}

        alice_after = prompt_module.get_enabled_skills_for_config(config, user_id="alice")
        skills_by_name = {skill.name: skill for skill in alice_after}
        assert set(skills_by_name) == {"added-skill", "changed-skill"}
        assert skills_by_name["changed-skill"].description == "new description"

        rendered_prompt = prompt_module.get_skills_prompt_section(app_config=config, user_id="alice")
        assert "added-skill" in rendered_prompt
        assert "new description" in rendered_prompt
        assert "removed-skill" not in rendered_prompt
    finally:
        _reset_prompt_cache_state()


def test_reload_does_not_allow_inflight_user_scan_to_repopulate_stale_cache(monkeypatch, tmp_path: Path) -> None:
    _write_skill(tmp_path, "changed-skill", "old description")

    storage = LocalSkillStorage(host_path=str(tmp_path))
    config = SimpleNamespace(
        skills=SimpleNamespace(
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
            get_skills_path=lambda: tmp_path,
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )
    first_scan_started = threading.Event()
    release_first_scan = threading.Event()
    user_load_count = 0

    class BlockingFirstLoadStorage:
        def load_skills(self, *, enabled_only: bool):
            nonlocal user_load_count
            user_load_count += 1
            skills = storage.load_skills(enabled_only=enabled_only)
            if user_load_count == 1:
                first_scan_started.set()
                assert release_first_scan.wait(timeout=5)
            return skills

    user_storage = BlockingFirstLoadStorage()
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda **_kwargs: storage)
    monkeypatch.setattr(prompt_module, "get_or_new_user_skill_storage", lambda _user_id, **_kwargs: user_storage)
    _reset_prompt_cache_state()

    first_result = []
    first_error = []

    def _load_for_alice() -> None:
        try:
            first_result.extend(prompt_module.get_enabled_skills_for_config(config, user_id="alice"))
        except BaseException as exc:  # pragma: no cover - surfaced by the main test thread
            first_error.append(exc)

    load_thread = threading.Thread(target=_load_for_alice)
    load_thread.start()
    try:
        assert first_scan_started.wait(timeout=5)
        _write_skill(tmp_path, "changed-skill", "new description")

        anyio.run(prompt_module.refresh_skills_system_prompt_cache_async)
        release_first_scan.set()
        load_thread.join(timeout=5)

        assert not load_thread.is_alive()
        assert first_error == []
        assert first_result[0].description == "old description"
        with prompt_module._enabled_skills_lock:
            assert prompt_module._enabled_skills_by_config_cache == {}

        next_result = prompt_module.get_enabled_skills_for_config(config, user_id="alice")
        assert next_result[0].description == "new description"
        assert user_load_count == 2
    finally:
        release_first_scan.set()
        load_thread.join(timeout=5)
        _reset_prompt_cache_state()


def test_reload_refresh_raises_when_background_scan_wait_times_out(monkeypatch) -> None:
    wait_timeouts = []

    class NeverCompletesEvent:
        def wait(self, timeout=None) -> bool:
            wait_timeouts.append(timeout)
            return False

    monkeypatch.setattr(prompt_module, "_invalidate_enabled_skills_cache", lambda: NeverCompletesEvent())

    with pytest.raises(TimeoutError, match="Timed out waiting for enabled skills cache refresh"):
        anyio.run(prompt_module.refresh_skills_system_prompt_cache_async)

    assert wait_timeouts == [prompt_module._ENABLED_SKILLS_REFRESH_WAIT_TIMEOUT_SECONDS]
