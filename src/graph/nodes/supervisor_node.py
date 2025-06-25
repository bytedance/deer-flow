from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
from src.prompts.template import apply_prompt_template
from src.prompts.planner_model import Plan
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
        
    def get_step_state(self, plan: Plan, step_index: str):
        """
        获取id的step信息， 同时获取当前和下一节点信息，如果无下一节点返回空字典
        "id": "G1-A1",
        "description": "action1的详细描述",
        "type": "员工类型",
        "dependencies": []  // 依赖的action id,
        "details": "需要补充的相关细节信息，但是不要限定子模型具体使用的工具"
        "references":[], //reference ids
        "status": "pending|waiting|processing|completed"
        """
        current_action = {}
        next_action = {}
        fetch_next_step = False
        for G_step in plan.goals:
            for action in G_step.actions:
                if fetch_next_step:
                    next_action = action
                    return current_action, next_action
                if action.id == step_index:
                    fetch_next_step = True
                    current_action = action
                
        if current_action != {}:
            return current_action, next_action
        else:
            raise ValueError

    def get_dependencies(self, action):
        dependencies_ids = action.dependencies
        dependencies_actions = []
        for G_step in self.current_plan.goals:
            for action in G_step.actions:
                if action.id in dependencies_ids:
                    dependencies_actions.append(action)
        return dependencies_actions
                
    def get_next_step(self, next_action):
        # 只获取下一个step的信息和其依赖，汇总为文字summary
        dependencies_actions = self.get_dependencies(next_action)
        summary = f"# 当前任务:\n{next_action.description}\n## details\n {next_action.details}\n"
        summary += "## 依赖的其他任务结果:\n"
        for action in dependencies_actions:
            # if "execution_res" in action:
            summary += f"### 任务描述:\n{action.description}\n### 任务结果：\n{action.execution_res}\n"

        return summary
    
    def check_plan_complete(self, plan: Plan):
        # 检查是否完成整个plan
        for G_step in plan.goals:
            for action in G_step.actions:
                if action.status != "completed":
                    return False
        return True
                
    def plan_update(self, current_step_index, current_step_res):
        for G_step in self.current_plan.goals:
            for action in G_step.actions:
                if action.id == current_step_index:
                    action.execution_res = current_step_res

    def plan_res_summary(self):
        summary = f"# 终极任务：\n{self.current_plan.description}\n"
        for G_step in self.current_plan.goals:
            summary += f"## 主要任务 {G_step.id} 的目标：\n{G_step.description}\n"
            for action in G_step.actions:
                summary += f"### 次要任务 {action.id} 的目标：\n{action.description}\n"
                summary += f"完成情况：{action.execution_res}\n"
        return summary

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) \
        -> Command[Literal["writer", "reporter", "searcher", "coder", "interpreter", "reader", "__end__"]]|Dict[str, Any]:
        """执行supervisor逻辑"""
        self.log_execution("Evaluating step completion")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.llms.llm import get_llm_by_type
       
        configurable = Configuration.from_runnable_config(config)
        if not self.current_plan:
            self.current_plan = state.get("current_plan")

        current_step_index = state.get("current_step_index")
        current_action, next_action  = self.get_step_state(self.current_plan, current_step_index)
        current_messages = state["messages"]
        current_step_res = state["messages"][-1].content

        current_task_summary = f"# Action Task:\n{current_action.description}\n# Action condition:\n{current_step_res}"
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

                    if next_action == {}:
                        # 全部任务完成，汇总信息返回
                        self.log_execution(f"Plan complete")
                        self.plan_update(current_step_index, current_step_res)
                        return {"final_report": current_step_res}

                    else:
                        # 任务完成继续任务
                        self.log_execution(f"Step {current_step_index} complete")
                        self.plan_update(current_step_index, current_step_res)
                        self.log_execution("supervisor plan update")
                        self.log_execution(self.current_plan)
                        next_node = AgentConfiguration.STEP_TYPE_TO_NODE[next_action.type.lower()]
                        # .get(
                        #     next_action.type.lower(), "reporter"
                        # )
                        next_step_summary = self.get_next_step(next_action)
                        return Command(
                            update={
                                "messages": [HumanMessage(content=next_step_summary, name="supervisor")],
                                "current_step_index": next_action.id,  
                                "supervisor_iterate_time": 0
                            },
                            goto=next_node
                        )
        
        # 如果没有工具调用，直接结束流程
        return {"final_report": current_step_res}
        