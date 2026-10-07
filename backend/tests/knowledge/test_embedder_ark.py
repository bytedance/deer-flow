"""Tests for the Volcengine Ark embedding provider (spec 2026-09-17).

Ark's ``doubao-embedding-vision`` is the **second** provider that returns dense *and* sparse
in one call — that is the whole reason the row exists — so what these tests pin is the shape
that makes it usable at all:

1. **One content item per call.** That endpoint takes *one item's* content parts, not a list
   of texts; ``batch_size`` says so, and three texts therefore mean three requests.
2. **The width is always declared.** The model is born at 2048 while the collections are
   fixed at 1024, so ``dimensions`` must go out on every request. The factory injects it and
   the adapter never decides for itself: the dimension guard only fires on a *real* call, so
   a silent default would surface as "saved fine, exploded on the first ingest".
3. **``text_type`` is accepted but not transmitted** — the shape has no query/document knob,
   and both sides must share one sparse index space anyway.
4. **The fixed-endpoint rule.** ``has_fixed_endpoint`` is what locks the address field in the
   UI; a stored ``embedding_base_url`` is still honoured (that is what keeps DashScope's
   workspace-scoped URL usable), and the allowlist's ``default_endpoint`` only supplies the
   fallback.
"""

from __future__ import annotations

import json

import httpx
import pytest
from deerflow_knowledge.embedder import EmbedderAuthError, EmbedderError, RagConfigurationError, SparseHalfMissingError
from deerflow_knowledge.embedder_ark import ARK_BASE_URL, ArkEmbedder
from deerflow_knowledge.embedder_factory import build_embedder
from deerflow_knowledge.providers import PROVIDER_ALLOWLIST, resolve_provider, secret_env_var

ARK_PATH = "/api/v3/embeddings/multimodal"
CUSTOM_BASE = "http://custom.example:9999"


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """The dimension probe is cached per process; tests must not see each other's entries."""
    from deerflow_knowledge import embedder_factory as factory_mod

    factory_mod._PROBED_DIMENSIONS.clear()
    yield
    factory_mod._PROBED_DIMENSIONS.clear()


def _stub_config(monkeypatch, **rag_updates):
    """Point ``build_embedder`` at a stubbed ``rag`` block."""
    from deerflow_knowledge import embedder_factory as factory_mod

    real = factory_mod.get_app_config()
    stub = real.model_copy(update={"rag": real.rag.model_copy(update=rag_updates)})
    monkeypatch.setattr(factory_mod, "get_app_config", lambda: stub)


def _ark_transport(
    recorded: list[httpx.Request],
    *,
    dims: int = 1024,
    sparse: bool = True,
    status: int = 200,
    payload: dict | None = None,
) -> httpx.MockTransport:
    """Answer one Ark multimodal embedding call locally.

    ``sparse=False`` answers exactly like the real endpoint does for a model that cannot
    supply the sparse half: HTTP 200, dense filled, ``sparse_embedding`` an empty list.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        if payload is not None:
            return httpx.Response(200, json=payload)
        data: dict = {"embedding": [0.5] * dims, "object": "embedding"}
        if sparse:
            data["sparse_embedding"] = [{"index": 7, "value": 0.25}, {"index": 99, "value": 0.75}]
        return httpx.Response(200, json={"id": "x", "model": "doubao-embedding-vision-250615", "data": data})

    return httpx.MockTransport(handler)


def _ark_embedder(client: httpx.AsyncClient, **kwargs) -> ArkEmbedder:
    kwargs.setdefault("model", "doubao-embedding-vision-250615")
    # The width is never defaulted in the adapter (spec §3 D3) — direct construction states it.
    kwargs.setdefault("dimension", 1024)
    return ArkEmbedder(base_url=ARK_BASE_URL, client=client, **kwargs)


def _dashscope_transport(recorded: list[httpx.Request], *, dims: int = 1024) -> httpx.MockTransport:
    """The DashScope shape, needed only by the parametrised fixed-endpoint test below."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        texts = json.loads(request.content.decode())["input"]["texts"]
        return httpx.Response(
            200,
            json={"output": {"embeddings": [{"text_index": index, "embedding": [0.5] * dims, "sparse_embedding": [{"index": 1, "token": "t", "value": 0.5}]} for index in range(len(texts))]}},
        )

    return httpx.MockTransport(handler)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


