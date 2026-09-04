"""What the agent was actually assembled from, captured at build time.

Everything here is knowable only inside the factory: the resolved model after
runtime overrides, the rendered prompt, the tool list after authorization
filtering, the composed middleware stack. None of it survives to any later
observation point.
"""

from pathlib import Path

from deerflow_extension_api import AgentAssemblyDescriptor, MiddlewareDescriptor, ToolDescriptor


def test_fingerprint_is_stable_for_identical_assemblies():
    def make():
        return AgentAssemblyDescriptor(
            namespace="lead",
            agent_name="lead-agent",
            requested_model=None,
            effective_model="gpt-x",
            model_parameters={"temperature": 0},
            thinking_enabled=False,
            reasoning_effort=None,
            base_prompt_hash="abc",
            tools=(ToolDescriptor(name="bash", description_hash="d", schema_hash="s", source="builtin"),),
            middlewares=(MiddlewareDescriptor(name="M", module="m", policy_parameters={"limit": 1}),),
            deferred_tool_names=(),
            enabled_skills=(),
            effective_policies={"recursion_limit": 100},
        )

    assert make().fingerprint == make().fingerprint


def test_fingerprint_changes_when_a_middleware_policy_changes():
    from dataclasses import replace

    base = AgentAssemblyDescriptor(
        namespace="lead",
        agent_name="lead-agent",
        requested_model=None,
        effective_model="gpt-x",
        model_parameters={},
        thinking_enabled=False,
        reasoning_effort=None,
        base_prompt_hash="abc",
        tools=(),
        middlewares=(MiddlewareDescriptor(name="M", module="m", policy_parameters={"limit": 1}),),
        deferred_tool_names=(),
        enabled_skills=(),
        effective_policies={},
    )
    changed = replace(base, middlewares=(MiddlewareDescriptor(name="M", module="m", policy_parameters={"limit": 2}),))
    assert base.fingerprint != changed.fingerprint


def test_fingerprint_ignores_tool_ordering():
    """Tool order is an assembly detail, not a behavioural difference."""
    from dataclasses import replace

    a = ToolDescriptor(name="a", description_hash="1", schema_hash="1", source="builtin")
    b = ToolDescriptor(name="b", description_hash="2", schema_hash="2", source="builtin")
    base = AgentAssemblyDescriptor(
        namespace="lead",
        agent_name="lead-agent",
        requested_model=None,
        effective_model="gpt-x",
        model_parameters={},
        thinking_enabled=False,
        reasoning_effort=None,
        base_prompt_hash="abc",
        tools=(a, b),
        middlewares=(),
        deferred_tool_names=(),
        enabled_skills=(),
        effective_policies={},
    )
    assert base.fingerprint == replace(base, tools=(b, a)).fingerprint


def test_middleware_order_does_affect_the_fingerprint():
    """Stack order determines what wraps what, so it is behavioural."""
    from dataclasses import replace

    m1 = MiddlewareDescriptor(name="A", module="m", policy_parameters={})
    m2 = MiddlewareDescriptor(name="B", module="m", policy_parameters={})
    base = AgentAssemblyDescriptor(
        namespace="lead",
        agent_name="lead-agent",
        requested_model=None,
        effective_model="gpt-x",
        model_parameters={},
        thinking_enabled=False,
        reasoning_effort=None,
        base_prompt_hash="abc",
        tools=(),
        middlewares=(m1, m2),
        deferred_tool_names=(),
        enabled_skills=(),
        effective_policies={},
    )
    assert base.fingerprint != replace(base, middlewares=(m2, m1)).fingerprint


