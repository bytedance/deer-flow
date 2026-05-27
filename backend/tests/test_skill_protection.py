"""Tests for skill protection: core-industrial skills cannot be disabled directly.

Locks the invariants from the industrial-intelligence-primary-track change:
- `PUT /api/skills/{name}` with enabled=false returns 409 for core-industrial skills
- `PUT /api/skills/batch-tier` rejects bulk demotion of core-industrial skills
- Tier changes (industrial → foundation) remain available for explicit admin actions
- All tier change attempts and rejections are audit-logged via logger.warning/info
"""

import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import skills as skills_router
from deerflow.skills.types import Skill, SkillCategory, SkillTier


def _make_skill(name: str, *, tier: SkillTier = SkillTier.FOUNDATION, enabled: bool = True) -> Skill:
    skill_dir = Path(f"/tmp/{name}")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category=SkillCategory.PUBLIC,
        enabled=enabled,
        tier=tier,
    )


def _make_test_app(config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    app.include_router(skills_router.router)
    return app


def _fake_storage(skills: list[Skill]):
    class FakeStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            result = skills
            if enabled_only:
                result = [s for s in result if s.enabled]
            return result

    return FakeStorage()


def _base_config():
    from types import SimpleNamespace

    return SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: Path("/tmp"), container_path="/mnt/skills"),
    )


def _install_noop_side_effects(monkeypatch) -> None:
    async def _noop():
        pass

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop)
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda *a: None)


# ---- disable rejection ----


def test_disable_industrial_skill_rejected_with_409(monkeypatch, tmp_path, caplog):
    industrial_skill = _make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL)
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage([industrial_skill])

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {}, "skills": {"vibration-fault-diagnosis": {"enabled": True, "tier": "core-industrial"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig

    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    _install_noop_side_effects(monkeypatch)

    with TestClient(app) as client, caplog.at_level(logging.WARNING):
        resp = client.put("/api/skills/vibration-fault-diagnosis", json={"enabled": False})
        assert resp.status_code == 409
        assert "Industrial skills cannot be disabled" in resp.json()["detail"]
        # Config file must not be modified
        written = json.loads(config_file.read_text(encoding="utf-8"))
        assert written["skills"]["vibration-fault-diagnosis"]["enabled"] is True
        # Audit log emitted — message text mentions the skill name and "disable" rejection
        assert any("disable" in rec.message.lower() and "vibration-fault-diagnosis" in rec.message for rec in caplog.records)


def test_enable_industrial_skill_allowed(monkeypatch, tmp_path):
    """Enabling an industrial skill (or toggling it on) must still work."""
    config = _base_config()
    app = _make_test_app(config)

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {}, "skills": {"vibration-fault-diagnosis": {"enabled": False, "tier": "core-industrial"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig

    class ReloadStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            ext = ExtensionsConfig.from_file(str(config_file))
            state = ext.skills.get("vibration-fault-diagnosis")
            enabled = state.enabled if state else True
            return [_make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL, enabled=enabled)]

    skills_router.get_or_new_skill_storage = lambda **kw: ReloadStorage()
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    _install_noop_side_effects(monkeypatch)

    with TestClient(app) as client:
        resp = client.put("/api/skills/vibration-fault-diagnosis", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True


def test_disable_foundation_skill_allowed(monkeypatch, tmp_path):
    """Foundation skills can still be disabled — protection only applies to core-industrial."""
    config = _base_config()
    app = _make_test_app(config)

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {}, "skills": {"deep-research": {"enabled": True, "tier": "foundation"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig

    class ReloadStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            ext = ExtensionsConfig.from_file(str(config_file))
            state = ext.skills.get("deep-research")
            enabled = state.enabled if state else True
            return [_make_skill("deep-research", tier=SkillTier.FOUNDATION, enabled=enabled)]

    skills_router.get_or_new_skill_storage = lambda **kw: ReloadStorage()
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    _install_noop_side_effects(monkeypatch)

    with TestClient(app) as client:
        resp = client.put("/api/skills/deep-research", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False


# ---- bulk demotion rejection ----


def test_batch_demote_industrial_skills_rejected_with_400(monkeypatch, caplog):
    skills = [
        _make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL),
        _make_skill("ins-device-analysis", tier=SkillTier.CORE_INDUSTRIAL),
        _make_skill("deep-research", tier=SkillTier.FOUNDATION),
    ]
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage(skills)

    _install_noop_side_effects(monkeypatch)

    with TestClient(app) as client, caplog.at_level(logging.WARNING):
        resp = client.put(
            "/api/skills/batch-tier",
            json={
                "skill_names": ["vibration-fault-diagnosis", "ins-device-analysis", "deep-research"],
                "tier": "foundation",
            },
        )
        assert resp.status_code == 400
        assert "Bulk demotion of industrial skills is not allowed" in resp.json()["detail"]
        # Audit log emitted — message text mentions "bulk demotion"
        assert any("bulk demotion" in rec.message.lower() for rec in caplog.records)


def test_batch_promote_to_industrial_allowed(monkeypatch, tmp_path):
    """Bulk promotion (foundation → industrial) is not restricted."""
    config = _base_config()
    app = _make_test_app(config)

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig

    class ReloadStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            ext = ExtensionsConfig.from_file(str(config_file))
            result = []
            for name in ("a", "b"):
                tier_str = ext.get_skill_tier(name)
                result.append(_make_skill(name, tier=SkillTier(tier_str)))
            return result

    skills_router.get_or_new_skill_storage = lambda **kw: ReloadStorage()
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    _install_noop_side_effects(monkeypatch)

    with TestClient(app) as client:
        resp = client.put(
            "/api/skills/batch-tier",
            json={"skill_names": ["a", "b"], "tier": "core-industrial"},
        )
        assert resp.status_code == 200
        for s in resp.json()["skills"]:
            assert s["tier"] == "core-industrial"


# ---- tier change audit logging ----


def test_individual_tier_change_audit_log(monkeypatch, tmp_path, caplog):
    skill = _make_skill("my-skill", tier=SkillTier.CORE_INDUSTRIAL)
    config = _base_config()
    app = _make_test_app(config)

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {}, "skills": {"my-skill": {"enabled": True, "tier": "core-industrial"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig

    class ReloadStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            ext = ExtensionsConfig.from_file(str(config_file))
            return [_make_skill("my-skill", tier=SkillTier(ext.get_skill_tier("my-skill")))]

    skills_router.get_or_new_skill_storage = lambda **kw: ReloadStorage()
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    _install_noop_side_effects(monkeypatch)

    with TestClient(app) as client, caplog.at_level(logging.INFO):
        resp = client.put("/api/skills/my-skill/tier", json={"tier": "foundation"})
        assert resp.status_code == 200
        # Audit log mentions tier change
        assert any("tier" in rec.message.lower() for rec in caplog.records)
