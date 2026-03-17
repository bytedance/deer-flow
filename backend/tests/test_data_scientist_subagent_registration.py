"""Tests for data-scientist subagent registration."""

from src.subagents.builtins import BUILTIN_SUBAGENTS


def test_data_scientist_subagent_registered():
    assert "data-scientist" in BUILTIN_SUBAGENTS
    cfg = BUILTIN_SUBAGENTS["data-scientist"]
    assert cfg.name == "data-scientist"
    assert "reproducible" in cfg.description.lower()
    assert "generate_reproducible_figure" in cfg.system_prompt
    assert "random seed" in cfg.system_prompt.lower()
    assert "provenance hash" in cfg.system_prompt.lower()

