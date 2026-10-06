"""Tests for the pluggable embedding providers (spec 2026-09-14 §4.1 / §4.2).

Two things are load-bearing here and are what these tests pin:

1. **The cross-check.** ``sparse_source=provider`` is only valid for a provider that emits
   both halves. A generic OpenAI-compatible endpoint returns dense only, so pairing it with
   ``provider`` must be refused at build time — otherwise the deployment discovers at
   retrieval time that it silently lost a whole route.
2. **The dimension rule.** The width is a deployment setting (spec 2026-09-26 D1 乙): the
   declared one is authoritative, blank means the historical 1024. What stays fixed is that
   the *pipeline's* width and the *collections'* width must agree, so an undeclared provider
   is still measured once against the default and refused loudly if it disagrees — with the
   exit (the rebuild entry) named in the message. DashScope pins its dimension *in the
   request* (`parameters.dimension`), so it needs no probe; a generic endpoint cannot
   self-certify, so it is probed once — the probe also serves as a connectivity check.

The interface stays what it always was — ``embed(texts, text_type) -> list[EmbeddingResult]``
— so callers are unchanged (甲: a composition adapter, spec §4.2).
"""

from __future__ import annotations

import json

import httpx
import pytest

from deerflow.knowledge.embedder import DashScopeEmbedder, EmbedderAuthError, EmbedderError, RagConfigurationError, SparseHalfMissingError
from deerflow.knowledge.embedder_factory import build_embedder, effective_dimension
from deerflow.knowledge.embedder_openai import OpenAICompatibleEmbedder
from deerflow.knowledge.sparse import BM25SparseEncoder, TEISparseEncoder

OPENAI_BASE = "http://127.0.0.1:8080"
SPARSE_BASE = "http://127.0.0.1:8081"


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """Per-process memories must not leak between tests: the width probe, the learned batch cap,
    and "this endpoint refuses the dimensions parameter" (spec 2026-09-26 D3/D2 甲a)."""
    from deerflow.knowledge import embedder_factory as factory_mod
    from deerflow.knowledge import embedder_openai as openai_mod

    factory_mod._PROBED_DIMENSIONS.clear()
    openai_mod._BATCH_CAPS.clear()
    openai_mod._NO_DIMENSION_PARAM.clear()
    yield
    factory_mod._PROBED_DIMENSIONS.clear()
    openai_mod._BATCH_CAPS.clear()
    openai_mod._NO_DIMENSION_PARAM.clear()


def _stub_config(monkeypatch, **rag_updates):
    """Point ``build_embedder`` at a stubbed ``rag`` block."""
    from deerflow.knowledge import embedder_factory as factory_mod

    real = factory_mod.get_app_config()
    stub = real.model_copy(update={"rag": real.rag.model_copy(update=rag_updates)})
    monkeypatch.setattr(factory_mod, "get_app_config", lambda: stub)


