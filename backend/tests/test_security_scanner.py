from types import SimpleNamespace

import pytest

from deerflow.skills.security_scanner import scan_skill_content


@pytest.mark.anyio
async def test_scan_skill_content_blocks_when_model_unavailable(monkeypatch):
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=None))
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_system_model_name", lambda task_override=None: None)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = await scan_skill_content("---\nname: demo-skill\ndescription: demo\n---\n", executable=False)

    assert result.decision == "block"
    assert "manual review required" in result.reason


@pytest.mark.anyio
async def test_scan_skill_content_uses_system_model_name(monkeypatch):
    """Verify scan_skill_content passes the resolved system model name to create_chat_model."""
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name="task-model"))
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)

    captured = {}

    def _fake_get_system_model_name(task_override=None):
        return task_override or "fallback"

    def _fake_create_chat_model(**kwargs):
        captured["name"] = kwargs.get("name")
        raise RuntimeError("boom")

    monkeypatch.setattr("deerflow.skills.security_scanner.get_system_model_name", _fake_get_system_model_name)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", _fake_create_chat_model)

    await scan_skill_content("---\nname: demo-skill\ndescription: demo\n---\n", executable=False)

    assert captured["name"] == "task-model"


@pytest.mark.anyio
async def test_scan_skill_content_falls_back_when_no_task_override(monkeypatch):
    """When task_override is None, get_system_model_name returns the system default."""
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=None))
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)

    captured = {}

    def _fake_get_system_model_name(task_override=None):
        return "system-default"

    def _fake_create_chat_model(**kwargs):
        captured["name"] = kwargs.get("name")
        raise RuntimeError("boom")

    monkeypatch.setattr("deerflow.skills.security_scanner.get_system_model_name", _fake_get_system_model_name)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", _fake_create_chat_model)

    await scan_skill_content("---\nname: demo-skill\ndescription: demo\n---\n", executable=False)

    assert captured["name"] == "system-default"
