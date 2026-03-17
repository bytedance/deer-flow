"""Middleware for automatic scientific audit/figure closure before final conclusions."""

from __future__ import annotations

import json
import re
import uuid
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from src.config.paths import get_paths

_INDEX_PATH_RE = re.compile(r'index_path="([^"]*)"')
_AUDIT_COUNTS_RE = re.compile(
    r"claims=(?P<claims>\d+), supported=(?P<supported>\d+), partial=(?P<partial>\d+), unsupported=(?P<unsupported>\d+), contradicted=(?P<contradicted>\d+)"
)
_OUTPUT_PATH_IN_LINE_RE = re.compile(r"(/mnt/user-data/outputs/\S+)")
_SUMMARY_SECTION_TITLE = "## 证据一致性摘要"
_FIGURE_SECTION_TITLE = "## 图表复现路径"
_RISK_SECTION_TITLE = "## 风险结论模板"
_STRONG_CLAIM_REWRITES: tuple[tuple[str, str], ...] = (
    (r"\b(demonstrates|demonstrate|demonstrated)\b", "suggests"),
    (r"\b(proves|prove|proved)\b", "is consistent with"),
    (r"\b(definitive|certainly|always)\b", "preliminary"),
    (r"\b(guarantees|guarantee)\b", "supports"),
    (r"\b(causes|cause|caused)\b", "is associated with"),
)


class AutoScientificClosureMiddlewareState(AgentState):
    """Compatible with ThreadState."""

    artifacts: NotRequired[list[str] | None]


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _has_image_report_context(messages: list) -> bool:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            injected = (msg.additional_kwargs or {}).get("deerflow_injected")
            if injected == "image_report":
                return True
            if "<image_report" in str(msg.content):
                return True
    return False


def _latest_image_report_meta(messages: list) -> tuple[str | None, list[str]]:
    index_path: str | None = None
    report_paths: list[str] = []
    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        if (msg.additional_kwargs or {}).get("deerflow_injected") != "image_report":
            continue
        kwargs = msg.additional_kwargs or {}
        candidate_reports = kwargs.get("report_paths")
        if isinstance(candidate_reports, list):
            report_paths = [p for p in candidate_reports if isinstance(p, str)]
        content = str(msg.content)
        m = _INDEX_PATH_RE.search(content)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                index_path = candidate
        break
    return index_path, report_paths


def _collect_analysis_paths(artifacts: list[str]) -> list[str]:
    paths: list[str] = []
    for path in artifacts:
        if not isinstance(path, str):
            continue
        if "/scientific-vision/raw-data/" in path and path.endswith("/analysis.json"):
            paths.append(path)
    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _resolve_thread_id(runtime: Runtime) -> str | None:
    ctx = getattr(runtime, "context", None)
    if ctx is not None and hasattr(ctx, "get"):
        configurable = ctx.get("configurable") or {}
        if isinstance(configurable, dict):
            thread_id = configurable.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        raw = ctx.get("thread_id")
        if isinstance(raw, str) and raw:
            return raw
    return None


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        if not isinstance(path, str):
            continue
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _collect_figure_paths(artifacts: list[str], *, max_paths: int = 12) -> list[str]:
    paths = [
        a
        for a in artifacts
        if isinstance(a, str) and "/scientific-vision/figures/" in a and (a.endswith(".svg") or a.endswith(".pdf"))
    ]
    return _dedupe_paths(paths)[-max_paths:]


def _latest_audit_path(artifacts: list[str]) -> str | None:
    for path in reversed(artifacts):
        if isinstance(path, str) and "/scientific-vision/cross-modal-consistency/" in path and path.endswith("/audit.json"):
            return path
    return None


def _latest_injected_summary_index(messages: list) -> int:
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if not isinstance(msg, HumanMessage):
            continue
        if (msg.additional_kwargs or {}).get("deerflow_injected") == "auto_scientific_closure_summary":
            return idx
    return -1


def _latest_user_human_index(messages: list) -> int:
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if not isinstance(msg, HumanMessage):
            continue
        if (msg.additional_kwargs or {}).get("deerflow_injected"):
            continue
        return idx
    return -1


def _extract_section_body(text: str, section_title: str) -> str | None:
    bare = section_title.replace("#", "").strip()
    pattern = rf"(?ms)^##\s*{re.escape(bare)}\s*\n(?P<body>.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, text)
    if not m:
        return None
    return str(m.group("body") or "").strip()


