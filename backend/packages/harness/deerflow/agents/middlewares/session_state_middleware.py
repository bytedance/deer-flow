"""Lightweight session-state reminder for long-running threads."""

from __future__ import annotations

import re
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import SessionStateData, TaskContractData
from deerflow.config.context_management_config import get_context_management_config

_UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)
_SESSION_STATE_TAG = "<session_state>"
_SUMMARY_PREFIXES = (
    "Here is a summary of the conversation to date:",
    "Here is the summary of the conversation to date:",
)
_DELIVERY_INTENT_MARKERS = (
    "生成",
    "输出",
    "导出",
    "保存",
    "产出",
    "给我一份",
    "写成",
    "生成一个",
    "生成一份",
    "generate",
    "create",
    "export",
    "save",
    "write",
    "produce",
    "present",
    "deliver",
)
_FORMAT_RULES: list[tuple[str, tuple[str, ...], str]] = [
    ("html", ("html", "htm", "网页", "web page", "single page", "单文件页面"), "HTML report"),
    ("markdown", ("markdown", "md", "markdown report"), "Markdown report"),
    ("pptx", ("pptx", "ppt", "powerpoint", "slides", "幻灯片", "演示文稿"), "Slide deck"),
    ("docx", ("docx", "doc", "word", "word document", "word文档"), "Word document"),
    ("pdf", ("pdf",), "PDF document"),
    ("image", ("image", "images", "png", "jpg", "jpeg", "webp", "svg", "图片", "海报", "配图"), "Image asset"),
    ("csv", ("csv",), "CSV file"),
    ("json", ("json",), "JSON file"),
]


class SessionStateMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    todos: NotRequired[list | None]
    artifacts: NotRequired[list[str] | None]
    session_state: NotRequired[SessionStateData | None]


def _truncate_text(value: str | None, *, limit: int) -> str | None:
    if not value:
        return None
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 3, 0)].rstrip()}..."


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        pending_string = ""
        for item in content:
            if isinstance(item, str):
                pending_string += item
                continue
            if pending_string:
                parts.append(pending_string)
                pending_string = ""
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        if pending_string:
            parts.append(pending_string)
        return "\n".join(part for part in parts if part)
    return str(content) if content is not None else ""


def _normalize_human_content(msg: HumanMessage) -> str:
    content = _extract_text(msg.content)
    if "<uploaded_files>" in content:
        content = _UPLOAD_BLOCK_RE.sub("", content).strip()
    return content.strip()


def _is_summary_like_human_message(msg: HumanMessage) -> bool:
    content = _normalize_human_content(msg)
    if not content:
        return True
    if "<system_reminder>" in content:
        return True
    if content.startswith(_SUMMARY_PREFIXES):
        return True
    if "<session_history_summary>" in content or "<session_state>" in content:
        return True
    return False


def _iter_real_human_messages(messages: list[Any]) -> list[HumanMessage]:
    return [msg for msg in messages if isinstance(msg, HumanMessage) and not _is_summary_like_human_message(msg)]


def _extract_latest_user_goal(messages: list[Any], *, limit: int) -> str | None:
    for msg in reversed(_iter_real_human_messages(messages)):
        content = _normalize_human_content(msg)
        if content:
            return _truncate_text(content, limit=limit)
    return None


def _extract_original_user_request(messages: list[Any], *, limit: int) -> str | None:
    real_human_messages = _iter_real_human_messages(messages)
    if not real_human_messages:
        return None
    return _truncate_text(_normalize_human_content(real_human_messages[0]), limit=limit)


def _has_delivery_intent(text: str) -> bool:
    lowered = text.lower()
    return any(marker in text or marker in lowered for marker in _DELIVERY_INTENT_MARKERS)


def _derive_task_contract(original_request: str | None, *, goal_limit: int) -> TaskContractData | None:
    if not original_request:
        return None

    lowered = original_request.lower()
    deliverable = None
    output_format = None
    scope = None
    quality_bar = None
    delivery_intent = _has_delivery_intent(original_request)

    for candidate_format, markers, candidate_deliverable in _FORMAT_RULES:
        if any(marker in lowered for marker in markers):
            output_format = candidate_format
            if delivery_intent:
                deliverable = candidate_deliverable
            break

    if deliverable is None and delivery_intent and ("报告" in original_request or "report" in lowered):
        deliverable = "report"

    chapter_match = re.search(r"(\d+)\s*(?:个)?章节", original_request)
    if chapter_match:
        scope = f"all {chapter_match.group(1)} chapters"
    elif "每个章节" in original_request or "all chapters" in lowered:
        scope = "all chapters"

    quality_markers = [
        "深入研究",
        "仔细研究",
        "carefully",
        "detailed",
        "deeply research",
    ]
    if any(marker in original_request or marker in lowered for marker in quality_markers):
        quality_bar = "detailed / careful research"

    contract: TaskContractData = {
        "original_request": _truncate_text(original_request, limit=goal_limit),
        "active_request": _truncate_text(original_request, limit=goal_limit),
        "scope": scope,
        "deliverable": deliverable,
        "output_format": output_format,
        "quality_bar": quality_bar,
        "must_save_output": bool(deliverable and delivery_intent),
        "must_present_output": bool(deliverable and delivery_intent),
    }
    if not any(contract.values()):
        return None
    return contract


