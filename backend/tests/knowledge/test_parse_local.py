"""Tests for the local MinerU parse provider (spec 2026-09-24, contract pinned at 4.0.7).

The local service is MinerU's own FastAPI app (``mineru-api``), driven as a **thin
client**: upload in three steps, submit one parse job, poll it, then pull the result zip
out of the service's file registry. The contract is pinned from upstream source
(``mineru/parser/api_server.py``) and cross-checked against a live 4.0.7 service
(``pr-build/mineru-4x-smoke-2026-09-24/``):

- ``POST /v1/uploads`` (JSON ``{filename, bytes, mime_type, purpose}``) → ``{id,
  status: "pending", upload_url, upload_headers}``;
- ``PUT`` that URL (raw bytes, the response's own headers) → 200, empty body;
- ``POST /v1/uploads/{id}/complete`` (no body) → ``{status: "completed", file: {id}}``;
- ``POST /v1/parse/jobs`` (``files[0].source = {type: "file_id", file_id}``,
  ``output_formats: ["zip"]``, optional ``tier``) → 202 ``{job_id, status: "queued"}``;
- ``GET /v1/parse/jobs/{id}`` → ``queued`` / ``running`` / ``completed`` / ``partial`` /
  ``failed`` / ``canceled``;
- ``GET /v1/files/{file_id}/content`` → the zip (``markdown.md`` + ``images/*``).

No request carries a credential (spec §8: the service ships without auth and belongs on an
internal network). ``sha256sum`` is deliberately never sent (D4): it is the service's
dedup shortcut, and hashing the whole file is work the thin client does not do.

The document→``failed`` half of "service unavailable" is pinned separately by
``test_worker.py::test_parse_failure_marks_failed_with_error``.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from deerflow_knowledge import parser as parser_mod
from deerflow_knowledge.embedder import RagConfigurationError
from deerflow_knowledge.parse_local import MineruLocalParseProvider
from deerflow_knowledge.parser import (
    MineruError,
    MineruParseFailedError,
    MineruTimeoutError,
    parse_document,
)

BASE_URL = "http://127.0.0.1:9999"
UPLOAD_ID = "upload_abc"
FILE_ID = "file-abc"
JOB_ID = "job_abc"
ZIP_FILE_ID = "file-zip"
PDF_BYTES = b"%PDF-1.4 fake"

#: MinerU 风格产物：正文 + 图片链接 + HTML 表（v4+vlm 的形状）+ 文末唯一标题。
_RAW_MD = "正文第一段。\n\n![](images/page_0_image_1.png)\n\n<table><tr><th>列A</th><th>列B</th></tr><tr><td>1</td><td>2</td></tr></table>\n\n结尾正文。\n\n## 页面标题"
_IMAGE = b"png-bytes"


def _zip_bytes(
    *,
    md_name: str = "markdown.md",
    markdown: str | None = _RAW_MD,
    images: tuple[tuple[str, bytes], ...] = (("images/page_0_image_1.png", _IMAGE),),
    extra: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if markdown is not None:
            archive.writestr(md_name, markdown)
        archive.writestr("middle_json.json", "{}")
        for name, content in images + extra:
            archive.writestr(name, content)
    return buffer.getvalue()


def _upload_payload(*, status: str = "pending", upload_url: str) -> dict:
    payload = {
        "id": UPLOAD_ID,
        "object": "upload",
        "bytes": len(PDF_BYTES),
        "created_at": 0,
        "expires_at": 0,
        "filename": "手册.pdf",
        "purpose": "parse",
        "mime_type": "application/pdf",
        "sha256sum": None,
        "status": status,
        "upload_url": upload_url,
        "upload_method": "PUT",
        "upload_headers": {"Content-Type": "application/pdf"},
        "file": None,
    }
    if status == "completed":
        payload["upload_url"] = None
        payload["file"] = {"id": FILE_ID, "object": "file", "bytes": len(PDF_BYTES), "created_at": 0, "expires_at": None, "filename": "手册.pdf", "purpose": "parse", "sha256sum": None}
    return payload


def _job_payload(status: str, *, error: dict | None = None, output: bool = True) -> dict:
    return {
        "job_id": JOB_ID,
        "status": status,
        "created_at": "2026-09-24T00:00:00Z",
        "started_at": "2026-09-24T00:00:00Z",
        "finished_at": None,
        "tier": "flash",
        "output_formats": ["zip"],
        "access_level": "anonymous",
        "progress": {"completed": 0, "failed": 0, "total": 1},
        "files": [
            {
                "file_id": FILE_ID,
                "name": "手册.pdf",
                "page_range": "",
                "status": status,
                "parse": None,
                "output_files": {"zip": {"file_id": ZIP_FILE_ID, "bytes": 1234}} if output else None,
                "error": error,
            }
        ],
        "links": {"self": f"/v1/parse/jobs/{JOB_ID}", "cancel": f"/v1/parse/jobs/{JOB_ID}"},
    }


class _Service:
    """A scripted 4.0.7 service: serves the six routes and records every request."""

    def __init__(
        self,
        *,
        statuses: tuple[str, ...] = ("completed",),
        error: dict | None = None,
        job_output: bool = True,
        zip_payload: bytes | None = None,
        upload_status: str = "pending",
        relative_upload_url: bool = False,
        create_status: int = 200,
        raise_at: tuple[str, str, Exception] | None = None,
    ) -> None:
        self.recorded: list[httpx.Request] = []
        self._statuses = statuses
        self._error = error
        self._job_output = job_output
        self._zip_payload = zip_payload
        self._upload_status = upload_status
        self._relative_upload_url = relative_upload_url
        self._create_status = create_status
        self._raise_at = raise_at
        self._polls = 0

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.recorded.append(request)
            path = request.url.path
            if self._raise_at is not None and (request.method, path) == self._raise_at[:2]:
                raise self._raise_at[2]
            if (request.method, path) == ("POST", "/v1/uploads"):
                if self._create_status >= 400:
                    return httpx.Response(self._create_status, json={"error": {"type": "auth_error", "code": None, "message": "missing api key", "param": None}})
                upload_url = f"{BASE_URL}/v1/uploads/{UPLOAD_ID}/content"
                if self._relative_upload_url:
                    upload_url = f"/v1/uploads/{UPLOAD_ID}/content"
                return httpx.Response(200, json=_upload_payload(status=self._upload_status, upload_url=upload_url))
            if (request.method, path) == ("PUT", f"/v1/uploads/{UPLOAD_ID}/content"):
                return httpx.Response(200)
            if (request.method, path) == ("POST", f"/v1/uploads/{UPLOAD_ID}/complete"):
                return httpx.Response(200, json=_upload_payload(status="completed", upload_url=f"{BASE_URL}/v1/uploads/{UPLOAD_ID}/content"))
            if (request.method, path) == ("POST", "/v1/parse/jobs"):
                return httpx.Response(202, json=_job_payload("queued"))
            if (request.method, path) == ("GET", f"/v1/parse/jobs/{JOB_ID}"):
                status = self._statuses[min(self._polls, len(self._statuses) - 1)]
                self._polls += 1
                return httpx.Response(200, json=_job_payload(status, error=self._error, output=self._job_output))
            if (request.method, path) == ("GET", f"/v1/files/{ZIP_FILE_ID}/content"):
                return httpx.Response(200, content=self._zip_payload if self._zip_payload is not None else _zip_bytes())
            return httpx.Response(404, json={"unexpected": f"{request.method} {path}"})

        return httpx.MockTransport(handler)

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.recorded]


def _provider(client: httpx.AsyncClient, **kwargs) -> MineruLocalParseProvider:
    kwargs.setdefault("poll_interval_seconds", 0.01)
    kwargs.setdefault("timeout_seconds", 5.0)
    return MineruLocalParseProvider(base_url=BASE_URL, client=client, **kwargs)


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "手册.pdf"
    path.write_bytes(PDF_BYTES)
    return path


def _stub_config(monkeypatch, **rag_updates) -> None:
    """Point ``parse_document``'s dispatch at a stubbed ``rag`` block."""
    real = parser_mod.get_app_config()
    stub = real.model_copy(update={"rag": real.rag.model_copy(update=rag_updates)})
    monkeypatch.setattr(parser_mod, "get_app_config", lambda: stub)


