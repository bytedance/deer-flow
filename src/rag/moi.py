# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from urllib.parse import urlparse

import requests

from src.rag.retriever import Chunk, Document, Resource, Retriever


class MOIProvider(Retriever):
    """
    MatrixOne Intelligence (MOI) is a multimodal data AI processing platform. 
    It supports connecting, processing, managing, and using both structured and unstructured data. 
    Through steps such as parsing, extraction, segmentation, cleaning, and enhancement, 
    it transforms raw data like documents, images, and audio/video into AI-ready application data. 
    With its self-developed data service layer (the MatrixOne database), 
    it can directly provide retrieval services for the processed data.

    The open-source repository is available at: https://github.com/matrixorigin/matrixone
    For more information, please visit the website: https://www.matrixorigin.io/matrixone-intelligence
    Documentation: https://docs.matrixorigin.cn/zh/m1intelligence/MatrixOne-Intelligence/Workspace-Mgmt/overview/
    Online Demo: https://www.matrixorigin.io/demo
    """

    def __init__(self):
        # Initialize MOI API configuration from environment variables
        self.api_url = os.getenv("MOI_API_URL")
        if not self.api_url:
            raise ValueError("MOI_API_URL is not set")
        
        # Add /byoa suffix to the API URL for MOI compatibility
        if not self.api_url.endswith("/byoa"):
            self.api_url = self.api_url + "/byoa"
        
        self.api_key = os.getenv("MOI_API_KEY")
        if not self.api_key:
            raise ValueError("MOI_API_KEY is not set")
        
        # Set page size for document retrieval
        self.page_size = 10
        moi_size = os.getenv("MOI_RETRIEVAL_SIZE")
        if moi_size:
            self.page_size = int(moi_size)
        
        # Set MOI-specific list limit parameter
        self.moi_list_limit = None
        moi_list_limit = os.getenv("MOI_LIST_LIMIT")
        if moi_list_limit:
            self.moi_list_limit = int(moi_list_limit)

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        """
        Query relevant documents from MOI API using the provided resources.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        dataset_ids: list[str] = []
        document_ids: list[str] = []

        for resource in resources:
            dataset_id, document_id = self._parse_uri(resource.uri)
            dataset_ids.append(dataset_id)
            if document_id:
                document_ids.append(document_id)

        payload = {
            "question": query,
            "dataset_ids": dataset_ids,
            "document_ids": document_ids,
            "page_size": self.page_size,
        }

        response = requests.post(
            f"{self.api_url}/api/v1/retrieval", headers=headers, json=payload
        )

        if response.status_code != 200:
            raise Exception(f"Failed to query documents: {response.text}")

        result = response.json()
        data = result.get("data", {})
        doc_aggs = data.get("doc_aggs", [])
        docs: dict[str, Document] = {
            doc.get("doc_id"): Document(
                id=doc.get("doc_id"),
                title=doc.get("doc_name"),
                chunks=[],
            )
            for doc in doc_aggs
        }

        for chunk in data.get("chunks", []):
            doc = docs.get(chunk.get("document_id"))
            if doc:
                doc.chunks.append(
                    Chunk(
                        content=chunk.get("content"),
                        similarity=chunk.get("similarity"),
                    )
                )

        return list(docs.values())

    def list_resources(self, query: str | None = None) -> list[Resource]:
        """
        List resources from MOI API with optional query filtering and limit support.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        params = {}
        if query:
            params["name"] = query
        
        if self.moi_list_limit:
            params["limit"] = self.moi_list_limit

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

    def _parse_uri(self, uri: str) -> tuple[str, str]:
        """
        Parse URI to extract dataset ID and document ID.
        """
        parsed = urlparse(uri)
        if parsed.scheme != "rag":
            raise ValueError(f"Invalid URI: {uri}")
        return parsed.path.split("/")[1], parsed.fragment
