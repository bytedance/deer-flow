"""Middleware to inject deep-link passthrough parameters into agent context."""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# Keys in additional_kwargs that are for internal infra use and should NOT be
# exposed to the LLM as deep-link parameters.
_INTERNAL_KWARGS_KEYS = frozenset({"files", "hide_from_ui", "element"})

# Strong system instruction to enforce deep-link direct execution path.
# Placed as SystemMessage for higher LLM priority than HumanMessage.
_DEEP_LINK_SYSTEM_INSTRUCTION = """[系统指令] 首条用户消息中包含 <deep_link_params> 参数块。

你必须立即执行以下检查：
1. 解析 <deep_link_params> 中的所有参数
2. 如果必选参数齐全 → 跳过所有表单交互，直接进入直达执行流程（DSL 管道 / 数据查询 / 报告生成）
3. 如果必选参数缺失 → 静默回退到普通交互流程

严禁行为：
- 禁止向用户提及 "deep-link"、"deep_link_params" 或参数名称
- 禁止在参数齐全时仍渲染表单（render_ui interactive=True）
- 禁止要求用户重复提供已有的参数

正确行为：
- 参数齐全：直接执行，输出结果或进度提示
- 参数缺失：当作没有 deep_link_params，走正常流程"""


class PassthroughParamsMiddleware(AgentMiddleware):
    """Middleware to inject deep-link passthrough parameters into message content.

    Reads non-internal keys from the first HumanMessage's ``additional_kwargs``
    (set by the frontend from deep-link URL query parameters) and prepends a
    ``<deep_link_params>`` block to the message content so the LLM can read them.

    Internal keys (``files``, ``hide_from_ui``, ``element``) are excluded.
    The original ``additional_kwargs`` dict is preserved on the message unchanged
    for frontend stream consumers.
    """

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        first_message = messages[0]
        if not isinstance(first_message, HumanMessage):
            return None

        additional_kwargs = first_message.additional_kwargs or {}
        passthrough = {
            k: v
            for k, v in additional_kwargs.items()
            if k not in _INTERNAL_KWARGS_KEYS and v is not None
        }
        if not passthrough:
            return None

        block_lines = ["<deep_link_params>"]
        for k, v in passthrough.items():
            block_lines.append(f"  {k}: {v}")
        block_lines.append("</deep_link_params>")
        block = "\n".join(block_lines)

        original_content = first_message.content
        if isinstance(original_content, str):
            updated_content = f"{block}\n\n{original_content}"
        elif isinstance(original_content, list):
            text_block = {"type": "text", "text": f"{block}\n\n"}
            updated_content = [text_block, *original_content]
        else:
            updated_content = original_content

        updated_message = HumanMessage(
            content=updated_content,
            id=first_message.id,
            name=first_message.name,
            additional_kwargs=first_message.additional_kwargs,
        )

        # Insert SystemMessage at position 0 for stronger LLM compliance.
        # The SystemMessage enforces deep-link direct execution path.
        system_msg = SystemMessage(content=_DEEP_LINK_SYSTEM_INSTRUCTION)
        messages[0] = updated_message
        messages.insert(0, system_msg)
        return {"messages": messages}