# ── the request shape ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_request_carries_one_content_item_and_the_switches():
    """形状守卫：一条内容条目 + 两个开关都在，别多也别少。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ark_transport(recorded)) as client:
        await _ark_embedder(client).embed(["苹果手机"])

    assert len(recorded) == 1
    assert recorded[0].url.path == ARK_PATH
    assert set(_body(recorded[0])) == {"model", "input", "dimensions", "sparse_embedding"}
    assert _body(recorded[0])["input"] == [{"type": "text", "text": "苹果手机"}], "一条内容条目，不是一份文本列表"
    assert _body(recorded[0])["dimensions"] == 1024
    assert _body(recorded[0])["sparse_embedding"] == {"type": "enabled"}, "稀疏要显式开，默认不给"


@pytest.mark.asyncio
async def test_three_texts_mean_three_requests_and_batch_size_says_one():
    """一次一条：端点只吃「一条的多个模态部分」，所以文本数 = 请求数。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ark_transport(recorded)) as client:
        embedder = _ark_embedder(client)
        assert embedder.batch_size == 1, "`index_chunks` 按它切片——报 1 才是一批一片"
        results = await embedder.embed(["甲", "乙", "丙"])

    assert len(recorded) == 3, "三条文本必须三次请求（不是一次塞三条）"
    assert len(results) == 3
    assert [_body(r)["input"][0]["text"] for r in recorded] == ["甲", "乙", "丙"], "顺序要照输入"


@pytest.mark.asyncio
async def test_the_single_data_object_carries_both_halves():
    """响应是**单个对象**（不是数组）：稠密读 data.embedding，稀疏读 data.sparse_embedding[]。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ark_transport(recorded)) as client:
        results = await _ark_embedder(client).embed(["苹果手机"])

    assert len(results[0].dense) == 1024
    assert results[0].sparse.indices == [7, 99]
    assert results[0].sparse.values == [0.25, 0.75]


@pytest.mark.asyncio
async def test_text_type_is_accepted_but_not_transmitted():
    """收下 ``text_type`` 但不发——这个形状没有 query/document 位；签名不符会直接 TypeError。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ark_transport(recorded)) as client:
        embedder = _ark_embedder(client)
        await embedder.embed(["苹果"], text_type="query")
        await embedder.embed(["苹果"], text_type="document")

    assert _body(recorded[0]) == _body(recorded[1]), "两侧请求体必须逐字节相同"


# ── failures ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_rejected_key_is_not_retried_and_a_server_error_is():
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ark_transport(recorded, status=401)) as client:
        with pytest.raises(EmbedderAuthError):
            await _ark_embedder(client, api_key="bad").embed(["a"])
    assert len(recorded) == 1, "鉴权失败不重试"

    async with httpx.AsyncClient(transport=_ark_transport(recorded, status=500)) as client:
        with pytest.raises(EmbedderError):
            await _ark_embedder(client, max_retries=2, retry_backoff_seconds=0).embed(["a"])


@pytest.mark.asyncio
async def test_a_response_without_the_data_object_is_reported():
    """形状不符要报错，不能静默当成空结果。"""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ark_transport(recorded, payload={"id": "x"})) as client:
        with pytest.raises(EmbedderError, match="data"):
            await _ark_embedder(client).embed(["a"])


# ── the runtime shell around it ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_empty_sparse_half_is_refused_by_the_shell_that_wraps_it(monkeypatch):
    """适配器自己不判空稀疏——外层 ``_SparseHalfCheckedEmbedder`` 兜，且它**每次都判**。"""
    recorded: list[httpx.Request] = []
    _stub_config(
        monkeypatch,
        embedding_provider="volcengine-ark",
        embedding_base_url=ARK_BASE_URL,
        embedding_model="doubao-embedding-vision-250615",
        embedding_sparse_source="provider",
    )

    async with httpx.AsyncClient(transport=_ark_transport(recorded, sparse=False)) as client:
        embedder = build_embedder(client=client)
        with pytest.raises(SparseHalfMissingError):
            await embedder.embed(["a"])


# ── the allowlist row and the factory ────────────────────────────────────────