class TestLeadAgentAssembly:
    def test_make_lead_agent_still_returns_a_bare_graph(self):
        """langgraph.json declares this factory; its ABI must not move."""
        import inspect

        from deerflow.agents.lead_agent.agent import make_lead_agent

        signature = inspect.signature(make_lead_agent)
        assert list(signature.parameters) == ["config"]

    @staticmethod
    def _isolate_from_the_ambient_config(monkeypatch):
        """Assemble against a config this test owns, not the machine's.

        ``assemble_lead_agent`` falls back to ``get_app_config()``, so without
        this the test passes only where a developer happens to have a usable
        ``config.yaml``. CI checks out ``config.example.yaml``, whose ``models:``
        entries are all commented out, and assembly raises "No chat models are
        configured" before it can produce anything to assert on.
        """
        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.config.app_config import AppConfig
        from deerflow.config.model_config import ModelConfig
        from deerflow.config.sandbox_config import SandboxConfig

        app_config = AppConfig(
            models=[
                ModelConfig(
                    name="assembly-test-model",
                    display_name="assembly-test-model",
                    description=None,
                    use="langchain_openai:ChatOpenAI",
                    model="assembly-test-model",
                    supports_thinking=False,
                    supports_vision=False,
                )
            ],
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        )
        monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
        monkeypatch.setattr(
            lead_agent_module,
            "create_chat_model",
            lambda **kwargs: object(),
        )
        monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
        return app_config

    @staticmethod
    def _extensions_with_an_agent_assembly_observer(observer=None):
        """A minimal LoadedExtensions carrying one agent-assembly observer.

        Building the descriptor is real work (hashing every tool's description
        and schema, probing every middleware), so it only happens when an
        observer is actually registered to receive it.
        """
        from deerflow.extensions.registry import ExtensionRegistry

        class _NoOpObserver:
            def on_agent_assembled(self, app_store, descriptor):
                return None

        registry = ExtensionRegistry()
        with registry.attributed_to("test"):
            registry.agent_assembly_observer(observer or _NoOpObserver())
        return registry.build()

    def test_assemble_returns_both_the_graph_and_a_descriptor(self, monkeypatch):
        from deerflow.agents.lead_agent.agent import LeadAgentAssembly, assemble_lead_agent
        from deerflow.extensions import bind_agent_build_extensions

        self._isolate_from_the_ambient_config(monkeypatch)
        with bind_agent_build_extensions(self._extensions_with_an_agent_assembly_observer()):
            assembly = assemble_lead_agent({"configurable": {"thread_id": "t-1"}})
        assert isinstance(assembly, LeadAgentAssembly)
        assert assembly.graph is not None
        assert assembly.descriptor.effective_model
        assert assembly.descriptor.fingerprint

    def test_descriptor_hashes_the_same_scoped_prompt_passed_to_the_graph(self, monkeypatch):
        from deerflow_extension_api import canonical_hash

        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.agents.lead_agent.agent import assemble_lead_agent
        from deerflow.config.agents_config import AgentConfig
        from deerflow.extensions import bind_agent_build_extensions

        self._isolate_from_the_ambient_config(monkeypatch)
        agent_config = AgentConfig(name="custom", allowed_subagents=["general-purpose"])
        monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda name, *, user_id=None: agent_config)

        prompt_calls = []

        def render_prompt(**kwargs):
            prompt_calls.append(kwargs)
            return f"allowed_subagents={kwargs['allowed_subagents']}"

        monkeypatch.setattr(lead_agent_module, "apply_prompt_template", render_prompt)
        with bind_agent_build_extensions(self._extensions_with_an_agent_assembly_observer()):
            assembly = assemble_lead_agent(
                {
                    "configurable": {
                        "thread_id": "t-scoped-prompt",
                        "agent_name": "custom",
                        "subagent_enabled": True,
                    }
                }
            )

        assert len(prompt_calls) == 1
        assert prompt_calls[0]["allowed_subagents"] == ["general-purpose"]
        assert assembly.graph["system_prompt"] == "allowed_subagents=['general-purpose']"
        assert assembly.descriptor.base_prompt_hash == canonical_hash(assembly.graph["system_prompt"])

    def test_observers_receive_the_descriptor(self, monkeypatch):
        from deerflow.agents.lead_agent.agent import assemble_lead_agent
        from deerflow.extensions import bind_agent_build_extensions

        seen = []

        class Observer:
            def on_agent_assembled(self, app_store, descriptor):
                seen.append(descriptor)

        monkeypatch.setattr(
            "deerflow.extensions.notify.notify_agent_assembled",
            lambda descriptor, extensions=None: Observer().on_agent_assembled(None, descriptor),
        )
        self._isolate_from_the_ambient_config(monkeypatch)
        with bind_agent_build_extensions(self._extensions_with_an_agent_assembly_observer()):
            assemble_lead_agent({"configurable": {"thread_id": "t-2"}})
        assert len(seen) == 1

    def test_no_descriptor_is_built_without_a_registered_observer(self, monkeypatch):
        """The zero-observer fast path must skip the expensive build entirely,
        not just skip notifying — mirroring notify_agent_assembled's own
        zero-observer short-circuit."""
        from deerflow.agents.lead_agent.agent import assemble_lead_agent

        def _fail(*args, **kwargs):
            raise AssertionError("build_assembly_descriptor must not run without an observer")

        monkeypatch.setattr("deerflow.agents.assembly_descriptor.build_assembly_descriptor", _fail)
        self._isolate_from_the_ambient_config(monkeypatch)
        assembly = assemble_lead_agent({"configurable": {"thread_id": "t-3"}})
        assert assembly.descriptor is None


