"""Tests for the MinerU parse client and the VLM captioner.

HTTP layer is mocked with ``httpx.MockTransport``; the MinerU token must come
from the ``MINERU_API_TOKEN`` env var (never from the caller), and the caption
target is a real ``models:`` entry — the key comes from the entry (spec
2026-09-23 D10.3: the env fallback and the bare-id path are gone).
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
import zipfile

import httpx
import pytest
from deerflow_knowledge.captioner import apply_captions, caption_images
from deerflow_knowledge.parser import (
    MineruAuthError,
    MineruError,
    MineruParseFailedError,
    MineruTimeoutError,
    ParsedImage,
    parse_document,
)


def _make_result_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "# 解析结果\n\n正文第一段。\n\n![](images/p1.jpg)\n\n正文第二段。")
        zf.writestr("images/p1.jpg", b"\xff\xd8\xff\xe0jpeg-bytes")
        zf.writestr("content_list.json", "{}")
    return buf.getvalue()


#: The caption target this file's tests resolve: a real ``models:`` entry, because the
#: caption legs read the key from the entry now (spec 2026-09-23 D10.3/R14) — the env
#: fallback and the bare-id path are gone, so a bare id is no longer a target at all.
_VLM_ENTRY = {
    "name": "test-vlm",
    "use": "langchain_openai:ChatOpenAI",
    "model": "test-vlm-wire",
    "base_url": "https://vlm.example/v1",
    "api_key": "test-entry-key",
    "supports_vision": True,
}


def _vlm_config(*, with_key: bool = True, rag: dict | None = None):
    """The entry-backed config; ``with_key=False`` leaves the entry keyless on purpose.

    It is still a *target* (the entry exists), which is exactly the out-of-scope case the
    strict rule does not judge: the leg degrades to placeholders, as it always did.
    ``rag`` overrides the section's own keys (A-4's caption knobs).
    """
    from deerflow.config.app_config import AppConfig

    entry = {key: value for key, value in _VLM_ENTRY.items() if with_key or key != "api_key"}
    return AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": [entry], "rag": {"vlm_model": "test-vlm", **(rag or {})}})


def _mineru_transport(recorded: list[httpx.Request], *, poll_states: list[dict] | None = None) -> httpx.MockTransport:
    """Happy-path MinerU v4 mock: apply upload URL → PUT → poll → zip."""
    states = poll_states or [
        {"state": "running", "extract_progress": {"extracted_pages": 1, "total_pages": 2}},
        {"state": "done", "full_zip_url": "https://cdn.example.com/result.zip"},
    ]
    poll_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.method == "POST" and request.url.path == "/api/v4/file-urls/batch":
            return httpx.Response(200, json={"code": 0, "msg": "ok", "data": {"batch_id": "batch-1", "file_urls": ["https://oss.example.com/upload-1"]}})
        if request.method == "PUT" and request.url.host == "oss.example.com":
            return httpx.Response(200)
        if request.method == "GET" and request.url.path == "/api/v4/extract-results/batch/batch-1":
            state = states[min(poll_calls["n"], len(states) - 1)]
            poll_calls["n"] += 1
            return httpx.Response(200, json={"code": 0, "msg": "ok", "data": {"batch_id": "batch-1", "extract_result": [{"file_name": "手册.pdf", **state}]}})
        if request.method == "GET" and request.url.host == "cdn.example.com":
            return httpx.Response(200, content=_make_result_zip())
        return httpx.Response(404, json={"unexpected": f"{request.method} {request.url}"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_parse_pdf_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_mineru_transport(recorded))
    # zip 下载走独立 client（支持 MINERU_ZIP_PROXY，不经传入的 mock transport）
    # —— mock 掉网络层，保留真实 zip 解包路径的验证。
    from deerflow_knowledge import parser as parser_mod

    async def _fake_download(zip_url: str) -> bytes:
        return _make_result_zip()

    monkeypatch.setattr(parser_mod, "_download_zip", _fake_download)
    pdf = tmp_path / "手册.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    doc = await parse_document(pdf, client=client, poll_interval_seconds=0.01, timeout_seconds=5.0)

    assert "# 解析结果" in doc.markdown
    assert "正文第一段" in doc.markdown
    assert len(doc.images) == 1
    assert doc.images[0].ref == "images/p1.jpg"
    assert doc.images[0].content == b"\xff\xd8\xff\xe0jpeg-bytes"
    assert doc.images[0].media_type == "image/jpeg"

    # Request contract: Bearer auth, batch apply carries the file name, the
    # OSS upload is a bare-binary PUT (no Content-Type, per MinerU docs).
    apply_req = next(r for r in recorded if r.url.path == "/api/v4/file-urls/batch")
    assert apply_req.headers["Authorization"] == "Bearer test-token"
    assert json.loads(apply_req.content)["files"][0]["name"] == "手册.pdf"
    put_req = next(r for r in recorded if r.method == "PUT")
    assert put_req.headers.get("Content-Type") is None
    assert put_req.content == b"%PDF-1.4 fake"


@pytest.mark.asyncio
async def test_parse_markdown_file_short_circuits_mineru(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_mineru_transport(recorded))
    md = tmp_path / "笔记.md"
    md.write_text("# 直接可用\n\n无需解析。", encoding="utf-8")

    doc = await parse_document(md, client=client)

    assert doc.markdown == "# 直接可用\n\n无需解析。"
    assert doc.images == []
    assert recorded == []  # no HTTP call at all


@pytest.mark.asyncio
async def test_token_read_from_env_never_from_caller(tmp_path, monkeypatch):
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    with pytest.raises(MineruAuthError, match="MINERU_API_TOKEN"):
        await parse_document(pdf, client=httpx.AsyncClient(transport=_mineru_transport([])))


@pytest.mark.asyncio
async def test_auth_error_code_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "bad-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "A0202", "msg": "Token 错误"})

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(MineruAuthError):
        await parse_document(pdf, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_http_error_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(MineruError, match="503"):
        await parse_document(pdf, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_business_error_code_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": -10001, "msg": "服务异常"})

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(MineruError, match="服务异常"):
        await parse_document(pdf, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_failed_state_maps_to_parse_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    recorded: list[httpx.Request] = []
    transport = _mineru_transport(recorded, poll_states=[{"state": "failed", "err_msg": "文件格式不支持"}])
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    with pytest.raises(MineruParseFailedError, match="文件格式不支持"):
        await parse_document(pdf, client=httpx.AsyncClient(transport=transport), poll_interval_seconds=0.01, timeout_seconds=5.0)


@pytest.mark.asyncio
async def test_poll_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    recorded: list[httpx.Request] = []
    transport = _mineru_transport(recorded, poll_states=[{"state": "running"}])
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    with pytest.raises(MineruTimeoutError):
        await parse_document(pdf, client=httpx.AsyncClient(transport=transport), poll_interval_seconds=0.01, timeout_seconds=0.05)


# ── VLM captioner ──────────────────────────────────────────────────────────

_SAMPLE_IMAGE = ParsedImage(ref="images/p1.jpg", content=b"\xff\xd8\xff\xe0jpeg-bytes", media_type="image/jpeg")


def _vlm_transport(recorded: list[httpx.Request], *, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, text="vlm boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": "系统架构示意图"}}]})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_caption_images_calls_vlm_with_base64(monkeypatch):
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", _vlm_config)
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_vlm_transport(recorded))

    outcome = await caption_images([_SAMPLE_IMAGE], client=client, model="test-vlm")

    assert outcome.captions == {"images/p1.jpg": "系统架构示意图"}
    request = recorded[0]
    assert request.headers["Authorization"] == "Bearer test-entry-key"
    body = json.loads(request.content)
    assert body["model"] == "test-vlm-wire"
    content = body["messages"][0]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_apply_captions_merges_back_into_markdown():
    md = "# 标题\n\n前文 ![](images/p1.jpg) 后文\n\n![旧alt](images/p2.png)\n"
    merged = apply_captions(md, {"images/p1.jpg": "系统架构示意图", "images/p2.png": "部署流程图"})
    assert "![系统架构示意图](images/p1.jpg)" in merged
    assert "![部署流程图](images/p2.png)" in merged
    assert "旧alt" not in merged


# ── 落表清洗（spec 2026-10-03 §2.4；评审③=甲）───────────────────────────────


def test_apply_captions_flattens_newlines_so_the_table_row_stays_one_line():
    """D2=乙 把图链接放进表行内；多行 caption 会把 GFM 表行切断（chunker 的
    表收集随之提前终止），落笔前必须压成单行。"""
    md = "| a | b |\n| --- | --- |\n| 1 ![图片](images/x.png) | 2 |"

    merged = apply_captions(md, {"images/x.png": "第一行\r\n第二行\n第三行\r第四行"})

    assert merged.splitlines()[2] == "| 1 ![第一行 第二行 第三行 第四行](images/x.png) | 2 |"


def test_apply_captions_escapes_pipes_brackets_and_backslashes():
    r"""`|` 会串列、`[`/`]` 会破掉图片语法；先翻倍 `\` 再插入转义，保证后加的
    `\|`/`\[` 不再被二次转义。"""
    md = "| a | b |\n| --- | --- |\n| 1 ![图片](images/x.png) | 2 |"

    merged = apply_captions(md, {"images/x.png": "c:\\tmp | [草稿] 表"})

    assert merged.splitlines()[2] == r"| 1 ![c:\\tmp \| \[草稿\] 表](images/x.png) | 2 |"


def test_apply_captions_rewrites_anchored_cells_and_tail_images():
    """D2=乙 组装产物（表行内 ref、同格多图、段尾图）重写后结构不变、每处 alt
    就地换 caption（评审⑤钉点）。"""
    md = "## Sheet1\n\n| Region | Q1 |\n| --- | --- |\n| North | 120 ![图片](images/image1.png) ![图片](images/image2.png) |\n\n![图片](images/image3.png)"

    merged = apply_captions(md, {"images/image1.png": "柱状图", "images/image2.png": "折线图", "images/image3.png": "尾图"})

    assert merged == ("## Sheet1\n\n| Region | Q1 |\n| --- | --- |\n| North | 120 ![柱状图](images/image1.png) ![折线图](images/image2.png) |\n\n![尾图](images/image3.png)")


@pytest.mark.asyncio
async def test_vlm_failure_degrades_to_filename_placeholder(monkeypatch):
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", _vlm_config)
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_vlm_transport(recorded, status=500))

    outcome = await caption_images([_SAMPLE_IMAGE], client=client, model="test-vlm")

    assert outcome.captions == {"images/p1.jpg": "图片 p1.jpg"}


@pytest.mark.asyncio
async def test_missing_vlm_key_degrades_all_images(monkeypatch):
    """A target with no usable key degrades to placeholders — and now that is only reachable
    for an entry outside the strict grid (the declared-UI case is refused upstream)."""
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", lambda: _vlm_config(with_key=False))
    recorded: list[httpx.Request] = []

    outcome = await caption_images([_SAMPLE_IMAGE], client=httpx.AsyncClient(transport=_vlm_transport(recorded)), model="test-vlm")

    assert outcome.captions == {"images/p1.jpg": "图片 p1.jpg"}
    assert recorded == []  # no outbound call without a key


# ── Task 15: dual-mode captioning (full transcription for text-dense images) ──


def test_caption_prompt_offers_transcription_mode_for_text_dense_images():
    """Task 15: text-dense images (doc screenshots/tables/code) must be fully
    transcribed; other images keep the one-sentence summary. One prompt, two
    branches, still retrieval-oriented."""
    from deerflow_knowledge.captioner import _CAPTION_PROMPT

    assert "完整转录" in _CAPTION_PROMPT  # text-dense branch
    assert "一句" in _CAPTION_PROMPT  # summary branch kept


@pytest.mark.asyncio
async def test_caption_request_allows_transcription_length(monkeypatch):
    """Task 15: max_tokens raised from 256 (one sentence) to 1024 so a full
    page of transcribed text fits."""
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", _vlm_config)
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_vlm_transport(recorded))

    await caption_images([_SAMPLE_IMAGE], client=client, model="test-vlm")

    body = json.loads(recorded[0].content)
    assert body["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_caption_request_carries_the_configured_generation_params(monkeypatch):
    """A-4: the two knobs reach the wire from ``rag.caption_*`` (spec 2026-09-30 D1/D2)."""
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", lambda: _vlm_config(rag={"caption_max_tokens": 2048, "caption_temperature": 0.7}))
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_vlm_transport(recorded))

    await caption_images([_SAMPLE_IMAGE], client=client, model="test-vlm")

    body = json.loads(recorded[0].content)
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.7


@pytest.mark.asyncio
async def test_caption_request_defaults_are_the_pre_change_values(monkeypatch):
    """The leg-level negative control: undeclared ⇒ 1024 / 0.15 on the wire (Task 0 capture)."""
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", _vlm_config)
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_vlm_transport(recorded))

    await caption_images([_SAMPLE_IMAGE], client=client, model="test-vlm")

    body = json.loads(recorded[0].content)
    assert body["max_tokens"] == 1024
    assert body["temperature"] == 0.15


# ── Task 16: DashScope qwen3.7-flash + concurrency (RED) ──────────────────


def test_caption_prompt_no_longer_requests_structure_preservation():
    """Task 16: remove 'retain original structure' from prompt to cut token
    output by ~15–20% while still transcribing all text verbatim."""
    from deerflow_knowledge.captioner import _CAPTION_PROMPT

    assert "保留原有结构" not in _CAPTION_PROMPT  # removed
    assert "完整转录" in _CAPTION_PROMPT  # kept for full transcription


@pytest.mark.asyncio
async def test_concurrent_captions_maintain_original_order(monkeypatch):
    """Task 16: concurrent calls must return results in input list order; Markdown
    image positions are protected by key-value mapping, never mixed up.
    Simulate: p1 needs 5s, p2 needs 1s → p2 returns first but stays at pos2."""
    import asyncio

    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", _vlm_config)
    recorded: list[httpx.Request] = []

    # Mock transport that delays p1 more than p2 (simulate different generation times)
    call_count = [0]  # Mutable list for thread-safe counter
    lock = asyncio.Lock()

    async def delayed_handler(request: httpx.Request) -> httpx.Response:
        async with lock:
            call_count[0] += 1
            idx = call_count[0]
        recorded.append(request)
        if idx == 1:
            await asyncio.sleep(0.5)  # p1 slow
            return httpx.Response(200, json={"choices": [{"message": {"content": "caption for p1.jpg"}}]})
        else:
            await asyncio.sleep(0.1)  # p2 fast
            return httpx.Response(200, json={"choices": [{"message": {"content": "caption for p2.png"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(delayed_handler))
    images = [
        ParsedImage(ref="images/p1.jpg", content=b"jpeg-bytes", media_type="image/jpeg"),
        ParsedImage(ref="images/p2.png", content=b"png-bytes", media_type="image/png"),
    ]

    outcome = await caption_images(images, client=client, model="test-vlm")

    # Verify order preservation: dict keys match input list order
    assert list(outcome.captions.keys()) == ["images/p1.jpg", "images/p2.png"]
    assert "p1.jpg" in outcome.captions["images/p1.jpg"]
    assert "p2.png" in outcome.captions["images/p2.png"]


@pytest.mark.asyncio
async def test_timeout_parameter_extended_to_180_seconds(monkeypatch):
    """Task 16: timeout raised from 60s to 180s so long-form transcription fits.
    Connect timeout remains 15s."""
    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", _vlm_config)
    recorded: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "steady-state caption"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(transport_handler), timeout=httpx.Timeout(180.0, connect=15.0))

    await caption_images([_SAMPLE_IMAGE], client=client, model="test-vlm")

    # Timeout configured correctly
    assert client.timeout.connect == 15.0
    assert client.timeout.read == 180.0


# ── Task 6: local-read extension (.txt/.csv) + upload allowlist ────────────


def test_supported_upload_suffixes_contract():
    """spec §6 frozen set; helpers are case-insensitive, suffixes carry the dot."""
    from deerflow_knowledge.parser import SUPPORTED_UPLOAD_SUFFIXES, is_local_suffix, is_supported_suffix

    assert SUPPORTED_UPLOAD_SUFFIXES == frozenset(
        {
            ".md",
            ".markdown",
            ".txt",
            ".csv",
            ".pdf",
            ".doc",
            ".docx",
            ".ppt",
            ".pptx",
            ".png",
            ".jpg",
            ".jpeg",
        }
    )
    assert is_supported_suffix(".TXT")  # case-insensitive
    assert not is_supported_suffix(".exe")
    assert not is_supported_suffix("")
    for suffix in (".md", ".markdown", ".txt", ".csv"):
        assert is_local_suffix(suffix), suffix
    assert not is_local_suffix(".pdf")


def _stub_gates(monkeypatch, *, table: bool = False) -> None:
    """把 parser 的配置读取器指向表格腿 stub：门控两态不读本机 config.yaml。

    预存缺陷修复（2026-09-09）：off 态断言原先依赖「测试环境默认 off」，但开发机
    的真实 config.yaml 里该门是开的，使它们恒红。stub 让两态都可控。
    """
    from types import SimpleNamespace

    from deerflow_knowledge import parser as knowledge_parser

    monkeypatch.setattr(
        knowledge_parser,
        "get_app_config",
        lambda: SimpleNamespace(
            rag=SimpleNamespace(
                table=SimpleNamespace(enabled=table, max_size_mb=50, card_mode="markdown"),
            )
        ),
    )


def test_table_upload_suffixes_contract(monkeypatch):
    """spec 2026-09-09 §4（plan Task 1）：表格集是独立 frozenset（文本冻结集原地
    不动、`.csv` 留在文本集不进表格集），并集助手随 rag.table.enabled 两态。"""
    from deerflow_knowledge.parser import (
        SUPPORTED_UPLOAD_SUFFIXES,
        TABLE_UPLOAD_SUFFIXES,
        is_supported_suffix,
        supported_upload_suffixes,
        table_ingest_enabled,
        table_upload_limit_bytes,
    )

    assert TABLE_UPLOAD_SUFFIXES == frozenset({".xlsx", ".xls", ".tsv"})
    assert SUPPORTED_UPLOAD_SUFFIXES & TABLE_UPLOAD_SUFFIXES == frozenset()  # 两集不相交
    assert ".csv" in SUPPORTED_UPLOAD_SUFFIXES  # .csv 恒在文本集，成员身份不变
    assert ".csv" not in TABLE_UPLOAD_SUFFIXES

    # off 态：表格后缀被拒（大小写不敏感），体积门返 None（不新设限制）
    _stub_gates(monkeypatch)
    assert not table_ingest_enabled()
    assert supported_upload_suffixes() == SUPPORTED_UPLOAD_SUFFIXES
    assert not is_supported_suffix(".XLSX")
    assert is_supported_suffix(".csv")
    assert table_upload_limit_bytes() is None

    # on 态：并集含表格集，体积门按 max_size_mb 折算字节
    _stub_gates(monkeypatch, table=True)
    assert table_ingest_enabled()
    assert supported_upload_suffixes() == SUPPORTED_UPLOAD_SUFFIXES | TABLE_UPLOAD_SUFFIXES
    assert is_supported_suffix(".XLSX")
    assert is_supported_suffix(".tsv")
    assert is_supported_suffix(".md")
    assert table_upload_limit_bytes() == 50 * 1024 * 1024


def test_table_gate_degrades_to_off_when_config_unreadable(monkeypatch):
    """配置读取抛错时门控降级为 off——门口绝不因异常而放宽（spec §4）。"""
    from deerflow_knowledge import parser as knowledge_parser
    from deerflow_knowledge.parser import (
        SUPPORTED_UPLOAD_SUFFIXES,
        is_supported_suffix,
        supported_upload_suffixes,
        table_ingest_enabled,
        table_upload_limit_bytes,
    )

    def _boom():
        raise RuntimeError("config.yaml unreadable")

    monkeypatch.setattr(knowledge_parser, "get_app_config", _boom)

    assert not table_ingest_enabled()
    assert supported_upload_suffixes() == SUPPORTED_UPLOAD_SUFFIXES
    assert not is_supported_suffix(".xlsx")
    assert table_upload_limit_bytes() is None


@pytest.mark.asyncio
async def test_parse_txt_utf8_short_circuits_mineru(tmp_path, monkeypatch):
    # No token at all — local read must not touch the network or the env var.
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_mineru_transport(recorded))
    txt = tmp_path / "笔记.txt"
    txt.write_text("第一行\n第二行", encoding="utf-8")

    doc = await parse_document(txt, client=client)

    assert doc.markdown == "第一行\n第二行"
    assert doc.images == []
    assert recorded == []


@pytest.mark.asyncio
async def test_parse_txt_gbk_fallback(tmp_path):
    txt = tmp_path / "国标.txt"
    txt.write_bytes("中文标题\n正文第二行".encode("gbk"))

    doc = await parse_document(txt, client=httpx.AsyncClient(transport=_mineru_transport([])))

    assert doc.markdown == "中文标题\n正文第二行"


@pytest.mark.asyncio
async def test_parse_csv_local_read_gbk(tmp_path):
    """CSV 走表格感知解析（spec 2026-09-09 §5）：GBK 回退仍生效，输出 GFM 管道表而非原始逗号文本。"""
    csv = tmp_path / "数据.csv"
    csv.write_bytes("名称,数量\n苹果,3".encode("gbk"))

    doc = await parse_document(csv, client=httpx.AsyncClient(transport=_mineru_transport([])))

    assert doc.markdown == "| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |"


@pytest.mark.asyncio
async def test_parse_local_read_undecodable_raises_value_error(tmp_path):
    bad = tmp_path / "坏编码.txt"
    bad.write_bytes(b"\xff\xff\xfe\xfd")  # neither UTF-8 nor GBK

    with pytest.raises(ValueError, match="坏编码.txt"):
        await parse_document(bad, client=httpx.AsyncClient(transport=_mineru_transport([])))


# ── zip 下载：专用代理逃生通道（2026-08-23 Defender 按进程树拦截直连）────────


def test_download_zip_uses_proxy_env(monkeypatch):
    """MINERU_ZIP_PROXY 设置时，zip 下载走该代理（绕过宿主进程直连被拦）。"""
    import asyncio

    from deerflow_knowledge import parser as parser_mod

    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            class _Resp:
                status_code = 200
                content = b"zip-bytes"
                text = ""

            return _Resp()

    monkeypatch.setenv("MINERU_ZIP_PROXY", "http://127.0.0.1:57519")
    monkeypatch.setattr(parser_mod.httpx, "AsyncClient", _FakeClient)

    result = asyncio.run(parser_mod._download_zip("https://cdn.example.com/x.zip"))

    assert result == b"zip-bytes"
    assert captured.get("proxy") == "http://127.0.0.1:57519"


def test_download_zip_direct_without_proxy_env(monkeypatch):
    """未设置 MINERU_ZIP_PROXY 时，zip 下载直连（不传 proxy 参数）。"""
    import asyncio

    from deerflow_knowledge import parser as parser_mod

    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            class _Resp:
                status_code = 200
                content = b"zip-bytes"
                text = ""

            return _Resp()

    monkeypatch.delenv("MINERU_ZIP_PROXY", raising=False)
    monkeypatch.setattr(parser_mod.httpx, "AsyncClient", _FakeClient)

    result = asyncio.run(parser_mod._download_zip("https://cdn.example.com/x.zip"))

    assert result == b"zip-bytes"
    assert "proxy" not in captured


def test_download_zip_falls_back_to_direct_when_proxy_unreachable(monkeypatch):
    """代理不可达（ConnectError）时自动降级直连——安全软件关/开两种环境都可用。"""
    import asyncio

    from deerflow_knowledge import parser as parser_mod

    attempts: list[dict] = []

    class _FakeClient:
        def __init__(self, **kwargs):
            attempts.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            if "proxy" in attempts[-1]:
                raise httpx.ConnectError("proxy refused")

            class _Resp:
                status_code = 200
                content = b"zip-via-direct"
                text = ""

            return _Resp()

    monkeypatch.setenv("MINERU_ZIP_PROXY", "http://127.0.0.1:57519")
    monkeypatch.setattr(parser_mod.httpx, "AsyncClient", _FakeClient)

    result = asyncio.run(parser_mod._download_zip("https://cdn.example.com/x.zip"))

    assert result == b"zip-via-direct"
    assert len(attempts) == 2  # 先代理后直连
    assert "proxy" in attempts[0] and "proxy" not in attempts[1]


# ── 2026-09-04: MinerU 短文档输出归一化（标题被放到文末）───────────────────


def _make_result_zip_with_md(markdown: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", markdown)
    return buf.getvalue()


def _fake_zip_download(zip_bytes: bytes):
    async def _download(zip_url: str) -> bytes:
        return zip_bytes

    return _download


async def _parse_pdf_from_zip(tmp_path, monkeypatch, markdown: str) -> str:
    from deerflow_knowledge import parser as parser_mod

    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    monkeypatch.setattr(parser_mod, "_download_zip", _fake_zip_download(_make_result_zip_with_md(markdown)))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    doc = await parse_document(pdf, client=httpx.AsyncClient(transport=_mineru_transport([])), poll_interval_seconds=0.01, timeout_seconds=5.0)
    return doc.markdown


@pytest.mark.asyncio
async def test_mineru_trailing_sole_title_relocated_to_top(tmp_path, monkeypatch):
    """复现 2026-09-04（春秋肠.pdf）：MinerU 把页面标题作为 ``##`` 标题行放在
    正文之后，切片随之变成「正文在前、加粗标题在后」。MinerU 路径应把全文唯一
    且位于文末的标题行搬回文档开头。"""
    body = "JVM 堆内存分为新生代和老年代：新生代采用复制算法回收，老年代采用标记-整理算法。"
    markdown = await _parse_pdf_from_zip(tmp_path, monkeypatch, f"{body}\n\n## 你好呀,我是沉只鸭")

    assert markdown == f"## 你好呀,我是沉只鸭\n\n{body}"


@pytest.mark.asyncio
async def test_mineru_trailing_heading_kept_when_other_headings_exist(tmp_path, monkeypatch):
    """多标题文档末尾的悬空小节标题是合法结构，不得搬移。"""
    source = "# 章\n\n正文一。\n\n## 尾节\n"
    markdown = await _parse_pdf_from_zip(tmp_path, monkeypatch, source)

    assert markdown == source


@pytest.mark.asyncio
async def test_mineru_trailing_heading_inside_fence_not_moved(tmp_path, monkeypatch):
    """未闭合代码 fence 内的 ``#`` 行不是标题（与 chunker 同口径）。"""
    source = "正文。\n\n```\n## 尾\n"
    markdown = await _parse_pdf_from_zip(tmp_path, monkeypatch, source)

    assert markdown == source


@pytest.mark.asyncio
async def test_mineru_heading_only_document_not_moved(tmp_path, monkeypatch):
    """全文只有一行标题（无正文）时没有可搬移的对象，原样返回。"""
    source = "## 只有标题\n"
    markdown = await _parse_pdf_from_zip(tmp_path, monkeypatch, source)

    assert markdown == source


# ── Task 2: 分隔文本 CSV/TSV → GFM 管道表（spec 2026-09-09 §5）──────────────
#
# `.csv`/`.tsv` 从「原始文本 dump」升级为「表格感知」：首行表头 → GFM 管道表，编码复用
# UTF-8 严格 → GBK 回退 + BOM 剥离，`.tsv` 固定 tab / `.csv` 用 csv.Sniffer 嗅探逗号/分号
# （回退逗号）。均经 ``parse_document`` 本地分支路由（不触网、不触 MinerU）。


def test_parse_delimited_csv_comma_to_gfm(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "sales.csv"
    p.write_bytes("名称,数量\n苹果,3\n香蕉,5\n".encode())

    assert _parse_delimited(p) == "| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |\n| 香蕉 | 5 |"


def test_parse_delimited_csv_semicolon_sniffed(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "semi.csv"
    p.write_bytes(b"a;b;c\n1;2;3\n")

    assert _parse_delimited(p) == "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 | 3 |"


def test_parse_delimited_tsv_fixed_tab(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "data.tsv"
    p.write_bytes("列一\t列二\n值A\t值B\n".encode())

    assert _parse_delimited(p) == "| 列一 | 列二 |\n| --- | --- |\n| 值A | 值B |"


def test_parse_delimited_gbk_fallback(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "国标.csv"
    p.write_bytes("名称,数量\n苹果,3".encode("gbk"))

    assert _parse_delimited(p) == "| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |"


def test_parse_delimited_strips_utf8_bom(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "bom.csv"
    p.write_bytes("\ufeff名称,数量\n苹果,3\n".encode("utf-8"))

    out = _parse_delimited(p)

    assert "\ufeff" not in out  # BOM 不残留进首个表头单元格
    assert out.splitlines()[0] == "| 名称 | 数量 |"


def test_parse_delimited_ragged_rows_fit_header_width(tmp_path):
    """行宽不齐：短行补空、长行截断到表头列数（与 HTML 归一同口径，spec §5）。"""
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "ragged.csv"
    p.write_bytes(b"a,b,c\n1,2\n3,4,5,6\n")

    assert _parse_delimited(p) == "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |  |\n| 3 | 4 | 5 |"


def test_parse_delimited_cell_pipe_is_escaped(tmp_path):
    """单元格内字面竖线转义后不破坏 GFM 列结构（parser 保证输出恒为合法 GFM）。"""
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "pipe.csv"
    p.write_bytes(b"cmd,note\na|b,keep\n")

    assert _parse_delimited(p).splitlines()[2] == "| a\\|b | keep |"


def test_parse_delimited_collapses_multiline_cell_to_space(tmp_path):
    """带引号的多行单元格 → 空白折叠为单空格（GFM 单元格必须单行，spec §5）。"""
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "multi.csv"
    p.write_bytes(b'a,b\n"line1\nline2",x\n')

    assert _parse_delimited(p).splitlines()[2] == "| line1 line2 | x |"


def test_parse_delimited_empty_file_returns_empty_string(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "empty.csv"
    p.write_bytes(b"")

    assert _parse_delimited(p) == ""


def test_parse_delimited_blank_only_returns_empty_string(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "blank.csv"
    p.write_bytes(b"\n\n  \n")

    assert _parse_delimited(p) == ""


def test_parse_delimited_header_only_no_data_rows(tmp_path):
    """单行（仅表头）→ GFM 表头 + 分隔行，无数据行。"""
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "header_only.csv"
    p.write_bytes(b"a,b,c\n")

    assert _parse_delimited(p) == "| a | b | c |\n| --- | --- | --- |"


def test_parse_delimited_skips_blank_rows(tmp_path):
    from deerflow_knowledge.parser import _parse_delimited

    p = tmp_path / "gaps.csv"
    p.write_bytes(b"a,b\n1,2\n\n3,4\n")

    assert _parse_delimited(p) == "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"


@pytest.mark.asyncio
async def test_parse_document_routes_csv_to_delimited_not_verbatim(tmp_path, monkeypatch):
    """`.csv` 本地分支改路由到 `_parse_delimited`：输出 GFM 而非原始逗号文本，仍不触网。"""
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    recorded: list[httpx.Request] = []
    p = tmp_path / "sales.csv"
    p.write_bytes(b"a,b\n1,2\n")

    doc = await parse_document(p, client=httpx.AsyncClient(transport=_mineru_transport(recorded)))

    assert doc.markdown == "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert doc.images == []
    assert recorded == []


@pytest.mark.asyncio
async def test_parse_document_routes_tsv_to_delimited_no_mineru(tmp_path, monkeypatch):
    """`.tsv` 是本地读后缀（绝不进 MinerU）且走 `_parse_delimited`。"""
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    recorded: list[httpx.Request] = []
    p = tmp_path / "data.tsv"
    p.write_bytes(b"a\tb\n1\t2\n")

    doc = await parse_document(p, client=httpx.AsyncClient(transport=_mineru_transport(recorded)))

    assert doc.markdown == "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert recorded == []


def test_is_local_suffix_covers_tsv():
    """`.tsv` 归本地读集（永不触 MinerU）；`.csv` 成员身份不变。"""
    from deerflow_knowledge.parser import is_local_suffix

    assert is_local_suffix(".tsv")
    assert is_local_suffix(".TSV")
    assert is_local_suffix(".csv")


# ── Task 2: MinerU HTML <table> → GFM 归一（spec 2026-09-09 §5，Task 0 实测冻结）──
#
# Task 0 实测门坐实：MinerU 云 API v4 + model_version="vlm" 恒出 HTML <table>，不出 GFM →
# 归一器是必需路径。形态 A fixture 直接取 pr-build/t0-mineru-table-gate/ 两份实测 full.md
# （无 <thead>/<th>、表头=首 <tr>、整表压一行、含 rowspan/colspan；底纹表头失读→首行全空
# <td>）。形态 B（docx 路：<thead><th> + 嵌套 <p>/<strong> + 单格多 <p> + 隐式空 <td>）
# 按 spec §5 实测样例构造。

# 形态 A（t0_mineru_full_plain.md 第 7 行）：无 <thead>、表头=首 <tr>、整表压一行
_FORM_A_TABLE1 = (
    "<table><tr><td>Region</td><td>Q1</td><td>Q2</td><td>Total</td></tr>"
    "<tr><td>North</td><td>120</td><td>135</td><td>255</td></tr>"
    "<tr><td>South</td><td>98</td><td>112</td><td>210</td></tr>"
    "<tr><td>East</td><td>143</td><td>150</td><td>293</td></tr>"
    "<tr><td>West</td><td>87</td><td>94</td><td>181</td></tr></table>"
)
# 形态 A（t0_mineru_full_plain.md 第 11 行）：含 rowspan=2 / colspan=3
_FORM_A_TABLE2 = (
    "<table><tr><td>Product</td><td>Attribute</td><td>Value</td></tr>"
    '<tr><td rowspan="2">Widget A</td><td>Color</td><td>Red</td></tr>'
    "<tr><td>Weight</td><td>2.4 kg</td></tr>"
    "<tr><td>Widget B</td><td>Color</td><td>Blue</td></tr>"
    '<tr><td colspan="3">Notes: measured at 20 C under dry conditions.</td></tr></table>'
)
# 底纹表头失读（t0_mineru_full.md 第 7 行）：首行 <tr> 全空 <td>
_FORM_A_SHADED_TABLE1 = (
    "<table><tr><td></td><td></td><td></td><td></td></tr>"
    "<tr><td>North</td><td>120</td><td>135</td><td>255</td></tr>"
    "<tr><td>South</td><td>98</td><td>112</td><td>210</td></tr>"
    "<tr><td>East</td><td>143</td><td>150</td><td>293</td></tr>"
    "<tr><td>West</td><td>87</td><td>94</td><td>181</td></tr></table>"
)


def test_normalize_form_a_header_is_first_tr():
    """形态 A（PDF 路）：无 <thead>/<th> → 表头回落首个 <tr>；整表压一行也吃下。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    assert _normalize_tables_to_gfm(_FORM_A_TABLE1) == ("| Region | Q1 | Q2 | Total |\n| --- | --- | --- | --- |\n| North | 120 | 135 | 255 |\n| South | 98 | 112 | 210 |\n| East | 143 | 150 | 293 |\n| West | 87 | 94 | 181 |")


def test_normalize_rowspan_sinks_value_into_spanned_rows():
    """rowspan=2 扁平化：值下沉填充到被跨的行（检索行卡自足，spec §5）。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    lines = _normalize_tables_to_gfm(_FORM_A_TABLE2).splitlines()

    assert lines[0] == "| Product | Attribute | Value |"
    assert lines[2] == "| Widget A | Color | Red |"
    assert lines[3] == "| Widget A | Weight | 2.4 kg |"  # Widget A 下沉填充
    assert lines[4] == "| Widget B | Color | Blue |"


def test_normalize_colspan_row_padded_to_header_width():
    """colspan=3 行只回 1 个 <td> → 值取首列、余列空、补齐到表头 3 列（spec §5）。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    lines = _normalize_tables_to_gfm(_FORM_A_TABLE2).splitlines()

    assert lines[-1] == "| Notes: measured at 20 C under dry conditions. |  |  |"


def test_normalize_shaded_empty_header_not_guessed():
    """底纹表头失读（首 <tr> 全空 <td>）：不猜列名、退化为无列名行组、列数守恒。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    lines = _normalize_tables_to_gfm(_FORM_A_SHADED_TABLE1).splitlines()

    assert lines[0] == "|  |  |  |  |"  # 4 空列，绝不臆造列名
    assert lines[1] == "| --- | --- | --- | --- |"
    assert lines[2] == "| North | 120 | 135 | 255 |"


def test_normalize_form_b_nested_p_strong_joined_by_space():
    """形态 B（docx 路）：<thead><th> + 嵌套 <p>/<strong>；单格多 <p> 以空格连接、绝不插
    换行；剥内嵌标签。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    html = "<table><thead><tr><th><p><strong>数据类型</strong></p></th><th><p>Private</p><p>扑瑞沃特</p></th></tr></thead><tbody><tr><td><p>基本类型</p></td><td><p>int</p></td></tr></tbody></table>"

    assert _normalize_tables_to_gfm(html) == "| 数据类型 | Private 扑瑞沃特 |\n| --- | --- |\n| 基本类型 | int |"


def test_normalize_form_b_implicit_empty_td_tolerated():
    """形态 B 合并区的隐式空 <td></td>（无 span 属性）：按字面空值处理、宽度守恒。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    html = "<table><tbody><tr><th>类别</th><th>类型</th></tr><tr><td></td><td>可中断锁</td></tr><tr><td></td><td>可重入锁</td></tr></tbody></table>"

    assert _normalize_tables_to_gfm(html) == "| 类别 | 类型 |\n| --- | --- |\n|  | 可中断锁 |\n|  | 可重入锁 |"


def test_normalize_unescapes_html_entities():
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    html = "<table><tr><td>A &amp; B</td><td>&lt;tag&gt;</td></tr><tr><td>x</td><td>y</td></tr></table>"

    assert _normalize_tables_to_gfm(html).splitlines()[0] == "| A & B | <tag> |"


def test_normalize_already_gfm_is_noop():
    """已是 GFM 管道表（用户 authored .md）：幂等 no-op，原样返回。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    gfm = "| a | b |\n| --- | --- |\n| 1 | 2 |"

    assert _normalize_tables_to_gfm(gfm) == gfm


def test_normalize_prose_with_pipe_untouched():
    """散文里的 |（shell 管道）不在 <table> 内 → 原样保留，绝不误判为表格（Task 0 #6）。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    prose = "Pipeline note: the shell command cat sales.csv | grep north | wc -l counts rows."

    assert _normalize_tables_to_gfm(prose) == prose


def test_normalize_preserves_surrounding_markdown():
    """归一只替换 <table> 段，标题/散文/空行逐字保留（散文里的 | 不动）。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    md = "## 报告\n\n表一：\n\n" + _FORM_A_TABLE1 + "\n\n结尾 cat a.csv | grep x | wc -l 说明。"

    out = _normalize_tables_to_gfm(md)

    assert out.startswith("## 报告\n\n表一：\n\n| Region | Q1 | Q2 | Total |")
    assert out.endswith("| West | 87 | 94 | 181 |\n\n结尾 cat a.csv | grep x | wc -l 说明。")


def test_normalize_nested_table_left_as_residual_html():
    """嵌套表（归一器未覆盖形态）→ 整段原样保留为残留 HTML，交 chunker 原子块防御（spec §6）。"""
    from deerflow_knowledge.parser import _normalize_tables_to_gfm

    nested = "<table><tr><td><table><tr><td>inner</td></tr></table></td></tr></table>"

    assert _normalize_tables_to_gfm(nested) == nested


@pytest.mark.asyncio
async def test_mineru_html_table_normalized_to_gfm(tmp_path, monkeypatch):
    """集成：MinerU 分支（v4+vlm 恒出 HTML）经 `_normalize_tables_to_gfm` 落地为 GFM。"""
    md = "## Quarterly Sales Report\n\nTable 1.\n\n" + _FORM_A_TABLE1 + "\n\nNote: cat sales.csv | grep north | wc -l counts rows. End."

    markdown = await _parse_pdf_from_zip(tmp_path, monkeypatch, md)

    assert "| Region | Q1 | Q2 | Total |" in markdown
    assert "<table>" not in markdown
    assert "cat sales.csv | grep north | wc -l" in markdown  # 散文 | 保留


@pytest.mark.asyncio
async def test_local_markdown_html_table_not_normalized(tmp_path, monkeypatch):
    """归一器只作用于 MinerU 分支；本地直读 .md 的 HTML 表原样保留（用户 authored，spec §5）。"""
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    md = tmp_path / "笔记.md"
    md.write_text("前文\n\n<table><tr><td>a</td></tr></table>", encoding="utf-8")

    doc = await parse_document(md, client=httpx.AsyncClient(transport=_mineru_transport([])))

    assert "<table><tr><td>a</td></tr></table>" in doc.markdown  # 未归一


@pytest.mark.asyncio
async def test_local_markdown_trailing_heading_not_touched(tmp_path, monkeypatch):
    """归一化只作用于 MinerU 输出；本地直读的 .md 是用户 authored 内容，原样返回。"""
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    md = tmp_path / "笔记.md"
    md.write_text("正文。\n\n## 尾节", encoding="utf-8")

    doc = await parse_document(md, client=httpx.AsyncClient(transport=_mineru_transport([])))

    assert doc.markdown == "正文。\n\n## 尾节"


# ── Task 3: Excel .xlsx/.xls → 每 sheet 一张 GFM 表（spec 2026-09-09 §5）──────
#
# `_parse_excel` 门控 rag.table.enabled + 延迟 import python-calamine（缺失/门控 off
# 抛清晰 ValueError），blocking 读取经 run_file_io；每 sheet → `## {sheet}\n\n<GFM 表>`，
# 空 sheet 跳过、多 sheet 顺序拼接。纯转换 `_workbook_rows_to_markdown` 用字面 sheet 数据
# 直测（复用 Task 2 的 _gfm_row/_fit_width）；`_parse_excel` 用 fake calamine 模块覆盖接线/
# 降级；真实 .xlsx 端到端 skipif（本机/CI 无 calamine 不阻塞回归，对齐视频 Task 3 skipif 纪律）。


def test_workbook_to_markdown_single_sheet_first_row_header():
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown([("Sales", [["Region", "Q1"], ["North", 120], ["South", 98]])])

    assert md == "## Sales\n\n| Region | Q1 |\n| --- | --- |\n| North | 120 |\n| South | 98 |"


def test_workbook_to_markdown_multi_sheet_in_order_joined_by_blank_line():
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown(
        [
            ("Q1", [["a"], ["1"]]),
            ("Q2", [["b"], ["2"]]),
        ]
    )

    assert md == "## Q1\n\n| a |\n| --- |\n| 1 |\n\n## Q2\n\n| b |\n| --- |\n| 2 |"


def test_workbook_to_markdown_skips_empty_sheet():
    """空 sheet（无行 / 全空行）跳过，不产出空 ## 段（spec §5）。"""
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown(
        [
            ("Data", [["a"], ["1"]]),
            ("Blank", []),
            ("Whitespace", [["", ""], ["", ""]]),
            ("More", [["b"], ["2"]]),
        ]
    )

    assert "## Blank" not in md
    assert "## Whitespace" not in md
    assert md == "## Data\n\n| a |\n| --- |\n| 1 |\n\n## More\n\n| b |\n| --- |\n| 2 |"


def test_workbook_to_markdown_all_sheets_empty_returns_empty_string():
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    assert _workbook_rows_to_markdown([("A", []), ("B", [["", ""]])]) == ""


def test_workbook_to_markdown_stringifies_typed_cells():
    """calamine to_python 返回原生类型（int/float/bool/None）→ 文本；None 落空单元格。"""
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown([("S", [["n", "f", "b", "e"], [120, 2.5, True, None]])])

    assert md.splitlines()[-1] == "| 120 | 2.5 | True |  |"


def test_workbook_to_markdown_integral_float_renders_as_int():
    """calamine 把数值单元格读成 float（120.0）→ 渲染为整数形式 120，非 120.0。

    真实 .xlsx 端到端（openpyxl 写 int、calamine 读回 float）暴露：整数列显示
    120.0 是格式瑕疵；整值 float 归一为 int 文本，非整值 float 保留小数。
    """
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown([("S", [["n", "f"], [120.0, 2.5]])])

    assert md.splitlines()[-1] == "| 120 | 2.5 |"


def test_workbook_to_markdown_ragged_rows_fit_header_width():
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown([("S", [["a", "b", "c"], ["1"], ["2", "3", "4", "5"]])])

    assert md == "## S\n\n| a | b | c |\n| --- | --- | --- |\n| 1 |  |  |\n| 2 | 3 | 4 |"


def test_workbook_to_markdown_header_only_sheet():
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    assert _workbook_rows_to_markdown([("S", [["a", "b"]])]) == "## S\n\n| a | b |\n| --- | --- |"


def _install_fake_calamine(monkeypatch, sheets, starts=None):
    """把 fake `python_calamine` 塞进 sys.modules：CalamineWorkbook.from_path →
    sheet_names（属性）/ get_sheet_by_name(name).to_python() → rows，镜像真实 API。

    ``starts`` 按 sheet 覆盖 ``sheet.start``（0-based 绝对 (row, col) 原点；缺省
    ``(0, 0)``，显式传 ``None`` 模拟空 sheet —— 真实 calamine 空 sheet 即 None）。"""
    import sys
    import types

    class _FakeSheet:
        def __init__(self, rows, start):
            self._rows = rows
            self.start = start

        def to_python(self, **kwargs):
            return self._rows

    class _FakeWorkbook:
        def __init__(self, data):
            self._data = data
            self.sheet_names = list(data)

        @classmethod
        def from_path(cls, path):
            return cls(sheets)

        def get_sheet_by_name(self, name):
            start = starts[name] if starts and name in starts else (0, 0)
            return _FakeSheet(self._data[name], start)

    module = types.ModuleType("python_calamine")
    module.CalamineWorkbook = _FakeWorkbook
    monkeypatch.setitem(sys.modules, "python_calamine", module)


@pytest.mark.asyncio
async def test_parse_excel_gate_off_raises_clear_error(tmp_path, monkeypatch):
    """门控 off：不进 calamine，直接抛清晰 ValueError（带 rag.table.enabled，spec §4/§8）。"""
    from deerflow_knowledge.parser import _parse_excel

    _stub_gates(monkeypatch)  # table off
    p = tmp_path / "book.xlsx"
    p.write_bytes(b"not-really-read")

    with pytest.raises(ValueError, match="rag.table.enabled"):
        await _parse_excel(p)


@pytest.mark.asyncio
async def test_parse_excel_missing_calamine_raises_clear_error(tmp_path, monkeypatch):
    """门控 on 但 python-calamine 缺失：抛清晰 ValueError（带安装指引），不静默产空。"""
    import sys

    from deerflow_knowledge.parser import _parse_excel

    _stub_gates(monkeypatch, table=True)
    monkeypatch.setitem(sys.modules, "python_calamine", None)  # 强制 ImportError
    p = tmp_path / "book.xlsx"
    p.write_bytes(b"x")

    with pytest.raises(ValueError, match="calamine"):
        await _parse_excel(p)


@pytest.mark.asyncio
async def test_parse_excel_happy_path_via_fake_calamine(tmp_path, monkeypatch):
    """fake calamine 走完接线：from_path → sheet_names → get_sheet_by_name → to_python
    → 每 sheet 一段 GFM；证明 run_file_io 包裹的 blocking 读取产出正确 markdown。
    .xlsx 会尽力读一次 zip（本夹具是假字节 ⇒ 落回退腿、images 空，spec 2026-10-03）。"""
    from deerflow_knowledge.parser import _parse_excel

    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"Sales": [["Region", "Q1"], ["North", 120]], "Empty": []})
    p = tmp_path / "book.xlsx"
    p.write_bytes(b"xlsx-bytes")  # 假字节：图片提取走 BadZipFile 回退腿

    doc = await _parse_excel(p)

    assert doc.markdown == "## Sales\n\n| Region | Q1 |\n| --- | --- |\n| North | 120 |"
    assert doc.images == []


@pytest.mark.asyncio
async def test_parse_document_routes_xlsx_to_parse_excel_no_mineru(tmp_path, monkeypatch):
    """`.xlsx` 经 parse_document 路由到 _parse_excel（不触 MinerU/网络）。"""
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"S1": [["a", "b"], ["1", "2"]]})
    recorded: list[httpx.Request] = []
    p = tmp_path / "book.xlsx"
    p.write_bytes(b"xlsx-bytes")

    doc = await parse_document(p, client=httpx.AsyncClient(transport=_mineru_transport(recorded)))

    assert doc.markdown == "## S1\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert doc.images == []
    assert recorded == []


def _calamine_available() -> bool:
    try:
        import python_calamine  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _calamine_available(), reason="python-calamine 未安装（uv sync --extra table）")
@pytest.mark.asyncio
async def test_parse_excel_real_xlsx_end_to_end(tmp_path, monkeypatch):
    """真实 .xlsx 端到端（openpyxl 造 → calamine 读）：多 sheet + 空 sheet 跳过 + GFM。
    本机/CI 无 calamine → skip，不阻塞回归（对齐视频 Task 3 skipif 纪律）。"""
    import openpyxl

    _stub_gates(monkeypatch, table=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Region", "Q1"])
    ws.append(["North", 120])
    ws.append(["South", 98])
    wb.create_sheet("Empty")  # 空 sheet
    p = tmp_path / "real.xlsx"
    wb.save(p)

    doc = await parse_document(p, client=httpx.AsyncClient(transport=_mineru_transport([])))

    assert "## Sales" in doc.markdown
    assert "| Region | Q1 |" in doc.markdown
    assert "| North | 120 |" in doc.markdown
    assert "## Empty" not in doc.markdown


# ── 工作簿内嵌图片提取（spec 2026-10-03 D2=乙/§2.4）────────────────────────────
#
# `.xlsx` 是 zip：提取只读 OOXML 关系链（workbook → sheet rels → drawing 锚点 →
# drawing rels → media），纯 stdlib。夹具手造最小 OOXML 包，不依赖 openpyxl/calamine；
# 真 .xlsx 端到端在 Task 4。锚点=`xdr:from` 0-based 绝对 (row, col)；只取包内
# `xl/media/` 下经 `r:embed` 引用的白名单媒体（`r:link` 外部图、越界部件跳过）。

_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_XLSX_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX_XDR_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_XLSX_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _rel(rid, rel_type, target, *, external=False):
    mode = ' TargetMode="External"' if external else ""
    return f'<Relationship Id="{rid}" Type="{rel_type}" Target="{target}"{mode}/>'


def _rels(*entries):
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_XLSX_RELS_NS}">' + "".join(entries) + "</Relationships>"


def _anchor(kind, *, embed=None, link=None, frm=None, to=None, pic_id=1):
    """一个 drawing 锚（oneCell/twoCell/absolute）包一张图。

    ``frm``/``to`` 为 0-based ``(col, row)``（XML 子元素序）；``embed`` 写 ``r:embed``
    （包内字节），``link`` 写 ``r:link``（外部图，刻意没有字节可取）。
    """

    def _cell(tag, pair):
        return f"<xdr:{tag}><xdr:col>{pair[0]}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{pair[1]}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:{tag}>"

    blip = f'<a:blip r:embed="{embed}"/>' if embed is not None else f'<a:blip r:link="{link}"/>'
    body = []
    if kind == "absoluteAnchor":
        body.append('<xdr:pos x="0" y="0"/><xdr:ext cx="200000" cy="200000"/>')
    else:
        if frm is not None:
            body.append(_cell("from", frm))
        if to is not None:
            body.append(_cell("to", to))
        if kind == "oneCellAnchor":
            body.append('<xdr:ext cx="200000" cy="200000"/>')
    body.append(f'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{pic_id}" name="Picture {pic_id}"/><xdr:cNvPicPr/></xdr:nvPicPr><xdr:blipFill>{blip}<a:stretch/></xdr:blipFill><xdr:spPr/></xdr:pic>')
    body.append("<xdr:clientData/>")
    return f"<xdr:{kind}>" + "".join(body) + f"</xdr:{kind}>"


def _drawing(*anchors):
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="{_XLSX_XDR_NS}" xmlns:a="{_XLSX_A_NS}" xmlns:r="{_XLSX_R_NS}">' + "".join(anchors) + "</xdr:wsDr>"


def _build_xlsx(path, *, sheet1_rels=None, drawing=None, drawing_rels=None, members=None):
    """最小两 sheet OOXML 包：``Sheet1`` 挂（可选）drawing 链、``Notes`` 永无 rels；
    workbook rels 刻意一绝对一相对，钉住 Target 两形态。返回 ``path``。"""
    parts = {
        "xl/workbook.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_XLSX_MAIN_NS}" xmlns:r="{_XLSX_R_NS}"><sheets>'
            f'<sheet name="Sheet1" sheetId="1" r:id="rId1"/><sheet name="Notes" sheetId="2" r:id="rId2"/>'
            f"</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": _rels(
            _rel("rId1", f"{_XLSX_R_NS}/worksheet", "/xl/worksheets/sheet1.xml"),
            _rel("rId2", f"{_XLSX_R_NS}/worksheet", "worksheets/sheet2.xml"),
        ),
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{_XLSX_MAIN_NS}"/>',
        "xl/worksheets/sheet2.xml": f'<worksheet xmlns="{_XLSX_MAIN_NS}"/>',
    }
    if sheet1_rels is not None:
        parts["xl/worksheets/_rels/sheet1.xml.rels"] = sheet1_rels
    if drawing is not None:
        parts["xl/drawings/drawing1.xml"] = drawing
    if drawing_rels is not None:
        parts["xl/drawings/_rels/drawing1.xml.rels"] = drawing_rels
    parts.update(members or {})
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in parts.items():
            zf.writestr(name, content)
    return path


# Sheet1 的 sheet rels：一个 drawing 关系 + 一个 hyperlink 关系（只认 /drawing 类型）。
_SHEET1_RELS = _rels(
    _rel("rId1", f"{_XLSX_R_NS}/drawing", "/xl/drawings/drawing1.xml"),
    _rel("rId2", f"{_XLSX_R_NS}/hyperlink", "https://example.com/", external=True),
)

# 富夹具：7 个锚覆盖三形态/白名单/去重/双闸/悬空引用——
# ① oneCell(4,2) embed rId1 → image1.png 命中锚（首见）
# ② twoCell from=(19,5) to=(20,6) embed rId2 → image2.jpeg（只读 from）
# ③ absoluteAnchor embed rId3 → image3.png（无 from ⇒ 无锚）
# ④ oneCell(1,1) embed rId4 → image4.emf（白名单外跳过）
# ⑤ oneCell(3,3) r:link rId5 → 外部图跳过
# ⑥ oneCell(0,0) embed rId6 → /xl/embeddings/note.png（xl/media 硬界外跳过）
# ⑦ oneCell(7,7) embed rId1 → 同媒体第二次引用（去重，归①的锚）
_RICH_DRAWING = _drawing(
    _anchor("oneCellAnchor", embed="rId1", frm=(4, 2), pic_id=1),
    _anchor("twoCellAnchor", embed="rId2", frm=(19, 5), to=(20, 6), pic_id=2),
    _anchor("absoluteAnchor", embed="rId3", pic_id=3),
    _anchor("oneCellAnchor", embed="rId4", frm=(1, 1), pic_id=4),
    _anchor("oneCellAnchor", link="rId5", frm=(3, 3), pic_id=5),
    _anchor("oneCellAnchor", embed="rId6", frm=(0, 0), pic_id=6),
    _anchor("oneCellAnchor", embed="rId1", frm=(7, 7), pic_id=7),
)

# drawing rels：绝对/相对 Target 各一；rId5=External；rId6=越界部件；rId7=悬空（无锚引用）。
_RICH_DRAWING_RELS = _rels(
    _rel("rId1", f"{_XLSX_R_NS}/image", "/xl/media/image1.png"),
    _rel("rId2", f"{_XLSX_R_NS}/image", "../media/image2.jpeg"),
    _rel("rId3", f"{_XLSX_R_NS}/image", "/xl/media/image3.png"),
    _rel("rId4", f"{_XLSX_R_NS}/image", "/xl/media/image4.emf"),
    _rel("rId5", f"{_XLSX_R_NS}/image", "https://example.com/remote.png", external=True),
    _rel("rId6", f"{_XLSX_R_NS}/image", "/xl/embeddings/note.png"),
    _rel("rId7", f"{_XLSX_R_NS}/image", "../media/ghost.png"),
)

_RICH_MEMBERS = {
    "xl/media/image1.png": b"png-one",
    "xl/media/image2.jpeg": b"jpeg-two",
    "xl/media/image3.png": b"png-three",
    "xl/media/image4.emf": b"emf-four",
    "xl/media/zzz_orphan.png": b"orphan",
    "xl/embeddings/note.png": b"outside",
}


def test_xlsx_sheet_images_maps_anchors_media_and_bytes(tmp_path):
    from deerflow_knowledge.parser import _extract_xlsx_images, _xlsx_sheet_images

    book = _build_xlsx(
        tmp_path / "rich.xlsx",
        sheet1_rels=_SHEET1_RELS,
        drawing=_RICH_DRAWING,
        drawing_rels=_RICH_DRAWING_RELS,
        members=_RICH_MEMBERS,
    )

    with zipfile.ZipFile(book) as zf:
        result = _xlsx_sheet_images(zf)

    assert set(result) == {"Sheet1"}  # Notes（无 rels）不产出；孤儿媒体不被取
    assert [(image.ref, image.content, image.media_type, row, col) for image, row, col in result["Sheet1"]] == [
        ("images/image1.png", b"png-one", "image/png", 2, 4),  # oneCell 锚 from=(col 4, row 2)
        ("images/image2.jpeg", b"jpeg-two", "image/jpeg", 5, 19),  # twoCell 取 from、不取 to
        ("images/image3.png", b"png-three", "image/png", None, None),  # absoluteAnchor 无 from
    ]
    # 白名单外的 emf、r:link 外部图、硬界外的 embeddings 部件、重复引用的 rId1 都不在清单里。

    assert _extract_xlsx_images(book) == result


def test_xlsx_sheet_images_sheet_with_only_filtered_images_is_absent(tmp_path):
    from deerflow_knowledge.parser import _xlsx_sheet_images

    book = _build_xlsx(
        tmp_path / "filtered.xlsx",
        sheet1_rels=_SHEET1_RELS,
        drawing=_drawing(
            _anchor("oneCellAnchor", embed="rId1", frm=(0, 0), pic_id=1),  # .emf 不在白名单
            _anchor("oneCellAnchor", link="rId2", frm=(1, 1), pic_id=2),  # r:link：字节不在包内
        ),
        drawing_rels=_rels(
            _rel("rId1", f"{_XLSX_R_NS}/image", "/xl/media/icon.emf"),
            _rel("rId2", f"{_XLSX_R_NS}/image", "https://example.com/remote.png", external=True),
        ),
        members={"xl/media/icon.emf": b"emf-bytes"},
    )

    with zipfile.ZipFile(book) as zf:
        assert _xlsx_sheet_images(zf) == {}


def test_xlsx_sheet_images_dedupes_same_media_keeping_first_anchor(tmp_path):
    from deerflow_knowledge.parser import _xlsx_sheet_images

    book = _build_xlsx(
        tmp_path / "dedupe.xlsx",
        sheet1_rels=_SHEET1_RELS,
        drawing=_drawing(
            _anchor("oneCellAnchor", embed="rId1", frm=(4, 2), pic_id=1),
            _anchor("oneCellAnchor", embed="rId1", frm=(7, 7), pic_id=2),
        ),
        drawing_rels=_rels(_rel("rId1", f"{_XLSX_R_NS}/image", "/xl/media/image1.png")),
        members={"xl/media/image1.png": b"png-one"},
    )

    with zipfile.ZipFile(book) as zf:
        items = _xlsx_sheet_images(zf)["Sheet1"]

    assert [(image.ref, row, col) for image, row, col in items] == [("images/image1.png", 2, 4)]


def test_xlsx_sheet_images_skips_missing_drawing_and_missing_media(tmp_path):
    from deerflow_knowledge.parser import _xlsx_sheet_images

    # sheet rels 指向包内不存在的 drawing9 → 该件跳过、不炸（其余照出）
    book = _build_xlsx(
        tmp_path / "no-drawing.xlsx",
        sheet1_rels=_rels(_rel("rId1", f"{_XLSX_R_NS}/drawing", "/xl/drawings/drawing9.xml")),
    )
    with zipfile.ZipFile(book) as zf:
        assert _xlsx_sheet_images(zf) == {}

    # drawing 在、其中一个 media 部件缺失 → 该图跳过、其余照出（件级容错）
    book = _build_xlsx(
        tmp_path / "no-media.xlsx",
        sheet1_rels=_SHEET1_RELS,
        drawing=_drawing(
            _anchor("oneCellAnchor", embed="rId1", frm=(4, 2), pic_id=1),
            _anchor("oneCellAnchor", embed="rId2", frm=(5, 5), pic_id=2),
        ),
        drawing_rels=_rels(
            _rel("rId1", f"{_XLSX_R_NS}/image", "/xl/media/image1.png"),
            _rel("rId2", f"{_XLSX_R_NS}/image", "/xl/media/missing.png"),
        ),
        members={"xl/media/image1.png": b"png-one"},
    )
    with zipfile.ZipFile(book) as zf:
        items = _xlsx_sheet_images(zf)["Sheet1"]

    assert [(image.ref, row, col) for image, row, col in items] == [("images/image1.png", 2, 4)]


def test_extract_xlsx_images_bad_zip_raises(tmp_path):
    from deerflow_knowledge.parser import _extract_xlsx_images

    p = tmp_path / "broken.xlsx"
    p.write_bytes(b"this is not a zip")

    with pytest.raises(zipfile.BadZipFile):
        _extract_xlsx_images(p)


# ── Task 2: 挂载与接线（同一 spec；D2=乙 并入规则 + 回退）──────────────────────


def _img(ref):
    return ParsedImage(ref=ref, content=b"", media_type="image/png")


def test_merge_anchor_links_merges_into_cells_keeping_text_form():
    from deerflow_knowledge.parser import _merge_anchor_links

    rows = [["Region", "Q1"], ["North", 120.0], ["South", None]]

    merged, tail = _merge_anchor_links(
        rows,
        (0, 0),
        [
            (_img("images/p1.png"), 1, 1),  # 数字格：经 _cell_to_text 写 120，不写 120.0
            (_img("images/p2.png"), 2, 1),  # 空格：仅链接
            (_img("images/p3.png"), 1, 1),  # 同格第二图：空格连接
        ],
    )

    assert merged[0] == ["Region", "Q1"]  # 未命中单元格不动
    assert merged[1][1] == "120 ![图片](images/p1.png) ![图片](images/p3.png)"
    assert merged[2][1] == "![图片](images/p2.png)"
    assert tail == []


def test_merge_anchor_links_normalizes_anchors_against_sheet_start():
    from deerflow_knowledge.parser import _merge_anchor_links

    entries = [
        (_img("images/hit.png"), 3, 2),  # abs (3,2) − start (2,1) → 矩阵 (1,1)
        (_img("images/row.png"), 9, 1),  # 越界行
        (_img("images/col.png"), 2, 9),  # 超表宽
        (_img("images/above.png"), 1, 1),  # 原点之上（行小于 start）
    ]

    merged, tail = _merge_anchor_links([["a", "b"], ["1", "2"]], (2, 1), entries)

    assert merged[1][1] == "2 ![图片](images/hit.png)"
    assert [image.ref for image in tail] == ["images/row.png", "images/col.png", "images/above.png"]


def test_merge_anchor_links_falls_back_when_unplaceable():
    from deerflow_knowledge.parser import _merge_anchor_links

    absolute = (_img("images/abs.png"), None, None)  # absoluteAnchor：无 from
    anchored = (_img("images/cell.png"), 0, 0)

    merged, tail = _merge_anchor_links([["a"]], (0, 0), [absolute, anchored])

    assert merged[0][0] == "a ![图片](images/cell.png)"
    assert [image.ref for image in tail] == ["images/abs.png"]

    merged, tail = _merge_anchor_links([["a"]], None, [anchored])  # 空 sheet start=None

    assert merged == [["a"]]
    assert [image.ref for image in tail] == ["images/cell.png"]


def test_workbook_to_markdown_trailing_images_and_image_only_sheet():
    from deerflow_knowledge.parser import _workbook_rows_to_markdown

    md = _workbook_rows_to_markdown(
        [("Data", [["a"], ["1"]]), ("Shots", [])],
        trailing_images_by_sheet={"Data": [_img("images/tail.png"), _img("images/tail2.png")], "Shots": [_img("images/bare.png")]},
    )

    assert md == "## Data\n\n| a |\n| --- |\n| 1 |\n\n![图片](images/tail.png)\n\n![图片](images/tail2.png)\n\n## Shots\n\n![图片](images/bare.png)"


@pytest.mark.asyncio
async def test_parse_excel_merges_anchor_links_and_flattens_images(tmp_path, monkeypatch):
    from deerflow_knowledge.parser import _parse_excel

    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"Sheet1": [["Region", "Q1"], ["North", 120.0]]})
    book = _build_xlsx(
        tmp_path / "anchored.xlsx",
        sheet1_rels=_SHEET1_RELS,
        drawing=_drawing(
            _anchor("oneCellAnchor", embed="rId1", frm=(1, 1), pic_id=1),  # 命中 (row 1, col 1)
            _anchor("oneCellAnchor", embed="rId2", frm=(0, 9), pic_id=2),  # 越界行 → 段尾
        ),
        drawing_rels=_rels(
            _rel("rId1", f"{_XLSX_R_NS}/image", "/xl/media/image1.png"),
            _rel("rId2", f"{_XLSX_R_NS}/image", "/xl/media/image2.png"),
        ),
        members={"xl/media/image1.png": b"png-one", "xl/media/image2.png": b"png-two"},
    )

    doc = await _parse_excel(book)

    assert doc.markdown == "## Sheet1\n\n| Region | Q1 |\n| --- | --- |\n| North | 120 ![图片](images/image1.png) |\n\n![图片](images/image2.png)"
    assert [(image.ref, image.content) for image in doc.images] == [("images/image1.png", b"png-one"), ("images/image2.png", b"png-two")]


@pytest.mark.asyncio
async def test_parse_excel_startless_sheet_appends_images_section(tmp_path, monkeypatch):
    from deerflow_knowledge.parser import _parse_excel

    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"Sheet1": []}, starts={"Sheet1": None})
    book = _build_xlsx(
        tmp_path / "image-only.xlsx",
        sheet1_rels=_SHEET1_RELS,
        drawing=_drawing(_anchor("oneCellAnchor", embed="rId1", frm=(0, 0), pic_id=1)),
        drawing_rels=_rels(_rel("rId1", f"{_XLSX_R_NS}/image", "/xl/media/image1.png")),
        members={"xl/media/image1.png": b"png-one"},
    )

    doc = await _parse_excel(book)

    assert doc.markdown == "## Sheet1\n\n![图片](images/image1.png)"
    assert [image.ref for image in doc.images] == ["images/image1.png"]


