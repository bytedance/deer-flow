# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
质量控制集成测试
测试权威数据源、数据验证和质量评分的集成功能
"""

import pytest
from unittest.mock import patch, MagicMock
from src.tools.authority_search import AuthoritySourceManager, authority_search_tool
from src.tools.data_validator import DataValidator
from src.tools.quality_scoring import QualityScorer


class TestQualityControlIntegration:
    """质量控制系统集成测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.authority_manager = AuthoritySourceManager()
        self.data_validator = DataValidator()
        self.quality_scorer = QualityScorer()
    
    @patch('src.tools.authority_search.get_web_search_tool')
    def test_end_to_end_quality_control(self, mock_search_tool):
        """测试端到端质量控制流程"""
        # Mock搜索结果
        mock_search_results = [
            {
                "url": "https://stats.gov.cn/data/report",
                "title": "国家统计局数据报告",
                "content": "详细的统计数据和分析报告...",
                "snippet": "权威统计数据"
            },
            {
                "url": "https://example.com/news",
                "title": "普通新闻网站",
                "content": "一般性新闻内容...",
                "snippet": "新闻报道"
            }
        ]
        
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = mock_search_results
        mock_search_tool.return_value = mock_tool
        
        # 执行权威搜索
        results = authority_search_tool.invoke({"query": "经济数据", "domain_type": "government"})
        
        # 验证权威源过滤
        assert len(results) > 0
        authority_result = results[0]
        assert "authority_score" in authority_result
        assert authority_result["authority_score"] > 0
        
        # 验证数据质量评估
        validation_result = self.data_validator.validate_search_result(authority_result)
        assert validation_result["overall_score"] > 0
        assert "credibility" in validation_result
        assert "content_quality" in validation_result
    
    def test_authority_source_prioritization(self):
        """测试权威源优先级排序"""
        search_results = [
            {"url": "https://example.com/article", "title": "普通文章"},
            {"url": "https://www.gov.cn/policy", "title": "政府政策"},
            {"url": "https://www.tsinghua.edu.cn/research", "title": "清华研究"},
            {"url": "https://www.who.int/report", "title": "WHO报告"}
        ]
        
        # 过滤和排序权威源
        authority_results = self.authority_manager.filter_authority_results(search_results)
        
        # 验证排序正确性
        assert len(authority_results) >= 3  # 至少有3个权威源
        
        # 政府源应该排在前面
        gov_found = False
        for result in authority_results[:2]:  # 检查前两个
            if ".gov" in result["url"]:
                gov_found = True
                break
        assert gov_found
    
    def test_quality_scoring_integration(self):
        """测试质量评分集成"""
        # 高质量数据源
        high_quality_data = {
            "url": "https://stats.gov.cn/report",
            "title": "国家统计局年度报告",
            "content": "详细的统计分析，包含大量数据表格和专业分析...",
            "source_type": "government",
            "publish_date": "2024-01-15"
        }
        
        # 低质量数据源
        low_quality_data = {
            "url": "https://unknown-blog.com/post",
            "title": "个人博客文章",
            "content": "简短的个人观点...",
            "source_type": "blog",
            "publish_date": "2023-01-01"
        }
        
        # 评分对比
        high_score = self.quality_scorer.calculate_comprehensive_score(high_quality_data)
        low_score = self.quality_scorer.calculate_comprehensive_score(low_quality_data)
        
        assert high_score > low_score
        assert high_score >= 7.0  # 高质量应该得到高分
        assert low_score <= 5.0   # 低质量应该得到低分
    
    def test_credibility_assessment_workflow(self):
        """测试可信度评估工作流程"""
        test_urls = [
            "https://www.gov.cn/article",
            "https://www.who.int/report",
            "https://www.tsinghua.edu.cn/research",
            "https://random-blog.com/post"
        ]
        
        credibility_results = []
        for url in test_urls:
            credibility_info = self.authority_manager.get_source_credibility_info(url)
            credibility_results.append(credibility_info)
        
        # 验证可信度评估结果
        assert len(credibility_results) == 4
        
        # 政府网站应该有最高可信度
        gov_result = credibility_results[0]
        assert gov_result["score"] >= 8
        assert gov_result["credibility"] in ["极高", "高"]
        
        # 随机博客应该有最低可信度
        blog_result = credibility_results[3]
        assert blog_result["score"] <= 4
    
    def test_data_validation_comprehensive(self):
        """测试综合数据验证"""
        # 准备测试数据
        test_data = {
            "url": "https://stats.gov.cn/data",
            "title": "2024年经济统计数据",
            "content": "根据国家统计局最新数据显示，2024年第一季度GDP增长率为5.3%，" +
                      "工业增加值同比增长6.1%，消费价格指数上涨0.1%。" +
                      "数据来源可靠，统计方法科学，具有重要参考价值。",
            "snippet": "权威经济数据统计",
            "publish_date": "2024-07-15"
        }
        
        # 执行综合验证
        validation_result = self.data_validator.validate_search_result(test_data)
        
        # 验证各项指标
        assert validation_result["overall_score"] >= 7.0
        assert validation_result["credibility"]["score"] >= 8
        assert validation_result["content_quality"]["score"] >= 6
        assert validation_result["timeliness"]["score"] >= 7
        assert validation_result["completeness"]["score"] >= 6
        
        # 验证质量等级
        assert validation_result["quality_level"] in ["优秀", "良好"]
    
    def test_search_enhancement_with_authority_domains(self):
        """测试权威域名搜索增强"""
        original_query = "经济增长数据"
        
        # 测试政府域名增强
        enhanced_gov = self.authority_manager.enhance_search_query(original_query, "government")
        assert "site:" in enhanced_gov
        assert ".gov" in enhanced_gov
        
        # 测试学术域名增强
        enhanced_academic = self.authority_manager.enhance_search_query(original_query, "academic")
        assert "site:" in enhanced_academic
        assert ".edu" in enhanced_academic
        
        # 测试无特定域名类型
        enhanced_general = self.authority_manager.enhance_search_query(original_query)
        assert "site:" in enhanced_general