class TestFactoryConsumersUnwrapTheGraph:
    """A missed unwrap fails at request time, not at import time."""

    def test_worker_unwraps_the_assembly(self):
        from deerflow.agents.lead_agent.agent import LeadAgentAssembly
        from deerflow.runtime.runs.worker import _agent_graph

        graph = object()
        assert _agent_graph(LeadAgentAssembly(graph=graph, descriptor=object())) is graph

    def test_worker_leaves_a_third_party_bare_graph_alone(self):
        from deerflow.runtime.runs.worker import _agent_graph

        graph = object()
        assert _agent_graph(graph) is graph


class TestAssemblyObserverHost:
    def test_registration_survives_rollback_of_a_later_install(self):
        from deerflow.extensions.registry import ExtensionRegistry

        class Observer:
            def on_agent_assembled(self, app_store, descriptor):
                return None

        registry = ExtensionRegistry()
        keeper = Observer()
        with registry.attributed_to("keeper"):
            registry.agent_assembly_observer(keeper)
        mark = registry.mark()
        with registry.attributed_to("doomed"):
            registry.agent_assembly_observer(Observer())
        registry.rollback_to(mark)

        loaded = registry.build()
        assert loaded.agent_assembly_observers == (("keeper", keeper),)
        assert loaded.has_agent_assembly_observers is True
        # The descriptor is app-scoped; it does not create a task store need.
        assert loaded.needs_task_store is False

    def test_a_broken_observer_does_not_stop_its_successors(self, caplog):
        from deerflow.extensions.notify import notify_agent_assembled
        from deerflow.extensions.registry import ExtensionRegistry

        seen = []

        class Broken:
            def on_agent_assembled(self, app_store, descriptor):
                raise RuntimeError("boom")

        class Working:
            def on_agent_assembled(self, app_store, descriptor):
                seen.append(descriptor)

        registry = ExtensionRegistry()
        with registry.attributed_to("broken"):
            registry.agent_assembly_observer(Broken())
        with registry.attributed_to("working"):
            registry.agent_assembly_observer(Working())
        loaded = registry.build()

        notify_agent_assembled("descriptor", loaded)

        assert seen == ["descriptor"]