@pytest.mark.asyncio
async def test_parse_excel_broken_xlsx_falls_back_to_text_only(tmp_path, monkeypatch, caplog):
    import logging

    from deerflow_knowledge.parser import _parse_excel

    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"S": [["a"], ["1"]]})
    p = tmp_path / "broken.xlsx"
    p.write_bytes(b"not a zip at all")

    with caplog.at_level(logging.WARNING, logger="deerflow_knowledge.parser"):
        doc = await _parse_excel(p)

    assert doc.markdown == "## S\n\n| a |\n| --- |\n| 1 |"
    assert doc.images == []
    assert "failed to extract embedded images" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [zipfile.BadZipFile("bad"), ET.ParseError("bad"), KeyError("bad")])
async def test_parse_excel_image_extraction_errors_degrade_to_text(tmp_path, monkeypatch, caplog, exc):
    import logging

    from deerflow_knowledge import parser as knowledge_parser

    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"S": [["a"], ["1"]]})
    p = tmp_path / "book.xlsx"
    p.write_bytes(b"x")

    def _boom(path):
        raise exc

    monkeypatch.setattr(knowledge_parser, "_extract_xlsx_images", _boom)

    with caplog.at_level(logging.WARNING, logger="deerflow_knowledge.parser"):
        doc = await knowledge_parser._parse_excel(p)

    assert doc.markdown == "## S\n\n| a |\n| --- |\n| 1 |"
    assert doc.images == []
    assert "failed to extract embedded images" in caplog.text


