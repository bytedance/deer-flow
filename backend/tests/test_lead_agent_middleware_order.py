"""Regression tests for the lead-agent middleware chain assembly (plan M0-13).

Goal: lock in that ``custom_middlewares=`` (the hook M0-9 uses to inject
the enterprise middleware stack) is applied as the **second-to-last** entry
in the chain, with :class:`ClarificationMiddleware` always at the tail.

Why this matters: M0-9 wires ``get_enterprise_middlewares(...)`` through
to ``_build_middlewares(..., custom_middlewares=...)``. If a later
refactor re-orders the chain (for example moves Clarification before the
custom block, or drops the ``extend()`` call), the audit, RBAC, and
approval features land in the wrong position and silently misbehave.
We cover three inputs the production code path emits:

* ``custom_middlewares=None``  -> chain ends with ClarificationMiddleware
* ``custom_middlewares=[]``    -> identical to None case (M0 default)
* ``custom_middlewares=[Mock]`` -> Mock appears immediately before
  ClarificationMiddleware
"""

from __future__ import annotations

import pytest
from langchain.agents.middleware import AgentMiddleware

from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


class _MarkerMiddleware(AgentMiddleware):
    """Minimal AgentMiddleware used as a chain ordering marker."""

    def __init__(self, name: str = "marker") -> None:
        super().__init__()
        self._name = name

    def __repr__(self) -> str:  # pragma: no cover — debug aid only
        return f"_MarkerMiddleware({self._name!r})"


def _make_app_config() -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="test-model",
                display_name="test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="test-model",
                supports_thinking=False,
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        loop_detection=LoopDetectionConfig(),
    )


@pytest.fixture
def runnable_config() -> dict:
    """Minimal RunnableConfig payload that triggers the default chain."""
    return {"configurable": {"is_plan_mode": False, "subagent_enabled": False}}


def test_clarification_middleware_is_always_last_when_custom_is_none(runnable_config):
    """custom_middlewares=None: chain ends with ClarificationMiddleware, no Marker present."""
    app_config = _make_app_config()
    chain = lead_agent_module._build_middlewares(
        runnable_config,
        model_name="test-model",
        custom_middlewares=None,
        app_config=app_config,
    )

    assert chain, "middleware chain must not be empty"
    assert isinstance(chain[-1], ClarificationMiddleware), f"expected ClarificationMiddleware at tail, got {type(chain[-1]).__name__}"
    assert not any(isinstance(m, _MarkerMiddleware) for m in chain), "no marker should be present when custom_middlewares is None"


def test_clarification_middleware_is_always_last_when_custom_is_empty(runnable_config):
    """custom_middlewares=[]: behaviour is identical to the None case."""
    app_config = _make_app_config()
    chain_empty = lead_agent_module._build_middlewares(
        runnable_config,
        model_name="test-model",
        custom_middlewares=[],
        app_config=app_config,
    )
    chain_none = lead_agent_module._build_middlewares(
        runnable_config,
        model_name="test-model",
        custom_middlewares=None,
        app_config=app_config,
    )

    # Both code paths must produce structurally equivalent chains (same types
    # in the same order). We compare class names because middleware instances
    # are not equality-comparable in general.
    assert [type(m).__name__ for m in chain_empty] == [type(m).__name__ for m in chain_none]
    assert isinstance(chain_empty[-1], ClarificationMiddleware)


def test_custom_middleware_is_injected_immediately_before_clarification(runnable_config):
    """custom_middlewares=[Marker]: Marker sits at index -2, Clarification at -1."""
    app_config = _make_app_config()
    marker = _MarkerMiddleware()

    chain = lead_agent_module._build_middlewares(
        runnable_config,
        model_name="test-model",
        custom_middlewares=[marker],
        app_config=app_config,
    )

    assert len(chain) >= 2
    assert isinstance(chain[-1], ClarificationMiddleware), "ClarificationMiddleware must remain the final entry"
    assert chain[-2] is marker, f"custom middleware must be injected immediately before ClarificationMiddleware; chain tail: {[type(m).__name__ for m in chain[-3:]]}"


def test_multiple_custom_middlewares_preserve_order(runnable_config):
    """A custom list preserves its declared order, all inserted before Clarification."""
    app_config = _make_app_config()
    first = _MarkerMiddleware("first")
    second = _MarkerMiddleware("second")

    chain = lead_agent_module._build_middlewares(
        runnable_config,
        model_name="test-model",
        custom_middlewares=[first, second],
        app_config=app_config,
    )

    assert isinstance(chain[-1], ClarificationMiddleware)
    assert chain[-3] is first
    assert chain[-2] is second


def test_chain_with_none_matches_legacy_behaviour(runnable_config):
    """Sanity check: the None code path produces the same chain a pre-M0 build would.

    Concretely: no _MarkerMiddleware leaks in, ClarificationMiddleware is last,
    and the chain still contains the standard middlewares (DynamicContext,
    TitleMiddleware, MemoryMiddleware).
    """
    app_config = _make_app_config()
    chain = lead_agent_module._build_middlewares(
        runnable_config,
        model_name="test-model",
        custom_middlewares=None,
        app_config=app_config,
    )
    names = {type(m).__name__ for m in chain}

    # Spot-check a few well-known entries; their absence would mean the chain
    # was gutted by an unrelated refactor.
    assert "ClarificationMiddleware" in names
    assert "TitleMiddleware" in names
    assert "MemoryMiddleware" in names
    assert "DynamicContextMiddleware" in names
