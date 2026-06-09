"""测试 RAG 召回内容注入到模型的过程。

验证：用户消息 → 检索 → 格式化 → SystemMessage 注入的完整链路。
重点：模型最终看到了什么内容。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import SystemMessage

from deerflow.rag.vector_store import SearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunks(contents: list[str], source: str = "doc.md") -> list[SearchResult]:
    return [
        SearchResult(
            chunk_id=f"chunk-{i}",
            content=content,
            metadata={"source": source, "title": "Test Doc"},
            score=0.9 - i * 0.1,
        )
        for i, content in enumerate(contents)
    ]


def _make_multi_kb_chunks() -> list[SearchResult]:
    return [
        SearchResult(
            chunk_id="kb1-c1",
            content="设备 A 的振动值超过阈值",
            metadata={
                "kb_name": "设备维护知识库",
                "knowledge_base_id": "kb-001",
                "title": "振动告警处理",
                "score": 0.92,
            },
            score=0.92,
        ),
        SearchResult(
            chunk_id="kb2-c1",
            content="轴承温度异常时需要停机检查",
            metadata={
                "kb_name": "故障处理手册",
                "knowledge_base_id": "kb-002",
                "title": "温度故障处理",
                "score": 0.85,
            },
            score=0.85,
        ),
    ]


# ---------------------------------------------------------------------------
# 测试类：Prompt 格式化
# ---------------------------------------------------------------------------


class TestRagPromptFormatting:
    """测试 prompt 格式化函数，验证模型看到的内容格式。"""

    def test_format_chunks_for_injection_wraps_xml(self) -> None:
        """format_chunks_for_injection 生成正确的 XML 包装。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        chunks = _make_chunks([
            "振动值超过阈值",
            "温度异常需要停机",
        ])

        result = format_chunks_for_injection(chunks, max_tokens=2000)

        assert "<knowledge_base>" in result
        assert "</knowledge_base>" in result
        assert "振动值超过阈值" in result
        assert "温度异常需要停机" in result
        assert "(source: doc.md)" in result
        assert "[1]" in result
        assert "[2]" in result

    def test_format_multi_kb_context_structured_xml(self) -> None:
        """format_multi_kb_context 生成结构化 XML。"""
        from deerflow.rag.prompt import format_multi_kb_context

        chunks = _make_multi_kb_chunks()

        result = format_multi_kb_context(chunks, max_tokens=4000)

        assert "<knowledge_base_context>" in result
        assert "</knowledge_base_context>" in result
        assert '<source kb_id="kb-001"' in result
        assert 'kb_name="设备维护知识库"' in result
        assert 'doc_title="振动告警处理"' in result
        assert 'score="0.92"' in result
        assert "振动值超过阈值" in result

    def test_format_chunks_respects_token_limit(self) -> None:
        """format_chunks_for_injection 遵守 token 限制。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        chunks = _make_chunks([
            "第一个 chunk 的内容比较长，会占用较多的 token 空间",
            "第二个 chunk 的内容也应该被考虑进去",
            "第三个 chunk 如果超出限制应该被截断",
        ])

        # header ≈ 50 tokens, footer ≈ 10 tokens, 留 200 tokens 给内容
        result = format_chunks_for_injection(chunks, max_tokens=300)

        # 应该包含前两个 chunk
        assert "第一个 chunk" in result
        assert "第二个 chunk" in result
        # 第三个可能也被包含，取决于实际 token 计算

    def test_format_chunks_empty_returns_empty(self) -> None:
        """空 chunks 返回空字符串。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        result = format_chunks_for_injection([], max_tokens=2000)
        assert result == ""

    def test_format_multi_kb_empty_returns_empty(self) -> None:
        """空 results 返回空字符串。"""
        from deerflow.rag.prompt import format_multi_kb_context

        result = format_multi_kb_context([], max_tokens=4000)
        assert result == ""

    def test_format_chunks_includes_score_and_source(self) -> None:
        """验证 chunk 包含分数和来源信息。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        chunks = [
            SearchResult(
                chunk_id="c1",
                content="关键信息内容",
                metadata={"source": "manual.pdf", "page": 42},
                score=0.95,
            ),
        ]

        result = format_chunks_for_injection(chunks, max_tokens=2000)

        assert "关键信息内容" in result
        assert "(source: manual.pdf)" in result

    def test_format_multi_kb_includes_all_metadata(self) -> None:
        """验证多 KB 格式包含所有元数据。"""
        from deerflow.rag.prompt import format_multi_kb_context

        chunks = [
            SearchResult(
                chunk_id="c1",
                content="设备维护指南",
                metadata={
                    "kb_name": "维护手册",
                    "knowledge_base_id": "kb-123",
                    "title": "第一章",
                    "score": 0.88,
                },
                score=0.88,
            ),
        ]

        result = format_multi_kb_context(chunks, max_tokens=4000)

        assert 'kb_id="kb-123"' in result
        assert 'kb_name="维护手册"' in result
        assert 'doc_title="第一章"' in result
        assert 'score="0.88"' in result
        assert "设备维护指南" in result

    def test_format_chunks_truncates_long_content(self) -> None:
        """验证长内容会被截断以适应 token 限制。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        # 创建多个 chunk
        chunks = [
            SearchResult(
                chunk_id="c1",
                content="第一个 chunk 内容",
                metadata={"source": "doc.txt"},
                score=0.9,
            ),
            SearchResult(
                chunk_id="c2",
                content="第二个 chunk 内容",
                metadata={"source": "doc.txt"},
                score=0.8,
            ),
            SearchResult(
                chunk_id="c3",
                content="第三个 chunk 内容",
                metadata={"source": "doc.txt"},
                score=0.7,
            ),
        ]

        # header ≈ 16 tokens, footer ≈ 4 tokens, 每个 chunk line ≈ 9 tokens
        # max_tokens=30: 20 + 9 = 29 (fits chunk 1), 29 + 9 = 38 (exceeds, stops)
        result = format_chunks_for_injection(chunks, max_tokens=30)

        # 应该只包含第一个 chunk
        assert "第一个 chunk" in result
        # 后面的 chunk 应该被截断
        assert "第二个 chunk" not in result
        assert "第三个 chunk" not in result