def _remove_section(text: str, section_title: str) -> str:
    bare = section_title.replace("#", "").strip()
    pattern = rf"(?ms)^##\s*{re.escape(bare)}\s*\n.*?(?=^##\s+|\Z)"
    cleaned = re.sub(pattern, "", text)
    return cleaned.strip()


def _extract_output_paths_from_line(line: str) -> list[str]:
    candidates = _OUTPUT_PATH_IN_LINE_RE.findall(line)
    out: list[str] = []
    for raw in candidates:
        cleaned = raw.strip().strip("`'\"),.;:!?]}，。；：！？）】")
        if cleaned:
            out.append(cleaned)
    return out


def _downgrade_strong_conclusions(text: str) -> str:
    output = text
    for pattern, replacement in _STRONG_CLAIM_REWRITES:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    return output


def _line_has_known_artifact_path(line: str, artifact_set: set[str]) -> bool:
    if not artifact_set:
        return False
    for path in _extract_output_paths_from_line(line):
        if path in artifact_set:
            return True
    return False


def _is_valid_summary_item_line(line: str, artifact_set: set[str]) -> bool:
    s = line.strip()
    if not s:
        return False
    low = s.lower()
    keys = ("claims_total", "supported", "partially_supported", "unsupported", "contradicted")
    if any(k in low for k in keys):
        return True
    return _line_has_known_artifact_path(s, artifact_set)


def _is_valid_figure_item_line(line: str, artifact_set: set[str]) -> bool:
    s = line.strip()
    if not s:
        return False
    low = s.lower()
    if "generated_figures_count" in low or "figure_count" in low:
        return True
    for path in _extract_output_paths_from_line(s):
        if path not in artifact_set:
            continue
        if "/scientific-vision/figures/" in path and (path.endswith(".svg") or path.endswith(".pdf")):
            return True
    return False


def _section_quality_ok(body: str | None, *, checker: str, artifact_set: set[str]) -> bool:
    if body is None:
        return False
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return False
    if checker == "summary":
        return any(_is_valid_summary_item_line(ln, artifact_set) for ln in lines)
    if checker == "figure":
        return any(_is_valid_figure_item_line(ln, artifact_set) for ln in lines)
    return False


