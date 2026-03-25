"""Tests for built-in guardrail providers."""

import pytest

from deerflow.guardrails.builtin import AllowlistProvider
from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest


class TestAllowlistProvider:
    """Tests for AllowlistProvider guardrail."""

    def test_allows_tool_in_allowlist(self):
        """Should allow tools in the allowlist."""
        provider = AllowlistProvider(allowed_tools=["tool_a", "tool_b"])
        request = GuardrailRequest(tool_name="tool_a")
        
        decision = provider.evaluate(request)
        
        assert decision.allow is True
        assert any(r.code == "oap.allowed" for r in decision.reasons)

    def test_denies_tool_not_in_allowlist(self):
        """Should deny tools not in the allowlist."""
        provider = AllowlistProvider(allowed_tools=["tool_a", "tool_b"])
        request = GuardrailRequest(tool_name="tool_c")
        
        decision = provider.evaluate(request)
        
        assert decision.allow is False
        assert any("not in allowlist" in r.message for r in decision.reasons)

    def test_denies_tool_in_denylist(self):
        """Should deny tools in the denylist."""
        provider = AllowlistProvider(denied_tools=["dangerous_tool"])
        request = GuardrailRequest(tool_name="dangerous_tool")
        
        decision = provider.evaluate(request)
        
        assert decision.allow is False
        assert any("is denied" in r.message for r in decision.reasons)

    def test_allows_any_tool_when_no_allowlist(self):
        """Should allow any tool when no allowlist is specified."""
        provider = AllowlistProvider()
        request = GuardrailRequest(tool_name="any_tool")
        
        decision = provider.evaluate(request)
        
        assert decision.allow is True

    def test_denylist_takes_precedence_over_allowlist(self):
        """Denylist should take precedence over allowlist."""
        provider = AllowlistProvider(
            allowed_tools=["tool_a", "tool_b"],
            denied_tools=["tool_a"]  # tool_a is in both
        )
        request = GuardrailRequest(tool_name="tool_a")
        
        decision = provider.evaluate(request)
        
        assert decision.allow is False
        assert any("is denied" in r.message for r in decision.reasons)

    def test_empty_allowlist_denies_all(self):
        """Empty allowlist should deny all tools."""
        provider = AllowlistProvider(allowed_tools=[])
        request = GuardrailRequest(tool_name="any_tool")
        
        decision = provider.evaluate(request)
        
        assert decision.allow is False

    def test_async_evaluate_matches_sync(self):
        """Async evaluate should return same result as sync."""
        provider = AllowlistProvider(allowed_tools=["tool_a"])
        request = GuardrailRequest(tool_name="tool_a")
        
        sync_decision = provider.evaluate(request)
        
        import asyncio
        async_decision = asyncio.run(provider.aevaluate(request))
        
        assert sync_decision.allow == async_decision.allow

    @pytest.mark.asyncio
    async def test_aevaluate_allows_tool_in_allowlist(self):
        """Async evaluate should allow tools in allowlist."""
        provider = AllowlistProvider(allowed_tools=["tool_a"])
        request = GuardrailRequest(tool_name="tool_a")
        
        decision = await provider.aevaluate(request)
        
        assert decision.allow is True

    @pytest.mark.asyncio
    async def test_aevaluate_denies_tool_not_in_allowlist(self):
        """Async evaluate should deny tools not in allowlist."""
        provider = AllowlistProvider(allowed_tools=["tool_a"])
        request = GuardrailRequest(tool_name="tool_b")
        
        decision = await provider.aevaluate(request)
        
        assert decision.allow is False