class TestBuildIdentityIsOutsideTheFingerprint:
    """A redeploy that changed nothing must not look like an assembly change."""

    def _descriptor(self, build):
        return AgentAssemblyDescriptor(
            namespace="lead",
            agent_name="lead-agent",
            requested_model=None,
            effective_model="gpt-x",
            model_parameters={},
            thinking_enabled=False,
            reasoning_effort=None,
            base_prompt_hash="abc",
            tools=(),
            middlewares=(),
            deferred_tool_names=(),
            enabled_skills=(),
            effective_policies={},
            build=build,
        )

    def test_two_builds_of_the_same_assembly_share_a_fingerprint(self):
        before = self._descriptor({"package_version": "1.0.0", "git_commit": "aaaa", "image_digest": "sha256:aaa"})
        after = self._descriptor({"package_version": "1.0.1", "git_commit": "bbbb", "image_digest": "sha256:bbb"})
        assert before.fingerprint == after.fingerprint

    def test_the_build_itself_stays_comparable(self):
        """The coarser question must remain answerable, just separately."""
        before = self._descriptor({"git_commit": "aaaa"})
        after = self._descriptor({"git_commit": "bbbb"})
        assert before.build != after.build

    def test_the_builder_reports_a_build_without_hashing_it(self):
        from deerflow.agents.assembly_descriptor import build_assembly_descriptor

        def make():
            return build_assembly_descriptor(
                namespace="deerflow",
                agent_name="lead-agent",
                requested_model=None,
                effective_model="gpt-x",
                model_config=None,
                thinking_enabled=False,
                reasoning_effort=None,
                rendered_base_prompt="prompt",
                tools=[],
                middlewares=[],
                deferred_names=frozenset(),
                enabled_skills=[],
                effective_policies={},
            )

        descriptor = make()
        assert descriptor.build["package_version"]
        assert "build" not in descriptor.effective_policies
        assert descriptor.fingerprint == make().fingerprint


class TestWrappedExtensionMiddlewaresStayDistinguishable:
    """Contributed middlewares all share the isolation wrapper's class name."""

    @staticmethod
    def _wrap(inner, source):
        from deerflow.extensions.isolation import IsolatedMiddleware

        return IsolatedMiddleware(inner, source, lambda diagnostic: None)

    @staticmethod
    def _inner(name, *, policy=None):
        from langchain.agents.middleware import AgentMiddleware

        namespace = {}
        if policy is not None:
            namespace["release_policy_parameters"] = lambda self: dict(policy)
        return type(name, (AgentMiddleware,), namespace)()

    def test_two_extensions_middlewares_do_not_collapse_into_one_descriptor(self):
        from deerflow.agents.assembly_descriptor import describe_middleware

        first = describe_middleware(self._wrap(self._inner("AlphaMiddleware"), "ext-a"))
        second = describe_middleware(self._wrap(self._inner("BetaMiddleware"), "ext-b"))

        assert first.name == "AlphaMiddleware"
        assert second.name == "BetaMiddleware"
        assert first.extension == "ext-a"
        assert second.extension == "ext-b"
        assert first != second

    def test_a_wrapped_declaration_reaches_the_descriptor(self):
        from deerflow.agents.assembly_descriptor import describe_middleware

        descriptor = describe_middleware(self._wrap(self._inner("DeclaringMiddleware", policy={"limit": 7}), "ext-a"))

        assert descriptor.policy_parameters == {"limit": 7}
        assert "probed" not in descriptor.policy_parameters

    def test_a_policy_change_inside_a_wrapped_middleware_moves_the_fingerprint(self):
        from dataclasses import replace

        from deerflow.agents.assembly_descriptor import describe_middleware

        def descriptor_for(limit):
            return AgentAssemblyDescriptor(
                namespace="lead",
                agent_name="lead-agent",
                requested_model=None,
                effective_model="gpt-x",
                model_parameters={},
                thinking_enabled=False,
                reasoning_effort=None,
                base_prompt_hash="abc",
                tools=(),
                middlewares=(describe_middleware(self._wrap(self._inner("DeclaringMiddleware", policy={"limit": limit}), "ext-a")),),
                deferred_tool_names=(),
                enabled_skills=(),
                effective_policies={},
            )

        assert descriptor_for(1).fingerprint != descriptor_for(2).fingerprint

        # And the same policy from a different extension is a different agent.
        base = descriptor_for(1)
        other = replace(base, middlewares=(replace(base.middlewares[0], extension="ext-b"),))
        assert base.fingerprint != other.fingerprint

    def test_an_unwrapped_host_middleware_reports_no_extension(self):
        from deerflow.agents.assembly_descriptor import describe_middleware

        descriptor = describe_middleware(self._inner("HostMiddleware", policy={"limit": 1}))

        assert descriptor.extension is None
        assert descriptor.name == "HostMiddleware"


