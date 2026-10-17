"""Named-Agent skill selection across the embedded harness."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.client import DeerFlowClient
from deerflow.config.agents_config import AgentConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture
def client():
    config = AppConfig(models=[ModelConfig(name="test-model", model="test-model", use="langchain_openai:ChatOpenAI")], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    with patch("deerflow.client.get_app_config", return_value=config):
        return DeerFlowClient()


class TestClientSkillSelection:
    @pytest.fixture
    def skill_client(self, client):
        client._agent_name = "researcher"
        client._app_config.tool_search.enabled = False
        enabled_skills = [
            SimpleNamespace(name="report-helper"),
            SimpleNamespace(name="my-test-skill"),
        ]
        graph = MagicMock()
        graph.stream.return_value = []
        with (
            patch("deerflow.client.create_chat_model"),
            patch("deerflow.client.create_agent", return_value=graph) as create_agent,
            patch("deerflow.client.build_middlewares", return_value=[]) as build_middlewares,
            patch("deerflow.client.apply_prompt_template", return_value="prompt") as apply_prompt,
            patch("deerflow.client.load_agent_config") as load_config,
            patch("deerflow.client.get_enabled_skills_for_config", return_value=enabled_skills),
            patch(
                "deerflow.client.build_skill_search_setup",
                return_value=SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
            ) as build_skill_search,
            patch.object(client, "_get_tools", return_value=[]),
            patch("deerflow.runtime.checkpointer.get_checkpointer", return_value=None),
        ):
            yield SimpleNamespace(
                client=client,
                graph=graph,
                create_agent=create_agent,
                build_middlewares=build_middlewares,
                apply_prompt=apply_prompt,
                load_config=load_config,
                build_skill_search=build_skill_search,
            )

    @pytest.mark.parametrize(
        ("selection", "expected_effective", "expected_names"),
        [
            (None, None, ["report-helper", "my-test-skill"]),
            ([], set(), []),
            (["report-helper"], {"report-helper"}, ["report-helper"]),
        ],
    )
    def test_saved_selection_applies_across_embedded_harness(
        self,
        skill_client,
        selection,
        expected_effective,
        expected_names,
    ):
        skill_client.load_config.return_value = AgentConfig(name="researcher", skills=selection)
        config = skill_client.client._get_runnable_config("t1")
        skill_client.client._ensure_agent(config)

        discovered = skill_client.build_skill_search.call_args.args[0]
        assert [skill.name for skill in discovered] == expected_names
        assert skill_client.build_middlewares.call_args.kwargs["available_skills"] == expected_effective
        assert skill_client.apply_prompt.call_args.kwargs["available_skills"] == expected_effective
        assert config["metadata"]["available_skills"] == (sorted(expected_effective) if expected_effective is not None else None)
        assert skill_client.client._available_skills is None

    @pytest.mark.parametrize(
        ("override", "expected_names"),
        [
            (set(), []),
            ({"my-test-skill"}, ["my-test-skill"]),
        ],
    )
    def test_constructor_selection_overrides_saved_agent_config(self, skill_client, override, expected_names):
        skill_client.client._available_skills = override
        skill_client.load_config.return_value = AgentConfig(name="researcher", skills=["report-helper"])
        config = skill_client.client._get_runnable_config("t1")
        skill_client.client._ensure_agent(config)

        discovered = skill_client.build_skill_search.call_args.args[0]
        assert [skill.name for skill in discovered] == expected_names
        assert skill_client.build_middlewares.call_args.kwargs["available_skills"] == override
        assert skill_client.apply_prompt.call_args.kwargs["available_skills"] == override
        assert config["metadata"]["available_skills"] == sorted(override)

    @pytest.mark.parametrize("selection", [None, [], ["report-helper"]])
    def test_each_stream_carries_skill_selection_for_delegation_on_cache_hit(self, skill_client, selection):
        skill_client.load_config.return_value = AgentConfig(name="researcher", skills=selection)
        for _ in range(2):
            list(skill_client.client.stream("hello", thread_id="t1"))

        skill_client.create_agent.assert_called_once()
        skill_client.load_config.assert_called_once()
        assert skill_client.graph.stream.call_count == 2
        for call in skill_client.graph.stream.call_args_list:
            assert call.kwargs["config"]["metadata"]["available_skills"] == selection

    def test_reset_refreshes_saved_skill_selection_and_graph_cache_identity(self, skill_client):
        client = skill_client.client
        keys = []
        for selection in [None, [], ["report-helper"]]:
            skill_client.load_config.return_value = AgentConfig(name="researcher", skills=selection)
            client.reset_agent()
            config = client._get_runnable_config("t1")
            config["metadata"] = {"existing": "preserved", "available_skills": ["stale"]}
            client._ensure_agent(config)
            keys.append(client._agent_config_key)
            assert config["metadata"] == {"existing": "preserved", "mcp_plugins": None, "available_skills": selection}

            # Saved changes take effect only after reset_agent(), matching the
            # existing named-Agent config cache contract.
            skill_client.load_config.return_value = AgentConfig(name="researcher", skills=["my-test-skill"])
            cached_config = client._get_runnable_config("t2")
            client._ensure_agent(cached_config)
            assert cached_config["metadata"]["available_skills"] == selection

        assert keys[0] != keys[1] != keys[2]
        assert skill_client.load_config.call_count == 3
        assert skill_client.create_agent.call_count == 3

    def test_reordered_saved_selection_reuses_graph(self, skill_client):
        saved = AgentConfig(name="researcher", skills=["report-helper", "my-test-skill"])
        skill_client.load_config.return_value = saved
        skill_client.client._ensure_agent(skill_client.client._get_runnable_config("t1"))
        saved.skills = list(reversed(saved.skills))
        config = skill_client.client._get_runnable_config("t2")
        skill_client.client._ensure_agent(config)

        skill_client.create_agent.assert_called_once()
        assert config["metadata"]["available_skills"] == ["my-test-skill", "report-helper"]

    @pytest.mark.parametrize("override", [None, {"my-test-skill"}])
    def test_role_policy_narrows_selection_and_cache_hit_delegation(self, skill_client, override):
        from deerflow.authz.rbac import RbacAuthorizationProvider
        from deerflow.config.authorization_config import AuthorizationConfig

        client = skill_client.client
        client._available_skills = override
        client._app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
        skill_client.load_config.return_value = AgentConfig(name="researcher", skills=["report-helper", "my-test-skill"])
        provider = RbacAuthorizationProvider(roles={"user": {"skills": {"allow": ["report-helper"]}, "tools": {"allow": "*"}, "models": {"allow": "*"}}})
        expected = {"report-helper"} if override is None else set()
        with (
            patch("deerflow.authz.skill_filter.resolve_authorization_provider", return_value=provider),
            patch("deerflow.authz.tool_filter.resolve_authorization_provider", return_value=provider),
            patch("deerflow.agents.lead_agent.agent.resolve_authorization_provider", return_value=provider),
        ):
            for thread_id in ("t1", "t2"):
                config = client._get_runnable_config(thread_id)
                config["metadata"] = {"available_skills": ["stale"], "existing": "preserved"}
                client._ensure_agent(config, context={"user_id": "alice", "user_role": "user"})
                assert config["metadata"]["available_skills"] == sorted(expected)
                assert config["metadata"]["existing"] == "preserved"

        skill_client.create_agent.assert_called_once()
        assert skill_client.build_middlewares.call_args.kwargs["available_skills"] == expected
        assert skill_client.apply_prompt.call_args.kwargs["available_skills"] == expected
        assert [skill.name for skill in skill_client.build_skill_search.call_args.args[0]] == sorted(expected)

    def test_saved_selection_is_loaded_in_each_users_scope(self, skill_client):
        skill_client.load_config.side_effect = lambda name, *, user_id: AgentConfig(name=name, skills=["report-helper"] if user_id == "alice" else [])
        for user_id, expected in [("alice", ["report-helper"]), ("bob", []), ("bob", [])]:
            config = skill_client.client._get_runnable_config("t1")
            skill_client.client._ensure_agent(config, context={"user_id": user_id})
            assert config["metadata"]["available_skills"] == expected

        assert skill_client.create_agent.call_count == 2
        assert [call.kwargs["user_id"] for call in skill_client.load_config.call_args_list] == ["alice", "bob"]

    def test_saved_selection_filters_real_user_scoped_skill_catalog(self, tmp_path):
        """Exercise the on-disk AgentConfig and per-user skill storage together."""
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig
        from deerflow.persistence.agents.file import FileAgentStore
        from deerflow.skills.storage import reset_skill_storage

        paths = Paths(base_dir=tmp_path)
        skills_root = tmp_path / "skills"

        def write_skill(path: Path, name: str, description: str) -> None:
            path.mkdir(parents=True, exist_ok=True)
            (path / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
                encoding="utf-8",
            )

        write_skill(skills_root / "public" / "public-research", "public-research", "Public research")
        write_skill(skills_root / "public" / "unlisted-public", "unlisted-public", "Not selected")
        write_skill(paths.user_custom_skills_dir("alice") / "alice-private", "alice-private", "Alice only")
        write_skill(paths.user_custom_skills_dir("bob") / "bob-private", "bob-private", "Bob only")

        agent_dir = paths.user_agent_dir("alice", "researcher")
        agent_dir.mkdir(parents=True)
        (agent_dir / "config.yaml").write_text(
            "name: researcher\nmemory_enabled: false\nskills:\n  - public-research\n  - alice-private\n",
            encoding="utf-8",
        )
        (agent_dir / "SOUL.md").write_text("You are Alice's research agent.", encoding="utf-8")

        app_config = AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            skills={"path": str(skills_root), "deferred_discovery": True},
            title={"enabled": False},
        )
        graph = MagicMock()
        reset_skill_storage()
        with (
            patch("deerflow.client.get_app_config", return_value=app_config),
            patch("deerflow.config.agents_config.get_paths", return_value=paths),
            patch("deerflow.config.paths.get_paths", return_value=paths),
            patch("deerflow.persistence.agents.get_agent_store", return_value=FileAgentStore()),
            patch("deerflow.client.create_chat_model"),
            patch("deerflow.client.create_agent", return_value=graph) as create_agent,
            patch("deerflow.runtime.checkpointer.get_checkpointer", return_value=None),
        ):
            client = DeerFlowClient(agent_name="researcher")
            with patch.object(client, "_get_tools", return_value=[]):
                config = client._get_runnable_config("t1")
                client._ensure_agent(config, context={"user_id": "alice"})

        assert config["metadata"]["available_skills"] == ["alice-private", "public-research"]
        assembled = create_agent.call_args.kwargs
        prompt = assembled["system_prompt"]
        assert "alice-private" in prompt
        assert "public-research" in prompt
        assert "unlisted-public" not in prompt
        assert "bob-private" not in prompt

        describe_skill = next(tool for tool in assembled["tools"] if tool.name == "describe_skill")
        allowed = describe_skill.invoke(
            {
                "args": {"name": "select:alice-private"},
                "name": "describe_skill",
                "type": "tool_call",
                "id": "allowed-skill",
            }
        )
        denied = describe_skill.invoke(
            {
                "args": {"name": "select:unlisted-public"},
                "name": "describe_skill",
                "type": "tool_call",
                "id": "denied-skill",
            }
        )
        assert "## Skill: alice-private" in allowed.update["messages"][0].content
        assert "No skills matched" in denied.update["messages"][0].content

        slash_middleware = next(m for m in assembled["middleware"] if isinstance(m, SkillActivationMiddleware))
        assert slash_middleware.release_policy_parameters()["available_skills"] == ["alice-private", "public-research"]
