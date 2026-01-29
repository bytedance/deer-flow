# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pydantic import BaseModel, Field

from src.rag.retriever import Resource


class RAGConfigResponse(BaseModel):
    """Response model for RAG config."""

    provider: str | None = Field(
        None, description="The provider of the RAG, default is ragflow"
    )


class RAGResourceRequest(BaseModel):
    """Request model for RAG resource."""

    query: str | None = Field(
        None, description="The query of the resource need to be searched"
    )


class RAGResourcesResponse(BaseModel):
    """Response model for RAG resources."""

    resources: list[Resource] = Field(..., description="The resources of the RAG")