@pytest.mark.asyncio
async def test_parse_excel_xls_never_reads_the_zip_leg(tmp_path, monkeypatch):
    from deerflow_knowledge import parser as knowledge_parser

    _stub_gates(monkeypatch, table=True)
    _install_fake_calamine(monkeypatch, {"S": [["a"], ["1"]]})
    calls: list = []
    monkeypatch.setattr(knowledge_parser, "_extract_xlsx_images", lambda path: calls.append(path) or {})
    p = tmp_path / "old.xls"
    p.write_bytes(b"biff-bytes")

    doc = await knowledge_parser._parse_excel(p)

    assert calls == []
    assert doc.markdown == "## S\n\n| a |\n| --- |\n| 1 |"
    assert doc.images == []


# ── Task 4: 真 .xlsx 端到端（openpyxl+PIL 造图 → calamine 读行 + zip 提取）──────


def _xlsx_imaging_available() -> bool:
    try:
        import openpyxl  # noqa: F401
        import python_calamine  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _xlsx_imaging_available(), reason="python-calamine/openpyxl/Pillow 未安装（uv sync --extra table）")
@pytest.mark.asyncio
async def test_parse_excel_real_xlsx_merges_anchored_images(tmp_path, monkeypatch):
    """真实 .xlsx 端到端（spec 2026-10-03）：命中锚（B2）的图链接并入锚点单元格
    行内、越界锚（F50）回退 `## {sheet}` 段尾、images 字节==原图。缺任一依赖 →
    skip，不阻塞回归（对齐既有真 e2e 的 skipif 纪律）。"""
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image

    _stub_gates(monkeypatch, table=True)
    hit_png = tmp_path / "hit.png"
    far_png = tmp_path / "far.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(hit_png)
    Image.new("RGB", (8, 8), (0, 0, 255)).save(far_png)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Shots"
    ws.append(["Region", "Q1"])
    ws.append(["North", 120])
    ws.add_image(XLImage(str(hit_png)), "B2")  # 命中：B2 = 数据格 120
    ws.add_image(XLImage(str(far_png)), "F50")  # 越界行 → 段尾
    book = tmp_path / "anchored.xlsx"
    wb.save(book)

    doc = await parse_document(book, client=httpx.AsyncClient(transport=_mineru_transport([])))

    assert len(doc.images) == 2
    assert doc.images[0].content == hit_png.read_bytes()  # ref 字节==原图
    assert doc.images[1].content == far_png.read_bytes()
    assert f"| North | 120 ![图片]({doc.images[0].ref}) |" in doc.markdown  # 命中图在锚点行内
    assert doc.markdown.endswith(f"\n\n![图片]({doc.images[1].ref})")  # 越界锚回退段尾


