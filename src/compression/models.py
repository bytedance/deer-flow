# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Pydantic models for tool result compression system."""

from typing import List

from pydantic import BaseModel, Field


class ToolResultCompression(BaseModel):
    """
    Compressed representation of a tool result.

    This model represents the output of the compression LLM, containing
    a structured summary of the raw tool output.
    """

    summary_title: str = Field(
        ...,
        description=(
            "5-12 words, human-readable title describing the semantic "
            "content of the result"
        ),
        min_length=5,
        max_length=100,
    )

    summary: str = Field(
        ...,
        description=(
            "3-10 sentences, strictly relevant to the current research step. "
            "No speculation or filler."
        ),
        min_length=50,
        max_length=1000,
    )

    extraction: List[str] = Field(
        default_factory=list,
        description=(
            "Key factual bullets. May be empty. Each item should be "
            "independently useful."
        ),
    )

    is_useful: bool = Field(
        ...,
        description=(
            "True if the tool output contains any relevant or actionable "
            "information. False if the output is irrelevant, empty, or pure noise."
        ),
    )


class ArtifactMetadata(BaseModel):
    """
    Metadata for a compressed tool result artifact.

    This is injected into the conversation context when is_useful == true.
    """

    summary_title: str = Field(..., description="Short title of the compressed result")
    summary: str = Field(..., description="Compressed summary of the tool output")
    extraction: List[str] = Field(
        default_factory=list, description="Key factual bullets extracted"
    )
    artifact_file: str = Field(..., description="Filename where raw output is stored")


class CompressionInput(BaseModel):
    """
    Input to the compression LLM (out of band, not injected into context).

    These inputs are used only to guide compression.
    """

    plan_title: str = Field(..., description="Title of the research plan")
    step_id: str = Field(..., description="ID of the current step")
    step_title: str = Field(..., description="Title of the current step")
    step_description: str = Field(..., description="Description of the current step")
    tool_name: str = Field(..., description="Name of the tool that was called")
    raw_output: str = Field(..., description="Raw output from the tool")
