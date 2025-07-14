# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import Mock, patch
from langchain_core.callbacks import (
    CallbackManagerForToolRun,
    AsyncCallbackManagerForToolRun,
)
import pytest
from src.tools.retriever import RetrieverInput, RetrieverTool, get_retriever_tool
from src.rag import Document, Retriever, Resource, Chunk


def test_retriever_input_model():
    input_data = RetrieverInput(keywords="test keywords")
    assert input_data.keywords == "test keywords"


def test_retriever_tool_init():
    mock_retriever = Mock(spec=Retriever)
    resources = [Resource(uri="test://uri", title="Test")]
    tool = RetrieverTool(retriever=mock_retriever, resources=resources)

    assert tool.name == "local_search_tool"
    assert "retrieving information" in tool.description
    assert tool.args_schema == RetrieverInput
    assert tool.retriever == mock_retriever
    assert tool.resources == resources


def test_retriever_tool_run_with_results():
    mock_retriever = Mock(spec=Retriever)
    chunk = Chunk(content="test content", similarity=0.9)
    doc = Document(id="doc1", chunks=[chunk])
    mock_retriever.query_relevant_documents.return_value = [doc]

    resources = [Resource(uri="test://uri", title="Test")]
    tool = RetrieverTool(retriever=mock_retriever, resources=resources)

    result = tool._run("test keywords")

    mock_retriever.query_relevant_documents.assert_called_once_with(
        "test keywords", resources
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == doc.to_dict()


def test_retriever_tool_run_no_results():
    mock_retriever = Mock(spec=Retriever)
    mock_retriever.query_relevant_documents.return_value = []

    resources = [Resource(uri="test://uri", title="Test")]
    tool = RetrieverTool(retriever=mock_retriever, resources=resources)

    result = tool._run("test keywords")

    assert result == "No results found from the local knowledge base."


@pytest.mark.asyncio
async def test_retriever_tool_arun():
    mock_retriever = Mock(spec=Retriever)
    chunk = Chunk(content="async content", similarity=0.8)
    doc = Document(id="doc2", chunks=[chunk])
    mock_retriever.query_relevant_documents.return_value = [doc]

    resources = [Resource(uri="test://uri", title="Test")]
    tool = RetrieverTool(retriever=mock_retriever, resources=resources)

    mock_run_manager = Mock(spec=AsyncCallbackManagerForToolRun)
    mock_sync_manager = Mock(spec=CallbackManagerForToolRun)
    mock_run_manager.get_sync.return_value = mock_sync_manager

    result = await tool._arun("async keywords", mock_run_manager)

    mock_run_manager.get_sync.assert_called_once()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == doc.to_dict()


@patch("src.tools.retriever.build_retriever")
def test_get_retriever_tool_success(mock_build_retriever):
    mock_retriever = Mock(spec=Retriever)
    mock_build_retriever.return_value = mock_retriever

    resources = [Resource(uri="test://uri", title="Test")]
    tool = get_retriever_tool(resources)

    assert isinstance(tool, RetrieverTool)
    assert tool.retriever == mock_retriever
    assert tool.resources == resources


def test_get_retriever_tool_empty_resources():
    result = get_retriever_tool([])
    assert result is None


@patch("src.tools.retriever.build_retriever")
def test_get_retriever_tool_no_retriever(mock_build_retriever):
    mock_build_retriever.return_value = None

    resources = [Resource(uri="test://uri", title="Test")]
    result = get_retriever_tool(resources)

    assert result is None


def test_retriever_tool_run_with_callback_manager():
    mock_retriever = Mock(spec=Retriever)
    mock_retriever.query_relevant_documents.return_value = []

    resources = [Resource(uri="test://uri", title="Test")]
    tool = RetrieverTool(retriever=mock_retriever, resources=resources)

    mock_callback_manager = Mock(spec=CallbackManagerForToolRun)
    result = tool._run("test keywords", mock_callback_manager)

    assert result == "No results found from the local knowledge base."
