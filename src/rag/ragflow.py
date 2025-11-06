# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from typing import List, Optional
from urllib.parse import urlparse

import requests

from src.rag.retriever import Chunk, Document, Resource, Retriever


class RAGFlowProvider(Retriever):
    """
    RAGFlowProvider is a provider that uses RAGFlow to retrieve documents.
    """

    api_url: str
    api_key: str
    page_size: int = 10
    cross_languages: Optional[List[str]] = None

    def __init__(self):
        api_url = os.getenv("RAGFLOW_API_URL")
        if not api_url:
            raise ValueError("RAGFLOW_API_URL is not set")
        self.api_url = api_url

        api_key = os.getenv("RAGFLOW_API_KEY")
        if not api_key:
            raise ValueError("RAGFLOW_API_KEY is not set")
        self.api_key = api_key

        page_size = os.getenv("RAGFLOW_PAGE_SIZE")
        if page_size:
            self.page_size = int(page_size)

        self.cross_languages = None
        cross_languages = os.getenv("RAGFLOW_CROSS_LANGUAGES")
        if cross_languages:
            self.cross_languages = cross_languages.split(",")

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        dataset_ids: list[str] = []
        document_ids: list[str] = []

        for resource in resources:
            dataset_id, document_id = parse_uri(resource.uri)
            dataset_ids.append(dataset_id)
            if document_id:
                document_ids.append(document_id)

        payload = {
            "question": query,
            "dataset_ids": dataset_ids,
            "document_ids": document_ids,
            "page_size": self.page_size,
        }

        if self.cross_languages:
            payload["cross_languages"] = self.cross_languages

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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        params = {}
        if query:
            params["name"] = query

        response = requests.get(
            f"{self.api_url}/api/v1/datasets", headers=headers, params=params
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

    def upload_document(
        self,
        file_content: bytes,
        file_name: str,
        dataset_name: str | None = None,
        dataset_id: str | None = None,
    ) -> Resource:
        """
        Upload a document to RAGFlow.
        If dataset_name is provided, create a new dataset.
        If dataset_id is provided, upload to existing dataset.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        # If creating new dataset
        if dataset_name:
            # Create dataset first
            create_response = requests.post(
                f"{self.api_url}/api/v1/datasets",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"name": dataset_name},
            )

            if create_response.status_code not in [200, 201]:
                raise Exception(
                    f"Failed to create dataset: {create_response.text}"
                )

            create_result = create_response.json()
            dataset_id = create_result.get("data", {}).get("id")
            if not dataset_id:
                raise Exception("Failed to get dataset ID from response")

        if not dataset_id:
            raise ValueError("Either dataset_name or dataset_id must be provided")

        # Upload document
        files = {"file": (file_name, file_content)}
        data = {"dataset_id": dataset_id}

        upload_response = requests.post(
            f"{self.api_url}/api/v1/documents",
            headers=headers,
            files=files,
            data=data,
        )

        if upload_response.status_code not in [200, 201]:
            raise Exception(f"Failed to upload document: {upload_response.text}")

        upload_result = upload_response.json()
        document_data = upload_result.get("data", {})

        # Return the dataset resource (not the document, as RAGFlow works with datasets)
        return Resource(
            uri=f"rag://dataset/{dataset_id}",
            title=dataset_name or f"Dataset {dataset_id}",
            description=f"Document: {file_name}",
        )


def parse_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "rag":
        raise ValueError(f"Invalid URI: {uri}")
    return parsed.path.split("/")[1], parsed.fragment
