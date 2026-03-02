"""Modular system prompt engineering for the lead agent.

This package decomposes the monolithic system prompt into composable fragments
and provides a PromptComposer class for assembly.
"""

from src.agents.lead_agent.prompts.composer import Intensity, PromptComposer

__all__ = ["PromptComposer", "Intensity"]