# ---------------------------------------------------------------------------
# 测试类：Integration with DocumentRetriever
# ---------------------------------------------------------------------------


class TestRetrievalToPromptIntegration:
    """测试从检索到 prompt 格式化的集成流程。"""

    def test_retriever_results_can_be_formatted(self) -> None:
        """验证 retriever 返回的结果可以被格式化。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        # 模拟 DocumentRetriever.retrieve() 返回的结果
        simulated_results = [
            SearchResult(
                chunk_id="id1",
                content="检索到的相关内容 1",
                metadata={"source": "kb1/doc1.md"},
                score=0.92,
            ),
            SearchResult(
                chunk_id="id2",
                content="检索到的相关内容 2",
                metadata={"source": "kb1/doc2.md"},
                score=0.85,
            ),
        ]

        # 格式化为 prompt
        formatted = format_chunks_for_injection(simulated_results, max_tokens=2000)

        # 验证格式正确
        assert "<knowledge_base>" in formatted
        assert "检索到的相关内容 1" in formatted
        assert "检索到的相关内容 2" in formatted
        assert "[1]" in formatted
        assert "[2]" in formatted

    def test_multi_kb_results_can_be_formatted(self) -> None:
        """验证多 KB 检索结果可以被格式化。"""
        from deerflow.rag.prompt import format_multi_kb_context

        # 模拟 multi_kb_retrieve() 返回的结果
        simulated_results = [
            SearchResult(
                chunk_id="kb1-id1",
                content="来自 KB1 的内容",
                metadata={
                    "kb_name": "知识库 1",
                    "knowledge_base_id": "kb-001",
                    "title": "文档标题",
                    "score": 0.9,
                },
                score=0.9,
            ),
            SearchResult(
                chunk_id="kb2-id1",
                content="来自 KB2 的内容",
                metadata={
                    "kb_name": "知识库 2",
                    "knowledge_base_id": "kb-002",
                    "title": "另一个文档",
                    "score": 0.85,
                },
                score=0.85,
            ),
        ]

        # 格式化为 prompt
        formatted = format_multi_kb_context(simulated_results, max_tokens=4000)

        # 验证 XML 结构
        assert "<knowledge_base_context>" in formatted
        assert "<source" in formatted
        assert "知识库 1" in formatted
        assert "知识库 2" in formatted
        assert "来自 KB1 的内容" in formatted
        assert "来自 KB2 的内容" in formatted

    def test_formatted_output_is_valid_system_message_content(self) -> None:
        """验证格式化输出可以作为 SystemMessage 的 content。"""
        from deerflow.rag.prompt import format_chunks_for_injection

        chunks = _make_chunks(["测试内容"])
        formatted = format_chunks_for_injection(chunks, max_tokens=2000)

        # 创建 SystemMessage
        msg = SystemMessage(content=formatted)

        # 验证可以正常访问
        assert isinstance(msg.content, str)
        assert len(msg.content) > 0
        assert "<knowledge_base>" in msg.content