def _openai_transport(recorded: list[httpx.Request], *, dims: int = 1024, order: list[int] | None = None, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        import json

        texts = json.loads(request.content.decode())["input"]
        indexes = order or list(range(len(texts)))
        return httpx.Response(
            200,
            json={"data": [{"index": indexes[i], "embedding": [float(indexes[i] + 1)] * dims} for i in range(len(texts))]},
        )

    return httpx.MockTransport(handler)


def _openai_embedder(client: httpx.AsyncClient, **kwargs) -> OpenAICompatibleEmbedder:
    kwargs.setdefault("model", "bge-m3")
    return OpenAICompatibleEmbedder(base_url=OPENAI_BASE, client=client, **kwargs)


def _dashscope_transport(recorded: list[httpx.Request], *, sparse: bool = True, dims: int = 1024) -> httpx.MockTransport:
    """Answer the DashScope embedding call locally.

    ``sparse=False`` reproduces the failure this task exists for: HTTP 200, dense filled,
    ``sparse_embedding`` absent — which the provider turns into an empty ``SparseVector``
    without complaining (``embedder.py`` ``or []``).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        import json

        texts = json.loads(request.content.decode())["input"]["texts"]
        items: list[dict[str, object]] = []
        for index in range(len(texts)):
            item: dict[str, object] = {"text_index": index, "embedding": [0.0] * dims}
            if sparse:
                item["sparse_embedding"] = [{"index": 7, "value": 0.5}]
            items.append(item)
        return httpx.Response(200, json={"output": {"embeddings": items}})

    return httpx.MockTransport(handler)


def _stub_dashscope_config(monkeypatch, **rag_updates):
    """DashScope with an explicit key, so the outcome never depends on the ambient env."""
    rag_updates.setdefault("embedding_provider", "dashscope")
    rag_updates.setdefault("embedding_model", "qwen3.7-text-embedding")
    rag_updates.setdefault("embedding_api_key", "sk-test")
    _stub_config(monkeypatch, **rag_updates)


# ── OpenAI-compatible dense provider ────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_embedder_pins_the_request_shape():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_openai_transport(recorded)) as client:
        results = await _openai_embedder(client, api_key="sk-test").embed(["甲", "乙"], text_type="document")

    request = recorded[0]
    assert str(request.url) == f"{OPENAI_BASE}/v1/embeddings"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert request.headers["content-type"].startswith("application/json")
    import json

    body = json.loads(request.content.decode())
    assert body == {"model": "bge-m3", "input": ["甲", "乙"]}, "通用形状只有 model + input"
    assert [len(r.dense) for r in results] == [1024, 1024]
    assert all(r.sparse.indices == [] for r in results), "通用 provider 只出 dense（稀疏由组合层补）"


@pytest.mark.asyncio
async def test_openai_embedder_orders_results_by_index():
    """响应可能乱序 —— 按 text_index 归位，别信数组顺序。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_openai_transport(recorded, order=[1, 0])) as client:
        results = await _openai_embedder(client).embed(["第一", "第二"])

    assert results[0].dense[0] == 1.0, "index=0 的那条要回到第一个位置"
    assert results[1].dense[0] == 2.0


@pytest.mark.asyncio
async def test_openai_embedder_splits_batches_and_reports_auth_failure():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_openai_transport(recorded)) as client:
        await _openai_embedder(client, batch_size=2).embed(["a", "b", "c"])
    assert len(recorded) == 2

    async with httpx.AsyncClient(transport=_openai_transport(recorded, status=401)) as client:
        with pytest.raises(EmbedderAuthError):
            await _openai_embedder(client, api_key="bad").embed(["a"])

    async with httpx.AsyncClient(transport=_openai_transport(recorded, status=500)) as client:
        with pytest.raises(EmbedderError):
            await _openai_embedder(client, max_retries=2, retry_backoff_seconds=0).embed(["a"])


@pytest.mark.asyncio
async def test_the_generic_embedder_starts_at_the_ladder_top():
    """起手就是阶梯顶端 20：能吃的端点请求数减半，吃不下的由 400 那一刀自己降档。

    历史（这台阶梯的由来，2026-09-25 真栈实测）：百炼兼容端点每次最多 10 行（20 行 ⇒ 400
    `batch size is invalid`）；当年把 20 写死时，297 行的整页重建被整批拒、零写入，运行状态
    照样报 succeeded。现在同一条路径会被 `_embed_with_healing` 降档重发（见下一个用例）。
    """
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_openai_transport(recorded)) as client:
        embedder = _openai_embedder(client)
        assert embedder.batch_size == 20
        results = await embedder.embed([f"切片{i}" for i in range(25)])

    rows_per_request = [len(json.loads(request.content.decode())["input"]) for request in recorded]
    assert rows_per_request == [20, 5]
    assert len(results) == 25, "拆批不影响结果条数与顺序"


# ── build_embedder: resolution, cross-check, dimension ──────────────────────


@pytest.mark.asyncio
async def test_build_embedder_defaults_to_dashscope_and_keeps_its_sparse(monkeypatch):
    """百炼 + 同出双路（地址必填后夹具自带端点；spec 2026-09-25 rag-endpoint-unlock）；且它自证维度、无需探测。"""
    from deerflow.knowledge import embedder_factory as factory_mod
    from deerflow.knowledge.providers import resolve_provider

    _stub_config(
        monkeypatch,
        embedding_provider="dashscope",
        embedding_base_url="https://dashscope.aliyuncs.com",
        embedding_sparse_source="provider",
    )

    embedder = build_embedder()

    # 仍是百炼实现、**没有套组合层（甲）**——外面只有那道「要求了稀疏就必须拿到」的运行期守卫。
    assert isinstance(embedder, factory_mod._SparseHalfCheckedEmbedder)
    assert isinstance(embedder._inner, DashScopeEmbedder)
    assert resolve_provider("embedding", "dashscope").pins_dimension is True


