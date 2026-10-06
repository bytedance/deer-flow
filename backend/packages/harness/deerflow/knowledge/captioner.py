"""VLM image captioning for parsed documents (spec §3.1, Task 15 dual-mode).

Each image extracted by the parser gets a Chinese caption from the DashScope
VLM (qwen3.7-flash), written back into the markdown as ``![caption](ref)`` alt text
*before* chunking, so image content becomes searchable text. The prompt is
dual-mode (Task 15): text-dense images (document screenshots, tables, code)
are transcribed in full — matching the depth standalone image uploads get from
MinerU OCR — while other images get a one-sentence summary. Captioning is an
enhancement, never a hard dependency: a VLM failure (or a missing key)
degrades that image to a filename placeholder without aborting the document.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from deerflow.config.app_config import get_app_config
from deerflow.knowledge.caption_client import _CAPTION_CONCURRENCY, request_caption
from deerflow.knowledge.graph.indexer import DEGRADED_FAILURE_THRESHOLD
from deerflow.knowledge.parser import ParsedImage
from deerflow.knowledge.vlm_target import VlmTarget, resolve_vlm_target

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CaptionOutcome:
    """What one document's image pass produced (spec 2026-09-23 D8/R13).

    Same family as the video leg's outcome: the captions themselves plus the verdict the
    worker records. The verdict is computed here — against the graph leg's own threshold
    constant — so the worker reads it instead of recomputing a ratio of its own.
    """

    captions: dict[str, str] = field(default_factory=dict)
    failed: int = 0
    degraded: bool = False


_CAPTION_PROMPT = "请分析这张图片，用于文档检索索引：如果图片以文字内容为主（如文档截图、表格、代码），请完整转录图中的全部文字；否则请用一句简洁的中文描述图片的主要内容（对象、场景、关键文字）。只输出转录或描述文本，不要多余解释。"

_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def _placeholder(ref: str) -> str:
    return f"图片 {Path(ref).name}"


async def _caption_one(client: httpx.AsyncClient, image: ParsedImage, *, target: VlmTarget, max_tokens: int, temperature: float, thinking: bool = False) -> str:
    return await request_caption(client, target=target, prompt=_CAPTION_PROMPT, images=[(image.content, image.media_type)], max_tokens=max_tokens, temperature=temperature, thinking=thinking)


async def caption_images(
    images: Sequence[ParsedImage],
    *,
    client: httpx.AsyncClient | None = None,
    model: str | None = None,
) -> CaptionOutcome:
    """Caption every image with concurrent calls; failures degrade to filename placeholders.

    The target (model id, endpoint, key) is resolved by :func:`resolve_vlm_target` — naming
    a configured ``models:`` entry supplies all three. A missing key degrades every image to
    its placeholder without any outbound call. *model* overrides ``rag.vlm_model``. Uses
    asyncio.gather with the shared ``_CAPTION_CONCURRENCY`` cap for concurrency control;
    results are returned in input
    list order to protect Markdown image position mapping.

    The verdict travels with the data (spec 2026-09-23 D8/R13): the failure count and the
    degradation flag are computed here, against the same threshold the graph leg uses, so the
    worker never recomputes a ratio of its own.
    """
    if not images:
        return CaptionOutcome()

    cfg = get_app_config()
    target = resolve_vlm_target(cfg, model)
    api_key = target.api_key
    max_tokens = cfg.rag.caption_max_tokens
    temperature = cfg.rag.caption_temperature
    total = len(images)

    if not api_key:
        logger.warning("the caption target %r carries no API key; degrading %d image(s) to filename placeholders", target.model, total)
        return CaptionOutcome(captions={image.ref: _placeholder(image.ref) for image in images}, failed=total, degraded=True)

    own_client = client is None
    # Task 16: timeout raised to 180s for long-form transcription
    timeout = httpx.Timeout(cfg.rag.vlm_timeout or 180.0, connect=cfg.rag.vlm_connect_timeout or 15.0)
    http = client or httpx.AsyncClient(timeout=timeout)

    # Task 16: concurrent execution with semaphore-limited parallelism
    captions: dict[str, str] = {}
    failed = 0
    semaphore = asyncio.Semaphore(_CAPTION_CONCURRENCY)  # one cap, both legs (spec 2026-10-03 D1=甲)

    async def caption_with_semaphore(img: ParsedImage) -> tuple[str, str]:
        nonlocal failed
        async with semaphore:
            try:
                result = await _caption_one(http, img, target=target, max_tokens=max_tokens, temperature=temperature, thinking=bool(cfg.rag.vlm_thinking))
                return img.ref, result
            except Exception as exc:
                logger.warning("VLM caption failed for %s (%s); using filename placeholder", img.ref, exc)
                failed += 1
                return img.ref, _placeholder(img.ref)

    try:
        # Run all captions concurrently and preserve original list order
        tasks = [caption_with_semaphore(img) for img in images]
        results = await asyncio.gather(*tasks)
        # zip ensures results follow input list order, never mixed up
        captions.update(results)
    finally:
        if own_client:
            await http.aclose()
    return CaptionOutcome(captions=captions, failed=failed, degraded=(failed / total) > DEGRADED_FAILURE_THRESHOLD)


def _sanitize_caption(text: str) -> str:
    r"""Make one caption safe for the single GFM line it lands on (spec 2026-10-03 §2.4).

    The caption is rewritten into ``![caption](ref)`` alt text, which can now sit inside
    a table row (workbook anchors, D2=乙): a newline would cut the row short — the chunker
    stops collecting the table there — and a raw ``|`` would split the column, while
    ``[``/``]`` would break the image syntax itself. Backslashes are doubled *first* so
    the escapes inserted here render literally instead of being re-escaped.
    """
    text = text.replace("\\", "\\\\")
    text = re.sub(r"\r\n?|\n", " ", text)
    for char in "|[]":
        text = text.replace(char, f"\\{char}")
    return text


def apply_captions(markdown: str, captions: Mapping[str, str]) -> str:
    """Rewrite ``![alt](ref)`` alt text with captions for known refs.

    Captions are sanitized before they land (see ``_sanitize_caption``): single line,
    with ``|``/``[``/``]`` escaped, so a caption cannot break a GFM row it sits in.
    """

    def _sub(match: re.Match[str]) -> str:
        ref = match.group(1)
        caption = captions.get(ref)
        if caption is None:
            return match.group(0)
        return f"![{_sanitize_caption(caption)}]({ref})"

    return _IMAGE_REF_RE.sub(_sub, markdown)
