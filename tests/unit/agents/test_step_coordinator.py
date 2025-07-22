"""
步骤协调器单元测试
测试步骤依赖分析、拓扑排序和执行协调功能
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.step_coordinator import (
    StepCoordinator, StepDependency, StepStatus, 
    ExecutionPlan, get_step_coordinator
)
from src.prompts.planner_model import Step, StepType


class TestStepCoordinator:
    """StepCoordinator类的单元测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.coordinator = StepCoordinator()
    
    def test_init(self):
        """测试StepCoordinator初始化"""
        assert self.coordinator is not None
        assert hasattr(self.coordinator, 'analyze_dependencies')
        assert hasattr(self.coordinator, 'create_execution_plan')
        assert hasattr(self.coordinator, 'execute_step')
    
    def test_analyze_dependencies_simple(self):
        """测试简单依赖关系分析"""
        steps = [
            Step(
                step_id="step1",
                description="收集基础数据",
                step_type=StepType.RESEARCH,
                expected_output="基础数据集"
            ),
            Step(
                step_id="step2", 
                description="基于step1的数据进行分析",
                step_type=StepType.PROCESSING,
                expected_output="分析结果"
            )
        ]
        
        dependencies = self.coordinator.analyze_dependencies(steps)
        
        assert len(dependencies) >= 0
        assert isinstance(dependencies, list)
        if dependencies:
            assert all(isinstance(dep, StepDependency) for dep in dependencies)
    
    def test_analyze_dependencies_complex(self):
        """测试复杂依赖关系分析"""
        steps = [
            Step(
                step_id="data_collection",
                description="收集原始数据",
                step_type=StepType.RESEARCH,
                expected_output="原始数据"
            ),
            Step(
                step_id="data_cleaning",
                description="清理和预处理数据",
                step_type=StepType.PROCESSING,
                expected_output="清洁数据"
            ),
            Step(
                step_id="analysis",
                description="分析处理后的数据",
                step_type=StepType.PROCESSING,
                expected_output="分析结果"
            ),
            Step(
                step_id="report",
                description="生成最终报告",
                step_type=StepType.RESEARCH,
                expected_output="研究报告"
            )
        ]
        
        dependencies = self.coordinator.analyze_dependencies(steps)
        
        assert isinstance(dependencies, list)
        # 验证依赖关系的逻辑性
        step_ids = {step.step_id for step in steps}
        for dep in dependencies:
            assert dep.step_id in step_ids
            assert dep.dependency_id in step_ids
    
    def test_create_execution_plan(self):
        """测试执行计划创建"""
        steps = [
            Step(
                step_id="step1",
                description="第一步",
                step_type=StepType.RESEARCH,
                expected_output="结果1"
            ),
            Step(
                step_id="step2",
                description="第二步",
                step_type=StepType.PROCESSING,
                expected_output="结果2"
            )
        ]
        
        plan = self.coordinator.create_execution_plan(steps)
        
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.execution_order) == len(steps)
        assert plan.total_steps == len(steps)
        assert all(step_id in [s.step_id for s in steps] for step_id in plan.execution_order)
    
    def test_topological_sort_simple(self):
        """测试简单拓扑排序"""
        steps = [
            Step(step_id="A", description="步骤A", step_type=StepType.RESEARCH, expected_output="A结果"),
            Step(step_id="B", description="步骤B", step_type=StepType.PROCESSING, expected_output="B结果")
        ]
        
        dependencies = [
            StepDependency("B", "A", "prerequisite", "B依赖A")
        ]
        
        sorted_steps = self.coordinator._topological_sort(steps, dependencies)
        
        assert len(sorted_steps) == 2
        assert sorted_steps[0] == "A"  # A应该在B之前
        assert sorted_steps[1] == "B"
    
    def test_topological_sort_complex(self):
        """测试复杂拓扑排序"""
        steps = [
            Step(step_id="A", description="步骤A", step_type=StepType.RESEARCH, expected_output="A结果"),
            Step(step_id="B", description="步骤B", step_type=StepType.RESEARCH, expected_output="B结果"),
            Step(step_id="C", description="步骤C", step_type=StepType.PROCESSING, expected_output="C结果"),
            Step(step_id="D", description="步骤D", step_type=StepType.PROCESSING, expected_output="D结果")
        ]
        
        dependencies = [
            StepDependency("C", "A", "prerequisite", "C依赖A"),
            StepDependency("C", "B", "prerequisite", "C依赖B"),
            StepDependency("D", "C", "prerequisite", "D依赖C")
        ]
        
        sorted_steps = self.coordinator._topological_sort(steps, dependencies)
        
        assert len(sorted_steps) == 4
        # A和B应该在C之前
        a_index = sorted_steps.index("A")
        b_index = sorted_steps.index("B")
        c_index = sorted_steps.index("C")
        d_index = sorted_steps.index("D")
        
        assert a_index < c_index
        assert b_index < c_index
        assert c_index < d_index
    
    def test_execute_step_success(self):
        """测试步骤执行成功"""
        step = Step(
            step_id="test_step",
            description="测试步骤",
            step_type=StepType.RESEARCH,
            expected_output="测试结果"
        )
        
        with patch.object(self.coordinator, '_execute_step_logic') as mock_execute:
            mock_execute.return_value = {"success": True, "result": "执行成功"}
            
            result = self.coordinator.execute_step(step)
            
            assert result["success"] is True
            assert "result" in result
            mock_execute.assert_called_once_with(step)
    
    def test_execute_step_failure(self):
        """测试步骤执行失败"""
        step = Step(
            step_id="test_step",
            description="测试步骤",
            step_type=StepType.RESEARCH,
            expected_output="测试结果"
        )
        
        with patch.object(self.coordinator, '_execute_step_logic') as mock_execute:
            mock_execute.side_effect = Exception("执行失败")
            
            result = self.coordinator.execute_step(step)
            
            assert result["success"] is False
            assert "error" in result
    
    def test_get_step_status(self):
        """测试获取步骤状态"""
        step_id = "test_step"
        
        # 初始状态应该是PENDING
        status = self.coordinator.get_step_status(step_id)
        assert status == StepStatus.PENDING
        
        # 更新状态
        self.coordinator._update_step_status(step_id, StepStatus.RUNNING)
        status = self.coordinator.get_step_status(step_id)
        assert status == StepStatus.RUNNING
    
    def test_get_execution_progress(self):
        """测试获取执行进度"""
        steps = [
            Step(step_id="step1", description="步骤1", step_type=StepType.RESEARCH, expected_output="结果1"),
            Step(step_id="step2", description="步骤2", step_type=StepType.PROCESSING, expected_output="结果2")
        ]
        
        plan = self.coordinator.create_execution_plan(steps)
        
        # 初始进度
        progress = self.coordinator.get_execution_progress(plan.plan_id)
        assert progress["total_steps"] == 2
        assert progress["completed_steps"] == 0
        assert progress["progress_percentage"] == 0.0
        
        # 模拟完成一个步骤
        self.coordinator._update_step_status("step1", StepStatus.COMPLETED)
        progress = self.coordinator.get_execution_progress(plan.plan_id)
        assert progress["completed_steps"] == 1
        assert progress["progress_percentage"] == 50.0
    
    def test_parallel_execution_limit(self):
        """测试并行执行限制"""
        steps = [
            Step(step_id=f"step{i}", description=f"步骤{i}", 
                 step_type=StepType.RESEARCH, expected_output=f"结果{i}")
            for i in range(5)
        ]
        
        plan = self.coordinator.create_execution_plan(steps, max_parallel=2)
        
        assert plan.max_parallel_steps == 2
        
        # 验证并行执行逻辑
        with patch.object(self.coordinator, 'execute_step') as mock_execute:
            mock_execute.return_value = {"success": True, "result": "成功"}
            
            self.coordinator.execute_plan(plan)
            
            # 验证execute_step被调用了正确的次数
            assert mock_execute.call_count == len(steps)


