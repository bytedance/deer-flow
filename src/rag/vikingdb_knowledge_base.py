# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import requests
import json
import hashlib
import hmac
import urllib.parse
from datetime import datetime
from src.rag.retriever import Chunk, Document, Resource, Retriever
from urllib.parse import urlparse


class VikingDBKnowledgeBaseProvider(Retriever):
    """
    VikingDBKnowledgeBaseProvider is a provider that uses VikingDB Knowledge base API to retrieve documents.
    """

    api_url: str
    api_ak: str
    api_sk: str
    retrieval_size: int = 10
    region: str = "cn-north-1"
    service: str = "air"

    def __init__(self):
        api_url = os.getenv("VIKINGDB_KNOWLEDGE_BASE_API_URL")
        if not api_url:
            raise ValueError("VIKINGDB_KNOWLEDGE_BASE_API_URL is not set")
        self.api_url = api_url

        api_ak = os.getenv("VIKINGDB_KNOWLEDGE_BASE_API_AK")
        if not api_ak:
            raise ValueError("VIKINGDB_KNOWLEDGE_BASE_API_AK is not set")
        self.api_ak = api_ak

        api_sk = os.getenv("VIKINGDB_KNOWLEDGE_BASE_API_SK")
        if not api_sk:
            raise ValueError("VIKINGDB_KNOWLEDGE_BASE_API_SK is not set")
        self.api_sk = api_sk

        retrieval_size = os.getenv("VIKINGDB_KNOWLEDGE_BASE_RETRIEVAL_SIZE")
        if retrieval_size:
            self.retrieval_size = int(retrieval_size)

        # 设置region，如果需要可以从环境变量获取
        region = os.getenv("VIKINGDB_KNOWLEDGE_BASE_REGION", "cn-north-1")
        self.region = region

    def _hmac_sha256(self, key: bytes, content: str) -> bytes:
        return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()

    def _hash_sha256(self, data: bytes) -> bytes:
        return hashlib.sha256(data).digest()

    def _get_signed_key(
        self, secret_key: str, date: str, region: str, service: str
    ) -> bytes:
        k_date = self._hmac_sha256(secret_key.encode("utf-8"), date)
        k_region = self._hmac_sha256(k_date, region)
        k_service = self._hmac_sha256(k_region, service)
        k_signing = self._hmac_sha256(k_service, "request")
        return k_signing

    def _create_canonical_request(
        self, method: str, path: str, query_params: dict, headers: dict, payload: bytes
    ) -> str:
        canonical_method = method.upper()
        canonical_uri = path if path else "/"
        if query_params:
            encoded_params = []
            for key in sorted(query_params.keys()):
                value = query_params[key]
                encoded_key = urllib.parse.quote(str(key), safe="")
                encoded_value = urllib.parse.quote(str(value), safe="")
                encoded_params.append(f"{encoded_key}={encoded_value}")
            canonical_query_string = "&".join(encoded_params)
        else:
            canonical_query_string = ""

        canonical_headers_list = []
        signed_headers_list = []
        for header_name in sorted(headers.keys(), key=str.lower):
            header_name_lower = header_name.lower()
            header_value = str(headers[header_name]).strip()
            canonical_headers_list.append(f"{header_name_lower}:{header_value}")
            signed_headers_list.append(header_name_lower)

        canonical_headers = "\n".join(canonical_headers_list) + "\n"
        signed_headers = ";".join(signed_headers_list)

        payload_hash = self._hash_sha256(payload).hex()

        canonical_request = "\n".join(
            [
                canonical_method,
                canonical_uri,
                canonical_query_string,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )

        return canonical_request, signed_headers

    def _create_signature(
        self, method: str, path: str, query_params: dict, headers: dict, payload: bytes
    ) -> str:
        now = datetime.utcnow()
        date_stamp = now.strftime("%Y%m%dT%H%M%SZ")
        auth_date = date_stamp[:8]

        headers["X-Date"] = date_stamp
        headers["Host"] = self.api_url.replace("https://", "").replace("http://", "")
        headers["X-Content-Sha256"] = self._hash_sha256(payload).hex()
        headers["Content-Type"] = "application/json"

        canonical_request, signed_headers = self._create_canonical_request(
            method, path, query_params, headers, payload
        )

        algorithm = "HMAC-SHA256"
        credential_scope = f"{auth_date}/{self.region}/{self.service}/request"
        canonical_request_hash = self._hash_sha256(
            canonical_request.encode("utf-8")
        ).hex()

        string_to_sign = "\n".join(
            [algorithm, date_stamp, credential_scope, canonical_request_hash]
        )

        signing_key = self._get_signed_key(
            self.api_sk, auth_date, self.region, self.service
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        authorization = (
            f"{algorithm} "
            f"Credential={self.api_ak}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        headers["Authorization"] = authorization

        return headers

    def _make_signed_request(
        self, method: str, path: str, params: dict = None, data: dict = None
    ):
        if data is None:
            payload = b""
        else:
            payload = json.dumps(data).encode("utf-8")

        if params is None:
            params = {}

        url = f"https://{self.api_url}{path}"
        headers = {}
        signed_headers = self._create_signature(method, path, params, headers, payload)
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=signed_headers,
                params=params,
                data=payload if payload else None,
                timeout=30,
            )
            return response
        except Exception as e:
            raise ValueError(f"Request failed: {e}")

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        """
        Query relevant documents from the knowledge base
        """
        if not resources:
            return []

        all_documents = {}
        for resource in resources:
            resource_id, document_id = parse_uri(resource.uri)
            request_params = {
                "resource_id": resource_id,
                "query": query,
                "limit": self.retrieval_size,
                "dense_weight": 0.5,
                "pre_processing": {
                    "need_instruction": True,
                    "rewrite": False,
                    "return_token_usage": True,
                },
                "post_processing": {
                    "rerank_switch": True,
                    "chunk_diffusion_count": 0,
                    "chunk_group": True,
                    "get_attachment_link": True,
                },
            }
            if document_id:
                doc_filter = {"op": "must", "field": "doc_id", "conds": [document_id]}
                query_param = {"doc_filter": doc_filter}
                request_params["query_param"] = query_param

            path = "/api/knowledge/collection/search_knowledge"

            # 使用新的签名请求方法
            response = self._make_signed_request(
                method="POST", path=path, data=request_params
            )

            try:
                response_data = response.json()
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON response: {e}")

            if response_data["code"] != 0:
                raise ValueError(
                    f"Failed to query documents from resource: {response_data['message']}"
                )

            rsp_data = response_data.get("data", {})

            if "result_list" not in rsp_data:
                continue

            result_list = rsp_data["result_list"]

            for item in result_list:
                doc_info = item.get("doc_info", {})
                doc_id = doc_info.get("doc_id")

                if not doc_id:
                    continue

                if doc_id not in all_documents:
                    all_documents[doc_id] = Document(
                        id=doc_id, title=doc_info.get("doc_name"), chunks=[]
                    )

                chunk = Chunk(
                    content=item.get("content", ""), similarity=item.get("score", 0.0)
                )
                all_documents[doc_id].chunks.append(chunk)

        return list(all_documents.values())

    def list_resources(self, query: str | None = None) -> list[Resource]:
        """
        List resources (knowledge bases) from the knowledge base service
        """
        path = "/api/knowledge/collection/list"

        response = self._make_signed_request(method="POST", path=path)

        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}")

        if response_data["code"] != 0:
            raise Exception(f"Failed to list resources: {response_data['message']}")

        resources = []
        rsp_data = response_data.get("data", {})
        collection_list = rsp_data.get("collection_list", [])
        for item in collection_list:
            collection_name = item.get("collection_name", "")
            description = item.get("description", "")

            if query and query.lower() not in collection_name.lower():
                continue

            resource_id = item.get("resource_id", "")
            resource = Resource(
                uri=f"rag://dataset/{resource_id}",
                title=collection_name,
                description=description,
            )
            resources.append(resource)

        return resources


def parse_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "rag":
        raise ValueError(f"Invalid URI: {uri}")
    return parsed.path.split("/")[1], parsed.fragment
