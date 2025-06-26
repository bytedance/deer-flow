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
from langchain_mcp_adapters.client import MultiServerMCPClient


class InterpreterNode(BaseNode):
    """编程节点 - 处理编程任务"""
    
    def __init__(self, toolmanager):
        super().__init__("interpreter", AgentConfiguration.NODE_CONFIGS["interpreter"], toolmanager)
        self.call_supervisor = {
            "name": "display_result",
            "description": "This function used to display your result to Supervisor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "object",
                        "properties": {
                            "generate": {
                                "type": "string",
                                "description": "Generated analysis report content with markdown formatting and download links."
                            },
                            "execution": {
                                "type": "string", 
                                "description": "Execution log showing chart generation status and download links."
                            }
                        },
                        "required": ["generate", "execution"],
                        "description": "The analysis result containing generated content and execution log."
                    },
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "The display name of the generated file."
                                },
                                "path": {
                                    "type": "string",
                                    "description": "The full path to the generated file (e.g., sandbox:/mnt/data/filename.png)."
                                },
                                "type": {
                                    "type": "string",
                                    "description": "The file type/extension (e.g., png, jpg, pdf, etc.)."
                                }
                            },
                            "required": ["name", "path", "type"]
                        },
                        "description": "List of generated files with their metadata."
                    }
                },
                "required": ["result"]
            }
        }

        self.python_repl_tool = {
            "name": "python_repl_tool",
            "description": "Use this to execute python code and do data analysis or calculation. If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The python code to execute to do further analysis or calculation."
                    }
                },
                "required": ["code"]
            }
        }

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        """执行编程逻辑"""
        self.log_execution("Starting interpreter task")
        
        configurable = Configuration.from_runnable_config(config)
        supervisor_iterate_time = state["supervisor_iterate_time"]

        messages = apply_prompt_template("writer", state, configurable)
        # print(messages)
        # 准备委托工具
        tools = [self.call_supervisor]

        mcp_servers = {}
        if configurable.mcp_settings:
            for server_name, server_config in configurable.mcp_settings["servers"].items():
                if server_config.get("enabled_tools") and "coder" in server_config.get(
                    "add_to_agents", []
                ):
                    mcp_servers[server_name] = {
                        k: v
                        for k, v in server_config.items()
                        if k in ("transport", "command", "args", "url", "env")
                    }

        # 创建mcp agent
        if len(mcp_servers) != 0:
            try:
                client = MultiServerMCPClient(mcp_servers)
                tools.append(await client.get_tools(server_name="Sandbox"))
                self.log_execution(
                    "Able to establish the connection with the sandbox. Use sandbox service to run codes."
                )
            except Exception as e:
                self.log_execution_warning(
                    f"Could not estabilish connection with the sandbox service with error {e}. Fallback to python_repl_tool"
                )
                tools.append(self.python_repl_tool)
        else:
            self.log_execution("Do not configurate to use sandbox. Fallback to python_repl_tool.")
            tools.append(self.python_repl_tool)

        llm = get_llm_by_type( self.config.llm_type).bind_tools(tools)
        self.log_input_message(messages)
        response = llm.invoke(messages)

        node_res_summary = ""
        iterate_times = state.get("tool_call_iterate_time", 0)
        if hasattr(response, 'tool_calls') and response.tool_calls:
            iterate_times += 1
            self.log_tool_call(response, iterate_times)
            for tool_call in response.tool_calls:
                if tool_call["name"] == "display_result":
                    node_res_summary += f"\n{tool_call['args']['result']}"
                    return Command(
                        update={
                            "messages": [HumanMessage(content=node_res_summary, name="writer")],
                            "tool_call_iterate_time" : 0,
                            "supervisor_iterate_time": supervisor_iterate_time + 1
                        },
                        goto="supervisor"
                    )

                elif tool_call["name"] == "python_repl_tool":
                    code = tool_call['args']['code']
                    ci_result = ""
                    from langchain_experimental.utilities import PythonREPL
                    repl = PythonREPL()
                    try:
                        result = repl.run(code)
                        # Check if the result is an error message by looking for typical error patterns
                        if isinstance(result, str) and ("Error" in result or "Exception" in result):
                            self.log_execution_error(result)
                            ci_result = f"Error executing code:\n```python\n{code}\n```\nError: {result}"
                        self.log_execution("Code execution successful")
                    except BaseException as e:
                        error_msg = repr(e)
                        self.log_execution_error(error_msg)
                        ci_result = f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

                    return Command(
                        update={
                            "messages": [ToolMessage(content=ci_result, name="interpreter", tool_call_id=response.tool_call["id"])],
                            "tool_call_iterate_time" : iterate_times
                        },
                        goto="interpreter"
                    )
        else:
            self.log_execution_error("no tool call")
            raise ValueError