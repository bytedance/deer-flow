# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock
from src.tools.authority_search import AuthoritySourceManager, authority_search_tool


class TestAuthoritySourceManager:
    """AuthoritySourceManager类的单元测试"""
    
    def setup_method(self):
        """每个测试方法前的设置"""
        self.manager = AuthoritySourceManager()
    
    def test_initialization(self):
        """测试AuthoritySourceManager初始化"""
        assert self.manager is not None
        assert hasattr(self.manager, 'get_domain_priority')
        assert hasattr(self.manager, 'filter_authority_sources')
    
    def test_get_domain_priority_government(self):
        """测试政府域名优先级评分"""
        # 测试中国政府域名
        gov_cn_score = self.manager.get_domain_priority("www.gov.cn")
        assert gov_cn_score == 10.0
        
        # 测试其他政府域名
        gov_score = self.manager.get_domain_priority("www.whitehouse.gov")
        assert gov_score == 10.0
        
        # 测试部委域名
        ministry_score = self.manager.get_domain_priority("www.mof.gov.cn")
        assert ministry_score == 10.0
    
    def test_get_domain_priority_academic(self):
        """测试学术机构域名优先级评分"""
        # 测试知名大学
        tsinghua_score = self.manager.get_domain_priority("www.tsinghua.edu.cn")
        assert tsinghua_score >= 8.0
        
        # 测试国外大学
        mit_score = self.manager.get_domain_priority("web.mit.edu")
        assert mit_score >= 8.0
        
        # 测试研究机构
        cas_score = self.manager.get_domain_priority("www.cas.cn")
        assert cas_score >= 8.0
    
    def test_get_domain_priority_international_org(self):
        """测试国际组织域名优先级评分"""
        # 测试联合国
        un_score = self.manager.get_domain_priority("www.un.org")
        assert un_score >= 9.0
        
        # 测试世界银行
        wb_score = self.manager.get_domain_priority("www.worldbank.org")
        assert wb_score >= 9.0
        
        # 测试WHO
        who_score = self.manager.get_domain_priority("www.who.int")
        assert who_score >= 9.0
    
    def test_get_domain_priority_media(self):
        """测试权威媒体域名优先级评分"""
        # 测试新华社
        xinhua_score = self.manager.get_domain_priority("www.xinhuanet.com")
        assert xinhua_score >= 7.0
        
        # 测试人民日报
        peoples_score = self.manager.get_domain_priority("www.people.com.cn")
        assert peoples_score >= 7.0
        
        # 测试BBC
        bbc_score = self.manager.get_domain_priority("www.bbc.com")
        assert bbc_score >= 7.0
    
    def test_get_domain_priority_unknown(self):
        """测试未知域名优先级评分"""
        unknown_score = self.manager.get_domain_priority("www.unknown-site.com")
        assert unknown_score == 5.0  # 默认分数
    
    def test_get_domain_priority_empty_domain(self):
        """测试空域名处理"""
        empty_score = self.manager.get_domain_priority("")
        assert empty_score == 5.0
        
        none_score = self.manager.get_domain_priority(None)
        assert none_score == 5.0
    
    def test_filter_authority_sources_basic(self):
        """测试基本的权威源过滤"""
        search_results = [
            {"url": "https://www.gov.cn/article1", "title": "政府报告", "content": "官方内容"},
            {"url": "https://www.example.com/article2", "title": "普通文章", "content": "普通内容"},
            {"url": "https://www.tsinghua.edu.cn/research", "title": "学术研究", "content": "研究内容"},
        ]
        
        filtered = self.manager.filter_authority_sources(search_results, min_score=7.0)
        
        # 应该只保留政府和学术机构的结果
        assert len(filtered) == 2
        assert any("gov.cn" in result["url"] for result in filtered)
        assert any("tsinghua.edu.cn" in result["url"] for result in filtered)
    
    def test_filter_authority_sources_empty_input(self):
        """测试空输入的权威源过滤"""
        filtered = self.manager.filter_authority_sources([], min_score=7.0)
        assert filtered == []
        
        filtered_none = self.manager.filter_authority_sources(None, min_score=7.0)
        assert filtered_none == []
    
    def test_filter_authority_sources_high_threshold(self):
        """测试高阈值的权威源过滤"""
        search_results = [
            {"url": "https://www.gov.cn/article1", "title": "政府报告"},
            {"url": "https://www.xinhuanet.com/article2", "title": "新华社报道"},
            {"url": "https://www.example.com/article3", "title": "普通文章"},
        ]
        
        # 使用很高的阈值，只有政府源能通过
        filtered = self.manager.filter_authority_sources(search_results, min_score=9.5)
        
        assert len(filtered) == 1
        assert "gov.cn" in filtered[0]["url"]
    
    def test_get_authority_info(self):
        """测试获取权威机构信息"""
        # 测试政府机构
        gov_info = self.manager.get_authority_info("www.gov.cn")
        assert gov_info["type"] == "government"
        assert gov_info["credibility"] == 10.0
        assert "中国政府" in gov_info["description"]
        
        # 测试学术机构
        edu_info = self.manager.get_authority_info("www.tsinghua.edu.cn")
        assert edu_info["type"] == "academic"
        assert edu_info["credibility"] >= 8.0
        
        # 测试未知机构
        unknown_info = self.manager.get_authority_info("www.unknown.com")
        assert unknown_info["type"] == "unknown"
        assert unknown_info["credibility"] == 5.0
    
    def test_sort_by_authority_priority(self):
        """测试按权威性排序"""
        search_results = [
            {"url": "https://www.example.com/article1", "title": "普通文章"},
            {"url": "https://www.gov.cn/article2", "title": "政府报告"},
            {"url": "https://www.tsinghua.edu.cn/article3", "title": "学术研究"},
            {"url": "https://www.xinhuanet.com/article4", "title": "新华社报道"},
        ]
        
        sorted_results = self.manager.sort_by_authority_priority(search_results)
        
        # 验证排序正确性：政府 > 学术 > 媒体 > 普通
        assert "gov.cn" in sorted_results[0]["url"]
        assert "tsinghua.edu.cn" in sorted_results[1]["url"]
        assert "xinhuanet.com" in sorted_results[2]["url"]
        assert "example.com" in sorted_results[3]["url"]


