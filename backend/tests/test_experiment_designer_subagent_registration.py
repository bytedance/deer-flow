"""Tests for experiment-designer subagent registration."""

from src.subagents.builtins import BUILTIN_SUBAGENTS


def test_experiment_designer_subagent_registered():
    assert "experiment-designer" in BUILTIN_SUBAGENTS
    cfg = BUILTIN_SUBAGENTS["experiment-designer"]
    assert cfg.name == "experiment-designer"
    assert "power analysis" in cfg.system_prompt.lower()
    assert "sample-size" in cfg.system_prompt.lower() or "sample size" in cfg.system_prompt.lower()
    assert "ablation" in cfg.system_prompt.lower()
