"""Tests for writer-agent subagent registration."""

from src.subagents.builtins import BUILTIN_SUBAGENTS


def test_writer_agent_registered():
    assert "writer-agent" in BUILTIN_SUBAGENTS
    cfg = BUILTIN_SUBAGENTS["writer-agent"]
    assert cfg.name == "writer-agent"
    assert "writer" in cfg.description.lower()

