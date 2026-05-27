"""Tests for agent inheritance: fork with/without skills and industrial pre-enabling.

Covers tasks from the industrial-intelligence-primary-track change:
- Fork agent with explicit skills preserves them
- Fork agent with no skills (skills=None) gets industrial skills pre-enabled
- Create agent with no skills gets industrial skills pre-enabled
- Industrial agent creation emits telemetry event
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import agents as agents_router
from deerflow.config.agents_config import AgentConfig
from deerflow.skills.types import Skill, SkillCategory, SkillTier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(name: str, *, tier: SkillTier = SkillTier.FOUNDATION) -> Skill:
    skill_dir = Path(f"/tmp/{name}")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category=SkillCategory.PUBLIC,
        enabled=True,
        tier=tier,
    )


def _fake_storage(skills: list[Skill]):
    class FakeStorage:
        def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
            result = skills
            if enabled_only:
                result = [s for s in result if s.enabled]
            return result

    return FakeStorage()


def _write_agent(base_dir: Path, name: str, config: dict, soul: str = "You are helpful.", *, scope: str = "builtin") -> None:
    """Write an agent directory with config.yaml and SOUL.md."""
    if scope == "builtin":
        agent_dir = base_dir / "agents" / "builtin" / name
    elif scope == "user":
        agent_dir = base_dir / "users" / "default" / "agents" / name
    else:
        agent_dir = base_dir / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    config_copy = dict(config)
    if "name" not in config_copy:
        config_copy["name"] = name

    with open(agent_dir / "config.yaml", "w") as f:
        yaml.dump(config_copy, f)

    (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")


# ===========================================================================
# Tests
# ===========================================================================


class TestForkAgentSkillsInheritance:
    """Test that fork_agent correctly handles skills inheritance."""

    def test_fork_preserves_explicit_skills(self, tmp_path, monkeypatch):
        """Fork an agent that has explicit skills — the forked agent gets the same skills."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=tmp_path)
        _write_agent(tmp_path, "source-agent", {"name": "source-agent", "skills": ["deep-research", "code-review"]})

        # Monkeypatch get_paths, get_effective_user_id, get_current_tenant_id
        monkeypatch.setattr(agents_router, "get_paths", lambda: paths)
        monkeypatch.setattr(agents_router, "get_effective_user_id", lambda: "default")
        monkeypatch.setattr(agents_router, "get_current_tenant_id", lambda: None)
        monkeypatch.setattr(agents_router, "_require_agents_api_enabled", lambda: None)
        monkeypatch.setattr(agents_router, "_validate_agent_name", lambda n: None)
        monkeypatch.setattr(agents_router, "_normalize_agent_name", lambda n: n)

        # Mock skill storage — not used when source has explicit skills
        industrial_skills = [_make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL)]
        monkeypatch.setattr(
            "deerflow.skills.storage.get_or_new_skill_storage",
            lambda **kw: _fake_storage(industrial_skills),
        )

        # load_agent_config should return the source agent
        source_config = AgentConfig(name="source-agent", skills=["deep-research", "code-review"])
        monkeypatch.setattr(agents_router, "load_agent_config", lambda name, **kw: source_config)

        from deerflow.config.agents_config import load_builtin_agent_soul
        monkeypatch.setattr(agents_router, "load_builtin_agent_soul", lambda name: "You are helpful.")
        monkeypatch.setattr(agents_router, "load_tenant_agent_soul", lambda tid, name: None)

        app = FastAPI()
        app.include_router(agents_router.router)

        with TestClient(app) as client:
            resp = client.post("/api/agents/fork/source-agent")
            assert resp.status_code == 201
            data = resp.json()
            # Forked agent should have the same skills as source
            assert data["skills"] == ["deep-research", "code-review"]

    def test_fork_pre_enables_industrial_skills_when_source_has_none(self, tmp_path, monkeypatch):
        """Fork an agent with skills=None → industrial skills are pre-enabled."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=tmp_path)
        _write_agent(tmp_path, "generic-agent", {"name": "generic-agent"})

        monkeypatch.setattr(agents_router, "get_paths", lambda: paths)
        monkeypatch.setattr(agents_router, "get_effective_user_id", lambda: "default")
        monkeypatch.setattr(agents_router, "get_current_tenant_id", lambda: None)
        monkeypatch.setattr(agents_router, "_require_agents_api_enabled", lambda: None)
        monkeypatch.setattr(agents_router, "_validate_agent_name", lambda n: None)
        monkeypatch.setattr(agents_router, "_normalize_agent_name", lambda n: n)

        # Mock skill storage with industrial skills
        industrial_skills = [
            _make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL),
            _make_skill("ins-device-analysis", tier=SkillTier.CORE_INDUSTRIAL),
            _make_skill("deep-research", tier=SkillTier.FOUNDATION),
        ]
        monkeypatch.setattr(
            "deerflow.skills.storage.get_or_new_skill_storage",
            lambda **kw: _fake_storage(industrial_skills),
        )

        # Source agent has skills=None; forked agent should be loaded from disk
        source_config = AgentConfig(name="generic-agent", skills=None)

        def mock_load_config(name, **kw):
            user_id = kw.get("user_id")
            if user_id:
                config_path = paths.user_agent_dir(user_id, name) / "config.yaml"
                if config_path.exists():
                    with open(config_path) as f:
                        data = yaml.safe_load(f)
                    return AgentConfig(**data)
            return source_config

        monkeypatch.setattr(agents_router, "load_agent_config", mock_load_config)
        monkeypatch.setattr(agents_router, "load_builtin_agent_soul", lambda name: "Generic agent soul.")
        monkeypatch.setattr(agents_router, "load_tenant_agent_soul", lambda tid, name: None)

        app = FastAPI()
        app.include_router(agents_router.router)

        with TestClient(app) as client:
            resp = client.post("/api/agents/fork/generic-agent")
            assert resp.status_code == 201
            data = resp.json()
            # Forked agent should have industrial skills pre-enabled
            assert data["skills"] is not None
            assert "vibration-fault-diagnosis" in data["skills"]
            assert "ins-device-analysis" in data["skills"]
            # Foundation skills should NOT be included
            assert "deep-research" not in data["skills"]

    def test_fork_with_empty_skills_list_preserves_empty(self, tmp_path, monkeypatch):
        """Fork an agent with skills=[] (explicit empty) → stays empty (no pre-enabling)."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=tmp_path)
        _write_agent(tmp_path, "minimal-agent", {"name": "minimal-agent", "skills": []})

        monkeypatch.setattr(agents_router, "get_paths", lambda: paths)
        monkeypatch.setattr(agents_router, "get_effective_user_id", lambda: "default")
        monkeypatch.setattr(agents_router, "get_current_tenant_id", lambda: None)
        monkeypatch.setattr(agents_router, "_require_agents_api_enabled", lambda: None)
        monkeypatch.setattr(agents_router, "_validate_agent_name", lambda n: None)
        monkeypatch.setattr(agents_router, "_normalize_agent_name", lambda n: n)

        # Even if industrial skills exist, they shouldn't be added when skills=[] explicitly
        industrial_skills = [_make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL)]
        monkeypatch.setattr(
            "deerflow.skills.storage.get_or_new_skill_storage",
            lambda **kw: _fake_storage(industrial_skills),
        )

        source_config = AgentConfig(name="minimal-agent", skills=[])
        monkeypatch.setattr(agents_router, "load_agent_config", lambda name, **kw: source_config)
        monkeypatch.setattr(agents_router, "load_builtin_agent_soul", lambda name: "Minimal agent.")
        monkeypatch.setattr(agents_router, "load_tenant_agent_soul", lambda tid, name: None)

        app = FastAPI()
        app.include_router(agents_router.router)

        with TestClient(app) as client:
            resp = client.post("/api/agents/fork/minimal-agent")
            assert resp.status_code == 201
            data = resp.json()
            # skills=[] is not None, so industrial pre-enabling should NOT trigger
            assert data["skills"] == []