@pytest.mark.asyncio
async def test_local_parse_pins_the_4x_upload_job_poll_and_zip_sequence(tmp_path):
    """一整条链路：三步上传 → 建 job → 轮询 → 文件注册表取 zip → 归一化。"""
    service = _Service(statuses=("queued", "running", "completed"))

    async with httpx.AsyncClient(transport=service.transport()) as client:
        doc = await _provider(client).parse(_pdf(tmp_path))

    assert service.calls() == [
        ("POST", "/v1/uploads"),
        ("PUT", f"/v1/uploads/{UPLOAD_ID}/content"),
        ("POST", f"/v1/uploads/{UPLOAD_ID}/complete"),
        ("POST", "/v1/parse/jobs"),
        ("GET", f"/v1/parse/jobs/{JOB_ID}"),
        ("GET", f"/v1/parse/jobs/{JOB_ID}"),
        ("GET", f"/v1/parse/jobs/{JOB_ID}"),
        ("GET", f"/v1/files/{ZIP_FILE_ID}/content"),
    ]

    upload = service.recorded[0]
    assert json.loads(upload.content) == {
        "filename": "手册.pdf",
        "bytes": len(PDF_BYTES),
        "mime_type": "application/pdf",
        "purpose": "parse",
    }, "上传体只带这四个字段——尤其不发 sha256sum（D4）"

    assert service.recorded[1].content == PDF_BYTES, "PUT 的是原字节"
    assert service.recorded[1].headers["content-type"] == "application/pdf", "PUT 的头用服务端响应里给的那份"
    assert service.recorded[2].content == b"", "complete 不带 body（照抄官方客户端）"

    assert json.loads(service.recorded[3].content) == {
        "files": [{"source": {"type": "file_id", "file_id": FILE_ID}}],
        "output_formats": ["zip"],
    }, "未配置档位时不下发 tier（D2）"

    assert not any("authorization" in request.headers for request in service.recorded), "本地服务无鉴权（spec §8）"

    assert doc.markdown.startswith("## 页面标题"), "文末唯一标题要搬回开头（与云端同一步骤）"
    assert "<table>" not in doc.markdown and "| 列A | 列B |" in doc.markdown, "HTML 表要归一成 GFM"
    assert len(doc.images) == 1
    assert doc.images[0].ref == "images/page_0_image_1.png", "ref 必须与 markdown 里的链接逐字一致（captioner/落盘都按它匹配）"
    assert doc.images[0].content == _IMAGE
    assert doc.images[0].media_type == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["flash", "basic", "standard", "advanced"])
