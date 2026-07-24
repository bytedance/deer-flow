"""Adapter that presents an AuthorizationProvider as a GuardrailProvider.

This lets the existing :class:`~deerflow.guardrails.middleware.GuardrailMiddleware`
enforce :class:`~deerflow.authz.provider.AuthorizationProvider` decisions at
tool-call time — no new middleware class required (see RFC §6.1).

The adapter maps :class:`~deerflow.guardrails.provider.GuardrailRequest`
fields to :class:`~deerflow.authz.provider.AuthzRequest` fields, calls the
authorization provider, and converts the :class:`~deerflow.authz.provider.AuthzDecision`
back to a :class:`~deerflow.guardrails.provider.GuardrailDecision`.

Principal construction delegates to
:func:`~deerflow.authz.principal.build_principal_from_context` so Layer 1
(tool assembly) and Layer 2 (this adapter) share a single identity builder
with consistent ``default_role`` and ``attributes`` semantics.
"""

from __future__ import annotations

from collections.abc import Iterable

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest
from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class GuardrailAuthorizationAdapter:
    """Adapt an :class:`AuthorizationProvider` to the ``GuardrailProvider`` Protocol.

    ``resource_type`` and ``action`` default to ``"tool"`` / ``"call"``,
    which is correct for the tool-execution path. A different resource/action
    pair can be injected if the adapter is reused outside the tool path.

    Args:
        provider: The authorization provider to delegate decisions to.
        default_role: Role used when ``user_role`` is absent or empty in the
            runtime context. Must be passed by Phase 1B wiring from
            ``AuthorizationConfig.default_role``.
        resource_type: Resource type for all ``AuthzRequest`` instances.
        action: Action for all ``AuthzRequest`` instances.
        infrastructure_tool_names: Framework tools created from an already
            authorized capability set. These may execute without a second
            provider decision; callers must derive the names from the current
            build's concrete deferred setup rather than from static config.
    """

    name = "authorization"

    def __init__(
        self,
        provider: AuthorizationProvider,
        *,
        default_role: str = "user",
        resource_type: str = "tool",
        action: str = "call",
        infrastructure_tool_names: Iterable[str] = (),
    ) -> None:
        self._provider = provider
        self._default_role = default_role
        self._resource_type = resource_type
        self._action = action
        self._infrastructure_tool_names = frozenset(infrastructure_tool_names)

    def _infrastructure_decision(self, request: GuardrailRequest) -> GuardrailDecision | None:
        """Allow framework tools created from an already-filtered capability set."""
        if request.tool_name not in self._infrastructure_tool_names:
            return None
        return GuardrailDecision(
            allow=True,
            reasons=[GuardrailReason(code="authz.infrastructure_tool")],
            policy_id="authz:infrastructure",
        )

    def _to_authz(self, gr: GuardrailRequest) -> AuthzRequest:
        """Map a guardrail request to an authorization request."""
        principal = build_principal_from_context(
            {
                "user_id": gr.user_id,
                "user_role": gr.user_role,
                "oauth_provider": gr.oauth_provider,
                "oauth_id": gr.oauth_id,
                "channel_user_id": gr.channel_user_id,
                "is_internal": gr.is_internal,
                "authz_attributes": gr.authz_attributes,
            },
            default_role=self._default_role,
        )
        return AuthzRequest(
            principal=principal,
            resource=self._resource_type,
            action=self._action,
            target=gr.tool_name,
            context={
                "thread_id": gr.thread_id,
                "run_id": gr.run_id,
                "tool_call_id": gr.tool_call_id,
                "tool_input": gr.tool_input,
                "is_subagent": gr.is_subagent,
                "agent_id": gr.agent_id,
                "timestamp": gr.timestamp,
            },
        )

    @staticmethod
    def _to_guardrail(d: AuthzDecision) -> GuardrailDecision:
        """Convert an authorization decision to a guardrail decision."""
        return GuardrailDecision(
            allow=d.allow,
            reasons=[GuardrailReason(code=r.code, message=r.message) for r in d.reasons],
            policy_id=d.policy_id,
            metadata=d.metadata,
        )

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Synchronous evaluation: delegate to ``provider.authorize``.

        Provider exceptions are intentionally allowed to propagate. The
        adapter is consumed by :class:`~deerflow.guardrails.middleware.GuardrailMiddleware`,
        whose ``wrap_tool_call`` / ``awrap_tool_call`` already applies
        fail-closed semantics based on its ``fail_closed`` parameter
        (backed by ``AuthorizationConfig.fail_closed``). Catching exceptions
        here would duplicate that logic and risk divergent behavior between
        the two layers.
        """
        if infrastructure_decision := self._infrastructure_decision(request):
            return infrastructure_decision
        decision = self._provider.authorize(self._to_authz(request))
        return self._to_guardrail(decision)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Async evaluation: delegate to ``provider.aauthorize``.

        See :meth:`evaluate` for exception-propagation rationale.
        """
        if infrastructure_decision := self._infrastructure_decision(request):
            return infrastructure_decision
        decision = await self._provider.aauthorize(self._to_authz(request))
        return self._to_guardrail(decision)