class TestModelParametersProjectEffectiveSettings:
    """Provider kwargs a user actually sets must move the fingerprint.

    ``ModelConfig`` is ``extra="allow"``, so ``temperature``/``max_tokens``/
    anything else a deployer sets live only as extra fields; a fixed allowlist
    never saw them. And the *effective* per-agent override (issue #4336's
    ``model_settings``) must reach the descriptor too, not just the static
    profile.
    """

    @staticmethod
    def _build(model_config, *, model_overrides=None):
        from deerflow.agents.assembly_descriptor import build_assembly_descriptor

        return build_assembly_descriptor(
            namespace="deerflow",
            agent_name="lead-agent",
            requested_model=None,
            effective_model="gpt-x",
            model_config=model_config,
            model_overrides=model_overrides,
            thinking_enabled=False,
            reasoning_effort=None,
            rendered_base_prompt="prompt",
            tools=[],
            middlewares=[],
            deferred_names=frozenset(),
            enabled_skills=[],
            effective_policies={},
        )

    @staticmethod
    def _model_config(**extra):
        from deerflow.config.model_config import ModelConfig

        return ModelConfig(
            name="assembly-test-model",
            display_name=None,
            description=None,
            use="langchain_openai:ChatOpenAI",
            model="gpt-x",
            **extra,
        )

    def test_changing_temperature_changes_the_fingerprint(self):
        cold = self._build(self._model_config(temperature=0.1))
        hot = self._build(self._model_config(temperature=0.9))
        assert cold.fingerprint != hot.fingerprint
        assert cold.model_parameters["temperature"] == 0.1

    def test_changing_a_per_agent_model_setting_changes_the_fingerprint(self):
        """The *effective* override, not just the static profile, must count."""
        model_config = self._model_config()
        without_override = self._build(model_config)
        with_override = self._build(model_config, model_overrides={"temperature": 0.7})
        assert without_override.fingerprint != with_override.fingerprint
        assert with_override.model_parameters["temperature"] == 0.7

    def test_a_none_valued_override_does_not_clobber_the_profile(self):
        model_config = self._model_config(temperature=0.3)
        profile_only = self._build(model_config)
        with_noop_override = self._build(model_config, model_overrides={"temperature": None})
        assert profile_only.fingerprint == with_noop_override.fingerprint

    def test_api_key_is_never_projected_and_never_moves_the_fingerprint(self):
        quiet = self._build(self._model_config(api_key="sk-aaaaaaaaaaaa"))
        loud = self._build(self._model_config(api_key="sk-bbbbbbbbbbbb"))
        assert "api_key" not in quiet.model_parameters
        assert quiet.fingerprint == loud.fingerprint

    def test_an_override_named_like_a_credential_is_also_excluded(self):
        model_config = self._model_config()
        descriptor = self._build(model_config, model_overrides={"api_key": "sk-should-not-appear"})
        assert "api_key" not in descriptor.model_parameters


