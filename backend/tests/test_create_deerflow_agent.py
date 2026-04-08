"""Tests for create_deerflow_agent SDK entry point."""

from typing import get_type_hints
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.factory import create_deerflow_agent
from deerflow.agents.features import Next, Prev, RuntimeFeatures
from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.agents.thread_state import ThreadState


def _make_mock_model():
    return MagicMock(name="mock_model")


def _make_mock_tool(name: str = "my_tool"):
    tool = MagicMock(name=name)
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# 1. Minimal creation — only model
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_minimal_creation(mock_create_agent):
    mock_create_agent.return_value = MagicMock(name="compiled_graph")
    model = _make_mock_model()

    result = create_deerflow_agent(model)

    mock_create_agent.assert_called_once()
    assert result is mock_create_agent.return_value
    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["model"] is model
    assert call_kwargs["system_prompt"] is None


# ---------------------------------------------------------------------------
# 2. With tools
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_with_tools(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    model = _make_mock_model()
    tool = _make_mock_tool("search")

    create_deerflow_agent(model, tools=[tool])

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "search" in tool_names


# ---------------------------------------------------------------------------
# 3. With system_prompt
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_with_system_prompt(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    prompt = "You are a helpful assistant."

    create_deerflow_agent(_make_mock_model(), system_prompt=prompt)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["system_prompt"] == prompt


# ---------------------------------------------------------------------------
# 4. Features mode — auto-assemble middleware chain
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_features_mode(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=True, auto_title=True)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert len(middleware) > 0
    mw_types = [type(m).__name__ for m in middleware]
    assert "ThreadDataMiddleware" in mw_types
    assert "SandboxMiddleware" in mw_types
    assert "TitleMiddleware" in mw_types
    assert "ClarificationMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 5. Middleware full takeover
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_middleware_takeover(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    custom_mw = MagicMock(name="custom_middleware")
    custom_mw.name = "custom"

    create_deerflow_agent(_make_mock_model(), middleware=[custom_mw])

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["middleware"] == [custom_mw]


# ---------------------------------------------------------------------------
# 6. Conflict — middleware + features raises ValueError
# ---------------------------------------------------------------------------
def test_middleware_and_features_conflict():
    with pytest.raises(ValueError, match="Cannot specify both"):
        create_deerflow_agent(
            _make_mock_model(),
            middleware=[MagicMock()],
            features=RuntimeFeatures(),
        )


# ---------------------------------------------------------------------------
# 7. Vision feature auto-injects view_image_tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_vision_injects_view_image_tool(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(vision=True, sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "view_image" in tool_names


def test_view_image_middleware_preserves_viewed_images_reducer():
    middleware_hints = get_type_hints(ViewImageMiddleware.state_schema, include_extras=True)
    thread_hints = get_type_hints(ThreadState, include_extras=True)

    assert middleware_hints["viewed_images"] == thread_hints["viewed_images"]


# ---------------------------------------------------------------------------
# 8. Subagent feature auto-injects task_tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_subagent_injects_task_tool(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(subagent=True, sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "task" in tool_names


# ---------------------------------------------------------------------------
# 9. Middleware ordering — ClarificationMiddleware always last
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_clarification_always_last(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=True, memory=True, vision=True)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    last_mw = middleware[-1]
    assert type(last_mw).__name__ == "ClarificationMiddleware"


# ---------------------------------------------------------------------------
# 10. RuntimeFeatures default values
# ---------------------------------------------------------------------------
def test_agent_features_defaults():
    f = RuntimeFeatures()
    assert f.sandbox is True
    assert f.memory is False
    assert f.summarization is False
    assert f.subagent is False
    assert f.vision is False
    assert f.auto_title is False
    assert f.guardrail is False


# ---------------------------------------------------------------------------
# 11. Tool deduplication — user-provided tools take priority
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_tool_deduplication(mock_create_agent):
    """If user provides a tool with the same name as an auto-injected one, no duplicate."""
    mock_create_agent.return_value = MagicMock()
    user_clarification = _make_mock_tool("ask_clarification")

    create_deerflow_agent(_make_mock_model(), tools=[user_clarification], features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    names = [t.name for t in call_kwargs["tools"]]
    assert names.count("ask_clarification") == 1
    # The first one should be the user-provided tool
    assert call_kwargs["tools"][0] is user_clarification


# ---------------------------------------------------------------------------
# 12. Sandbox disabled — no ThreadData/Uploads/Sandbox middleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_sandbox_disabled(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "ThreadDataMiddleware" not in mw_types
    assert "UploadsMiddleware" not in mw_types
    assert "SandboxMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 13. Checkpointer passed through
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_checkpointer_passthrough(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    cp = MagicMock(name="checkpointer")

    create_deerflow_agent(_make_mock_model(), checkpointer=cp)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["checkpointer"] is cp


# ---------------------------------------------------------------------------
# 14. Custom AgentMiddleware instance replaces default
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_custom_middleware_replaces_default(mock_create_agent):
    """Passing an AgentMiddleware instance uses it directly instead of the built-in default."""
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MyMemoryMiddleware(AgentMiddleware):
        pass

    custom_memory = MyMemoryMiddleware()
    feat = RuntimeFeatures(sandbox=False, memory=custom_memory)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom_memory in middleware
    # Should NOT have the default MemoryMiddleware
    mw_types = [type(m).__name__ for m in middleware]
    assert "MemoryMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 15. Custom sandbox middleware replaces the 3-middleware group
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_custom_sandbox_replaces_group(mock_create_agent):
    """Passing an AgentMiddleware for sandbox replaces ThreadData+Uploads+Sandbox with one."""
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MySandbox(AgentMiddleware):
        pass

    custom_sb = MySandbox()
    feat = RuntimeFeatures(sandbox=custom_sb)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom_sb in middleware
    mw_types = [type(m).__name__ for m in middleware]
    assert "ThreadDataMiddleware" not in mw_types
    assert "UploadsMiddleware" not in mw_types
    assert "SandboxMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 16. Always-on error handling middlewares are present
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_always_on_error_handling(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = RuntimeFeatures(sandbox=False)

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "DanglingToolCallMiddleware" in mw_types
    assert "ToolErrorHandlingMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 17. Vision with custom middleware still injects tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_vision_custom_middleware_still_injects_tool(mock_create_agent):
    """Custom vision middleware still gets the view_image_tool auto-injected."""
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MyVision(AgentMiddleware):
        pass

    feat = RuntimeFeatures(sandbox=False, vision=MyVision())

    create_deerflow_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "view_image" in tool_names


# ===========================================================================
# @Next / @Prev decorators and extra_middleware insertion
# ===========================================================================


# ---------------------------------------------------------------------------
# 18. @Next decorator sets _next_anchor
# ---------------------------------------------------------------------------
def test_next_decorator():
    from langchain.agents.middleware import AgentMiddleware

    class Anchor(AgentMiddleware):
        pass

    @Next(Anchor)
    class MyMW(AgentMiddleware):
        pass

    assert MyMW._next_anchor is Anchor


# ---------------------------------------------------------------------------
# 19. @Prev decorator sets _prev_anchor
# ---------------------------------------------------------------------------
def test_prev_decorator():
    from langchain.agents.middleware import AgentMiddleware

    class Anchor(AgentMiddleware):
        pass

    @Prev(Anchor)
    class MyMW(AgentMiddleware):
        pass

    assert MyMW._prev_anchor is Anchor


# ---------------------------------------------------------------------------
# 20. extra_middleware with @Next inserts after anchor
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_next_inserts_after_anchor(mock_create_agent):
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    mock_create_agent.return_value = MagicMock()

    @Next(DanglingToolCallMiddleware)
    class MyAudit(AgentMiddleware):
        pass

    audit = MyAudit()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[audit],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    dangling_idx = mw_types.index("DanglingToolCallMiddleware")
    audit_idx = mw_types.index("MyAudit")
    assert audit_idx == dangling_idx + 1


# ---------------------------------------------------------------------------
# 21. extra_middleware with @Prev inserts before anchor
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_prev_inserts_before_anchor(mock_create_agent):
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    mock_create_agent.return_value = MagicMock()

    @Prev(ClarificationMiddleware)
    class MyFilter(AgentMiddleware):
        pass

    filt = MyFilter()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[filt],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    clar_idx = mw_types.index("ClarificationMiddleware")
    filt_idx = mw_types.index("MyFilter")
    assert filt_idx == clar_idx - 1


# ---------------------------------------------------------------------------
# 22. Unanchored extra_middleware goes before ClarificationMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_unanchored_before_clarification(mock_create_agent):
    from langchain.agents.middleware import AgentMiddleware

    mock_create_agent.return_value = MagicMock()

    class MyPlain(AgentMiddleware):
        pass

    plain = MyPlain()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[plain],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    assert mw_types[-1] == "ClarificationMiddleware"
    assert mw_types[-2] == "MyPlain"


# ---------------------------------------------------------------------------
# 23. Conflict: two extras @Next same anchor → ValueError
# ---------------------------------------------------------------------------
def test_extra_conflict_same_next_target():
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    @Next(DanglingToolCallMiddleware)
    class MW1(AgentMiddleware):
        pass

    @Next(DanglingToolCallMiddleware)
    class MW2(AgentMiddleware):
        pass

    with pytest.raises(ValueError, match="Conflict"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW1(), MW2()],
        )


# ---------------------------------------------------------------------------
# 24. Conflict: two extras @Prev same anchor → ValueError
# ---------------------------------------------------------------------------
def test_extra_conflict_same_prev_target():
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    @Prev(ClarificationMiddleware)
    class MW1(AgentMiddleware):
        pass

    @Prev(ClarificationMiddleware)
    class MW2(AgentMiddleware):
        pass

    with pytest.raises(ValueError, match="Conflict"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW1(), MW2()],
        )


# ---------------------------------------------------------------------------
# 25. Both @Next and @Prev on same class → ValueError
# ---------------------------------------------------------------------------
def test_extra_both_next_and_prev_error():
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    class MW(AgentMiddleware):
        pass

    MW._next_anchor = DanglingToolCallMiddleware
    MW._prev_anchor = ClarificationMiddleware

    with pytest.raises(ValueError, match="both @Next and @Prev"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW()],
        )


# ---------------------------------------------------------------------------
# 26. Cross-external anchoring: extra anchors to another extra
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_extra_cross_external_anchoring(mock_create_agent):
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    mock_create_agent.return_value = MagicMock()

    @Next(DanglingToolCallMiddleware)
    class First(AgentMiddleware):
        pass

    @Next(First)
    class Second(AgentMiddleware):
        pass

    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[Second(), First()],  # intentionally reversed
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    dangling_idx = mw_types.index("DanglingToolCallMiddleware")
    first_idx = mw_types.index("First")
    second_idx = mw_types.index("Second")
    assert first_idx == dangling_idx + 1
    assert second_idx == first_idx + 1


# ---------------------------------------------------------------------------
# 27. Unresolvable anchor → ValueError
# ---------------------------------------------------------------------------
def test_extra_unresolvable_anchor():
    from langchain.agents.middleware import AgentMiddleware

    class Ghost(AgentMiddleware):
        pass

    @Next(Ghost)
    class MW(AgentMiddleware):
        pass

    with pytest.raises(ValueError, match="Cannot resolve"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW()],
        )


# ---------------------------------------------------------------------------
# 28. extra_middleware + middleware (full takeover) → ValueError
# ---------------------------------------------------------------------------
def test_extra_with_middleware_takeover_conflict():
    with pytest.raises(ValueError, match="full takeover"):
        create_deerflow_agent(
            _make_mock_model(),
            middleware=[MagicMock()],
            extra_middleware=[MagicMock()],
        )


# ===========================================================================
# LoopDetection, TodoMiddleware, GuardrailMiddleware
# ===========================================================================


# ---------------------------------------------------------------------------
# 29. LoopDetectionMiddleware is always present
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_loop_detection_always_present(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "LoopDetectionMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 30. LoopDetection before Clarification
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_loop_detection_before_clarification(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    loop_idx = mw_types.index("LoopDetectionMiddleware")
    clar_idx = mw_types.index("ClarificationMiddleware")
    assert loop_idx < clar_idx
    assert loop_idx == clar_idx - 1


# ---------------------------------------------------------------------------
# 31. plan_mode=True adds TodoMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_plan_mode_adds_todo_middleware(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False), plan_mode=True)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "TodoMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 32. plan_mode=False (default) — no TodoMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_plan_mode_default_no_todo(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "TodoMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 33. summarization=True without model → ValueError
# ---------------------------------------------------------------------------
def test_summarization_true_raises():
    with pytest.raises(ValueError, match="requires a custom AgentMiddleware"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False, summarization=True),
        )


# ---------------------------------------------------------------------------
# 34. guardrail=True without built-in → ValueError
# ---------------------------------------------------------------------------
def test_guardrail_true_raises():
    with pytest.raises(ValueError, match="requires a custom AgentMiddleware"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False, guardrail=True),
        )


# ---------------------------------------------------------------------------
# 34. guardrail with custom AgentMiddleware replaces default
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_guardrail_custom_middleware(mock_create_agent):
    from langchain.agents.middleware import AgentMiddleware as AM

    mock_create_agent.return_value = MagicMock()

    class MyGuardrail(AM):
        pass

    custom = MyGuardrail()
    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False, guardrail=custom),
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert custom in middleware
    mw_types = [type(m).__name__ for m in middleware]
    assert "GuardrailMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 35. guardrail=False (default) — no GuardrailMiddleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_guardrail_default_off(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    create_deerflow_agent(_make_mock_model(), features=RuntimeFeatures(sandbox=False))

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "GuardrailMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 36. Full chain order matches make_lead_agent (all features on)
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_full_chain_order(mock_create_agent):
    from langchain.agents.middleware import AgentMiddleware as AM

    mock_create_agent.return_value = MagicMock()

    class MyGuardrail(AM):
        pass

    class MySummarization(AM):
        pass

    feat = RuntimeFeatures(
        sandbox=True,
        memory=True,
        summarization=MySummarization(),
        subagent=True,
        vision=True,
        auto_title=True,
        guardrail=MyGuardrail(),
    )
    create_deerflow_agent(_make_mock_model(), features=feat, plan_mode=True)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]

    expected_order = [
        "ThreadDataMiddleware",
        "UploadsMiddleware",
        "SandboxMiddleware",
        "DanglingToolCallMiddleware",
        "MyGuardrail",
        "ToolErrorHandlingMiddleware",
        "MySummarization",
        "TodoMiddleware",
        "TitleMiddleware",
        "MemoryMiddleware",
        "ViewImageMiddleware",
        "SubagentLimitMiddleware",
        "LoopDetectionMiddleware",
        "ClarificationMiddleware",
    ]
    assert mw_types == expected_order


