from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_knowledge", parse_docstring=True, return_direct=True)
def dify_knowledge_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Dify 知识问答工具。

    当用户明确要求使用 dify_knowledge 或调用 dify 知识问答工具时调用。
    不要在普通聊天中提及 dify 时调用。

    Args:
        query: 用户在银行办公场景中的知识检索问题（如规章制度、操作流程、业务指引等）。
    """
    return invoke_workflow("dify_knowledge", query, config)