class TestStepDependency:
    """StepDependency数据模型测试"""
    
    def test_step_dependency_creation(self):
        """测试StepDependency对象创建"""
        dependency = StepDependency(
            step_id="step2",
            dependency_id="step1",
            dependency_type="prerequisite",
            description="step2依赖step1"
        )
        
        assert dependency.step_id == "step2"
        assert dependency.dependency_id == "step1"
        assert dependency.dependency_type == "prerequisite"
        assert dependency.description == "step2依赖step1"
    
    def test_dependency_types(self):
        """测试不同依赖类型"""
        types = ["prerequisite", "parallel", "optional"]
        
        for dep_type in types:
            dependency = StepDependency(
                step_id="step2",
                dependency_id="step1", 
                dependency_type=dep_type,
                description=f"测试{dep_type}依赖"
            )
            assert dependency.dependency_type == dep_type


class TestExecutionPlan:
    """ExecutionPlan数据模型测试"""
    
    def test_execution_plan_creation(self):
        """测试ExecutionPlan对象创建"""
        plan = ExecutionPlan(
            plan_id="test_plan",
            execution_order=["step1", "step2", "step3"],
            dependencies=[],
            total_steps=3,
            max_parallel_steps=2
        )
        
        assert plan.plan_id == "test_plan"
        assert plan.execution_order == ["step1", "step2", "step3"]
        assert plan.total_steps == 3
        assert plan.max_parallel_steps == 2


