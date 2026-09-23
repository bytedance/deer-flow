from langchain_core.tools import StructuredTool

from deerflow.mcp.tools import ServerDiscoveryResult, _flatten_server_tool_groups


def _tool(name: str) -> StructuredTool:
    async def _call() -> str:
        return name

    return StructuredTool.from_function(coroutine=_call, name=name, description=name)


def test_flatten_order_preserves_tool_identity_and_empty_success():
    a, b = _tool("a"), _tool("b")
    grouped = {
        "A": ServerDiscoveryResult(tools=(a,)),
        "B": ServerDiscoveryResult(tools=(b,)),
        "EMPTY": ServerDiscoveryResult(tools=()),
    }
    flattened = _flatten_server_tool_groups(("B", "EMPTY", "A"), grouped)
    assert flattened == [b, a]
    assert flattened[0] is b and flattened[1] is a
    assert "EMPTY" in grouped and grouped["EMPTY"].tools == ()
