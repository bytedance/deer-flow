import json
from typing import Any, Dict, List, Optional

from langchain_community.utilities import SearxSearchWrapper
from langchain_community.tools.searx_search.tool import SearxSearchResults


class CustomSearxSearchWrapper(SearxSearchWrapper):
    """Custom SearxNG搜索包装器，返回标准化JSON格式结果"""
    
    def results(
        self,
        query: str,
        num_results: int,
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        query_suffix: Optional[str] = "",
        **kwargs: Any,
    ) -> List[Dict]:
        # 调用父类获取原始结果
        raw_results = super().results(
            query=query,
            num_results=num_results,
            engines=engines,
            categories=categories,
            query_suffix=query_suffix,
            **kwargs
        )
        
        # 转换结果格式
        formatted_results = []
        for result in raw_results:
            formatted = {
                "type": "page",  # 默认类型为网页
                "title": result.get("title", ""),
                "url": result.get("link", ""),    # 原始字段名为link
                "content": result.get("snippet", ""),  # 原始字段名为snippet
            }
            formatted_results.append(formatted)
        
        return formatted_results

    async def aresults(
        self,
        query: str,
        num_results: int,
        engines: Optional[List[str]] = None,
        query_suffix: Optional[str] = "",
        **kwargs: Any,
    ) -> str:
        """异步获取并格式化结果"""
        raw_results = await super().aresults(
            query=query,
            num_results=num_results,
            engines=engines,
            query_suffix=query_suffix,
            **kwargs
        )
        
        # 转换异步结果格式
        formatted_results = []
        for result in raw_results:
            formatted = {
                "type": "page",
                "title": result.get("title", ""),
                "url": result.get("link", ""),
                "content": result.get("snippet", ""),
            }
            formatted_results.append(formatted)
        
        return json.dumps(formatted_results, ensure_ascii=False)


class CustomSearxSearchResults(SearxSearchResults):
    """支持JSON格式输出的SearxNG搜索工具"""
    
    def _run(self, query: str) -> str:
        """同步执行搜索并返回JSON字符串"""
        results = self.wrapper.results(
            query=query,
            num_results=self.kwargs.get("num_results", 5)
        )
        return json.dumps(results, ensure_ascii=False)

    async def _arun(self, query: str) -> str:
        """异步执行搜索并返回JSON字符串"""
        return await self.wrapper.aresults(
            query=query,
            num_results=self.kwargs.get("num_results", 5)
        )
