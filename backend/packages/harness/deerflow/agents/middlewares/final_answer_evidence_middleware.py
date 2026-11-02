"""Record deterministic, lead-only evidence after a final answer."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.final_answer_evidence import SCHEMA, build_final_answer_evidence, event_changes
from deerflow.agents.middlewares.model_response import has_tool_call_intent, has_visible_content

logger = logging.getLogger(__name__)

DEDUPE_CAPACITY = 1000


class FinalAnswerEvidenceMiddleware(AgentMiddleware[AgentState]):
    """Emit advisory evidence for the lead's terminal visible answer.

    This is intentionally observational: it never rewrites messages, prompts,
    tool calls, or the run outcome. Subagent chains do not install it, and the
    journal itself is the run-scoped trust boundary for lead attribution.
    """

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "evidence_schema": SCHEMA,
            "dedupe_capacity": DEDUPE_CAPACITY,
            "emission": "lead_only_terminal_visible_answer",
        }

    def __init__(self) -> None:
        super().__init__()
        # A provider retry or middleware re-entry can observe the same completed
        # AIMessage twice. Bound dedupe state by run plus final message identity;
        # this is process-local only, and is not a durability claim.
        self._recorded: set[tuple[str, str]] = set()
        self._recorded_order: deque[tuple[str, str]] = deque()
        self._recorded_lock = threading.Lock()

    def _remember(self, key: tuple[str, str]) -> None:
        if key in self._recorded:
            return
        if len(self._recorded_order) >= DEDUPE_CAPACITY:
            self._recorded.discard(self._recorded_order.popleft())
        self._recorded.add(key)
        self._recorded_order.append(key)

    def _claim(self, key: tuple[str, str]) -> bool:
        """Atomically claim a final answer; the sync and async hooks share it."""
        with self._recorded_lock:
            if key in self._recorded:
                return False
            self._remember(key)
            return True

    def _release(self, key: tuple[str, str]) -> None:
        with self._recorded_lock:
            if key not in self._recorded:
                return
            self._recorded.remove(key)
            try:
                self._recorded_order.remove(key)
            except ValueError:
                pass

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._record(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._record(state, runtime)

    def _record(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None
        final = messages[-1]
        if has_tool_call_intent(final) or not has_visible_content(final):
            return None

        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return None
        journal_run_id = getattr(journal, "run_id", None)
        run_id = journal_run_id if isinstance(journal_run_id, str) and journal_run_id else None
        final_identity = final.id if isinstance(final.id, str) else ""
        evidence = build_final_answer_evidence(final, messages, context=context)
        dedupe_key = (run_id, final_identity or evidence["final_content_sha256"])
        if run_id is not None and final_identity and not self._claim(dedupe_key):
            return None
        try:
            journal.record_final_answer_evidence(event_changes(evidence))
        except Exception:  # noqa: BLE001
            if run_id is not None and final_identity:
                self._release(dedupe_key)
            logger.warning("Failed to record run.answer_evidence event", exc_info=True)
        return None
