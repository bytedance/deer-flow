import json
from typing import Dict, Set, List
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class EmployeeType(str, Enum):
    SEARCHER = "searcher"
    RECEIVER = "receiver" 
    CODER = "coder"
    INTERPRETER = "interpreter"
    WRITER = "writer"
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


class PlanActionExtractor:
    def __init__(self, plan: Plan):
        self.plan = plan
        # 创建action ID到action对象的映射
        self.action_map: Dict[str, Action] = {}
        self._build_action_map()
    
    def _build_action_map(self):
        """构建action ID到action对象的映射"""
        for goal in self.plan.goals:
            for action in goal.actions:
                self.action_map[action.id] = action
    
    def _find_action_goal(self, action_id: str) -> Optional[Goal]:
        """找到包含指定action的goal"""
        for goal in self.plan.goals:
            for action in goal.actions:
                if action.id == action_id:
                    return goal
        return None
    
    def _collect_dependencies(self, action_id: str, visited: Set[str] = None) -> Set[str]:
        """递归收集所有依赖的action ID"""
        if visited is None:
            visited = set()
        
        if action_id in visited:
            return visited
        
        visited.add(action_id)
        
        if action_id in self.action_map:
            action = self.action_map[action_id]
            for dep_id in action.dependencies:
                self._collect_dependencies(dep_id, visited)
        
        return visited
    
    def get_action_with_dependencies(self, target_action_id: str) -> str:
        """
        获取指定action及其所有依赖项的完整信息，返回JSON字符串
        
        Args:
            target_action_id: 目标action的ID
            
        Returns:
            包含目标action及其依赖项的JSON字符串
        """
        if target_action_id not in self.action_map:
            raise ValueError(f"Action with ID '{target_action_id}' not found in plan")
        
        # 收集目标action及其所有依赖项
        all_action_ids = self._collect_dependencies(target_action_id)
        
        # 按goal分组，收集需要包含的actions
        goals_to_include = {}
        
        for action_id in all_action_ids:
            goal = self._find_action_goal(action_id)
            if goal:
                if goal.id not in goals_to_include:
                    goals_to_include[goal.id] = {
                        'goal': goal,
                        'actions': []
                    }
                
                action = self.action_map[action_id]
                goals_to_include[goal.id]['actions'].append(action)
        
        # 构建结果结构
        result_goals = []
        for goal_info in goals_to_include.values():
            goal_dict = {
                "id": goal_info['goal'].id,
                "description": goal_info['goal'].description,
                "actions": []
            }
            
            # 添加actions
            for action in goal_info['actions']:
                action_dict = {
                    "id": action.id,
                    "description": action.description,
                    "type": action.type.value,
                    "dependencies": action.dependencies,
                    "references": action.references,
                    "details": action.details,
                    "status": action.status.value
                }
                
                # 如果有执行结果，添加到字典中
                if action.execution_res is not None:
                    action_dict["result"] = action.execution_res
                
                goal_dict["actions"].append(action_dict)
            
            result_goals.append(goal_dict)
        
        # 构建最终结果
        result = {
            "title": self.plan.title,
            "description": self.plan.description,
            "goals": result_goals
        }
        
        return json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    
    def update_action_status(self, action_id: str, status: TaskStatus, execution_result: str = None):
        """
        更新action的状态和执行结果
        
        Args:
            action_id: action的ID
            status: 新的状态
            execution_result: 执行结果（可选）
        """
        if action_id in self.action_map:
            self.action_map[action_id].status = status
            if execution_result is not None:
                self.action_map[action_id].execution_res = execution_result
        else:
            raise ValueError(f"Action with ID '{action_id}' not found in plan")


