from types import SimpleNamespace

from deerflow.agents.lead_agent import prompt as prompt_module


def test_build_custom_mounts_section_returns_empty_when_no_mounts(monkeypatch):
    config = SimpleNamespace(sandbox=SimpleNamespace(mounts=[]))
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    assert prompt_module._build_custom_mounts_section() == ""


def test_build_custom_mounts_section_lists_configured_mounts(monkeypatch):
    mounts = [
        SimpleNamespace(container_path="/home/user/shared", read_only=False),
        SimpleNamespace(container_path="/mnt/reference", read_only=True),
    ]
    config = SimpleNamespace(sandbox=SimpleNamespace(mounts=mounts))
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    section = prompt_module._build_custom_mounts_section()

    assert "**Custom Mounted Directories:**" in section
    assert "`/home/user/shared`" in section
    assert "read-write" in section
    assert "`/mnt/reference`" in section
    assert "read-only" in section


def test_apply_prompt_template_includes_custom_mounts(monkeypatch):
    mounts = [SimpleNamespace(container_path="/home/user/shared", read_only=False)]
    config = SimpleNamespace(
        sandbox=SimpleNamespace(mounts=mounts),
        skills=SimpleNamespace(container_path="/mnt/skills"),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr(prompt_module, "load_skills", lambda enabled_only=True: [])
    monkeypatch.setattr(prompt_module, "get_deferred_tools_prompt_section", lambda: "")
    monkeypatch.setattr(prompt_module, "_build_acp_section", lambda: "")
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda agent_name=None: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda agent_name=None: "")

    prompt = prompt_module.apply_prompt_template()

    assert "`/home/user/shared`" in prompt
    assert "Custom Mounted Directories" in prompt
