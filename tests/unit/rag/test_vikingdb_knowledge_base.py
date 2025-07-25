# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import pytest
import json
import hashlib
import hmac
from unittest.mock import patch, MagicMock
from datetime import datetime
from src.rag.vikingdb_knowledge_base import VikingDBKnowledgeBaseProvider, parse_uri


# Dummy classes to mock dependencies
class MockResource:
    def __init__(self, uri, title="", description=""):
        self.uri = uri
        self.title = title
        self.description = description


class MockChunk:
    def __init__(self, content, similarity):
        self.content = content
        self.similarity = similarity


class MockDocument:
    def __init__(self, id, title, chunks=None):
        self.id = id
        self.title = title
        self.chunks = chunks or []


# Patch the imports to use mock classes
@pytest.fixture(autouse=True)
def patch_imports():
    with (
        patch("src.rag.vikingdb_knowledge_base.Resource", MockResource),
        patch("src.rag.vikingdb_knowledge_base.Chunk", MockChunk),
        patch("src.rag.vikingdb_knowledge_base.Document", MockDocument),
    ):
        yield


@pytest.fixture
def env_vars():
    """Fixture to set up environment variables"""
    with patch.dict(
        os.environ,
        {
            "VIKINGDB_KNOWLEDGE_BASE_API_URL": "api-test.example.com",
            "VIKINGDB_KNOWLEDGE_BASE_API_AK": "test_ak",
            "VIKINGDB_KNOWLEDGE_BASE_API_SK": "test_sk",
            "VIKINGDB_KNOWLEDGE_BASE_RETRIEVAL_SIZE": "10",
            "VIKINGDB_KNOWLEDGE_BASE_REGION": "cn-north-1",
        },
    ):
        yield


class TestParseUri:
    def test_parse_uri_valid_with_fragment(self):
        """Test parsing valid URI with fragment"""
        uri = "rag://dataset/123#doc456"
        resource_id, document_id = parse_uri(uri)
        assert resource_id == "123"
        assert document_id == "doc456"

    def test_parse_uri_valid_without_fragment(self):
        """Test parsing valid URI without fragment"""
        uri = "rag://dataset/123"
        resource_id, document_id = parse_uri(uri)
        assert resource_id == "123"
        assert document_id == ""

    def test_parse_uri_invalid_scheme(self):
        """Test parsing URI with invalid scheme"""
        with pytest.raises(ValueError, match="Invalid URI"):
            parse_uri("http://dataset/123#abc")

    def test_parse_uri_malformed(self):
        """Test parsing malformed URI"""
        with pytest.raises(ValueError, match="Invalid URI"):
            parse_uri("invalid_uri")


