from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EmployeeType(str, Enum):
    SEARCHER = "searcher"
    RECEIVER = "receiver" 
    CODER = "coder"
    INTERPRETER = "interpreter"
    ANALYZER = "anaylzer"
    REPORTER = "reporter"


class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"


class Confidence(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    missing_info: List[str] = Field(default_factory=list, description="List of potentially missing information")


class TaskInfo(BaseModel):
    title: str = Field(..., description="Task title")
    description: str = Field(..., description="Detailed task description")
    requirements: List[str] = Field(default_factory=list, description="List of requirements")
    constraints: List[str] = Field(default_factory=list, description="List of constraints")
    expected_outcome: str = Field(..., description="Expected task completion result")
    status: str = Field(..., description="Task information collection status")
    references: str = Field(default="", description="User uploaded files and their usage description")
    confidence: Confidence = Field(..., description="Confidence assessment")


class Action(BaseModel):
    id: str = Field(..., description="Action ID in format G{n}-A{m}")
    description: str = Field(..., description="Detailed action description")
    type: EmployeeType = Field(..., description="Employee type for this action")
    dependencies: List[str] = Field(default_factory=list, description="List of dependent action IDs")
    details: str = Field(default="", description="Additional details, but don't limit specific tools for sub-models")
    references: List[str] = Field(default_factory=list, description="Reference IDs")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Action status")
    execution_res: Optional[str] = Field(default=None, description="Action execution result")


class Goal(BaseModel):
    id: str = Field(..., description="Goal ID in format G{n}")
    description: str = Field(..., description="Detailed goal description")
    actions: List[Action] = Field(default_factory=list, description="List of actions under this goal")


class Plan(BaseModel):
    title: str = Field(..., description="Task title")
    description: str = Field(..., description="Task description summary")
    goals: List[Goal] = Field(default_factory=list, description="List of goals with their actions")
    
    class Config:
        json_schema_extra = {
            "examples": [
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
        }