"""图片识别 Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_image_recognition", parse_docstring=True, return_direct=True)
def dify_image_recognition_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """图片识别工具。

    当用户明确要求使用 dify_image_recognition 或调用图片识别工具时调用。
    不要在普通聊天中调用。

    Args:
        query: 需要识别的图片相关问题或描述。
    """
    return invoke_workflow("dify_image_recognition", query, config)
