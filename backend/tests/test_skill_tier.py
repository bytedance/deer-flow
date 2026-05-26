"""Tests for skill tier management: filtering, updating, and batch operations."""

import json
from pathlib import Path
from types import SimpleNamespace

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
    """Create a fake storage that returns the given skills."""

    class FakeStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            result = skills
            if enabled_only:
                result = [s for s in result if s.enabled]
            return result

    return FakeStorage()


def _base_config():
    return SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: Path("/tmp"), container_path="/mnt/skills"),
    )


# ---- list with tier filter ----


def test_list_skills_returns_tier_field():
    skills = [_make_skill("deep-research", tier=SkillTier.FOUNDATION), _make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL)]
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage(skills)

    with TestClient(app) as client:
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 2
        tiers = {s["name"]: s["tier"] for s in data["skills"]}
        assert tiers["deep-research"] == "foundation"
        assert tiers["vibration-fault-diagnosis"] == "core-industrial"


def test_list_skills_filter_by_tier():
    skills = [
        _make_skill("deep-research", tier=SkillTier.FOUNDATION),
        _make_skill("data-analysis", tier=SkillTier.FOUNDATION),
        _make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL),
        _make_skill("ins-device-analysis", tier=SkillTier.CORE_INDUSTRIAL),
    ]
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage(skills)

    with TestClient(app) as client:
        resp = client.get("/api/skills?tier=core-industrial")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 2
        names = {s["name"] for s in data["skills"]}
        assert names == {"vibration-fault-diagnosis", "ins-device-analysis"}

        resp = client.get("/api/skills?tier=foundation")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 2
        names = {s["name"] for s in data["skills"]}
        assert names == {"deep-research", "data-analysis"}


def test_list_skills_no_filter_returns_all():
    skills = [_make_skill("a", tier=SkillTier.FOUNDATION), _make_skill("b", tier=SkillTier.CORE_INDUSTRIAL)]
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage(skills)

    with TestClient(app) as client:
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        assert len(resp.json()["skills"]) == 2


# ---- tier update endpoint ----


def test_update_skill_tier(monkeypatch, tmp_path):
    skill = _make_skill("my-skill", tier=SkillTier.FOUNDATION)
    config = _base_config()
    app = _make_test_app(config)

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(json.dumps({"mcpServers": {}, "skills": {"my-skill": {"enabled": True, "tier": "foundation"}}}), encoding="utf-8")
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig

    def _make_reload_storage():
        """Storage that re-reads tier from config file on each load_skills call."""

        class TierAwareStorage:
            def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
                ext = ExtensionsConfig.from_file(str(config_file))
                fresh = _make_skill("my-skill", tier=SkillTier(ext.get_skill_tier("my-skill")))
                return [fresh]

        return TierAwareStorage()

    skills_router.get_or_new_skill_storage = lambda **kw: _make_reload_storage()
    injected = ExtensionsConfig.from_file(str(config_file))
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda *a: None)

    async def _noop():
        pass

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop)

    with TestClient(app) as client:
        resp = client.put("/api/skills/my-skill/tier", json={"tier": "core-industrial"})
        assert resp.status_code == 200
        assert resp.json()["tier"] == "core-industrial"

        written = json.loads(config_file.read_text(encoding="utf-8"))
        assert written["skills"]["my-skill"]["tier"] == "core-industrial"


def test_update_skill_tier_not_found(monkeypatch):
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage([])

    with TestClient(app) as client:
        resp = client.put("/api/skills/nonexistent/tier", json={"tier": "core-industrial"})
        assert resp.status_code == 404


# ---- batch tier update ----


def test_batch_update_skill_tier(monkeypatch, tmp_path):
    skills = [
        _make_skill("skill-a", tier=SkillTier.FOUNDATION),
        _make_skill("skill-b", tier=SkillTier.FOUNDATION),
        _make_skill("skill-c", tier=SkillTier.CORE_INDUSTRIAL),
    ]
    config = _base_config()
    app = _make_test_app(config)

    config_file = tmp_path / "extensions_config.json"
    config_file.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", lambda *a: config_file)

    from deerflow.config.extensions_config import ExtensionsConfig

    def _make_reload_storage():
        class TierAwareStorage:
            def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
                ext = ExtensionsConfig.from_file(str(config_file))
                result = []
                for s in skills:
                    tier_str = ext.get_skill_tier(s.name)
                    result.append(_make_skill(s.name, tier=SkillTier(tier_str)))
                return result

        return TierAwareStorage()

    skills_router.get_or_new_skill_storage = lambda **kw: _make_reload_storage()
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: ExtensionsConfig.from_file(str(config_file)))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda *a: None)

    async def _noop():
        pass

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop)

    with TestClient(app) as client:
        resp = client.put(
            "/api/skills/batch-tier",
            json={"skill_names": ["skill-a", "skill-b"], "tier": "core-industrial"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 2
        for s in data["skills"]:
            assert s["tier"] == "core-industrial"


def test_batch_update_skill_tier_not_found():
    skills = [_make_skill("existing-skill")]
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage(skills)

    with TestClient(app) as client:
        resp = client.put(
            "/api/skills/batch-tier",
            json={"skill_names": ["nonexistent"], "tier": "core-industrial"},
        )
        assert resp.status_code == 404


def test_batch_update_skill_tier_empty_list():
    config = _base_config()
    app = _make_test_app(config)
    skills_router.get_or_new_skill_storage = lambda **kw: _fake_storage([])

    with TestClient(app) as client:
        resp = client.put(
            "/api/skills/batch-tier",
            json={"skill_names": [], "tier": "core-industrial"},
        )
        assert resp.status_code == 400


# ---- SkillTier enum ----


def test_skill_tier_enum_values():
    assert SkillTier.CORE_INDUSTRIAL.value == "core-industrial"
    assert SkillTier.FOUNDATION.value == "foundation"


def test_skill_default_tier_is_foundation():
    skill = Skill(
        name="test",
        description="d",
        license=None,
        skill_dir=Path("."),
        skill_file=Path("."),
        relative_path=Path("."),
        category=SkillCategory.PUBLIC,
    )
    assert skill.tier == SkillTier.FOUNDATION


# ---- ExtensionsConfig tier helpers ----


def test_extensions_config_get_skill_tier_default():
    from deerflow.config.extensions_config import ExtensionsConfig

    config = ExtensionsConfig(skills={})
    assert config.get_skill_tier("nonexistent") == "foundation"


def test_extensions_config_get_skill_tier_set():
    from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig

    config = ExtensionsConfig(skills={"my-skill": SkillStateConfig(enabled=True, tier="core-industrial")})
    assert config.get_skill_tier("my-skill") == "core-industrial"


def test_extensions_config_get_skill_tier_none_falls_back():
    from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig

    config = ExtensionsConfig(skills={"my-skill": SkillStateConfig(enabled=True, tier=None)})
    assert config.get_skill_tier("my-skill") == "foundation"
