"""制度问答 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_policy_qa", parse_docstring=True, return_direct=True)
def dify_policy_qa_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """制度问答工具。

    当用户明确要求使用 dify_policy_qa 或调用制度问答工具时调用。
    不要在普通聊天中调用。

    Args:
        query: 用户关于制度/政策方面的提问。
    """
    return invoke_workflow("dify_policy_qa", query, config)