def _load_audit_summary_from_artifact(*, thread_id: str | None, audit_path: str | None) -> dict[str, int] | None:
    if not thread_id or not audit_path:
        return None
    try:
        physical = get_paths().resolve_virtual_path(thread_id, audit_path)
        payload = json.loads(physical.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            return None
        return {
            "claims_total": int(summary.get("claims_total", 0)),
            "supported": int(summary.get("supported", 0)),
            "partially_supported": int(summary.get("partially_supported", 0)),
            "unsupported": int(summary.get("unsupported", 0)),
            "contradicted": int(summary.get("contradicted", 0)),
        }
    except Exception:
        return None


def _load_audit_summary_from_tool_messages(messages: list, assistant_idx: int) -> dict[str, int] | None:
    for msg in messages[assistant_idx + 1 :]:
        if not isinstance(msg, ToolMessage):
            continue
        content = str(msg.content or "")
        m = _AUDIT_COUNTS_RE.search(content)
        if not m:
            continue
        return {
            "claims_total": int(m.group("claims")),
            "supported": int(m.group("supported")),
            "partially_supported": int(m.group("partial")),
            "unsupported": int(m.group("unsupported")),
            "contradicted": int(m.group("contradicted")),
        }
    return None


class AutoScientificClosureMiddleware(AgentMiddleware[AutoScientificClosureMiddlewareState]):
    """Auto-trigger scientific consistency audit and reproducible figure generation.

    Behavior:
    - Runs after each model response.
    - If the model is about to provide a final textual conclusion (no tool calls),
      and scientific evidence context exists (`<image_report>`), this middleware
      injects tool calls to enforce an automatic closure loop:
        1) `audit_cross_modal_consistency`
        2) `generate_reproducible_figure` for each discovered analysis artifact
    """

    state_schema = AutoScientificClosureMiddlewareState

    def __init__(self, max_figure_calls: int = 4):
        super().__init__()
        self.max_figure_calls = max(1, min(12, int(max_figure_calls)))

    def _already_forced_once(self, messages: list) -> bool:
        for msg in reversed(messages[-20:]):
            if isinstance(msg, AIMessage):
                if (msg.additional_kwargs or {}).get("deerflow_auto_scientific_closure"):
                    return True
        return False

    def _latest_auto_closure_message(self, messages: list) -> AIMessage | None:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and (msg.additional_kwargs or {}).get("deerflow_auto_scientific_closure"):
                return msg
        return None

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        tool_calls = getattr(assistant_msg, "tool_calls", None)
        if not tool_calls:
            return False

        tool_call_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False

        completed_tool_ids: set[str] = set()
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and isinstance(msg.tool_call_id, str) and msg.tool_call_id:
                completed_tool_ids.add(msg.tool_call_id)
        return tool_call_ids.issubset(completed_tool_ids)

    def _already_injected_summary(self, messages: list, assistant_msg: AIMessage) -> bool:
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False
        for msg in messages[assistant_idx + 1 :]:
            if not isinstance(msg, HumanMessage):
                continue
            injected = (msg.additional_kwargs or {}).get("deerflow_injected")
            if injected == "auto_scientific_closure_summary":
                return True
            if "<scientific_closure_summary>" in str(msg.content):
                return True
        return False

    def _needs_cross_modal_audit(self, artifacts: list[str]) -> bool:
        return not any(isinstance(a, str) and "/scientific-vision/cross-modal-consistency/" in a for a in artifacts)

    def _needs_repro_figures(self, artifacts: list[str], analysis_paths: list[str]) -> bool:
        if not analysis_paths:
            return False
        return not any(isinstance(a, str) and "/scientific-vision/figures/" in a for a in artifacts)

    def _build_tool_calls(self, *, narrative_text: str, index_path: str | None, report_paths: list[str], analysis_paths: list[str], need_audit: bool, need_figures: bool) -> list[dict]:
        tool_calls: list[dict] = []
        if need_audit:
            args: dict = {"narrative_text": narrative_text, "run_vision_recheck": True, "max_claims": 25}
            if index_path:
                args["index_path"] = index_path
            if report_paths:
                args["report_paths"] = report_paths[:12]
            if analysis_paths:
                args["analysis_paths"] = analysis_paths[:12]
            tool_calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:20]}",
                    "name": "audit_cross_modal_consistency",
                    "args": args,
                    "type": "tool_call",
                }
            )

        if need_figures:
            for analysis_path in analysis_paths[: self.max_figure_calls]:
                tool_calls.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:20]}",
                        "name": "generate_reproducible_figure",
                        "args": {"analysis_path": analysis_path, "language": "python"},
                        "type": "tool_call",
                    }
                )
        return tool_calls

    def _auto_close(self, state: AutoScientificClosureMiddlewareState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        if getattr(last, "tool_calls", None):
            return None
        if (last.additional_kwargs or {}).get("deerflow_auto_scientific_closure"):
            return None
        if self._already_forced_once(messages):
            return None
        if not _has_image_report_context(messages):
            return None

        artifacts = state.get("artifacts") or []
        if not isinstance(artifacts, list):
            artifacts = []
        analysis_paths = _collect_analysis_paths(artifacts)
        need_audit = self._needs_cross_modal_audit(artifacts)
        need_figures = self._needs_repro_figures(artifacts, analysis_paths)
        if not need_audit and not need_figures:
            return None

        narrative_text = _extract_text(last.content)
        if len(narrative_text.strip()) < 24:
            return None

        index_path, report_paths = _latest_image_report_meta(messages)
        tool_calls = self._build_tool_calls(
            narrative_text=narrative_text,
            index_path=index_path,
            report_paths=report_paths,
            analysis_paths=analysis_paths,
            need_audit=need_audit,
            need_figures=need_figures,
        )
        if not tool_calls:
            return None

        updated = last.model_copy(
            update={
                "content": "",
                "tool_calls": tool_calls,
                "additional_kwargs": {
                    **(last.additional_kwargs or {}),
                    "deerflow_auto_scientific_closure": True,
                    "deerflow_auto_scientific_original_response": narrative_text[:3000],
                },
            }
        )
        return {"messages": [updated]}

    def _inject_final_summary_template(self, state: AutoScientificClosureMiddlewareState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        closure_ai = self._latest_auto_closure_message(messages)
        if closure_ai is None:
            return None
        if self._already_injected_summary(messages, closure_ai):
            return None
        if not self._all_tools_completed(messages, closure_ai):
            return None

        artifacts = state.get("artifacts") or []
        if not isinstance(artifacts, list):
            artifacts = []

        try:
            closure_idx = messages.index(closure_ai)
        except ValueError:
            closure_idx = -1

        thread_id = _resolve_thread_id(runtime)
        audit_path = _latest_audit_path(artifacts)
        audit_summary = _load_audit_summary_from_artifact(thread_id=thread_id, audit_path=audit_path)
        if audit_summary is None and closure_idx >= 0:
            audit_summary = _load_audit_summary_from_tool_messages(messages, closure_idx)
        if audit_summary is None:
            audit_summary = {
                "claims_total": 0,
                "supported": 0,
                "partially_supported": 0,
                "unsupported": 0,
                "contradicted": 0,
            }

        figure_paths = _collect_figure_paths(artifacts, max_paths=12)
        original_response = (closure_ai.additional_kwargs or {}).get("deerflow_auto_scientific_original_response")
        original_text = original_response if isinstance(original_response, str) else ""

        summary_lines = [
            "<scientific_closure_summary>",
            "你刚完成自动科学闭环（cross-modal consistency audit + reproducible figure generation）。",
            "现在请基于以下结果输出最终回答，并严格在结尾包含两个固定小节：",
            "1) `## 证据一致性摘要`",
            "2) `## 图表复现路径`",
            "",
            "可用闭环结果：",
            f"- 审计 artifact: {audit_path or 'unknown'}",
            "- 审计统计："
            f" claims_total={audit_summary.get('claims_total', 0)},"
            f" supported={audit_summary.get('supported', 0)},"
            f" partially_supported={audit_summary.get('partially_supported', 0)},"
            f" unsupported={audit_summary.get('unsupported', 0)},"
            f" contradicted={audit_summary.get('contradicted', 0)}",
            "- 可复现图路径：",
        ]
        if figure_paths:
            summary_lines.extend([f"  - {p}" for p in figure_paths])
        else:
            summary_lines.append("  - 无（本轮未生成图表产物）")

        if original_text.strip():
            summary_lines.extend(
                [
                    "",
                    "闭环前草稿结论（可参考并修订）：",
                    original_text[:2500],
                ]
            )

        summary_lines.extend(
            [
                "",
                "强约束：",
                "- 若 `unsupported` 或 `contradicted` > 0，必须在结论中明确标注风险与不确定性。",
                "- 若 `unsupported` 或 `contradicted` > 0，必须追加 `## 风险结论模板`，并禁止强结论措辞。",
                "- `图表复现路径` 小节必须列出本轮真实 artifact 路径（无则写无）。",
                "- 不要省略这两个小节。",
                "</scientific_closure_summary>",
            ]
        )

        msg = HumanMessage(
            content="\n".join(summary_lines),
            additional_kwargs={"deerflow_injected": "auto_scientific_closure_summary"},
        )
        return {"messages": [msg]}

    def _enforce_final_answer_format(self, state: AutoScientificClosureMiddlewareState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        if getattr(last, "tool_calls", None):
            return None
        if (last.additional_kwargs or {}).get("deerflow_auto_scientific_format_enforced"):
            return None

        summary_idx = _latest_injected_summary_index(messages)
        if summary_idx < 0:
            return None

        # If a real user message appears after summary injection, this is likely a new turn;
        # do not enforce old closure constraints on unrelated replies.
        user_idx = _latest_user_human_index(messages)
        if user_idx > summary_idx:
            return None

        artifacts = state.get("artifacts") or []
        if not isinstance(artifacts, list):
            artifacts = []
        artifact_set = {a for a in artifacts if isinstance(a, str)}

        content_text = _extract_text(last.content)
        summary_body = _extract_section_body(content_text, _SUMMARY_SECTION_TITLE)
        figure_body = _extract_section_body(content_text, _FIGURE_SECTION_TITLE)
        has_summary = summary_body is not None
        has_figures = figure_body is not None
        summary_quality_ok = _section_quality_ok(summary_body, checker="summary", artifact_set=artifact_set)
        figure_quality_ok = _section_quality_ok(figure_body, checker="figure", artifact_set=artifact_set)

        audit_path = _latest_audit_path(artifacts)
        figure_paths = _collect_figure_paths(artifacts, max_paths=12)

        thread_id = _resolve_thread_id(runtime)
        audit_summary = _load_audit_summary_from_artifact(thread_id=thread_id, audit_path=audit_path)
        if audit_summary is None:
            audit_summary = {
                "claims_total": 0,
                "supported": 0,
                "partially_supported": 0,
                "unsupported": 0,
                "contradicted": 0,
            }

        risk_required = int(audit_summary.get("unsupported", 0)) > 0 or int(audit_summary.get("contradicted", 0)) > 0
        risk_body = _extract_section_body(content_text, _RISK_SECTION_TITLE)
        risk_quality_ok = bool(risk_body and any(token in risk_body.lower() for token in ("风险", "fail-close", "不确定", "保守")))
        if has_summary and has_figures and summary_quality_ok and figure_quality_ok and (not risk_required or risk_quality_ok):
            return None

        base_answer = content_text.strip()
        if has_summary:
            base_answer = _remove_section(base_answer, _SUMMARY_SECTION_TITLE)
        if has_figures:
            base_answer = _remove_section(base_answer, _FIGURE_SECTION_TITLE)
        if risk_body is not None:
            base_answer = _remove_section(base_answer, _RISK_SECTION_TITLE)
        original = base_answer.strip()
        if not original:
            original = "（模型原始回答为空或闭环小节质量不足，已由系统进行结构化补全）"
        if risk_required:
            original = _downgrade_strong_conclusions(original)

        lines: list[str] = [original, ""]
        if risk_required:
            lines.extend(
                [
                    _RISK_SECTION_TITLE,
                    "- 状态: 风险保守（fail-close）",
                    "- 触发条件: unsupported/contradicted claim present",
                    f"- unsupported: {audit_summary.get('unsupported', 0)}",
                    f"- contradicted: {audit_summary.get('contradicted', 0)}",
                    "- 约束: 禁止输出强因果或确定性结论，需补充验证与证据。",
                    "",
                ]
            )

        if (not has_summary) or (not summary_quality_ok):
            lines.extend(
                [
                    _SUMMARY_SECTION_TITLE,
                    f"- claims_total: {audit_summary.get('claims_total', 0)}",
                    f"- supported: {audit_summary.get('supported', 0)}",
                    f"- partially_supported: {audit_summary.get('partially_supported', 0)}",
                    f"- unsupported: {audit_summary.get('unsupported', 0)}",
                    f"- contradicted: {audit_summary.get('contradicted', 0)}",
                    f"- audit_artifact: {audit_path or 'unknown'}",
                    "- 说明：若 unsupported 或 contradicted > 0，请将结论视为有风险并补充不确定性说明。",
                    "",
                ]
            )

        if (not has_figures) or (not figure_quality_ok):
            lines.append(_FIGURE_SECTION_TITLE)
            lines.append(f"- generated_figures_count: {len(figure_paths)}")
            if figure_paths:
                lines.extend([f"- {p}" for p in figure_paths])
            else:
                lines.append("- 无（本轮未生成图表产物）")

        updated = last.model_copy(
            update={
                "content": "\n".join(lines).strip(),
                "additional_kwargs": {
                    **(last.additional_kwargs or {}),
                    "deerflow_auto_scientific_format_enforced": True,
                },
            }
        )
        return {"messages": [updated]}

    @override
    def before_model(self, state: AutoScientificClosureMiddlewareState, runtime: Runtime) -> dict | None:
        return self._inject_final_summary_template(state, runtime)

    @override
    async def abefore_model(self, state: AutoScientificClosureMiddlewareState, runtime: Runtime) -> dict | None:
        return self._inject_final_summary_template(state, runtime)

    @override
    def after_model(self, state: AutoScientificClosureMiddlewareState, runtime: Runtime) -> dict | None:
        closure = self._auto_close(state)
        if closure is not None:
            return closure
        return self._enforce_final_answer_format(state, runtime)

    @override
    async def aafter_model(self, state: AutoScientificClosureMiddlewareState, runtime: Runtime) -> dict | None:
        closure = self._auto_close(state)
        if closure is not None:
            return closure
        return self._enforce_final_answer_format(state, runtime)

