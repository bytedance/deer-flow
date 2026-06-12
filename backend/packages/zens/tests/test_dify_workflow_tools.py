# backend/packages/zens/tests/test_dify_workflow_tools.py


def test_aml_tool_loads():
    from zens.community.dify.workflows.aml import dify_aml_tool

    assert dify_aml_tool.name == "dify_aml"
    assert "反洗钱" in dify_aml_tool.description


def test_knowledge_tool_loads():
    from zens.community.dify.workflows.knowledge import dify_knowledge_tool

    assert dify_knowledge_tool.name == "dify_knowledge"


def test_general_tool_loads():
    from zens.community.dify.workflows.general import dify_general_tool

    assert dify_general_tool.name == "dify_general"


def test_all_tools_have_query_arg():
    import inspect

    from zens.community.dify.workflows.aml import dify_aml_tool
    from zens.community.dify.workflows.general import dify_general_tool
    from zens.community.dify.workflows.knowledge import dify_knowledge_tool

    for t in [dify_aml_tool, dify_knowledge_tool, dify_general_tool]:
        sig = inspect.signature(t.invoke)
        assert "input" in sig.parameters, f"{t.name} missing 'input' param"