# ---------------------------------------------------------------------------
# 37. @Next(ClarificationMiddleware) does not break tail invariant
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_next_clarification_preserves_tail_invariant(mock_create_agent):
    """Even with @Next(ClarificationMiddleware), Clarification stays last."""
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    mock_create_agent.return_value = MagicMock()

    @Next(ClarificationMiddleware)
    class AfterClar(AgentMiddleware):
        pass

    create_deerflow_agent(
        _make_mock_model(),
        features=RuntimeFeatures(sandbox=False),
        extra_middleware=[AfterClar()],
    )

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    mw_types = [type(m).__name__ for m in middleware]
    assert mw_types[-1] == "ClarificationMiddleware"
    assert "AfterClar" in mw_types


# ---------------------------------------------------------------------------
# 38. @Next(X) + @Prev(X) on same anchor from different extras → ValueError
# ---------------------------------------------------------------------------
def test_extra_opposite_direction_same_anchor_conflict():
    from langchain.agents.middleware import AgentMiddleware

    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    @Next(DanglingToolCallMiddleware)
    class AfterDangling(AgentMiddleware):
        pass

    @Prev(DanglingToolCallMiddleware)
    class BeforeDangling(AgentMiddleware):
        pass

    with pytest.raises(ValueError, match="cross-anchoring"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[AfterDangling(), BeforeDangling()],
        )


