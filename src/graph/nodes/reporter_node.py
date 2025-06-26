from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
from src.config.configuration import Configuration
from src.prompts.template import apply_prompt_template
from src.llms.llm import get_llm_by_type
import logging

class ReporterNode(BaseNode):
    """报告器节点 - 综合所有步骤结果生成最终报告"""
    
    def __init__(self, toolmanager):
        super().__init__("reporter", AgentConfiguration.NODE_CONFIGS["reporter"], toolmanager)
        self.call_supervisor = {
            "name": "display_result",
            "description": "This function used to display results including text, files and code snippets to user and Supervisor.",
            "parameters": {
                "type": "object",
                "properties": {
                "result": {
                    "type": "string",
                    "description": "The primary result text."
                },
                "files": {
                    "type": "array",
                    "description": "Array of files to be displayed",
                    "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                        "type": "string",
                        "enum": ["image", "pdf", "docx", "xlsx", "json"],
                        "description": "The type of the file."
                        },
                        "name": {
                        "type": "string",
                        "description": "Name of the file."
                        },
                        "path": {
                        "type": "string",
                        "description": "Path to the file."
                        }
                    },
                    "required": ["type", "name", "path"]
                    }
                },
                "codes": {
                    "type": "array",
                    "description": "Array of code snippets",
                    "items": {
                    "type": "object",
                    "properties": {
                        "language": {
                        "type": "string",
                        "description": "Programming language of the code."
                        },
                        "content": {
                        "type": "string",
                        "description": "The actual code content."
                        }
                    },
                    "required": ["language", "content"]
                    }
                }
                },
                "required": ["result"]
            }
        }

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:

        """执行报告器逻辑"""
        self.log_execution("Generating final report")
        supervisor_iterate_time = state["supervisor_iterate_time"]

        configurable = Configuration.from_runnable_config(config)
        messages = apply_prompt_template(self.name, state, configurable)
        tools = [self.call_supervisor]
        self.log_input_message(messages)
        llm = get_llm_by_type(self.config.llm_type).bind_tools(tools)
        response = llm.invoke(messages)

        node_res_summary = ""
        iterate_times = state.get("tool_call_iterate_time", 0)
        if hasattr(response, 'tool_calls') and response.tool_calls:
            iterate_times += 1
            self.log_tool_call(response, iterate_times)
            for tool_call in response.tool_calls:
                if tool_call["name"] == "display_result":
                    node_res_summary += f"\n{tool_call['args']['result']}"
                else:
                    node_res_summary += f"\n{tool_call}"
                    raise ValueError
                
            return Command(
                update={
                    "messages": [HumanMessage(content=node_res_summary, name="reporter")],
                    "supervisor_iterate_time": supervisor_iterate_time + 1
                },
                goto="supervisor"
            )
        else:
            self.log_execution_error("no tool call")
            raise ValueError