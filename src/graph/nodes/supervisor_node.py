from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
from src.prompts.template import apply_prompt_template
from src.prompts.planner_model import Plan, TaskStatus
import logging

logger = logging.getLogger(__name__)

class SupervisorNode(BaseNode):
    """Supervisor节点 - 评估步骤完成度"""
    
    def __init__(self, toolmanager):
        super().__init__("supervisor", AgentConfiguration.NODE_CONFIGS["supervisor"], toolmanager)
        self.current_plan = None
        self.adviseTool = {
            "name": "advise",
            "description": "This function is used to send advice to the action worker.",
            "parameters": {
                "type": "object",
                "properties": {
                "suggestion": {
                    "type": "string",
                    "description": "Identify specific issues using professional terminology, and clearly articulate the direction for improvement."
                },
                "score": {
                    "type": "float",
                    "description": "Score for the action result."
                }
                },
                "required": ["suggestion", "score"]
            }
        }
        self.completeTool = {
            "name": "complete",
            "description": "This function sends a signal to the manager to change the action status to 'complete'. This function will not get a response.",
            "parameters": {
                "type": "object",
                "properties": {
                "action_id": {
                    "type": "string",
                    "description": "The action ID."
                    }
                },
                "required": ["action_id"]
            }
        }

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) \
        -> Command[Literal["writer", "reporter", "searcher", "coder", "interpreter", "reader", "receiver", "__end__"]]|Dict[str, Any]:
        """执行supervisor逻辑"""
        self.log_execution("Supervisor step completion")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.llms.llm import get_llm_by_type
       
        configurable = Configuration.from_runnable_config(config)
        if not self.current_plan:
            self.current_plan = state.get("current_plan")
        current_step_index = state.get("current_step_index")
        current_action = self.get_action(self.current_plan, current_step_index)

        current_step_res = state["messages"][-1].content

        current_task_summary = f"### action_id\n{current_step_index}\n\n### result\n{current_step_res}"
        self.log_execution(f"[Supervisor action summary]:\n {current_task_summary}")
        supervisor_state = {
            "messages": [HumanMessage(content=current_task_summary)],
            "locale": state.get("locale", "en-US"),
            "resources": state.get("resources", [])
        }
        supervisor_input = apply_prompt_template("supervisor", supervisor_state, configurable)

        tools = [self.adviseTool, self.completeTool]
        # 使用LLM进行评估
        llm = get_llm_by_type(self.config.llm_type).bind_tools(tools)
        
        response = llm.invoke(supervisor_input)
        self.log_execution(response)
        # max_supervisor_iterate_times = configurable.max_supervisor_iterate_times
        # 处理supervisor的决策
        if hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                action = tool_call.get("name")
                
                if action == "advise":
                    # 打回重跑
                    self.log_execution(f"Step {current_step_index} not complete")
                    
                     # 根据当前步骤类型确定要重新执行的节点
                    retry_node = AgentConfiguration.STEP_TYPE_TO_NODE.get(
                        current_action.type.lower(), "reporter"
                    )
                    suggestion = tool_call["args"]["suggestion"]
                    score = tool_call["args"]["score"]
                    return Command(
                        update={
                            "messages": [HumanMessage(content=f"Step rejected: {suggestion}. \nStep score: {score}.\nPlease retry.", name="supervisor")],
                            "supervisor_iterate_time": state["supervisor_iterate_time"] + 1
                        },
                        goto=retry_node
                    )
                
                elif action == "complete":
                    next_action = self.get_next_action(self.current_plan, current_step_index)
                    
                    if next_action:
                        # 全部任务完成，汇总信息返回
                        self.log_execution(f"Plan complete")
                        self.update_plan_action_status(self.current_plan, current_step_index, TaskStatus.COMPLETED, current_step_res)
                        return {"final_report": current_step_res}

                    else:
                        # 任务完成继续任务
                        self.log_execution(f"Step {current_step_index} complete")
                        self.update_plan_action_status(self.current_plan, current_step_index, TaskStatus.COMPLETED, current_step_res)
                        self.log_execution("supervisor plan update")
                        # self.log_execution(self.current_plan)
                        next_node = AgentConfiguration.STEP_TYPE_TO_NODE[next_action.type.lower()]
                        # .get(
                        #     next_action.type.lower(), "reporter"
                        # )
                        self.log_execution(f"next_node: {next_node}")
                        self.log_execution(f"next_action: {next_action}")
                        next_step_summary = self.get_action_with_dependencies_json(self.current_plan, next_action.id)
                        self.log_execution(f"next_step_summary: {next_step_summary}")
                        return Command(
                            update={
                                "messages": [RemoveMessage(id="__remove_all__"), 
                                             HumanMessage(content=next_step_summary, name="supervisor")],
                                "current_step_index": next_action.id,  
                                "supervisor_iterate_time": 0,
                            },
                            goto=next_node
                        )
        
        # 如果没有工具调用，直接结束流程
        return {"final_report": current_step_res}
        