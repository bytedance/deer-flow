"""AI 写作 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_writing", parse_docstring=True, return_direct=True)
def dify_writing_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """AI 写作工具。

    当用户明确要求使用 dify_writing 或调用 AI 写作工具时调用。
    不要在普通聊天中调用。

    Args:
        query: 用户的写作需求或任务描述。
    """
    return invoke_workflow("dify_writing", query, config)
