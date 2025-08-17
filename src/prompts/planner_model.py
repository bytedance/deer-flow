# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from enum import Enum
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, validator


class StepType(str, Enum):
    RESEARCH = "research"
    PROCESSING = "processing"


class StepTool(BaseModel):
    """表示步骤中使用的工具。"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    server: str = Field(..., description="工具所属的MCP服务器")
    parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="工具参数配置"
    )

    @validator('name')
    def validate_name(cls, v):
        """验证工具名称不能为空且符合命名规范"""
        if not v or not v.strip():
            raise ValueError("工具名称不能为空")
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError("工具名称只能包含字母、数字、下划线和连字符")
        return v.strip()

    @validator('server')
    def validate_server(cls, v):
        """验证服务器名称不能为空"""
        if not v or not v.strip():
            raise ValueError("服务器名称不能为空")
        return v.strip()

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "name": "tavily_search",
                    "description": "Search the web for current information",
                    "server": "tavily",
                    "parameters": {
                        "query": "AI market trends 2024",
                        "max_results": 10
                    }
                }
            ]
        }


class Step(BaseModel):
    need_search: bool = Field(..., description="Must be explicitly set for each step")
    title: str
    description: str = Field(..., description="Specify exactly what data to collect")
    step_type: StepType = Field(..., description="Indicates the nature of the step")
    tools: Optional[List[StepTool]] = Field(
        default=None, description="MCP工具列表，用于此步骤的执行"
    )
    execution_res: Optional[str] = Field(
        default=None, description="The Step execution result"
    )

    @validator('tools')
    def validate_tools(cls, v):
        """验证工具列表的合理性"""
        if v is not None:
            # todo: 检查工具名称是否重复, 如果名称和参数完全一致, 要有对应的策略.
            # tool_names = [tool.name for tool in v]
            # if len(tool_names) != len(set(tool_names)):
            
            # 检查工具列表不能为空
            if len(v) == 0:
                raise ValueError("如果指定了工具列表，则不能为空")
        
        return v


class Plan(BaseModel):
    locale: str = Field(
        ..., description="e.g. 'en-US' or 'zh-CN', based on the user's language"
    )
    has_enough_context: bool
    thought: str
    title: str
    steps: List[Step] = Field(
        default_factory=list,
        description="Research & Processing steps to get more context",
    )

    @validator('steps')
    def validate_steps(cls, v):
        """验证步骤列表的合理性"""
        if v:
            # 检查步骤标题是否重复
            step_titles = [step.title for step in v]
            if len(step_titles) != len(set(step_titles)):
                raise ValueError("计划中不能包含重复标题的步骤")
        
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "has_enough_context": False,
                    "thought": (
                        "To understand the current market trends in AI, we need to gather comprehensive information."
                    ),
                    "title": "AI Market Research Plan",
                    "steps": [
                        {
                            "need_search": True,
                            "title": "Current AI Market Analysis",
                            "description": (
                                "Collect data on market size, growth rates, major players, and investment trends in AI sector."
                            ),
                            "step_type": "research",
                            "tools": [
                                {
                                    "name": "tavily_search",
                                    "description": "Search the web for current information",
                                    "server": "tavily",
                                    "parameters": {
                                        "query": "AI market trends 2024",
                                        "max_results": 10
                                    }
                                }
                            ]
                        }
                    ],
                }
            ]
        }
