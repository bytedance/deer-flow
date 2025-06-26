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

class CoderNode(BaseNode):
    
    def __init__(self, toolmanager):
        super().__init__("coder", AgentConfiguration.NODE_CONFIGS["writer"], toolmanager)
        # 输出给superviser的参数
        self.call_supervisor = {
            "name": "display_result",
            "description": "This function used to display your result to Supervisor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "The code content."
                                },
                                "file_name": {
                                    "type": "string",
                                    "description": "The name of the file."
                                }
                            },
                            "required": ["content","file_name"]
                        },
                        "description": "The list of coder files."
                    }
                },
                "required": [
                    "codes"
                ]
            }
        }

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        
        configurable = Configuration.from_runnable_config(config)

        supervisor_iterate_time = state["supervisor_iterate_time"]
        messages = apply_prompt_template("coder", state, configurable)

        tools = [self.call_supervisor]
        self.log_input_message(messages)
        llm = get_llm_by_type( self.config.llm_type).bind_tools(tools)
        response = llm.invoke(messages)
        
        node_res_summary = ""
        iterate_times = state.get("tool_call_iterate_time", 0)
        if hasattr(response, 'tool_calls') and response.tool_calls:
            iterate_times += 1
            self.log_tool_call(response, iterate_times)
            for tool_call in response.tool_calls:
                if tool_call["name"] == "display_result":
                    node_res_summary += f"\n{tool_call['args']['codes']}"
                else:
                    node_res_summary += f"\n{tool_call}"
                    # print(node_res_summary)
                    raise ValueError
            return Command(
                update={
                    "messages": [HumanMessage(content=node_res_summary, name="coder")],
                    "tool_call_iterate_time" : 0,
                    "supervisor_iterate_time" : supervisor_iterate_time + 1
                },
                goto="supervisor"
            )
        else:
            self.log_execution_error("no tool call")
            raise ValueError
    
