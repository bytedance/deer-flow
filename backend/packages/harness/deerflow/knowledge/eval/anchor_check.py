"""Write-path anchor verification for golden questions (spec 2026-10-05 §2/§4).

机械门禁：参考答案术语（``sparse._tokenize`` 分词集合交）与锚定切片正文比对，
零 LLM、零新依赖。机器的定位 = 要求人看一眼，不否决人：术语级拦截可带一次性
确认标记（``anchor_ack``）放行；锚失效（片不存在）不给绕过——确认了数据也是
坏数据。两条豁免：无参考答案免术语核验（锚存在性照跑）、多片题只拦单片零命中。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from deerflow.knowledge.eval.dataset import GoldenDatasetError
from deerflow.knowledge.sparse import _tokenize

REASON_OK = "ok"
REASON_SKIPPED = "skipped"
REASON_MISMATCH = "mismatch"
REASON_ZERO_HIT = "zero_hit"
REASON_MISSING = "missing_chunk"

ChunkFetch = Callable[[Sequence[str]], Awaitable[Mapping[str, str]]]
AnchorGuard = Callable[[Sequence[str], str | None, bool], Awaitable[None]]


@dataclass(frozen=True)
class AnchorVerdict:
    """机器判定结果；``detail`` 即拦截响应回显的结构化明细（spec §4）。
    ``chunk_ids`` 是被疑的锚（读时「存疑」徽章的疑片集，spec §2④）——
    属内部标注、**不进 detail**（五键 wire 契约不变）。"""

    reason: str
    miss_terms: tuple[str, ...] = ()
    hits: int = 0
    best_hits: int = 0
    suggested_chunk: str | None = None
    chunk_ids: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.reason in (REASON_MISMATCH, REASON_ZERO_HIT, REASON_MISSING)

    @property
    def detail(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "miss_terms": list(self.miss_terms),
            "hits": self.hits,
            "best_hits": self.best_hits,
            "suggested_chunk": self.suggested_chunk,
        }


class AnchorMismatchError(GoldenDatasetError):
    """锚定核验拦截；``detail`` 是结构化机器依据，独立于 schema 校验的字符串 detail。"""

    def __init__(self, verdict: AnchorVerdict):
        self.verdict = verdict
        self.detail = verdict.detail
        super().__init__(f"anchor check {verdict.reason}: hits={verdict.hits} best_hits={verdict.best_hits}")


def _doc_of(chunk_id: str) -> str:
    return chunk_id.rsplit("#", 1)[0]


def check_anchor(
    *,
    reference_answer: str | None,
    anchor_chunk_ids: Sequence[str],
    chunk_texts: Mapping[str, str],
) -> AnchorVerdict:
    """纯判定（spec §2 五步）：术语集 K → 锚内命中 h → 同文档最佳 B → 判定。``chunk_texts``
    须覆盖全部锚定片及其同文档切片；锚缺位 ⇒ ``missing_chunk``（豁免只免术语核验）。"""
    anchors = list(anchor_chunk_ids)
    if not anchors:
        return AnchorVerdict(REASON_OK)
    if any(chunk_id not in chunk_texts for chunk_id in anchors):
        return AnchorVerdict(REASON_MISSING)

    terms = set(_tokenize(reference_answer or ""))
    if not terms:
        return AnchorVerdict(REASON_SKIPPED)

    def _hits_of(chunk_id: str) -> int:
        return len(terms & set(_tokenize(chunk_texts[chunk_id])))

    hits_by_chunk = {chunk_id: _hits_of(chunk_id) for chunk_id in anchors}

    def _best_for(anchor: str) -> tuple[str, int]:
        doc = _doc_of(anchor)
        best_id, best_hits = anchor, hits_by_chunk[anchor]
        for chunk_id in sorted(chunk_texts):
            if _doc_of(chunk_id) != doc:
                continue
            hits = _hits_of(chunk_id)
            if hits > best_hits:
                best_id, best_hits = chunk_id, hits
        return best_id, best_hits

    def _verdict_for(anchor: str, *, hits: int, reason: str, suspects: Sequence[str] | None = None) -> AnchorVerdict:
        best_id, best_hits = _best_for(anchor)
        miss_terms = tuple(sorted(terms - set(_tokenize(chunk_texts[anchor]))))
        return AnchorVerdict(
            reason,
            miss_terms=miss_terms,
            hits=hits,
            best_hits=best_hits,
            suggested_chunk=best_id if best_id != anchor else None,
            chunk_ids=tuple(suspects) if suspects is not None else (anchor,),
        )

    if len(anchors) == 1:
        anchor = anchors[0]
        hits = hits_by_chunk[anchor]
        if hits == 0:
            return _verdict_for(anchor, hits=0, reason=REASON_ZERO_HIT)
        best_id, best_hits = _best_for(anchor)
        if best_hits - hits >= 2:
            return _verdict_for(anchor, hits=hits, reason=REASON_MISMATCH)
        return AnchorVerdict(REASON_OK, hits=hits, best_hits=best_hits)

    zero_chunks = [chunk_id for chunk_id in anchors if hits_by_chunk[chunk_id] == 0]
    if zero_chunks:
        return _verdict_for(zero_chunks[0], hits=0, reason=REASON_ZERO_HIT, suspects=tuple(zero_chunks))
    return AnchorVerdict(REASON_OK)


def guard_from_fetch(fetch: ChunkFetch) -> AnchorGuard:
    """包一层拦截策略：术语级拦截看 ``ack``；锚失效无条件拦。"""

    async def guard(chunk_ids: Sequence[str], reference_answer: str | None, ack: bool) -> None:
        texts = await fetch(list(chunk_ids))
        verdict = check_anchor(reference_answer=reference_answer, anchor_chunk_ids=chunk_ids, chunk_texts=texts)
        if verdict.reason == REASON_MISSING:
            raise AnchorMismatchError(verdict)
        if verdict.blocked and not ack:
            raise AnchorMismatchError(verdict)

    return guard


async def store_fetch(store: Any, kb_id: str, chunk_ids: Sequence[str], *, known: Mapping[str, str] | None = None) -> dict[str, str]:
    """锚定片正文 + 同文档切片（找对照 B 用）；``known`` 传入已取到的锚文本免二次查。"""
    texts = dict(known or {})
    missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in texts]
    if missing:
        rows = await store.get_chunks_by_ids(missing, kb_id=kb_id)
        texts.update({row["chunk_id"]: row.get("text") or "" for row in rows})
    for doc_id in sorted({_doc_of(chunk_id) for chunk_id in chunk_ids}):
        offset = 0
        while True:
            page = await store.list_chunks(doc_id, offset=offset)
            for row in page:
                texts.setdefault(row["chunk_id"], row.get("text") or "")
            if len(page) < 50:
                break
            offset += 50
    return texts


def build_anchor_guard(store: Any, kb_id: str, *, anchor_texts: Mapping[str, str] | None = None) -> AnchorGuard:
    """服务层注入形状：默认关的 ``add_question`` guard 参数由两个真实写口传它。"""

    async def fetch(chunk_ids: Sequence[str]) -> Mapping[str, str]:
        return await store_fetch(store, kb_id, chunk_ids, known=anchor_texts)

    return guard_from_fetch(fetch)
