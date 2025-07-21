# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
权威数据库单元测试
"""

import pytest
from src.config.authority_database import AuthorityDatabase, AuthoritySource


class TestAuthorityDatabase:
    """AuthorityDatabase类的单元测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.db = AuthorityDatabase()
    
    def test_initialization(self):
        """测试数据库初始化"""
        assert self.db is not None
        assert len(self.db.sources) > 0
        assert hasattr(self.db, 'get_source')
        assert hasattr(self.db, 'search_sources')
    
    def test_get_source_by_domain(self):
        """测试通过域名获取数据源"""
        # 测试政府域名
        gov_source = self.db.get_source("stats.gov.cn")
        if gov_source:
            assert gov_source.category == "government"
            assert gov_source.credibility_score >= 8
        
        # 测试学术域名
        edu_source = self.db.get_source("tsinghua.edu.cn")
        if edu_source:
            assert gov_source.category in ["academic", "education"]
    
    def test_search_sources_by_category(self):
        """测试按类别搜索数据源"""
        gov_sources = self.db.search_sources(category="government")
        assert len(gov_sources) > 0
        
        for source in gov_sources:
            assert source.category == "government"
            assert source.credibility_score >= 7
    
    def test_search_sources_by_country(self):
        """测试按国家搜索数据源"""
        china_sources = self.db.search_sources(country="China")
        assert len(china_sources) > 0
        
        for source in china_sources:
            assert source.country == "China"
    
    def test_get_top_sources_by_credibility(self):
        """测试获取高可信度数据源"""
        top_sources = self.db.get_top_sources_by_credibility(limit=5)
        assert len(top_sources) <= 5
        
        # 验证按可信度排序
        for i in range(1, len(top_sources)):
            assert top_sources[i-1].credibility_score >= top_sources[i].credibility_score
    
    def test_authority_source_model(self):
        """测试AuthoritySource数据模型"""
        source = AuthoritySource(
            domain="test.gov.cn",
            name="测试政府网站",
            category="government",
            country="China",
            language="zh",
            credibility_score=9,
            description="测试用政府网站"
        )
        
        assert source.domain == "test.gov.cn"
        assert source.category == "government"
        assert source.credibility_score == 9
        assert source.is_high_credibility() == True
    
    def test_source_validation(self):
        """测试数据源验证"""
        # 测试无效的可信度分数
        with pytest.raises(ValueError):
            AuthoritySource(
                domain="test.com",
                name="测试网站",
                category="other",
                credibility_score=11  # 超出范围
            )
    
    def test_search_with_multiple_filters(self):
        """测试多条件搜索"""
        results = self.db.search_sources(
            category="government",
            country="China",
            language="zh"
        )
        
        for source in results:
            assert source.category == "government"
            assert source.country == "China"
            assert source.language == "zh"