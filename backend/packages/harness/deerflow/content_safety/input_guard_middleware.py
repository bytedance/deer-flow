"""InputGuardMiddleware — scans user messages before agent processing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
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


class InputGuardMiddleware(AgentMiddleware[AgentState]):
    """Scans user messages for harmful content and PII before the agent processes them.

    Uses the ``before_agent`` hook so content is checked before any other
    middleware or the model sees it.
    """

    def __init__(
        self,
        provider: ContentSafetyProvider,
        *,
        block_on_harmful: bool = True,
        injection_provider: ContentSafetyProvider | None = None,
        audit_storage: object | None = None,
    ) -> None:
        self.provider = provider
        self.block_on_harmful = block_on_harmful
        self.injection_provider = injection_provider
        self.audit_storage = audit_storage

    def _get_last_user_message(self, state: AgentState) -> HumanMessage | None:
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return msg
        return None

    def _evaluate(self, text: str, thread_id: str | None, tenant_id: str = "default", *, actor_user_id: str | None = None) -> dict | None:
        request = ContentSafetyRequest(text=text, role="user", thread_id=thread_id)
        try:
            decision = self.provider.evaluate(request)
        except Exception:
            logger.exception("Input guard provider error")
            return None

        self._log_audit(text, decision, thread_id, "input", "user", tenant_id=tenant_id, actor_user_id=actor_user_id)

        if not decision.allowed and self.block_on_harmful:
            logger.warning("Input guard blocked user message: %s", decision.reasons)
            return {"messages": [HumanMessage(content=f"[Content blocked by safety policy: {'; '.join(decision.reasons)}]")]}

        if decision.sanitized_text and decision.sanitized_text != text:
            logger.info("Input guard sanitized PII in user message: %s", decision.flagged_categories)
            return {"messages": [HumanMessage(content=decision.sanitized_text)]}

        return None

    def _log_audit(self, text: str, decision, thread_id: str | None, direction: str, role: str, *, provider_name: str = "", tenant_id: str = "default", actor_user_id: str | None = None) -> None:
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
                provider=provider_name or getattr(self.provider, "name", ""),
            )
            self.audit_storage.add_entry(entry)
        except Exception:
            logger.exception("Failed to write audit log entry")

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        msg = self._get_last_user_message(state)
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

        if self.injection_provider is not None:
            injection_result = self._check_injection(text, tenant_id, actor_user_id=user_id)
            if injection_result is not None:
                return injection_result

        return self._evaluate(text, None, tenant_id, actor_user_id=user_id)

    def _check_injection(self, text: str, tenant_id: str = "default", *, actor_user_id: str | None = None) -> dict | None:
        request = ContentSafetyRequest(text=text, role="user")
        try:
            decision = self.injection_provider.evaluate(request)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Prompt injection provider error")
            return None

        self._log_audit(text, decision, None, "input", "user", provider_name=getattr(self.injection_provider, "name", ""), tenant_id=tenant_id, actor_user_id=actor_user_id)

        if not decision.allowed:
            logger.warning("Prompt injection blocked: %s", decision.reasons)
            return {"messages": [HumanMessage(content=f"[Content blocked by safety policy: {'; '.join(decision.reasons)}]")]}

        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        msg = self._get_last_user_message(state)
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

        if self.injection_provider is not None:
            injection_result = await self._acheck_injection(text, tenant_id, actor_user_id=user_id)
            if injection_result is not None:
                return injection_result

        request = ContentSafetyRequest(text=text, role="user")
        try:
            decision = await self.provider.aevaluate(request)
        except Exception:
            logger.exception("Input guard provider error (async)")
            return None

        self._log_audit(text, decision, None, "input", "user", tenant_id=tenant_id, actor_user_id=user_id)

        if not decision.allowed and self.block_on_harmful:
            logger.warning("Input guard blocked user message: %s", decision.reasons)
            return {"messages": [HumanMessage(content=f"[Content blocked by safety policy: {'; '.join(decision.reasons)}]")]}

        if decision.sanitized_text and decision.sanitized_text != text:
            logger.info("Input guard sanitized PII in user message: %s", decision.flagged_categories)
            return {"messages": [HumanMessage(content=decision.sanitized_text)]}

        return None

    async def _acheck_injection(self, text: str, tenant_id: str = "default", *, actor_user_id: str | None = None) -> dict | None:
        request = ContentSafetyRequest(text=text, role="user")
        try:
            decision = await self.injection_provider.aevaluate(request)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Prompt injection provider error (async)")
            return None

        self._log_audit(text, decision, None, "input", "user", provider_name=getattr(self.injection_provider, "name", ""), tenant_id=tenant_id, actor_user_id=actor_user_id)

        if not decision.allowed:
            logger.warning("Prompt injection blocked: %s", decision.reasons)
            return {"messages": [HumanMessage(content=f"[Content blocked by safety policy: {'; '.join(decision.reasons)}]")]}

        return None