class TestVikingDBKnowledgeBaseProviderInit:
    def test_init_success_with_all_env_vars(self, env_vars):
        """Test successful initialization with all environment variables"""
        provider = VikingDBKnowledgeBaseProvider()
        assert provider.api_url == "api-test.example.com"
        assert provider.api_ak == "test_ak"
        assert provider.api_sk == "test_sk"
        assert provider.retrieval_size == 10
        assert provider.region == "cn-north-1"
        assert provider.service == "air"

    def test_init_success_without_retrieval_size(self):
        """Test initialization without VIKINGDB_KNOWLEDGE_BASE_RETRIEVAL_SIZE (should use default)"""
        with patch.dict(
            os.environ,
            {
                "VIKINGDB_KNOWLEDGE_BASE_API_URL": "api-test.example.com",
                "VIKINGDB_KNOWLEDGE_BASE_API_AK": "test_ak",
                "VIKINGDB_KNOWLEDGE_BASE_API_SK": "test_sk",
            },
            clear=True,
        ):
            provider = VikingDBKnowledgeBaseProvider()
            assert provider.retrieval_size == 10

    def test_init_custom_retrieval_size(self):
        """Test initialization with custom retrieval size"""
        with patch.dict(
            os.environ,
            {
                "VIKINGDB_KNOWLEDGE_BASE_API_URL": "api-test.example.com",
                "VIKINGDB_KNOWLEDGE_BASE_API_AK": "test_ak",
                "VIKINGDB_KNOWLEDGE_BASE_API_SK": "test_sk",
                "VIKINGDB_KNOWLEDGE_BASE_RETRIEVAL_SIZE": "5",
            },
        ):
            provider = VikingDBKnowledgeBaseProvider()
            assert provider.retrieval_size == 5

    def test_init_custom_region(self):
        """Test initialization with custom region"""
        with patch.dict(
            os.environ,
            {
                "VIKINGDB_KNOWLEDGE_BASE_API_URL": "api-test.example.com",
                "VIKINGDB_KNOWLEDGE_BASE_API_AK": "test_ak",
                "VIKINGDB_KNOWLEDGE_BASE_API_SK": "test_sk",
                "VIKINGDB_KNOWLEDGE_BASE_REGION": "us-east-1",
            },
        ):
            provider = VikingDBKnowledgeBaseProvider()
            assert provider.region == "us-east-1"

    def test_init_missing_api_url(self):
        """Test initialization fails when API URL is missing"""
        with patch.dict(
            os.environ,
            {
                "VIKINGDB_KNOWLEDGE_BASE_API_AK": "test_ak",
                "VIKINGDB_KNOWLEDGE_BASE_API_SK": "test_sk",
            },
            clear=True,
        ):
            with pytest.raises(
                ValueError, match="VIKINGDB_KNOWLEDGE_BASE_API_URL is not set"
            ):
                VikingDBKnowledgeBaseProvider()

    def test_init_missing_api_ak(self):
        """Test initialization fails when API AK is missing"""
        with patch.dict(
            os.environ,
            {
                "VIKINGDB_KNOWLEDGE_BASE_API_URL": "api-test.example.com",
                "VIKINGDB_KNOWLEDGE_BASE_API_SK": "test_sk",
            },
            clear=True,
        ):
            with pytest.raises(
                ValueError, match="VIKINGDB_KNOWLEDGE_BASE_API_AK is not set"
            ):
                VikingDBKnowledgeBaseProvider()

    def test_init_missing_api_sk(self):
        """Test initialization fails when API SK is missing"""
        with patch.dict(
            os.environ,
            {
                "VIKINGDB_KNOWLEDGE_BASE_API_URL": "api-test.example.com",
                "VIKINGDB_KNOWLEDGE_BASE_API_AK": "test_ak",
            },
            clear=True,
        ):
            with pytest.raises(
                ValueError, match="VIKINGDB_KNOWLEDGE_BASE_API_SK is not set"
            ):
                VikingDBKnowledgeBaseProvider()


