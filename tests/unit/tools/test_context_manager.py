# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock
from src.tools.context_manager import ContextManager


class TestContextManager:
    """ContextManager类的单元测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.context_manager = ContextManager()
    
    def test_initialization(self):
        """测试ContextManager初始化"""
        assert self.context_manager is not None
        assert hasattr(self.context_manager, 'generate_step_summary')
        assert hasattr(self.context_manager, 'control_context_length')
    
    def test_generate_step_summary_basic(self):
        """测试基本的步骤摘要生成"""
        step_result = """
        这是一个详细的研究结果，包含了大量的信息。
        研究发现人工智能在医疗领域的应用越来越广泛。
        主要应用包括医学影像诊断、药物研发、个性化治疗等。
        未来AI在医疗领域还有更大的发展空间。
        """
        
        summary = self.context_manager.generate_step_summary(step_result)
        
        # 验证摘要比原文短
        assert len(summary) < len(step_result)
        assert summary is not None
        assert len(summary.strip()) > 0
    
    def test_generate_step_summary_empty_input(self):
        """测试空输入的摘要生成"""
        summary = self.context_manager.generate_step_summary("")
        assert summary == ""
    
    def test_generate_step_summary_short_input(self):
        """测试短输入的摘要生成"""
        short_text = "这是一个短文本"
        summary = self.context_manager.generate_step_summary(short_text)
        # 短文本应该直接返回或稍作处理
        assert len(summary) <= len(short_text) + 10  # 允许少量增加
    
    def test_control_context_length_within_limit(self):
        """测试在限制范围内的上下文长度控制"""
        context = "这是一个适中长度的上下文内容"
        max_length = 1000
        
        controlled = self.context_manager.control_context_length(context, max_length)
        
        assert len(controlled) <= max_length
        assert controlled == context  # 在限制内应该不变
    
    def test_control_context_length_exceeds_limit(self):
        """测试超出限制的上下文长度控制"""
        long_context = "这是一个很长的上下文内容。" * 100
        max_length = 50
        
        controlled = self.context_manager.control_context_length(long_context, max_length)
        
        assert len(controlled) <= max_length
        assert len(controlled) > 0
    
    def test_control_context_length_zero_limit(self):
        """测试零长度限制"""
        context = "任何内容"
        controlled = self.context_manager.control_context_length(context, 0)
        assert controlled == ""
    
    def test_track_research_progress(self):
        """测试研究进度跟踪"""
        steps = [
            {"title": "步骤1", "status": "completed"},
            {"title": "步骤2", "status": "in_progress"},
            {"title": "步骤3", "status": "pending"}
        ]
        
        progress = self.context_manager.track_research_progress(steps)
        
        assert "completed" in progress
        assert "total" in progress
        assert progress["completed"] == 1
        assert progress["total"] == 3
    
    @patch('src.tools.context_manager.get_llm_by_type')
    def test_generate_step_summary_with_llm_error(self, mock_llm):
        """测试LLM调用失败时的处理"""
        mock_llm.side_effect = Exception("LLM调用失败")
        
        step_result = "测试内容"
        summary = self.context_manager.generate_step_summary(step_result)
        
        # 应该有fallback机制
        assert summary is not None
        assert len(summary) > 0
    
    def test_reset_context(self):
        """测试上下文重置功能"""
        # 假设有一些上下文状态
        self.context_manager._current_context = "一些上下文内容"
        
        self.context_manager.reset_context()
        
        # 验证上下文已被重置
        assert getattr(self.context_manager, '_current_context', None) is None or \
               self.context_manager._current_context == ""
    
    def test_get_context_stats(self):
        """测试获取上下文统计信息"""
        context = "这是一个测试上下文，包含一些内容用于统计。"
        
        stats = self.context_manager.get_context_stats(context)
        
        assert "length" in stats
        assert "word_count" in stats
        assert stats["length"] == len(context)
        assert stats["word_count"] > 0


class TestContextManagerIntegration:
    """ContextManager集成测试"""
    
    def test_full_workflow_simulation(self):
        """测试完整工作流程模拟"""
        manager = ContextManager()
        
        # 模拟多步骤研究过程
        step1_result = "第一步研究结果：发现了重要信息A"
        step2_result = "第二步研究结果：基于信息A，进一步发现了信息B"
        step3_result = "第三步研究结果：综合信息A和B，得出最终结论C"
        
        # 生成各步骤摘要
        summary1 = manager.generate_step_summary(step1_result)
        summary2 = manager.generate_step_summary(step2_result)
        summary3 = manager.generate_step_summary(step3_result)
        
        # 验证摘要质量
        assert all(len(s) > 0 for s in [summary1, summary2, summary3])
        assert all(len(s) < len(r) for s, r in zip([summary1, summary2, summary3], 
                                                   [step1_result, step2_result, step3_result]))
        
        # 组合所有摘要
        combined_context = f"{summary1}\n{summary2}\n{summary3}"
        
        # 控制最终上下文长度
        final_context = manager.control_context_length(combined_context, max_length=200)
        
        assert len(final_context) <= 200
        assert len(final_context) > 0


if __name__ == "__main__":
    pytest.main([__file__])