# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from typing import Dict, List, Optional, Union
import asyncio

from tencentcloud.common.common_client import CommonClient
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

logger = logging.getLogger(__name__)


class SogouSearchAPIWrapper:
    """
    搜狗搜索API包装器 - 基于腾讯云TMS API实现
    支持文本搜索功能
    """
    
    def __init__(
        self,
        secret_id: Optional[str] = None,
        secret_key: Optional[str] = None,
        endpoint: str = "tms.tencentcloudapi.com",
        region: str = "ap-beijing"
    ):
        """
        初始化搜狗搜索API包装器
        
        Args:
            secret_id: 腾讯云访问密钥ID
            secret_key: 腾讯云访问密钥Secret  
            endpoint: API端点，默认为tms.tencentcloudapi.com
            region: 服务区域，默认ap-beijing
        """
        self.secret_id = secret_id or os.getenv("TENCENT_CLOUD_SECRET_ID")
        self.secret_key = secret_key or os.getenv("TENCENT_CLOUD_SECRET_KEY")
        self.endpoint = endpoint
        self.region = region
        logger.info(f"secret_id: {self.secret_id}, secret_key: {self.secret_key}")
        
        if not all([self.secret_id, self.secret_key]):
            raise ValueError("需要提供腾讯云的secret_id和secret_key")
        
        # 初始化凭证
        self.cred = credential.Credential(self.secret_id, self.secret_key)
        
        # 配置HTTP请求配置
        self.http_profile = HttpProfile()
        self.http_profile.endpoint = self.endpoint
        
        # 配置客户端配置
        self.client_profile = ClientProfile()
        self.client_profile.httpProfile = self.http_profile
        
        # 创建公共客户端
        self.common_client = CommonClient("tms", "2020-12-29", self.cred, self.region, profile=self.client_profile)
    
    def search(self, query: str, mode: int = 1, insite: Optional[str] = None, max_results: int = 5, **kwargs) -> Dict:
        """
        同步执行搜索
        
        Args:
            query: 搜索查询字符串
            mode: 搜索模式，默认为1
            insite: 指定站点搜索，如zhihu.com
            max_results: 返回的最大搜索结果数量
            **kwargs: 其他参数
        
        Returns:
            Dict: 搜索结果
        """
        try:
            logger.info(f"开始搜索: query='{query}', mode={mode}, insite='{insite}'")
            self.max_results = max_results
            # 构建搜索参数
            search_params = {"Query": query}
            if mode != 1:
                search_params["Mode"] = mode
            if insite:
                search_params["Insite"] = insite
                
            params_json = json.dumps(search_params, ensure_ascii=False)
            response = self.common_client.call_json("SearchPro", json.loads(params_json))
            
            return response
            
        except TencentCloudSDKException as e:
            error_msg = f"腾讯云API调用失败: {str(e)}"
            logger.error(error_msg)
            return {"error": f"搜索失败: {str(e)}"}
        except Exception as e:
            error_msg = f"搜索失败: {str(e)}"
            logger.error(error_msg)
            return {"error": f"搜索失败: {str(e)}"}
    
    async def search_async(self, query: str, mode: int = 1, insite: Optional[str] = None, max_results: int = 5, **kwargs) -> Dict:
        """
        异步执行搜索
        
        Args:
            query: 搜索查询字符串
            mode: 搜索模式，默认为1
            insite: 指定站点搜索，如zhihu.com
            max_results: 返回的最大搜索结果数量
            **kwargs: 其他参数
        
        Returns:
            Dict: 搜索结果
        """
        # 在异步环境中运行同步搜索
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.search, query, mode, insite, max_results, **kwargs)
    
    def clean_results(self, raw_results: Dict) -> List[Dict[str, str]]:
        """
        清理和格式化搜索结果
        
        Args:
            raw_results: 原始API响应
        
        Returns:
            List[Dict[str, str]]: 清理后的搜索结果列表
        """
        try:
            cleaned_results = []
            
            # 检查响应结构
            if not isinstance(raw_results, dict):
                logger.warning("原始结果不是字典格式")
                return cleaned_results
            
            response = raw_results.get("Response", {})
            if not response:
                logger.warning("响应中没有Response字段")
                return cleaned_results
            
            pages = response.get("Pages", [])
            if pages and isinstance(pages, list):
                for i, page in enumerate(pages):
                    if isinstance(page, str):
                        # 尝试解析页面内容，提取标题和链接
                        try:                          
                            cleaned_results.append({
                                "title": json.loads(page).get("title", ""),
                                "content": json.loads(page).get("content", ""),
                                "url": json.loads(page).get("url", ""),
                                "source": json.loads(page).get("site", ""),
                                "score": json.loads(page).get("score", 0),
                                "date": json.loads(page).get("date", ""),
                            })
                        except Exception as e:
                            logger.warning(f"解析页面内容失败: {e}")
                            cleaned_results.append({
                                "title": page.split("title")[1].split("url")[0].strip(),
                                "content": page.split("content")[1].split("site")[0].strip(),
                                "url": page.split("url")[1].split("content")[0].strip(),
                                "source": page.split("site")[1].split("images")[0].strip(),
                                "score": page.split("score")[1].split("date")[0].strip(),
                                "date": page.split("date")[1].split("title")[0].strip(),
                            })
            else:
                cleaned_results.append({
                    "title": "搜索结果",
                    "content": json.dumps(response, ensure_ascii=False, indent=2),
                    "url": "API响应",
                    "source": "搜狗搜索"
                })
            
            return cleaned_results[:self.max_results]
            
        except Exception as e:
            logger.error(f"清理搜索结果失败: {str(e)}")
            return [{
                "title": "处理错误",
                "content": f"处理搜索结果时发生错误: {str(e)}",
                "url": "错误",
                "source": "搜狗搜索"
            }]


if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    async def test_sogou_search_api():
        """测试搜狗搜索API包装器"""
        # 使用环境变量或默认值进行测试
        try:
            api = SogouSearchAPIWrapper()
            
            # 测试同步搜索
            print("\n1. 测试同步搜索:")
            results = api.search("小红书巴黎奥运会田径运动员足球球星短片")
            cleaned = api.clean_results(results)
            print(f"清理后结果: {cleaned}")
            
            # 测试异步搜索
            print("\n2. 测试异步搜索:")
            async_results = await api.search_async("DeepSeek 最新", mode=2, insite="zhihu.com")
            async_cleaned = api.clean_results(async_results)
            print(f"异步清理后结果: {async_cleaned}")
            
        except Exception as e:
            print(f"测试失败: {e}")
    
    asyncio.run(test_sogou_search_api())