class TestVikingDBKnowledgeBaseProviderSignature:
    @pytest.fixture
    def provider(self, env_vars):
        return VikingDBKnowledgeBaseProvider()

    def test_hmac_sha256(self, provider):
        """Test HMAC SHA256 calculation"""
        key = b"test_key"
        content = "test_content"
        result = provider._hmac_sha256(key, content)
        expected = hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()
        assert result == expected

    def test_hash_sha256(self, provider):
        """Test SHA256 hash calculation"""
        data = b"test_data"
        result = provider._hash_sha256(data)
        expected = hashlib.sha256(data).digest()
        assert result == expected

    def test_get_signed_key(self, provider):
        """Test signed key generation"""
        secret_key = "test_secret"
        date = "20250722"
        region = "cn-north-1"
        service = "air"

        result = provider._get_signed_key(secret_key, date, region, service)
        assert isinstance(result, bytes)
        assert len(result) == 32  # SHA256 digest is 32 bytes

    def test_create_canonical_request(self, provider):
        """Test canonical request creation"""
        method = "POST"
        path = "/api/test"
        query_params = {"param1": "value1", "param2": "value2"}
        headers = {"Content-Type": "application/json", "Host": "example.com"}
        payload = b'{"test": "data"}'

        canonical_request, signed_headers = provider._create_canonical_request(
            method, path, query_params, headers, payload
        )

        assert "POST" in canonical_request
        assert "/api/test" in canonical_request
        assert "param1=value1&param2=value2" in canonical_request
        assert "content-type:application/json" in canonical_request
        assert "host:example.com" in canonical_request
        assert signed_headers == "content-type;host"

    @patch("src.rag.vikingdb_knowledge_base.datetime")
    def test_create_signature(self, mock_datetime, provider):
        """Test signature creation"""
        # Mock datetime
        mock_now = datetime(2025, 7, 22, 10, 30, 45)
        mock_datetime.utcnow.return_value = mock_now

        method = "POST"
        path = "/api/test"
        query_params = {}
        headers = {}
        payload = b'{"test": "data"}'

        result = provider._create_signature(
            method, path, query_params, headers, payload
        )

        assert "X-Date" in result
        assert "Host" in result
        assert "X-Content-Sha256" in result
        assert "Content-Type" in result
        assert "Authorization" in result
        assert "HMAC-SHA256" in result["Authorization"]

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_make_signed_request_success(self, mock_request, provider):
        """Test successful signed request"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {}}
        mock_request.return_value = mock_response

        result = provider._make_signed_request(
            "POST", "/api/test", data={"test": "data"}
        )

        assert result == mock_response
        mock_request.assert_called_once()

        # Verify the call arguments
        call_args = mock_request.call_args
        assert call_args[1]["method"] == "POST"
        assert call_args[1]["url"] == f"https://{provider.api_url}/api/test"
        assert call_args[1]["timeout"] == 30

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_make_signed_request_with_exception(self, mock_request, provider):
        """Test signed request with exception"""
        mock_request.side_effect = Exception("Network error")

        with pytest.raises(ValueError, match="Request failed: Network error"):
            provider._make_signed_request("GET", "/api/test")


class TestVikingDBKnowledgeBaseProviderQueryRelevantDocuments:
    @pytest.fixture
    def provider(self, env_vars):
        return VikingDBKnowledgeBaseProvider()

    def test_query_relevant_documents_empty_resources(self, provider):
        """Test querying with empty resources list"""
        result = provider.query_relevant_documents("test query", [])
        assert result == []

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_query_relevant_documents_success(self, mock_request, provider):
        """Test successful document query"""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "result_list": [
                    {
                        "doc_info": {
                            "doc_id": "doc123",
                            "doc_name": "Test Document",
                        },
                        "content": "Test content",
                        "score": 0.95,
                    }
                ]
            },
        }
        mock_request.return_value = mock_response

        resources = [MockResource("rag://dataset/123")]
        result = provider.query_relevant_documents("test query", resources)

        assert len(result) == 1
        assert result[0].id == "doc123"
        assert result[0].title == "Test Document"
        assert len(result[0].chunks) == 1
        assert result[0].chunks[0].content == "Test content"
        assert result[0].chunks[0].similarity == 0.95

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_query_relevant_documents_with_document_filter(
        self, mock_request, provider
    ):
        """Test document query with document ID filter"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"result_list": []}}
        mock_request.return_value = mock_response

        resources = [MockResource("rag://dataset/123#doc456")]
        provider.query_relevant_documents("test query", resources)

        # Verify that query_param with doc_filter was included in the request
        call_args = mock_request.call_args
        request_data = call_args[1]["data"]
        assert "query_param" in request_data
        assert "doc_filter" in request_data["query_param"]

        doc_filter = request_data["query_param"]["doc_filter"]
        assert doc_filter["op"] == "must"
        assert doc_filter["field"] == "doc_id"
        assert doc_filter["conds"] == ["doc456"]

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_query_relevant_documents_api_error(self, mock_request, provider):
        """Test handling of API error response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 1, "message": "API Error"}
        mock_request.return_value = mock_response

        resources = [MockResource("rag://dataset/123")]
        with pytest.raises(
            ValueError, match="Failed to query documents from resource: API Error"
        ):
            provider.query_relevant_documents("test query", resources)

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_query_relevant_documents_json_decode_error(self, mock_request, provider):
        """Test handling of JSON decode error"""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_request.return_value = mock_response

        resources = [MockResource("rag://dataset/123")]
        with pytest.raises(ValueError, match="Failed to parse JSON response"):
            provider.query_relevant_documents("test query", resources)

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_query_relevant_documents_multiple_resources(self, mock_request, provider):
        """Test querying multiple resources and merging results"""
        # Mock responses for different resources
        responses = [
            {
                "code": 0,
                "data": {
                    "result_list": [
                        {
                            "doc_info": {
                                "doc_id": "doc1",
                                "doc_name": "Document 1",
                            },
                            "content": "Content 1",
                            "score": 0.9,
                        }
                    ]
                },
            },
            {
                "code": 0,
                "data": {
                    "result_list": [
                        {
                            "doc_info": {
                                "doc_id": "doc1",
                                "doc_name": "Document 1",
                            },
                            "content": "Content 2",
                            "score": 0.8,
                        },
                        {
                            "doc_info": {
                                "doc_id": "doc2",
                                "doc_name": "Document 2",
                            },
                            "content": "Content 3",
                            "score": 0.7,
                        },
                    ]
                },
            },
        ]

        mock_responses = [MagicMock() for _ in responses]
        for i, resp in enumerate(responses):
            mock_responses[i].json.return_value = resp
        mock_request.side_effect = mock_responses

        resources = [
            MockResource("rag://dataset/123"),
            MockResource("rag://dataset/456"),
        ]
        result = provider.query_relevant_documents("test query", resources)

        # Should have 2 documents: doc1 (with 2 chunks) and doc2 (with 1 chunk)
        assert len(result) == 2
        doc1 = next(doc for doc in result if doc.id == "doc1")
        doc2 = next(doc for doc in result if doc.id == "doc2")
        assert len(doc1.chunks) == 2
        assert len(doc2.chunks) == 1


class TestVikingDBKnowledgeBaseProviderListResources:
    @pytest.fixture
    def provider(self, env_vars):
        return VikingDBKnowledgeBaseProvider()

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_list_resources_success(self, mock_request, provider):
        """Test successful resource listing"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "collection_list": [
                    {
                        "resource_id": "123",
                        "collection_name": "Dataset 1",
                        "description": "Description 1",
                    },
                    {
                        "resource_id": "456",
                        "collection_name": "Dataset 2",
                        "description": "Description 2",
                    },
                ]
            },
        }
        mock_request.return_value = mock_response

        result = provider.list_resources()

        assert len(result) == 2
        assert result[0].uri == "rag://dataset/123"
        assert result[0].title == "Dataset 1"
        assert result[0].description == "Description 1"
        assert result[1].uri == "rag://dataset/456"
        assert result[1].title == "Dataset 2"
        assert result[1].description == "Description 2"

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_list_resources_with_query_filter(self, mock_request, provider):
        """Test resource listing with query filter"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {
                "collection_list": [
                    {
                        "resource_id": "123",
                        "collection_name": "Test Dataset",
                        "description": "Description",
                    },
                    {
                        "resource_id": "456",
                        "collection_name": "Other Dataset",
                        "description": "Description",
                    },
                ]
            },
        }
        mock_request.return_value = mock_response

        result = provider.list_resources("test")

        # Should only return the dataset with "test" in the name
        assert len(result) == 1
        assert result[0].title == "Test Dataset"

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_list_resources_api_error(self, mock_request, provider):
        """Test handling of API error in list_resources"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 1, "message": "API Error"}
        mock_request.return_value = mock_response

        with pytest.raises(Exception, match="Failed to list resources: API Error"):
            provider.list_resources()

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_list_resources_json_decode_error(self, mock_request, provider):
        """Test handling of JSON decode error in list_resources"""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_request.return_value = mock_response

        with pytest.raises(ValueError, match="Failed to parse JSON response"):
            provider.list_resources()

    @patch.object(VikingDBKnowledgeBaseProvider, "_make_signed_request")
    def test_list_resources_empty_response(self, mock_request, provider):
        """Test handling of empty response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"collection_list": []}}
        mock_request.return_value = mock_response

        result = provider.list_resources()
        assert result == []
