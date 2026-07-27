from pathlib import Path
from types import SimpleNamespace

from deerflow.agents.lead_agent.prompt import get_skills_prompt_section
from deerflow.config.agents_config import AgentConfig
from deerflow.skills.types import Skill


class NamedTool:
    def __init__(self, name: str):
        self.name = name


def _make_skill(name: str, allowed_tools: list[str] | None = None, *, enabled: bool = True) -> Skill:
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=Path(f"/tmp/{name}"),
        skill_file=Path(f"/tmp/{name}/SKILL.md"),
        relative_path=Path(name),
        category="public",
        allowed_tools=tuple(allowed_tools) if allowed_tools is not None else None,
        enabled=enabled,
    )


def _mock_skill_storages(monkeypatch, skills):
    """Patch storage factories and config so get_skills_prompt_section works without config.yaml."""
    from types import SimpleNamespace

    mock_storage = SimpleNamespace(load_skills=lambda *, enabled_only: skills)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kwargs: mock_storage)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda user_id, **kwargs: mock_storage)
    monkeypatch.setattr(
        "deerflow.config.get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/skills")),
            skill_evolution=SimpleNamespace(enabled=False),
        ),
    )


def test_get_skills_prompt_section_returns_empty_when_no_skills_match(monkeypatch):
    skills = [_make_skill("skill1"), _make_skill("skill2")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    _mock_skill_storages(monkeypatch, skills)

    result = get_skills_prompt_section(available_skills={"non_existent_skill"})
    assert result == ""


def test_get_skills_prompt_section_returns_empty_when_available_skills_empty(monkeypatch):
    skills = [_make_skill("skill1"), _make_skill("skill2")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    _mock_skill_storages(monkeypatch, skills)

    result = get_skills_prompt_section(available_skills=set())
    assert result == ""


def test_get_skills_prompt_section_returns_skills(monkeypatch):
    skills = [_make_skill("skill1"), _make_skill("skill2")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    _mock_skill_storages(monkeypatch, skills)

    result = get_skills_prompt_section(available_skills={"skill1"})
    assert "skill1" in result
    assert "skill2" not in result
    assert "[built-in]" in result


def test_get_skills_prompt_section_returns_all_when_available_skills_is_none(monkeypatch):
    skills = [_make_skill("skill1"), _make_skill("skill2")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    _mock_skill_storages(monkeypatch, skills)

    result = get_skills_prompt_section(available_skills=None)
    assert "skill1" in result
    assert "skill2" in result


def test_get_skills_prompt_section_no_arg_cold_cache_loads_enabled_skills(monkeypatch):
    """#4144: a fresh process calling the no-arg helper must not render an empty
    enabled-skills list while the synchronously-loaded disabled section is populated."""
    import threading

    from deerflow.agents.lead_agent import prompt as prompt_mod

    skills = [_make_skill("skill1"), _make_skill("skill2", enabled=False)]
    mock_storage = SimpleNamespace(load_skills=lambda *, enabled_only: [s for s in skills if s.enabled or not enabled_only])
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kwargs: mock_storage)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda user_id, **kwargs: mock_storage)
    monkeypatch.setattr(
        "deerflow.config.get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/skills")),
            skill_evolution=SimpleNamespace(enabled=False),
        ),
    )
    # Cold cache: no warmed enabled-skills list, and the background refresh must
    # not fill it mid-test — the reporter's cold start loses exactly this race.
    monkeypatch.setattr(prompt_mod, "_enabled_skills_cache", None)
    monkeypatch.setattr(prompt_mod, "_ensure_enabled_skills_cache", lambda: threading.Event())

    result = get_skills_prompt_section(available_skills=None)

    assert "<available_skills>" in result
    assert "skill1" in result
    assert "<disabled_skills>" in result


def test_get_skills_prompt_section_includes_slash_activation_guidance(monkeypatch):
    skills = [_make_skill("data-analysis")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    _mock_skill_storages(monkeypatch, skills)

    result = get_skills_prompt_section(available_skills={"data-analysis"})

    assert "Explicit Slash Skill Activation" in result
    assert "The runtime injects the activated skill content" in result
    assert "do not call `read_file` for that SKILL.md again" in result


def test_get_skills_prompt_section_includes_self_evolution_rules(monkeypatch):
    skills = [_make_skill("skill1")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: skills))
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda user_id, **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: skills))
    monkeypatch.setattr(
        "deerflow.config.get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/skills")),
            skill_evolution=SimpleNamespace(enabled=True),
        ),
    )

    result = get_skills_prompt_section(available_skills=None)
    assert "Skill Self-Evolution" in result


