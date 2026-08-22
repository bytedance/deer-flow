"""Registry bridge: user-scoped custom agents (``/api/agents``) are dispatchable subagent types.

Issue #1731 asked for heterogeneous multi-agent orchestration. DeerFlow's documented
architecture (``frontend/src/content/en/introduction/why-deerflow.mdx``) deliberately
keeps a single dynamic lead agent instead of fixed graphs, but the two agent systems
were disconnected: agents created through ``/api/agents`` + ``/workspace/agents``
could only ever run as the lead persona and could not be dispatched via ``task()``.

This bridge makes the registry resolve them as a third-priority source
(built-in > config.yaml custom_agents > per-user API agents), so users can define
specialist workers (writer / coder / reviewer with their own SOUL, tool groups,
skills, and model) from the existing UI without introducing graph primitives.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from deerflow.config import agents_config as agents_config_module
from deerflow.config.paths import Paths
from deerflow.subagents import registry as registry_module
from deerflow.subagents.config import SubagentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paths(base_dir: Path) -> Paths:
    return Paths(base_dir=base_dir)


def _write_user_agent(
    base_dir: Path,
    name: str,
    config: dict,
    soul: str | None = "You are a focused writer.",
    *,
    user_id: str = "u1",
) -> None:
    """Write an agent directory under the per-user layout with config.yaml (+ SOUL.md)."""
    agent_dir = base_dir / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    cfg = dict(config)
    cfg.setdefault("name", name)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    if soul is not None:
        (agent_dir / "SOUL.md").write_text(soul, encoding="utf-8")


@pytest.fixture
def api_agent_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the agent-store path resolution at an isolated temp base dir."""
    paths = _make_paths(tmp_path)
    monkeypatch.setattr(agents_config_module, "get_paths", lambda: paths)
    return tmp_path


def _fake_app_config(tools: list[SimpleNamespace] | None = None, custom_agents: dict | None = None) -> SimpleNamespace:
    """Minimal AppConfig stand-in carrying .tools (for group expansion) and .subagents."""
    return SimpleNamespace(
        tools=tools or [],
        subagents=SimpleNamespace(
            custom_agents=custom_agents or {},
            agents={},
            timeout_seconds=1800,
            max_turns=None,
            get_model_for=lambda name: None,
            get_skills_for=lambda name: None,
        ),
    )


# ---------------------------------------------------------------------------
# Resolution & field mapping
# ---------------------------------------------------------------------------


class TestApiAgentResolution:
    def test_api_agent_resolves_as_subagent(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {"description": "Drafts prose."})
        config = registry_module.get_subagent_config("writer", user_id="u1")
        assert config is not None
        assert isinstance(config, SubagentConfig)
        assert config.name == "writer"
        assert config.description == "Drafts prose."

    def test_soul_becomes_system_prompt(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {}, soul="You are a focused writer.")
        config = registry_module.get_subagent_config("writer", user_id="u1")
        assert config is not None
        assert config.system_prompt == "You are a focused writer."

    def test_agent_without_soul_gets_none_system_prompt(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "plain", {}, soul=None)
        config = registry_module.get_subagent_config("plain", user_id="u1")
        assert config is not None
        assert config.system_prompt is None

    def test_tool_groups_expand_to_concrete_tool_names(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "researcher", {"tool_groups": ["web"], "skills": ["deep-research"]})
        app_config = _fake_app_config(
            tools=[
                SimpleNamespace(name="web_search", group="web"),
                SimpleNamespace(name="web_fetch", group="web"),
                SimpleNamespace(name="bash", group="shell"),
            ]
        )
        config = registry_module.get_subagent_config("researcher", app_config=app_config, user_id="u1")
        assert config is not None
        assert sorted(config.tools) == ["web_fetch", "web_search"]
        assert config.skills == ["deep-research"]

    def test_no_tool_groups_inherits_full_pool(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {})
        config = registry_module.get_subagent_config("writer", user_id="u1")
        assert config is not None
        # AgentConfig.tool_groups defaults to None == unrestricted; mirror that.
        assert config.tools is None

    def test_model_defaults_to_inherit(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {})
        config = registry_module.get_subagent_config("writer", user_id="u1")
        assert config is not None
        assert config.model == "inherit"

    def test_task_is_always_disallowed(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {})
        config = registry_module.get_subagent_config("writer", user_id="u1")
        assert config is not None
        # Subagents must never re-delegate; the SubagentConfig default holds.
        assert config.disallowed_tools == ["task"]