# 示例使用
def example_usage():
    # 示例plan数据
    plan_data = {
        "title": "分析IF椰子水股票投资价值",
        "description": "从业务构成、市场空间、基石投资者及承销商表现等维度评估IFBH港股投资价值",
        "goals": [
            {
                "id": "G1",
                "description": "业务分析",
                "actions": [
                    {
                        "id": "G1-A1",
                        "description": "分析主营业务构成",
                        "type": "interpreter",
                        "dependencies": [],
                        "references": [],
                        "details": "重点关注椰子水业务占比",
                        "status": "completed",
                        "execution_res": "业务构成分析已完成"
                    },
                    {
                        "id": "G1-A2", 
                        "description": "评估市场空间和竞争地位",
                        "type": "searcher",
                        "dependencies": ["G1-A1"],
                        "references": [],
                        "details": "包含行业增长率和市占率分析",
                        "status": "completed",
                        "execution_res": "市场分析已完成"
                    }
                ]
            },
            {
                "id": "G2",
                "description": "投资者分析", 
                "actions": [
                    {
                        "id": "G2-A1",
                        "description": "分析基石投资者背景",
                        "type": "searcher",
                        "dependencies": [],
                        "references": [],
                        "details": "研究投资机构历史表现",
                        "status": "completed"
                    },
                    {
                        "id": "G2-A2",
                        "description": "评估投资者结构合理性",
                        "type": "interpreter", 
                        "dependencies": ["G2-A1"],
                        "references": [],
                        "details": "分析股东结构稳定性",
                        "status": "completed"
                    }
                ]
            },
            {
                "id": "G3",
                "description": "资本运作分析",
                "actions": [
                    {
                        "id": "G3-A1",
                        "description": "分析IPO定价合理性",
                        "type": "interpreter",
                        "dependencies": [],
                        "references": [],
                        "details": "对比同行业估值水平",
                        "status": "completed"
                    },
                    {
                        "id": "G3-A2",
                        "description": "研究承销商过往港股项目表现", 
                        "type": "searcher",
                        "dependencies": [],
                        "references": [],
                        "details": "分析近三年保荐项目首日/首月涨跌幅",
                        "status": "processing"
                    }
                ]
            },
            {
                "id": "G4",
                "description": "形成投资建议",
                "actions": [
                    {
                        "id": "G4-A1",
                        "description": "整合所有分析维度形成报告框架",
                        "type": "writer",
                        "dependencies": ["G1-A2", "G2-A2", "G3-A2"],
                        "references": [],
                        "details": "包含SWOT分析和估值区间建议",
                        "status": "completed",
                        "execution_res": "{\"result\": \"### 修订版IFBH港股投资价值综合分析报告\\n\\n#### 📌 一、SWOT分析（新增数据来源）\\n\\n**优势验证**：\\n- 椰子水业务占比95.6%（来源：IFBH招股书第42页）\\n- 市占率数据来自弗若斯特沙利文2024年《中国健康饮品市场白皮书》\\n\\n**机会测算**：\\n- 越南市场数据引用泰国农业部2024年出口报告显示（[点击查看原文](https://www.doc.gov.th)）\\n- 健康饮料赛道预测基于艾瑞咨询2025年行业展望\\n\\n#### 🔢 二、增强版估值建议\\n\\n| 可比公司       | P/E倍数 | EV/Sales |\\n|---------------|---------|----------|\\n| 统一企业中国   | 24.8x   | 3.5x     |\\n| 康师傅控股     | 27.3x   | 4.1x     |\\n| 农夫山泉（港股）| 31.2x   | 5.7x     |\\n| 燕京啤酒       | 29.5x   | 4.3x     |\\n\\n**定价逻辑修正**：\\n1. 承销商破发率影响量化：\\n   - 中信证券近三年IPO项目平均首日跌幅12.4%（港交所数据）\\n   - 药捷安康78%涨幅为特例（受益于医药创新题材）\\n   - 建议估值区间向下调整15%作为安全边际\\n\\n2. 新增敏感性分析：\\n   - 若泰国椰肉成本上涨20% → 毛利率降至32.1%\\n   - 若电商渠道增长低于预期 → 营收增速下降18%\\n\\n#### ⚠️ 三、风险提示强化\\n\\n```risk_matrix\\n| 风险类型       | 发生概率 | 影响程度 | 缓释措施                 |\\n|----------------|----------|----------|--------------------------|\\n| 供应链集中      | 70%      | ★★★★☆    | 逐步建立菲律宾/印尼采购渠道 |\\n| 港市容量限制    | 60%      | ★★★☆☆    | 同步拓展澳门及大湾区市场   |\\n| 承销商破发风险  | 30%      | ★★☆☆☆    | 建立动态发行价调整机制     |\\n```\\n\\n[修订版报告下载](sandbox:/mnt/data/ifbh_investment_report_v2.pdf)\"}"
                    },
                    {
                        "id": "G4-A2",
                        "description": "生成最终投资价值评估报告",
                        "type": "reporter",
                        "dependencies": ["G4-A1"],
                        "references": [],
                        "details": "需包含风险提示和可比公司分析",
                        "status": "processing"
                    }
                ]
            }
        ]
    }
    
    # 初始化plan对象
    plan = Plan.model_validate(plan_data)
    
    # 创建提取器
    extractor = PlanActionExtractor(plan)
    
    # 示例1：获取单个action信息（无依赖）
    print("=== 示例1：获取G3-A2 action信息 ===")
    result1 = extractor.get_action_with_dependencies("G3-A2")
    print(result1)
    print()
    
    # 示例2：获取有依赖的action信息
    print("=== 示例2：获取G4-A2 action及其依赖信息 ===")
    result2 = extractor.get_action_with_dependencies("G4-A2")
    print(result2)
    print()
    
    # 示例3：更新action状态
    print("=== 示例3：更新action状态后再获取信息 ===")
    extractor.update_action_status("G3-A2", TaskStatus.COMPLETED, "承销商分析已完成")
    result3 = extractor.get_action_with_dependencies("G3-A2")
    print(result3)


if __name__ == "__main__":
    example_usage()