@pytest.mark.asyncio
async def test_build_embedder_refuses_dense_only_provider_with_provider_sparse(monkeypatch):
    """交叉校验：通用嵌入只出 dense ⇒ sparse_source 必须改成 external/bm25。"""
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="provider")

    with pytest.raises(RagConfigurationError, match="sparse"):
        build_embedder()


@pytest.mark.asyncio
async def test_build_embedder_refuses_a_non_dashscope_provider_without_an_address(monkeypatch):
    """只有自带地址的 provider（dashscope / volcengine-ark）能省掉 ``embedding_base_url``。"""
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=None, embedding_sparse_source="bm25")

    with pytest.raises(RagConfigurationError, match="embedding_base_url"):
        build_embedder()


@pytest.mark.asyncio
async def test_build_embedder_composes_external_sparse(monkeypatch):
    _stub_config(
        monkeypatch,
        embedding_provider="openai-compatible",
        embedding_base_url=OPENAI_BASE,
        embedding_dimension=1024,  # 声明维度 ⇒ dense 裸装，组合层结构一眼可见
        embedding_sparse_source="external",
        sparse_provider="tei-sparse",
        sparse_base_url=SPARSE_BASE,
    )

    embedder = build_embedder()

    assert isinstance(getattr(embedder, "_dense", None), OpenAICompatibleEmbedder)
    assert isinstance(getattr(embedder, "_sparse", None), TEISparseEncoder)


@pytest.mark.asyncio
async def test_build_embedder_composes_local_bm25(monkeypatch):
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_dimension=1024, embedding_sparse_source="bm25")

    embedder = build_embedder()

    assert isinstance(getattr(embedder, "_sparse", None), BM25SparseEncoder), "bm25 零模型、无需端点"


@pytest.mark.asyncio
async def test_external_sparse_requires_an_endpoint(monkeypatch):
    _stub_config(
        monkeypatch,
        embedding_provider="openai-compatible",
        embedding_base_url=OPENAI_BASE,
        embedding_sparse_source="external",
        sparse_provider="tei-sparse",
        sparse_base_url=None,
    )

    with pytest.raises(RagConfigurationError, match="sparse_base_url"):
        build_embedder()


def test_the_declared_dimension_is_the_live_width(monkeypatch):
    """声明就是这一部署的生效宽度（spec 2026-09-26 D1 乙）：1536 不再被拒。

    拒绝的权力交给保存期探针那一发实测（它比这里凭空多一次真调用更有资格），这里只负责
    让配置立起来 —— 曾经的守卫把「模型返回几维」和「库有多宽」绑死成 1024。
    """
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="bm25", embedding_dimension=1536)

    assert effective_dimension() == 1536
    assert build_embedder() is not None


def test_an_undeclared_width_is_still_the_historical_default(monkeypatch):
    """留空 = 1024：不改这一格的老部署，生效宽度与集合名都逐字节不变。"""
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="bm25", embedding_dimension=None)

    assert effective_dimension() == 1024


@pytest.mark.asyncio
async def test_declared_dimension_overrides_the_measured_length(monkeypatch):
    """显式声明是权威：某些自建服务的探测不稳（spec §4.2 维度 #1），声明了就不再测。"""
    from deerflow.knowledge import embedder_factory as factory_mod

    recorded: list[httpx.Request] = []
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="bm25", embedding_dimension=1024)

    async with httpx.AsyncClient(transport=_openai_transport(recorded, dims=768)) as client:
        await build_embedder(client=client).embed(["一"])

    assert factory_mod._PROBED_DIMENSIONS == {}, "声明之后不做探测，也就不留测量记录"
    assert len(recorded) == 1, "只有那次真实嵌入"


@pytest.mark.asyncio
async def test_probe_reads_the_real_length_and_refuses_another_width(monkeypatch):
    """未声明 ⇒ 用首次真实调用的返回长度认证；与生效宽度不符当场拒绝（不再多打一次探测请求）。"""
    recorded: list[httpx.Request] = []
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="bm25")

    async with httpx.AsyncClient(transport=_openai_transport(recorded, dims=768)) as client:
        embedder = build_embedder(client=client)
        with pytest.raises(ValueError, match="1024"):
            await embedder.embed(["探测"])

    assert len(recorded) == 1, "认证与首次嵌入同一次往返"