# ---------------------------------------------------------------------------
# Precedence & isolation
# ---------------------------------------------------------------------------


class TestPrecedenceAndIsolation:
    def test_yaml_custom_agent_wins_over_same_name_api_agent(self, api_agent_base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_user_agent(api_agent_base, "writer", {"description": "api version"})
        yaml_custom = SimpleNamespace(
            description="yaml version",
            system_prompt="yaml prompt",
            tools=None,
            disallowed_tools=None,
            skills=None,
            model="inherit",
            max_turns=None,
            timeout_seconds=None,
        )
        monkeypatch.setattr(
            registry_module,
            "_resolve_subagents_app_config",
            lambda app_config=None: SimpleNamespace(custom_agents={"writer": yaml_custom}, agents={}, timeout_seconds=1800, max_turns=None, get_model_for=lambda n: None, get_skills_for=lambda n: None),
        )
        config = registry_module.get_subagent_config("writer", user_id="u1")
        assert config is not None
        assert config.system_prompt == "yaml prompt"

    def test_builtin_still_wins_over_api_agent_name(self, api_agent_base: Path) -> None:
        # An API agent squatting on a built-in name cannot shadow it.
        _write_user_agent(api_agent_base, "general-purpose", {"description": "imposter"})
        config = registry_module.get_subagent_config("general-purpose", user_id="u1")
        assert config is not None
        assert config.system_prompt != "You are a focused writer."
        assert "imposter" not in config.description

    def test_cross_user_isolation(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {}, user_id="u1")
        assert registry_module.get_subagent_config("writer", user_id="u2") is None

    def test_invalid_name_returns_none_instead_of_raising(self, api_agent_base: Path) -> None:
        # validate_agent_name rejects path-traversal shapes; the adapter must
        # translate that into "not resolvable", never leak an exception into task().
        assert registry_module.get_subagent_config("../evil", user_id="u1") is None


# ---------------------------------------------------------------------------
# Discoverability
# ---------------------------------------------------------------------------


class TestDiscoverability:
    def test_names_listing_includes_api_agents(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {})
        names = registry_module.get_subagent_names(user_id="u1")
        assert "writer" in names

    def test_names_listing_is_user_scoped(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "writer", {}, user_id="u1")
        assert "writer" not in registry_module.get_subagent_names(user_id="u2")

    def test_unknown_type_message_lists_api_agents(self, api_agent_base: Path) -> None:
        # task_tool builds its error from get_available_subagent_names(); keep the
        # contract that a mistyped subagent_type surfaces user-defined workers.
        _write_user_agent(api_agent_base, "reviewer", {})
        available = ", ".join(registry_module.get_available_subagent_names(user_id="u1"))
        assert "reviewer" in available

    def test_prompt_builder_renders_api_agent_description(self, api_agent_base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deerflow.agents.lead_agent.prompt import _build_available_subagents_description

        monkeypatch.setattr(
            registry_module,
            "get_subagent_config",
            lambda name, app_config=None, user_id=None: SimpleNamespace(description="Drafts prose."),
        )
        rendered = _build_available_subagents_description(["writer"], bash_available=True, user_id="u1")
        assert "- **writer**: Drafts prose." in rendered

    def test_subagent_section_lists_real_api_agent(self, api_agent_base: Path) -> None:
        # Full unmocked path: _build_subagent_section -> get_available_subagent_names ->
        # get_subagent_config against the real file-backed agent store.
        from deerflow.agents.lead_agent.prompt import _build_subagent_section

        _write_user_agent(api_agent_base, "writer", {"description": "Drafts prose."})
        section = _build_subagent_section(3, 6, user_id="u1")
        assert "**writer**: Drafts prose." in section

    def test_multiple_api_agents_render_and_dedup(self, api_agent_base: Path) -> None:
        from deerflow.agents.lead_agent.prompt import _build_available_subagents_description

        _write_user_agent(api_agent_base, "writer", {"description": "Drafts prose."})
        _write_user_agent(api_agent_base, "coder", {"description": "Writes code."}, user_id="u1")
        rendered = _build_available_subagents_description(["general-purpose", "writer", "coder"], bash_available=True, user_id="u1")
        assert "- **writer**: Drafts prose." in rendered
        assert "- **coder**: Writes code." in rendered


class TestFailurePaths:
    def test_list_failure_degrades_to_builtins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A broken agent store (I/O error, permission problem) must never break
        # task() dispatch or prompt building — degrade to the built-in listing.
        import deerflow.config.agents_config as agents_cfg_module

        def _raise(user_id=None):
            raise OSError("disk on fire")

        monkeypatch.setattr(agents_cfg_module, "list_custom_agents", _raise)
        names = registry_module.get_subagent_names(user_id="u1")
        assert "general-purpose" in names
        assert names == registry_module.get_available_subagent_names(user_id="u1")

    def test_tool_group_expansion_fail_open_without_config(self, api_agent_base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # An agent WITH tool_groups but no resolvable app config inherits the
        # full pool (documented fail-open), rather than silently getting no tools.
        import deerflow.config.app_config as app_config_module

        def _raise():
            raise RuntimeError("no config here")

        monkeypatch.setattr(app_config_module, "get_app_config", _raise)
        _write_user_agent(api_agent_base, "restricted", {"tool_groups": ["web"]})
        cfg = registry_module.get_subagent_config("restricted", app_config=None, user_id="u1")
        assert cfg is not None
        assert cfg.tools is None

    def test_fail_open_expansion_logs_warning(self, api_agent_base: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        import deerflow.config.app_config as app_config_module

        def _raise():
            raise RuntimeError("no config here")

        monkeypatch.setattr(app_config_module, "get_app_config", _raise)
        _write_user_agent(api_agent_base, "restricted", {"tool_groups": ["web"]})
        with caplog.at_level(logging.WARNING, logger="deerflow.subagents.registry"):
            registry_module.get_subagent_config("restricted", user_id="u1")
        assert any("inheriting full tool pool" in r.message for r in caplog.records)

    def test_unreadable_store_degrades_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PermissionError / OSError from a broken store must degrade to the task
        # tool's clean unknown-type error, never propagate into the tool call.
        import deerflow.config.agents_config as agents_cfg_module

        def _raise(name, *, user_id=None):
            raise PermissionError("store unreadable")

        monkeypatch.setattr(agents_cfg_module, "load_agent_config", _raise)
        assert registry_module.get_subagent_config("writer", user_id="u1") is None


class TestGlobalDefaultsForStoreAgents:
    """Review finding: global ``subagents`` defaults apply to this tier like builtins."""

    @staticmethod
    def _app_config_with_globals(timeout_seconds: int, max_turns: int) -> SimpleNamespace:
        return SimpleNamespace(
            tools=[],
            subagents=SimpleNamespace(
                custom_agents={},
                agents={},
                timeout_seconds=timeout_seconds,
                max_turns=max_turns,
                get_model_for=lambda name: None,
                get_skills_for=lambda name: None,
            ),
        )

    def test_global_timeout_and_max_turns_apply(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "coder", {})
        cfg = registry_module.get_subagent_config("coder", app_config=self._app_config_with_globals(1800, 150), user_id="u1")
        assert cfg is not None
        assert cfg.timeout_seconds == 1800
        assert cfg.max_turns == 150

    def test_bare_defaults_without_effective_globals(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "coder", {})
        cfg = registry_module.get_subagent_config("coder", app_config=self._app_config_with_globals(900, 50), user_id="u1")
        assert cfg is not None
        # Globals equal to the dataclass defaults change nothing observable.
        assert cfg.timeout_seconds == 900
        assert cfg.max_turns == 50

    def test_per_agent_yaml_override_still_wins(self, api_agent_base: Path) -> None:
        _write_user_agent(api_agent_base, "coder", {})
        app_config = self._app_config_with_globals(1800, 150)
        app_config.subagents.agents = {"coder": SimpleNamespace(timeout_seconds=55, max_turns=None)}
        cfg = registry_module.get_subagent_config("coder", app_config=app_config, user_id="u1")
        assert cfg is not None
        assert cfg.timeout_seconds == 55
        assert cfg.max_turns == 150
