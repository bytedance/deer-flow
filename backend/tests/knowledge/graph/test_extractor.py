"""Tests for the LLM graph extractor (spec §3.4).

The LLM is faked through the ``ainvoke`` protocol; extraction uses the small
model (config ``rag.extract_model``) with a JSON-schema prompt, then one
gleaning round ("did you miss anything?") whose newly-found entities and
relations are merged in.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deerflow.knowledge.graph.extractor import (
    EXTRACT_SYSTEM_PROMPT,
    ExtractionError,
    ExtractionResult,
    extract_graph,
)


class _FakeLLM:
    """Returns canned message contents in call order (last one repeats)."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[object] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


def _payload(entities: list[dict], relations: list[dict] | None = None) -> str:
    return json.dumps({"entities": entities, "relations": relations or []}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_extract_parses_json_entities_and_relations():
    llm = _FakeLLM(
        [
            _payload(
                [
                    {"name": "DeerFlow", "type": "系统", "description": "基于 LangGraph 的超级智能体"},
                    {"name": "Gateway", "type": "组件", "description": "会话管理"},
                ],
                [{"source": "DeerFlow", "target": "Gateway", "relation": "包含", "description": "DeerFlow 包含 Gateway 组件"}],
            )
        ]
    )

    result = await extract_graph("DeerFlow 包含 Gateway。", llm=llm, gleaning_rounds=0)

    assert isinstance(result, ExtractionResult)
    assert [e.name for e in result.entities] == ["DeerFlow", "Gateway"]
    assert result.entities[0].type == "系统"
    assert result.entities[0].description == "基于 LangGraph 的超级智能体"
    assert len(result.relations) == 1
    rel = result.relations[0]
    assert (rel.source, rel.target, rel.relation) == ("DeerFlow", "Gateway", "包含")
    assert rel.description == "DeerFlow 包含 Gateway 组件"
    assert len(llm.calls) == 1  # gleaning disabled


@pytest.mark.asyncio
async def test_extract_tolerates_code_fenced_json():
    llm = _FakeLLM(["```json\n" + _payload([{"name": "MinerU", "type": "服务", "description": "解析"}]) + "\n```"])

    result = await extract_graph("任意文本", llm=llm, gleaning_rounds=0)

    assert [e.name for e in result.entities] == ["MinerU"]


@pytest.mark.asyncio
async def test_malformed_json_raises_extraction_error():
    llm = _FakeLLM(["这不是 JSON，模型失控输出"])

    with pytest.raises(ExtractionError, match="JSON|parse|malformed"):
        await extract_graph("任意文本", llm=llm, gleaning_rounds=0)


@pytest.mark.asyncio
async def test_missing_required_keys_raises_extraction_error():
    llm = _FakeLLM([json.dumps({"unexpected": True})])

    with pytest.raises(ExtractionError):
        await extract_graph("任意文本", llm=llm, gleaning_rounds=0)


@pytest.mark.asyncio
async def test_empty_result_returns_empty_lists():
    llm = _FakeLLM([_payload([], [])])

    result = await extract_graph("没有任何实体的文本。", llm=llm, gleaning_rounds=0)

    assert result.entities == []
    assert result.relations == []


@pytest.mark.asyncio
async def test_gleaning_second_pass_merges_new_entities_and_relations():
    first = _payload(
        [{"name": "DeerFlow", "type": "系统", "description": "智能体"}],
        [{"source": "DeerFlow", "target": "Gateway", "relation": "包含", "description": ""}],
    )
    gleaned = _payload(
        [
            {"name": "DeerFlow", "type": "系统", "description": "重复项应去重"},
            {"name": "LangGraph", "type": "框架", "description": "底层框架"},
        ],
        [
            {"source": "DeerFlow", "target": "Gateway", "relation": "包含", "description": "重复关系"},
            {"source": "DeerFlow", "target": "LangGraph", "relation": "基于", "description": "构建于 LangGraph"},
        ],
    )
    llm = _FakeLLM([first, gleaned])

    result = await extract_graph("DeerFlow 基于 LangGraph，包含 Gateway。", llm=llm, gleaning_rounds=1)

    assert len(llm.calls) == 2
    names = [e.name for e in result.entities]
    assert sorted(names) == ["DeerFlow", "LangGraph"]  # duplicate name merged
    # First-seen description wins for the duplicate.
    assert next(e for e in result.entities if e.name == "DeerFlow").description == "智能体"
    triples = {(r.source, r.target, r.relation) for r in result.relations}
    assert triples == {("DeerFlow", "Gateway", "包含"), ("DeerFlow", "LangGraph", "基于")}


@pytest.mark.asyncio
async def test_gleaning_prompt_mentions_missed_items():
    llm = _FakeLLM([_payload([{"name": "A", "type": "t", "description": "d"}]), _payload([], [])])

    await extract_graph("文本", llm=llm, gleaning_rounds=1)

    follow_up = str(llm.calls[1])
    assert "遗漏" in follow_up or "miss" in follow_up.lower()
    assert '"A"' in follow_up or "A" in follow_up  # already-found entities shown for context


def test_extract_prompt_guides_cross_language_canonical_names():
    """Task 10: the extraction prompt asks for the cross-language canonical
    form 「中文（英文）」 so the two halves of one concept arrive pre-linked.
    Task 10 revision (user badcase): no example (the model was mimicking it and
    inventing translations for every Chinese entity), an explicit definition of
    跨语言 (both names present in the source text), and a no-translation ban."""
    assert "中文（英文）" in EXTRACT_SYSTEM_PROMPT
    assert "不要自行翻译" in EXTRACT_SYSTEM_PROMPT
    assert "字符串（String）" not in EXTRACT_SYSTEM_PROMPT  # example removed
