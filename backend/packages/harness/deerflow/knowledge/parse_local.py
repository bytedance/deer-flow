"""Local MinerU service client (spec 2026-09-24, contract pinned at upstream 4.0.7).

The local service is MinerU's own FastAPI app (``mineru-api``), driven as a **thin
client** (D2-A): we upload the file, submit one parse job and poll it, while the engine
choice and every model-management concern stay on the service side. The contract is pinned
from upstream source (``mineru/parser/api_server.py``; the call sequence mirrors the
official client ``mineru/parser/api_client.py``):

1. ``POST /v1/uploads`` declares the file (JSON, no ``sha256sum`` — D4) and answers with
   ``{id, status, upload_url, upload_headers}``;
2. ``PUT`` that URL with the raw bytes and the response's own ``upload_headers``;
3. ``POST /v1/uploads/{id}/complete`` turns the upload into a File object;
4. ``POST /v1/parse/jobs`` with ``files[0].source = {type: "file_id", file_id}``,
   ``output_formats: ["zip"]`` and — when configured — ``tier``;
5. ``GET /v1/parse/jobs/{id}`` until a terminal status
   (``completed`` / ``partial`` / ``failed`` / ``canceled``);
6. ``GET /v1/files/{zip_file_id}/content`` → the zip, unpacked by the cloud leg's own
   ``_unpack_zip`` (``markdown.md`` + ``images/*``; Task 0 pinned that the sidecar prefix
   and the markdown links agree, so nothing here rescales the refs).

``tier`` is the only per-request quality knob left in 4.x: the old ``backend``
(``vlm`` / ``hybrid``) became a *service startup* flag, so this client does not translate
it (D2). The tier rules themselves belong to the service — an unavailable tier comes back
as the service's own 4xx/5xx, which we report verbatim rather than mirror (D8).

The service ships without authentication (spec §8.2) — it belongs on an internal network,
so no token is ever sent. Failures reuse the parser's error taxonomy so the worker's
degradation contract stays identical across providers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.messages import bilingual
from deerflow.knowledge.parser import (
    MineruError,
    MineruParseFailedError,
    MineruTimeoutError,
    ParsedDocument,
    _unpack_zip,
    normalize_mineru_markdown,
)

logger = logging.getLogger(__name__)

#: The 4.x service tiers. Configuration is a Literal, so this check is defensive only —
#: same posture as the retired ``backend`` check it replaces.
_TIERS = ("flash", "basic", "standard", "advanced")
#: Non-terminal job statuses (upstream: queued / running).
_PENDING_STATUSES = frozenset({"queued", "running"})
#: Terminal statuses other than ``completed`` (D5): a partial job is a failed one here,
#: because our jobs carry exactly one file.
_FAILED_STATUSES = frozenset({"partial", "failed", "canceled"})
#: Suffix → MIME for the upload declaration (D4), mirroring the extensions the service
#: declares parseable. Anything else declares ``application/octet-stream``.
_MIME_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "epub": "application/epub+zip",
    "ofd": "application/ofd",
    "html": "text/html",
    "htm": "text/html",
    "mhtml": "multipart/related",
    "mht": "multipart/related",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "txt": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
}


def _check_http(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise MineruError(f"本地 MinerU HTTP {response.status_code}: {response.text[:200]}", status=response.status_code)


def _json_object(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise MineruError(f"本地 MinerU 返回了非 JSON 响应：{response.text[:200]}") from exc
    if not isinstance(payload, dict):
        raise MineruError(f"本地 MinerU 返回了非对象 JSON：{payload!r}")
    return payload


def _mime_type(path: Path) -> str:
    return _MIME_TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")


def _failure_message(payload: dict, job_id: str) -> str:
    """The service's own words when the file carries them; the job status otherwise."""
    files = payload.get("files") or []
    entry = files[0] if files and isinstance(files[0], dict) else {}
    error = entry.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str) and error:
        return error
    return f"本地 MinerU 解析未完成（job {job_id}，状态 {payload.get('status')}）"