def test_get_skills_prompt_section_includes_self_evolution_rules_without_skills(monkeypatch):
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: [])
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: []))
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda user_id, **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: []))
    monkeypatch.setattr(
        "deerflow.config.get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/skills")),
            skill_evolution=SimpleNamespace(enabled=True),
        ),
    )

    result = get_skills_prompt_section(available_skills=None)
    assert "Skill Self-Evolution" in result


def test_get_skills_prompt_section_cache_respects_skill_evolution_toggle(monkeypatch):
    skills = [_make_skill("skill1")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: skills))
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda user_id, **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: skills))
    config = SimpleNamespace(
        skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/skills")),
        skill_evolution=SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    enabled_result = get_skills_prompt_section(available_skills=None)
    assert "Skill Self-Evolution" in enabled_result

    config.skill_evolution.enabled = False
    disabled_result = get_skills_prompt_section(available_skills=None)
    assert "Skill Self-Evolution" not in disabled_result


def test_get_skills_prompt_section_uses_explicit_config_for_enabled_skills(monkeypatch):
    explicit_config = SimpleNamespace(
        skills=SimpleNamespace(container_path="/mnt/alt-skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/alt-skills")),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    def fail_get_app_config():
        raise AssertionError("ambient get_app_config() must not be used when app_config is explicit")

    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: [_make_skill("global-skill")])
    monkeypatch.setattr("deerflow.config.get_app_config", fail_get_app_config)
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.get_or_new_skill_storage",
        lambda app_config=None, **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: [_make_skill("explicit-skill")] if app_config is explicit_config else []),
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage",
        lambda user_id, app_config=None, **kwargs: __import__("types").SimpleNamespace(load_skills=lambda *, enabled_only: [_make_skill("explicit-skill")] if app_config is explicit_config else []),
    )

    result = get_skills_prompt_section(app_config=explicit_config)

    assert "explicit-skill" in result
    assert "global-skill" not in result


def test_get_skills_prompt_section_deferred_path_uses_skill_index(monkeypatch):
    """When skill_names is provided, renders <skill_index> instead of <available_skills>."""
    skills = [_make_skill("data-analysis"), _make_skill("deep-research")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    monkeypatch.setattr(
        "deerflow.config.get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills"),
            skill_evolution=SimpleNamespace(enabled=False),
        ),
    )
    # Deferred path never touches storage, but patch defensively in case of fallback.
    _null_storage = SimpleNamespace(load_skills=lambda *, enabled_only: [])
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kw: _null_storage)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda *a, **kw: _null_storage)

    # Deferred path: skill_names provided
    result = get_skills_prompt_section(
        available_skills=None,
        skill_names=frozenset({"data-analysis", "deep-research"}),
    )
    assert "<skill_index>" in result
    assert "data-analysis" in result
    assert "deep-research" in result
    assert "describe_skill" in result
    # Must NOT contain legacy full-metadata format
    assert "<available_skills>" not in result
    assert "Description for data-analysis" not in result  # descriptions excluded from index


def test_get_skills_prompt_section_legacy_path_when_skill_names_none(monkeypatch):
    """When skill_names is None, falls back to legacy <available_skills> rendering."""
    skills = [_make_skill("data-analysis")]
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt._get_enabled_skills", lambda: skills)
    monkeypatch.setattr(
        "deerflow.config.get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills"),
            skill_evolution=SimpleNamespace(enabled=False),
        ),
    )
    # Legacy path loads ALL skills (enabled + disabled) from storage for the disabled-skills section.
    _storage = SimpleNamespace(load_skills=lambda *, enabled_only: skills)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_skill_storage", lambda **kw: _storage)
    monkeypatch.setattr("deerflow.agents.lead_agent.prompt.get_or_new_user_skill_storage", lambda *a, **kw: _storage)

    # Legacy path: skill_names not provided
    result = get_skills_prompt_section(available_skills=None)
    assert "<available_skills>" in result
    assert "data-analysis" in result
    assert "Description for data-analysis" in result
    assert "<skill_index>" not in result
    assert "describe_skill" not in result


def test_make_lead_agent_empty_skills_passed_correctly(monkeypatch):
    from unittest.mock import MagicMock

    from deerflow.agents.lead_agent import agent as lead_agent_module

    # Mock dependencies
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: MagicMock())
    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)

    class MockModelConfig:
        supports_thinking = False

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = MockModelConfig()
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    captured_skills = []

    def mock_apply_prompt_template(**kwargs):
        captured_skills.append(kwargs.get("available_skills"))
        return "mock_prompt"

    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", mock_apply_prompt_template)

    # Case 1: Empty skills list
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=[]))
    lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})
    assert captured_skills[-1] == set()

    # Case 2: None skills list
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=None))
    lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})
    assert captured_skills[-1] is None

    # Case 3: Some skills list
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=["skill1"]))
    lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})
    assert captured_skills[-1] == {"skill1"}


