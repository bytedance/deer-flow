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
        
        reporter_input = {
            "messages": state["messages"],
            "locale": state.get("locale", "en-US"),
        }
       
        configurable = Configuration.from_runnable_config(config)
        # 应用reporter模板
        invoke_messages = apply_prompt_template("reporter", reporter_input, configurable)
        # print(f"reporter: \n{invoke_messages}")
        # 生成最终报告
        tools = [self.call_supervisor]
        response = get_llm_by_type(self.config.llm_type).bind_tools(tools).invoke(invoke_messages)
        self.log_execution("Final report generated successfully.")
        self.log_execution(f"{response.content}")
        
        node_res_summary = ""
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call["name"] == "display_result":
                    node_res_summary += f"\n{tool_call['args']['result']["description"]}"
                else:
                    node_res_summary += f"\n{tool_call}"
                    raise ValueError
                
        return Command(
            update={
                "messages": [HumanMessage(content=node_res_summary, name="reporter")],
            },
            goto="reporter"
        )
    
            # print(response.content)
            # return {"final_report": response.content}