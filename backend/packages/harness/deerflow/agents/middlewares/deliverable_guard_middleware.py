"""Ensure file-based task contracts are satisfied before the agent can finish."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.session_state_middleware import build_session_state_snapshot, build_task_contract_snapshot
from deerflow.agents.thread_state import SessionStateData, TaskContractData


class DeliverableGuardState(AgentState):
    artifacts: NotRequired[list[str] | None]
    session_state: NotRequired[SessionStateData | None]


_REMINDER_TAG = "<deliverable_guard>"
_FORMAT_SUFFIXES: dict[str, set[str]] = {
    "html": {".html", ".htm"},
    "markdown": {".md", ".markdown"},
    "pptx": {".ppt", ".pptx"},
    "docx": {".doc", ".docx"},
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"},
    "csv": {".csv"},
    "json": {".json"},
}


def _artifact_matches_deliverable(artifact: str, deliverable: str) -> bool:
    suffix = PurePosixPath(artifact).suffix.lower()
    normalized = deliverable.lower()

    if normalized == "html report":
        return suffix in {".html", ".htm"}

    return True


def _artifact_matches_output_format(artifact: str, output_format: str | None) -> bool:
    if not output_format:
        return True

    suffix = PurePosixPath(artifact).suffix.lower()
    normalized = output_format.lower()
    return suffix in _FORMAT_SUFFIXES.get(normalized, {suffix})


def _artifacts_satisfy_deliverable(artifacts: list[str], deliverable: str, output_format: str | None) -> bool:
    return any(
        _artifact_matches_deliverable(artifact, deliverable) and _artifact_matches_output_format(artifact, output_format)
        for artifact in artifacts
    )


def _resolve_task_contract(state: DeliverableGuardState) -> TaskContractData:
    session_state = state.get("session_state") or build_session_state_snapshot(state) or {}
    task_contract = session_state.get("task_contract")
    if task_contract:
        return task_contract

    return build_task_contract_snapshot(list(state.get("messages") or [])) or {}


def _deliverable_requirement_unmet(state: DeliverableGuardState) -> tuple[bool, str | None]:
    task_contract = _resolve_task_contract(state)
    deliverable = task_contract.get("deliverable")
    output_format = task_contract.get("output_format")

    if not deliverable:
        return False, None

    if not (task_contract.get("must_save_output") or task_contract.get("must_present_output")):
        return False, None

    artifacts = state.get("artifacts") or []
    if artifacts and _artifacts_satisfy_deliverable(artifacts, deliverable, output_format):
        return False, None

    return True, deliverable


class DeliverableGuardMiddleware(AgentMiddleware[DeliverableGuardState]):
    """Push the agent back into execution when a required deliverable file is missing."""

    state_schema = DeliverableGuardState

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(self, state: DeliverableGuardState, runtime: Runtime) -> dict | None:  # noqa: ARG002
        messages = list(state.get("messages") or [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None
        if getattr(last_msg, "tool_calls", None):
            return None

        unmet, deliverable = _deliverable_requirement_unmet(state)
        if not unmet:
            return None

        reminder = HumanMessage(
            content=(
                f"{_REMINDER_TAG}\n"
                "The task contract is not complete yet.\n"
                f"- Required deliverable: {deliverable}\n"
                "- The currently presented files do not satisfy the required deliverable yet.\n"
                "- Do not stop after summarizing partial research.\n"
                "- Continue working until you create the final deliverable in /mnt/user-data/outputs and call present_files.\n"
                f"\n</{_REMINDER_TAG[1:]}"
            ),
        )
        return {"messages": [reminder], "jump_to": "model"}

    @override
    async def aafter_model(self, state: DeliverableGuardState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)
