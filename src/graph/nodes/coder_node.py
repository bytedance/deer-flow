# nodes/coder_node.py
"""编程节点"""

from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
import os
import logging

logger = logging.getLogger(__name__)

class CoderNode(BaseNode):
    """编程节点 - 处理编程任务"""
    
    def __init__(self, toolmanager):
        super().__init__("coder", AgentConfiguration.NODE_CONFIGS["coder"], toolmanager)
    
    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        """执行编程逻辑"""
        self.log_execution("Starting coding task")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.prompts.template import apply_prompt_template
        from src.agents import create_agent
        from src.tools import python_repl_tool
        from langchain_mcp_adapters.client import MultiServerMCPClient
        
        try:
            configurable = Configuration.from_runnable_config(config)
            
            # 推进到下一步
            current_step_index = self.get_next_step_index(state)
            current_plan = state.get("current_plan")
            
            if not current_plan or current_step_index >= len(current_plan.steps):
                return Command(goto="reporter")
            
            current_step = current_plan.steps[current_step_index]
            self.log_execution(f"Working on step {current_step_index}: {current_step.title}")
            
            # 构建coder输入
            coder_input = {
                "messages": [
                    HumanMessage(
                        content=f"""# Current Task

## Title
{current_step.title}

## Description
{current_step.description}

## Previous Message
{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}

## Locale
{state.get('locale', 'en-US')}"""
                    )
                ],
                "locale": state.get("locale", "en-US"),
                "resources": state.get("resources", [])
            }
            
            messages = apply_prompt_template("coder", coder_input, configurable)
            
            # 准备编程工具
            tools = []
            
            # 处理MCP服务器配置
            mcp_servers = {}
            if configurable.mcp_settings:
                for server_name, server_config in configurable.mcp_settings["servers"].items():
                    if server_config.get("enabled_tools") and "coder" in server_config.get("add_to_agents", []):
                        mcp_servers[server_name] = {
                            k: v
                            for k, v in server_config.items()
                            if k in ("transport", "command", "args", "url", "env")
                        }
            
            # 创建并配置工具
            if len(mcp_servers) != 0:
                try:
                    client = MultiServerMCPClient(mcp_servers)
                    tools = await client.get_tools(server_name="Sandbox")
                    self.log_execution("Using sandbox service for code execution")
                except Exception as e:
                    self.log_execution(f"Could not establish connection with sandbox service: {e}. Fallback to python_repl_tool")
                    tools = [python_repl_tool]
            else:
                self.log_execution("No sandbox configured. Using python_repl_tool")
                tools = [python_repl_tool]
            
            # 创建coder agent
            coder_agent = create_agent("coder", "coder", tools, "coder")
            
            # 执行agent
            recursion_limit = int(os.getenv("AGENT_RECURSION_LIMIT", "30"))
            result = await coder_agent.ainvoke(
                input={"messages": messages}, 
                config={"recursion_limit": recursion_limit}
            )
            
            self.log_execution(f"Coder execution completed")
            execution_result = result["messages"][-1].content
            current_step.execution_res = execution_result
            
            # 确定下一个节点
            next_node = self.determine_next_node(state)
            
            return Command(
                update={
                    "messages": [AIMessage(content=execution_result, name="coder")],
                    "current_plan": current_plan,
                    "current_step_index": current_step_index
                },
                goto=next_node
            )
            
        except Exception as e:
            self.log_execution(f"Error in coder execution: {e}")
            return Command(
                update={
                    "messages": [AIMessage(content=f"Error in coding: {str(e)}", name="coder")]
                },
                goto="reporter"
            )