def test_the_allowlist_row_declares_the_capabilities():
    spec = resolve_provider("embedding", "volcengine-ark")

    assert spec.emits_sparse is True, "这一行就是「第二家双路」的全部声明"
    assert spec.pins_dimension is True, "适配器无条件发 dimensions ⇒ 不需要运行时探测"
    assert spec.has_fixed_endpoint is True
    assert spec.default_endpoint == ARK_BASE_URL
    assert spec.path == ARK_PATH
    assert secret_env_var("embedding", "volcengine-ark") == "ARK_API_KEY"

    generic = resolve_provider("embedding", "openai-compatible")
    assert generic.has_fixed_endpoint is False, "默认关，别把别家带偏"
    assert generic.default_endpoint is None


def test_the_two_new_fields_never_disagree():
    """⑥甲：两个键表达同一条规则 ⇒ 不允许出现「有固定地址却没有默认」的行。"""
    for leg, rows in PROVIDER_ALLOWLIST.items():
        for provider_id, spec in rows.items():
            assert spec.has_fixed_endpoint == (spec.default_endpoint is not None), f"{leg}/{provider_id}"


def test_the_dashscope_default_endpoint_has_not_drifted():
    """值在两处各有一份（本模块要 import-light，不能 import 实现模块）⇒ 用这条钉住。"""
    from deerflow_knowledge.embedder import DASHSCOPE_BASE_URL

    assert resolve_provider("embedding", "dashscope").default_endpoint == DASHSCOPE_BASE_URL


@pytest.mark.asyncio
async def test_build_embedder_builds_the_ark_provider_and_injects_the_width(monkeypatch):
    """宽度由工厂注入：即使没声明 ``embedding_dimension``，请求里也必须带 1024。"""
    recorded: list[httpx.Request] = []
    _stub_config(
        monkeypatch,
        embedding_provider="volcengine-ark",
        embedding_base_url=ARK_BASE_URL,
        embedding_model="doubao-embedding-vision-250615",
        embedding_dimension=None,
        embedding_sparse_source="provider",
    )

    async with httpx.AsyncClient(transport=_ark_transport(recorded)) as client:
        embedder = build_embedder(client=client)
        await embedder.embed(["a"])

    assert _body(recorded[0])["dimensions"] == 1024
    assert recorded[0].url.host == "ark.cn-beijing.volces.com", "没给地址就用允许名单的默认"


@pytest.mark.asyncio
async def test_the_default_provider_is_still_dashscope(monkeypatch):
    from deerflow.config.app_config import RagConfig

    _stub_config(monkeypatch)
    assert RagConfig().embedding_provider == "dashscope"
    assert RagConfig().embedding_model is None  # no literal default since 2026-09-30 (A-1)


# ── the fixed-endpoint rule keeps stored addresses in play (⑤-4) ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["dashscope", "volcengine-ark"])
async def test_a_stored_address_still_beats_the_built_in_default(monkeypatch, provider):
    """回归保护：**存量地址仍然生效**——百炼的 workspace 级地址就靠这一条活着。"""
    recorded: list[httpx.Request] = []
    _stub_config(
        monkeypatch,
        embedding_provider=provider,
        embedding_base_url=CUSTOM_BASE,
        embedding_model="doubao-embedding-vision-250615",
        embedding_dimension=1024,  # 声明维度 ⇒ 不挂探测，省掉一次额外调用
        embedding_sparse_source="bm25",
    )
    transport = _ark_transport(recorded) if provider == "volcengine-ark" else _dashscope_transport(recorded)

    async with httpx.AsyncClient(transport=transport) as client:
        await build_embedder(client=client).embed(["a"])

    assert recorded[0].url.host == "custom.example", "自定义地址被忽略 = workspace 级地址被砍"


@pytest.mark.asyncio
async def test_a_generic_provider_without_an_address_is_still_refused(monkeypatch):
    """对照组：没有固定地址的那一家，缺地址仍要拒（改文案不能把这条也放过）。"""
    _stub_config(
        monkeypatch,
        embedding_provider="openai-compatible",
        embedding_base_url=None,
        embedding_sparse_source="bm25",
    )

    with pytest.raises(RagConfigurationError, match="embedding_base_url"):
        build_embedder()
