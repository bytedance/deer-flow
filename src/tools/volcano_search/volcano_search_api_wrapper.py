# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from typing import Dict, List, Optional, Union
import requests
import httpx
import hashlib
import hmac
import time
import base64
import urllib.parse
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class VolcanoSearchAPIWrapper:
    """
    火山引擎搜索API包装器 - 支持文本和图像搜索
    基于火山引擎智能体API实现
    """
    
    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bot_id: Optional[str] = None,
        region: str = "cn-north-1"
    ):
        """
        初始化火山引擎搜索API包装器
        
        Args:
            access_key: 火山引擎访问密钥ID
            secret_key: 火山引擎访问密钥Secret  
            bot_id: 搜索智能体ID
            region: 服务区域，默认cn-north-1
        """
        self.access_key = access_key or os.getenv("VOLCANO_ACCESS_KEY")
        self.secret_key = secret_key or os.getenv("VOLCANO_SECRET_KEY")
        self.bot_id = bot_id or os.getenv("VOLCANO_SEARCH_BOT_ID")
        self.region = region
        
        if not all([self.access_key, self.secret_key, self.bot_id]):
            raise ValueError("需要提供火山引擎的access_key, secret_key和bot_id")
            
        self.service_name = "volc_torchlight_api"
        self.host = "mercury.volcengineapi.com"
        self.base_url = f"https://{self.host}"
    
    def _get_canonical_query_string(self, params: Dict[str, str]) -> str:
        """构建规范化查询字符串"""
        sorted_params = sorted(params.items())
        return '&'.join([f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted_params])
    
    def _get_canonical_headers(self, headers: Dict[str, str]) -> tuple:
        """构建规范化请求头"""
        canonical_headers = []
        signed_headers = []
        
        # 按字母顺序排序请求头
        sorted_headers = sorted(headers.items(), key=lambda x: x[0].lower())
        
        for key, value in sorted_headers:
            canonical_headers.append(f"{key.lower()}:{value.strip()}")
            signed_headers.append(key.lower())
            
        return '\n'.join(canonical_headers), ';'.join(signed_headers)
    
    def _get_payload_hash(self, payload: str) -> str:
        """计算请求体哈希值"""
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()
    
    def _get_canonical_request(self, method: str, uri: str, query_string: str, 
                             canonical_headers: str, signed_headers: str, payload_hash: str) -> str:
        """构建规范化请求"""
        return f"{method}\n{uri}\n{query_string}\n{canonical_headers}\n\n{signed_headers}\n{payload_hash}"
    
    def _get_string_to_sign(self, timestamp: str, credential_scope: str, canonical_request: str) -> str:
        """构建待签名字符串"""
        algorithm = "HMAC-SHA256"
        canonical_request_hash = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        return f"{algorithm}\n{timestamp}\n{credential_scope}\n{canonical_request_hash}"
    
    def _get_signing_key(self, date: str) -> bytes:
        """计算签名密钥"""
        k_date = hmac.new(self.secret_key.encode('utf-8'), date.encode('utf-8'), hashlib.sha256).digest()
        k_region = hmac.new(k_date, self.region.encode('utf-8'), hashlib.sha256).digest()
        k_service = hmac.new(k_region, self.service_name.encode('utf-8'), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
        return k_signing
    
    def _get_signature(self, signing_key: bytes, string_to_sign: str) -> str:
        """计算签名"""
        return hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    
    def _sign_request(self, method: str, uri: str, params: Dict[str, str], 
                     headers: Dict[str, str], payload: str) -> Dict[str, str]:
        """对请求进行签名"""
        # 时间戳
        now = time.gmtime()
        timestamp = time.strftime('%Y%m%dT%H%M%SZ', now)
        date = time.strftime('%Y%m%d', now)
        
        # 添加必要的请求头
        headers['Host'] = self.host
        headers['X-Date'] = timestamp
        headers['Content-Type'] = 'application/json'
        
        # 构建规范化组件
        query_string = self._get_canonical_query_string(params)
        canonical_headers, signed_headers = self._get_canonical_headers(headers)
        payload_hash = self._get_payload_hash(payload)
        
        # 构建规范化请求
        canonical_request = self._get_canonical_request(
            method, uri, query_string, canonical_headers, signed_headers, payload_hash
        )
        
        # 构建待签名字符串
        credential_scope = f"{date}/{self.region}/{self.service_name}/request"
        string_to_sign = self._get_string_to_sign(timestamp, credential_scope, canonical_request)
        
        # 计算签名
        signing_key = self._get_signing_key(date)
        signature = self._get_signature(signing_key, string_to_sign)
        
        # 构建Authorization头
        authorization = (
            f"HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        
        headers['Authorization'] = authorization
        return headers
    
    def _image_to_base64(self, image_path: str) -> str:
        """将本地图片转换为base64格式"""
        with open(image_path, 'rb') as image_file:
            image_data = image_file.read()
            base64_string = base64.b64encode(image_data).decode('utf-8')
            
            # 检测图片格式
            if image_path.lower().endswith('.png'):
                mime_type = 'image/png'
            elif image_path.lower().endswith(('.jpg', '.jpeg')):
                mime_type = 'image/jpeg'
            elif image_path.lower().endswith('.gif'):
                mime_type = 'image/gif'
            elif image_path.lower().endswith('.webp'):
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'  # 默认
                
            return f"data:{mime_type};base64,{base64_string}"
    
    def create_text_message(self, role: str, content: str) -> Dict:
        """创建文本消息"""
        return {
            "role": role,
            "content": content
        }
    
    def create_multimodal_message(self, role: str, text: str, images: List[Union[str, Dict]]) -> Dict:
        """
        创建多模态消息（文本+图片）
        
        Args:
            role: 角色 (user/assistant/system)
            text: 文本内容
            images: 图片列表，可以是：
                   - 本地文件路径字符串
                   - 网络URL字符串  
                   - 字典格式: {"type": "file|url", "value": "路径或URL"}
        """
        content = [{"type": "text", "text": text}]
        
        for image in images:
            if isinstance(image, str):
                # 判断是本地文件还是URL
                if image.startswith(('http://', 'https://')):
                    # 网络URL
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": image}
                    })
                else:
                    # 本地文件，转换为base64
                    base64_url = self._image_to_base64(image)
                    content.append({
                        "type": "image_url", 
                        "image_url": {"url": base64_url}
                    })
            elif isinstance(image, dict):
                if image.get("type") == "file":
                    base64_url = self._image_to_base64(image["value"])
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": base64_url}
                    })
                elif image.get("type") == "url":
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": image["value"]}
                    })
        
        return {
            "role": role,
            "content": content
        }
    
    def _prepare_request_data(self, query: str, images: Optional[List[Union[str, Dict]]] = None, 
                            max_results: int = 5, **kwargs) -> tuple:
        """
        准备请求数据（支持文本和图像搜索）
        
        Args:
            query: 搜索查询字符串
            images: 图片列表（可选）
            max_results: 最大结果数量
            **kwargs: 其他参数
        
        Returns:
            tuple: (url, headers, payload)
        """
        # 构造搜索消息
        if images and len(images) > 0:
            # 多模态搜索（文本+图像）
            messages = [
                self.create_multimodal_message("user", query, images)
            ]
        else:
            # 纯文本搜索
            messages = [
                self.create_text_message("user", query)
            ]
        
        # 构造请求参数
        params = {
            "Action": "ChatCompletion",
            "Version": "2024-01-01",
            "Limit": max_results
        }
        
        # 构建请求体
        request_body = {
            "bot_id": self.bot_id,
            "messages": messages,
            "stream": False,
            "user_id": f"search_user_{int(time.time())}"
        }
        
        # 添加其他可选参数
        for key, value in kwargs.items():
            if value is not None:
                request_body[key] = value
        
        payload = json.dumps(request_body, ensure_ascii=False)
        
        # 签名请求
        headers = self._sign_request("POST", "/", params, {}, payload)
        
        # 构造完整URL
        url = f"{self.base_url}/?{self._get_canonical_query_string(params)}"
        
        return url, headers, payload
    
    def search(self, query: str, max_results: int = 5, images: Optional[List[Union[str, Dict]]] = None,
               **kwargs) -> Dict:
        """
        同步执行搜索查询（支持文本和图像搜索）
        
        Args:
            query: 搜索查询字符串
            max_results: 最大结果数量
            images: 图片列表（可选）
            **kwargs: 其他参数
            
        Returns:
            搜索结果字典
        """
        try:
            self.max_results = max_results
            url, headers, payload = self._prepare_request_data(query, images, max_results, **kwargs)
            
            response = requests.post(
                url,
                headers=headers,
                data=payload,
                timeout=30
            )
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"火山引擎搜索失败: {str(e)}")
            return {"error": f"搜索失败: {str(e)}"}
    
    async def search_async(self, query: str, max_results: int = 5, 
                          images: Optional[List[Union[str, Dict]]] = None, **kwargs) -> Dict:
        """
        异步执行搜索查询（支持文本和图像搜索）
        
        Args:
            query: 搜索查询字符串
            max_results: 最大结果数量
            images: 图片列表（可选）
            **kwargs: 其他参数
            
        Returns:
            搜索结果字典
        """
        try:
            self.max_results = max_results
            url, headers, payload = self._prepare_request_data(query, images, max_results, **kwargs)
            
            # 使用httpx进行异步请求
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    data=payload
                )
                response.raise_for_status()
                
                return response.json()
                
        except httpx.TimeoutException:
            error_msg = "火山引擎搜索请求超时"
            logger.error(error_msg)
            return {"error": error_msg}
        except httpx.HTTPStatusError as e:
            error_msg = f"火山引擎搜索HTTP错误: {e.response.status_code}"
            logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"火山引擎搜索失败: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def clean_results(self, raw_results: Dict) -> List[Dict[str, str]]:
        """
        清理和格式化搜索结果，使其符合DeerFlow的标准格式
        
        Args:
            raw_results: 原始搜索结果
            
        Returns:
            格式化后的搜索结果列表
        """
        try:
            if "error" in raw_results:
                return [{"title": "搜索错误", "url": "", "content": raw_results["error"]}]
            
            results = []
            # 从火山引擎响应中提取references
            if "references" in raw_results and raw_results["references"]:
                for reference in raw_results["references"][:self.max_results]:
                    results.append({
                        "type": reference["source_type"],
                        "title": reference["title"],
                        "url": reference["url"],
                        "content": reference["summary"],
                    })
                
                return results
            else:
                return [{"title": "无搜索结果", "url": "", "content": "未找到相关信息"}]
                
        except Exception as e:
            logger.error(f"清理搜索结果失败: {str(e)}")
            return [{"title": "结果处理错误", "url": "", "content": f"处理结果时出错: {str(e)}"}]


