from types import SimpleNamespace

import pytest

from deerflow.skills.security_scanner import scan_skill_content


@pytest.mark.anyio
async def test_scan_skill_content_passes_run_name_to_model(monkeypatch):
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=None))
    fake_response = SimpleNamespace(content='{"decision":"allow","reason":"ok"}')

    class FakeModel:
        async def ainvoke(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return fake_response

    model = FakeModel()
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", lambda **kwargs: model)

    result = await scan_skill_content("---\nname: demo-skill\ndescription: demo\n---\n", executable=False)

    assert result.decision == "allow"
    assert model.kwargs["config"] == {"run_name": "security_agent"}


@pytest.mark.anyio
async def test_scan_skill_content_blocks_when_model_unavailable(monkeypatch):
    config = SimpleNamespace(skill_evolution=SimpleNamespace(moderation_model_name=None))
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.create_chat_model", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = await scan_skill_content("---\nname: demo-skill\ndescription: demo\n---\n", executable=False)

    assert result.decision == "block"
    assert "manual review required" in result.reason
