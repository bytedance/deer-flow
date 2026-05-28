"""知识问答 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_knowledge", parse_docstring=True)
def dify_knowledge_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """知识问答工作流（需在 query 中包含"dify"或"知识库"关键词触发）。

    当用户显式要求查询知识库时调用本工具：
    - 知识库检索 / 知识查询 / 文档查阅
    - 产品说明 / 操作指南 / 业务介绍

    注意：query 中需包含"dify"、"知识库"或"查询知识库"等关键词，模型才会触发本工具。

    Args:
        query: 用户的知识性或百科类问题。
    """
    return invoke_workflow("dify_knowledge", query, config)
