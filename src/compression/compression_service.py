# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""LLM-based compression service for tool results."""

import json
import logging
from typing import Optional

from jinja2 import Template
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

from src.compression.artifact_storage import ArtifactStorageManager
from src.compression.models import (
    ArtifactMetadata,
    CompressionInput,
    ToolResultCompression,
)
from src.prompts.template import get_prompt_template

logger = logging.getLogger(__name__)


# Simple template for rendering the compression prompt
COMPRESSION_TEMPLATE = Template("""# Tool Result Compression

You are a compression specialist. Your task is to analyze tool outputs and produce structured, concise summaries that capture only the most relevant information for the current research step.

## Context

- **Research Plan**: {{ plan_title }}
- **Current Step**: {{ step_title }} (Step {{ step_id }})
- **Step Description**: {{ step_description }}
- **Tool Used**: {{ tool_name }}

## Your Task

Analyze the tool output below and produce a structured compression following the exact schema provided.

## Important Rules

1. **summary_title**: 5-12 words, human-readable title describing the semantic content
2. **summary**: 3-10 sentences, strictly relevant to the current research step, no speculation
3. **extraction**: Key factual bullets (may be empty if no discrete facts exist)
4. **is_useful**: Set to `false` if the output is irrelevant, empty, error-only, or pure noise

## Guidelines

- Be concise and factual
- Focus on information directly relevant to the current step description
- Ignore generic messages, boilerplate text, and irrelevant metadata
- If the tool failed or returned no useful data, set `is_useful: false`
- Extract only actionable facts that would be useful for the LLM's reasoning

## Tool Output

```
{{ raw_output }}
```

## Output Schema

Return ONLY valid JSON matching this exact structure:

```json
{
  "summary_title": "string (5-12 words)",
  "summary": "string (3-10 sentences)",
  "extraction": [
    "bullet point 1",
    "bullet point 2"
  ],
  "is_useful": true
}
```

Do not include any explanations or text outside the JSON.
""")


class CompressionService:
    """
    Service for compressing tool results using an LLM.

    This service orchestrates the compression pipeline:
    1. Invokes an LLM with the tool output and context
    2. Parses the structured compression response
    3. Stores the raw output and compression metadata via ArtifactStorageManager
    4. Returns the compressed result for conversation injection
    """

    def __init__(
        self,
        llm: BaseChatModel,
        storage_manager: Optional[ArtifactStorageManager] = None,
        enabled: bool = True,
    ):
        """
        Initialize the compression service.

        Args:
            llm: The LLM to use for compression (should be a fast, cost-effective model)
            storage_manager: Optional artifact storage manager. Defaults to a new instance.
            enabled: Whether compression is enabled. Can be toggled dynamically.
        """
        self.llm = llm
        self.storage_manager = storage_manager or ArtifactStorageManager()
        self.enabled = enabled

    async def compress_tool_result(
        self,
        input_data: CompressionInput,
    ) -> Optional[ArtifactMetadata]:
        """
        Compress a tool result and save the raw output to disk.

        This is the main entry point for the compression pipeline.

        Args:
            input_data: The compression input containing context and raw output

        Returns:
            ArtifactMetadata if is_useful == true (for injection into conversation)
            None if is_useful == false or compression is disabled

        Raises:
            json.JSONDecodeError: If the LLM returns invalid JSON
            ValueError: If the compression result fails validation
        """
        if not self.enabled:
            logger.debug("Compression is disabled, skipping compression pipeline")
            return None

        # Step 1: Save raw output to disk (always runs, even if compression fails)
        artifact_file = self.storage_manager.save_raw_output(
            input_data=input_data,
            raw_output=input_data.raw_output,
        )
        logger.info(f"Saved raw tool output to: {artifact_file}")

        # Step 2: Invoke LLM for compression
        try:
            compression = await self._invoke_compression_llm(input_data)
        except Exception as e:
            logger.error(f"Compression LLM invocation failed: {e}")
            # On compression failure, we still saved the raw output
            # Return None to skip injection but preserve the artifact
            return None

        # Step 3: Save compression metadata
        self.storage_manager.save_compression_metadata(
            input_data=input_data,
            compression=compression,
            artifact_file=artifact_file,
        )

        # Step 4: Return metadata for injection only if useful
        if compression.is_useful:
            return ArtifactMetadata(
                summary_title=compression.summary_title,
                summary=compression.summary,
                extraction=compression.extraction,
                artifact_file=artifact_file,
            )
        else:
            logger.info(f"Tool result marked as not useful, skipping conversation injection")
            return None

    async def _invoke_compression_llm(
        self,
        input_data: CompressionInput,
    ) -> ToolResultCompression:
        """
        Invoke the LLM to compress the tool output.

        Args:
            input_data: The compression input containing context and raw output

        Returns:
            Parsed ToolResultCompression object

        Raises:
            json.JSONDecodeError: If the LLM returns invalid JSON
            ValueError: If the result fails Pydantic validation
        """
        # Render the prompt with input data
        prompt = COMPRESSION_TEMPLATE.render(
            plan_title=input_data.plan_title,
            step_id=input_data.step_id,
            step_title=input_data.step_title,
            step_description=input_data.step_description,
            tool_name=input_data.tool_name,
            raw_output=input_data.raw_output[:50000],  # Truncate very large outputs
        )

        # Prepare messages
        messages = [
            SystemMessage(content="You are a compression specialist. Always respond with valid JSON."),
            HumanMessage(content=prompt),
        ]

        # Invoke LLM
        logger.debug(f"Invoking compression LLM for tool: {input_data.tool_name}")
        response = await self.llm.ainvoke(messages)

        # Parse response
        content = response.content

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Parse JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse compression LLM response as JSON: {content[:500]}")
            raise ValueError(f"Compression LLM returned invalid JSON: {e}")

        # Validate and return
        try:
            return ToolResultCompression.model_validate(parsed)
        except Exception as e:
            logger.error(f"Compression result failed validation: {parsed}")
            raise ValueError(f"Compression result failed validation: {e}")

    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable compression.

        Args:
            enabled: Whether to enable compression
        """
        self.enabled = enabled
        logger.info(f"Compression {'enabled' if enabled else 'disabled'}")
