from pathlib import Path

import yaml


CONFIG_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "config.example.yaml"
CODING_AGENT_NAMES = {"code-analyzer", "code-implementer", "code-reviewer"}
WRITE_TOOLS = {"write_file", "str_replace"}


def _load_coding_agents() -> dict:
    config = yaml.safe_load(CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"))
    return config["subagents"]["custom_agents"]


def test_config_example_registers_coding_subagents() -> None:
    coding_agents = _load_coding_agents()

    assert CODING_AGENT_NAMES <= coding_agents.keys()


def test_only_implementer_has_file_write_tools() -> None:
    coding_agents = _load_coding_agents()

    assert WRITE_TOOLS.isdisjoint(coding_agents["code-analyzer"]["tools"])
    assert WRITE_TOOLS <= set(coding_agents["code-implementer"]["tools"])
    assert WRITE_TOOLS.isdisjoint(coding_agents["code-reviewer"]["tools"])


def test_coding_subagents_do_not_inherit_unrelated_skills() -> None:
    coding_agents = _load_coding_agents()

    for name in CODING_AGENT_NAMES:
        assert coding_agents[name]["skills"] == []