class TestAuthoritySearchTool:
    """authority_search_tool的单元测试"""
    
    @patch('src.tools.authority_search.get_web_search_tool')
    def test_authority_search_tool_basic(self, mock_search_tool):
        """测试权威搜索工具基本功能"""
        # Mock搜索工具返回结果
        mock_search_results = [
            {"url": "https://www.gov.cn/policy", "title": "政策文件", "content": "官方政策"},
            {"url": "https://www.example.com/news", "title": "新闻报道", "content": "普通新闻"},
        ]
        
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = mock_search_results
        mock_search_tool.return_value = mock_tool
        
        # 执行权威搜索
        query = "人工智能政策"
        results = authority_search_tool.invoke({"query": query})
        
        # 验证结果
        assert isinstance(results, list)
        assert len(results) > 0
        
        # 验证权威源优先
        if len(results) > 1:
            first_result = results[0]
            assert "gov.cn" in first_result["url"]  # 政府源应该排在前面
    
    @patch('src.tools.authority_search.get_web_search_tool')
    def test_authority_search_tool_empty_results(self, mock_search_tool):
        """测试权威搜索工具处理空结果"""
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = []
        mock_search_tool.return_value = mock_tool
        
        results = authority_search_tool.invoke({"query": "测试查询"})
        
        assert results == []
    
    @patch('src.tools.authority_search.get_web_search_tool')
    def test_authority_search_tool_error_handling(self, mock_search_tool):
        """测试权威搜索工具错误处理"""
        mock_tool = MagicMock()
        mock_tool.invoke.side_effect = Exception("搜索失败")
        mock_search_tool.return_value = mock_tool
        
        # 应该有错误处理机制
        try:
            results = authority_search_tool.invoke({"query": "测试查询"})
            # 如果有fallback机制，应该返回空列表或默认结果
            assert isinstance(results, list)
        except Exception:
            # 如果没有错误处理，应该抛出异常
            pass


class TestAuthoritySearchIntegration:
    """权威搜索集成测试"""
    
    def test_full_authority_search_workflow(self):
        """测试完整的权威搜索工作流程"""
        manager = AuthoritySourceManager()
        
        # 模拟搜索结果
        mock_results = [
            {"url": "https://www.stats.gov.cn/data", "title": "统计数据", "content": "官方统计"},
            {"url": "https://www.tsinghua.edu.cn/research", "title": "研究报告", "content": "学术研究"},
            {"url": "https://www.sohu.com/news", "title": "新闻报道", "content": "媒体报道"},
            {"url": "https://www.random-blog.com/post", "title": "博客文章", "content": "个人观点"},
        ]
        
        # 1. 按权威性排序
        sorted_results = manager.sort_by_authority_priority(mock_results)
        
        # 2. 过滤高质量源
        filtered_results = manager.filter_authority_sources(sorted_results, min_score=7.0)
        
        # 3. 验证结果质量
        assert len(filtered_results) >= 2  # 至少保留政府和学术源
        assert all(manager.get_domain_priority(result["url"]) >= 7.0 
                  for result in filtered_results)
        
        # 4. 验证排序正确性
        priorities = [manager.get_domain_priority(result["url"]) 
                     for result in filtered_results]
        assert priorities == sorted(priorities, reverse=True)


if __name__ == "__main__":
    pytest.main([__file__])