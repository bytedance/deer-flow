"""表格行卡进 L1 检索评测的最小集成用例（spec 2026-09-09 §3/§9，plan Task 5）。

证明 spec §3 的核心断言——「表格文档经 parser 归一为 GFM、经表格感知 chunker 切成
行卡 chunk 后，自动进入 L1（确定性检索）与 recall@k / hit_rate / path_accuracy 全部
现有指标」——**零改造**成立：行卡 chunk_id（``{doc_id}#{index:04d}``，doc_id 是 32 位
小写 hex）天然匹配 golden schema 的 ``relevant_chunk_ids`` 正则 ``<32-hex>#NNNN``
（``dataset._CHUNK_ID_RE``），行卡正文（每块重复表头 + 行组，Task 4）即嵌入文本。

故本用例建一个 fake 表格 KB（真实 store）：一个 ``.csv`` 文档走生产 ``parse_document``
归一、一个 ``.xlsx`` 文档走生产 ``_workbook_rows_to_markdown`` 组装，二者均用生产
``chunk_markdown`` 切成行卡入库；再跑生产同款 L1 编排（``run_evaluation`` +
``save_eval_run``），断言 recall@k 有数。向量检索用 stub searcher（真实 embedding
非本用例关注点；L1 编排 / 指标计算 / 持久化全走真实链路）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from deerflow_knowledge.chunker import chunk_markdown
from deerflow_knowledge.eval.dataset import load_golden, validate_question
from deerflow_knowledge.eval.persistence import baseline_diff_from_report, generate_run_id, layer1_metrics_from_report, save_eval_run
from deerflow_knowledge.eval.runner import ScoredHit, report_to_dict, run_evaluation
from deerflow_knowledge.parser import _workbook_rows_to_markdown, parse_document
from deerflow_knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio

KB = "kb-table-eval"
OWNER = str(uuid.UUID(int=1234567890))
GENERATED_AT = "2026-09-10T10:00:00+00:00"
CSV_NAME = "销售明细.csv"
XLSX_NAME = "季度报表.xlsx"
SHEET_NAME = "季度销售"

_COLUMNS = ["Region", "Product", "Q1", "Q2", "Total"]
_REGIONS = ["华北", "华东", "华南", "西南", "东北"]
_PRODUCTS = ["Widget-A", "Widget-B", "Gadget-C"]


def _row(i: int) -> list[object]:
    """第 i 行销售数据（i=0 恰为 华北 / Widget-A，供「按列值提问」精确锚定）。"""
    q1, q2 = 100 + i, 110 + i
    return [_REGIONS[i % len(_REGIONS)], _PRODUCTS[i % len(_PRODUCTS)], q1, q2, q1 + q2]


def _csv_text(row_count: int = 120) -> str:
    """一张足够大的销售表 → 生产 chunk_markdown（默认 cap）切成多张行卡。"""
    lines = [",".join(_COLUMNS)]
    lines.extend(",".join(str(cell) for cell in _row(i)) for i in range(row_count))
    return "\n".join(lines) + "\n"


def _xlsx_rows(row_count: int = 120) -> list[list[object]]:
    """Excel sheet 的原生行（首行表头），交生产 _workbook_rows_to_markdown 组装。"""
    return [list(_COLUMNS), *[_row(i) for i in range(row_count)]]


@pytest.fixture
def store(session_factory):
    return KnowledgeStore(session_factory)


async def _insert_row_cards(store: KnowledgeStore, doc_id: str, name: str, markdown: str) -> list[str]:
    """建文档行 + 用生产 chunk_markdown 切行卡入库 → 读回真实 chunk_id 列表。

    行卡即 spec §3「表格 → 行卡 = chunk」的落库形态：chunk_id 扁平序 ``{doc_id}#NNNN``、
    卡正文是重复表头 + 行组（Task 4）。从 store 读回证明行卡确实是 KB 里的 chunk
    （而非凭空构造的 id），字段口径与 worker ``_reparse_and_chunk`` 的 insert 一致。
    """
    await store.create_document(
        doc_id=doc_id,
        kb_id=KB,
        uploader_id=OWNER,
        name=name,
        size_bytes=len(markdown.encode("utf-8")),
        storage_path=f"/data/{doc_id}/{name}",
    )
    chunks = chunk_markdown(markdown, doc_id)  # 生产表格感知切分（默认 card_mode=markdown）
    await store.insert_chunks(
        [
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": doc_id,
                "kb_id": KB,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "heading_path": chunk.heading_path,
                "page": chunk.page,
                "token_count": chunk.token_count,
            }
            for chunk in chunks
        ]
    )
    stored = await store.list_chunks(doc_id)
    return [row["chunk_id"] for row in stored]


async def _seed_table_kb(store: KnowledgeStore, tmp_path) -> tuple[list[str], list[str]]:
    """建 fake 表格 KB：一个 .csv 文档（生产 parse_document）+ 一个 .xlsx 文档
    （生产 _workbook_rows_to_markdown），均用生产 chunk_markdown 切成行卡入库。

    返回 ``(csv_chunk_ids, xlsx_chunk_ids)``（各自按 chunk_index 序）。CSV 路永远开启
    （不受 rag.table.enabled 门控），xlsx 路用纯组装函数避开 calamine/门控依赖。
    """
    await store.create_kb(kb_id=KB, owner_id=OWNER, name="表格库")

    csv_path = tmp_path / CSV_NAME
    csv_path.write_text(_csv_text(), encoding="utf-8")
    csv_markdown = (await parse_document(csv_path)).markdown
    csv_chunk_ids = await _insert_row_cards(store, uuid.uuid4().hex, CSV_NAME, csv_markdown)

    xlsx_markdown = _workbook_rows_to_markdown([(SHEET_NAME, _xlsx_rows())])
    xlsx_chunk_ids = await _insert_row_cards(store, uuid.uuid4().hex, XLSX_NAME, xlsx_markdown)

    return csv_chunk_ids, xlsx_chunk_ids


def _searchers_hitting(hit_chunk_ids: list[str]) -> dict:
    """stub searcher：vector 路按序命中给定行卡（模拟向量召回，分数递减）。"""

    async def vector_fn(query: str, top_k: int):
        return tuple(ScoredHit(chunk_id=cid, score=0.9 - 0.01 * i) for i, cid in enumerate(hit_chunk_ids[:top_k]))

    return {"vector": vector_fn}


async def test_table_row_card_chunk_ids_are_valid_golden_anchors(store, tmp_path) -> None:
    """行卡 chunk_id 可直接作 golden ``relevant_chunk_ids``（零 schema 改造）。

    ``dataset.validate_question`` 强制每条 relevant_chunk_id 匹配
    ``<32-hex doc_id>#NNNN``（``dataset._CHUNK_ID_RE``）；表格行卡 chunk_id 通过校验 =
    天然兼容现有评测锚定，无需为表格引入任何新 schema 或降级语义。
    """
    csv_chunk_ids, xlsx_chunk_ids = await _seed_table_kb(store, tmp_path)
    all_chunk_ids = [*csv_chunk_ids, *xlsx_chunk_ids]

    # 大表被生产 chunk_markdown 切成多张行卡（行组 + 每块重复表头，Task 4）。
    assert len(csv_chunk_ids) >= 2

    question = validate_question(
        {
            "id": "q-table-anchor",
            "query": "表格行卡锚定兼容性",
            "expected_paths": ["vector"],
            "relevant_chunk_ids": all_chunk_ids,
            "relevant_entities": [],
            "category": "table",
        }
    )

    assert question.relevant_chunk_ids == tuple(all_chunk_ids)


async def test_table_row_cards_enter_layer1_recall(store, tmp_path) -> None:
    """fake 表格 KB → 行卡作为 chunk 进 L1 检索：recall@k / hit_rate / path_accuracy 有数（spec §3）。"""
    csv_chunk_ids, xlsx_chunk_ids = await _seed_table_kb(store, tmp_path)
    all_chunk_ids = [*csv_chunk_ids, *xlsx_chunk_ids]
    target_card = csv_chunk_ids[0]  # 首张行卡含 华北 / Widget-A 行（按列值提问的锚点）

    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        json.dumps(
            {
                "id": "q-table-row-card",
                "query": "华北区 Widget-A 的 Q1 销售额是多少",
                "expected_paths": ["vector"],
                "relevant_chunk_ids": [target_card],
                "relevant_entities": [],
                "category": "table",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    questions = load_golden(golden)

    report = await run_evaluation(questions, _searchers_hitting(all_chunk_ids), top_k=5, generated_at=GENERATED_AT)
    payload = report_to_dict(report)
    await save_eval_run(
        run_id=generate_run_id(),
        kb_id=KB,
        status="completed",
        created_at=datetime.fromisoformat(GENERATED_AT),
        completed_at=datetime.now(UTC),
        layer1_metrics=layer1_metrics_from_report(payload),
        baseline_diff=baseline_diff_from_report(payload),
    )

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    assert rows[0].status == "completed"
    summary = rows[0].layer1_metrics["summary"]
    assert summary["question_count"] == 1
    # 目标行卡被 vector 路命中 → recall@k / hit_rate 满分（有数，非 None/0）。
    assert summary["recall_at_k"] == 1.0
    assert summary["hit_rate"] == 1.0
    # 行卡走 vector 路命中且 expected_paths=["vector"] → path_accuracy 也计入。
    assert summary["path_accuracy"] == 1.0