@pytest.mark.asyncio
async def test_probe_certifies_once_per_process(monkeypatch):
    from deerflow.knowledge import embedder_factory as factory_mod

    recorded: list[httpx.Request] = []
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_model="bge-m3", embedding_sparse_source="bm25")

    async with httpx.AsyncClient(transport=_openai_transport(recorded)) as client:
        await build_embedder(client=client).embed(["一次"])
        await build_embedder(client=client).embed(["两次"])

    assert factory_mod._PROBED_DIMENSIONS == {("openai-compatible", OPENAI_BASE, "bge-m3"): 1024}
    assert len(recorded) == 2, "两次真实嵌入，零次额外探测"


@pytest.mark.asyncio
async def test_non_pinning_provider_mismatch_is_not_an_embedder_error(monkeypatch):
    """维度不符必须抛 ValueError —— 抛 EmbedderError 会被 index_chunks 当软失败吞掉。"""
    recorded: list[httpx.Request] = []
    _stub_config(monkeypatch, embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="bm25")

    async with httpx.AsyncClient(transport=_openai_transport(recorded, dims=512)) as client:
        with pytest.raises(RagConfigurationError) as excinfo:
            await build_embedder(client=client).embed(["文本"])

    assert not isinstance(excinfo.value, EmbedderError)
    assert "重建" in str(excinfo.value), "错误里要指向重建入口这条出路"


# ── run-time fallback: a provider that promised sparse and did not deliver ──


@pytest.mark.asyncio
async def test_provider_sparse_that_comes_back_empty_is_refused(monkeypatch):
    """HTTP 200 但稀疏为空 ⇒ 拒绝启用的那一路，而不是静静建一个没有稀疏的索引。

    ``SparseHalfMissingError`` 而不是基类：探针正是靠这个类型把"模型答复了：不出稀疏"
    与"没能查成"分开，所以它是契约的一部分，不该只靠消息文本钉住。
    """
    recorded: list[httpx.Request] = []
    _stub_dashscope_config(monkeypatch, embedding_sparse_source="provider")

    async with httpx.AsyncClient(transport=_dashscope_transport(recorded, sparse=False)) as client:
        with pytest.raises(SparseHalfMissingError, match="bm25"):
            await build_embedder(client=client).embed(["一段文本"])

    assert len(recorded) == 1, "判定发生在一次真实嵌入之后，不是构造期"


@pytest.mark.asyncio
async def test_the_refusal_repeats_on_every_call(monkeypatch):
    """每次嵌入都判 —— 不缓存「已判过」（空稀疏是合法值，放过一次就真写进库了）。"""
    recorded: list[httpx.Request] = []
    _stub_dashscope_config(monkeypatch, embedding_sparse_source="provider")

    async with httpx.AsyncClient(transport=_dashscope_transport(recorded, sparse=False)) as client:
        embedder = build_embedder(client=client)
        for _ in range(2):
            with pytest.raises(RagConfigurationError):
                await embedder.embed(["一段文本"])

    assert len(recorded) == 2, "两次调用两次判定，没有「喊一声就永久静默」"


@pytest.mark.asyncio
async def test_a_configured_sparse_source_is_not_judged(monkeypatch):
    """其它来源下稠密侧那份稀疏本来就被 ComposedEmbedder 丢弃 ⇒ 不该在这里拦。"""
    recorded: list[httpx.Request] = []
    _stub_dashscope_config(monkeypatch, embedding_sparse_source="bm25")

    async with httpx.AsyncClient(transport=_dashscope_transport(recorded, sparse=False)) as client:
        results = await build_embedder(client=client).embed(["一段文本"])

    assert results[0].sparse.indices, "稀疏来自 BM25，空的那份是稠密 provider 的，被组合层丢掉"


# ── per-model row cap: the platform's limit is not one number ────────────────


