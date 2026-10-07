"""A→B isolation guard (spec 2026-09-23 default model D6 / §4 item 7).

Two snapshots, identical except ``rag.default_model`` (``None`` vs ``"B"``), over models
``[A, B]`` where only ``A`` declares vision. ``A`` is first, so it is what every non-RAG seam
picks — which makes "did the RAG default leak here?" a one-line comparison per seam.

The positive half pins that the RAG roles *do* move; the negative half pins each host
selection seam and each other functional-model leg in place, one assertion per call site, so
"covered" cannot quietly mean "mostly covered". Two seams cannot be driven without a live
client or a whole agent build; those are pinned at the source and named as such.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig, RagConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

HARNESS = Path(__file__).resolve().parents[1] / "packages" / "harness" / "deerflow"
#: The knowledge legs live in the extension package (Task 3): their non-role members are
#: pinned against that root instead of the harness one.
KNOWLEDGE = Path(__file__).resolve().parents[1] / "packages" / "knowledge-extension" / "deerflow_knowledge"

#: The field name as a *field* — ``_default_model_name`` is a different thing entirely and
#: must not be mistaken for a leak.
FIELD = re.compile(r"\bdefault_model\b(?!_)")

#: Non-role legs: they take their own provider/model settings and never the RAG default.
NOT_ROLE_LEGS = (
    "embedder_factory.py",
    "reranker_factory.py",
    "providers/__init__.py",
    "parse_local.py",
)

#: Seams that need a live client / a full agent build to drive behaviourally. Pinned at the
#: source instead, and recorded as such in the plan's 实测.
SOURCE_PINNED_SEAMS = (
    "agents/middlewares/summarization_middleware.py",  # :716, the enabled-summarization factory
    "client.py",  # :301, DeerFlowClient's own lead-agent construction
)


def _model(name: str, *, vision: bool = False) -> ModelConfig:
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use="langchain_openai:ChatOpenAI",
        model=f"{name}-wire",
        api_key="test-key",
        supports_thinking=False,
        supports_vision=vision,
    )


def _snapshot(default_model: str | None) -> AppConfig:
    return AppConfig(
        models=[_model("A", vision=True), _model("B")],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        rag=RagConfig(default_model=default_model),
    )


@pytest.fixture
def pair() -> tuple[AppConfig, AppConfig]:
    """(without the RAG default, with it set to B)."""
    return _snapshot(None), _snapshot("B")


# ── the premise: only the RAG default differs ────────────────────────────


def test_the_two_snapshots_differ_only_in_the_rag_default(pair):
    without, with_default = pair

    assert without.rag.default_model is None
    assert with_default.rag.default_model == "B"
    assert without.rag.model_dump(exclude={"default_model"}) == with_default.rag.model_dump(exclude={"default_model"})
    assert [model.name for model in without.models] == [model.name for model in with_default.models] == ["A", "B"]


def test_the_rag_roles_do_move(pair):
    """The positive half — without it the negative half could pass on a no-op feature."""
    from deerflow_knowledge.model_target import resolve_rag_model_name

    without, with_default = pair

    assert resolve_rag_model_name(without) == "A"
    assert resolve_rag_model_name(with_default) == "B"


# ── host selection seams, one per call site ──────────────────────────────


def test_lead_agent_model_resolution_does_not_move(pair):
    """``lead_agent/agent.py:133`` ``_resolve_model_name`` — ordinary chat + the eval's
    answering agent (which runs as the ``rag`` agent and resolves here)."""
    from deerflow.agents.lead_agent.agent import _resolve_model_name

    without, with_default = pair

    assert _resolve_model_name(None, app_config=without) == "A"
    assert _resolve_model_name(None, app_config=with_default) == "A"


def test_the_factory_implicit_default_does_not_move(pair):
    """``models/factory.py:299`` ``name is None`` — what any unnamed build resolves to."""
    from deerflow.models.factory import create_chat_model

    without, with_default = pair

    assert create_chat_model(name=None, app_config=without).model_name == "A-wire"
    assert create_chat_model(name=None, app_config=with_default).model_name == "A-wire"


def test_the_tool_vision_gate_does_not_move(pair):
    """``tools/tools.py:114`` — the ``view_image`` tool follows the *chat* model's vision."""
    from deerflow.tools.tools import get_available_tools

    without, with_default = pair

    def _names(config: AppConfig) -> set[str]:
        return {tool.name for tool in get_available_tools(None, False, None, False, app_config=config)}

    assert "view_image" in _names(without)
    assert "view_image" in _names(with_default)


def test_the_subagent_vision_gate_does_not_move(pair):
    """``tool_error_handling_middleware.py:361`` — the **subagent** chain's capability read."""
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

    without, with_default = pair

    def _has_view_image(config: AppConfig) -> bool:
        return any(type(middleware).__name__ == "ViewImageMiddleware" for middleware in build_subagent_runtime_middlewares(app_config=config))

    assert _has_view_image(without)
    assert _has_view_image(with_default)


def test_the_summarization_default_does_not_move(pair):
    """``summarization_middleware.py:162`` ``_default_model_name`` — the summary model."""
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    without, with_default = pair

    def _default(config: AppConfig) -> str | None:
        return DeerFlowSummarizationMiddleware._default_model_name(SimpleNamespace(_app_config=config))

    assert _default(without) == "A"
    assert _default(with_default) == "A"


def test_the_compaction_default_does_not_move(pair):
    """``runtime/context_compaction.py:88`` — manual ``/compact`` and goal resolution."""
    from deerflow.runtime.context_compaction import _aresolve_thread_model_name

    without, with_default = pair

    assert asyncio.run(_aresolve_thread_model_name(None, None, None, without)) == "A"
    assert asyncio.run(_aresolve_thread_model_name(None, None, None, with_default)) == "A"


# ── source pins: the two seams behaviour cannot reach, plus the other legs ─


@pytest.mark.parametrize("relative", SOURCE_PINNED_SEAMS)
def test_unreachable_seams_never_read_the_rag_default(relative: str):
    source = (HARNESS / relative).read_text(encoding="utf-8")

    assert "models[0].name" in source
    assert not FIELD.search(source), f"{relative} must resolve its own default, not the RAG one"


@pytest.mark.parametrize("relative", NOT_ROLE_LEGS)
def test_other_functional_legs_never_read_the_rag_default(relative: str):
    """embedding / sparse / rerank / parse keep their own provider settings (D1)."""
    source = (KNOWLEDGE / relative).read_text(encoding="utf-8")

    assert not FIELD.search(source), f"{relative} must not follow the RAG role default"
