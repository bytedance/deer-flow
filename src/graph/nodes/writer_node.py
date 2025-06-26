from src.llms.llm import get_llm_by_type
from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.config.configuration import Configuration
from src.prompts.template import apply_prompt_template
from src.llms.llm import get_llm_by_type
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
import json
import logging

logger = logging.getLogger(__name__)

class WriterNode(BaseNode):
    
    def __init__(self, toolmanager):
        super().__init__("writer", AgentConfiguration.NODE_CONFIGS["writer"], toolmanager)
        # 输出给superviser的参数
        self.call_supervisor = {
            "name": "display_result",
            "description": "This function used to display your result to user and Supervisor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "A comprehensive markdown-formatted text content, including the generated or processed text organized in a readable format."
                    }
                },
                "required": [
                "result"
                ]
            }
        }
    
    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        self.log_execution("Starting Coder")
        configurable = Configuration.from_runnable_config(config)

        supervisor_iterate_time = state["supervisor_iterate_time"]
        messages = apply_prompt_template("writer", state, configurable)
        # print(messages)
        # 准备委托工具
        tools = [self.call_supervisor]
        self.log_input_message(messages)
        llm = get_llm_by_type( self.config.llm_type).bind_tools(tools)
        response = llm.invoke(messages)
        self.log_execution(response)

        node_res_summary = ""
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call["name"] == "display_result":
                    node_res_summary += f"\n{tool_call['args']['result']}"
                else:
                    node_res_summary += f"\n{tool_call}"
                    # print(node_res_summary)
                    raise ValueError
        
            return Command(
                update={
                    "messages": [HumanMessage(content=node_res_summary, name="writer")],
                    "supervisor_iterate_time": supervisor_iterate_time + 1
                },
                goto="supervisor"
            )
        else:
            self.log_execution_error("no tool call")
            raise ValueError