def test_the_row_cap_is_conservative_for_models_nobody_measured():
    """默认取**已知最低**上限：未知模型最坏是多一次往返，而不是被平台整批拒掉。

    2026-09-17 实测：`text-embedding-v3` / `v4` 一次最多 10 行（20 行 ⇒ 400
    `batch size is invalid`），`qwen3.7-text-embedding` 能吃 20。
    """
    from deerflow.knowledge.embedder import DASHSCOPE_SAFE_BATCH_SIZE, dashscope_batch_size

    assert DASHSCOPE_SAFE_BATCH_SIZE == 10
    assert dashscope_batch_size("text-embedding-v3") == 10
    assert dashscope_batch_size("text-embedding-v4") == 10
    assert dashscope_batch_size("qwen3.7-text-embedding") == 20
    # A model the table has never heard of keeps the safe value — the table only ever *raises* it.
    assert dashscope_batch_size("some-model-from-next-year") == 10
    assert dashscope_batch_size(None) == 10


@pytest.mark.asyncio
async def test_the_embedder_sends_batches_the_model_can_take(monkeypatch):
    """25 片在 v3 上必须拆成 10 / 10 / 5 三次请求，而不是两次 20 / 5（后者第一批就被拒）。"""
    recorded: list[httpx.Request] = []
    _stub_dashscope_config(monkeypatch, embedding_model="text-embedding-v3")

    async with httpx.AsyncClient(transport=_dashscope_transport(recorded)) as client:
        embedder = build_embedder(client=client)
        assert embedder.batch_size == 10
        results = await embedder.embed([f"切片{i}" for i in range(25)])

    rows_per_request = [len(json.loads(request.content.decode())["input"]["texts"]) for request in recorded]
    assert rows_per_request == [10, 10, 5]
    assert len(results) == 25, "拆批不影响结果条数与顺序"


@pytest.mark.asyncio
async def test_build_embedder_refuses_an_empty_endpoint_even_for_dashscope(monkeypatch):
    """Spec 2026-09-25 rag-endpoint-unlock D1 乙: the vendor's built-in fallback is gone —
    an empty ``rag.embedding_base_url`` is a construction error whatever the provider."""
    from deerflow.knowledge.embedder import RagConfigurationError

    _stub_config(monkeypatch, embedding_provider="dashscope", embedding_base_url=None)

    with pytest.raises(RagConfigurationError, match="embedding_base_url"):
        build_embedder()


@pytest.mark.asyncio
async def test_openai_embedder_accepts_an_ecosystem_base_with_v1():
    """照文档填（把 /v1 算进 base）也打得出门（spec 2026-09-26 rag-endpoint-dedup）。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_openai_transport(recorded)) as client:
        embedder = OpenAICompatibleEmbedder(
            base_url=f"{OPENAI_BASE}/v1",
            model="bge-m3",
            api_key="sk-test",
            client=client,
        )
        await embedder.embed(["甲"], text_type="document")

    assert str(recorded[0].url) == f"{OPENAI_BASE}/v1/embeddings"


# ── 声明发参 + 批量阶梯 (spec 2026-09-26 D2 甲a / D3 甲′) ───────────────────────


def _healing_transport(
    recorded: list[httpx.Request],
    *,
    max_rows: int | None = None,
    reject_dimensions: bool = False,
) -> httpx.MockTransport:
    """An endpoint that refuses big batches and/or the ``dimensions`` parameter, like the real ones.

    ``max_rows`` reproduces the compatible-mode refusal (`batch size is invalid`);
    ``reject_dimensions`` reproduces a strict server that 400s on an unknown parameter.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content.decode())
        if reject_dimensions and "dimensions" in body:
            return httpx.Response(400, json={"error": {"message": "unknown parameter: dimensions"}})
        if max_rows is not None and len(body.get("input") or []) > max_rows:
            return httpx.Response(400, json={"error": {"message": "batch size is invalid"}})
        texts = body["input"]
        return httpx.Response(
            200,
            json={"data": [{"index": index, "embedding": [1.0, 2.0]} for index in range(len(texts))]},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_the_declared_dimension_is_sent_and_undeclared_stays_byte_identical():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_openai_transport(recorded)) as client:
        # 未声明 ⇒ 与今天逐字节相同：请求体只有 model 与 input。
        await _openai_embedder(client).embed(["a"])
        assert set(json.loads(recorded[-1].content).keys()) == {"model", "input"}

        # 声明 ⇒ 每一发都带上它（D2 甲a）；拆批只改行数，不改这个键。
        await _openai_embedder(client, dimension=1024, batch_size=2).embed(["a", "b", "c"])

    assert [json.loads(request.content).get("dimensions") for request in recorded[-2:]] == [1024, 1024]


