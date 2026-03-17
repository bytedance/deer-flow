"""Tests for AutoScientificClosureMiddleware."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.config.paths import Paths

middleware_module = importlib.import_module("src.agents.middlewares.auto_scientific_closure_middleware")


def _state(*, ai_text: str, artifacts: list[str], with_image_report: bool = True) -> dict:
    messages: list = []
    if with_image_report:
        messages.append(
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={
                    "deerflow_injected": "image_report",
                    "report_paths": ["/mnt/user-data/outputs/scientific-vision/image-reports/images/sha256-x/report-1.json"],
                },
            )
        )
    messages.append(AIMessage(content=ai_text))
    return {"messages": messages, "artifacts": artifacts}


def test_auto_triggers_audit_and_figure_generation():
    mw = middleware_module.AutoScientificClosureMiddleware(max_figure_calls=3)
    state = _state(
        ai_text="处理组条带下降约20%，且聚类分离更明显，结论可靠。",
        artifacts=[
            "/mnt/user-data/outputs/scientific-vision/raw-data/embedding/batch-1/analysis.json",
            "/mnt/user-data/outputs/scientific-vision/raw-data/spectrum/batch-2/analysis.json",
        ],
    )

    update = mw.after_model(state, runtime=None)
    assert update is not None
    updated_ai = update["messages"][0]
    assert isinstance(updated_ai, AIMessage)
    names = [tc.get("name") for tc in (updated_ai.tool_calls or [])]
    assert "audit_cross_modal_consistency" in names
    assert "generate_reproducible_figure" in names


def test_does_not_trigger_without_image_report_context():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = _state(
        ai_text="这里是普通结论文本，不涉及 scientific image report。",
        artifacts=["/mnt/user-data/outputs/scientific-vision/raw-data/embedding/batch-1/analysis.json"],
        with_image_report=False,
    )
    assert mw.after_model(state, runtime=None) is None


def test_does_not_trigger_when_closure_already_present():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = _state(
        ai_text="结论文本。",
        artifacts=[
            "/mnt/user-data/outputs/scientific-vision/raw-data/embedding/batch-1/analysis.json",
            "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-x/audit.json",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-1/demo.svg",
        ],
    )
    assert mw.after_model(state, runtime=None) is None


def _runtime(thread_id: str = "thread-1") -> SimpleNamespace:
    return SimpleNamespace(context={"configurable": {"thread_id": thread_id}})


def test_injects_final_summary_template_after_tools_complete():
    mw = middleware_module.AutoScientificClosureMiddleware()
    closure_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-audit",
                "name": "audit_cross_modal_consistency",
                "args": {"narrative_text": "处理组条带下降约20%"},
                "type": "tool_call",
            },
            {
                "id": "tc-fig",
                "name": "generate_reproducible_figure",
                "args": {"analysis_path": "/mnt/user-data/outputs/scientific-vision/raw-data/embedding/batch-1/analysis.json", "language": "python"},
                "type": "tool_call",
            },
        ],
        additional_kwargs={
            "deerflow_auto_scientific_closure": True,
            "deerflow_auto_scientific_original_response": "处理组条带下降约20%，结论可靠。",
        },
    )
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            closure_ai,
            ToolMessage(content="audit_cross_modal_consistency completed: claims=3, supported=2, partial=1, unsupported=0, contradicted=0.", tool_call_id="tc-audit"),
            ToolMessage(content="generate_reproducible_figure completed: kind=embedding, language=python.", tool_call_id="tc-fig"),
        ],
        "artifacts": [
            "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-x/audit.json",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-y/demo.svg",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-y/demo.pdf",
        ],
    }

    update = mw.before_model(state, runtime=_runtime())
    assert update is not None
    msg = update["messages"][0]
    assert isinstance(msg, HumanMessage)
    assert (msg.additional_kwargs or {}).get("deerflow_injected") == "auto_scientific_closure_summary"
    content = str(msg.content)
    assert "## 证据一致性摘要" in content
    assert "## 图表复现路径" in content
    assert "claims_total=3" in content
    assert "/scientific-vision/figures/embedding/batch-y/demo.svg" in content


def test_before_model_not_inject_when_tools_not_completed():
    mw = middleware_module.AutoScientificClosureMiddleware()
    closure_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-audit",
                "name": "audit_cross_modal_consistency",
                "args": {"narrative_text": "处理组条带下降约20%"},
                "type": "tool_call",
            }
        ],
        additional_kwargs={"deerflow_auto_scientific_closure": True},
    )
    state = {
        "messages": [
            HumanMessage(content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>', additional_kwargs={"deerflow_injected": "image_report"}),
            closure_ai,
        ],
        "artifacts": [],
    }
    assert mw.before_model(state, runtime=_runtime()) is None


def test_before_model_not_inject_when_summary_already_injected():
    mw = middleware_module.AutoScientificClosureMiddleware()
    closure_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-audit",
                "name": "audit_cross_modal_consistency",
                "args": {"narrative_text": "处理组条带下降约20%"},
                "type": "tool_call",
            }
        ],
        additional_kwargs={"deerflow_auto_scientific_closure": True},
    )
    state = {
        "messages": [
            HumanMessage(content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>', additional_kwargs={"deerflow_injected": "image_report"}),
            closure_ai,
            ToolMessage(content="audit_cross_modal_consistency completed: claims=1, supported=1, partial=0, unsupported=0, contradicted=0.", tool_call_id="tc-audit"),
            HumanMessage(content="already injected", additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"}),
        ],
        "artifacts": [],
    }
    assert mw.before_model(state, runtime=_runtime()) is None


def test_after_model_enforces_final_answer_sections_once():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-audit",
                        "name": "audit_cross_modal_consistency",
                        "args": {"narrative_text": "处理组条带下降约20%"},
                        "type": "tool_call",
                    }
                ],
                additional_kwargs={"deerflow_auto_scientific_closure": True},
            ),
            HumanMessage(
                content="<scientific_closure_summary>...</scientific_closure_summary>",
                additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
            ),
            AIMessage(content="结论：处理组趋势明显，建议继续验证。"),
        ],
        "artifacts": [
            "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-z/audit.json",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.pdf",
        ],
    }

    update = mw.after_model(state, runtime=_runtime())
    assert update is not None
    msg = update["messages"][0]
    assert isinstance(msg, AIMessage)
    text = str(msg.content)
    assert "## 证据一致性摘要" in text
    assert "## 图表复现路径" in text
    assert "/scientific-vision/figures/embedding/batch-z/demo.svg" in text
    assert (msg.additional_kwargs or {}).get("deerflow_auto_scientific_format_enforced") is True


def test_after_model_skip_when_sections_already_exist():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-audit",
                        "name": "audit_cross_modal_consistency",
                        "args": {"narrative_text": "处理组条带下降约20%"},
                        "type": "tool_call",
                    }
                ],
                additional_kwargs={"deerflow_auto_scientific_closure": True},
            ),
            HumanMessage(
                content="<scientific_closure_summary>...</scientific_closure_summary>",
                additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
            ),
            AIMessage(
                content=(
                    "结论内容\n\n"
                    "## 证据一致性摘要\n"
                    "- supported: 2\n\n"
                    "## 图表复现路径\n"
                    "- /mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg"
                )
            ),
        ],
        "artifacts": [
            "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-z/audit.json",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg",
        ],
    }
    assert mw.after_model(state, runtime=_runtime()) is None


def test_after_model_skip_when_figure_section_has_count_stat():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-audit",
                        "name": "audit_cross_modal_consistency",
                        "args": {"narrative_text": "处理组条带下降约20%"},
                        "type": "tool_call",
                    }
                ],
                additional_kwargs={"deerflow_auto_scientific_closure": True},
            ),
            HumanMessage(
                content="<scientific_closure_summary>...</scientific_closure_summary>",
                additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
            ),
            AIMessage(
                content=(
                    "已按审计结果修订。\n\n"
                    "## 证据一致性摘要\n"
                    "- claims_total: 3\n"
                    "- supported: 2\n\n"
                    "## 图表复现路径\n"
                    "- generated_figures_count: 0\n"
                    "- 无（本轮未生成图表产物）"
                )
            ),
        ],
        "artifacts": ["/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-x/audit.json"],
    }
    assert mw.after_model(state, runtime=_runtime()) is None


def test_after_model_rewrites_when_figure_path_not_in_artifacts():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-audit",
                        "name": "audit_cross_modal_consistency",
                        "args": {"narrative_text": "处理组条带下降约20%"},
                        "type": "tool_call",
                    }
                ],
                additional_kwargs={"deerflow_auto_scientific_closure": True},
            ),
            HumanMessage(
                content="<scientific_closure_summary>...</scientific_closure_summary>",
                additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
            ),
            AIMessage(
                content=(
                    "结论内容\n\n"
                    "## 证据一致性摘要\n"
                    "- supported: 2\n\n"
                    "## 图表复现路径\n"
                    "- /mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/not-real.svg"
                )
            ),
        ],
        "artifacts": [
            "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-z/audit.json",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg",
        ],
    }

    update = mw.after_model(state, runtime=_runtime())
    assert update is not None
    msg = update["messages"][0]
    assert isinstance(msg, AIMessage)
    text = str(msg.content)
    assert "generated_figures_count" in text
    assert "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg" in text
    assert "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/not-real.svg" not in text


def test_after_model_rewrites_when_sections_exist_but_quality_too_low():
    mw = middleware_module.AutoScientificClosureMiddleware()
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-audit",
                        "name": "audit_cross_modal_consistency",
                        "args": {"narrative_text": "处理组条带下降约20%"},
                        "type": "tool_call",
                    }
                ],
                additional_kwargs={"deerflow_auto_scientific_closure": True},
            ),
            HumanMessage(
                content="<scientific_closure_summary>...</scientific_closure_summary>",
                additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
            ),
            AIMessage(
                content=(
                    "结论内容\n\n"
                    "## 证据一致性摘要\n"
                    "- 文本一致，见上文。\n\n"
                    "## 图表复现路径\n"
                    "- 路径同上。"
                )
            ),
        ],
        "artifacts": [
            "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-z/audit.json",
            "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg",
        ],
    }
    update = mw.after_model(state, runtime=_runtime())
    assert update is not None
    msg = update["messages"][0]
    assert isinstance(msg, AIMessage)
    text = str(msg.content)
    assert "generated_figures_count" in text
    assert "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-z/demo.svg" in text


def test_after_model_injects_risk_template_when_unsupported_exists(tmp_path):
    mw = middleware_module.AutoScientificClosureMiddleware()
    paths = Paths(base_dir=tmp_path)
    thread_id = "thread-risk"
    audit_path = "/mnt/user-data/outputs/scientific-vision/cross-modal-consistency/audit-risk/audit.json"
    audit_file = paths.resolve_virtual_path(thread_id, audit_path)
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text(
        json.dumps(
            {
                "summary": {
                    "claims_total": 3,
                    "supported": 1,
                    "partially_supported": 1,
                    "unsupported": 1,
                    "contradicted": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    figure_path = "/mnt/user-data/outputs/scientific-vision/figures/embedding/batch-risk/demo.svg"
    state = {
        "messages": [
            HumanMessage(
                content='<image_report model="x" mode="index" index_path="/mnt/user-data/outputs/scientific-vision/image-reports/indexes/index-abc.json">...</image_report>',
                additional_kwargs={"deerflow_injected": "image_report"},
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc-audit",
                        "name": "audit_cross_modal_consistency",
                        "args": {"narrative_text": "处理组条带下降约20%"},
                        "type": "tool_call",
                    }
                ],
                additional_kwargs={"deerflow_auto_scientific_closure": True},
            ),
            HumanMessage(
                content="<scientific_closure_summary>...</scientific_closure_summary>",
                additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
            ),
            AIMessage(
                content=(
                    "We prove this is definitive.\n\n"
                    "## 证据一致性摘要\n"
                    "- claims_total: 3\n"
                    "- supported: 1\n"
                    "- partially_supported: 1\n"
                    "- unsupported: 1\n"
                    "- contradicted: 1\n\n"
                    "## 图表复现路径\n"
                    f"- {figure_path}"
                )
            ),
        ],
        "artifacts": [
            audit_path,
            figure_path,
        ],
    }
    with patch("src.agents.middlewares.auto_scientific_closure_middleware.get_paths", return_value=paths):
        update = mw.after_model(state, runtime=_runtime(thread_id))
    assert update is not None
    msg = update["messages"][0]
    text = str(msg.content)
    assert "## 风险结论模板" in text
    assert "unsupported: 1" in text
    assert "contradicted: 1" in text
    assert "prove" not in text.lower()