if __name__ == "__main__":
    # 测试函数
    async def test_volcano_search_with_images():
        """测试火山引擎搜索工具（包括图像搜索）"""
        wrapper = VolcanoSearchAPIWrapper(
            access_key="",
            secret_key="",
            bot_id=""
        )
        
        try:
            text_results = await wrapper.search_async("查找资料并生成2012—2023年中国人口数据的真实数据，要求有年份，人口总数，出生人口，死亡人口。", max_results=1)
            cleaned_text = wrapper.clean_results(text_results)
            print("\n文本结果:")
            print(json.dumps(cleaned_text, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"文本搜索错误: {e}")

        try:
            local_image_path = "/mnt/afs/shaoyuyao/code/agent/test/images/07708079f24c7ffc54815f45be1fb8839870763-c3f1-43cd-9482-0ee91.jpg"
            if os.path.exists(local_image_path):
                image_results = await wrapper.search_async(
                    query="判断这张图片是哪一首曲子？",
                    images=[local_image_path],
                    max_results=1
                )
                cleaned_text = wrapper.clean_results(image_results)
                print("\n图像结果:")
                print(json.dumps(cleaned_text, indent=2, ensure_ascii=False))
            else:
                print("本地图片不存在，跳过测试")
        except Exception as e:
            print(f"图像搜索错误: {e}")
            
    asyncio.run(test_volcano_search_with_images())