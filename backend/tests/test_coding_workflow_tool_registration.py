from deerflow.tools.tools import get_available_tools

CODING_WORKFLOW_TOOLS = {
    "submit_task_plan",
    "create_coding_worktree",
    "recover_coding_task",
    "continue_after_review",
    "task",
}


def test_ultra_mode_registers_complete_coding_workflow_toolchain() -> None:
    tool_names = {
        tool.name
        for tool in get_available_tools(
            include_mcp=False,
            subagent_enabled=True,
        )
    }

    assert CODING_WORKFLOW_TOOLS <= tool_names


def test_non_ultra_mode_does_not_expose_coding_workflow_toolchain() -> None:
    tool_names = {
        tool.name
        for tool in get_available_tools(
            include_mcp=False,
            subagent_enabled=False,
        )
    }

    assert CODING_WORKFLOW_TOOLS.isdisjoint(tool_names)
