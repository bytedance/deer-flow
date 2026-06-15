"""L2 召回评测主入口 —— 真实 embedding + 标注集 + IR 指标。

跑这个脚本会:

1. 用 ``recall-l2-eval`` 隔离租户 + 临时 chroma 目录,不污染真实数据
2. 读 ``dataset/corpus/*.md``,按 ``<!-- anchor: name -->`` 切分成
   ``{file}#{anchor}`` 段,逐段调 ``DocumentIngestor.ingest_text`` 索引
   到 ``recall_l2_eval_corpus`` collection
3. 读 ``dataset/queries.jsonl``,逐条调 ``DocumentRetriever.retrieve``
   拿排序结果,根据 ``metadata["doc_id"]`` 计算 ``Recall@K`` /
   ``MRR`` / ``nDCG``
4. 写报告到 ``reports/run-{timestamp}.json``;若 ``reports/baseline.json``
   存在,任何指标下降 > 5% 退出码非 0,并打印高亮 diff

为什么是 L2 不是 L1:这里跑的是 ``config.yaml`` 里配置的真实 embedding
模型(默认 ``openai:text-embedding-v4`` 走代理),measure 的是检索质
量。L1 用 ``ControlledEmbedder`` 把目标向量锚到查询,Recall@K 恒为
100%,只能验证管道工程正确性。

CLI:

    python tests/recall_l2/eval_recall.py
    python tests/recall_l2/eval_recall.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 让脚本在不依赖 pytest 的情况下可以从 backend/ 直接运行。
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
_HARNESS_ROOT = _BACKEND_ROOT / "packages" / "harness"
if str(_HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(_HARNESS_ROOT))

from deerflow.config.app_config import AppConfig  # noqa: E402
from deerflow.config.rag_config import RagConfig, get_rag_config, set_rag_config  # noqa: E402
from deerflow.config.tenant import set_current_tenant_id  # noqa: E402
from deerflow.evaluation.metrics import (  # noqa: E402
    calculate_mrr,
    calculate_ndcg,
    calculate_recall_at_k,
)
from deerflow.rag.ingestion import DocumentIngestor  # noqa: E402
from deerflow.rag.retrieval import DocumentRetriever  # noqa: E402

logger = logging.getLogger("recall_l2")

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
CORPUS_DIR = DATASET_DIR / "corpus"
QUERIES_FILE = DATASET_DIR / "queries.jsonl"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
BASELINE_FILE = REPORTS_DIR / "baseline.json"
COLLECTION_NAME = "recall_l2_eval_corpus"
TENANT_ID = "recall-l2-eval"
TOP_K = 20
REPORT_KS = (1, 3, 5, 10)
REGRESSION_THRESHOLD = 0.05  # 5% 下降即视为回归


@dataclass
class QueryCase:
    qid: str
    query: str
    relevant_doc_ids: list[str]
    notes: str = ""


@dataclass
class PerQueryResult:
    qid: str
    query: str
    relevant_doc_ids: list[str]
    retrieved_doc_ids: list[str] = field(default_factory=list)
    retrieved_scores: list[float] = field(default_factory=list)
    hit_positions: list[int] = field(default_factory=list)  # 0-indexed
    top1_score: float | None = None
    notes: str = ""


@dataclass
class Aggregate:
    recall_at_k: dict[int, float]
    mrr: float
    ndcg_at_10: float
    judged_query_count: int
    negative_query_count: int


# ---------- corpus 解析 ----------


def parse_anchored_markdown(path: Path) -> list[tuple[str, str]]:
    """把单个 markdown 文件切分成 ``[(anchor, text)]``。

    规则:遇到 ``<!-- anchor: NAME -->`` 行作为分段开始,该行之前的
    文本(通常是文档前言)被丢弃 —— 我们只索引 anchor 标记过的内容,
    确保 chunk metadata 里都有合法 ``doc_id``。
    """
    text = path.read_text(encoding="utf-8")
    sections: list[tuple[str, list[str]]] = []
    current_anchor: str | None = None
    current_lines: list[str] = []

    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("<!-- anchor:") and stripped.endswith("-->"):
            if current_anchor is not None:
                sections.append((current_anchor, current_lines))
            current_anchor = stripped[len("<!-- anchor:") : -len("-->")].strip()
            current_lines = []
        else:
            if current_anchor is not None:
                current_lines.append(raw)

    if current_anchor is not None:
        sections.append((current_anchor, current_lines))

    return [(anchor, "\n".join(lines).strip()) for anchor, lines in sections if "".join(lines).strip()]


def load_corpus(corpus_dir: Path) -> list[tuple[str, str, str]]:
    """返回 ``[(file_name, anchor, text)]``,按文件名 + anchor 字典序稳定排序。"""
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"corpus 目录不存在: {corpus_dir}")
    out: list[tuple[str, str, str]] = []
    for md_file in sorted(corpus_dir.glob("*.md")):
        for anchor, body in parse_anchored_markdown(md_file):
            out.append((md_file.name, anchor, body))
    if not out:
        raise RuntimeError(f"corpus 目录里没找到带 anchor 的 markdown 段: {corpus_dir}")
    return out


def load_queries(queries_file: Path) -> list[QueryCase]:
    if not queries_file.is_file():
        raise FileNotFoundError(f"queries 文件不存在: {queries_file}")
    out: list[QueryCase] = []
    for line_no, raw in enumerate(queries_file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"queries.jsonl 第 {line_no} 行不是合法 JSON: {e}") from e
        out.append(
            QueryCase(
                qid=obj["qid"],
                query=obj["query"],
                relevant_doc_ids=list(obj.get("relevant_doc_ids", [])),
                notes=obj.get("notes", ""),
            )
        )
    if not out:
        raise RuntimeError(f"queries.jsonl 是空的: {queries_file}")
    return out


# ---------- 索引 + 检索 ----------


def index_corpus(sections: list[tuple[str, str, str]]) -> int:
    """把 corpus 写入向量库,返回总 chunk 数。

    ``DocumentIngestor`` 默认从 ``RagConfig`` 拉 embedder + chroma_persist_dir
    + chunk 策略,我们已经在外面设置好了。
    """
    ingestor = DocumentIngestor()
    total_chunks = 0
    for file_name, anchor, body in sections:
        doc_id = f"{file_name}#{anchor}"
        result = ingestor.ingest_text(
            text=body,
            source_name=file_name,
            collection=COLLECTION_NAME,
            metadata={"source_file": file_name, "anchor": anchor, "doc_id": doc_id},
        )
        if result.error:
            raise RuntimeError(f"索引 {doc_id} 失败: {result.error}")
        total_chunks += result.chunk_count
        logger.info("indexed %s -> %d chunks", doc_id, result.chunk_count)
    return total_chunks


def run_query(retriever: DocumentRetriever, case: QueryCase, top_k: int) -> PerQueryResult:
    """执行一条 query,把 chunk-level 排序去重成 doc_id-level 排序。"""
    raw = retriever.retrieve(query=case.query, collection=COLLECTION_NAME, top_k=top_k)

    seen: OrderedDict[str, float] = OrderedDict()
    for r in raw.results:
        doc_id = r.metadata.get("doc_id")
        if not doc_id:
            continue
        # 同一 doc_id 多 chunk 命中只保留得分最高的那个
        if doc_id not in seen or r.score > seen[doc_id]:
            seen[doc_id] = r.score

    retrieved = list(seen.keys())
    scores = [seen[d] for d in retrieved]
    relevant = set(case.relevant_doc_ids)
    hit_positions = [i for i, d in enumerate(retrieved) if d in relevant]

    return PerQueryResult(
        qid=case.qid,
        query=case.query,
        relevant_doc_ids=case.relevant_doc_ids,
        retrieved_doc_ids=retrieved,
        retrieved_scores=scores,
        hit_positions=hit_positions,
        top1_score=(scores[0] if scores else None),
        notes=case.notes,
    )


# ---------- 指标 ----------


def _build_id_map(per_query: list[PerQueryResult]) -> dict[str, int]:
    """把字符串 doc_id 映射为稳定整数,供 metrics.py 使用。"""
    seen: list[str] = []
    seen_set: set[str] = set()
    for q in per_query:
        for d in q.retrieved_doc_ids:
            if d not in seen_set:
                seen.append(d)
                seen_set.add(d)
        for d in q.relevant_doc_ids:
            if d not in seen_set:
                seen.append(d)
                seen_set.add(d)
    return {d: i for i, d in enumerate(seen)}


def aggregate_metrics(per_query: list[PerQueryResult]) -> Aggregate:
    judged = [q for q in per_query if q.relevant_doc_ids]
    if not judged:
        return Aggregate(
            recall_at_k={k: 0.0 for k in REPORT_KS},
            mrr=0.0,
            ndcg_at_10=0.0,
            judged_query_count=0,
            negative_query_count=len(per_query),
        )

    id_map = _build_id_map(judged)
    ranked_ids: list[list[int]] = []
    relevant_sets: list[set[int]] = []
    relevance_lists: list[list[int]] = []  # 0/1 标签序列,供 MRR / nDCG 用
    ideal_lists: list[list[int]] = []

    for q in judged:
        ranked_ids.append([id_map[d] for d in q.retrieved_doc_ids])
        relevant_sets.append({id_map[d] for d in q.relevant_doc_ids})
        labels = [1 if d in set(q.relevant_doc_ids) else 0 for d in q.retrieved_doc_ids]
        relevance_lists.append(labels)
        ideal_lists.append(sorted(labels, reverse=True))

    recall_map = {k: calculate_recall_at_k(ranked_ids, relevant_sets, k=k) for k in REPORT_KS}
    mrr = calculate_mrr(relevance_lists)
    ndcg10 = calculate_ndcg(
        [labels[:10] for labels in relevance_lists],
        [labels[:10] for labels in ideal_lists],
    )

    return Aggregate(
        recall_at_k=recall_map,
        mrr=mrr,
        ndcg_at_10=ndcg10,
        judged_query_count=len(judged),
        negative_query_count=len(per_query) - len(judged),
    )


# ---------- 报告 ----------


def build_report(
    *,
    aggregate: Aggregate,
    per_query: list[PerQueryResult],
    rag_config: RagConfig,
    started_at: datetime,
    duration_ms: int,
    corpus_section_count: int,
    indexed_chunk_count: int,
) -> dict[str, Any]:
    return {
        "metadata": {
            "started_at": started_at.isoformat(),
            "duration_ms": duration_ms,
            "embedding_model": rag_config.embedding_model,
            "embedding_base_url": rag_config.embedding_base_url or None,
            "vector_backend": rag_config.vector_store_backend,
            "chunk_size": rag_config.chunk_size,
            "chunk_overlap": rag_config.chunk_overlap,
            "chunk_strategy": rag_config.chunk_strategy,
            "top_k": TOP_K,
            "corpus_section_count": corpus_section_count,
            "indexed_chunk_count": indexed_chunk_count,
            "query_count": len(per_query),
        },
        "aggregate": {
            "recall_at_k": {str(k): v for k, v in aggregate.recall_at_k.items()},
            "mrr": aggregate.mrr,
            "ndcg_at_10": aggregate.ndcg_at_10,
            "judged_query_count": aggregate.judged_query_count,
            "negative_query_count": aggregate.negative_query_count,
        },
        "per_query": [
            {
                "qid": q.qid,
                "query": q.query,
                "relevant_doc_ids": q.relevant_doc_ids,
                "retrieved_doc_ids": q.retrieved_doc_ids[:TOP_K],
                "retrieved_scores": [round(s, 4) for s in q.retrieved_scores[:TOP_K]],
                "hit_positions": q.hit_positions,
                "top1_score": q.top1_score,
                "notes": q.notes,
            }
            for q in per_query
        ],
    }


def diff_against_baseline(report: dict[str, Any], baseline_path: Path) -> list[str]:
    """返回回归项的高亮信息;没有则返回空列表。"""
    if not baseline_path.exists():
        logger.info("基线文件 %s 不存在,跳过 diff (首次跑请用 --update-baseline 冻结)", baseline_path)
        return []

    with baseline_path.open(encoding="utf-8") as f:
        baseline = json.load(f)

    regressions: list[str] = []
    cur_agg = report["aggregate"]
    base_agg = baseline.get("aggregate", {})

    def _check(name: str, cur: float, base: float) -> None:
        if base <= 0:
            return  # 基线为 0 时不判定回归(没有更差的余地)
        delta = cur - base
        rel = delta / base
        if rel < -REGRESSION_THRESHOLD:
            regressions.append(f"{name}: {base:.4f} → {cur:.4f}  (Δ={delta:+.4f}, {rel:+.2%})")

    for k_str, base_v in base_agg.get("recall_at_k", {}).items():
        cur_v = cur_agg["recall_at_k"].get(k_str, 0.0)
        _check(f"recall@{k_str}", cur_v, base_v)
    _check("mrr", cur_agg["mrr"], base_agg.get("mrr", 0.0))
    _check("ndcg@10", cur_agg["ndcg_at_10"], base_agg.get("ndcg_at_10", 0.0))

    return regressions


# ---------- 主流程 ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="L2 召回评测")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="把本次结果写入 reports/baseline.json,用于首次冻结或人工确认 OK 后更新",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=TOP_K,
        help=f"每条 query 检索的 chunk 数(默认 {TOP_K})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 加载真实 config —— 主要为了把 embedding model / api_key / base_url
    #    注入到 RagConfig 里(它会处理 $OPENAI_API_KEY 这种环境变量解析)
    try:
        AppConfig.from_file()
    except Exception as exc:  # noqa: BLE001
        logger.error("加载 config.yaml 失败: %s", exc)
        return 2

    base_rag = get_rag_config()
    if not base_rag.embedding_api_key and base_rag.embedding_model.startswith("openai"):
        logger.error(
            "RagConfig.embedding_api_key 为空 —— 请在 config.yaml 里把 "
            "$OPENAI_API_KEY (或对应代理 key) 设成环境变量再跑",
        )
        return 2

    # 2) 用临时 chroma 目录隔离,跑完清理 —— 不污染真实租户数据
    tmp_dir = Path(tempfile.mkdtemp(prefix="recall_l2_chroma_"))
    set_rag_config(
        RagConfig(
            **{
                **base_rag.model_dump(),
                "enabled": True,
                "chroma_persist_dir": str(tmp_dir),
                "vector_store_backend": "chroma",
                # eval 跑完就丢,直接放行 default tenant 的检查;但我们已经
                # 切到了 recall-l2-eval,这个开关只是兜底
                "allow_no_auth_kb": True,
            }
        )
    )

    token = set_current_tenant_id(TENANT_ID)
    started_at = datetime.now(UTC)
    t0 = time.time()
    exit_code = 0
    try:
        sections = load_corpus(CORPUS_DIR)
        queries = load_queries(QUERIES_FILE)
        logger.info("corpus=%d sections, queries=%d", len(sections), len(queries))

        indexed_chunks = index_corpus(sections)

        retriever = DocumentRetriever()
        per_query = [run_query(retriever, q, top_k=args.top_k) for q in queries]
        aggregate = aggregate_metrics(per_query)

        duration_ms = int((time.time() - t0) * 1000)
        report = build_report(
            aggregate=aggregate,
            per_query=per_query,
            rag_config=get_rag_config(),
            started_at=started_at,
            duration_ms=duration_ms,
            corpus_section_count=len(sections),
            indexed_chunk_count=indexed_chunks,
        )

        ts = started_at.strftime("%Y%m%dT%H%M%SZ")
        run_path = REPORTS_DIR / f"run-{ts}.json"
        run_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("report -> %s", run_path)

        # 漂亮打印聚合指标
        agg = report["aggregate"]
        print()
        print("=" * 60)
        print(f"召回评测结果 (judged={agg['judged_query_count']}, negative={agg['negative_query_count']})")
        print("-" * 60)
        for k_str, v in agg["recall_at_k"].items():
            print(f"  Recall@{k_str:<3} = {v:.4f}")
        print(f"  MRR       = {agg['mrr']:.4f}")
        print(f"  nDCG@10   = {agg['ndcg_at_10']:.4f}")
        print("=" * 60)

        if args.update_baseline:
            BASELINE_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("baseline 已更新 -> %s", BASELINE_FILE)
        else:
            regressions = diff_against_baseline(report, BASELINE_FILE)
            if regressions:
                exit_code = 1
                print()
                print("!! 检测到指标回归(>5% 下降) !!")
                for line in regressions:
                    print(f"  - {line}")
                print()
            elif BASELINE_FILE.exists():
                print()
                print("vs baseline: OK,无显著回归")
                print()

    except Exception as exc:  # noqa: BLE001
        logger.exception("评测失败: %s", exc)
        exit_code = 2
    finally:
        # 3) 清理临时 chroma 目录 + 还原 tenant context
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        from deerflow.config.tenant import _current_tenant_id

        _current_tenant_id.reset(token)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
