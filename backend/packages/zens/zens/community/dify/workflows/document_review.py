"""文档校验 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_document_review", parse_docstring=True)
def dify_document_review_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """文档校验工具。

    当用户明确要求使用 dify_document_review 或调用文档校验工具时调用。
    不要在普通聊天中调用。

    Args:
        query: 需要校验的文档内容或文档相关问题。
    """
    return invoke_workflow("dify_document_review", query, config)
