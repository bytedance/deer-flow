"""Tests for subagent availability and prompt exposure under local bash hardening."""

from types import SimpleNamespace

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.subagents import registry as registry_module


def test_get_available_subagent_names_hides_bash_when_host_bash_disabled(monkeypatch) -> None:
    monkeypatch.setattr(registry_module, "is_host_bash_allowed", lambda: False)

    names = registry_module.get_available_subagent_names()

    assert names == ["general-purpose"]


def test_get_available_subagent_names_keeps_bash_when_allowed(monkeypatch) -> None:
    monkeypatch.setattr(registry_module, "is_host_bash_allowed", lambda: True)

    names = registry_module.get_available_subagent_names()

    assert names == ["general-purpose", "bash"]


def test_build_subagent_section_hides_bash_examples_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda **_kwargs: ["general-purpose"])

    section = prompt_module._build_subagent_section(3)

    # When bash is not available, it should not appear at all (aligned with Codex:
    # unavailable roles are omitted, not listed as disabled)
    assert "**bash**" not in section
    assert 'bash("npm test")' not in section
    assert 'read_file("/mnt/user-data/workspace/README.md")' in section
    assert "available tools (ls, read_file, web_search, etc.)" in section


def test_build_subagent_section_includes_bash_when_available(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda **_kwargs: ["general-purpose", "bash"])

    section = prompt_module._build_subagent_section(3)

    assert "Routine git, build, test, or deploy operations are not sufficient reason to delegate" in section
    assert 'bash("npm test")' in section
    assert "available tools (bash, ls, read_file, web_search, etc.)" in section


def test_build_subagent_section_lists_only_caller_allowlisted_subagents(monkeypatch) -> None:
    def available(*, allowed_subagents, **_kwargs):
        return [name for name in ["planner", "writer"] if name in allowed_subagents]

    monkeypatch.setattr(prompt_module, "get_available_subagent_names", available)
    monkeypatch.setattr(
        registry_module,
        "get_subagent_config",
        lambda name, **_kwargs: SimpleNamespace(description=f"Managed {name}"),
    )

    section = prompt_module._build_subagent_section(3, allowed_subagents=["planner"])

    assert "**planner**" in section
    assert "**writer**" not in section


def test_build_subagent_section_threads_user_id_to_custom_agent_lookups(monkeypatch) -> None:
    captured = {}

    def available(**kwargs):
        captured["available"] = kwargs
        return ["writer"]

    def config(name, **kwargs):
        captured["config"] = (name, kwargs)
        return SimpleNamespace(description="User writer")

    monkeypatch.setattr(prompt_module, "get_available_subagent_names", available)
    monkeypatch.setattr(registry_module, "get_subagent_config", config)

    section = prompt_module._build_subagent_section(3, user_id="user-1")

    assert "**writer**: User writer" in section
    assert captured["available"]["user_id"] == "user-1"
    assert captured["config"] == (
        "writer",
        {"app_config": None, "user_id": "user-1"},
    )


def test_build_subagent_section_is_empty_for_explicit_hard_deny(monkeypatch) -> None:
    monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda *, allowed_subagents, **_kwargs: allowed_subagents)

    assert prompt_module._build_subagent_section(3, allowed_subagents=[]) == ""


def test_bash_subagent_prompt_mentions_workspace_relative_paths() -> None:
    from deerflow.subagents.builtins.bash_agent import BASH_AGENT_CONFIG

    assert "Treat `/mnt/user-data/workspace` as the default working directory for file IO" in BASH_AGENT_CONFIG.system_prompt
    assert "`hello.txt`, `../uploads/input.csv`, and `../outputs/result.md`" in BASH_AGENT_CONFIG.system_prompt


def test_general_purpose_subagent_prompt_mentions_workspace_relative_paths() -> None:
    from deerflow.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG

    assert "Treat `/mnt/user-data/workspace` as the default working directory for coding and file IO" in GENERAL_PURPOSE_CONFIG.system_prompt
    assert "`hello.txt`, `../uploads/input.csv`, and `../outputs/result.md`" in GENERAL_PURPOSE_CONFIG.system_prompt


def test_general_purpose_subagent_prompt_prohibits_task_tool() -> None:
    """The system prompt must explicitly tell the LLM that `task` is unavailable.

    Without this, subagents may attempt to call `task` after seeing the parent
    agent use it, triggering a LangGraph tool validation error (#4159).
    """
    from deerflow.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG

    prompt = GENERAL_PURPOSE_CONFIG.system_prompt
    assert "task" in prompt.lower()
    assert "NOT available" in prompt or "must NEVER" in prompt
    assert "disallowed_tools" not in prompt  # don't leak internal implementation details
