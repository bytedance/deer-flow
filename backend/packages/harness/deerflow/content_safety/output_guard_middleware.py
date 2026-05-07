"""OutputGuardMiddleware — scans AI responses before they reach the user."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.content_safety.provider import ContentSafetyProvider, ContentSafetyRequest
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


def _get_tenant_from_runtime(runtime: Runtime | None) -> str:
    """Extract tenant_id from runtime context, falling back to ContextVar."""
    if runtime is not None:
        ctx = getattr(runtime, "context", None) or {}
        if isinstance(ctx, dict) and ctx.get("tenant_id"):
            return ctx["tenant_id"]
    from deerflow.config.tenant import get_current_tenant_id

    return get_current_tenant_id()


class OutputGuardMiddleware(AgentMiddleware[AgentState]):
    """Scans AI responses for harmful content and PII before they reach the user.

    Uses the ``after_agent`` hook so content is checked after the model
    produces output but before the response is finalized.
    """

    def __init__(
        self,
        provider: ContentSafetyProvider,
        *,
        block_on_harmful: bool = False,
        pii_action: str = "mask",
        audit_storage: object | None = None,
    ) -> None:
        self.provider = provider
        self.block_on_harmful = block_on_harmful
        self.pii_action = pii_action
        self.audit_storage = audit_storage

    def _get_last_ai_message(self, state: AgentState) -> AIMessage | None:
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg
        return None

    def _evaluate(self, text: str, thread_id: str | None, tenant_id: str = "default", *, actor_user_id: str | None = None) -> dict | None:
        request = ContentSafetyRequest(text=text, role="assistant", thread_id=thread_id)
        try:
            decision = self.provider.evaluate(request)
        except Exception:
            logger.exception("Output guard provider error")
            return None

        self._log_audit(text, decision, thread_id, "output", "assistant", tenant_id=tenant_id, actor_user_id=actor_user_id)

        if not decision.allowed and self.block_on_harmful:
            logger.warning("Output guard blocked AI response: %s", decision.reasons)
            return {"messages": [AIMessage(content="[Response blocked by safety policy]")]}

        if decision.sanitized_text and decision.sanitized_text != text:
            logger.info("Output guard sanitized PII in AI response: %s", decision.flagged_categories)
            return {"messages": [AIMessage(content=decision.sanitized_text)]}

        return None

    def _log_audit(self, text: str, decision, thread_id: str | None, direction: str, role: str, *, tenant_id: str = "default", actor_user_id: str | None = None) -> None:
        if self.audit_storage is None:
            return
        try:
            from deerflow.content_safety.log_storage import AuditLogEntry

            entry = AuditLogEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                tenant_id=tenant_id,
                thread_id=thread_id,
                actor_user_id=actor_user_id,
                direction=direction,
                role=role,
                original_text=text,
                sanitized_text=decision.sanitized_text,
                allowed=decision.allowed,
                flagged_categories=decision.flagged_categories,
                reasons=decision.reasons,
                provider=getattr(self.provider, "name", ""),
            )
            self.audit_storage.add_entry(entry)
        except Exception:
            logger.exception("Failed to write audit log entry")

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        msg = self._get_last_ai_message(state)
        if msg is None:
            return None
        content = msg.content
        if isinstance(content, list):
            text_parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in content]
            text = " ".join(text_parts)
        else:
            text = str(content)
        if not text.strip():
            return None
        tenant_id = _get_tenant_from_runtime(runtime)
        user_id = get_effective_user_id()
        return self._evaluate(text, None, tenant_id, actor_user_id=user_id)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        msg = self._get_last_ai_message(state)
        if msg is None:
            return None
        content = msg.content
        if isinstance(content, list):
            text_parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in content]
            text = " ".join(text_parts)
        else:
            text = str(content)
        if not text.strip():
            return None

        tenant_id = _get_tenant_from_runtime(runtime)
        user_id = get_effective_user_id()

        request = ContentSafetyRequest(text=text, role="assistant")
        try:
            decision = await self.provider.aevaluate(request)
        except Exception:
            logger.exception("Output guard provider error (async)")
            return None

        self._log_audit(text, decision, None, "output", "assistant", tenant_id=tenant_id, actor_user_id=user_id)

        if not decision.allowed and self.block_on_harmful:
            logger.warning("Output guard blocked AI response: %s", decision.reasons)
            return {"messages": [AIMessage(content="[Response blocked by safety policy]")]}

        if decision.sanitized_text and decision.sanitized_text != text:
            logger.info("Output guard sanitized PII in AI response: %s", decision.flagged_categories)
            return {"messages": [AIMessage(content=decision.sanitized_text)]}

        return None
