"""Tests for ``tools[].interrupt_on`` config validation."""

import pytest
from pydantic import ValidationError

from deerflow.config.tool_config import InterruptOnConfig, ToolConfig


def _tool(**interrupt_kwargs) -> ToolConfig:
    return ToolConfig(
        name="bash_tool",
        group="sandbox",
        use="deerflow.sandbox.tools:bash_tool",
        interrupt_on=InterruptOnConfig(**interrupt_kwargs),
    )


class TestInterruptOnAbsent:
    """A tool without ``interrupt_on`` keeps working exactly as before."""

    def test_defaults_to_none(self):
        tool = ToolConfig(name="bash_tool", group="sandbox", use="deerflow.sandbox.tools:bash_tool")
        assert tool.interrupt_on is None


class TestAllowedDecisions:
    def test_accepts_every_decision_type(self):
        config = InterruptOnConfig(allowed_decisions=["approve", "edit", "reject", "respond"])
        assert config.allowed_decisions == ["approve", "edit", "reject", "respond"]

    def test_rejects_unknown_decision(self):
        with pytest.raises(ValidationError):
            InterruptOnConfig(allowed_decisions=["approve", "detonate"])

    def test_rejects_empty_list(self):
        # An empty list would silently auto-approve, which reads as the
        # opposite of what configuring interrupt_on asks for.
        with pytest.raises(ValidationError, match="must not be empty"):
            InterruptOnConfig(allowed_decisions=[])

    def test_rejects_duplicates(self):
        with pytest.raises(ValidationError, match="duplicate"):
            InterruptOnConfig(allowed_decisions=["approve", "approve"])


class TestDescriptionSources:
    def test_static_description(self):
        tool = _tool(allowed_decisions=["approve"], description="Review this command")
        assert tool.interrupt_on.description == "Review this command"

    def test_description_provider(self):
        tool = _tool(allowed_decisions=["approve"], description_use="my_pkg.my_mod:describe")
        assert tool.interrupt_on.description_use == "my_pkg.my_mod:describe"

    def test_rejects_both_description_sources(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            InterruptOnConfig(
                allowed_decisions=["approve"],
                description="static",
                description_use="my_pkg.my_mod:describe",
            )


class TestNonApprovableTools:
    """``ask_clarification`` runs its own human hand-off and cannot be gated."""

    def test_rejects_interrupt_on_ask_clarification(self):
        with pytest.raises(ValidationError, match="own human-in-the-loop flow"):
            ToolConfig(
                name="ask_clarification",
                group="builtin",
                use="deerflow.tools.builtins:ask_clarification",
                interrupt_on=InterruptOnConfig(allowed_decisions=["approve"]),
            )

    def test_allows_ask_clarification_without_interrupt_on(self):
        tool = ToolConfig(
            name="ask_clarification",
            group="builtin",
            use="deerflow.tools.builtins:ask_clarification",
        )
        assert tool.interrupt_on is None
