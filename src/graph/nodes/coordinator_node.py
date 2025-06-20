# nodes/coordinator_node.py
"""协调器节点"""

import json
from .base_node import BaseNode
from src.prompts.template import apply_prompt_template
from src.config.agents import AgentConfiguration
from src.llms.llm import get_llm_by_type
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
from src.config.configuration import Configuration
import logging

logger = logging.getLogger(__name__)



class CoordinatorNode(BaseNode):
    """协调器节点 - 过滤无意义问题"""
    
    def __init__(self, toolmanager):
        super().__init__("coordinator", AgentConfiguration.NODE_CONFIGS["coordinator"], toolmanager)
    
        self.webSearchTool = {
            "name": "web_search",
            "description": "This function acts as a search engine to retrieve a wide range of information from the web. It is capable of processing queries related to various topics and returning relevant results.This search tool's performance is limited and it only returns summary information. Therefore, it's necessary to narrow down the search scope as much as possible. For example, avoid searching for specific time periods. Note: Except for proper nouns, abbreviations, and terms, it is recommended to use Chinese for search keywords to obtain better search results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query used to retrieve information from the internet. Rewrite and optimize the query based on conversation history for best search quality.The keywords should not exceed four."
                    }
                },
                "required": [
                    "query"
                ]
            }
        }

        self.askUserTool = {
            "name": "message_ask_user",
            "description": "Ask user a question and wait for response. Use for requesting clarification, asking for confirmation, or gathering additional information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The question text for user interaction, structured clearly to guide the user's response."
                    }
                },
                "required":[
                    "text"
                ]
            }
        }

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["planner", "__end__"]]:
        """执行协调器逻辑"""
        self.log_execution("Starting coordination")
    
        # 初始化 enabled_tools 下一个节点的tool call信息不在此初始化
        tools = self.tools_manager.get_tools_for_node(self.name)
        tools.extend(self.tools_manager.get_node_functioncall("planner"))

        configurable = Configuration.from_runnable_config(config)
        messages = apply_prompt_template("coordinator", state, configurable)
        
        llm = get_llm_by_type(self.config.llm_type).bind_tools(tools)
        response = llm.invoke(messages)

        self.log_execution(f"Coordinator response: {response.content}")
        
        max_toolcall_iterater_times = configurable.max_toolcall_iterater_times
        iterater_times = 0
        while hasattr(response, 'tool_calls') \
            and response.tool_calls \
            and iterater_times < max_toolcall_iterater_times:
            self.log_execution(f"Coordinator tool call: {response.tool_calls}")
            iterater_times += 1
            logger.info(f"call times: {iterater_times}")
            for tool_call in response.tool_calls:
                if tool_call["name"] == "planner":

                    # 这里直接给planner
                    return Command(
                        update={
                            "messages": [HumanMessage(content=json.dumps(tool_call["args"], ensure_ascii=False, indent=2), name="coordinator")]
                        },
                        goto="planner"
                    )
                elif tool_call["name"] == "web_search":
                    # TODO web_search
                    from src.tools.search import LoggedTavilySearch
                    from src.config import SELECTED_SEARCH_ENGINE, SearchEngine
                    # TODO
                    # 背景调研
                    if state.get("enable_background_investigation", True):
                        query = state["messages"][-1].content
                        if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
                            try:
                                searched_content = LoggedTavilySearch(
                                    max_results=configurable.max_search_results
                                ).invoke(query)
                                if isinstance(searched_content, list):
                                    background_results = [
                                        {"title": elem["title"], "content": elem["content"]}
                                        for elem in searched_content
                                    ]
                                    messages.append({
                                        "role": "user",
                                        "content": f"Background investigation results:\n{json.dumps(background_results, ensure_ascii=False)}"
                                    })
                            except Exception as e:
                                self.log_execution(f"Background research failed: {e}")
                    tool_summary = ""
                    # 第二次LLM调用：基于MCP结果分析
                    messages = messages + [
                        HumanMessage(content=response.content, tool_calls=response.tool_calls),
                        ToolMessage(content= tool_summary,
                            tool_call_id=response.tool_calls[0]["id"]  # 必须与上面的 id 匹配
                        )
                        ]
                    response = llm.invoke(messages)

        if iterater_times == 0:
            goto = "__end__"
            return Command(
                update={
                    "messages": [HumanMessage(content=response.content, name="coordinator")],
                    "current_step_index": "G"
                },
                goto=goto
            )
                