class MineruLocalParseProvider:
    """``ParseProvider`` for a self-hosted MinerU 4.x service (upload + job + poll + zip)."""

    def __init__(
        self,
        *,
        base_url: str | None,
        tier: str | None = None,
        client: httpx.AsyncClient | None = None,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
    ) -> None:
        if not (base_url or "").strip():
            raise RagConfigurationError(bilingual("本地解析需要服务地址：请设置 rag.parse_base_url（parse_provider=mineru-local）", "Local parsing needs a service address: set rag.parse_base_url (parse_provider=mineru-local)"))
        if tier is not None and tier not in _TIERS:
            raise RagConfigurationError(bilingual(f"未知的 parse_tier {tier!r}；可选 {list(_TIERS)}", f"Unknown parse_tier {tier!r}; expected one of {list(_TIERS)}"))
        self._base_url = base_url.strip().rstrip("/")
        # 空 = 由服务端决定（D2）：不下发 tier 字段。注意 flash-only 服务端没有默认质量档，
        # 空档位会被它 503 拒（服务端事实，不镜像——D8），那种部署要显式给档。
        self._tier = tier
        self._client = client
        self._poll_interval_seconds = poll_interval_seconds
        self._timeout_seconds = timeout_seconds

    async def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        own_client = self._client is None
        http = self._client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0))
        try:
            file_id = await self._upload(http, path)
            job_id = await self._submit(http, file_id)
            payload = await self._await_terminal(http, job_id)
            parsed = _unpack_zip(await self._download_zip(http, payload))
            return ParsedDocument(markdown=normalize_mineru_markdown(parsed.markdown), images=parsed.images)
        finally:
            if own_client:
                await http.aclose()

    async def _send(self, http: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
        """One call to the local service: transport failures become ``MineruError``."""
        try:
            response = await http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise MineruError(f"本地 MinerU 服务不可达（{url}）：{exc}") from exc
        _check_http(response)
        return response

    async def _request(self, http: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
        return _json_object(await self._send(http, method, url, **kwargs))

    async def _upload(self, http: httpx.AsyncClient, path: Path) -> str:
        """The three-step upload (D4): declare → PUT bytes → complete. Returns the File id."""
        payload = await self._request(
            http,
            "POST",
            f"{self._base_url}/v1/uploads",
            json={"filename": path.name, "bytes": path.stat().st_size, "mime_type": _mime_type(path), "purpose": "parse"},
        )
        upload_id = payload.get("id")
        if not upload_id:
            raise MineruError(f"本地 MinerU 未返回 upload id：{payload!r}")
        # 服务端里已有同 sha256 的文件时 create 直接是终态，没有 PUT/complete 可走
        # （照抄官方客户端；我们不发 sha256sum ⇒ 一般命不中，但这分支照抄更稳）
        if payload.get("status") == "completed":
            return self._file_id(payload)
        upload_url = payload.get("upload_url")
        if not upload_url:
            raise MineruError(f"本地 MinerU 未返回 upload_url：{payload!r}")
        if upload_url.startswith("/"):  # 相对地址按 base_url 解析（照抄官方客户端）
            upload_url = f"{self._base_url}{upload_url}"
        await self._send(
            http,
            "PUT",
            upload_url,
            headers=payload.get("upload_headers") or {},
            content=path.read_bytes(),
        )
        return self._file_id(await self._request(http, "POST", f"{self._base_url}/v1/uploads/{upload_id}/complete"))

    @staticmethod
    def _file_id(payload: dict) -> str:
        file_id = (payload.get("file") or {}).get("id")
        if not file_id:
            raise MineruError(f"本地 MinerU 未返回 file id：{payload!r}")
        return str(file_id)

    async def _submit(self, http: httpx.AsyncClient, file_id: str) -> str:
        body: dict = {"files": [{"source": {"type": "file_id", "file_id": file_id}}], "output_formats": ["zip"]}
        if self._tier is not None:
            body["tier"] = self._tier
        payload = await self._request(http, "POST", f"{self._base_url}/v1/parse/jobs", json=body)
        job_id = payload.get("job_id")
        if not job_id:
            raise MineruError(f"本地 MinerU 未返回 job_id：{payload!r}")
        return str(job_id)

    async def _await_terminal(self, http: httpx.AsyncClient, job_id: str) -> dict:
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            payload = await self._request(http, "GET", f"{self._base_url}/v1/parse/jobs/{job_id}")
            status = payload.get("status")
            if status == "completed":
                return payload
            if status in _FAILED_STATUSES:
                raise MineruParseFailedError(_failure_message(payload, job_id))
            if status not in _PENDING_STATUSES:
                logger.warning("Unknown local MinerU job status %r; continuing to poll", status)
            if time.monotonic() >= deadline:
                raise MineruTimeoutError(f"本地 MinerU 解析超时（{self._timeout_seconds:.0f}s，job {job_id}）")
            await asyncio.sleep(self._poll_interval_seconds)

    async def _download_zip(self, http: httpx.AsyncClient, payload: dict) -> bytes:
        files = payload.get("files") or []
        entry = files[0] if files and isinstance(files[0], dict) else {}
        output_files = entry.get("output_files") or {}
        zip_file_id = (output_files.get("zip") or {}).get("file_id")
        if not zip_file_id:
            raise MineruError(f"本地 MinerU 结果里没有 zip 输出（job {payload.get('job_id')}）：{output_files!r}")
        return (await self._send(http, "GET", f"{self._base_url}/v1/files/{zip_file_id}/content")).content
