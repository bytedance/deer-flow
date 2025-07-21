"""
质量评分系统单元测试
测试内容质量评分、可信度评估和综合质量分析功能
"""

import pytest
from unittest.mock import Mock, patch
from src.tools.quality_scoring import QualityScorer, ContentQuality, SourceCredibility


class TestQualityScorer:
    """QualityScorer类的单元测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.scorer = QualityScorer()
    
    def test_init(self):
        """测试QualityScorer初始化"""
        assert self.scorer is not None
        assert hasattr(self.scorer, 'score_content_quality')
        assert hasattr(self.scorer, 'evaluate_source_credibility')
    
    def test_score_content_quality_high_quality(self):
        """测试高质量内容评分"""
        content = {
            'title': 'Comprehensive Research on Climate Change',
            'content': 'This is a detailed scientific analysis with multiple references and data points. The content includes statistical evidence, peer-reviewed citations, and comprehensive methodology.',
            'url': 'https://nature.com/articles/climate-research',
            'domain': 'nature.com'
        }
        
        quality = self.scorer.score_content_quality(content)
        
        assert isinstance(quality, ContentQuality)
        assert quality.overall_score >= 0.7
        assert quality.depth_score > 0.5
        assert quality.accuracy_indicators > 0.5
    
    def test_score_content_quality_low_quality(self):
        """测试低质量内容评分"""
        content = {
            'title': 'Quick tips',
            'content': 'Some basic info here.',
            'url': 'https://random-blog.com/post',
            'domain': 'random-blog.com'
        }
        
        quality = self.scorer.score_content_quality(content)
        
        assert isinstance(quality, ContentQuality)
        assert quality.overall_score < 0.5
        assert quality.depth_score < 0.5
    
    def test_evaluate_source_credibility_academic(self):
        """测试学术源可信度评估"""
        source_info = {
            'domain': 'arxiv.org',
            'url': 'https://arxiv.org/abs/2023.12345',
            'title': 'Machine Learning Research Paper',
            'author': 'Dr. John Smith, MIT'
        }
        
        credibility = self.scorer.evaluate_source_credibility(source_info)
        
        assert isinstance(credibility, SourceCredibility)
        assert credibility.overall_credibility >= 0.8
        assert credibility.domain_authority > 0.7
        assert credibility.author_expertise > 0.6
    
    def test_evaluate_source_credibility_news(self):
        """测试新闻源可信度评估"""
        source_info = {
            'domain': 'reuters.com',
            'url': 'https://reuters.com/news/article',
            'title': 'Breaking News Report',
            'publication_date': '2024-01-15'
        }
        
        credibility = self.scorer.evaluate_source_credibility(source_info)
        
        assert isinstance(credibility, SourceCredibility)
        assert credibility.overall_credibility >= 0.7
        assert credibility.domain_authority > 0.6
    
    def test_evaluate_source_credibility_unknown(self):
        """测试未知源可信度评估"""
        source_info = {
            'domain': 'unknown-site.xyz',
            'url': 'https://unknown-site.xyz/article',
            'title': 'Random Article'
        }
        
        credibility = self.scorer.evaluate_source_credibility(source_info)
        
        assert isinstance(credibility, SourceCredibility)
        assert credibility.overall_credibility < 0.5
        assert credibility.domain_authority < 0.3
    
    def test_calculate_composite_score(self):
        """测试综合评分计算"""
        content_quality = ContentQuality(
            overall_score=0.8,
            depth_score=0.7,
            accuracy_indicators=0.9,
            completeness=0.8,
            clarity=0.7
        )
        
        source_credibility = SourceCredibility(
            overall_credibility=0.9,
            domain_authority=0.8,
            author_expertise=0.7,
            publication_quality=0.9,
            citation_count=0.6
        )
        
        composite_score = self.scorer.calculate_composite_score(
            content_quality, source_credibility
        )
        
        assert 0 <= composite_score <= 1
        assert composite_score > 0.7  # 高质量内容和高可信度源应该得到高分
    
    def test_get_quality_tier(self):
        """测试质量等级分类"""
        # 高质量
        high_score = 0.85
        tier = self.scorer.get_quality_tier(high_score)
        assert tier == 'premium'
        
        # 中等质量
        medium_score = 0.65
        tier = self.scorer.get_quality_tier(medium_score)
        assert tier == 'standard'
        
        # 低质量
        low_score = 0.35
        tier = self.scorer.get_quality_tier(low_score)
        assert tier == 'basic'
    
    def test_batch_score_contents(self):
        """测试批量内容评分"""
        contents = [
            {
                'title': 'High Quality Research',
                'content': 'Detailed scientific analysis with references.',
                'url': 'https://nature.com/article1',
                'domain': 'nature.com'
            },
            {
                'title': 'Basic Info',
                'content': 'Simple content.',
                'url': 'https://blog.com/post',
                'domain': 'blog.com'
            }
        ]
        
        scores = self.scorer.batch_score_contents(contents)
        
        assert len(scores) == 2
        assert all(isinstance(score, dict) for score in scores)
        assert all('content_quality' in score for score in scores)
        assert all('source_credibility' in score for score in scores)
        assert all('composite_score' in score for score in scores)


class TestContentQuality:
    """ContentQuality数据模型测试"""
    
    def test_content_quality_creation(self):
        """测试ContentQuality对象创建"""
        quality = ContentQuality(
            overall_score=0.8,
            depth_score=0.7,
            accuracy_indicators=0.9,
            completeness=0.8,
            clarity=0.7
        )
        
        assert quality.overall_score == 0.8
        assert quality.depth_score == 0.7
        assert quality.accuracy_indicators == 0.9
        assert quality.completeness == 0.8
        assert quality.clarity == 0.7
    
    def test_content_quality_validation(self):
        """测试ContentQuality数据验证"""
        # 测试分数范围验证
        with pytest.raises(ValueError):
            ContentQuality(overall_score=1.5)  # 超出范围
        
        with pytest.raises(ValueError):
            ContentQuality(overall_score=-0.1)  # 低于范围


class TestSourceCredibility:
    """SourceCredibility数据模型测试"""
    
    def test_source_credibility_creation(self):
        """测试SourceCredibility对象创建"""
        credibility = SourceCredibility(
            overall_credibility=0.9,
            domain_authority=0.8,
            author_expertise=0.7,
            publication_quality=0.9,
            citation_count=0.6
        )
        
        assert credibility.overall_credibility == 0.9
        assert credibility.domain_authority == 0.8
        assert credibility.author_expertise == 0.7
        assert credibility.publication_quality == 0.9
        assert credibility.citation_count == 0.6
    
    def test_source_credibility_validation(self):
        """测试SourceCredibility数据验证"""
        # 测试分数范围验证
        with pytest.raises(ValueError):
            SourceCredibility(overall_credibility=1.2)  # 超出范围
        
        with pytest.raises(ValueError):
            SourceCredibility(domain_authority=-0.5)  # 低于范围


class TestQualityScoringIntegration:
    """质量评分系统集成测试"""
    
    def setup_method(self):
        """测试前的设置"""
        self.scorer = QualityScorer()
    
    def test_end_to_end_scoring(self):
        """测试端到端评分流程"""
        test_content = {
            'title': 'Advanced Machine Learning Techniques',
            'content': 'This comprehensive review covers state-of-the-art machine learning algorithms, including deep learning, reinforcement learning, and transfer learning. The paper includes extensive experimental results, statistical analysis, and comparison with existing methods.',
            'url': 'https://arxiv.org/abs/2024.01234',
            'domain': 'arxiv.org',
            'author': 'Dr. Jane Smith, Stanford University',
            'publication_date': '2024-01-15'
        }
        
        # 评估内容质量
        content_quality = self.scorer.score_content_quality(test_content)
        assert content_quality.overall_score > 0.6
        
        # 评估源可信度
        source_credibility = self.scorer.evaluate_source_credibility(test_content)
        assert source_credibility.overall_credibility > 0.7
        
        # 计算综合评分
        composite_score = self.scorer.calculate_composite_score(
            content_quality, source_credibility
        )
        assert composite_score > 0.6
        
        # 获取质量等级
        tier = self.scorer.get_quality_tier(composite_score)
        assert tier in ['basic', 'standard', 'premium']
    
    @patch('src.tools.quality_scoring.QualityScorer.score_content_quality')
    def test_scoring_with_mock(self, mock_score):
        """测试使用Mock的评分功能"""
        # 设置Mock返回值
        mock_quality = ContentQuality(
            overall_score=0.8,
            depth_score=0.7,
            accuracy_indicators=0.9,
            completeness=0.8,
            clarity=0.7
        )
        mock_score.return_value = mock_quality
        
        content = {'title': 'Test', 'content': 'Test content'}
        result = self.scorer.score_content_quality(content)
        
        assert result == mock_quality
        mock_score.assert_called_once_with(content)