async def test_local_parse_sends_the_configured_tier(tmp_path, tier):
    service = _Service()

    async with httpx.AsyncClient(transport=service.transport()) as client:
        await _provider(client, tier=tier).parse(_pdf(tmp_path))

    job = next(r for r in service.recorded if r.url.path == "/v1/parse/jobs")
    body = json.loads(job.content)
    assert body["tier"] == tier
    assert set(body) == {"files", "output_formats", "tier"}, "除了 tier 不额外发别的字段"


@pytest.mark.asyncio
async def test_local_parse_picks_the_markdown_sidecar_and_only_images_prefix_entries(tmp_path):
    """zip 里认「任意 .md」+「images/ 前缀」两类条目（Task 0 定案的零改动路径）。"""
    payload = _zip_bytes(
        md_name="full.md",
        images=(("images/a.png", b"a-bytes"),),
        extra=(("stray.png", b"not-collected"),),
    )
    service = _Service(zip_payload=payload)

    async with httpx.AsyncClient(transport=service.transport()) as client:
        doc = await _provider(client).parse(_pdf(tmp_path))

    assert doc.markdown.startswith("## 页面标题")
    assert [image.ref for image in doc.images] == ["images/a.png"], "根级散图不收（只认 images/ 前缀）"
    assert doc.images[0].content == b"a-bytes"


@pytest.mark.asyncio
async def test_local_parse_job_failure_raises_parse_failed_with_the_service_message(tmp_path):
    service = _Service(
        statuses=("running", "failed"),
        error={"type": "parse_error", "code": None, "message": "文档已加密，无法解析", "param": None},
    )

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruParseFailedError, match="文档已加密"):
            await _provider(client).parse(_pdf(tmp_path))

    assert not any(path == f"/v1/files/{ZIP_FILE_ID}/content" for _, path in service.calls()), "失败 job 不再取结果"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["partial", "canceled"])