# ── caption_images()'s outcome (spec 2026-09-23 D8/R13) ────────────────────
#
# The return shape is a dataclass, not a bare mapping: the worker needs the failure count
# and the degradation verdict, and it must not compute the ratio a second time. The failure
# ratio is controlled through the image bytes, so a case is deterministic under the
# concurrent gather.


def _images(flags: str) -> list[ParsedImage]:
    """One image per character; ``F`` carries the marker the stub fails on."""
    return [ParsedImage(ref=f"images/p{i}.jpg", content=b"FAIL" if flag == "F" else b"OK", media_type="image/jpeg") for i, flag in enumerate(flags)]


def _marker_transport(recorded: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if b"RkFJTA==" in request.content:  # base64 of b"FAIL": the body carries the encoded bytes
            return httpx.Response(500, text="vlm boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": "图注"}}]})

    return httpx.MockTransport(handler)


async def _caption(monkeypatch, flags: str, *, key: str = "test-entry-key"):
    from deerflow_knowledge.captioner import caption_images

    monkeypatch.setattr("deerflow_knowledge.captioner.get_app_config", lambda: _vlm_config(with_key=bool(key)))
    recorded: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=_marker_transport(recorded))
    outcome = await caption_images(_images(flags), client=client, model="test-vlm")
    await client.aclose()
    return outcome, recorded