# ===========================================================================
# Input validation and error message hardening
# ===========================================================================


# ---------------------------------------------------------------------------
# 39. @Next with non-AgentMiddleware anchor → TypeError
# ---------------------------------------------------------------------------
def test_next_bad_anchor_type():
    with pytest.raises(TypeError, match="AgentMiddleware subclass"):

        @Next(str)  # type: ignore[arg-type]
        class MW:
            pass


# ---------------------------------------------------------------------------
# 40. @Prev with non-AgentMiddleware anchor → TypeError
# ---------------------------------------------------------------------------
def test_prev_bad_anchor_type():
    with pytest.raises(TypeError, match="AgentMiddleware subclass"):

        @Prev(42)  # type: ignore[arg-type]
        class MW:
            pass


# ---------------------------------------------------------------------------
# 41. extra_middleware with non-AgentMiddleware item → TypeError
# ---------------------------------------------------------------------------
def test_extra_middleware_bad_type():
    with pytest.raises(TypeError, match="AgentMiddleware instances"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[object()],  # type: ignore[list-item]
        )


# ---------------------------------------------------------------------------
# 42. Circular dependency among extras → clear error message
# ---------------------------------------------------------------------------
def test_extra_circular_dependency():
    from langchain.agents.middleware import AgentMiddleware

    class MW_A(AgentMiddleware):
        pass

    class MW_B(AgentMiddleware):
        pass

    MW_A._next_anchor = MW_B  # type: ignore[attr-defined]
    MW_B._next_anchor = MW_A  # type: ignore[attr-defined]

    with pytest.raises(ValueError, match="Circular dependency"):
        create_deerflow_agent(
            _make_mock_model(),
            features=RuntimeFeatures(sandbox=False),
            extra_middleware=[MW_A(), MW_B()],
        )
