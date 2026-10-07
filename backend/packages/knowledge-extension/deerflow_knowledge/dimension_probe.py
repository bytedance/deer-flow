"""Which dimensions does an embedding model accept? (spec 2026-09-26 §3 探针实现)

The answer is a *shape*, and there are three of them:

- **tiered** — the model accepts a closed set of values (DashScope's ``v3``/``v4`` family). The
  probe walks a candidate table and lists what passed.
- **range** — the model truncates whatever it is handed (Matryoshka models), so enumerating is
  meaningless and the useful facts are the native width and "the upper bound is reachable".
- **fixed** — the model ignores the parameter; there is exactly one width (its default).

One criterion holds it together: **a candidate passes only when the answer is ``200`` *and* the
returned width equals what was asked.** DashScope's own 400 text lists 1536/2048/2560 as legal
for ``qwen3.7-text-embedding-flash`` while live calls answer ``200`` and silently clamp them
back to 1024 (2026-09-27, see ``pr-build/rag-embedding-probe-2026-09-27/``) — reading the status
code instead of the vector would publish three values that cannot actually be stored.

The probe builds its own request per provider leg (the same three shapes the ingest clients
speak, mirrored here rather than reusing their constructors: this leg varies ``dimensions`` on
every call, and a constructed client fixes its width once). ``text`` and ``timeout`` are
**required arguments** on purpose — the gateway owns the single copy of those probe-family
constants and hands them down, so this module must not grow a second default.

Read-only by construction: nothing is persisted, and every failure comes back as
``DimensionProbeError`` (the endpoint renders that as "未探明", never as a 500).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from deerflow_knowledge.endpoint_url import join_endpoint

logger = logging.getLogger(__name__)

#: The deliberately odd value that classifies the model: it is not a tier any vendor publishes,
#: so a ``400`` means "closed set" and a ``200`` means "I truncate whatever you give me".
WILD_DIMENSION = 333

#: The tiers worth asking about. A closed-set model answers 400 to everything it does not carry,
#: so the list only decides which values get a chance to be discovered — it is a sampling, not a
#: boundary, and callers may extend it.
CANDIDATE_DIMENSIONS: tuple[int, ...] = (256, 512, 768, 1024, 1536, 2048, 2560, 3072, 4096)

_GENERIC = "openai-compatible"
_DASHSCOPE = "dashscope"
_ARK = "volcengine-ark"

_GENERIC_PATH = "/v1/embeddings"
_DASHSCOPE_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"
_ARK_PATH = "/api/v3/embeddings/multimodal"

ProbeType = Literal["tiered", "range", "fixed"]


class DimensionProbeError(Exception):
    """The probe could not get an answer (unreachable, refused, timed out, malformed).

    Deliberately not a per-value "unsupported" signal: this is "could not check", which the
    settings row renders as 未探明 rather than as a refusal.
    """


@dataclass(slots=True)
class DimensionProbeResult:
    """What the probe learned. ``native`` is for display and verification only — never persisted.

    ``values`` is ``[]`` for a tiered model that passed nothing (the caller shows the fallback
    copy and lets the admin type a value), ``[native]`` for range/fixed.
    """

    type: ProbeType
    native: int
    values: list[int]
    detail: str


def _url(provider: str, base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise DimensionProbeError("探测需要服务地址（embedding_base_url 为空）")
    if provider == _GENERIC:
        return join_endpoint(base, _GENERIC_PATH)
    if provider == _DASHSCOPE:
        return f"{base}{_DASHSCOPE_PATH}"
    if provider == _ARK:
        return f"{base}{_ARK_PATH}"
    raise DimensionProbeError(f"未知的嵌入 provider {provider!r}")


def _payload(provider: str, model: str, text: str, dimension: int | None) -> dict[str, Any]:
    """The three legs' bodies, mirroring their clients byte for byte apart from ``dimensions``."""
    if provider == _GENERIC:
        body: dict[str, Any] = {"model": model, "input": [text]}
        if dimension is not None:
            body["dimensions"] = dimension
        return body
    if provider == _DASHSCOPE:
        parameters: dict[str, Any] = {"output_type": "dense&sparse", "text_type": "document"}
        if dimension is not None:
            parameters["dimension"] = dimension
        return {"model": model, "input": {"texts": [text]}, "parameters": parameters}
    if provider == _ARK:
        ark: dict[str, Any] = {"model": model, "input": [{"type": "text", "text": text}], "sparse_embedding": {"type": "enabled"}}
        if dimension is not None:
            ark["dimensions"] = dimension
        return ark
    raise DimensionProbeError(f"未知的嵌入 provider {provider!r}")


