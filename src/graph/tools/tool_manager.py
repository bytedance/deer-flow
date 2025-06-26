# core/tool_manager.py
"""工具管理器"""

from typing import Dict, List, Any, Callable
from src.config.agents import ToolConfig, AgentConfiguration
import logging

logger = logging.getLogger(__name__)

class ToolManager:
    """工具管理器 - 统一管理所有工具"""
    
    def __init__(self):
        self.tools: Dict[str, Any] = {}
        self.tool_configs: Dict[str, ToolConfig] = {}
        self._initialize_default_configs()
    
    def _initialize_default_configs(self):
        """初始化默认工具配置"""
        self.tool_configs = AgentConfiguration.TOOL_CONFIGS.copy()
    
    def register_tool(self, tool_name: str, tool_func: Callable|dict, config: ToolConfig = None):
        """
        注册工具
        Args:
            tool_name: 工具名称
            tool_func: 工具函数
            config: 工具配置，如果为None则使用默认配置
        """
        if tool_func == {}:
            return
        self.tools[tool_name] = tool_func
        
        if config:
            self.tool_configs[tool_name] = config
        elif tool_name not in self.tool_configs:
            # 如果没有配置且不在默认配置中，创建默认配置
            self.tool_configs[tool_name] = ToolConfig(
                name=tool_name,
                type="interactive",
                enabled=True
            )
        
        logger.debug(f"Registered tool: {tool_name}")
    
    def get_tools_for_node(self, node_name: str) -> List[Any]:
        """
        获取节点可用的工具
        Args:
            node_name: 节点名称
        Returns:
            List[Any]: 可用的工具列表
        """
        node_config = AgentConfiguration.NODE_CONFIGS.get(node_name)
        if not node_config:
            logger.warning(f"No configuration found for node: {node_name}")
            return []
        available_tools = []
        for tool_name in node_config.enabled_tools:
            if tool_name in self.tools and self.tool_configs.get(tool_name, ToolConfig("", "interactive")).enabled:
                available_tools.append(self.tools[tool_name])
                logger.debug(f"Added tool {tool_name} to node {node_name}")

        logger.info(f"Node {node_name} has {len(available_tools)} available tools")
        return available_tools
    
    def get_node_functioncall(self, node_name:str) -> list[Dict]:
        """
        获取节点的调用fc信息 默认是一个dict， 此时已经初始化结束，call_{node_name}_agent
        Args:
            node_name (str): 节点名称
        Returns:
            Dict: 节点的函数调用信息
            {
                "name": "planner",
                "description": "xxx",
                "parameters": {}
            }
        """
        # 获取节点的调用信息
        function_call = [self.tools.get(f"call_{node_name}_agent", None)]
        return function_call
    
    def is_direct_tool(self, tool_name: str) -> bool:
        """
        判断是否为直接工具
        Args:
            tool_name: 工具名称
        Returns:
            bool: True为直接工具，False为交互式工具
        """
        config = self.tool_configs.get(tool_name)
        return config and config.type == "direct"
    
    def is_interactive_tool(self, tool_name: str) -> bool:
        """
        判断是否为交互式工具
        Args:
            tool_name: 工具名称
        Returns:
            bool: True为交互式工具，False为直接工具
        """
        return not self.is_direct_tool(tool_name)
    
    def get_tool_config(self, tool_name: str) -> ToolConfig:
        """
        获取工具配置
        Args:
            tool_name: 工具名称
        Returns:
            ToolConfig: 工具配置
        """
        return self.tool_configs.get(tool_name)
    
    def enable_tool(self, tool_name: str):
        """启用工具"""
        if tool_name in self.tool_configs:
            self.tool_configs[tool_name].enabled = True
            logger.info(f"Enabled tool: {tool_name}")
    
    def disable_tool(self, tool_name: str):
        """禁用工具"""
        if tool_name in self.tool_configs:
            self.tool_configs[tool_name].enabled = False
            logger.info(f"Disabled tool: {tool_name}")
    
    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        列出所有工具及其状态
        Returns:
            Dict[str, Dict[str, Any]]: 工具信息字典
        """
        tool_info = {}
        for tool_name, tool_func in self.tools.items():
            config = self.tool_configs.get(tool_name)
            tool_info[tool_name] = {
                "registered": True,
                "enabled": config.enabled if config else False,
                "type": config.type if config else "unknown",
                "max_retries": config.max_retries if config else 0,
                "function": tool_func.__name__ if hasattr(tool_func, '__name__') else str(tool_func)
            }
        
        # 添加配置中但未注册的工具
        for tool_name, config in self.tool_configs.items():
            if tool_name not in self.tools:
                tool_info[tool_name] = {
                    "registered": False,
                    "enabled": config.enabled,
                    "type": config.type,
                    "max_retries": config.max_retries,
                    "function": None
                }
        
        return tool_info
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取工具管理器统计信息
        Returns:
            Dict[str, Any]: 统计信息
        """
        tool_info = self.list_tools()
        
        stats = {
            "total_tools": len(tool_info),
            "registered_tools": sum(1 for info in tool_info.values() if info["registered"]),
            "enabled_tools": sum(1 for info in tool_info.values() if info["enabled"]),
            "direct_tools": sum(1 for info in tool_info.values() if info["type"] == "direct"),
            "interactive_tools": sum(1 for info in tool_info.values() if info["type"] == "interactive"),
            "unregistered_tools": sum(1 for info in tool_info.values() if not info["registered"])
        }
        
        return stats
