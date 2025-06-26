# nodes/thinker_node.py
"""思考器节点"""

from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
import logging

logger = logging.getLogger(__name__)

class ThinkerNode(BaseNode):
    """思考器节点 - 使用推理模型，能够深度思考问题"""
    
    def __init__(self, toolmanager):
        super().__init__("thinker", AgentConfiguration.NODE_CONFIGS["thinker"], toolmanager)
    
    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        """执行思考器逻辑"""
        self.log_execution("Starting deep thinking task")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.prompts.template import apply_prompt_template
        from src.llms.llm import get_llm_by_type
        
        try:
            configurable = Configuration.from_runnable_config(config)
            
            # 推进到下一步
            current_step_index = self.get_next_step_index(state)
            current_plan = state.get("current_plan")
            
            if not current_plan or current_step_index >= len(current_plan.steps):
                return Command(goto="reporter")
            
            current_step = current_plan.steps[current_step_index]
            self.log_execution(f"Working on step {current_step_index}: {current_step.title}")
            
            # 构建thinker输入
            thinker_input = {
                "messages": [
                    HumanMessage(
                        content=f"""# Current Task

## Title
{current_step.title}

## Description
{current_step.description}

## Previous Message
{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}

## Context
Please engage in deep, systematic thinking about this problem. Consider multiple perspectives, analyze potential solutions, evaluate trade-offs, and provide a comprehensive analysis.

## Locale
{state.get('locale', 'en-US')}"""
                    )
                ],
                "locale": state.get("locale", "en-US"),
                "resources": state.get("resources", [])
            }
            
            messages = apply_prompt_template("thinker", thinker_input, configurable)
            
            # 使用推理模型进行深度思考
            response = get_llm_by_type(self.config.llm_type).invoke(messages)
            
            self.log_execution("Deep thinking completed")
            current_step.execution_res = response.content
            
            # 确定下一个节点
            next_node = self.determine_next_node(state)
            
            return Command(
                update={
                    "messages": [AIMessage(content=response.content, name="thinker")],
                    "current_plan": current_plan,
                    "current_step_index": current_step_index
                },
                goto=next_node
            )
            
        except Exception as e:
            self.log_execution(f"Error in thinker execution: {e}")
            return Command(
                update={
                    "messages": [AIMessage(content=f"Error in thinking: {str(e)}", name="thinker")]
                },
                goto="reporter"
            )