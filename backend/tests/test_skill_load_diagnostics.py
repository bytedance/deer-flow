"""Management-only YAML diagnostics: scope, redaction and recovery."""

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from support.symlinks import symlink_or_skip

from app.gateway.auth.models import User
from app.gateway.routers import skills as routes
from deerflow.config.paths import Paths
from deerflow.skills.storage import reset_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

BAD = "---\nname: broken\ndescription: private-value: detail\n---\n"
GOOD = '---\nname: broken\ndescription: "private-value: detail"\n---\n'
USER_ID = "00000000-0000-0000-0000-000000000001"


def write(root: Path, package: str, content: str = BAD) -> Path:
    path = root / package / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    return path


@pytest.fixture
def scope(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    config = SimpleNamespace(skills=SimpleNamespace(get_skills_path=lambda: tmp_path / "global", container_path="/mnt/skills"))
    storage = UserScopedSkillStorage(USER_ID, app_config=config)
    reset_skill_storage()
    yield paths, config, storage
    reset_skill_storage()


def test_diagnostics_are_separate_and_disappear_after_correction(scope):
    paths, _, storage = scope
    root = paths.user_custom_skills_dir(USER_ID)
    broken = write(root, "namespace/broken")
    write(root, "valid", GOOD.replace("broken", "valid"))
    write(root, ".hidden")
    write(root, "valid/nested")
    assert [s.name for s in storage.load_skills()] == ["valid"]
    result = [asdict(d) for d in storage.load_custom_skill_diagnostics()]
    assert result == [{"package": "namespace/broken", "path": "SKILL.md", "code": "invalid_frontmatter", "hint": "quote_colon_value", "line": 3, "column": 27}]
    assert str(paths.base_dir) not in str(result)
    assert "private-value" not in str(result)
    broken.write_text(GOOD, encoding="utf-8")
    assert storage.load_custom_skill_diagnostics() == []
    assert {s.name for s in storage.load_skills()} == {"valid", "broken"}


@pytest.mark.parametrize("prefix", ["---\n", "\ufeff---\r\n\r\n"])
def test_locations_match_actual_file_and_other_yaml_errors_have_no_colon_hint(scope, prefix):
    paths, _, storage = scope
    write(paths.user_custom_skills_dir(USER_ID), "broken", prefix + "name: broken\ndescription: [one, two\n---\n")
    result = storage.load_custom_skill_diagnostics()
    assert len(result) == 1
    assert result[0].code == "invalid_frontmatter"
    assert result[0].hint is None
    assert result[0].line == prefix.count("\n") + 2
    assert result[0].column == 23


def test_other_owners_and_global_sources_are_excluded(scope):
    paths, config, storage = scope
    write(paths.user_custom_skills_dir("another-user"), "other-private")
    for category in ["custom", "public"]:
        write(config.skills.get_skills_path() / category, "global-private")
    write(paths.integration_skills_dir(), "provider/integration-private")
    assert storage.load_custom_skill_diagnostics() == []


def test_comment_colon_does_not_turn_indentation_error_into_quoting_hint(scope):
    paths, _, storage = scope
    write(paths.user_custom_skills_dir(USER_ID), "broken", "---\nname: broken\ndescription: normal\n  bad: value # comment: words\n---\n")
    result = storage.load_custom_skill_diagnostics()
    assert len(result) == 1
    assert result[0].hint is None


def test_owned_file_symlink_preserves_skill_filename(scope):
    paths, _, storage = scope
    root = paths.user_custom_skills_dir(USER_ID)
    source = root / "linked" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text(BAD, encoding="utf-8")
    symlink_or_skip(source.parent / "SKILL.md", source)
    result = storage.load_custom_skill_diagnostics()
    assert len(result) == 1
    assert result[0].package == "linked"
    assert result[0].path == "SKILL.md"


@pytest.mark.parametrize("kind", ["package", "file", "root"])
def test_symlink_escape_is_not_read(scope, monkeypatch, kind):
    paths, _, storage = scope
    root = paths.user_custom_skills_dir(USER_ID)
    target = write(paths.user_custom_skills_dir("another-user"), "private")
    if kind == "root":
        root.parent.mkdir(parents=True, exist_ok=True)
        symlink_or_skip(root, target.parent.parent, target_is_directory=True)
    elif kind == "package":
        root.mkdir(parents=True)
        symlink_or_skip(root / "escape", target.parent, target_is_directory=True)
    else:
        (root / "escape").mkdir(parents=True)
        symlink_or_skip(root / "escape" / "SKILL.md", target)
    original = Path.read_text

    def guarded_read(path, *args, **kwargs):
        assert path.resolve() != target.resolve(), "must authorize before reading another owner's file"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    assert storage.load_custom_skill_diagnostics() == []


def client_for(config, role="admin"):
    user = User(id=UUID(USER_ID), email="diagnostics@example.com", password_hash="x", system_role=role)
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.dependency_overrides[routes.get_config] = lambda: config
    app.include_router(routes.router)
    return TestClient(app)


def test_management_route_uses_caller_scope(scope):
    paths, config, _ = scope
    write(paths.user_custom_skills_dir(USER_ID), "mine")
    write(paths.user_custom_skills_dir("another-user"), "other-private")
    with client_for(config) as client:
        response = client.get("/api/skills/diagnostics/custom")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [d["package"] for d in response.json()["diagnostics"]] == ["mine"]
    for private in ["private-value", "other-private", str(paths.base_dir)]:
        assert private not in response.text


def test_non_admin_cannot_scan_diagnostics(scope, monkeypatch):
    _, config, _ = scope
    monkeypatch.setattr(routes, "_get_user_skill_storage", lambda _: pytest.fail("unauthorized scan"))
    with client_for(config, "user") as client:
        assert client.get("/api/skills/diagnostics/custom").status_code == 403


def test_diagnostic_failure_does_not_expose_exception(scope, monkeypatch):
    _, config, storage = scope

    def fail():
        raise OSError("private /srv/customer/secret SKILL.md source")

    monkeypatch.setattr(storage, "load_custom_skill_diagnostics", fail)
    monkeypatch.setattr(routes, "_get_user_skill_storage", lambda _: storage)
    with client_for(config) as client:
        response = client.get("/api/skills/diagnostics/custom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to load custom skill diagnostics."}


def test_correction_and_reload_restore_runtime_catalog(scope, monkeypatch):
    from deerflow.agents.lead_agent import prompt

    paths, config, storage = scope
    broken = write(paths.user_custom_skills_dir(USER_ID), "broken")
    monkeypatch.setattr(prompt, "get_or_new_user_skill_storage", lambda *_args, **_kwargs: storage)
    monkeypatch.setattr(prompt, "get_or_new_skill_storage", lambda **_kwargs: storage)
    monkeypatch.setattr(prompt, "resolve_shared_config_path", lambda: None)
    prompt.clear_skills_system_prompt_cache()
    try:
        assert prompt.get_enabled_skills_for_config(config, user_id=USER_ID) == []
        with client_for(config) as client:
            assert len(client.get("/api/skills/diagnostics/custom").json()["diagnostics"]) == 1
            broken.write_text(GOOD, encoding="utf-8")
            # A management read alone does not update the runtime's cached list.
            assert client.get("/api/skills/diagnostics/custom").json()["diagnostics"] == []
            assert prompt.get_enabled_skills_for_config(config, user_id=USER_ID) == []
            assert client.post("/api/skills/reload").status_code == 200
            assert client.get("/api/skills/diagnostics/custom").json()["diagnostics"] == []
        assert [s.name for s in prompt.get_enabled_skills_for_config(config, user_id=USER_ID)] == ["broken"]
    finally:
        prompt.clear_skills_system_prompt_cache()
