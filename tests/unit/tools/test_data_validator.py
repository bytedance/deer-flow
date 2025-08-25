# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock
from src.tools.data_validator import DataValidator, validate_search_results


class TestDataValidator:
    """DataValidator类的单元测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.validator = DataValidator()
    
    def test_initialization(self):
        """测试DataValidator初始化"""
        assert self.validator is not None
        assert hasattr(self.validator, 'validate_credibility')
        assert hasattr(self.validator, 'validate_content_quality')
        assert hasattr(self.validator, 'validate_timeliness')
        assert hasattr(self.validator, 'validate_completeness')
    
    def test_validate_credibility_government_source(self):
        """测试政府源可信度验证"""
        result = {
            "url": "https://www.gov.cn/policy",
            "title": "政府政策文件",
            "content": "这是官方发布的政策文件内容"
        }
        
        credibility_score = self.validator.validate_credibility(result)
        assert credibility_score >= 9.0  # 政府源应该有很高的可信度
    
    def test_validate_credibility_academic_source(self):
        """测试学术源可信度验证"""
        result = {
            "url": "https://www.tsinghua.edu.cn/research",
            "title": "学术研究报告",
            "content": "这是清华大学发布的研究报告"
        }
        
        credibility_score = self.validator.validate_credibility(result)
        assert credibility_score >= 8.0  # 学术源应该有较高的可信度
    
    def test_validate_credibility_unknown_source(self):
        """测试未知源可信度验证"""
        result = {
            "url": "https://www.unknown-blog.com/post",
            "title": "个人博客文章",
            "content": "这是个人博客的内容"
        }
        
        credibility_score = self.validator.validate_credibility(result)
        assert credibility_score <= 6.0  # 未知源可信度较低
    
    def test_validate_content_quality_high_quality(self):
        """测试高质量内容验证"""
        result = {
            "title": "人工智能在医疗领域的应用研究",
            "content": """
            本研究通过大规模数据分析，深入探讨了人工智能技术在医疗诊断、
            治疗方案制定、药物研发等领域的具体应用。研究采用了严格的
            实验设计，收集了来自50家医院的10万份病例数据，运用深度学习
            算法进行分析。结果显示，AI辅助诊断的准确率达到95%以上，
            显著提高了医疗服务质量。研究还发现了AI在个性化治疗方面的
            巨大潜力，为未来医疗发展提供了重要参考。
            """
        }
        
        quality_score = self.validator.validate_content_quality(result)
        assert quality_score >= 8.0  # 高质量内容应该得高分
    
    def test_validate_content_quality_low_quality(self):
        """测试低质量内容验证"""
        result = {
            "title": "AI很好",
            "content": "AI技术很好，很有用。大家都应该用。"
        }
        
        quality_score = self.validator.validate_content_quality(result)
        assert quality_score <= 5.0  # 低质量内容应该得低分
    
    def test_validate_timeliness_recent_content(self):
        """测试最新内容时效性验证"""
        from datetime import datetime, timedelta
        
        recent_date = datetime.now() - timedelta(days=30)
        result = {
            "url": "https://example.com/recent",
            "title": "最新报告",
            "content": "这是最近发布的内容",
            "published_date": recent_date.isoformat()
        }
        
        timeliness_score = self.validator.validate_timeliness(result)
        assert timeliness_score >= 8.0  # 最新内容时效性高
    
    def test_validate_timeliness_old_content(self):
        """测试过时内容时效性验证"""
        from datetime import datetime, timedelta
        
        old_date = datetime.now() - timedelta(days=365*3)  # 3年前
        result = {
            "url": "https://example.com/old",
            "title": "旧报告",
            "content": "这是很久以前的内容",
            "published_date": old_date.isoformat()
        }
        
        timeliness_score = self.validator.validate_timeliness(result)
        assert timeliness_score <= 5.0  # 过时内容时效性低
    
    def test_validate_timeliness_no_date(self):
        """测试无日期内容时效性验证"""
        result = {
            "url": "https://example.com/nodate",
            "title": "无日期报告",
            "content": "这是没有日期信息的内容"
        }
        
        timeliness_score = self.validator.validate_timeliness(result)
        assert 4.0 <= timeliness_score <= 6.0  # 无日期内容给中等分数
    
    def test_validate_completeness_complete_content(self):
        """测试完整内容的完整性验证"""
        result = {
            "title": "完整的研究报告",
            "content": """
            摘要：本研究探讨了...
            
            1. 引言
            人工智能技术的发展...
            
            2. 方法
            本研究采用了以下方法...
            
            3. 结果
            实验结果显示...
            
            4. 讨论
            基于以上结果，我们认为...
            
            5. 结论
            综上所述...
            
            参考文献：
            [1] Smith, J. (2023). AI in Healthcare...
            """,
            "url": "https://example.com/complete"
        }
        
        completeness_score = self.validator.validate_completeness(result)
        assert completeness_score >= 8.0  # 完整内容应该得高分
    
    def test_validate_completeness_incomplete_content(self):
        """测试不完整内容的完整性验证"""
        result = {
            "title": "不完整的文章",
            "content": "这是一个很短的内容片段。",
            "url": "https://example.com/incomplete"
        }
        
        completeness_score = self.validator.validate_completeness(result)
        assert completeness_score <= 5.0  # 不完整内容应该得低分
    
    def test_comprehensive_validation(self):
        """测试综合验证功能"""
        result = {
            "url": "https://www.gov.cn/policy/ai-strategy",
            "title": "国家人工智能发展战略",
            "content": """
            为贯彻落实国家人工智能发展战略，推动AI技术在各行业的应用，
            特制定本政策文件。文件详细阐述了AI发展的指导思想、基本原则、
            主要目标和重点任务。包括加强AI基础研究、推进产业应用、
            完善治理体系、加强人才培养等方面的具体措施。
            """,
            "published_date": "2024-01-15T10:00:00Z"
        }
        
        validation_result = self.validator.comprehensive_validation(result)
        
        # 验证返回结果结构
        assert "credibility" in validation_result
        assert "content_quality" in validation_result
        assert "timeliness" in validation_result
        assert "completeness" in validation_result
        assert "overall_score" in validation_result
        
        # 验证分数范围
        for score in validation_result.values():
            assert 0.0 <= score <= 10.0
        
        # 政府源的高质量内容应该得高分
        assert validation_result["overall_score"] >= 7.0
    
    def test_validation_weights(self):
        """测试验证权重配置"""
        # 测试默认权重
        weights = self.validator.get_validation_weights()
        
        assert weights["credibility"] == 0.4  # 可信度40%
        assert weights["content_quality"] == 0.3  # 内容质量30%
        assert weights["timeliness"] == 0.2  # 时效性20%
        assert weights["completeness"] == 0.1  # 完整性10%
        assert sum(weights.values()) == 1.0  # 总和为100%
    
    def test_set_custom_weights(self):
        """测试设置自定义权重"""
        custom_weights = {
            "credibility": 0.5,
            "content_quality": 0.3,
            "timeliness": 0.1,
            "completeness": 0.1
        }
        
        self.validator.set_validation_weights(custom_weights)
        weights = self.validator.get_validation_weights()
        
        assert weights == custom_weights


class TestValidateSearchResultsTool:
    """validate_search_results工具的单元测试"""
    
    def test_validate_search_results_basic(self):
        """测试基本的搜索结果验证"""
        search_results = [
            {
                "url": "https://www.gov.cn/policy",
                "title": "政府政策文件",
                "content": "详细的政策内容..."
            },
            {
                "url": "https://www.example.com/blog",
                "title": "个人博客",
                "content": "简短的个人观点"
            }
        ]
        
        validated_results = validate_search_results.invoke({"results": search_results})
        
        # 验证返回结果结构
        assert isinstance(validated_results, list)
        assert len(validated_results) == len(search_results)
        
        # 验证每个结果都包含验证信息
        for result in validated_results:
            assert "validation_score" in result
            assert "validation_details" in result
            assert 0.0 <= result["validation_score"] <= 10.0
    
    def test_validate_search_results_empty_input(self):
        """测试空输入的搜索结果验证"""
        validated_results = validate_search_results.invoke({"results": []})
        assert validated_results == []
    
    def test_validate_search_results_filtering(self):
        """测试搜索结果验证和过滤"""
        search_results = [
            {
                "url": "https://www.gov.cn/policy",
                "title": "高质量政府文件",
                "content": "详细、权威的政策内容，包含具体的实施方案和数据支撑..."
            },
            {
                "url": "https://www.random-blog.com/post",
                "title": "低质量博客",
                "content": "很短的内容"
            }
        ]
        
        validated_results = validate_search_results.invoke({
            "results": search_results,
            "min_score": 6.0
        })
        
        # 应该过滤掉低质量结果
        assert len(validated_results) < len(search_results)
        assert all(result["validation_score"] >= 6.0 for result in validated_results)


class TestDataValidatorIntegration:
    """DataValidator集成测试"""
    
    def test_full_validation_workflow(self):
        """测试完整的数据验证工作流程"""
        validator = DataValidator()
        
        # 模拟不同质量的搜索结果
        test_results = [
            {
                "url": "https://www.stats.gov.cn/data/annual-report",
                "title": "国家统计局年度报告",
                "content": """
                根据国家统计局最新数据，2024年我国GDP增长率达到5.2%，
                其中第三产业贡献最大。报告详细分析了各行业发展情况，
                包括制造业、服务业、农业等的具体数据和发展趋势。
                数据显示，新兴产业如人工智能、新能源等保持快速增长。
                """,
                "published_date": "2024-12-01T09:00:00Z"
            },
            {
                "url": "https://www.tsinghua.edu.cn/ai-research",
                "title": "清华大学AI研究报告",
                "content": """
                本研究基于大规模实验数据，分析了深度学习在图像识别
                领域的最新进展。研究团队收集了100万张图像样本，
                训练了多个神经网络模型，实验结果表明新算法的准确率
                比传统方法提高了15%。
                """,
                "published_date": "2024-11-15T14:30:00Z"
            },
            {
                "url": "https://www.personal-blog.com/my-opinion",
                "title": "我对AI的看法",
                "content": "我觉得AI很厉害，未来会很有用。",
                "published_date": "2024-10-01T12:00:00Z"
            }
        ]
        
        # 对所有结果进行验证
        validation_results = []
        for result in test_results:
            validation = validator.comprehensive_validation(result)
            validation_results.append({
                **result,
                "validation_score": validation["overall_score"],
                "validation_details": validation
            })
        
        # 验证结果质量排序
        sorted_results = sorted(validation_results, 
                              key=lambda x: x["validation_score"], 
                              reverse=True)
        
        # 政府统计数据应该排第一
        assert "stats.gov.cn" in sorted_results[0]["url"]
        assert sorted_results[0]["validation_score"] >= 8.0
        
        # 学术研究应该排第二
        assert "tsinghua.edu.cn" in sorted_results[1]["url"]
        assert sorted_results[1]["validation_score"] >= 7.0
        
        # 个人博客应该排最后
        assert "personal-blog.com" in sorted_results[2]["url"]
        assert sorted_results[2]["validation_score"] <= 6.0
        
        # 过滤高质量结果
        high_quality_results = [r for r in validation_results 
                               if r["validation_score"] >= 7.0]
        
        assert len(high_quality_results) == 2  # 只有政府和学术源通过


if __name__ == "__main__":
    pytest.main([__file__])