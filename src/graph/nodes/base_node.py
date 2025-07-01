"""基础节点抽象类"""

from datetime import datetime
import json
from src.config.agents import AgentConfiguration
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Union
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
import logging
from src.config.agents import NodeConfig
from src.graph.tools.tool_manager import ToolManager
from src.prompts.planner_model import Plan, Action, Goal, TaskStatus

log_filename = datetime.now().strftime("logs/log_%Y-%m-%d_%H-%M.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),  # 将日志写入文件
        logging.StreamHandler()  # 同时输出到终端
    ]
)
logger = logging.getLogger(__name__)

class BaseNode(ABC):
    """节点基类"""
    
    def __init__(self, name: str, config: 'NodeConfig', tools_manager: 'ToolManager'):
        # self.log_execution("Starting analysis")    
        self.name = name
        self.config = config
        self.tools_manager = tools_manager
        self.iteration_count = 0
        self.call_params = {} # function call 到当前节点需要传入的参数

    @abstractmethod
    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command:
        """执行节点逻辑"""
        pass

    # Utility functions
    def update_plan_action_status(self,
        plan: Plan,
        action_id: str,
        new_status: TaskStatus,
        execution_res: Optional[str] = None
    ) -> Plan:

        for goal in plan.goals:
            for action in goal.actions:
                if action.id == action_id:
                    action.status = new_status
                    action.execution_res = execution_res

    def get_next_action(self, plan: Plan, step_index: str) -> Optional[Action]:
        found = False
        for goal in plan.goals:
            for action in goal.actions:
                if found:
                    return action
                if action.id == step_index:
                    found = True
        return None

    def get_action(self, plan: Plan, step_index: str) -> Optional[Action]:

        for goal in plan.goals:
            for action in goal.actions:
                if action.id == step_index:
                    return action
        raise ValueError("get wrong action id")
    
    def find_goal_for_action(self, plan: Plan, action_id: str) -> Optional[Goal]:
        for goal in plan.goals:
            for action in goal.actions:
                if action.id == action_id:
                    return goal
        return None

    def collect_dependencies(self, plan: Plan, 
                             action_id: str, 
                             depth: int = 0, 
                             visited: Optional[Set[str]] = None
                             ) -> Set[str]:
        depth += 1
        if depth > 2:
            return visited
        if visited is None:
            visited = set()
        if action_id in visited:
            return visited
        visited.add(action_id)
        for goal in plan.goals:
            for action in goal.actions:
                if action.id == action_id:
                    for dep_id in action.dependencies:
                        self.collect_dependencies(plan, dep_id, depth, visited)
        return visited
    
    def get_references(self, references:list, resources: list[Dict]=None):
        if references == []:
            return []
        else:
            references_ontent = []
            for ref in references:
                if ref_content in resources[int(ref)]:
                    ref_content = resources[int(ref)][""]
                else:
                    ref_content = "文件过长，无法解析内容"
                references_ontent.append(
                    {
                        "file": resources[int(ref)]["uri"],
                        "content": ref_content
                    }
                )
            return references_ontent
        
    def get_action_with_dependencies_json(self, plan: Plan, target_action_id: str, resources: list[Dict] = None) -> str:
        if not any(action.id == target_action_id for goal in plan.goals for action in goal.actions):
            raise ValueError(f"Action with ID '{target_action_id}' not found in plan")
        all_action_ids = self.collect_dependencies(plan, target_action_id)
        all_action_ids = sorted(list(all_action_ids))
        result_goals = []
        for goal in plan.goals:
            goal_actions = [action for action in goal.actions if action.id in all_action_ids]
            if goal_actions:
                result_goals.append({
                    "id": goal.id,
                    "description": goal.description,
                    "actions": [
                        {
                            "id": action.id,
                            "description": action.description,
                            "type": action.type.value,
                            "dependencies": action.dependencies,
                            "references": self.get_references(action.references, resources) if action.id==target_action_id else action.references,
                            "details": action.details,
                            "status": action.status.value,
                            **({"result": action.execution_res} if action.execution_res is not None else {})
                        }
                        for action in goal_actions
                    ]
                })
        result = {
            "title": plan.title,
            "description": plan.description,
            "goals": result_goals
        }
        return f"</plan>\n\n{json.dumps(result, ensure_ascii=False, separators=(',', ':'))}\n\n</plan>your task is {target_action_id}"

    # log
    def show_current_plan(self, plan: Plan):
        """展示当前计划"""
        logger.info(plan)

    def log_execution(self, message: str):
        """记录执行日志"""
        logger.info(f"[{self.name}] {message}")
    
    def log_input_message(self, message: List):
        """记录输入的信息"""
        logger.info("-" * 50)
        logger.info(f"👇[{self.name}| Input Message]👇")
        for item in message: 
            if item.type != "system":
                logger.info(f"角色: {item.type}")
                logger.info(f"内容: {item.content}")
                if 'additional_kwargs' in item:
                    logger.info(f"附加参数: {item.additional_kwargs}")
                if 'response_metadata' in item:
                    logger.info(f"响应元数据: {item.response_metadata}")
                logger.info("-" * 50)

    def log_tool_call(self, response: str, iterate_times: int):
        """记录node的toolcall， 默认逻辑除了planner之外都需要toolcall"""
        logger.info("+" * 50)
        logger.info(f"[{self.name} | iterate time] {iterate_times}")
        logger.info(f"👇[{self.name} | Must Tool Call]👇")
        logger.info(f"[{self.name}] {response}")
        logger.info("+" * 50)

    def log_execution_warning(self, message: str):
        """记录warnin日志"""
        logger.warning(f"[{self.name}] {message}")

    def log_execution_error(self, message: str):
        """记录error日志"""
        logger.error(f"[{self.name}] {message}")