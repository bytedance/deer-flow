"""Built-in guardrail providers that ship with DeerFlow."""

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class AllowlistProvider:
    """Simple allowlist/denylist provider. No external dependencies."""

    name = "allowlist"

    def __init__(self, *, allowed_tools: list[str] | None = None, denied_tools: list[str] | None = None):
        # Distinguish "no allowlist configured" (None -> allow all) from an
        # explicitly empty allowlist ([] -> allow nothing). A truthiness test
        # would collapse [] into None and fail open, letting every tool through
        # when the operator intended to permit none.
        self._allowed = set(allowed_tools) if allowed_tools is not None else None
        self._denied = set(denied_tools) if denied_tools else set()

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        if self._allowed is not None and request.tool_name not in self._allowed:
            return GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.tool_not_allowed", message=f"tool '{request.tool_name}' not in allowlist")])
        if request.tool_name in self._denied:
            return GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.tool_not_allowed", message=f"tool '{request.tool_name}' is denied")])
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return self.evaluate(request)
