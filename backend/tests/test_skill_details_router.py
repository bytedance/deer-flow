"""Read-only full skill details are limited to skills visible to the caller."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router
from deerflow.skills.types import Skill, SkillCategory


def test_visible_skill_details_returns_complete_skill_markdown(monkeypatch, tmp_path):
    skill_file = tmp_path / "academic-paper-review" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("---\nname: academic-paper-review\ndescription: Short intro\n---\n\n# Complete instructions\n", encoding="utf-8")
    visible = Skill("academic-paper-review", "Short intro", None, skill_file.parent, skill_file, Path("academic-paper-review"), SkillCategory.PUBLIC)
    app = make_authed_test_app(user_factory=lambda: User(id=uuid4(), email="u@example.com", password_hash="x", system_role="user"))
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    app.include_router(skills_router.router)
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: SimpleNamespace(load_skills=lambda **_kwargs: [visible]))

    with TestClient(app) as client:
        response = client.get("/api/skills/academic-paper-review/details")

    assert response.status_code == 200
    assert "# Complete instructions" in response.json()["content"]


def test_unknown_skill_detail_returns_not_found(monkeypatch):
    app = make_authed_test_app(user_factory=lambda: User(id=uuid4(), email="u@example.com", password_hash="x", system_role="user"))
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    app.include_router(skills_router.router)
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda _config: SimpleNamespace(load_skills=lambda **_kwargs: []))

    with TestClient(app) as client:
        response = client.get("/api/skills/not-visible/details")

    assert response.status_code == 404
