# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from urllib.parse import urlparse

import requests

from src.rag.retriever import Chunk, Document, Resource, Retriever


class DifyProvider(Retriever):
    """
    DifyProvider is a provider that uses dify to retrieve documents.
    """

    api_url: str
    api_key: str
    web_url: str

    def __init__(self):
        api_url = os.getenv("DIFY_API_URL")
        if not api_url:
            raise ValueError("DIFY_API_URL is not set")
        self.api_url = api_url

        api_key = os.getenv("DIFY_API_KEY")
        if not api_key:
            raise ValueError("DIFY_API_KEY is not set")
        self.api_key = api_key

        # 获取Web UI URL，如果未设置则从API URL推导
        web_url = os.getenv("DIFY_WEB_URL")
        if web_url:
            self.web_url = web_url.rstrip("/")
        else:
            # 从API URL推导Web UI URL：移除/v1路径
            parsed = urlparse(api_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            self.web_url = base_url

    def _get_document_url(self, dataset_id: str, doc_id: str) -> str:
        """
        构建指向Dify Web UI的文档URL
        """
        return f"{self.web_url}/datasets/{dataset_id}/documents/{doc_id}"

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        if not resources:
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        all_documents = {}
        for resource in resources:
            dataset_id, _ = parse_uri(resource.uri)
            payload = {
                "query": query,
                "retrieval_model": {
                    "search_method": "hybrid_search",
                    "reranking_enable": False,
                    "weights": {
                        "weight_type": "customized",
                        "keyword_setting": {"keyword_weight": 0.3},
                        "vector_setting": {"vector_weight": 0.7},
                    },
                    "top_k": 3,
                    "score_threshold_enabled": True,
                    "score_threshold": 0.5,
                },
            }

            response = requests.post(
                f"{self.api_url}/datasets/{dataset_id}/retrieve",
                headers=headers,
                json=payload,
            )

            if response.status_code != 200:
                raise Exception(f"Failed to query documents: {response.text}")

            result = response.json()
            records = result.get("records", {})
            for record in records:
                segment = record.get("segment")
                if not segment:
                    continue
                document_info = segment.get("document")
                if not document_info:
                    continue
                doc_id = document_info.get("id")
                doc_name = document_info.get("name")
                if not doc_id or not doc_name:
                    continue

                if doc_id not in all_documents:
                    # 构建指向Dify Web UI的文档URL
                    doc_url = self._get_document_url(dataset_id, doc_id)
                    all_documents[doc_id] = Document(
                        id=doc_id, title=doc_name, url=doc_url, chunks=[]
                    )

                chunk = Chunk(
                    content=segment.get("content", ""),
                    similarity=record.get("score", 0.0),
                )
                all_documents[doc_id].chunks.append(chunk)

        return list(all_documents.values())

    def list_resources(self, query: str | None = None) -> list[Resource]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        params = {}
        if query:
            params["keyword"] = query

        response = requests.get(
            f"{self.api_url}/datasets", headers=headers, params=params
        )

        if response.status_code != 200:
            raise Exception(f"Failed to list resources: {response.text}")

        result = response.json()
        resources = []

        for item in result.get("data", []):
            item = Resource(
                uri=f"rag://dataset/{item.get('id')}",
                title=item.get("name", ""),
                description=item.get("description", ""),
            )
            resources.append(item)

        return resources


def parse_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "rag":
        raise ValueError(f"Invalid URI: {uri}")
    return parsed.path.split("/")[1], parsed.fragment