async def test_local_parse_non_completed_terminal_status_is_a_failure(tmp_path, status):
    """`partial` / `canceled` 都按失败处理（D5）；没有 per-file error 时消息带 job 状态。"""
    service = _Service(statuses=(status,))

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruParseFailedError, match=status):
            await _provider(client).parse(_pdf(tmp_path))


@pytest.mark.asyncio
async def test_local_parse_timeout_raises(tmp_path):
    service = _Service(statuses=("running",))

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruTimeoutError):
            await _provider(client, timeout_seconds=0.05).parse(_pdf(tmp_path))


@pytest.mark.asyncio
async def test_local_parse_service_unavailable_raises_mineru_error(tmp_path):
    """连不上本地服务要抛 MineruError（worker 侧 `except Exception` 据此落 failed）。"""
    service = _Service(raise_at=("POST", "/v1/uploads", httpx.ConnectError("connection refused")))

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruError) as excinfo:
            await _provider(client).parse(_pdf(tmp_path))

    assert not isinstance(excinfo.value, MineruParseFailedError), "服务不可用不是「文档解析失败」"
    assert BASE_URL in str(excinfo.value), "错误里要带上服务地址，便于就地排查"


@pytest.mark.asyncio
async def test_local_parse_missing_zip_output_fails_loud(tmp_path):
    service = _Service(job_output=False)

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruError, match="zip"):
            await _provider(client).parse(_pdf(tmp_path))


@pytest.mark.asyncio
async def test_local_parse_missing_markdown_in_the_zip_fails_loud(tmp_path):
    service = _Service(zip_payload=_zip_bytes(markdown=None))

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruError, match="markdown"):
            await _provider(client).parse(_pdf(tmp_path))


@pytest.mark.asyncio
async def test_local_parse_a_service_side_auth_error_carries_the_status(tmp_path):
    """服务端启了 `--api-key` 时本客户端会收到 401——按 HTTP 错误回报（spec §8，登记不支持）。"""
    service = _Service(create_status=401)

    async with httpx.AsyncClient(transport=service.transport()) as client:
        with pytest.raises(MineruError) as excinfo:
            await _provider(client).parse(_pdf(tmp_path))

    assert excinfo.value.status == 401


@pytest.mark.asyncio
async def test_an_already_completed_upload_short_circuits_the_put(tmp_path):
    """服务端去重命中时 create 直接返回 completed + file：不再发 PUT/complete（照抄官方客户端）。"""
    service = _Service(upload_status="completed")

    async with httpx.AsyncClient(transport=service.transport()) as client:
        await _provider(client).parse(_pdf(tmp_path))

    assert service.calls()[:2] == [("POST", "/v1/uploads"), ("POST", "/v1/parse/jobs")], "completed 的上传跳过 PUT 与 complete"


@pytest.mark.asyncio
async def test_a_relative_upload_url_is_resolved_against_the_base_url(tmp_path):
    service = _Service(relative_upload_url=True)

    async with httpx.AsyncClient(transport=service.transport()) as client:
        await _provider(client).parse(_pdf(tmp_path))

    put = next(r for r in service.recorded if r.method == "PUT")
    assert str(put.url) == f"{BASE_URL}/v1/uploads/{UPLOAD_ID}/content"


def test_an_unknown_tier_is_refused_as_a_configuration_error():
    """Defensive: `RagConfig.parse_tier` is a Literal, so configuration cannot reach this."""
    with pytest.raises(RagConfigurationError, match="parse_tier"):
        MineruLocalParseProvider(base_url="http://127.0.0.1:9999", tier="pipeline")


@pytest.mark.asyncio
async def test_parse_document_dispatches_on_parse_provider(tmp_path, monkeypatch):
    service = _Service()
    _stub_config(monkeypatch, parse_provider="mineru-local", parse_base_url=BASE_URL)

    async with httpx.AsyncClient(transport=service.transport()) as client:
        doc = await parse_document(_pdf(tmp_path), client=client, poll_interval_seconds=0.01, timeout_seconds=5.0)

    assert service.recorded[0].url.host == "127.0.0.1" and service.recorded[0].url.port == 9999, "本地 provider 要打到配置的地址"
    assert doc.markdown.startswith("## 页面标题")


