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
    """知识问答工作流。

    当用户问到以下场景时调用本工具：
    - 知识库检索 / 百科查询 / 常识问题
    - 文档查阅 / 资料查找 / 知识获取
    - 产品说明 / 操作指南 / 业务介绍

    Args:
        query: 用户的知识性或百科类问题。
    """
    return invoke_workflow("dify_knowledge", query, config)
