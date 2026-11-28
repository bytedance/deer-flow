"""Reject a validated version-1 pause without reviving version-1 approvals."""

from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from deerflow.approvals.message_cleanup import reject_tool_calls


class HitlApprovalMiddleware(AgentMiddleware):
    """Keep the historical graph-node name for one worker-bound recovery.

    Only worker-recovered, reject-only legacy actions may assemble this hook.
    It never asks for approval or executes a tool. After the original node
    replays once, normal operation approval owns the rest of this graph.
    """

    def __init__(self, *, tool_names: set[str]) -> None:
        self.tool_names = frozenset(tool_names)
        self._pending = True

    def release_policy_parameters(self) -> dict[str, Any]:
        return {"legacy_recovery": True, "tool_names": sorted(self.tool_names)}

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not self._pending:
            return None
        self._pending = False
        messages = state.get("messages", []) if isinstance(state, Mapping) else state.messages
        last = messages[-1] if messages else None
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return None
        targets = [call for call in last.tool_calls if call["name"] in self.tool_names]
        # A changed replay must not execute an operation in place of the pause
        # the user rejected. Keep no calls when none of its names still match.
        targets = targets or last.tool_calls
        note = "The legacy approval calls were rejected and not executed. Do not retry unless the user explicitly asks."
        return reject_tool_calls(last, targets, note)

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)