@pytest.mark.asyncio
async def test_captions_are_a_dataclass_with_the_counts_the_worker_needs(monkeypatch):
    import dataclasses

    outcome, recorded = await _caption(monkeypatch, "OOO")

    assert dataclasses.is_dataclass(outcome)
    assert outcome.captions == {"images/p0.jpg": "图注", "images/p1.jpg": "图注", "images/p2.jpg": "图注"}
    assert outcome.failed == 0
    assert outcome.degraded is False
    assert len(recorded) == 3


@pytest.mark.asyncio
async def test_one_failure_in_three_is_degraded(monkeypatch):
    outcome, _ = await _caption(monkeypatch, "FOO")

    assert outcome.failed == 1
    assert outcome.degraded is True
    # The failed image keeps a usable placeholder rather than an empty alt text.
    assert outcome.captions["images/p0.jpg"] == "图片 p0.jpg"


@pytest.mark.asyncio
async def test_one_failure_in_four_is_not_degraded(monkeypatch):
    outcome, _ = await _caption(monkeypatch, "FOOO")

    assert outcome.failed == 1
    assert outcome.degraded is False


@pytest.mark.asyncio
async def test_exactly_thirty_percent_is_not_degraded(monkeypatch):
    """Degradation is strictly *over* the threshold, matching the graph leg's rule."""
    outcome, _ = await _caption(monkeypatch, "FFF" + "O" * 7)

    assert outcome.failed == 3
    assert outcome.degraded is False


