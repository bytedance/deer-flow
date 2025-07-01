# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Dict, List, Optional, Tuple, Union
import logging

from langchain.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import Field

from .sogou_search_api_wrapper import SogouSearchAPIWrapper

logger = logging.getLogger(__name__)


class SogouSearchResults(BaseTool):
    """搜狗搜索工具 - 基于腾讯云TMS API实现文本搜索"""
    
    name: str = "sogou_search"
    description: str = (
        "使用搜狗进行网络搜索的工具："
        "输入参数："
        "- query (必需): 搜索查询字符串"
        "- mode (可选): 搜索模式，默认为1"
        "- insite (可选): 指定站点搜索，如zhihu.com"
        "输出: 包含搜索结果的JSON列表"
    )
    
    api_wrapper: SogouSearchAPIWrapper = Field(default_factory=SogouSearchAPIWrapper)
    max_results: int = Field(default=5, description="返回的最大搜索结果数量")
    
    def _run(
        self,
        query: str,
        mode: int = 1,
        insite: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        同步执行搜索
        
        Args:
            query: 搜索查询字符串
            mode: 搜索模式，默认为1
            insite: 指定站点搜索，如zhihu.com
            **kwargs: 其他参数
        
        Returns:
            Tuple[搜索结果, 原始结果]
        """
        try:
            logger.info(f"开始同步搜索: query='{query}', mode={mode}, insite='{insite}'")
            
            raw_results = self.api_wrapper.search(
                query=query, 
                mode=mode,
                insite=insite,
                max_results=self.max_results,
                **kwargs
            )
            cleaned_results = self.api_wrapper.clean_results(raw_results)
            
            logger.info(f"同步搜索完成，返回 {len(cleaned_results)} 个结果")
            return cleaned_results
            
        except Exception as e:
            error_msg = f"搜狗搜索失败: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    async def _arun(
        self,
        query: str,
        mode: int = 1,
        insite: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        异步执行搜索
        
        Args:
            query: 搜索查询字符串
            mode: 搜索模式，默认为1
            insite: 指定站点搜索，如zhihu.com
            **kwargs: 其他参数
        
        Returns:
            搜索结果
        """
        try:
            logger.info(f"开始异步搜索: query='{query}', mode={mode}, insite='{insite}'")
            
            raw_results = await self.api_wrapper.search_async(
                query=query, 
                mode=mode,
                insite=insite,
                max_results=self.max_results,
                **kwargs
            )
            cleaned_results = self.api_wrapper.clean_results(raw_results)
            
            logger.info(f"异步搜索完成，返回 {len(cleaned_results)} 个结果")
            return cleaned_results
            
        except Exception as e:
            error_msg = f"搜狗异步搜索失败: {str(e)}"
            logger.error(error_msg)
            return error_msg


if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    async def test_sogou_search_tool():
        """测试搜狗搜索工具"""
        try:
            # 创建搜索工具实例
            search_tool = SogouSearchResults()
            
            # 测试同步搜索
            print("\n1. 测试同步搜索:")
            text_results = search_tool._run("小红书巴黎奥运会田径运动员足球球星短片")
            for i, result in enumerate(text_results):
                print(f"第{i+1}个结果:")
                print(result)
            
            # 测试异步搜索
            print("\n2. 测试异步搜索:")
            async_results = await search_tool._arun("DeepSeek 最新", mode=2, insite="zhihu.com")
            for i, result in enumerate(async_results):
                print(f"第{i+1}个结果:")
                print(result)
                    
        except Exception as e:
            print(f"测试错误: {e}")
        
        # 打印总结日志
        logger.info("=== 测试完成 ===")
    
    asyncio.run(test_sogou_search_tool()) 