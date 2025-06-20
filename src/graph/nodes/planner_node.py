# nodes/planner_node.py
"""规划器节点"""

from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
import json
import logging

logger = logging.getLogger(__name__)

class PlannerNode(BaseNode):
    """规划器节点 - 制定执行计划"""
    
    def __init__(self, toolmanager):
        super().__init__("planner", AgentConfiguration.NODE_CONFIGS["planner"], toolmanager)
        self.call_params = {
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

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) \
        -> Command[Literal["writer", "reporter", "__end__"]]: #"coder", "searcher", "reader", "thinker"
        """执行规划器逻辑"""
        self.log_execution("Generating execution plan")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.prompts.template import apply_prompt_template
        from src.llms.llm import get_llm_by_type
        from src.prompts.planner_model import Plan

        configurable = Configuration.from_runnable_config(config)
        messages = apply_prompt_template("planner", state, configurable)
        
        # 使用结构化输出生成计划
        llm = get_llm_by_type(self.config.llm_type)
        #.with_structured_output(
            # Plan, method="json_mode"
        # )
        response = llm.invoke(messages)
        self.log_execution(response)
        self.log_execution(response.content)
        plan_content = response.content.split("<|plan|>")[1].split("<|end|>")[0]
        # plan_content = response.model_dump_json(indent=4, exclude_none=True)
        """ plan 输出结果示意
        [
        {
            "title": "AI Market Research Project",
            "description": "Comprehensive analysis of current AI market trends and opportunities",
            "goals": [
                {
                    "id": "G1",
                    "description": "Market data collection and analysis",
                    "actions": [
                        {
                            "id": "G1-A1",
                            "description": "Search for current AI market size and growth data",
                            "type": "searcher",
                            "dependencies": [],
                            "details": "Focus on 2024-2025 market data from reliable sources",
                            "references": [],
                            "status": "pending"
                        },
                        {
                            "id": "G1-A2", 
                            "description": "Analyze collected market data and identify trends",
                            "type": "interpreter",
                            "dependencies": ["G1-A1"],
                            "details": "Create visual representations and key insights",
                            "references": [],
                            "status": "pending"
                        }
                    ]
                },
                {
                    "id": "G2",
                    "description": "Report generation",
                    "actions": [
                        {
                            "id": "G2-A1",
                            "description": "Generate comprehensive market research report",
                            "type": "reporter", 
                            "dependencies": ["G1-A2"],
                            "details": "Include executive summary, detailed analysis, and recommendations",
                            "references": [],
                            "status": "pending"
                        }
                    ]
                }
            ]
        }
    ]
        """
        self.log_execution(f"Generated plan: {plan_content}")
        
        plan_dict = json.loads(plan_content)
        new_plan = Plan.model_validate(plan_dict)

        # 确定第一个要执行的节点
        if len(new_plan.goals) > 0:
            first_step = new_plan.goals[0].actions[0]
            """
            {
                "id": "G1-A1",
                "description": "action1的详细描述",
                "type": "员工类型", "searcher" "receiver" "coder" "interpreter" "anaylzer" "reporter" 
                "dependencies": []  // 依赖的action id,
                "details": "需要补充的相关细节信息，但是不要限定子模型具体使用的工具"
                "references":[], //reference ids
                "status": "pending|waiting|processing|completed"
            }

            """
            summary = f"# 当前任务:\n{first_step.description}\n## details\n {first_step.details}\n"
            next_node = AgentConfiguration.STEP_TYPE_TO_NODE.get(
                first_step.type.lower(), "writer"
            )
            return Command(
                update={
                    "current_plan": new_plan,
                    'current_step_index': "G1-A1",
                    "messages": [HumanMessage(content=summary, name="planner")],
                },
                goto=next_node
            )
        else:
            next_node = "reporter"
        
        return Command(
            update={
                "current_plan": new_plan,
                'current_step_index': "G1-A1",
                "messages": [HumanMessage(content=json.dumps(plan_content, ensure_ascii=False, indent=2), name="planner")],
            },
            goto=next_node
        )
            