def test_make_lead_agent_custom_skill_allowlist_does_not_activate_tool_policy(monkeypatch):
    from unittest.mock import MagicMock

    from deerflow.agents.lead_agent import agent as lead_agent_module

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=["restricted", "legacy"]))
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [_make_skill("restricted", ["read_file", "web_search"]), _make_skill("legacy", None)])
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [NamedTool("task"), NamedTool("bash"), NamedTool("read_file"), NamedTool("web_search")])

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)
    mock_app_config.tool_search.enabled = True
    mock_app_config.skills.container_path = "/mnt/skills"
    mock_app_config.skills.deferred_discovery = True  # describe_skill will be added
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    agent_kwargs = lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})

    # The custom-agent skill list controls discovery/activation, not baseline
    # tools. With deferred discovery, describe_skill is added as well.
    tool_names = [tool.name for tool in agent_kwargs["tools"]]
    assert "task" in tool_names
    assert "read_file" in tool_names
    assert "describe_skill" in tool_names


def test_skill_allowed_tools_default_does_not_preserve_read_file_for_subagents():
    from deerflow.skills.tool_policy import filter_tools_by_skill_allowed_tools

    tools = [NamedTool("read_file"), NamedTool("dataagent_query"), NamedTool("bash")]
    skills = [_make_skill("data-query", ["dataagent_query"])]

    filtered = filter_tools_by_skill_allowed_tools(tools, skills)

    assert [tool.name for tool in filtered] == ["dataagent_query"]


def test_make_lead_agent_all_legacy_skills_preserve_all_tools(monkeypatch):
    from unittest.mock import MagicMock

    from deerflow.agents.lead_agent import agent as lead_agent_module

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=None))
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [_make_skill("legacy", None)])
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [NamedTool("bash"), NamedTool("read_file")])

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    agent_kwargs = lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})

    # No skill is active yet, so the configured lead tools remain available.
    tool_names = [tool.name for tool in agent_kwargs["tools"]]
    assert tool_names == ["bash", "read_file", "update_agent", "describe_skill"]


def test_make_lead_agent_passive_empty_skill_policy_preserves_mcp_and_other_tools_when_cache_is_cold(monkeypatch):
    from unittest.mock import MagicMock

    from langchain_core.tools import tool

    from deerflow.agents.lead_agent import agent as lead_agent_module
    from deerflow.agents.lead_agent import prompt as prompt_module
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    @tool
    def lightrag_query(query: str) -> str:
        """Query a LightRAG MCP server."""
        return query

    tag_mcp_tool(lightrag_query)

    captured_deferred_setups = []

    def capture_build_middlewares(*args, **kwargs):
        captured_deferred_setups.append(kwargs["deferred_setup"])
        return []

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", capture_build_middlewares)
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        lead_agent_module,
        "load_agent_config",
        lambda x: AgentConfig(name="test", skills=["example-safe-skill"]),
    )
    monkeypatch.setattr(
        "deerflow.tools.get_available_tools",
        lambda **kwargs: [
            NamedTool("bash"),
            NamedTool("read_file"),
            NamedTool("web_search"),
            lightrag_query,
        ],
    )

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)
    mock_app_config.tool_search.enabled = True
    mock_app_config.tool_search.auto_promote_top_k = 3
    mock_storage = SimpleNamespace(load_skills=lambda *, enabled_only: [_make_skill("example-safe-skill", [])])

    with prompt_module._enabled_skills_lock:
        prompt_module._enabled_skills_cache = None
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda app_config=None, **kwargs: mock_storage)
    monkeypatch.setattr(prompt_module, "get_or_new_user_skill_storage", lambda user_id, app_config=None, **kwargs: mock_storage)
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    agent_kwargs = lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})

    tool_names = [tool.name for tool in agent_kwargs["tools"]]
    assert {"bash", "read_file", "web_search", "lightrag_query", "tool_search", "describe_skill"} <= set(tool_names)
    assert len(captured_deferred_setups) == 1
    assert captured_deferred_setups[0].deferred_names == frozenset({"lightrag_query"})


