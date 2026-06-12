"""反洗钱（AML）Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_aml", parse_docstring=True, return_direct=True)
def dify_aml_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """反洗钱（AML）工作流工具。

    当用户明确要求使用 dify_aml 或调用反洗钱工具时调用。
    不要在普通聊天中调用。

    Args:
        query: 用户的 AML 相关问题或交易描述。
    """
    return invoke_workflow("dify_aml", query, config)