def _merge_task_contracts(base: TaskContractData | None, override: TaskContractData | None) -> TaskContractData | None:
    if not base and not override:
        return None

    merged: TaskContractData = {}
    for key in (
        "original_request",
        "active_request",
        "scope",
        "deliverable",
        "output_format",
        "quality_bar",
        "must_save_output",
        "must_present_output",
    ):
        base_value = (base or {}).get(key)
        override_value = (override or {}).get(key)
        if override_value is not None:
            merged[key] = override_value
        elif base_value is not None:
            merged[key] = base_value

    if base and base.get("original_request"):
        merged["original_request"] = base["original_request"]
    if override and override.get("active_request"):
        merged["active_request"] = override["active_request"]
    elif base and base.get("active_request"):
        merged["active_request"] = base["active_request"]

    if not any(merged.values()):
        return None
    return merged


def _extract_latest_final_ai(messages: list[Any], *, limit: int) -> str | None:
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        if getattr(msg, "tool_calls", None):
            continue
        if not isinstance(msg.content, str):
            continue
        return _truncate_text(msg.content, limit=limit)
    return None


def _extract_active_todos(todos: list[dict] | None, *, max_items: int) -> list[str]:
    if not todos:
        return []
    active: list[str] = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = (todo.get("content") or "").strip()
        if not content or status == "completed":
            continue
        active.append(f"[{status}] {content}")
        if len(active) >= max_items:
            break
    return active


def _extract_recent_artifacts(artifacts: list[str] | None, *, max_items: int) -> list[str]:
    if not artifacts:
        return []
    return artifacts[-max_items:]


def build_session_state_snapshot(state: SessionStateMiddlewareState) -> SessionStateData | None:
    config = get_context_management_config().session_state
    if not config.enabled:
        return None

    messages = list(state.get("messages") or [])
    original_request = _extract_original_user_request(messages, limit=config.max_goal_chars)
    current_goal = _extract_latest_user_goal(messages, limit=config.max_goal_chars)
    original_contract = _derive_task_contract(original_request, goal_limit=config.max_goal_chars)
    latest_contract = _derive_task_contract(current_goal, goal_limit=config.max_goal_chars)
    session_state: SessionStateData = {
        "current_goal": current_goal,
        "task_contract": _merge_task_contracts(original_contract, latest_contract),
        "active_todos": _extract_active_todos(state.get("todos"), max_items=config.max_items),
        "recent_artifacts": _extract_recent_artifacts(state.get("artifacts"), max_items=config.max_items),
        "last_assistant_response": _extract_latest_final_ai(messages, limit=config.max_response_chars),
    }

    if not any(session_state.values()):
        return None
    return session_state


def _format_session_state(session_state: SessionStateData) -> str | None:
    lines: list[str] = [_SESSION_STATE_TAG, "Current execution state from this thread:"]

    current_goal = session_state.get("current_goal")
    if current_goal:
        lines.extend(["", f"Goal: {current_goal}"])

    task_contract = session_state.get("task_contract") or {}
    original_request = task_contract.get("original_request")
    if original_request:
        lines.extend(["", f"Original request contract: {original_request}"])
    active_request = task_contract.get("active_request")
    if active_request and active_request != original_request:
        lines.extend(["", f"Latest user requirement: {active_request}"])
    deliverable = task_contract.get("deliverable")
    output_format = task_contract.get("output_format")
    scope = task_contract.get("scope")
    quality_bar = task_contract.get("quality_bar")
    if deliverable or output_format or scope or quality_bar:
        lines.extend(["", "Required output contract:"])
        if deliverable:
            lines.append(f"- Deliverable: {deliverable}")
        if output_format:
            lines.append(f"- Output format: {output_format.upper()}")
        if scope:
            lines.append(f"- Scope: {scope}")
        if quality_bar:
            lines.append(f"- Quality bar: {quality_bar}")
        if task_contract.get("must_save_output"):
            lines.append("- Must save the final deliverable as a file under /mnt/user-data/outputs")
        if task_contract.get("must_present_output"):
            lines.append("- Must present the final deliverable with present_files before ending")

    active_todos = session_state.get("active_todos") or []
    if active_todos:
        lines.extend(["", "Open work items:"])
        lines.extend(f"- {item}" for item in active_todos)

    recent_artifacts = session_state.get("recent_artifacts") or []
    if recent_artifacts:
        lines.extend(["", "Recent output files:"])
        lines.extend(f"- {item}" for item in recent_artifacts)

    last_response = session_state.get("last_assistant_response")
    if last_response:
        lines.extend(["", f"Last final response: {last_response}"])

    lines.append(f"\n</{_SESSION_STATE_TAG[1:]}")
    return "\n".join(lines)


def _session_state_visible(messages: list[Any]) -> bool:
    for msg in messages:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str) and _SESSION_STATE_TAG in msg.content:
            return True
    return False


class SessionStateMiddleware(AgentMiddleware[SessionStateMiddlewareState]):
    """Inject and maintain lightweight execution-state context for long sessions."""

    state_schema = SessionStateMiddlewareState

    @override
    def before_model(self, state: SessionStateMiddlewareState, runtime: Runtime) -> dict[str, Any] | None:  # noqa: ARG002
        config = get_context_management_config().session_state
        if not config.enabled:
            return None

        messages = list(state.get("messages") or [])
        if len(messages) < config.inject_when_message_count_at_least:
            return None
        if _session_state_visible(messages):
            return None

        session_state = state.get("session_state")
        if not session_state:
            return None

        content = _format_session_state(session_state)
        if not content:
            return None

        return {"messages": [HumanMessage(content=content)]}

    @override
    async def abefore_model(self, state: SessionStateMiddlewareState, runtime: Runtime) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    @override
    def after_agent(self, state: SessionStateMiddlewareState, runtime: Runtime) -> dict | None:  # noqa: ARG002
        session_state = build_session_state_snapshot(state)
        if session_state is None:
            return None
        return {"session_state": session_state}