class TestStepCoordinatorIntegration:
    """步骤协调器集成测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.coordinator = StepCoordinator()
    
    def test_end_to_end_coordination(self):
        """测试端到端步骤协调"""
        steps = [
            Step(
                step_id="data_collection",
                description="收集研究数据",
                step_type=StepType.RESEARCH,
                expected_output="原始数据集"
            ),
            Step(
                step_id="data_analysis",
                description="分析收集的数据",
                step_type=StepType.PROCESSING,
                expected_output="分析结果"
            ),
            Step(
                step_id="report_generation",
                description="生成研究报告",
                step_type=StepType.RESEARCH,
                expected_output="最终报告"
            )
        ]
        
        # 分析依赖关系
        dependencies = self.coordinator.analyze_dependencies(steps)
        assert isinstance(dependencies, list)
        
        # 创建执行计划
        plan = self.coordinator.create_execution_plan(steps)
        assert isinstance(plan, ExecutionPlan)
        assert plan.total_steps == 3
        
        # 验证执行顺序的合理性
        assert len(plan.execution_order) == 3
        assert all(step_id in [s.step_id for s in steps] for step_id in plan.execution_order)
    
    @patch('src.agents.step_coordinator.get_context_manager')
    def test_context_manager_integration(self, mock_get_context):
        """测试与上下文管理器的集成"""
        mock_context_manager = Mock()
        mock_get_context.return_value = mock_context_manager
        
        step = Step(
            step_id="test_step",
            description="测试步骤",
            step_type=StepType.RESEARCH,
            expected_output="测试结果"
        )
        
        # 执行步骤时应该与上下文管理器交互
        with patch.object(self.coordinator, '_execute_step_logic') as mock_execute:
            mock_execute.return_value = {"success": True, "result": "成功"}
            
            result = self.coordinator.execute_step(step)
            
            assert result["success"] is True
            # 验证上下文管理器被正确调用
            mock_get_context.assert_called()


def test_get_step_coordinator():
    """测试获取步骤协调器实例"""
    coordinator = get_step_coordinator()
    assert isinstance(coordinator, StepCoordinator)
    
    # 验证单例模式
    coordinator2 = get_step_coordinator()
    assert coordinator is coordinator2