class TestCreateAgentIndustrialDefaults:
    """Test that create_agent_endpoint pre-enables industrial skills."""

    def test_create_agent_pre_enables_industrial_skills(self, tmp_path, monkeypatch):
        """Create agent without skills → industrial skills are pre-enabled."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=tmp_path)

        monkeypatch.setattr(agents_router, "get_paths", lambda: paths)
        monkeypatch.setattr(agents_router, "get_effective_user_id", lambda: "default")
        monkeypatch.setattr(agents_router, "_require_agents_api_enabled", lambda: None)
        monkeypatch.setattr(agents_router, "_validate_agent_name", lambda n: None)
        monkeypatch.setattr(agents_router, "_normalize_agent_name", lambda n: n)

        industrial_skills = [
            _make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL),
            _make_skill("ins-device-analysis", tier=SkillTier.CORE_INDUSTRIAL),
        ]
        monkeypatch.setattr(
            "deerflow.skills.storage.get_or_new_skill_storage",
            lambda **kw: _fake_storage(industrial_skills),
        )

        from deerflow.config.agents_config import load_agent_config as real_load
        def mock_load(name, **kw):
            config_path = paths.user_agent_dir("default", name) / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    data = yaml.safe_load(f)
                return AgentConfig(**data)
            raise FileNotFoundError(f"Agent {name} not found")

        monkeypatch.setattr(agents_router, "load_agent_config", mock_load)

        app = FastAPI()
        app.include_router(agents_router.router)

        with TestClient(app) as client:
            resp = client.post("/api/agents", json={
                "name": "new-industrial-agent",
                "description": "A new agent",
                "soul": "",
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["skills"] is not None
            assert "vibration-fault-diagnosis" in data["skills"]
            assert "ins-device-analysis" in data["skills"]

    def test_create_agent_with_explicit_skills_no_override(self, tmp_path, monkeypatch):
        """Create agent with explicit skills → skills are preserved as-is."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=tmp_path)

        monkeypatch.setattr(agents_router, "get_paths", lambda: paths)
        monkeypatch.setattr(agents_router, "get_effective_user_id", lambda: "default")
        monkeypatch.setattr(agents_router, "_require_agents_api_enabled", lambda: None)
        monkeypatch.setattr(agents_router, "_validate_agent_name", lambda n: None)
        monkeypatch.setattr(agents_router, "_normalize_agent_name", lambda n: n)

        industrial_skills = [_make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL)]
        monkeypatch.setattr(
            "deerflow.skills.storage.get_or_new_skill_storage",
            lambda **kw: _fake_storage(industrial_skills),
        )

        def mock_load(name, **kw):
            config_path = paths.user_agent_dir("default", name) / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    data = yaml.safe_load(f)
                return AgentConfig(**data)
            raise FileNotFoundError(f"Agent {name} not found")

        monkeypatch.setattr(agents_router, "load_agent_config", mock_load)

        app = FastAPI()
        app.include_router(agents_router.router)

        with TestClient(app) as client:
            resp = client.post("/api/agents", json={
                "name": "custom-agent",
                "description": "Custom",
                "soul": "Custom soul",
                "skills": ["deep-research"],
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["skills"] == ["deep-research"]


class TestIndustrialAgentTelemetry:
    """Test that industrial agent creation emits telemetry."""

    def test_telemetry_emitted_on_create_with_industrial_skills(self, tmp_path, monkeypatch):
        """Creating an agent that gets industrial skills pre-enabled should emit telemetry."""
        from deerflow.config.paths import Paths

        paths = Paths(base_dir=tmp_path)

        monkeypatch.setattr(agents_router, "get_paths", lambda: paths)
        monkeypatch.setattr(agents_router, "get_effective_user_id", lambda: "default")
        monkeypatch.setattr(agents_router, "get_current_tenant_id", lambda: "tenant-123")
        monkeypatch.setattr(agents_router, "_require_agents_api_enabled", lambda: None)
        monkeypatch.setattr(agents_router, "_validate_agent_name", lambda n: None)
        monkeypatch.setattr(agents_router, "_normalize_agent_name", lambda n: n)

        industrial_skills = [_make_skill("vibration-fault-diagnosis", tier=SkillTier.CORE_INDUSTRIAL)]
        monkeypatch.setattr(
            "deerflow.skills.storage.get_or_new_skill_storage",
            lambda **kw: _fake_storage(industrial_skills),
        )

        def mock_load(name, **kw):
            config_path = paths.user_agent_dir("default", name) / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    data = yaml.safe_load(f)
                return AgentConfig(**data)
            raise FileNotFoundError(f"Agent {name} not found")

        monkeypatch.setattr(agents_router, "load_agent_config", mock_load)

        # Reset telemetry metrics
        from app.gateway.routers.industrial_skills_telemetry import IndustrialSkillsMetrics
        import app.gateway.routers.industrial_skills_telemetry as telemetry_mod
        telemetry_mod._metrics = IndustrialSkillsMetrics()

        app = FastAPI()
        app.include_router(agents_router.router)

        with TestClient(app) as client:
            resp = client.post("/api/agents", json={
                "name": "telemetry-test-agent",
                "description": "Test",
                "soul": "",
            })
            assert resp.status_code == 201

        # Check telemetry was emitted
        summary = telemetry_mod._metrics.summary()
        assert summary["agent_creation"]["industrial_agents_created"] == 1