class TestCustomAgentModelSettingsReachTheDescriptor:
    """End-to-end: a custom agent's ``model_settings`` must move the fingerprint.

    ``agent.py`` computes ``agent_model_overrides`` from ``agent_config.model_settings``
    and passes it into ``create_chat_model``; this checks it also reaches
    ``_complete_assembly`` -> ``build_assembly_descriptor`` for the default
    (non-bootstrap) assembly branch. Composes with (rather than subclasses)
    ``TestLeadAgentAssembly``'s isolation helpers so this class's own tests are
    the only ones that run under it.
    """

    def test_temperature_override_on_a_custom_agent_changes_the_fingerprint(self, monkeypatch):
        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.agents.lead_agent.agent import assemble_lead_agent
        from deerflow.config.agents_config import AgentConfig, AgentModelSettings
        from deerflow.extensions import bind_agent_build_extensions

        TestLeadAgentAssembly._isolate_from_the_ambient_config(monkeypatch)

        def assemble(temperature):
            agent_config = AgentConfig(name="custom", model_settings=AgentModelSettings(temperature=temperature))
            monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda name, user_id=None: agent_config)
            with bind_agent_build_extensions(TestLeadAgentAssembly._extensions_with_an_agent_assembly_observer()):
                return assemble_lead_agent({"configurable": {"thread_id": "t-model-settings", "agent_name": "custom"}})

        low = assemble(0.1)
        high = assemble(0.9)
        assert low.descriptor.fingerprint != high.descriptor.fingerprint
        assert high.descriptor.model_parameters["temperature"] == 0.9

    def test_bootstrap_assembly_does_not_invent_model_overrides(self, monkeypatch):
        """The bootstrap branch has no ``agent_config``, so no overrides exist to project."""
        from deerflow.agents.lead_agent.agent import assemble_lead_agent
        from deerflow.extensions import bind_agent_build_extensions

        TestLeadAgentAssembly._isolate_from_the_ambient_config(monkeypatch)
        with bind_agent_build_extensions(TestLeadAgentAssembly._extensions_with_an_agent_assembly_observer()):
            assembly = assemble_lead_agent({"configurable": {"thread_id": "t-bootstrap", "is_bootstrap": True}})
        assert "temperature" not in assembly.descriptor.model_parameters


class TestSkillCatalogHashesContent:
    """Editing SKILL.md changes what ``SkillActivationMiddleware`` injects into
    the turn, so it must change the fingerprint even though name/description/
    allowed-tools are untouched."""

    @staticmethod
    def _skill(skill_dir: Path, *, required_secrets=(), secrets_autonomous=True):
        from deerflow.skills.types import Skill, SkillCategory

        skill_file = skill_dir / "SKILL.md"
        return Skill(
            name="my-skill",
            description="A test skill",
            license=None,
            skill_dir=skill_dir,
            skill_file=skill_file,
            relative_path=Path(skill_dir.name),
            category=SkillCategory.CUSTOM,
            required_secrets=required_secrets,
            secrets_autonomous=secrets_autonomous,
        )

    @staticmethod
    def _build(enabled_skills):
        from deerflow.agents.assembly_descriptor import build_assembly_descriptor

        return build_assembly_descriptor(
            namespace="deerflow",
            agent_name="lead-agent",
            requested_model=None,
            effective_model="gpt-x",
            model_config=None,
            thinking_enabled=False,
            reasoning_effort=None,
            rendered_base_prompt="prompt",
            tools=[],
            middlewares=[],
            deferred_names=frozenset(),
            enabled_skills=enabled_skills,
            effective_policies={},
        )

    def test_changing_only_skill_md_content_changes_the_fingerprint(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill = self._skill(skill_dir)

        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nOriginal instructions.\n", encoding="utf-8")
        before = self._build([skill])

        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nCompletely different instructions.\n", encoding="utf-8")
        after = self._build([skill])

        assert before.fingerprint != after.fingerprint
        assert before.enabled_skills == after.enabled_skills  # the catalog's visible identity is unchanged

    def test_required_secrets_flag_changes_the_fingerprint(self):
        from deerflow.skills.types import SecretRequirement

        no_secrets = self._skill(Path("/nonexistent/skill-a"))
        with_secret = self._skill(Path("/nonexistent/skill-b"), required_secrets=(SecretRequirement(name="API_KEY"),))
        assert self._build([no_secrets]).fingerprint != self._build([with_secret]).fingerprint

    def test_a_missing_skill_file_is_undescribable_not_fatal(self, tmp_path):
        skill = self._skill(tmp_path / "missing-skill")
        descriptor = self._build([skill])
        assert descriptor.fingerprint