def test_default_lead_agent_does_not_apply_installed_skill_allowlists(monkeypatch):
    """Installed skills are discoverable but not active for ordinary default chat.

    A public skill with ``allowed-tools`` must not globally hide configured
    tools like ``browser_navigate`` before the user has selected a specific
    skill-owned workflow.
    """
    from unittest.mock import MagicMock

    from deerflow.agents.lead_agent import agent as lead_agent_module

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(
        lead_agent_module,
        "_load_enabled_available_skills",
        lambda available_skills, *, app_config, user_id=None: [_make_skill("skill-reviewer", ["review_skill_package"])],
    )
    monkeypatch.setattr(
        "deerflow.tools.get_available_tools",
        lambda **kwargs: [NamedTool("bash"), NamedTool("browser_navigate"), NamedTool("review_skill_package")],
    )

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)
    mock_app_config.tool_search.enabled = True
    mock_app_config.skills.container_path = "/mnt/skills"
    mock_app_config.skills.deferred_discovery = True
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    agent_kwargs = lead_agent_module.make_lead_agent({"configurable": {}})

    tool_names = [tool.name for tool in agent_kwargs["tools"]]
    assert "browser_navigate" in tool_names
    assert "bash" in tool_names
    assert "describe_skill" in tool_names


def test_make_lead_agent_fails_closed_when_skill_policy_load_fails(monkeypatch):
    from unittest.mock import MagicMock

    import pytest

    from deerflow.agents.lead_agent import agent as lead_agent_module
    from deerflow.agents.lead_agent import prompt as prompt_module

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    create_agent_mock = MagicMock()
    monkeypatch.setattr(lead_agent_module, "create_agent", create_agent_mock)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=["restricted"]))

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)

    def fail_storage(*args, **kwargs):
        raise RuntimeError("skill storage unavailable")

    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", fail_storage)
    monkeypatch.setattr(prompt_module, "get_or_new_user_skill_storage", fail_storage)
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    with pytest.raises(RuntimeError, match="skill storage unavailable"):
        lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})

    create_agent_mock.assert_not_called()


def test_make_lead_agent_drops_update_agent_on_github_channel(monkeypatch):
    """Webhook-channel runs MUST NOT see ``update_agent``.

    The lead-agent prompt actively encourages the model to call
    ``update_agent`` when the user asks it to change its own skills /
    tool_groups / SOUL.md. On the GitHub channel, the "user" is whichever
    external commenter posted the triggering ``@<bot>`` mention — anyone
    with comment access on the configured repo. Exposing the tool there
    would let that commenter durably mutate the agent's tool whitelist
    or persona for every subsequent run. The factory therefore omits the
    tool from the toolset whenever the run's channel is webhook-shaped.

    This test guards against a future contributor reintroducing the tool
    unconditionally — that regression would silently re-open the
    privilege-escalation path.
    """
    from unittest.mock import MagicMock

    from deerflow.agents.lead_agent import agent as lead_agent_module

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=None))
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [_make_skill("legacy", None)])
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [NamedTool("bash"), NamedTool("read_file")])

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    # ``channel_name`` is plumbed onto run_context by ChannelManager and
    # surfaced via _get_runtime_config alongside the other configurable keys.
    agent_kwargs = lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}, "context": {"channel_name": "github"}})
    tool_names = [tool.name for tool in agent_kwargs["tools"]]
    assert "update_agent" not in tool_names
    # Sanity: regular tools still flow through.
    assert "bash" in tool_names
    assert "read_file" in tool_names


def test_make_lead_agent_keeps_update_agent_on_non_webhook_channels(monkeypatch):
    """Direct invocation and non-webhook channels still get ``update_agent``.

    Sanity check for the inverse of
    ``test_make_lead_agent_drops_update_agent_on_github_channel``: a chat-UI
    or default-channel run (or any run with no channel context at all)
    must keep the tool, otherwise the operator-trusted "change your own
    skills" workflow would break.
    """
    from unittest.mock import MagicMock

    from deerflow.agents.lead_agent import agent as lead_agent_module

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda x=None, **kwargs: "default-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "mock_prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: AgentConfig(name="test", skills=None))
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda available_skills, *, app_config, user_id=None: [_make_skill("legacy", None)])
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [NamedTool("bash")])

    mock_app_config = MagicMock()
    mock_app_config.get_model_config.return_value = SimpleNamespace(supports_thinking=False, supports_vision=False)
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: mock_app_config)

    # No channel set — equivalent to a chat-UI or direct invocation.
    kwargs_default = lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}})
    assert "update_agent" in [t.name for t in kwargs_default["tools"]]

    # Explicit non-webhook channel — telegram is interactive/trusted-by-operator.
    kwargs_tg = lead_agent_module.make_lead_agent({"configurable": {"agent_name": "test"}, "context": {"channel_name": "telegram"}})
    assert "update_agent" in [t.name for t in kwargs_tg["tools"]]
