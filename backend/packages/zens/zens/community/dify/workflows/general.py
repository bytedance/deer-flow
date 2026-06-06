"""通用 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_general", parse_docstring=True, return_direct=True)
def dify_general_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """通用 Dify 对话工具。

    当用户明确要求使用 dify_general 或调用通用对话工具时调用。
    不要在普通聊天中调用。

    Args:
        query: 用户的通用对话问题或任务描述。
    """
    return invoke_workflow("dify_general", query, config)