@pytest.mark.asyncio
async def test_a_batch_size_400_walks_the_ladder_down_and_remembers_where_it_landed():
    """端点最多 5 行：首批 20 被拒（白付一发）⇒ 20→10→5 降档，30 片照常入库；同端点下次直接 5。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_healing_transport(recorded, max_rows=5)) as client:
        embedder = _openai_embedder(client)
        assert embedder.batch_size == 20
        results = await embedder.embed([f"切片{i}" for i in range(30)])

    rows_per_request = [len(json.loads(request.content)["input"]) for request in recorded]
    assert rows_per_request == [20, 10, 5, 5, 5, 5, 5, 5]
    assert embedder.batch_size == 5, "学到的档要留给后续的批"
    assert len(results) == 30

    # 工厂每次都重建实例 ⇒ 记忆必须是端点级的（(base_url, model)）。
    recorded_again: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_healing_transport(recorded_again, max_rows=5)) as client2:
        again = _openai_embedder(client2)
        assert again.batch_size == 5
        await again.embed([f"切片{i}" for i in range(6)])

    assert [len(json.loads(request.content)["input"]) for request in recorded_again] == [5, 1]


@pytest.mark.asyncio
async def test_a_twenty_row_cap_is_used_without_a_single_rejected_request():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_healing_transport(recorded, max_rows=20)) as client:
        embedder = _openai_embedder(client)
        results = await embedder.embed([f"切片{i}" for i in range(25)])

    assert [len(json.loads(request.content)["input"]) for request in recorded] == [20, 5]
    assert embedder.batch_size == 20
    assert len(results) == 25


@pytest.mark.asyncio
async def test_a_rejected_dimension_parameter_is_dropped_once_and_remembered():
    """单行批 + 正带着 dimensions 撞 400 ⇒ 去参重试一次（不是无限降档），并记住该端点。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_healing_transport(recorded, reject_dimensions=True)) as client:
        results = await _openai_embedder(client, dimension=1024).embed(["a"])

    bodies = [json.loads(request.content) for request in recorded]
    assert "dimensions" in bodies[0]
    assert "dimensions" not in bodies[1]
    assert len(results) == 1

    recorded_again: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_healing_transport(recorded_again, reject_dimensions=True)) as client2:
        await _openai_embedder(client2, dimension=1024).embed(["a"])
    assert "dimensions" not in json.loads(recorded_again[0].content), "记住之后不再白付那一发"


# ── A-1: the model name has no default any more (spec 2026-09-30 D1) ─────────


def test_the_factory_refuses_a_missing_embedding_model():
    """An undeclared model is a configuration error at the construction point — never a silent
    vendor pick. The address and the sparse source are set on purpose, so the refusal under test
    is the model one (not the address or the dense-only cross-check)."""
    from deerflow.config.app_config import RagConfig

    rag = RagConfig(embedding_provider="openai-compatible", embedding_base_url=OPENAI_BASE, embedding_sparse_source="bm25").model_copy(update={"embedding_model": None})
    assert rag.embedding_model is None

    with pytest.raises(RagConfigurationError, match="embedding_model") as caught:
        build_embedder(rag=rag)

    assert isinstance(caught.value, ValueError)


# ── D2 嵌入身份（spec 2026-10-04 §2.2：指纹=provider/model/base_url，不含 api_key）──


def test_the_identity_covers_exactly_the_space_fields(monkeypatch):
    """换钥不换身份（防误触发重建/失配告警），换模型才换；宽度另有独立轴。"""
    _stub_dashscope_config(monkeypatch, embedding_base_url="https://dashscope.aliyuncs.com", embedding_api_key="sk-first")
    first = build_embedder().identity

    _stub_dashscope_config(monkeypatch, embedding_base_url="https://dashscope.aliyuncs.com", embedding_api_key="sk-rotated")
    assert build_embedder().identity == first, "轮换密钥不改身份"

    _stub_dashscope_config(monkeypatch, embedding_base_url="https://dashscope.aliyuncs.com", embedding_api_key="sk-rotated", embedding_model="another-embedding")
    assert build_embedder().identity != first, "换模型才改身份"
