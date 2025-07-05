# nodes/coordinator_node.py
"""协调器节点"""

import json
from .base_node import BaseNode
from src.prompts.template import apply_prompt_template
from src.config.agents import AgentConfiguration
from src.llms.llm import get_llm_by_type
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
from typing import Literal, Dict, Any
from src.config.configuration import Configuration

class CoordinatorNode(BaseNode):
    """协调器节点 - 过滤无意义问题"""
    
    def __init__(self, toolmanager):
        super().__init__("coordinator", AgentConfiguration.NODE_CONFIGS["coordinator"], toolmanager)
    
        self.call_planner = {
            "name": "planner",
            "description": "Trigger the task planning process, automatically advancing the planning workflow. No direct response is returned as the user will see the results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "A concise and clear task title."
                    },
                    "description": {
                        "type": "string",
                        "description": "A brief description summarizing the task."
                    },
                    "requirements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific requirements for the task."
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of constraints to follow during task execution."
                    },
                    "references": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique identifier for the reference."},
                                "type": {"type": "string", "description": "Type of reference: file|knowledge"},
                                "name": {"type": "string", "description": "File name."},
                                "function": {"type": "string", "description": "Summarize the purpose of the document; the planner will relay this information."}
                            },
                            "required": ["id", "type", "name", "function"]
                        },
                        "description": "List of reference materials provided by the user. References will be indicated using the <file>/<knowledge> tags. Do not fabricate information."
                    },
                    "expected_outcome": {
                        "type": "string",
                        "description": "The desired outcome after completing the task."
                    },
                    # "status": {
                    #     "type": "string",
                    #     "enum": ["collecting", "clarifying", "thinking", "complete"],
                    #     "description": "Current status of the task, indicating progress."
                    # },
                    "confidence": {
                        "type": "object",
                        "properties": {
                            "score": {
                                "type": "number",
                                "description": "Confidence score (0.00 - 1.00)."
                            },
                            "missing_info": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Potential missing information items."
                            }
                        },
                        "description": "Task confidence score (0.00 - 1.00). Use the score to determine the task's readiness. Ensure the score reaches 0.9 or above before setting the status to 'complete'.",
                        "required": ["score", "missing_info"]
                    }
                },
                "required": ["title", "description", "requirements", "constraints", "references", "expected_outcome", "status", "confidence"]
            }
        }

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

        self.tools = [self.webSearchTool, self.askUserTool, self.call_planner]

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["planner", "__end__"]]:
        """执行协调器逻辑"""
        self.log_execution("Starting coordination")
    
        # 执行节点标准流程 
        configurable = Configuration.from_runnable_config(config)
        messages = apply_prompt_template(self.name, state, configurable)
        self.log_input_message(messages)
        llm = get_llm_by_type(self.config.llm_type).bind_tools(self.tools)
        response = llm.invoke(messages)
        self.log_execution(response)
        
        max_toolcall_iterate_times = configurable.max_toolcall_iterate_times
        iterate_times = state.get("tool_call_iterate_time", 0)
        if hasattr(response, 'tool_calls') and response.tool_calls \
            and iterate_times < max_toolcall_iterate_times:
            iterate_times += 1
            self.log_tool_call(response, iterate_times)

            for tool_call in response.tool_calls:
                if tool_call["name"] == "planner":
                    # 这里直接给planner
                    return Command(
                        update={
                            "messages": [HumanMessage(content=json.dumps(tool_call["args"], ensure_ascii=False), name="coordinator")],
                            "tool_call_iterate_time" : 0
                        },
                        goto="planner"
                    )
                
                elif tool_call["name"] == "web_search":
                    from src.tools.search import get_web_search_tool, filter_garbled_text

                    background_summary = "相关背景信息收集:\n"
                    search_engine = get_web_search_tool(configurable.max_search_results)
                    try:
                        
                        searched_content = search_engine.invoke(tool_call["args"])
                        for elem in searched_content:
                            background_summary += f"- 题目：{ elem["title"]}\n- 内容：{elem["content"]}\n"
                        
                    except Exception as e:
                        self.log_execution(f"Background research failed: {e}")
                    background_summary = filter_garbled_text(background_summary)
                    return Command(
                        update={
                            "messages": [response, ToolMessage(content=background_summary, tool_call_id=tool_call["id"])],
                            "tool_call_iterate_time" : iterate_times
                        },
                        goto="coordinator"
                    )

                elif tool_call["name"] == "message_ask_user":
                    feedback = str(interrupt(tool_call["args"]["text"]))
                    # 整理feedback 返回节点
                    feedback_query = f"Human feedback: {feedback}"
                    return Command(
                        update={
                            "messages": [response,
                                ToolMessage(content=feedback_query, tool_call_id=tool_call["id"])],
                            "tool_call_iterate_time" : iterate_times
                        },
                        goto="coordinator"
                    )
        else:
            self.log_execution("NO tool call, complete dialogue directly")
        
            goto = "__end__"
            return {"final_report": response.content}

                