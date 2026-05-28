"""通用 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_general", parse_docstring=True)
def dify_general_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """通用对话工作流。

    适用于数据分析、日常对话、闲聊、通用问题解答等场景。

    Args:
        query: 用户的通用问题或对话内容。
    """
    return invoke_workflow("dify_general", query, config)