@pytest.mark.asyncio
async def test_parse_document_local_without_base_url_fails_loud(tmp_path, monkeypatch):
    _stub_config(monkeypatch, parse_provider="mineru-local", parse_base_url=None)

    # `RagConfigurationError`, not a bare `ValueError`: the gateway maps exactly this type to a
    # readable 400 (spec 2026-09-17 alignment §3 D1); it stays a `ValueError` subclass, so this
    # assertion only *narrows* what the deployment promises.
    with pytest.raises(RagConfigurationError, match="parse_base_url"):
        await parse_document(_pdf(tmp_path), client=httpx.AsyncClient(transport=_Service().transport()))


@pytest.mark.asyncio
async def test_parse_document_defaults_to_the_cloud_provider(tmp_path, monkeypatch):
    """老配置（未设 provider）必须仍走云端 —— 默认行为零变化。"""
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    recorded: list[httpx.Request] = []
    # 显式钉 `parse_base_url=None`：`_stub_config` 继承真实配置，而云腿现在会读这个字段
    # （spec 2026-09-29 ①＝乙）—— 让它继承真实值会把这条守卫绑到本机环境上。
    _stub_config(monkeypatch, parse_provider="mineru-cloud", parse_base_url=None)

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(404, json={"msg": "nope"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MineruError, match="404"):
            await parse_document(_pdf(tmp_path), client=client)

    assert recorded[0].url.host == "mineru.net"


# ── 云腿请求形状：语种／档位／服务地址（spec 2026-09-29 D2）──────────────────


def _capture_transport(recorded: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(404, json={"msg": "captured"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_cloud_request_carries_the_configured_language_and_model_version(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    _stub_config(monkeypatch, parse_provider="mineru-cloud", parse_language="japan", parse_model_version="pipeline")
    recorded: list[httpx.Request] = []

    async with httpx.AsyncClient(transport=_capture_transport(recorded)) as client:
        with pytest.raises(MineruError, match="404"):
            await parse_document(_pdf(tmp_path), client=client)

    body = json.loads(recorded[0].content)
    assert body["language"] == "japan"
    assert body["model_version"] == "pipeline"
    # 顶层批参数（官方文档：per-request），不是 per-file 字段。
    assert set(body) == {"files", "language", "model_version"}
    assert set(body["files"][0]) == {"name", "data_id"}


@pytest.mark.asyncio
async def test_cloud_request_is_byte_identical_when_nothing_is_declared(tmp_path, monkeypatch):
    """负向对照（Task 0 捕获的今日基线）：不声明 ⇒ 官方主机 + `ch`/`vlm`，其余逐字节相同。"""
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    _stub_config(monkeypatch, parse_provider="mineru-cloud", parse_base_url=None)
    recorded: list[httpx.Request] = []

    async with httpx.AsyncClient(transport=_capture_transport(recorded)) as client:
        with pytest.raises(MineruError, match="404"):
            await parse_document(_pdf(tmp_path), client=client)

    assert str(recorded[0].url) == "https://mineru.net/api/v4/file-urls/batch"
    assert json.loads(recorded[0].content) == {
        "files": [{"name": "手册.pdf", "data_id": "手册"}],
        "language": "ch",
        "model_version": "vlm",
    }


@pytest.mark.asyncio
async def test_cloud_request_follows_the_configured_service_address(tmp_path, monkeypatch):
    """① 裁乙 的那条行为变化：云腿现在读 `parse_base_url` —— 这条用例就是它的牙。"""
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    _stub_config(monkeypatch, parse_provider="mineru-cloud", parse_base_url=BASE_URL)
    recorded: list[httpx.Request] = []

    async with httpx.AsyncClient(transport=_capture_transport(recorded)) as client:
        with pytest.raises(MineruError, match="404"):
            await parse_document(_pdf(tmp_path), client=client)

    assert recorded[0].url.host == "127.0.0.1"
    assert recorded[0].url.port == 9999