@pytest.mark.asyncio
async def test_a_missing_key_degrades_every_image_without_a_call(monkeypatch):
    outcome, recorded = await _caption(monkeypatch, "OOO", key="")

    assert outcome.captions == {f"images/p{i}.jpg": f"图片 p{i}.jpg" for i in range(3)}
    assert outcome.failed == 3
    assert outcome.degraded is True
    assert recorded == [], "a missing key must not reach the network"


@pytest.mark.asyncio
async def test_no_images_is_an_empty_outcome(monkeypatch):
    outcome, recorded = await _caption(monkeypatch, "")

    assert outcome.captions == {}
    assert outcome.failed == 0
    assert outcome.degraded is False
    assert recorded == []


def test_the_captioner_owns_its_threshold_constant():
    """One constant, one home: with the graph leg gone the ratio lives in ``captioner.py``.

    The pin keeps a single definition — a second copy written elsewhere would have to be
    caught by the boundary cases above (0.3 within the captioner would pass no
    count-sensitive verdict test by accident).
    """
    from pathlib import Path

    from deerflow_knowledge import captioner as captioner_module
    from deerflow_knowledge.captioner import DEGRADED_FAILURE_THRESHOLD

    assert DEGRADED_FAILURE_THRESHOLD == 0.3
    source = Path(captioner_module.__file__).read_text(encoding="utf-8")

    assert source.count("DEGRADED_FAILURE_THRESHOLD") == 2  # the definition plus its one reader
    assert source.count("0.3") == 1  # the literal appears once — inside the definition
