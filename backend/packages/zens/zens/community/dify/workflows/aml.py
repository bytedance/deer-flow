"""反洗钱（AML）Dify 工作流 Tool。"""

from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.router import invoke_workflow


@tool("dify_aml", parse_docstring=True)
def dify_aml_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """反洗钱工作流（AML）。

    当用户问到以下场景时调用本工具：
    - 可疑交易识别 / 交易监控 / 洗钱风险评估
    - 金融机构合规 / 监管要求（反洗钱相关）
    - 客户尽职调查（CDD）/ 受益人识别 / 交易筛选
    - 制裁名单筛查 / PEP（PPE 政治敏感人士）核查

    Args:
        query: 用户的 AML 相关问题或交易描述。
    """
    return invoke_workflow("dify_aml", query, config)
