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

from .volcano_search_api_wrapper import VolcanoSearchAPIWrapper

logger = logging.getLogger(__name__)


class VolcanoSearchResults(BaseTool):
    """火山引擎统一搜索工具，自动识别并支持文本搜索和图像搜索"""
    
    name: str = "volcano_search"
    description: str = (
        "使用火山引擎进行网络搜索的统一工具，自动识别搜索类型："
        "1. 仅提供query参数：执行文本搜索"
        "2. 同时提供query和images参数：执行图像搜索"
        "输入参数："
        "- query (必需): 搜索查询字符串"
        "- images (可选): 图片列表，支持本地文件路径和网络URL"
        "输出: 包含搜索结果的JSON列表"
    )
    
    api_wrapper: VolcanoSearchAPIWrapper = Field(default_factory=VolcanoSearchAPIWrapper)
    max_results: int = Field(default=5, description="返回的最大搜索结果数量")
    
    def _run(
        self,
        query: str,
        images: Optional[List[Union[str, Dict]]] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        同步执行搜索，自动识别搜索类型
        
        Args:
            query: 搜索查询字符串
            images: 图片列表（可选，如果提供则执行图像搜索）
            **kwargs: 其他参数
        
        Returns:
            Tuple[搜索结果, 原始结果]
        """
        try:
            # 自动识别搜索类型
            has_images = images and len(images) > 0
            search_type = "多模态搜索" if has_images else "文本搜索"
            
            logger.info(f"开始同步{search_type}: query='{query}', images_count={len(images) if images else 0}")
            
            # 执行搜索
            raw_results = self.api_wrapper.search(
                query=query, 
                max_results=self.max_results, 
                images=images if has_images else None,
                **kwargs
            )
            
            # 清理结果
            cleaned_results = self.api_wrapper.clean_results(raw_results)
            
            logger.info(f"同步{search_type}完成，返回 {len(cleaned_results)} 个结果")
            return cleaned_results
            
        except Exception as e:
            error_msg = f"火山引擎搜索失败: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    async def _arun(
        self,
        query: str,
        images: Optional[List[Union[str, Dict]]] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        异步执行搜索，自动识别搜索类型
        
        Args:
            query: 搜索查询字符串
            images: 图片列表（可选，如果提供则执行图像搜索）
            **kwargs: 其他参数
        
        Returns:
            Tuple[搜索结果, 原始结果]
        """
        try:
            # 自动识别搜索类型
            has_images = images and len(images) > 0
            search_type = "多模态搜索" if has_images else "文本搜索"
            
            logger.info(f"开始异步{search_type}: query='{query}', images_count={len(images) if images else 0}")
            
            # 执行异步搜索
            raw_results = await self.api_wrapper.search_async(
                query=query, 
                max_results=self.max_results, 
                images=images if has_images else None,
                **kwargs
            )
            
            # 清理结果
            cleaned_results = self.api_wrapper.clean_results(raw_results)
            
            logger.info(f"异步{search_type}完成，返回 {len(cleaned_results)} 个结果")
            return cleaned_results
            
        except Exception as e:
            error_msg = f"火山引擎异步搜索失败: {str(e)}"
            logger.error(error_msg)
            return error_msg


if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    async def test_unified_volcano_search():
        """测试统一的火山引擎搜索工具"""
        from src.tools.search import get_web_search_tool
        search_tool = get_web_search_tool(3)
        import time
        start_time = time.time()
        # 测试文本搜索
        print("\n1. 测试文本搜索:")
        try:
            text_results = search_tool.invoke(
                input = {
                    "query": "查找资料并生成2012—2023年中国人口数据的真实数据，要求有年份，人口总数，出生人口，死亡人口。"
                }
            )
            if isinstance(text_results, list) and len(text_results) > 0:
                for i, result in enumerate(text_results):
                    print(f"第{i+1}个结果:")
                    print(result)
        except Exception as e:
            print(f"文本搜索错误: {e}")
        
        end_time = time.time()
        print(f"文本搜索耗时: {end_time - start_time} 秒")
        
        # 测试图像搜索
        print("\n2. 测试图像搜索:")
        try:
            image_results = await search_tool.ainvoke(
                input = {
                    "query": "描述这张图片，并判断这张图片是哪一首曲子？",
                    "images": ["/mnt/afs/shaoyuyao/code/agent/test/images/07708079f24c7ffc54815f45be1fb8839870763-c3f1-43cd-9482-0ee91.jpg"]
                }
            )
            if isinstance(image_results, list) and len(image_results) > 0:
                for i, result in enumerate(image_results):
                    print(f"第{i+1}个结果:")
                    print(result)
        except Exception as e:
            print(f"图像搜索错误: {e}")
        
        end_time2 = time.time()
        print(f"图像搜索耗时: {end_time2 - end_time} 秒")
        
        # 打印总结日志
        logger.info("=== 测试完成 ===")
        logger.info(f"总耗时: {end_time2 - start_time} 秒")
    
    asyncio.run(test_unified_volcano_search()) 