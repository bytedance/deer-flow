from deerflow.subagents.builtins import BUILTIN_SUBAGENTS

CODING_AGENT_NAMES = {"code-analyzer", "code-implementer", "code-reviewer"}
WRITE_TOOLS = {"write_file", "str_replace"}


def test_registry_contains_first_class_coding_subagents() -> None:
    assert CODING_AGENT_NAMES <= BUILTIN_SUBAGENTS.keys()


def test_only_implementer_has_file_write_tools() -> None:
    coding_agents = BUILTIN_SUBAGENTS

    assert WRITE_TOOLS.isdisjoint(coding_agents["code-analyzer"].tools or [])
    assert WRITE_TOOLS <= set(coding_agents["code-implementer"].tools or [])
    assert WRITE_TOOLS.isdisjoint(coding_agents["code-reviewer"].tools or [])


def test_coding_subagents_do_not_inherit_unrelated_skills() -> None:
    coding_agents = BUILTIN_SUBAGENTS

    for name in CODING_AGENT_NAMES:
        assert coding_agents[name].skills == []


def test_coding_subagents_define_workspace_and_artifact_contracts() -> None:
    assert BUILTIN_SUBAGENTS["code-analyzer"].workspace_access == "read_only"
    assert BUILTIN_SUBAGENTS["code-implementer"].workspace_access == "read_write"
    assert BUILTIN_SUBAGENTS["code-reviewer"].workspace_access == "read_only"
    assert {name: BUILTIN_SUBAGENTS[name].artifact_type for name in CODING_AGENT_NAMES} == {
        "code-analyzer": "analysis_report",
        "code-implementer": "implementation_report",
        "code-reviewer": "review_report",
    }
