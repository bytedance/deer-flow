"""Layer 1 authorization for middleware-declared tools (spec: PR 2, tool path).

Covers the five-step declaration pass in
``deerflow.agents.middlewares.tool_declarations`` — record the ordinary pass,
collect declarations, seeded incremental decision, build-local narrowing view,
post-chain verification — plus the copy contract, the ``TodoMiddleware``
degradation, and the wiring on the lead / client / subagent assembly paths.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool

from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
from deerflow.agents.middlewares.tool_declarations import (
    DeclaredToolViewError,
    LayerOneOutcome,
    apply_declared_tool_view,
    collect_declared_tools,
    decide_declared_tools,
    layer_one_outcome,
    narrow_declared_tools,
    verify_declared_tool_view,
)
from deerflow.agents.thread_state import normalize_middleware_state_schemas
from deerflow.authz.provider import AuthzDecision, Principal
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.isolation import IsolatedMiddleware


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(lambda: name, name=name, description=name)


class _FilterProvider:
    """AuthorizationProvider test double filtering by an allowed-name list."""

    name = "filter"

    def __init__(self, allowed: list[str]) -> None:
        self.allowed = allowed
        self.calls: list[tuple[Principal, str, list[str]]] = []

    def authorize(self, request):
        return AuthzDecision(allow=True)

    async def aauthorize(self, request):
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        self.calls.append((principal, resource_type, list(candidates)))
        return [candidate for candidate in candidates if candidate in self.allowed]


class _DeclaringMiddleware(AgentMiddleware):
    """Plain middleware declaring tools as an instance attribute."""

    def __init__(self, tools: list) -> None:
        super().__init__()
        self.tools = tools


def _app_config(*, fail_closed: bool = True) -> AppConfig:
    return AppConfig(
        models=[],
        sandbox=SandboxConfig(use="test"),
        authorization=AuthorizationConfig(
            enabled=True,
            fail_closed=fail_closed,
            provider=AuthorizationProviderConfig(use="unused:Provider"),
        ),
    )


def _outcome(submitted: list[str], allowed: list[str]) -> LayerOneOutcome:
    return LayerOneOutcome(submitted=frozenset(submitted), allowed=frozenset(allowed))


def _narrow(stack, *, provider, outcome, context=None, app_config=None):
    return narrow_declared_tools(
        stack,
        outcome=outcome,
        context=context or {},
        app_config=app_config or _app_config(),
        authorization_provider=provider,
    )


class TestDisabledAuthorization:
    def test_returns_the_original_stack_and_skips_everything(self):
        middleware = _DeclaringMiddleware([_tool("decl")])
        stack = [middleware]

        view, authorized_names = _narrow(
            stack,
            provider=None,
            outcome=_outcome([], []),
        )

        assert view is stack
        assert authorized_names is None
        verify_declared_tool_view(view, authorized_names=authorized_names)  # no-op
        assert view[0] is middleware


class TestCollectAndDecide:
    def test_collect_keeps_base_tools_in_middleware_order(self):
        first, second = _tool("first"), _tool("second")
        plain = AgentMiddleware()
        stack = [_DeclaringMiddleware([first]), plain, _DeclaringMiddleware([second])]

        assert collect_declared_tools(stack) == [first, second]

    def test_non_basetool_declaration_is_dropped_with_a_warning(self, caplog):
        middleware = _DeclaringMiddleware([lambda: "not a tool", _tool("real_decl")])

        with caplog.at_level(logging.WARNING):
            declared = collect_declared_tools([middleware])

        assert [tool.name for tool in declared] == ["real_decl"]
        assert "cannot be authorized" in caplog.text
        # The middleware itself is untouched — the entry was never a decision input.
        assert len(middleware.tools) == 2

    def test_decision_skips_the_provider_when_the_delta_is_empty(self):
        provider = _FilterProvider([])
        declared = [_tool("seen")]

        authorized = decide_declared_tools(
            declared,
            outcome=_outcome(["seen"], ["seen"]),
            context={},
            app_config=_app_config(),
            authorization_provider=provider,
        )

        assert authorized == frozenset({"seen"})
        assert provider.calls == []

    def test_decision_reuses_the_layer_one_provider_and_principal(self):
        provider = _FilterProvider(["regular", "allowed_decl"])
        app_config = _app_config()
        candidates = [_tool("regular")]
        authorized_tools, resolved = apply_tool_authorization(
            candidates,
            context={"user_role": "reviewer"},
            app_config=app_config,
            authorization_provider=provider,
        )
        outcome = layer_one_outcome(candidates, authorized_tools)

        authorized = decide_declared_tools(
            [_tool("allowed_decl"), _tool("denied_decl")],
            outcome=outcome,
            context={"user_role": "reviewer"},
            app_config=app_config,
            authorization_provider=resolved,
        )

        assert authorized == frozenset({"regular", "allowed_decl"})
        assert len(provider.calls) == 2
        first_principal, _, first_candidates = provider.calls[0]
        second_principal, _, second_candidates = provider.calls[1]
        assert first_candidates == ["regular"]
        assert second_candidates == ["allowed_decl", "denied_decl"]
        assert second_principal == first_principal  # one principal across both passes
        assert second_principal.role == "reviewer"

    def test_same_named_new_declarations_reach_the_provider_once(self):
        """Two middlewares declaring the same never-submitted name submit one
        candidate — counting or audit-logging providers must not see a doubled
        candidate."""
        provider = _FilterProvider(["dup"])

        authorized = decide_declared_tools(
            [_tool("dup"), _tool("dup")],
            outcome=_outcome([], []),
            context={},
            app_config=_app_config(),
            authorization_provider=provider,
        )

        assert authorized == frozenset({"dup"})
        assert len(provider.calls) == 1
        assert provider.calls[0][2] == ["dup"]


class TestNarrowingView:
    def test_denied_declaration_is_removed_on_an_independent_copy(self):
        allowed, denied = _tool("allowed_decl"), _tool("denied_decl")
        original = _DeclaringMiddleware([allowed, denied])
        provider = _FilterProvider(["allowed_decl"])

        view, names = _narrow([original], provider=provider, outcome=_outcome([], []))

        assert names == frozenset({"allowed_decl"})
        narrowed = view[0]
        assert narrowed is not original
        assert narrowed.tools == (allowed,)
        # The caller-owned instance is fully intact.
        assert original.tools == [allowed, denied]

    def test_fully_authorized_middlewares_keep_identity_and_position(self):
        first = _DeclaringMiddleware([_tool("a")])
        plain = AgentMiddleware()
        second = _DeclaringMiddleware([_tool("b")])
        provider = _FilterProvider(["a", "b"])

        view, _ = _narrow([first, plain, second], provider=provider, outcome=_outcome([], []))

        assert view == [first, plain, second]
        assert all(view[i] is original for i, original in enumerate([first, plain, second]))

    def test_authorized_declaration_binds_through_the_langchain_merge(self):
        declared = _tool("decl")
        view, names = _narrow([_DeclaringMiddleware([declared])], provider=_FilterProvider(["decl"]), outcome=_outcome([], []))

        assert "decl" in names
        # Binding convention: declarations are never added to final_tools; the
        # bound set is LangChain's middleware_tools + regular_tools merge.
        bound_names = [tool.name for middleware in view for tool in getattr(middleware, "tools", [])]
        assert bound_names == ["decl"]

    def test_non_collectable_declaration_is_removed_from_the_bound_view(self):
        """A plain callable cannot be authorized by name; with authorization
        enabled it must not bind (LangChain would auto-convert it into the
        ToolNode unchecked)."""
        allowed = _tool("allowed_decl")
        original = _DeclaringMiddleware([lambda: "not a tool", allowed])
        provider = _FilterProvider(["allowed_decl"])

        view, names = _narrow([original], provider=provider, outcome=_outcome([], []))

        assert names == frozenset({"allowed_decl"})
        narrowed = view[0]
        assert narrowed is not original
        assert narrowed.tools == (allowed,)
        assert len(original.tools) == 2  # caller-owned instance untouched

    def test_middleware_with_only_non_collectable_declarations_binds_none(self):
        original = _DeclaringMiddleware([lambda: "not a tool"])

        view, names = _narrow([original], provider=_FilterProvider([]), outcome=_outcome([], []))

        assert names == frozenset()
        assert view[0] is not original
        assert view[0].tools == ()
        assert len(original.tools) == 1

    def test_verify_fails_loudly_when_a_non_collectable_declaration_survives(self):
        """Backstop: a hostile __copy__ that rebuilds from constructor arguments
        would restore non-collectable entries after narrowing — same fail-loud
        standard as for denied names."""
        restored = _DeclaringMiddleware([lambda: "not a tool", _tool("kept")])

        with pytest.raises(DeclaredToolViewError, match="not a BaseTool"):
            verify_declared_tool_view([restored], authorized_names=frozenset({"kept"}))


class TestSeed:
    def test_fail_closed_denial_cannot_be_rebound_by_a_declaration(self):
        """A provider that fails on the ordinary pass and recovers must not let a
        same-named declaration resurrect the tool it denied under fail_closed."""

        class _FlakyProvider(_FilterProvider):
            def filter_resources(self, principal, resource_type, candidates):
                if not self.calls:
                    self.calls.append((principal, resource_type, list(candidates)))
                    raise RuntimeError("policy service down")
                return super().filter_resources(principal, resource_type, candidates)

        provider = _FlakyProvider(["decl"])
        app_config = _app_config(fail_closed=True)
        candidates = [_tool("decl")]
        authorized_tools, resolved = apply_tool_authorization(
            candidates,
            context={},
            app_config=app_config,
            authorization_provider=provider,
        )
        assert authorized_tools == []  # fail_closed denied every candidate
        outcome = layer_one_outcome(candidates, authorized_tools)

        view, names = _narrow([_DeclaringMiddleware([_tool("decl")])], provider=resolved, outcome=outcome, app_config=app_config)

        assert names == frozenset()
        assert view[0].tools == ()
        # The recovered provider was never consulted again for the seeded name.
        assert len(provider.calls) == 1

    def test_ordinary_allow_is_never_re_decided_for_a_same_named_declaration(self):
        provider = _FilterProvider(["decl"])
        app_config = _app_config()
        candidates = [_tool("decl")]
        authorized_tools, resolved = apply_tool_authorization(
            candidates,
            context={},
            app_config=app_config,
            authorization_provider=provider,
        )
        outcome = layer_one_outcome(candidates, authorized_tools)
        declared = _tool("decl")  # a *different* object with the same name

        view, names = _narrow([_DeclaringMiddleware([declared])], provider=resolved, outcome=outcome, app_config=app_config)

        assert "decl" in names
        assert len(provider.calls) == 1  # verdict reused, never re-submitted

    def test_same_named_declaration_cannot_shadow_an_authorized_regular_tool(self):
        """Under the name-keyed merge the regular tools= entry binds; the declared
        object inheriting its verdict is not a second capability."""
        regular = StructuredTool.from_function(lambda: "regular", name="shared", description="regular")
        declared = StructuredTool.from_function(lambda: "declared", name="shared", description="declared")
        provider = _FilterProvider(["shared"])
        outcome = _outcome(["shared"], ["shared"])

        view, names = _narrow([_DeclaringMiddleware([declared])], provider=provider, outcome=outcome)

        assert names == frozenset({"shared"})
        assert provider.calls == []  # seeded name: no second decision
        # LangChain merges middleware_tools + regular_tools, later entry wins.
        middleware_tools = [tool for middleware in view for tool in getattr(middleware, "tools", [])]
        merged = {tool.name: tool for tool in [*middleware_tools, regular]}
        assert merged["shared"] is regular


class TestCopyFailureModes:
    def test_copy_that_raises_fails_the_build_loudly(self):
        class _Uncopyable(_DeclaringMiddleware):
            def __copy__(self):
                raise TypeError("no copies")

        original = _Uncopyable([_tool("denied")])

        with pytest.raises(DeclaredToolViewError, match="cannot be copied"):
            apply_declared_tool_view([original], authorized_names=frozenset())
        assert [tool.name for tool in original.tools] == ["denied"]

    def test_copy_returning_self_is_rejected_without_touching_the_original(self):
        class _SelfCopy(_DeclaringMiddleware):
            def __copy__(self):
                return self

        original = _SelfCopy([_tool("denied")])

        with pytest.raises(DeclaredToolViewError, match="returns self"):
            apply_declared_tool_view([original], authorized_names=frozenset())
        assert [tool.name for tool in original.tools] == ["denied"]

        class _Rebuilding(AgentMiddleware):
            state_schema = object  # non-None so delta normalization copies it

            def __init__(self, tools):
                super().__init__()
                self._ctor_tools = list(tools)
                self.tools = list(tools)

            def __copy__(self):
                return type(self)(self._ctor_tools)

        original = _Rebuilding([_tool("denied")])
        view = apply_declared_tool_view([original], authorized_names=frozenset())
        assert view[0].tools == ()

        normalized = normalize_middleware_state_schemas(view, "delta")

        with pytest.raises(DeclaredToolViewError, match="'denied'"):
            verify_declared_tool_view(normalized, authorized_names=frozenset())

    def test_state_preserving_copy_passes_the_whole_chain(self):
        class _StatePreserving(AgentMiddleware):
            state_schema = object  # non-None so delta normalization copies it

            def __init__(self, tools):
                super().__init__()
                self.tools = list(tools)

            def __copy__(self):
                clone = object.__new__(type(self))
                clone.__dict__.update(self.__dict__)
                return clone

        original = _StatePreserving([_tool("denied"), _tool("kept")])
        view = apply_declared_tool_view([original], authorized_names=frozenset({"kept"}))
        normalized = normalize_middleware_state_schemas(view, "delta")

        verify_declared_tool_view(normalized, authorized_names=frozenset({"kept"}))
        assert [tool.name for tool in normalized[0].tools] == ["kept"]
        assert [tool.name for tool in original.tools] == ["denied", "kept"]


class TestSafeAssignmentPrecondition:
    def test_forwarding_property_is_refused_before_any_write(self):
        setter_calls: list = []

        class _PropertyTools(AgentMiddleware):
            def __init__(self, tools):
                super().__init__()
                self.__dict__["_shared"] = {"tools": list(tools)}

            @property
            def tools(self):
                return self._shared["tools"]

            @tools.setter
            def tools(self, value):
                setter_calls.append(value)
                self._shared["tools"] = value

        original = _PropertyTools([_tool("denied"), _tool("kept")])

        with pytest.raises(DeclaredToolViewError, match="data descriptor"):
            apply_declared_tool_view([original], authorized_names=frozenset({"kept"}))

        assert setter_calls == []  # the setter was never invoked
        assert [tool.name for tool in original.tools] == ["denied", "kept"]

        # A later allowing build on the same instance still binds the tool.
        view = apply_declared_tool_view([original], authorized_names=frozenset({"denied", "kept"}))
        assert view[0] is original
        assert [tool.name for tool in view[0].tools] == ["denied", "kept"]

    def test_setattr_override_is_bypassed_by_the_direct_dict_write(self):
        class _SetattrTrap(AgentMiddleware):
            def __init__(self, tools):
                super().__init__()
                self.__dict__["tools"] = list(tools)

            def __setattr__(self, key, value):
                if key == "tools":
                    raise AssertionError("attribute assignment must never be used for narrowing")
                super().__setattr__(key, value)

        original = _SetattrTrap([_tool("denied"), _tool("kept")])

        view = apply_declared_tool_view([original], authorized_names=frozenset({"kept"}))

        assert view[0] is not original
        assert [tool.name for tool in view[0].tools] == ["kept"]
        assert [tool.name for tool in original.tools] == ["denied", "kept"]


class TestIsolatedMiddlewareCopyChain:
    def _wrap(self, inner: AgentMiddleware) -> IsolatedMiddleware:
        return IsolatedMiddleware(inner, "test:install", lambda diagnostic: None)

    def test_copy_copy_on_the_wrapper_preserves_state(self):
        inner = _DeclaringMiddleware([_tool("a"), _tool("b")])
        wrapper = self._wrap(inner)

        clone = copy.copy(wrapper)

        assert clone is not wrapper
        assert [tool.name for tool in clone.tools] == ["a", "b"]
        assert clone.inner is inner
        assert clone.name == wrapper.name

    def test_narrowing_survives_full_and_delta_normalization_and_a_copy_of_a_copy(self):
        allowed, denied = _tool("allowed_decl"), _tool("denied_decl")
        inner = _DeclaringMiddleware([allowed, denied])
        wrapper = self._wrap(inner)
        provider = _FilterProvider(["allowed_decl"])

        view, names = _narrow([wrapper], provider=provider, outcome=_outcome([], []))
        narrowed = view[0]
        assert narrowed is not wrapper
        assert narrowed.tools == (allowed,)

        full = normalize_middleware_state_schemas(view, "full")
        assert [tool.name for middleware in full for tool in middleware.tools] == ["allowed_decl"]
        verify_declared_tool_view(full, authorized_names=names)

        delta = normalize_middleware_state_schemas(view, "delta")
        verify_declared_tool_view(delta, authorized_names=names)
        assert [tool.name for middleware in delta for tool in middleware.tools] == ["allowed_decl"]

        recopied = copy.copy(delta[0])
        assert [tool.name for tool in recopied.tools] == ["allowed_decl"]

        # Neither the wrapper nor the contributor's inner was mutated.
        assert [tool.name for tool in wrapper.tools] == ["allowed_decl", "denied_decl"]
        assert [tool.name for tool in inner.tools] == ["allowed_decl", "denied_decl"]

    def test_denied_declaration_is_not_callable_end_to_end(self):
        """Through a real create_agent graph: the model asking for the denied
        declaration reaches an unbound name, never the tool implementation."""
        from _agent_e2e_helpers import build_single_tool_call_model
        from langchain.agents import create_agent

        calls: list[str] = []
        denied = StructuredTool.from_function(lambda: calls.append("denied") or "denied", name="denied_ext", description="denied")
        inner = _DeclaringMiddleware([denied])
        wrapper = self._wrap(inner)
        view, names = _narrow([wrapper], provider=_FilterProvider([]), outcome=_outcome([], []))

        model = build_single_tool_call_model(tool_name="denied_ext", tool_args={})
        agent = create_agent(model=model, tools=[], middleware=view)
        agent.invoke({"messages": [HumanMessage(content="run it")]})

        assert calls == []
        verify_declared_tool_view(view, authorized_names=names)

    def test_authorized_declaration_is_callable_end_to_end(self):
        from _agent_e2e_helpers import build_single_tool_call_model
        from langchain.agents import create_agent

        calls: list[str] = []
        allowed = StructuredTool.from_function(lambda: calls.append("allowed") or "allowed", name="allowed_ext", description="allowed")
        inner = _DeclaringMiddleware([allowed])
        wrapper = self._wrap(inner)
        view, _ = _narrow([wrapper], provider=_FilterProvider(["allowed_ext"]), outcome=_outcome([], []))

        model = build_single_tool_call_model(tool_name="allowed_ext", tool_args={})
        agent = create_agent(model=model, tools=[], middleware=view)
        agent.invoke({"messages": [HumanMessage(content="run it")]})

        assert calls == ["allowed"]


class TestCrossBuildIsolation:
    def test_deny_then_allow_on_one_caller_owned_instance(self):
        allowed, denied = _tool("allowed_decl"), _tool("denied_decl")
        original = _DeclaringMiddleware([allowed, denied])
        before = dict(original.__dict__)

        denying_view, _ = _narrow([original], provider=_FilterProvider(["allowed_decl"]), outcome=_outcome([], []))
        assert [tool.name for tool in denying_view[0].tools] == ["allowed_decl"]
        assert original.__dict__ == before  # byte-identical after the denying build

        allowing_view, _ = _narrow([original], provider=_FilterProvider(["allowed_decl", "denied_decl"]), outcome=_outcome([], []))
        assert allowing_view[0] is original
        assert [tool.name for tool in allowing_view[0].tools] == ["allowed_decl", "denied_decl"]

    def test_interleaved_builds_with_different_principals_see_their_own_view(self):
        class _RoleProvider(_FilterProvider):
            def filter_resources(self, principal, resource_type, candidates):
                self.calls.append((principal, resource_type, list(candidates)))
                allowed = {"admin": ["decl_a", "decl_b"], "guest": ["decl_a"]}[principal.role]
                return [candidate for candidate in candidates if candidate in allowed]

        original = _DeclaringMiddleware([_tool("decl_a"), _tool("decl_b")])
        provider = _RoleProvider([])

        guest_view, guest_names = _narrow([original], provider=provider, outcome=_outcome([], []), context={"user_role": "guest"})
        admin_view, admin_names = _narrow([original], provider=provider, outcome=_outcome([], []), context={"user_role": "admin"})

        assert [tool.name for tool in guest_view[0].tools] == ["decl_a"]
        assert guest_names == frozenset({"decl_a"})
        assert [tool.name for tool in admin_view[0].tools] == ["decl_a", "decl_b"]
        assert admin_names == frozenset({"decl_a", "decl_b"})
        assert [tool.name for tool in original.tools] == ["decl_a", "decl_b"]


class TestPlanModeWriteTodos:
    def test_denied_write_todos_is_removed_from_the_bound_name_set(self):
        provider = _FilterProvider(["bash"])  # policy covers tools, write_todos not allowed
        todo = TodoMiddleware()
        outcome = _outcome(["bash"], ["bash"])

        view, names = _narrow([todo], provider=provider, outcome=outcome)

        bound_names = {tool.name for middleware in view for tool in getattr(middleware, "tools", [])} | {"bash"}
        assert "write_todos" not in bound_names
        assert view[0] is not todo
        assert [tool.name for tool in todo.tools] == ["write_todos"]  # original untouched

    def test_unrestricted_policy_still_binds_write_todos(self):
        provider = _FilterProvider(["bash", "write_todos"])
        todo = TodoMiddleware()

        view, _ = _narrow([todo], provider=provider, outcome=_outcome(["bash"], ["bash"]))

        assert view[0] is todo
        assert [tool.name for tool in view[0].tools] == ["write_todos"]


def _runtime():
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread", "run_id": "test-run"}
    return runtime


def _model_request(messages):
    from langchain.agents.middleware.types import ModelRequest

    return ModelRequest(
        model=object(),
        messages=list(messages),
        state={"messages": list(messages)},
        runtime=_runtime(),
    )


class TestTodoDegradation:
    def _narrowed_todo(self) -> TodoMiddleware:
        todo = TodoMiddleware()
        view = apply_declared_tool_view([todo], authorized_names=frozenset({"bash"}))
        narrowed = view[0]
        assert narrowed.tools == ()
        return narrowed

    def _state_with_incomplete_todos(self):
        return {
            "messages": [HumanMessage(content="hi"), AIMessage(content="all done, no more tool calls")],
            "todos": [{"status": "in_progress", "content": "finish the task"}],
        }

    def test_no_system_prompt_injection_when_denied(self):
        narrowed = self._narrowed_todo()
        request = _model_request([HumanMessage(content="hi")])
        seen = []

        narrowed.wrap_model_call(request, lambda req: seen.append(req) or MagicMock())

        assert seen == [request]  # untouched request: no todo system prompt
        assert seen[0].system_message is None

    def test_system_prompt_injection_preserved_when_allowed(self):
        todo = TodoMiddleware()
        request = _model_request([HumanMessage(content="hi")])
        seen = []

        todo.wrap_model_call(request, lambda req: seen.append(req) or MagicMock())

        assert seen[0].system_message is not None
        assert "write_todos" in str(seen[0].system_message.content)

    def test_no_completion_reminder_or_jump_when_denied(self):
        narrowed = self._narrowed_todo()
        state = self._state_with_incomplete_todos()

        assert narrowed.after_model(state, _runtime()) is None
        assert asyncio.run(narrowed.aafter_model(state, _runtime())) is None

    def test_completion_enforcement_preserved_when_allowed(self):
        todo = TodoMiddleware()
        state = self._state_with_incomplete_todos()

        result = todo.after_model(state, _runtime())

        assert result == {"jump_to": "model"}

    def test_context_loss_detection_inert_when_denied(self):
        narrowed = self._narrowed_todo()
        state = self._state_with_incomplete_todos()

        assert narrowed.before_model(state, _runtime()) is None
        assert asyncio.run(narrowed.abefore_model(state, _runtime())) is None

    def test_context_loss_reminder_preserved_when_allowed(self):
        todo = TodoMiddleware()
        state = self._state_with_incomplete_todos()

        result = todo.before_model(state, _runtime())

        assert result is not None
        assert result["messages"][0].name == "todo_reminder"

    def test_async_model_call_passthrough_when_denied(self):
        narrowed = self._narrowed_todo()
        request = _model_request([HumanMessage(content="hi")])
        seen = []

        async def handler(req):
            seen.append(req)
            return MagicMock()

        asyncio.run(narrowed.awrap_model_call(request, handler))

        assert seen == [request]
        assert seen[0].system_message is None


class TestLeadAgentWiring:
    @pytest.mark.parametrize("is_bootstrap", [False, True])
    def test_denied_declaration_absent_from_the_bound_middleware_stack(self, monkeypatch, is_bootstrap):
        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.config.model_config import ModelConfig

        config = AppConfig(
            models=[
                ModelConfig(
                    name="test-model",
                    display_name="Test model",
                    use="langchain_openai:ChatOpenAI",
                    model="test-model",
                )
            ],
            sandbox=SandboxConfig(use="test"),
            authorization=AuthorizationConfig(
                enabled=True,
                provider=AuthorizationProviderConfig(
                    use="deerflow.authz.rbac:RbacAuthorizationProvider",
                    config={"roles": {"user": {"tools": {"allow": ["safe_tool", "history_read", "allowed_decl"]}}}},
                ),
            ),
        )
        config.skills.deferred_discovery = True
        config.task_continuity.enabled = True

        monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda *args, **kwargs: "test-model")
        monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
        monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
        monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "prompt")
        monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
        monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            lead_agent_module,
            "build_skill_search_setup",
            lambda *args, **kwargs: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
            raising=False,
        )
        monkeypatch.setattr("deerflow.skills.describe.build_skill_search_setup", lead_agent_module.build_skill_search_setup)
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_tool("safe_tool")])
        monkeypatch.setattr(lead_agent_module, "should_use_memory_tools", lambda memory_config: False)

        declaring = _DeclaringMiddleware([_tool("allowed_decl"), _tool("denied_decl")])
        monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [declaring])

        runtime_context = {"user_role": "user"}
        if is_bootstrap:
            runtime_context["is_bootstrap"] = True
        result = lead_agent_module._make_lead_agent({"context": runtime_context}, app_config=config)

        # Binding convention: declarations never enter final_tools ...
        assert "allowed_decl" not in [tool.name for tool in result["tools"]]
        assert "denied_decl" not in [tool.name for tool in result["tools"]]
        # ... and the bound middleware stack carries only the authorized declaration.
        (bound,) = result["middleware"]
        assert bound is not declaring
        assert [tool.name for tool in bound.tools] == ["allowed_decl"]
        assert [tool.name for tool in declaring.tools] == ["allowed_decl", "denied_decl"]


class TestClientWiring:
    def test_denied_declaration_absent_from_the_bound_middleware_stack(self, tmp_path):
        import deerflow.skills.storage as _storage_mod
        from deerflow.client import DeerFlowClient
        from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

        provider = _FilterProvider(["safe_tool", "allowed_decl"])
        app_config = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.model = "test-model"
        model.supports_thinking = False
        model.supports_reasoning_effort = False
        model.model_dump.return_value = {"name": "test-model", "use": "langchain_openai:ChatOpenAI"}
        app_config.models = [model]
        app_config.token_usage.enabled = False
        app_config.skills.deferred_discovery = False
        app_config.skills.container_path = "/mnt/skills"
        app_config.tool_search.enabled = False
        app_config.database.checkpoint_channel_mode = "full"
        app_config.database.checkpoint_delta.snapshot_frequency = 10
        app_config.authorization = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(use="unused:Provider"),
        )

        _storage_mod._default_skill_storage = LocalSkillStorage(host_path=str(tmp_path))
        declaring = _DeclaringMiddleware([_tool("allowed_decl"), _tool("denied_decl")])
        safe_tool = _tool("safe_tool")

        with patch("deerflow.client.get_app_config", return_value=app_config):
            client = DeerFlowClient()
        client._app_config = app_config

        with (
            patch("deerflow.client.create_chat_model"),
            patch("deerflow.client.create_agent", return_value=MagicMock()) as mock_create_agent,
            patch("deerflow.client.build_middlewares", return_value=[declaring]),
            patch("deerflow.client.apply_prompt_template", return_value="prompt"),
            patch("deerflow.client.get_enabled_skills_for_config", return_value=[]),
            patch.object(client, "_get_tools", return_value=[safe_tool]),
            patch("deerflow.authz.tool_filter.resolve_authorization_provider", return_value=provider),
            patch("deerflow.agents.lead_agent.agent.resolve_authorization_provider", return_value=provider),
            # Phase 3 resolves a skill-authorization provider through
            # skill_filter's own import; a separate double keeps the tool-path
            # call assertions below exact.
            patch("deerflow.authz.skill_filter.resolve_authorization_provider", return_value=_FilterProvider([])),
            patch("deerflow.runtime.checkpointer.get_checkpointer", return_value=None),
        ):
            client._ensure_agent(client._get_runnable_config("t1"), context={"user_role": "user"})

        (bound,) = mock_create_agent.call_args.kwargs["middleware"]
        assert bound is not declaring
        assert [tool.name for tool in bound.tools] == ["allowed_decl"]
        assert [tool.name for tool in declaring.tools] == ["allowed_decl", "denied_decl"]
        assert [tool.name for tool in mock_create_agent.call_args.kwargs["tools"]] == ["safe_tool"]
        # One provider instance, two passes: the declared names were the second call.
        assert [call[2] for call in provider.calls] == [["safe_tool"], ["allowed_decl", "denied_decl"]]


class TestDescriptorConsistency:
    def test_descriptor_reports_the_narrowed_set(self):
        from deerflow.agents.assembly_descriptor import build_assembly_descriptor

        allowed, denied = _tool("allowed_decl"), _tool("denied_decl")
        original = _DeclaringMiddleware([allowed, denied])
        view, _ = _narrow([original], provider=_FilterProvider(["allowed_decl"]), outcome=_outcome([], []))

        descriptor = build_assembly_descriptor(
            namespace="deerflow",
            agent_name="test",
            requested_model="test-model",
            effective_model="test-model",
            model_config=None,
            thinking_enabled=False,
            reasoning_effort=None,
            rendered_base_prompt="prompt",
            prompt_template_id="test",
            tools=[_tool("regular")],
            middlewares=view,
            deferred_names=frozenset(),
            enabled_skills=[],
            effective_policies={},
        )

        reported_names = [tool.name for tool in descriptor.tools]
        assert "allowed_decl" in reported_names
        assert "denied_decl" not in reported_names
