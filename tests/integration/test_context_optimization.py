# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
上下文优化集成测试
测试ContextManager与其他组件的集成功能
"""

import pytest
from unittest.mock import patch, MagicMock
from src.tools.context_manager import ContextManager
from src.prompts.planner_model import Step


class TestContextOptimizationIntegration:
    """上下文优化集成测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.context_manager = ContextManager()
    
    def test_multi_step_research_workflow(self):
        """测试多步骤研究工作流程"""
        # 模拟研究步骤
        steps = [
            Step(title="数据收集", description="收集相关数据"),
            Step(title="数据分析", description="分析收集的数据"),
            Step(title="结论总结", description="总结研究结论")
        ]
        
        # 模拟执行结果
        results = [
            "收集到大量相关数据，包括统计数据、报告等...",
            "通过分析发现了重要趋势和模式...",
            "基于分析结果得出了重要结论..."
        ]
        
        # 测试步骤摘要生成
        for step, result in zip(steps, results):
            summary = self.context_manager.create_step_summary(step, result)
            assert summary is not None
            assert "step_title" in summary
            assert "summary" in summary
            assert "token_count" in summary
    
    def test_context_length_control_integration(self):
        """测试上下文长度控制集成"""
        # 创建大量步骤摘要
        for i in range(10):
            step = Step(title=f"步骤{i}", description=f"描述{i}")
            result = f"这是第{i}步的详细执行结果，包含大量信息..." * 100
            self.context_manager.add_step_summary(step, result)
        
        # 获取整合后的上下文
        consolidated = self.context_manager.get_consolidated_context()
        
        # 验证上下文长度控制
        assert len(consolidated) > 0
        assert self.context_manager.estimate_token_count(consolidated) <= self.context_manager.max_context_length
    
    @patch('src.tools.context_manager.get_llm_by_type')
    def test_llm_integration(self, mock_llm):
        """测试与LLM的集成"""
        # Mock LLM响应
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value.content = "这是一个测试摘要"
        mock_llm.return_value = mock_llm_instance
        
        step = Step(title="测试步骤", description="测试描述")
        result = "详细的执行结果"
        
        summary = self.context_manager.create_step_summary(step, result)
        
        # 验证LLM被正确调用
        mock_llm.assert_called_once()
        assert summary["summary"] == "这是一个测试摘要"
    
    def test_research_progress_tracking(self):
        """测试研究进度跟踪"""
        # 创建模拟研究计划
        class MockPlan:
            def __init__(self, steps):
                self.steps = steps
        
        steps = [
            Step(title="步骤1", description="描述1"),
            Step(title="步骤2", description="描述2"),
            Step(title="步骤3", description="描述3")
        ]
        
        # 模拟部分步骤完成
        steps[0].execution_res = "完成结果1"
        steps[1].execution_res = "完成结果2"
        
        plan = MockPlan(steps)
        progress = self.context_manager.get_research_progress(plan)
        
        assert progress["completed"] == 2
        assert progress["total"] == 3
        assert progress["percentage"] == 66.7
    
    def test_context_reset_functionality(self):
        """测试上下文重置功能"""
        # 添加一些摘要
        step = Step(title="测试步骤", description="测试描述")
        self.context_manager.add_step_summary(step, "测试结果")
        
        assert len(self.context_manager.step_summaries) > 0
        
        # 重置上下文
        self.context_manager.clear_summaries()
        
        assert len(self.context_manager.step_summaries) == 0
        assert self.context_manager.get_consolidated_context() == ""