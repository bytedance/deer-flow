"""Middlewares describe their own behaviour-affecting parameters.

Two runs that used different limits are different runs. Reconstructing that
from outside means reading private attributes and guessing which ones matter;
each middleware declares it instead.
"""

import importlib

import pytest
from deerflow_extension_api import ReleasePolicyProvider, canonical_hash, canonical_json, collect_release_policies
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_is_stable_across_processes_for_nested_values():
    assert canonical_json({"a": [1, {"d": 4, "c": 3}]}) == '{"a":[1,{"c":3,"d":4}]}'


def test_canonical_hash_differs_when_a_value_differs():
    assert canonical_hash({"limit": 5}) != canonical_hash({"limit": 6})


def test_canonical_json_rejects_unserialisable_values_loudly():
    with pytest.raises(TypeError):
        canonical_json({"f": object()})


def test_collect_skips_middlewares_that_declare_nothing():
    class Silent:
        pass

    class Declaring:
        def release_policy_parameters(self):
            return {"limit": 3}

    assert collect_release_policies([Silent(), Declaring()]) == {"Declaring": {"limit": 3}}


def test_collect_survives_a_middleware_whose_declaration_raises():
    class Broken:
        def release_policy_parameters(self):
            raise RuntimeError("boom")

    class Fine:
        def release_policy_parameters(self):
            return {"ok": True}

    result = collect_release_policies([Broken(), Fine()])
    assert result["Fine"] == {"ok": True}
    assert result["Broken"] == {"error": "RuntimeError"}


def test_collect_survives_two_middlewares_of_the_same_class():
    """A second instance of the same class must not overwrite the first."""

    class Declaring:
        def __init__(self, limit):
            self._limit = limit

        def release_policy_parameters(self):
            return {"limit": self._limit}

    result = collect_release_policies([Declaring(1), Declaring(2)])
    assert result == {"Declaring": {"limit": 1}, "Declaring#2": {"limit": 2}}


def test_collect_unwraps_an_isolation_style_wrapper():
    """A contributed middleware reaches the stack behind a duck-typed ``.inner``
    wrapper; describing the wrapper instead of the real middleware would
    collapse every extension contribution into one shared, empty entry."""

    class Wrapped:
        def release_policy_parameters(self):
            return {"limit": 3}

    class Wrapper:
        def __init__(self, inner):
            self.inner = inner

    assert collect_release_policies([Wrapper(Wrapped())]) == {"Wrapped": {"limit": 3}}


def test_protocol_is_runtime_checkable():
    class Declaring:
        def release_policy_parameters(self):
            return {}

    assert isinstance(Declaring(), ReleasePolicyProvider)


class _StaticChatModel(BaseChatModel):
    """Minimal real ``BaseChatModel`` that never calls a provider.

    Mirrors the construction-time stand-in already used by
    ``test_summarization_middleware.py``'s ``_StaticChatModel``: summarization
    middleware construction needs a model object, but no API key or network
    access, so a real (non-string) ``BaseChatModel`` subclass sidesteps
    ``langchain``'s ``init_chat_model`` entirely.
    """

    text: str = "ok"

    @property
    def _llm_type(self) -> str:
        return "static-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])


def _make_loop_detection_middleware():
    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

    return LoopDetectionMiddleware()


def _make_subagent_limit_middleware():
    from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware

    return SubagentLimitMiddleware(max_concurrent=2, max_total=6)


def _make_terminal_response_middleware():
    from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware

    return TerminalResponseMiddleware()


def _make_todo_middleware():
    from deerflow.agents.middlewares.todo_middleware import TodoMiddleware

    return TodoMiddleware()


def _make_token_budget_middleware():
    from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
    from deerflow.config.token_budget_config import TokenBudgetConfig

    return TokenBudgetMiddleware(config=TokenBudgetConfig())


def _make_deferred_tool_filter_middleware():
    from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

    return DeferredToolFilterMiddleware(deferred_names=frozenset({"tool_b", "tool_a"}), catalog_hash="catalog-1")


