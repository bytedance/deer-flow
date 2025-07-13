# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import pytest
import json
from unittest.mock import patch, MagicMock
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


class TestVikingDBKnowledgeBaseProviderPrepareRequest:
    @pytest.fixture
    def provider(self, env_vars):
        return VikingDBKnowledgeBaseProvider()

    def test_prepare_request_basic(self, provider):
        """Test basic request preparation"""
        with (
            patch("src.rag.vikingdb_knowledge_base.Request") as mock_request,
            patch("src.rag.vikingdb_knowledge_base.Credentials") as _mock_credentials,
            patch("src.rag.vikingdb_knowledge_base.SignerV4.sign") as _mock_sign,
        ):

            mock_req_instance = MagicMock()
            mock_request.return_value = mock_req_instance

            result = provider.prepare_request("POST", "/test/path")

            assert result == mock_req_instance
            mock_req_instance.set_shema.assert_called_once_with("https")
            mock_req_instance.set_method.assert_called_once_with("POST")
            mock_req_instance.set_path.assert_called_once_with("/test/path")

    def test_prepare_request_with_params(self, provider):
        """Test request preparation with parameters"""
        with (
            patch("src.rag.vikingdb_knowledge_base.Request") as mock_request,
            patch("src.rag.vikingdb_knowledge_base.Credentials"),
            patch("src.rag.vikingdb_knowledge_base.SignerV4.sign"),
        ):

            mock_req_instance = MagicMock()
            mock_request.return_value = mock_req_instance

            params = {"key": "value", "number": 123, "boolean": True}
            provider.prepare_request("GET", "/test", params=params)

            expected_params = {"key": "value", "number": "123", "boolean": "True"}
            mock_req_instance.set_query.assert_called_once_with(expected_params)

    def test_prepare_request_with_data(self, provider):
        """Test request preparation with data"""
        with (
            patch("src.rag.vikingdb_knowledge_base.Request") as mock_request,
            patch("src.rag.vikingdb_knowledge_base.Credentials"),
            patch("src.rag.vikingdb_knowledge_base.SignerV4.sign"),
        ):

            mock_req_instance = MagicMock()
            mock_request.return_value = mock_req_instance

            data = {"test": "data"}
            provider.prepare_request("POST", "/test", data=data)

            mock_req_instance.set_body.assert_called_once_with(json.dumps(data))


class TestVikingDBKnowledgeBaseProviderQueryRelevantDocuments:
    @pytest.fixture
    def provider(self, env_vars):
        return VikingDBKnowledgeBaseProvider()

    def test_query_relevant_documents_empty_resources(self, provider):
        """Test querying with empty resources list"""
        result = provider.query_relevant_documents("test query", [])
        assert result == []

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_query_relevant_documents_success(self, mock_request, provider):
        """Test successful document query"""
        # Mock response
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
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
        )
        mock_request.return_value = mock_response

        # Mock prepare_request
        with patch.object(provider, "prepare_request") as mock_prepare:
            mock_req = MagicMock()
            mock_req.method = "POST"
            mock_req.path = "/api/knowledge/collection/search_knowledge"
            mock_req.headers = {}
            mock_req.body = "{}"
            mock_prepare.return_value = mock_req

            resources = [MockResource("rag://dataset/123")]
            result = provider.query_relevant_documents("test query", resources)

            assert len(result) == 1
            assert result[0].id == "doc123"
            assert result[0].title == "Test Document"
            assert len(result[0].chunks) == 1
            assert result[0].chunks[0].content == "Test content"
            assert result[0].chunks[0].similarity == 0.95

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_query_relevant_documents_with_document_filter(
        self, mock_request, provider
    ):
        """Test document query with document ID filter"""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"code": 0, "data": {"result_list": []}})
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request") as mock_prepare:
            mock_req = MagicMock()
            mock_prepare.return_value = mock_req

            resources = [MockResource("rag://dataset/123#doc456")]
            provider.query_relevant_documents("test query", resources)

            # Verify that query_param with doc_filter was included in the request
            call_args = mock_prepare.call_args
            request_data = call_args[1]["data"]
            assert "query_param" in request_data
            assert "doc_filter" in request_data["query_param"]

            doc_filter = request_data["query_param"]["doc_filter"]
            assert doc_filter["op"] == "must"
            assert doc_filter["field"] == "doc_id"
            assert doc_filter["conds"] == ["doc456"]

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_query_relevant_documents_api_error(self, mock_request, provider):
        """Test handling of API error response"""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"code": 1, "message": "API Error"})
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request"):
            resources = [MockResource("rag://dataset/123")]
            with pytest.raises(
                ValueError, match="Failed to query documents from resource: API Error"
            ):
                provider.query_relevant_documents("test query", resources)

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_query_relevant_documents_json_decode_error(self, mock_request, provider):
        """Test handling of JSON decode error"""
        mock_response = MagicMock()
        mock_response.text = "invalid json"
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request"):
            resources = [MockResource("rag://dataset/123")]
            with pytest.raises(ValueError, match="Failed to parse JSON response"):
                provider.query_relevant_documents("test query", resources)

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_query_relevant_documents_multiple_resources(self, mock_request, provider):
        """Test querying multiple resources and merging results"""
        # Mock responses for different resources
        responses = [
            json.dumps(
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
                }
            ),
            json.dumps(
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
                }
            ),
        ]

        mock_request.side_effect = [MagicMock(text=resp) for resp in responses]

        with patch.object(provider, "prepare_request"):
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

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_list_resources_success(self, mock_request, provider):
        """Test successful resource listing"""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
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
        )
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request") as mock_prepare:
            mock_req = MagicMock()
            mock_prepare.return_value = mock_req

            result = provider.list_resources()

            assert len(result) == 2
            assert result[0].uri == "rag://dataset/123"
            assert result[0].title == "Dataset 1"
            assert result[0].description == "Description 1"
            assert result[1].uri == "rag://dataset/456"
            assert result[1].title == "Dataset 2"
            assert result[1].description == "Description 2"

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_list_resources_with_query_filter(self, mock_request, provider):
        """Test resource listing with query filter"""
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
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
        )
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request"):
            result = provider.list_resources("test")

            # Should only return the dataset with "test" in the name
            assert len(result) == 1
            assert result[0].title == "Test Dataset"

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_list_resources_api_error(self, mock_request, provider):
        """Test handling of API error in list_resources"""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"code": 1, "message": "API Error"})
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request"):
            with pytest.raises(Exception, match="Failed to list resources: API Error"):
                provider.list_resources()

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_list_resources_json_decode_error(self, mock_request, provider):
        """Test handling of JSON decode error in list_resources"""
        mock_response = MagicMock()
        mock_response.text = "invalid json"
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request"):
            with pytest.raises(ValueError, match="Failed to parse JSON response"):
                provider.list_resources()

    @patch("src.rag.vikingdb_knowledge_base.requests.request")
    def test_list_resources_empty_response(self, mock_request, provider):
        """Test handling of empty response"""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"code": 0, "data": {"collection_list": []}})
        mock_request.return_value = mock_response

        with patch.object(provider, "prepare_request"):
            result = provider.list_resources()
            assert result == []
