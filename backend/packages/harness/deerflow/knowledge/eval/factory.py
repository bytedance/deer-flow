"""Shared Layer 2 builder factory (CLI ``run_ragas_eval.py`` 与 gateway 按需完整评测共用).

Judge LLM 与 ragas 评估器的构建从 CLI 脚本提升到本模块：

- **judge 独立性**：judge 与答题 Agent 的模型刻意可分离（自评偏差是真实
  失败模式）——独立性由“换个条目名”实现，判分模型与答题模型都来自 ``models:``；
  judge 按 RAG 自己的顺序（D3）取 ``rag.judge_model`` → RAG 默认 → 首项，
  显式名字永不替换（错名一路抛到工厂）。
- **ragas 可选**：未安装时评估器返回 ``None``，``run_layer2_evaluation``
  把标准指标标记为显式跳过（绝不伪绿）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence


class DashScopeLangChainEmbeddings:
    """Minimal langchain ``Embeddings`` protocol over the DashScope embedder.

    ragas calls BOTH the async methods (from its own event loop) and the sync
    ones (via executor threads), so the sync methods must really work: they
    run the coroutine on a fresh thread with its own event loop when already
    inside a loop (``asyncio.run`` would explode in-place).
    """

    def __init__(self, embedder) -> None:
        self._embedder = embedder

    async def aembed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        results = await self._embedder.embed(list(texts), text_type="document")
        return [r.dense for r in results]

    async def aembed_query(self, text: str) -> list[float]:
        results = await self._embedder.embed([text], text_type="query")
        return results[0].dense

    @staticmethod
    def _run_blocking(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # Already inside a loop (ragas worker): run on a fresh thread with its own loop.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    def embed_documents(self, texts) -> list[list[float]]:
        results = self._run_blocking(self._embedder.embed(list(texts), text_type="document"))
        return [r.dense for r in results]

    def embed_query(self, text) -> list[float]:
        return self._run_blocking(self._embedder.embed([text], text_type="query"))[0].dense


def build_judge_llm(judge_model: str | None, *, config):
    """Build the judge LLM, independently from the answering agent's model.

    Anything the caller passes resolves through the config model entries, in RAG's own order
    (D3): the explicit name, then ``rag.judge_model``, then the RAG default, then the first
    configured model. An explicit name is never replaced — a wrong one reaches the factory
    and fails loudly rather than quietly grading with a model nobody asked for.
    """

    from deerflow.knowledge.model_target import create_rag_chat_model, require_usable_rag_target

    target = require_usable_rag_target(config, judge_model or config.rag.judge_model, role="评测裁判")
    return create_rag_chat_model(target, thinking=bool(config.rag.judge_thinking), app_config=config, attach_tracing=False)


def build_ragas_evaluator(judge_llm, *, embeddings_cls=None):
    """ragas-wrapped evaluator, or ``None`` when ragas is not installed.

    The returned callable matches the ``ragas_evaluator`` protocol of
    ``run_layer2_evaluation``; ``None`` makes the report mark the standard
    metrics as explicitly skipped. ``embeddings_cls`` 是可注入口（默认
    :class:`DashScopeLangChainEmbeddings`）——CLI 壳层传入自己的模块全局名，
    让既有测试的 monkeypatch 保持生效。``on_progress``（spec 2026-09-06 §9）
    透传给 ``compute_ragas_scores``，把 ragas 逐 job 进度变成可上报的回调。
    """

    try:
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
    except ImportError:
        return None

    from deerflow.knowledge.embedder_factory import build_embedder
    from deerflow.knowledge.eval.ragas_eval import compute_ragas_scores

    # bypass_n: answer_relevancy's strictness=3 asks the judge for n=3
    # completions in one request; DashScope (and other OpenAI-compatible
    # endpoints) reject n>1 with a 400. With bypass_n ragas falls back to n
    # separate single-completion calls, which every endpoint supports.
    wrapped_llm = LangchainLLMWrapper(judge_llm, bypass_n=True)
    effective_cls = embeddings_cls or DashScopeLangChainEmbeddings
    wrapped_embeddings = LangchainEmbeddingsWrapper(effective_cls(build_embedder()))

    async def evaluator(samples, *, judge_llm, embeddings, on_progress=None):  # protocol-aligned; wrappers are bound at build time
        return await compute_ragas_scores(samples, judge_llm=wrapped_llm, embeddings=wrapped_embeddings, on_progress=on_progress)

    return evaluator