def _make_safety_finish_reason_middleware():
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

    return SafetyFinishReasonMiddleware()


def _make_summarization_middleware():
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    return DeerFlowSummarizationMiddleware(
        model=_StaticChatModel(),
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
    )


def _make_tool_output_budget_middleware():
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware

    return ToolOutputBudgetMiddleware()


def _make_skill_activation_middleware():
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

    return SkillActivationMiddleware(available_skills={"skill-b", "skill-a"}, slash_source_owner_token="test-owner-token")


def _make_system_message_coalescing_middleware():
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    return SystemMessageCoalescingMiddleware()


# Single source of truth for "which middlewares declare a release policy" so
# the existence check and the construct-call-hash check below can never drift
# apart into two separately-maintained middleware lists. Every entry here is
# constructible with the minimum arguments needed for a valid instance; if a
# future addition genuinely cannot be constructed in a unit test, keep its
# entry and mark it with `pytest.param(..., marks=pytest.mark.skip(reason=...))`
# instead of dropping it — a documented gap beats an invisible one.
_MIDDLEWARE_DECLARATIONS = [
    ("deerflow.agents.middlewares.loop_detection_middleware", "LoopDetectionMiddleware", _make_loop_detection_middleware),
    ("deerflow.agents.middlewares.subagent_limit_middleware", "SubagentLimitMiddleware", _make_subagent_limit_middleware),
    ("deerflow.agents.middlewares.terminal_response_middleware", "TerminalResponseMiddleware", _make_terminal_response_middleware),
    # DeerFlow's own subclass, not the LangChain base class re-exported into
    # this module under the same import path (TodoListMiddleware).
    ("deerflow.agents.middlewares.todo_middleware", "TodoMiddleware", _make_todo_middleware),
    ("deerflow.agents.middlewares.token_budget_middleware", "TokenBudgetMiddleware", _make_token_budget_middleware),
    ("deerflow.agents.middlewares.deferred_tool_filter_middleware", "DeferredToolFilterMiddleware", _make_deferred_tool_filter_middleware),
    ("deerflow.agents.middlewares.safety_finish_reason_middleware", "SafetyFinishReasonMiddleware", _make_safety_finish_reason_middleware),
    ("deerflow.agents.middlewares.summarization_middleware", "DeerFlowSummarizationMiddleware", _make_summarization_middleware),
    ("deerflow.agents.middlewares.tool_output_budget_middleware", "ToolOutputBudgetMiddleware", _make_tool_output_budget_middleware),
    ("deerflow.agents.middlewares.skill_activation_middleware", "SkillActivationMiddleware", _make_skill_activation_middleware),
    ("deerflow.agents.middlewares.system_message_coalescing_middleware", "SystemMessageCoalescingMiddleware", _make_system_message_coalescing_middleware),
]


@pytest.mark.parametrize("import_path,class_name,make_instance", _MIDDLEWARE_DECLARATIONS)
def test_middleware_declares_release_policy_parameters(import_path, class_name, make_instance):
    cls = getattr(importlib.import_module(import_path), class_name)
    assert hasattr(cls, "release_policy_parameters"), f"{class_name} must declare its behaviour policy"


@pytest.mark.parametrize("import_path,class_name,make_instance", _MIDDLEWARE_DECLARATIONS)
def test_middleware_release_policy_parameters_are_canonically_serialisable(import_path, class_name, make_instance):
    """A declaration that cannot be hashed is not usable as release identity.

    Unlike ``test_middleware_declares_release_policy_parameters`` above (which
    only checks the method exists), this constructs a real instance and calls
    it for real. A set-typed or model-typed field added to any declaration
    later would raise ``TypeError`` here — a bare ``hasattr`` check would stay
    green while the identity mechanism this slice exists to provide breaks
    silently.
    """
    cls = getattr(importlib.import_module(import_path), class_name)
    middleware = make_instance()
    assert isinstance(middleware, cls)
    params = middleware.release_policy_parameters()
    assert isinstance(params, dict)
    canonical_hash(params)
