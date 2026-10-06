"""File-level tests for bottom-up question synthesis (spec 2026-08-28 §6).

合成造题核心：LLM 读编号切片 → 候选题（JSON）→ 双重守卫（①锚定编号必须
映射到真实切片，②``validate_question`` 全字段校验）→ 合并追加进暂存（2026-09-02 起）。
候选题不入题库——只有 ``accept_candidate`` 经 ``question_bank.add_question``
写题库（唯一写路径纪律）。LLM 用 stub 驱动，不碰真实模型。
2026-09-02 起支持多篇联合出题（路线二）：多篇切片全局统一编号，守卫映射不
变；暂存元数据 ``doc_id`` → ``doc_ids`` 列表；超预算按篇均额等距采样。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deerflow.knowledge.eval import synthesis
from deerflow.knowledge.eval.question_bank import load_questions

pytestmark = pytest.mark.asyncio

KB = "kb-synth"
DOC = "d" * 32
DOC_B = "e" * 32
CHUNKS = [
    {"chunk_id": f"{DOC}#0001", "text": "String 是不可变类型。"},
    {"chunk_id": f"{DOC}#0002", "text": "StringBuffer 是可变且线程安全的。"},
    {"chunk_id": f"{DOC}#0003", "text": "StringBuilder 可变但非线程安全。"},
]
CHUNKS_B = [
    {"chunk_id": f"{DOC_B}#0001", "text": "HashMap 非线程安全。"},
    {"chunk_id": f"{DOC_B}#0002", "text": "ConcurrentHashMap 支持并发。"},
]
# (doc_id, doc_name, chunks) 三元组——联合出题的入参形态。
DOCS_SINGLE = [(DOC, "Java 并发.md", CHUNKS)]
DOCS_MULTI = [(DOC, "Java 并发.md", CHUNKS), (DOC_B, "集合框架.md", CHUNKS_B)]

GOOD_QUESTIONS = [
    {
        "query": "String 有什么特点？",
        "category": "fact",
        "expected_paths": ["vector"],
        "chunk_refs": [1],
        "reference_answer": "String 是不可变类型。",
    },
    {
        "query": "StringBuffer 和 StringBuilder 在安全性上有什么关系？",
        "category": "relation",
        "expected_paths": ["vector", "graph"],
        "chunk_refs": [2, 3],
        "reference_answer": "前者线程安全，后者非线程安全。",
    },
]


class _StubLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.content)


def _factory(questions: list[dict]) -> tuple:
    llm = _StubLLM(json.dumps({"questions": questions}, ensure_ascii=False))
    return (lambda: llm), llm


async def _synthesize(tmp_path, questions, docs=None, **kwargs):
    factory, llm = _factory(questions)
    staging = tmp_path / "eval_candidates.json"
    candidates, dropped = await synthesis.synthesize_for_docs(KB, docs=docs or DOCS_SINGLE, count=len(questions), staging_path=staging, llm_factory=factory, **kwargs)
    return staging, candidates, dropped, llm


async def test_synthesize_writes_validated_candidates_to_staging(tmp_path) -> None:
    staging, candidates, dropped, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)

    assert dropped == 0
    assert len(candidates) == 2
    # 暂存是单一 JSON 文档：元数据 + 候选列表（审核期元数据不随候选消费丢失）。
    data = json.loads(staging.read_text(encoding="utf-8"))
    assert data["doc_ids"] == [DOC]
    assert data["kb_id"] == KB
    assert data["dropped"] == 0
    assert data["generated_at"]
    assert len(data["candidates"]) == 2
    first = candidates[0]
    assert first.candidate_id.startswith("c_") and len(first.candidate_id) == 10
    assert first.relevant_chunk_ids == (f"{DOC}#0001",)
    assert candidates[1].relevant_chunk_ids == (f"{DOC}#0002", f"{DOC}#0003")
    assert candidates[1].expected_paths == ("vector", "graph")
    ids = [c.candidate_id for c in candidates]
    assert len(set(ids)) == 2, "候选 id 互不重复"
    # 候选不落题库——暂存与题库是两个文件。
    assert not (tmp_path / "golden.jsonl").exists()


async def test_candidate_entities_constrained_to_anchored_vocabulary(tmp_path) -> None:
    # 实体标注（2026-09-08 约束选择）：prompt 逐片下发实体词汇表，LLM 挑
    # 题面考察子集；guard 过滤词汇表外名字（幻觉零污染）、保序去重。
    chunks = [
        {"chunk_id": f"{DOC}#0001", "text": "String 是不可变类型。", "entities": ["String", "Java"]},
        {"chunk_id": f"{DOC}#0002", "text": "StringBuffer 是可变且线程安全的。", "entities": ["Java", "Thread"]},
    ]
    questions = [dict(GOOD_QUESTIONS[0], chunk_refs=[1, 2], relevant_entities=["String", "Java", "幻觉实体", "String"])]

    _, candidates, dropped, llm = await _synthesize(tmp_path, questions, docs=[(DOC, "Java 并发.md", chunks)])

    assert dropped == 0
    assert candidates[0].relevant_entities == ("String", "Java")
    # 词汇表随 prompt 下发（逐片前缀），模型选得到才挑得准。
    assert "实体词汇表: [String, Java]" in llm.calls[0][1].content


async def test_empty_entity_selection_stays_unannotated(tmp_path) -> None:
    # 空选择 = 诚实无标注（不回退切片全量并集）：seed_hit_rate 记不适用，
    # 不制造稀释分母。
    chunks = [{"chunk_id": f"{DOC}#0001", "text": "t", "entities": ["String"]}]
    questions = [dict(GOOD_QUESTIONS[0], chunk_refs=[1], relevant_entities=[])]

    _, candidates, _dropped, _llm = await _synthesize(tmp_path, questions, docs=[(DOC, "d.md", chunks)])

    assert candidates[0].relevant_entities == ()


async def test_out_of_range_anchor_drops_only_that_candidate(tmp_path) -> None:
    # 守卫①：锚定编号越界 → 该候选整条丢弃，其余不受影响。
    bad = [GOOD_QUESTIONS[0], dict(GOOD_QUESTIONS[1], chunk_refs=[9])]

    staging, candidates, dropped, _ = await _synthesize(tmp_path, bad)

    assert dropped == 1
    assert [c.query for c in candidates] == [GOOD_QUESTIONS[0]["query"]]
    assert json.loads(staging.read_text(encoding="utf-8"))["dropped"] == 1


async def test_schema_violation_drops_candidate_after_guard_two(tmp_path) -> None:
    # 守卫②：锚定合法但字段违例（坏 category）→ validate_question 拦下。
    bad = [dict(GOOD_QUESTIONS[0], category="vibe")]

    staging, candidates, dropped, _ = await _synthesize(tmp_path, bad)

    assert dropped == 1
    assert candidates == []
    assert json.loads(staging.read_text(encoding="utf-8"))["candidates"] == []


async def test_invalid_llm_json_writes_empty_staging_without_raising(tmp_path) -> None:
    # LLM 输出非法 JSON → 0 候选、不抛错，暂存整体替换为空合成元数据。
    llm = _StubLLM("这不是 JSON")
    staging = tmp_path / "eval_candidates.json"

    candidates, dropped = await synthesis.synthesize_for_docs(KB, docs=DOCS_SINGLE, count=3, staging_path=staging, llm_factory=lambda: llm)

    assert candidates == [] and dropped == 0
    data = json.loads(staging.read_text(encoding="utf-8"))
    assert data["candidates"] == [] and data["doc_ids"] == [DOC]


async def test_resynthesis_appends_to_pending_staging(tmp_path) -> None:
    # 合并语义（2026-09-02 修订，原「整体替换」已作废）：重新合成新批追加、
    # 旧候选原样保留——快捷入口（右键出一条）不得冲掉用户待审内容。
    staging, first, _, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)
    factory, _ = _factory([GOOD_QUESTIONS[0]])

    second, dropped = await synthesis.synthesize_for_docs(KB, docs=DOCS_SINGLE, count=1, staging_path=staging, llm_factory=factory)

    assert dropped == 0 and len(second) == 1
    data = json.loads(staging.read_text(encoding="utf-8"))
    assert len(data["candidates"]) == len(first) + 1
    old_ids = {c.candidate_id for c in first}
    new_ids = {row["candidate_id"] for row in data["candidates"]}
    assert old_ids < new_ids, "旧候选全量保留"
    assert new_ids - old_ids == {second[0].candidate_id}, "新批用新 candidate_id"


async def test_accept_moves_candidate_into_bank_with_new_server_id(tmp_path) -> None:
    staging, candidates, _, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)
    bank = tmp_path / "golden.jsonl"

    question = await synthesis.accept_candidate(bank, staging, candidates[1].candidate_id)

    assert question.id.startswith("q_") and question.id != candidates[1].candidate_id
    assert question.expected_paths == ("vector", "graph")
    assert question.relevant_chunk_ids == (f"{DOC}#0002", f"{DOC}#0003")
    # 入库走 add_question 守卫——题库可被标准加载器回读。
    assert [q.id for q in await load_questions(bank)] == [question.id]
    # 暂存中该候选消失，另一条保留。
    remaining = json.loads(staging.read_text(encoding="utf-8"))["candidates"]
    assert [row["candidate_id"] for row in remaining] == [candidates[0].candidate_id]


async def test_accept_unknown_candidate_raises_key_error(tmp_path) -> None:
    staging, _, _, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)

    with pytest.raises(KeyError):
        await synthesis.accept_candidate(tmp_path / "golden.jsonl", staging, "c_missing0")


async def test_reject_removes_candidate_from_staging(tmp_path) -> None:
    staging, candidates, _, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)

    removed = await synthesis.reject_candidate(staging, candidates[0].candidate_id)

    assert removed == candidates[0].candidate_id
    remaining = json.loads(staging.read_text(encoding="utf-8"))["candidates"]
    assert [row["candidate_id"] for row in remaining] == [candidates[1].candidate_id]
    # 题库不受拒绝影响。
    assert not (tmp_path / "golden.jsonl").exists()


async def test_reject_unknown_candidate_raises_key_error(tmp_path) -> None:
    staging, _, _, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)

    with pytest.raises(KeyError):
        await synthesis.reject_candidate(staging, "c_missing0")


async def test_load_staging_missing_file_is_empty_not_error(tmp_path) -> None:
    # 新 KB 从未合成过：读暂存不是错误，缺省元数据可读（状态端点直接消费）。
    status = await synthesis.load_staging(tmp_path / "absent.json")

    assert status["candidates"] == []
    assert status["generated_at"] is None
    assert status["doc_ids"] == []
    assert status["dropped"] == 0


async def test_prompt_contract_carries_numbered_chunks_and_constraints(tmp_path) -> None:
    # prompt 契约钉死：编号切片清单 / 数量约束 / 混合题型 / 禁止照抄 / JSON 字段。
    _, _, _, llm = await _synthesize(tmp_path, GOOD_QUESTIONS)

    prompt_text = "\n".join(str(getattr(m, "content", m)) for m in llm.calls[0])
    assert "[1]" in prompt_text and f"[{len(CHUNKS)}]" in prompt_text, "切片必须编号喂入"
    assert str(len(GOOD_QUESTIONS)) in prompt_text, "数量约束进 prompt"
    assert "single-hop" in prompt_text and "multi-hop" in prompt_text
    assert "照抄" in prompt_text, "禁止照抄切片原文的约束进 prompt"
    assert "chunk_refs" in prompt_text and "expected_paths" in prompt_text
    # 约束选择（2026-09-08）：实体子集字段与挑选约束进 prompt 契约。
    assert "relevant_entities" in prompt_text and "实体词汇表" in prompt_text


# ── 多篇联合出题（2026-09-02 路线二）─────────────────────────────────


async def test_multi_doc_global_numbering_maps_anchors_across_docs(tmp_path) -> None:
    # 多篇切片全局统一编号：第二篇的第 1 片是全局第 4 号，锚定 [4] 映射到 B 的切片。
    cross = [
        {
            "query": "String 与 HashMap 在线程安全上有什么对照？",
            "category": "concept",
            "expected_paths": ["vector", "graph"],
            "chunk_refs": [1, 4],
            "reference_answer": "前者不可变天然安全，后者需换并发容器。",
        }
    ]

    staging, candidates, dropped, _ = await _synthesize(tmp_path, cross, docs=DOCS_MULTI)

    assert dropped == 0
    assert candidates[0].relevant_chunk_ids == (f"{DOC}#0001", f"{DOC_B}#0001")
    # 暂存元数据是多篇列表；候选的来源文档由锚定切片推导（跨篇逗号连接）。
    data = json.loads(staging.read_text(encoding="utf-8"))
    assert data["doc_ids"] == [DOC, DOC_B]
    assert candidates[0].doc_id == f"{DOC},{DOC_B}"


async def test_multi_doc_prompt_names_documents_and_asks_cross_doc_question(tmp_path) -> None:
    # 多篇场景：切片行带文档名前缀 + 跨文档出题约束；总编号贯穿两篇。
    _, _, _, llm = await _synthesize(tmp_path, GOOD_QUESTIONS, docs=DOCS_MULTI)

    prompt_text = "\n".join(str(getattr(m, "content", m)) for m in llm.calls[0])
    assert "Java 并发.md" in prompt_text and "集合框架.md" in prompt_text
    assert f"[{len(CHUNKS) + len(CHUNKS_B)}]" in prompt_text, "全局编号贯穿多篇"
    assert "跨文档" in prompt_text, "多篇时跨文档出题约束进 prompt"
    # 单篇时不应出现跨文档约束（避免自相矛盾）。
    _, _, _, single_llm = await _synthesize(tmp_path, GOOD_QUESTIONS, docs=DOCS_SINGLE)
    single_text = "\n".join(str(getattr(m, "content", m)) for m in single_llm.calls[0])
    assert "跨文档" not in single_text


async def test_oversized_doc_chunks_are_sampled_within_budget(tmp_path) -> None:
    # 超预算：单篇 200 切片 > MAX，等距采样到预算内，首尾切片必在样本中。
    big_doc = "f" * 32
    big_chunks = [{"chunk_id": f"{big_doc}#{index:04d}", "text": f"内容 {index}"} for index in range(1, 201)]
    question = [dict(GOOD_QUESTIONS[0], chunk_refs=[1])]

    _, _, _, llm = await _synthesize(tmp_path, question, docs=[(big_doc, "大文档.md", big_chunks)])

    prompt_text = "\n".join(str(getattr(m, "content", m)) for m in llm.calls[0])
    sampled = prompt_text.count("《大文档.md》")
    assert sampled == synthesis.MAX_SYNTH_CHUNKS
    assert "内容 1" in prompt_text and "内容 200" in prompt_text, "等距采样保留首尾"


async def test_multi_doc_budget_split_keeps_every_document(tmp_path) -> None:
    # 预算按篇均额：两篇各 100 切片，每篇至少分到配额、都不被饿死。
    doc_a, doc_b = "f" * 32, "a1" * 16
    chunks_a = [{"chunk_id": f"{doc_a}#{index:04d}", "text": f"A{index}"} for index in range(1, 101)]
    chunks_b = [{"chunk_id": f"{doc_b}#{index:04d}", "text": f"B{index}"} for index in range(1, 101)]

    _, _, _, llm = await _synthesize(tmp_path, [GOOD_QUESTIONS[0]], docs=[(doc_a, "A.md", chunks_a), (doc_b, "B.md", chunks_b)])

    prompt_text = "\n".join(str(getattr(m, "content", m)) for m in llm.calls[0])
    assert prompt_text.count("《A.md》") == synthesis.MAX_SYNTH_CHUNKS // 2
    assert prompt_text.count("《B.md》") == synthesis.MAX_SYNTH_CHUNKS // 2


async def test_load_staging_legacy_single_doc_id_normalizes_to_list(tmp_path) -> None:
    # 旧版暂存（单值 doc_id）读入时归一为 doc_ids 列表——升级不断层。
    staging = tmp_path / "eval_candidates.json"
    staging.write_text(json.dumps({"kb_id": KB, "doc_id": DOC, "generated_at": "t", "dropped": 0, "candidates": []}), encoding="utf-8")

    data = await synthesis.load_staging(staging)

    assert data["doc_ids"] == [DOC]


async def test_new_synthesis_merges_into_pending_staging(tmp_path) -> None:
    # 合并语义（2026-09-02 右键快捷出题）：已有未审候选时新批追加而非覆盖；
    # doc_ids 保序取并集，dropped 累加，旧候选原样保留。
    staging, first, _, _ = await _synthesize(tmp_path, GOOD_QUESTIONS)
    question_b = {
        "query": "HashMap 线程安全吗？",
        "category": "fact",
        "expected_paths": ["vector"],
        "chunk_refs": [1],
        "reference_answer": "HashMap 非线程安全。",
    }
    second, dropped2 = await synthesis.synthesize_for_docs(
        KB,
        docs=DOCS_MULTI[1:],
        count=1,
        staging_path=staging,
        llm_factory=_factory([question_b])[0],
    )

    assert len(second) == 1 and dropped2 == 0, "返回值只反映本批"
    data = await synthesis.load_staging(staging)
    assert len(data["candidates"]) == len(first) + 1, "旧候选保留 + 新批追加"
    assert data["doc_ids"] == [DOC, DOC_B], "并集保序（旧批在前）"
    assert data["dropped"] == 0
    # 新批候选带上自己的来源文档。
    assert data["candidates"][-1]["doc_id"] == DOC_B


def test_in_flight_registry_begin_end_semantics() -> None:
    assert synthesis.synthesis_in_progress(KB) is False
    assert synthesis.begin_synthesis(KB) is True
    assert synthesis.synthesis_in_progress(KB) is True
    assert synthesis.begin_synthesis(KB) is False, "in-flight 中重复 begin 返回 False"
    synthesis.end_synthesis(KB)
    assert synthesis.synthesis_in_progress(KB) is False
    synthesis.end_synthesis(KB)  # drain 后再 end 不下穿为负
    assert synthesis.synthesis_in_progress(KB) is False
