"""基础节点抽象类"""

from src.config.agents import AgentConfiguration
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
import logging
from src.config.agents import NodeConfig
from src.graph.tools.tool_manager import ToolManager

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
       
    def log_execution(self, message: str):
        """记录执行日志"""
        logger.info(f"[{self.name}] {message}")
    