def _width(provider: str, body: dict[str, Any]) -> int:
    if provider == _GENERIC:
        items = body.get("data") or []
        vector = items[0].get("embedding") if items else None
    elif provider == _DASHSCOPE:
        rows = (body.get("output") or {}).get("embeddings") or []
        vector = rows[0].get("embedding") if rows else None
    else:
        data = body.get("data")
        vector = data.get("embedding") if isinstance(data, dict) else None
    return len(vector) if isinstance(vector, list) else 0


class _Probe:
    """One probe run: the client, the leg's coordinates, and the three shared call helpers."""

    def __init__(self, *, provider: str, model: str, base_url: str, api_key: str | None, text: str, timeout: float, client: httpx.AsyncClient) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.text = text
        self.timeout = timeout
        self.client = client

    async def ask(self, dimension: int | None) -> tuple[bool, int]:
        """One real call. Returns ``(passed, width)``; anything without an answer raises."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = await self.client.post(_url(self.provider, self.base_url), headers=headers, json=_payload(self.provider, self.model, self.text, dimension), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise DimensionProbeError(f"嵌入端点不可达：{exc}") from exc
        if response.status_code in (401, 403):
            raise DimensionProbeError(f"嵌入端点拒绝了凭据（HTTP {response.status_code}）")
        if response.status_code != 200:
            return False, 0
        try:
            body = response.json()
        except ValueError as exc:
            raise DimensionProbeError("嵌入端点返回了非 JSON") from exc
        width = _width(self.provider, body)
        if width == 0:
            raise DimensionProbeError("嵌入端点返回了空向量")
        return True, width

    async def measure_native(self) -> int:
        """The width the model produces when nobody asks for one — the value ①② must measure."""
        passed, width = await self.ask(None)
        if not passed:
            raise DimensionProbeError("不带参数的那一发也被拒了（无法量出原生宽度）")
        return width

    async def classify(self) -> DimensionProbeResult:
        passed, width = await self.ask(WILD_DIMENSION)
        if passed and width == WILD_DIMENSION:
            return await self.range_type()
        if passed:
            # The parameter was accepted but ignored: this width *is* the native one.
            return DimensionProbeResult("fixed", width, [width], f"该模型不接受 dimensions 参数，固定 {width} 维")
        return await self.tiered_type()

    async def range_type(self) -> DimensionProbeResult:
        """②：量原生宽度 → 验上界。上界要不到 ⇒ 判歪，改当真 ① 跑候选表。"""
        native = await self.measure_native()
        passed, width = await self.ask(native)
        if passed and width == native:
            return DimensionProbeResult("range", native, [native], f"可接受任意 ≤ {native} 的值（上界已验）")
        logger.info("dimension probe: %r accepted %d but rejected its native %d ⇒ treating it as tiered", self.model, WILD_DIMENSION, native)
        return await self.tiered_type(native=native)

    async def tiered_type(self, *, native: int | None = None) -> DimensionProbeResult:
        """①：逐档并发探（通过 = 200 且宽度相等）→ 原生不在表里时补验一发。"""
        if native is None:
            native = await self.measure_native()
        answers = await asyncio.gather(*(self.ask(candidate) for candidate in CANDIDATE_DIMENSIONS))
        values = sorted(candidate for candidate, (passed, width) in zip(CANDIDATE_DIMENSIONS, answers, strict=True) if passed and width == candidate)
        if native not in CANDIDATE_DIMENSIONS:
            passed, width = await self.ask(native)
            if passed and width == native:
                values = sorted({*values, native})
        if values:
            detail = f"探到的有效档：{values}（原生 {native}）"
        else:
            detail = f"未探到候选档（原生 {native}）——可手填一个值，保存时会实发验证"
        return DimensionProbeResult("tiered", native, values, detail)


async def probe_dimensions(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str | None,
    text: str,
    timeout: float,
    client: httpx.AsyncClient | None = None,
) -> DimensionProbeResult:
    """Classify one embedding model and list the widths it accepts (see the module docstring).

    ``text``/``timeout`` come from the caller (the gateway passes its probe-family constants);
    ``client`` is for tests and for deployments that hand in their own transport.
    """
    close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        probe = _Probe(provider=provider, model=model, base_url=base_url, api_key=api_key, text=text, timeout=timeout, client=client)
        return await probe.classify()
    finally:
        if close_client:
            await client.aclose()
