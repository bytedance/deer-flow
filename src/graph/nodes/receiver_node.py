# nodes/receiver_node.py
"""接收器节点"""
import json
import logging
from typing import Any, Dict, Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from src.config.agents import AgentConfiguration
from src.config.configuration import Configuration
from src.llms.llm import get_llm_by_type
from src.prompts.template import apply_prompt_template

from .base_node import BaseNode

logger = logging.getLogger(__name__)

class ReceiverNode(BaseNode):
    def __init__(self, toolmanager):
        super().__init__("receiver", AgentConfiguration.NODE_CONFIGS["receiver"], toolmanager)

        # 定义与用户交互的工具
        self.ask_user_tool = {
            "name": "message_ask_user",
            "description": "Ask user a question and wait for response. Use for gathering information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The question text for user interaction, structured clearly to guide the user's response."
                    }
                },
                "required": ["text"]
            }
        }

        self.display_result_tool = {
            "name": "display_result",
            "description": "This function is used to display your result to the user and Supervisor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "A comprehensive markdown-formatted text that consolidates all user-provided information in a clear and organized format."
                    },
                    "references": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique identifier for the reference."},
                                "type": {"type": "string", "description": "Type of reference (e.g., file, image)."},
                                "name": {"type": "string", "description": "File name."},
                                "function": {"type": "string", "description": "Description of the file function."}
                            },
                            "required": ["id", "type", "name", "function"]
                        },
                        "description": "List of reference materials provided by the user."
                    }
                },
                "required": ["result"]
            }
        }
        
        # 记录已询问用户的次数
        self.asked_count = 0
        self.max_ask_limit = 5 

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        """执行接收器逻辑，与用户交互以收集信息，并最终展示"""

        configurable = Configuration.from_runnable_config(config)
        supervisor_iterate_time = state["supervisor_iterate_time"]

        # 应用提示模板
        messages = apply_prompt_template("receiver", state, configurable)
        
        # 准备委托工具
        # Receiver可以调用ask_user_tool和display_result_tool
        tools = [self.ask_user_tool, self.display_result_tool]

        llm = get_llm_by_type(self.config.llm_type).bind_tools(tools)
        response = llm.invoke(messages)
        node_res_summary = ""
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                if tool_name == "message_ask_user":
                    question = tool_args.get("text")
                    if question:
                        iterate_times += 1
                        self.log_execution(f"ReceiverNode asking user: {question} (Asked count: {iterate_times})")
                        
                        # 如果达到或超过最大询问次数，强制display_result
                        if iterate_times > self.max_ask_limit:   
                            self.log_execution(f"ReceiverNode reached max ask limit ({self.max_ask_limit}). Forcing display_result.")
                            # 模拟display_result调用，提示用户未提供有效信息
                            result_content = "用户未提供有效信息，已达到最大询问次数限制。"   #  是这个吗
                            # 更新状态并直接goto supervisor
                            return Command(
                                update={
                                    "messages": [HumanMessage(content=result_content, name="receiver")],   #这边是AImessage还是Human
                                    "tool_call_iterate_time": 0,
                                },
                                goto="supervisor"
                            )
                        else:
                            # 保持在receiver节点，等待收集用户信息
                            feedback = str(interrupt(tool_call["args"]["text"]))
                            # 整理feedback 返回节点
                            feedback_query = f"Human feedback: {feedback}"
                            return Command(
                                update={
                                    "messages": [response,
                                        ToolMessage(content=feedback_query, tool_call_id=tool_call["id"])],
                                    "tool_call_iterate_time": iterate_times
                                },
                                goto="receiver"
                            )

                elif tool_name == "display_result":
                    result = tool_args.get("result", "")
                    references = tool_args.get("references", [])
                    
                    final_result_content = f"### 用户信息收集完成\n\n{result}"
                    if references:
                        final_result_content += "\n\n### 参考:\n"
                        for ref in references:
                            final_result_content += f"- ID: {ref.get('id')}, Type: {ref.get('type')}, Name: {ref.get('name')}, Function: {ref.get('function')}\n"
                    
                    self.log_execution(f"ReceiverNode displaying result to supervisor: {final_result_content}")
                    node_res_summary += f"\n{final_result_content}"
                    return Command(
                        update={
                            "messages": [HumanMessage(content=node_res_summary, name="receiver")],
                            "tool_call_iterate_time": 0,
                        },
                        goto="supervisor"
                    )

                else:
                    self.log_execution(f"ReceiverNode received unexpected tool call: {tool_name}")
                    raise ValueError(f"ReceiverNode received unexpected tool call: {tool_name}")
        else:
            # LLM没有调用工具  是直接raise ValueError还是传递给supervisor
            self.log_execution("ReceiverNode LLM did not call any tools. This might indicate an issue.")
            return Command(
                update={
                    "messages": [
                        HumanMessage(content="Receiver 未能完成任务：未调用任何预期的工具。", name="receiver"),
                    ],
                    "tool_call_iterate_time": 0,
                },
                goto="supervisor"
            )

if __name__ == "__main__":
    receiver_try = ReceiverNode()
    
    state_try = {
        
    }