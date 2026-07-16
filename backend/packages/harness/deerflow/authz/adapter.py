"""Adapter that presents an AuthorizationProvider as a GuardrailProvider.

This lets the existing :class:`~deerflow.guardrails.middleware.GuardrailMiddleware`
enforce :class:`~deerflow.authz.provider.AuthorizationProvider` decisions at
tool-call time — no new middleware class required (see RFC §6.1).

The adapter maps :class:`~deerflow.guardrails.provider.GuardrailRequest`
fields to :class:`~deerflow.authz.provider.AuthzRequest` fields, calls the
authorization provider, and converts the :class:`~deerflow.authz.provider.AuthzDecision`
back to a :class:`~deerflow.guardrails.provider.GuardrailDecision`.
"""

from __future__ import annotations

from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class GuardrailAuthorizationAdapter:
    """Adapt an :class:`AuthorizationProvider` to the ``GuardrailProvider`` Protocol.

    ``resource_type`` and ``action`` default to ``"tool"`` / ``"call"``,
    which is correct for the tool-execution path. A different resource/action
    pair can be injected if the adapter is reused outside the tool path.

    .. note::

        ``Principal.is_internal`` is not populated by this adapter — the
        correct signal (``auth_source == AUTH_SOURCE_INTERNAL``) lives on
        ``request.state``, not on :class:`GuardrailRequest`. The field
        retains its dataclass default (``False``) until Phase 1 threads it
        into run context, so both layers derive it from one source.
    """

    name = "authorization"

    def __init__(
        self,
        provider: AuthorizationProvider,
        *,
        resource_type: str = "tool",
        action: str = "call",
    ) -> None:
        self._provider = provider
        self._resource_type = resource_type
        self._action = action

    def _to_authz(self, gr: GuardrailRequest) -> AuthzRequest:
        """Map a guardrail request to an authorization request."""
        return AuthzRequest(
            principal=Principal(
                user_id=gr.user_id,
                role=gr.user_role,
                oauth_provider=gr.oauth_provider,
                oauth_id=gr.oauth_id,
            ),
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
        decision = self._provider.authorize(self._to_authz(request))
        return self._to_guardrail(decision)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Async evaluation: delegate to ``provider.aauthorize``.

        See :meth:`evaluate` for exception-propagation rationale.
        """
        decision = await self._provider.aauthorize(self._to_authz(request))
        return self._to_guardrail(decision)
