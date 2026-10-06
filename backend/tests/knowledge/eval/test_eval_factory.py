"""Factory tests for the shared judge/ragas builders (spec 2026-09-01 B 方案 Task 1).

``deerflow.knowledge.eval.factory`` 是 ``scripts/run_ragas_eval.py`` 与
gateway 按需完整评测共用的构建层：judge LLM（config 模型条目，按 RAG 自己的
顺序（D3）解析）与 ragas 评估器（未安装 → None 显式跳过）。契约与 CLI 原实现逐条
对齐（见 test_ragas_eval_cli.py），此处钉工厂模块自身的公共口径。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deerflow.config.app_config import AppConfig, RagConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.knowledge.eval import factory

SANDBOX = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")


def _config(*names: str, default_model: str | None = None, judge_model: str | None = None) -> AppConfig:
    """A real config: the judge's not-found case needs the real factory to raise."""
    return AppConfig(
        models=[ModelConfig(name=name, display_name=name, description=None, use="langchain_openai:ChatOpenAI", model=f"{name}-wire", api_key="test-key", supports_thinking=False) for name in names],
        sandbox=SANDBOX,
        rag=RagConfig(default_model=default_model, judge_model=judge_model),
    )


class TestBuildJudgeLlm:
    def test_config_model_name_delegates_to_factory(self, monkeypatch):
        import deerflow.models.factory as models_factory

        seen = {}

        def _create(name=None, **kwargs):
            seen["name"] = name
            return object()

        monkeypatch.setattr(models_factory, "create_chat_model", _create)

        factory.build_judge_llm("qwen3.7-flash", config=_config("qwen3.7-flash"))
        assert seen["name"] == "qwen3.7-flash"

    def test_a_missing_name_raises_the_factorys_plain_not_found(self):
        """The library contract of D9: a wrong name is a plain ``ValueError`` with the
        factory's own sentence — nothing catches or rewords it here."""
        with pytest.raises(ValueError) as excinfo:
            factory.build_judge_llm("dashscope:qwen3.8-max", config=_config("A"))

        assert type(excinfo.value) is ValueError
        assert str(excinfo.value) == "Model dashscope:qwen3.8-max not found in config"

    def test_a_complete_entry_named_like_the_prefix_is_built_by_name(self, monkeypatch):
        """The prefix is not special any more (D9): a configured entry that *happens* to be
        named that way is resolved like any other name, through the factory."""
        import deerflow.models.factory as models_factory

        seen: list[str | None] = []
        sentinel = object()
        monkeypatch.setattr(models_factory, "create_chat_model", lambda name=None, **kwargs: seen.append(name) or sentinel)

        built = factory.build_judge_llm("dashscope:qwen3.8-max", config=_config("dashscope:qwen3.8-max"))

        assert built is sentinel
        assert seen == ["dashscope:qwen3.8-max"]

    def test_empty_parameter_prefers_the_role_declaration_over_the_default(self, monkeypatch):
        """D3's order, at this seam: the role field, then the RAG default, then the first."""
        import deerflow.models.factory as models_factory

        seen: list[str | None] = []
        monkeypatch.setattr(models_factory, "create_chat_model", lambda name=None, **kwargs: seen.append(name) or object())

        factory.build_judge_llm(None, config=_config("A", "B", "J", default_model="B", judge_model="J"))

        assert seen == ["J"]

    def test_the_direct_branch_is_gone_from_the_module(self):
        """Source pin (D9): the retired branch left no constant, no exception class and no
        prefix special-casing behind."""
        source = (Path(factory.__file__)).read_text(encoding="utf-8")

        assert "DASHSCOPE_COMPATIBLE_BASE_URL" not in source
        assert "JudgeKeyMissingError" not in source
        assert "dashscope:" not in source

    def test_default_none_falls_back_to_the_rag_default(self, monkeypatch):
        """``None`` no longer means "let the factory pick the first model".

        The delegate is pinned here rather than the fallback: D3 resolves the name before
        the factory sees it, so what reaches the factory is a concrete entry name.
        """
        from types import SimpleNamespace

        import deerflow.models.factory as models_factory

        seen = {}
        monkeypatch.setattr(models_factory, "create_chat_model", lambda name=None, **kwargs: seen.setdefault("name", name) or object())
        config = SimpleNamespace(
            models=[SimpleNamespace(name="A"), SimpleNamespace(name="B")],
            rag=SimpleNamespace(judge_model=None, default_model="B", judge_thinking=False),
        )

        factory.build_judge_llm(None, config=config)

        assert seen["name"] == "B"


class TestBuildRagasEvaluator:
    def test_returns_none_when_ragas_not_installed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "ragas", None)
        monkeypatch.setitem(sys.modules, "ragas.llms", None)
        monkeypatch.setitem(sys.modules, "ragas.embeddings", None)

        assert factory.build_ragas_evaluator(judge_llm=object()) is None

    def test_wraps_judge_with_bypass_n(self, monkeypatch):
        """DashScope judges reject ``n>1``，wrapper 必须开 ``bypass_n``（CLI 同款契约）。"""

        captured: dict = {}

        class FakeWrapper:
            def __init__(self, llm, **kwargs):
                captured["bypass_n"] = kwargs.get("bypass_n")

        class FakeEmbeddingsWrapper:
            def __init__(self, embeddings):
                pass

        fake_ragas_llms = type(sys)("ragas.llms")
        fake_ragas_llms.LangchainLLMWrapper = FakeWrapper
        fake_ragas_embed = type(sys)("ragas.embeddings")
        fake_ragas_embed.LangchainEmbeddingsWrapper = FakeEmbeddingsWrapper
        monkeypatch.setitem(sys.modules, "ragas.llms", fake_ragas_llms)
        monkeypatch.setitem(sys.modules, "ragas.embeddings", fake_ragas_embed)
        monkeypatch.setattr(factory, "DashScopeLangChainEmbeddings", lambda *a, **kw: object())

        evaluator = factory.build_ragas_evaluator(judge_llm=object())
        assert evaluator is not None
        assert captured["bypass_n"] is True

    @pytest.mark.asyncio
    async def test_evaluator_forwards_on_progress(self, monkeypatch):
        """spec 2026-09-06 §9：evaluator 协议新增 ``on_progress``，必须透传给 compute_ragas_scores。"""

        import deerflow.knowledge.eval.ragas_eval as ragas_module

        captured: dict = {}

        class FakeWrapper:
            def __init__(self, llm, **kwargs):
                pass

        fake_ragas_llms = type(sys)("ragas.llms")
        fake_ragas_llms.LangchainLLMWrapper = FakeWrapper
        fake_ragas_embed = type(sys)("ragas.embeddings")
        fake_ragas_embed.LangchainEmbeddingsWrapper = FakeWrapper
        monkeypatch.setitem(sys.modules, "ragas.llms", fake_ragas_llms)
        monkeypatch.setitem(sys.modules, "ragas.embeddings", fake_ragas_embed)
        monkeypatch.setattr(factory, "DashScopeLangChainEmbeddings", lambda *a, **kw: object())

        async def fake_compute(samples, *, judge_llm, embeddings, on_progress=None):
            captured["on_progress"] = on_progress
            return []

        monkeypatch.setattr(ragas_module, "compute_ragas_scores", fake_compute)

        def callback(done: int, total: int) -> None:
            return None

        evaluator = factory.build_ragas_evaluator(judge_llm=object())
        assert evaluator is not None

        await evaluator([{"question_id": "q1"}], judge_llm=None, embeddings=None, on_progress=callback)

        assert captured["on_progress"] is callback
