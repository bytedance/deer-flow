# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from typing import List, Optional

from src.rag.ragflow import RAGFlowProvider


class MOIProvider(RAGFlowProvider):
    """
    MOIProvider is a provider that uses MOI configuration but inherits all logic from RAGFlowProvider.
    It only overrides the initialization to read MOI_* environment variables instead of RAGFLOW_*.
    """

    def __init__(self):
        # 将MOI环境变量映射到RAGFLOW环境变量，但不恢复
        # 这样RAGFlowProvider的所有方法都能正常工作
        moi_url = os.getenv("MOI_API_URL")
        if not moi_url:
            raise ValueError("MOI_API_URL is not set")
        os.environ["RAGFLOW_API_URL"] = moi_url + "/byoa"
        
        moi_key = os.getenv("MOI_API_KEY")
        if not moi_key:
            raise ValueError("MOI_API_KEY is not set")
        os.environ["RAGFLOW_API_KEY"] = moi_key
        
        moi_size = os.getenv("MOI_RETRIEVAL_SIZE")
        if moi_size:
            os.environ["RAGFLOW_RETRIEVAL_SIZE"] = moi_size
            
        moi_languages = os.getenv("MOI_CROSS_LANGUAGES")
        if moi_languages:
            os.environ["RAGFLOW_CROSS_LANGUAGES"] = moi_languages
        
        # 调用父类的初始化方法
        super().__init__()
        
        # 设置MOI特有的list_limit参数
        self.moi_list_limit = None
        moi_list_limit = os.getenv("MOI_LIST_LIMIT")
        if moi_list_limit:
            self.moi_list_limit = int(moi_list_limit)

    def list_resources(self, query: str | None = None) -> list:
        """
        重写list_resources方法以支持MOI的limit参数
        """
        from src.rag.retriever import Resource
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        params = {}
        if query:
            params["name"] = query
        
        # 添加MOI特有的limit参数
        if self.moi_list_limit:
            params["limit"] = self.moi_list_limit

        import requests
        response = requests.get(
            f"{self.api_url}/api/v1/datasets", headers=headers, params=params
        )

        if response.status_code != 200:
            raise Exception(f"Failed to list resources: {response.text}")

        result = response.json()
        resources = []

        for item in result.get("data", []):
            resource = Resource(
                uri=f"rag://dataset/{item.get('id')}",
                title=item.get("name", ""),
                description=item.get("description", ""),
            )
            resources.append(resource)

        return resources
